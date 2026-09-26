# -*- coding: utf-8 -*-
"""网页控制台.

在浏览器中完成：登录 → 选择课程 → 选择要完成的任务 → 查看进度与日志。
只使用 Python 标准库，随程序一起分发，无需额外安装。

安全措施：
- 默认只监听 127.0.0.1；监听其它地址时必须使用访问口令（未设置 CHAOXING_WEB_TOKEN 时自动生成并打印）
- 所有写操作要求自定义请求头（阻止跨站请求伪造），本机模式校验 Host（阻止 DNS 重绑定）
- 密码只用于登录学习通，不写入磁盘；已保存的题库密钥不会回传给页面
"""
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from api.base import SessionManager
from api.config import GlobalConst as gc, resource_path
from api.logger import logger
from api.runner import Runner, format_summary, has_saved_cookies
from api.runtime import runtime
from api.settings import Settings, normalize_common

DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "chaoxing-web"

# 网页上可选择的题库及其需要填写的配置项（secret=True 的值不会回传给页面）
PROVIDER_FORMS = [
    {"id": "TikuGo", "name": "GO题（免费，无需配置）", "fields": [
        {"key": "go_authorization", "label": "Token（可选，用于解除限流）", "secret": True}]},
    {"id": "TikuYanxi", "name": "言溪题库", "fields": [
        {"key": "tokens", "label": "Token（多个用英文逗号分隔）", "secret": True, "required": True}]},
    {"id": "TikuLike", "name": "LIKE 知识库", "fields": [
        {"key": "tokens", "label": "Token（多个用英文逗号分隔）", "secret": True, "required": True}]},
    {"id": "AI", "name": "AI 大模型（OpenAI 兼容接口）", "fields": [
        {"key": "endpoint", "label": "API 地址，例如 https://api.deepseek.com/v1", "required": True},
        {"key": "key", "label": "API Key", "secret": True, "required": True},
        {"key": "model", "label": "模型名称，例如 deepseek-chat", "required": True}]},
    {"id": "SiliconFlow", "name": "硅基流动", "fields": [
        {"key": "siliconflow_key", "label": "API Key", "secret": True, "required": True},
        {"key": "siliconflow_model", "label": "模型名称（默认 deepseek-ai/DeepSeek-V3）"}]},
    {"id": "TikuAdapter", "name": "TikuAdapter（自建题库）", "fields": [
        {"key": "url", "label": "接口地址", "required": True}]},
]
_ALLOWED_TIKU_FIELDS = {f["key"] for p in PROVIDER_FORMS for f in p["fields"]}
_PROVIDER_IDS = {p["id"] for p in PROVIDER_FORMS}


class LogBuffer:
    """保存最近的日志，供页面轮询."""

    def __init__(self, maxlen: int = 3000) -> None:
        """初始化环形缓冲区."""
        self._lines: deque = deque(maxlen=maxlen)
        self._seq = 0
        self._lock = threading.Lock()

    def write(self, message) -> None:
        record = message.record
        text = f"{record['time']:%H:%M:%S} | {record['message']}"
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, record["level"].name, text))

    def since(self, after: int, limit: int = 500) -> dict[str, Any]:
        with self._lock:
            lines = [line for line in self._lines if line[0] > after][-limit:]
            return {"lines": lines, "next": self._seq}


def _is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class WebApp:
    """网页控制台状态（同一时间只服务一个学习通账号）."""

    def __init__(self, settings: Settings, token: Optional[str], local_only: bool) -> None:
        """初始化控制台状态."""
        self.settings = settings
        self.token = token
        self.local_only = local_only
        self.logs = LogBuffer()
        self._lock = threading.Lock()
        self.runner: Optional[Runner] = None
        self.user = ""
        self.courses: list[dict] = []
        self.thread: Optional[threading.Thread] = None
        self.summary: Optional[dict] = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # ------------------------------------------------------------------
    def _defaults(self) -> dict[str, Any]:
        common = self.settings.common
        tiku = self.settings.tiku
        provider = (tiku.get("provider") or "").split(",")[0].strip()
        return {
            "username": common.get("username", ""),
            "has_password": bool(common.get("password")),
            "speed": common.get("speed", 1.0),
            "jobs": common.get("jobs", 4),
            "notopen_action": common.get("notopen_action", "retry") if common.get("notopen_action") != "ask" else "retry",
            "add_learning_count": bool(common.get("add_learning_count")),
            "target_count": common.get("target_count", 100),
            "provider": provider if provider in _PROVIDER_IDS else "TikuGo",
            "work_mode": ("submit" if str(tiku.get("submit", "")).lower() == "true" else "save") if provider else "save",
            # 只告诉页面哪些字段已在配置文件中填写，不回传具体内容
            "configured_fields": sorted(k for k in _ALLOWED_TIKU_FIELDS if tiku.get(k)),
            "course_list": common.get("course_list", []),
        }

    def state(self) -> dict[str, Any]:
        snapshot = runtime.snapshot()
        return {
            "logged_in": bool(self.user or (self.runner and self.runner.chaoxing and self.courses)),
            "user": self.user,
            "running": self.running,
            "stopping": self.running and runtime.should_stop(),
            "stage": snapshot["stage"],
            "counts": snapshot["counts"],
            "items": snapshot["items"],
            "summary": self.summary,
            "error": self.error,
            "has_saved_login": has_saved_cookies(),
            "providers": PROVIDER_FORMS,
            "defaults": self._defaults(),
        }

    def login(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.running:
                return {"ok": False, "msg": "任务正在运行，请先停止"}
            username = str(data.get("username") or "").strip()
            password = str(data.get("password") or "")
            use_cookies = bool(data.get("use_saved_login"))
            if not use_cookies and not username:
                return {"ok": False, "msg": "请输入手机号"}
            if not use_cookies and not password:
                # 允许使用配置文件/环境变量中的密码
                if username == self.settings.common.get("username") and self.settings.common.get("password"):
                    password = self.settings.common["password"]
                else:
                    return {"ok": False, "msg": "请输入密码"}

            runner = Runner(self.settings, interactive=False)
            try:
                result = runner.login(username=username, password=password, use_cookies=use_cookies,
                                      tiku_overrides={"provider": ""})
            except Exception as e:
                logger.error(f"登录出错: {e}")
                return {"ok": False, "msg": f"登录出错: {e}"}
            if not result.get("status"):
                return {"ok": False, "msg": result.get("msg", "登录失败")}
            try:
                courses = runner.list_courses()
            except Exception as e:
                logger.error(f"读取课程列表失败: {e}")
                return {"ok": False, "msg": f"登录成功，但读取课程列表失败: {e}"}
            self.runner = runner
            self.courses = courses
            self.user = runner.chaoxing.get_name() or (username[:3] + "****" + username[-4:] if len(username) >= 7 else username) or "已登录"
            self.summary = None
            self.error = ""
            return {"ok": True, "user": self.user, "courses": self._course_view()}

    def logout(self) -> dict[str, Any]:
        with self._lock:
            if self.running:
                return {"ok": False, "msg": "任务正在运行，请先停止"}
            self.runner = None
            self.courses = []
            self.user = ""
            self.summary = None
            SessionManager.reset()
            try:
                if os.path.exists(gc.COOKIES_PATH):
                    os.remove(gc.COOKIES_PATH)
            except OSError as e:
                logger.warning(f"删除已保存的登录状态失败: {e}")
            return {"ok": True}

    def _course_view(self) -> list[dict[str, str]]:
        return [
            {
                "key": f"{c['courseId']}_{c['clazzId']}",
                "courseId": c["courseId"],
                "clazzId": c["clazzId"],
                "title": c.get("title", ""),
                "teacher": c.get("teacher", ""),
            }
            for c in self.courses
        ]

    def list_courses(self) -> dict[str, Any]:
        if not self.runner:
            return {"ok": False, "msg": "请先登录"}
        return {"ok": True, "courses": self._course_view()}

    @staticmethod
    def _tiku_overrides(data: dict[str, Any]) -> dict[str, Any]:
        work_mode = data.get("work_mode", "save")
        if work_mode not in ("skip", "save", "submit"):
            work_mode = "save"
        if work_mode == "skip":
            return {"provider": ""}
        provider = str(data.get("provider") or "TikuGo")
        if provider not in _PROVIDER_IDS:
            provider = "TikuGo"
        overrides: dict[str, Any] = {"provider": provider, "submit": "true" if work_mode == "submit" else "false"}
        for key, value in (data.get("tiku") or {}).items():
            # 留空表示沿用配置文件中的值
            if key in _ALLOWED_TIKU_FIELDS and str(value).strip():
                overrides[key] = str(value).strip()
        return overrides

    def start(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not self.runner:
                return {"ok": False, "msg": "请先登录"}
            if self.running:
                return {"ok": False, "msg": "任务已经在运行"}
            keys = set(data.get("courses") or [])
            courses = [c for c in self.courses if f"{c['courseId']}_{c['clazzId']}" in keys]
            if not courses:
                return {"ok": False, "msg": "请至少选择一门课程"}
            study = bool(data.get("study", True))
            add_learning_count = bool(data.get("add_learning_count"))
            if not study and not add_learning_count:
                return {"ok": False, "msg": "请至少选择一项任务"}

            options = normalize_common({
                "speed": data.get("speed"),
                "jobs": data.get("jobs"),
                "notopen_action": data.get("notopen_action") if data.get("notopen_action") in ("retry", "continue") else None,
                "target_count": data.get("target_count"),
            })
            options = {k: options[k] for k in ("speed", "jobs", "notopen_action", "target_count")}

            runner = self.runner
            try:
                runner.tiku = runner.build_tiku(self._tiku_overrides(data))
            except Exception as e:
                return {"ok": False, "msg": f"题库配置有误: {e}"}
            runner.chaoxing.tiku = runner.tiku

            runtime.reset()
            self.summary = None
            self.error = ""
            self.thread = threading.Thread(
                target=self._run,
                args=(runner, courses, study, add_learning_count, options),
                name="web-runner",
                daemon=True,
            )
            self.thread.start()
            return {"ok": True}

    def _run(self, runner: Runner, courses: list[dict], study: bool, add_learning_count: bool,
             options: dict[str, Any]) -> None:
        try:
            summary = runner.run(courses, study=study, add_learning_count=add_learning_count,
                                 target_count=options.get("target_count"), options=options)
            self.summary = summary
            report = format_summary(summary)
            logger.info("\n" + report)
            runner.notify(f"chaoxing : 任务结束\n{report}")
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            logger.error(f"运行出错: {self.error}")
            runtime.set_stage("运行出错")
            runner.notify(f"chaoxing : 出现错误 {self.error}")

    def stop(self) -> dict[str, Any]:
        if not self.running:
            return {"ok": False, "msg": "当前没有正在运行的任务"}
        runtime.request_stop()
        runtime.set_stage("正在停止…（当前请求结束后停止）")
        logger.warning("收到停止请求，正在停止…")
        return {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    server_version = "chaoxing-web"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> WebApp:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # 不在终端输出每个 HTTP 请求
        logger.trace("web: " + fmt % args)

    # ------------------------------------------------------------------
    def _host_allowed(self) -> bool:
        if not self.app.local_only:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):
            host = host[1:host.find("]")] if "]" in host else host
        else:
            host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return _is_loopback(host)

    def _authorized(self) -> bool:
        if not self.app.token:
            return True
        supplied = self.headers.get("X-Token") or ""
        return hmac.compare_digest(supplied.encode(), self.app.token.encode())

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _read_json(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length < 0 or length > MAX_BODY:
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------
    def do_GET(self):
        if not self._host_allowed():
            return self._json({"ok": False, "msg": "forbidden host"}, 403)
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            try:
                with open(resource_path("resource", "web", "index.html"), "rb") as f:
                    body = f.read()
            except OSError:
                return self._json({"ok": False, "msg": "页面文件缺失"}, 500)
            return self._send(200, body, "text/html; charset=utf-8")
        if path == "/api/ping":
            return self._json({"ok": True, "token_required": bool(self.app.token)})
        if not path.startswith("/api/"):
            return self._json({"ok": False, "msg": "not found"}, 404)
        if not self._authorized():
            return self._json({"ok": False, "msg": "访问口令错误", "token_required": True}, 401)
        if path == "/api/state":
            return self._json(self.app.state())
        if path == "/api/logs":
            try:
                after = int(parse_qs(parsed.query).get("after", ["0"])[0])
            except ValueError:
                after = 0
            return self._json(self.app.logs.since(after))
        if path == "/api/courses":
            return self._json(self.app.list_courses())
        return self._json({"ok": False, "msg": "not found"}, 404)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if not self._host_allowed():
            return self._json({"ok": False, "msg": "forbidden host"}, 403)
        # 跨站页面无法在不经过预检的情况下携带自定义请求头
        if self.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return self._json({"ok": False, "msg": "forbidden"}, 403)
        if not self._authorized():
            return self._json({"ok": False, "msg": "访问口令错误", "token_required": True}, 401)
        data = self._read_json()
        if data is None:
            return self._json({"ok": False, "msg": "请求格式错误"}, 400)
        routes = {
            "/api/login": lambda: self.app.login(data),
            "/api/logout": self.app.logout,
            "/api/start": lambda: self.app.start(data),
            "/api/stop": self.app.stop,
        }
        handler = routes.get(urlparse(self.path).path)
        if handler is None:
            return self._json({"ok": False, "msg": "not found"}, 404)
        try:
            return self._json(handler())
        except Exception as e:
            logger.error(f"处理请求出错: {type(e).__name__}: {e}")
            return self._json({"ok": False, "msg": f"服务器内部错误: {e}"}, 500)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(settings: Settings, host: str, port: int, token: Optional[str]) -> _Server:
    local_only = _is_loopback(host)
    server_cls = _Server
    if ":" in host:
        server_cls = type("_Server6", (_Server,), {"address_family": socket.AF_INET6})
    server = server_cls((host, port), _Handler)
    server.app = WebApp(settings, token, local_only)  # type: ignore[attr-defined]
    return server


def serve(settings: Settings, host: Optional[str] = None, port: Optional[int] = None,
          open_browser: bool = True) -> int:
    host = host or os.environ.get("CHAOXING_WEB_HOST") or "127.0.0.1"
    port = port or int(os.environ.get("CHAOXING_WEB_PORT") or DEFAULT_PORT)
    token = os.environ.get("CHAOXING_WEB_TOKEN") or None
    if not token and not _is_loopback(host):
        # 对外开放时必须设置访问口令，避免他人通过网络使用你的账号
        token = secrets.token_urlsafe(9)

    try:
        server = create_server(settings, host, port, token)
    except OSError as e:
        logger.error(f"无法在 {host}:{port} 启动网页控制台: {e}（端口可能被占用，可使用 --port 指定其它端口）")
        return 1

    handler_id = logger.add(server.app.logs.write, level="INFO", format="{message}")  # type: ignore[attr-defined]
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{display_host}:{port}/"
    logger.info(f"网页控制台已启动: {url}  (按 Ctrl+C 退出)")
    if token:
        logger.warning(f"访问口令: {token}  (在网页中输入此口令; 可通过环境变量 CHAOXING_WEB_TOKEN 自定义)")
    if open_browser and _is_loopback(display_host):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("网页控制台已关闭")
    finally:
        runtime.request_stop()
        server.server_close()
        logger.remove(handler_id)
    return 0
