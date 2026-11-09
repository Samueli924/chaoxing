# -*- coding: utf-8 -*-
"""
刷课助手的本地后台：提供登录、课程列表、设置读写和任务控制接口，界面在 gui/static 下。
只监听 127.0.0.1，所有 /api 请求都要带启动时生成的令牌。

用法: .venv/bin/python gui/server.py [--port 0] [--open]
"""
import argparse
import collections
import json
import logging
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui"
LOG_DIR = GUI / "logs"
LOG_DIR.mkdir(exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# 后台日志写文件；stdout 只用来告诉外壳程序端口号
_real_stdout = sys.stdout
sys.stderr = open(LOG_DIR / "server.log", "a", encoding="utf8", buffering=1)

from flask import Flask, abort, jsonify, request, send_from_directory  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from api.base import Account, Chaoxing, SessionManager  # noqa: E402
from api.config import GlobalConst  # noqa: E402
from gui import configio, keychain  # noqa: E402

CONFIG = ROOT / "config.ini"
TEMPLATE = ROOT / "config_template.ini"
WORKER_LOG = LOG_DIR / "worker.log"
TOKEN = os.environ.get("CXGUI_TOKEN") or secrets.token_urlsafe(24)
EV_PREFIX = "@@CX "
PLACEHOLDERS = {"", "xxx", "在这里填手机号", "在这里填密码"}

configio.ensure_config(str(CONFIG), str(TEMPLATE))
logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__, static_folder=None)


def ok(**kw):
    return jsonify({"ok": True, **kw})


def fail(msg, code=400, **kw):
    return jsonify({"ok": False, "msg": msg, **kw}), code


@app.before_request
def _auth():
    if request.path.startswith("/api/") and request.headers.get("X-Token") != TOKEN:
        abort(403)


@app.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    return send_from_directory(GUI / "static", "index.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(GUI / "static", name)


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------
class Account_:
    def __init__(self):
        self.lock = threading.RLock()
        self.logged_in = False
        self.phone = ""
        self.password = ""
        self.name = ""
        self.courses: list[dict] = []
        self.progress: dict[str, dict] = {}
        self.progress_gen = 0
        self.progress_loading = False
        self.auto_tried = False


ACC = Account_()


def _config_phone() -> str:
    cfg = configio.read_config(str(CONFIG))
    phone = cfg.get("common", {}).get("username", "").strip()
    return "" if phone in PLACEHOLDERS else phone


def _config_password() -> str:
    cfg = configio.read_config(str(CONFIG))
    pwd = cfg.get("common", {}).get("password", "").strip()
    return "" if pwd in PLACEHOLDERS else pwd


def _do_login(phone: str, password: str, use_cookies: bool) -> tuple[bool, str, str]:
    """返回 (是否成功, 提示信息, 姓名)"""
    try:
        cx = Chaoxing(account=Account(phone, password))
        res = cx.login(login_with_cookies=use_cookies)
    except Exception as e:  # 网络错误或接口返回异常
        return False, f"连接学习通失败：{type(e).__name__}，请检查网络后重试", ""
    if not res.get("status"):
        return False, res.get("msg") or "登录失败", ""
    name = ""
    try:
        name = Chaoxing.get_name()
    except Exception:
        pass
    return True, "登录成功", name


def _session_info():
    return {
        "logged_in": ACC.logged_in,
        "phone": ACC.phone or _config_phone(),
        "name": ACC.name,
        "remembered": bool(ACC.phone and keychain.load_password(ACC.phone)),
        "running": RUN.is_active(),
        "run_status": RUN.status,
    }


@app.get("/api/session")
def api_session():
    """首次打开时尝试用保存的 cookie / 钥匙串密码自动登录。"""
    with ACC.lock:
        if not ACC.logged_in and not ACC.auto_tried:
            ACC.auto_tried = True
            phone = _config_phone()
            pwd = (keychain.load_password(phone) if phone else None) or _config_password()
            has_cookie = (ROOT / GlobalConst.COOKIES_PATH).exists()
            if phone and (has_cookie or pwd):
                success, _msg, name = _do_login(phone, pwd or "", use_cookies=has_cookie)
                if success:
                    ACC.logged_in, ACC.phone, ACC.password, ACC.name = True, phone, pwd or "", name
    return ok(**_session_info())


@app.post("/api/login")
def api_login():
    data = request.get_json(force=True) or {}
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))
    remember = bool(data.get("remember", True))
    if not phone or not password:
        return fail("请填写手机号和密码")
    if RUN.is_active():
        return fail("正在学习中，不能切换账号")
    with ACC.lock:
        SessionManager.get_session().cookies.clear()
        success, msg, name = _do_login(phone, password, use_cookies=False)
        if not success:
            return fail(msg)
        if ACC.phone and ACC.phone != phone:
            ACC.courses, ACC.progress = [], {}
        ACC.logged_in, ACC.phone, ACC.password, ACC.name = True, phone, password, name
        configio.update_config(str(CONFIG), {"common": {"username": phone, "use_cookies": False}})
        if remember:
            keychain.save_password(phone, password)
        else:
            keychain.delete_password(phone)
    return ok(**_session_info())


@app.post("/api/logout")
def api_logout():
    if RUN.is_active():
        return fail("正在学习中，请先停止")
    with ACC.lock:
        keychain.delete_password(ACC.phone)
        try:
            (ROOT / GlobalConst.COOKIES_PATH).unlink()
        except FileNotFoundError:
            pass
        SessionManager.get_session().cookies.clear()
        ACC.logged_in, ACC.password, ACC.name = False, "", ""
        ACC.courses, ACC.progress = [], {}
        ACC.progress_gen += 1
    return ok(**_session_info())


# ---------------------------------------------------------------------------
# 课程
# ---------------------------------------------------------------------------
def _course_key(c: dict) -> str:
    return f"{c['courseId']}_{c['clazzId']}"


def _load_progress(gen: int, courses: list[dict]):
    """后台逐个读取课程章节完成情况，显示在课程卡片上。"""
    ACC.progress_loading = True
    try:
        cx = Chaoxing()
        for c in courses:
            if gen != ACC.progress_gen:
                return
            key = _course_key(c)
            if key in ACC.progress:
                continue
            try:
                pts = cx.get_course_point(c["courseId"], c["clazzId"], c["cpi"])["points"]
                ACC.progress[key] = {
                    "total": len(pts),
                    "done": sum(1 for p in pts if p.get("has_finished")),
                    "locked": any(p.get("need_unlock") for p in pts),
                }
            except Exception as e:
                ACC.progress[key] = {"error": type(e).__name__}
            time.sleep(0.3)
    finally:
        if gen == ACC.progress_gen:
            ACC.progress_loading = False


def _courses_payload():
    return [
        {**{k: c.get(k, "") for k in ("courseId", "clazzId", "title", "teacher", "desc")},
         "key": _course_key(c), "progress": ACC.progress.get(_course_key(c))}
        for c in ACC.courses
    ]


@app.get("/api/courses")
def api_courses():
    if not ACC.logged_in:
        return fail("请先登录", 401)
    refresh = request.args.get("refresh") == "1"
    with ACC.lock:
        if refresh or not ACC.courses:
            try:
                raw = Chaoxing().get_course_list()
            except Exception as e:
                return fail(f"读取课程失败：{type(e).__name__}，可能是登录已过期，请重新登录")
            seen, courses = set(), []
            for c in raw:
                k = _course_key(c)
                if k not in seen:
                    seen.add(k)
                    courses.append(c)
            ACC.courses = courses
            ACC.progress_gen += 1
            if refresh:
                ACC.progress = {}
            threading.Thread(target=_load_progress, args=(ACC.progress_gen, list(courses)),
                             daemon=True).start()
    return ok(courses=_courses_payload(), loading=ACC.progress_loading)


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------
EDITABLE = {
    "common": {"speed", "jobs", "notopen_action", "retry_interval", "add_learning_count",
               "target_count", "work_redo_enabled", "work_max_retries"},
    "tiku": {"provider", "submit", "cover_rate", "delay", "tokens", "url", "go_authorization",
             "endpoint", "key", "model", "min_interval_seconds", "http_proxy", "siliconflow_key",
             "siliconflow_model", "siliconflow_endpoint", "check_llm_connection", "likeapi_model",
             "likeapi_search", "likeapi_vision"},
    "notification": {"provider", "url", "tg_chat_id"},
}


@app.get("/api/settings")
def api_settings():
    cfg = configio.read_config(str(CONFIG))
    return ok(settings={sec: {k: v for k, v in cfg.get(sec, {}).items() if k in keys}
                        for sec, keys in EDITABLE.items()})


@app.post("/api/settings")
def api_save_settings():
    data = request.get_json(force=True) or {}
    updates = {}
    for sec, keys in EDITABLE.items():
        part = data.get(sec) or {}
        updates[sec] = {k: v for k, v in part.items() if k in keys}
    configio.update_config(str(CONFIG), updates)
    return api_settings()


def _bool(v, default=False):
    if v is None or v == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _num(v, cast, default):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def _common_from_config(cfg: dict) -> dict:
    c = cfg.get("common", {})
    action = c.get("notopen_action", "retry")
    return {
        "speed": min(2.0, max(1.0, _num(c.get("speed"), float, 1.0))),
        "jobs": max(1, min(16, _num(c.get("jobs"), int, 4))),
        "notopen_action": action if action in ("retry", "continue") else "retry",
        "retry_interval": _num(c.get("retry_interval"), float, 1.0),
        "add_learning_count": _bool(c.get("add_learning_count")),
        "target_count": _num(c.get("target_count"), int, 100),
        "work_redo_enabled": _bool(c.get("work_redo_enabled")),
        "work_max_retries": _num(c.get("work_max_retries"), int, 3),
    }


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------
STATUS_MAP = {"SUCCESS": "success", "NOT_OPEN": "waiting", "ERROR": "retry"}
FINAL_MAP = {"SUCCESS": "success", "NOT_OPEN": "skipped", "ERROR": "failed", "PENDING": "failed"}


class Run:
    ACTIVE = {"starting", "running", "counting"}

    def __init__(self):
        self.lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.caffeinate: subprocess.Popen | None = None
        self.reset()

    def reset(self):
        self.status = "idle"
        self.phase = ""
        self.started = None
        self.ended = None
        self.error = ""
        self.stop_requested = False
        self.courses: list[dict] = []
        self.chapter_index: dict[tuple, dict] = {}
        self.jobs: dict[int, dict] = {}
        self.recent = collections.deque(maxlen=8)
        self.logs = collections.deque(maxlen=3000)
        self.seq = 0
        self.speed = 1.0
        self.selected: list[dict] = []

    def is_active(self):
        return self.status in self.ACTIVE

    def add_log(self, level, msg, ts=None):
        self.seq += 1
        self.logs.append({"seq": self.seq, "level": level, "msg": msg,
                          "ts": ts or time.strftime("%H:%M:%S")})

    # 处理 worker 事件
    def handle(self, ev: dict):
        t = ev.get("t")
        with self.lock:
            if t == "log":
                self.add_log(ev.get("level", "INFO"), ev.get("msg", ""), ev.get("ts"))
            elif t == "phase":
                self.phase = ev.get("msg", "")
                if "学习次数" in self.phase:
                    self.status = "counting"
            elif t == "plan":
                self.courses = []
                self.chapter_index = {}
                for c in ev.get("courses", []):
                    chapters = [{"id": ch["id"], "title": ch["title"],
                                 "status": "done" if ch.get("finished") else "pending"}
                                for ch in c.get("chapters", [])]
                    course = {"key": c["key"], "title": c["title"], "teacher": c.get("teacher", ""),
                              "chapters": chapters}
                    self.courses.append(course)
                    for ch in chapters:
                        self.chapter_index[(c["key"], ch["id"])] = ch
                self.status = "running"
                self.phase = "正在学习"
            elif t == "ch_start":
                ch = self.chapter_index.get((ev.get("course"), ev.get("id")))
                if ch and ch["status"] != "done":
                    ch["status"] = "running"
            elif t == "ch_end":
                ch = self.chapter_index.get((ev.get("course"), ev.get("id")))
                if ch and ch["status"] != "done":
                    ch["status"] = STATUS_MAP.get(ev.get("result"), "retry")
            elif t == "job_start":
                self.jobs[ev["jid"]] = {k: ev.get(k) for k in ("jid", "kind", "name", "course", "chapter")}
                self.jobs[ev["jid"]].update(n=0, total=0, started=time.time())
            elif t == "progress":
                job = self.jobs.get(ev.get("jid"))
                if job:
                    job["n"], job["total"] = ev.get("n", 0), ev.get("total", 0)
            elif t == "job_end":
                job = self.jobs.pop(ev.get("jid"), None)
                if job:
                    job["result"] = ev.get("result")
                    job["ended"] = time.time()
                    self.recent.appendleft(job)
            elif t == "final":
                for item in ev.get("chapters", []):
                    ch = self.chapter_index.get((item["course"], item["id"]))
                    if ch and ch["status"] != "done":
                        ch["status"] = FINAL_MAP.get(item["result"], "failed")
                self.jobs.clear()
            elif t == "done":
                self.status = "done"
                self.phase = "全部完成"
                self.ended = time.time()
            elif t == "error":
                self.status = "error"
                self.error = ev.get("msg") or "未知错误"
                self.ended = time.time()

    def snapshot(self, since: int):
        with self.lock:
            titles = {c["key"]: c["title"] for c in self.courses}
            chapter_titles = {k: ch["title"] for k, ch in self.chapter_index.items()}

            def job_view(j):
                return {**j, "course_title": titles.get(j.get("course"), ""),
                        "chapter_title": chapter_titles.get((j.get("course"), j.get("chapter")), "")}

            return {
                "status": self.status, "phase": self.phase, "error": self.error,
                "started": self.started, "ended": self.ended, "now": time.time(),
                "speed": self.speed,
                "courses": self.courses,
                "jobs": [job_view(j) for j in self.jobs.values()],
                "recent": [job_view(j) for j in self.recent],
                "logs": [entry for entry in self.logs if entry["seq"] > since],
                "seq": self.seq,
                "selected": [c["title"] for c in self.selected],
                "selected_keys": [_course_key(c) for c in self.selected],
            }


RUN = Run()


def _notify(title: str, msg: str):
    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.Popen(["/usr/bin/osascript", "-e",
                          f'display notification "{esc(msg)}" with title "{esc(title)}" sound name "Glass"'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _reader(proc: subprocess.Popen):
    for raw in proc.stdout:
        line = raw.decode("utf8", errors="replace").rstrip("\n")
        if not line.startswith(EV_PREFIX):
            continue
        try:
            RUN.handle(json.loads(line[len(EV_PREFIX):]))
        except Exception as e:
            sys.stderr.write(f"bad event {line!r}: {e}\n")
    code = proc.wait()
    with RUN.lock:
        if RUN.caffeinate and RUN.caffeinate.poll() is None:
            RUN.caffeinate.terminate()
        if RUN.status in Run.ACTIVE:
            RUN.ended = time.time()
            if RUN.stop_requested:
                RUN.status, RUN.phase = "stopped", "已停止"
            else:
                RUN.status = "error"
                RUN.error = f"后台进程意外退出（代码 {code}），详情见日志"
        status, error = RUN.status, RUN.error
        done = sum(1 for c in RUN.courses for ch in c["chapters"] if ch["status"] in ("done", "success"))
        total = sum(len(c["chapters"]) for c in RUN.courses)
    if status == "done":
        _notify("刷课助手", f"学习完成：{done}/{total} 个章节已完成")
    elif status == "error":
        _notify("刷课助手", f"出错了：{error}")


@app.post("/api/run")
def api_run():
    if not ACC.logged_in:
        return fail("请先登录", 401)
    data = request.get_json(force=True) or {}
    keys = set(data.get("keys") or [])
    selected = [c for c in ACC.courses if _course_key(c) in keys]
    if not selected:
        return fail("请至少选择一门课程")
    with RUN.lock:
        if RUN.is_active():
            return fail("已经在学习中了")
        cfg = configio.read_config(str(CONFIG))
        common = _common_from_config(cfg)
        payload = {
            "username": ACC.phone,
            "password": ACC.password,
            "common": common,
            "tiku": cfg.get("tiku", {}),
            "notification": cfg.get("notification", {}),
            "courses": selected,
            "config_path": str(CONFIG),
        }
        RUN.reset()
        RUN.status, RUN.phase, RUN.started = "starting", "正在启动…", time.time()
        RUN.speed = common["speed"]
        RUN.selected = selected
        err = open(WORKER_LOG, "w", encoding="utf8")
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "gui.worker"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        err.close()
        proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf8"))
        proc.stdin.close()
        RUN.proc = proc
        try:  # 学习期间阻止电脑休眠，进程结束后自动失效
            RUN.caffeinate = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(proc.pid)])
        except Exception:
            RUN.caffeinate = None
        threading.Thread(target=_reader, args=(proc,), daemon=True).start()
    return ok()


@app.post("/api/stop")
def api_stop():
    with RUN.lock:
        proc = RUN.proc
        if not RUN.is_active() or not proc:
            return ok()
        RUN.stop_requested = True
        RUN.phase = "正在停止…"
    _terminate(proc)
    return ok()


@app.post("/api/run/clear")
def api_run_clear():
    with RUN.lock:
        if RUN.is_active():
            return fail("正在学习中")
        RUN.reset()
    return ok()


@app.get("/api/run")
def api_run_state():
    since = _num(request.args.get("since"), int, 0)
    return ok(run=RUN.snapshot(since))


@app.post("/api/reveal")
def api_reveal():
    what = (request.get_json(force=True) or {}).get("what")
    targets = {"config": CONFIG, "log": ROOT / "chaoxing.log", "folder": ROOT}
    path = targets.get(what)
    if path and path.exists():
        subprocess.Popen(["/usr/bin/open", "-R", str(path)] if what != "folder" else ["/usr/bin/open", str(path)])
    return ok()


def _terminate(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _shutdown(*_):
    with RUN.lock:
        RUN.stop_requested = True
        proc = RUN.proc
    if proc:
        _terminate(proc)
    os._exit(0)


def _watch_parent(ppid: int):
    while True:
        time.sleep(2)
        if os.getppid() != ppid:
            _shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--open", action="store_true", help="用浏览器打开界面（调试用）")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    if os.environ.get("CXGUI_WATCH_PARENT") == "1":
        threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()

    server = make_server("127.0.0.1", args.port, app, threaded=True)
    port = server.server_port
    url = f"http://127.0.0.1:{port}/?t={TOKEN}"
    _real_stdout.write(f"CXGUI_READY {port}\n{url}\n")
    _real_stdout.flush()
    if args.open:
        subprocess.Popen(["/usr/bin/open", url])
    server.serve_forever()


if __name__ == "__main__":
    main()
