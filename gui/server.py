# -*- coding: utf-8 -*-
"""
刷课助手的本地后台：多账号管理、课程列表、设置读写、排队调度和任务控制，界面在 gui/static 下。
只监听 127.0.0.1，所有 /api 请求都要带启动时生成的令牌。

用法:
    python gui/server.py            # 启动并用浏览器打开界面（Windows / Linux / macOS 通用）
    python gui/server.py --no-open  # 只启动后台，打印访问地址
macOS 上也可以用 gui/build_app.sh 打包成独立应用。
"""
import argparse
import collections
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui"
DATA = GUI / "data"
LOG_DIR = DATA / "logs"
COOKIE_DIR = DATA / "cookies"
for _d in (DATA, LOG_DIR, COOKIE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# 后台日志写文件；stdout 只用来告诉外壳程序端口号
_real_stdout = sys.stdout
sys.stderr = open(LOG_DIR / "server.log", "a", encoding="utf8", buffering=1)

from flask import Flask, abort, jsonify, request, send_from_directory  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from api.base import Account, Chaoxing, SessionManager  # noqa: E402
from api.config import GlobalConst  # noqa: E402
from gui import configio, keychain, llm_manager, platform_utils  # noqa: E402
from gui.scheduler import Scheduler  # noqa: E402

CONFIG = ROOT / "config.ini"
TEMPLATE = ROOT / "config_template.ini"
ACCOUNTS_FILE = DATA / "accounts.json"
LEGACY_COOKIES = ROOT / "cookies.txt"
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


def _bool(v, default=False):
    if v is None or v == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _num(v, cast, default):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def _course_key(c: dict) -> str:
    return f"{c['courseId']}_{c['clazzId']}"


# ---------------------------------------------------------------------------
# 网络会话：项目原有代码只有一个全局会话，这里按账号切换 cookie 文件并串行访问
# ---------------------------------------------------------------------------
NET = threading.RLock()


@contextlib.contextmanager
def net_as(acct: "Acct"):
    with NET:
        GlobalConst.COOKIES_PATH = str(acct.cookies_path)
        session = SessionManager.get_session()
        session.cookies.clear()
        SessionManager.update_cookies()
        yield


# ---------------------------------------------------------------------------
# 单个账号的一次学习任务
# ---------------------------------------------------------------------------
STATUS_MAP = {"SUCCESS": "success", "NOT_OPEN": "waiting", "ERROR": "retry"}
FINAL_MAP = {"SUCCESS": "success", "NOT_OPEN": "skipped", "ERROR": "failed", "PENDING": "failed"}
ACTIVE = {"starting", "running", "counting"}
BUSY = ACTIVE | {"queued"}


class Run:
    def __init__(self, acct: "Acct"):
        self.acct = acct
        self.lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.awake: subprocess.Popen | None = None
        self.reset()

    def reset(self):
        self.status = "idle"
        self.phase = ""
        self.queued_at = None
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

    def add_log(self, level, msg, ts=None):
        with self.lock:
            self.seq += 1
            self.logs.append({"seq": self.seq, "level": level, "msg": msg,
                              "ts": ts or time.strftime("%H:%M:%S")})

    def counts(self):
        finished = sum(1 for c in self.courses for ch in c["chapters"] if ch["status"] in ("done", "success"))
        total = sum(len(c["chapters"]) for c in self.courses)
        return finished, total

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
                self.courses, self.chapter_index = [], {}
                for c in ev.get("courses", []):
                    chapters = [{"id": ch["id"], "title": ch["title"],
                                 "status": "done" if ch.get("finished") else "pending"}
                                for ch in c.get("chapters", [])]
                    self.courses.append({"key": c["key"], "title": c["title"],
                                         "teacher": c.get("teacher", ""), "chapters": chapters})
                    for ch in chapters:
                        self.chapter_index[(c["key"], ch["id"])] = ch
                self.status, self.phase = "running", "正在学习"
            elif t == "ch_start":
                ch = self.chapter_index.get((ev.get("course"), ev.get("id")))
                if ch and ch["status"] != "done":
                    ch["status"] = "running"
            elif t == "ch_end":
                ch = self.chapter_index.get((ev.get("course"), ev.get("id")))
                if ch and ch["status"] != "done":
                    ch["status"] = STATUS_MAP.get(ev.get("result"), "retry")
            elif t == "job_start":
                job = {k: ev.get(k) for k in ("jid", "kind", "name", "course", "chapter")}
                job.update(n=0, total=0, started=time.time())
                self.jobs[ev["jid"]] = job
            elif t == "progress":
                job = self.jobs.get(ev.get("jid"))
                if job:
                    job["n"], job["total"] = ev.get("n", 0), ev.get("total", 0)
                    job["unit"], job["waiting"] = ev.get("unit"), bool(ev.get("waiting"))
            elif t == "job_end":
                job = self.jobs.pop(ev.get("jid"), None)
                if job:
                    job.update(result=ev.get("result"), ended=time.time())
                    self.recent.appendleft(job)
            elif t == "final":
                for item in ev.get("chapters", []):
                    ch = self.chapter_index.get((item["course"], item["id"]))
                    if ch and ch["status"] != "done":
                        ch["status"] = FINAL_MAP.get(item["result"], "failed")
                self.jobs.clear()
            elif t == "done":
                self.status, self.phase, self.ended = "done", "全部完成", time.time()
            elif t == "error":
                self.status, self.ended = "error", time.time()
                self.error = ev.get("msg") or "未知错误"

    def launch(self):
        acct = self.acct
        cfg = configio.read_config(str(CONFIG))
        common = common_from_config(cfg)
        with self.lock:
            self.status, self.phase = "starting", "正在启动…"
            self.started = self.started or time.time()
        prepare_local_model(self, cfg)
        prepare_search(self, cfg)
        with self.lock:
            if self.stop_requested:
                self.status, self.phase, self.ended = "stopped", "已停止", time.time()
                return
        payload = {
            "username": acct.phone,
            "password": acct.password or keychain.load_password(acct.phone) or "",
            "cookies_path": str(acct.cookies_path),
            "common": common,
            "tiku": cfg.get("tiku", {}),
            "notification": cfg.get("notification", {}),
            "courses": self.selected,
            "config_path": str(CONFIG),
        }
        with self.lock:
            self.phase = "正在启动…"
            self.speed = common["speed"]
            err = open(acct.log_path, "w", encoding="utf8")
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-u", "-m", "gui.worker"], cwd=ROOT,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
                )
            except Exception as e:
                self.status, self.error, self.ended = "error", f"无法启动刷课进程：{e}", time.time()
                return
            finally:
                err.close()
            proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf8"))
            proc.stdin.close()
            self.proc = proc
            self.awake = platform_utils.keep_awake_for(proc.pid)
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()

    def _reader(self, proc: subprocess.Popen):
        for raw in proc.stdout:
            line = raw.decode("utf8", errors="replace").rstrip("\r\n")
            if not line.startswith(EV_PREFIX):
                continue
            try:
                self.handle(json.loads(line[len(EV_PREFIX):]))
            except Exception as e:
                sys.stderr.write(f"bad event {line!r}: {e}\n")
        code = proc.wait()
        with self.lock:
            if self.awake and self.awake.poll() is None:
                self.awake.terminate()
            if self.status in ACTIVE:
                self.ended = time.time()
                if self.stop_requested:
                    self.status, self.phase = "stopped", "已停止"
                else:
                    self.status = "error"
                    self.error = f"刷课进程意外退出（代码 {code}），详情见日志"
            status, error = self.status, self.error
            finished, total = self.counts()
        who = self.acct.display()
        if status == "done":
            platform_utils.notify("刷课助手", f"{who} 学习完成：{finished}/{total} 个章节已完成")
        elif status == "error":
            platform_utils.notify("刷课助手", f"{who} 出错了：{error}")

    def stop(self):
        with self.lock:
            proc = self.proc
            if self.status not in ACTIVE:
                return
            if not proc or proc.poll() is not None:  # 还在加载模型，launch 会在加载完后放弃启动
                self.stop_requested = True
                self.phase = "正在停止…"
                return
            self.stop_requested = True
            self.phase = "正在停止…"
        terminate(proc)

    def snapshot(self, since: int, estimate=None):
        with self.lock:
            titles = {c["key"]: c["title"] for c in self.courses}
            chapter_titles = {k: ch["title"] for k, ch in self.chapter_index.items()}

            def job_view(j):
                return {**j, "course_title": titles.get(j.get("course"), ""),
                        "chapter_title": chapter_titles.get((j.get("course"), j.get("chapter")), "")}

            return {
                "status": self.status, "phase": self.phase, "error": self.error,
                "queued_at": self.queued_at, "started": self.started, "ended": self.ended,
                "now": time.time(), "speed": self.speed, "queue": estimate,
                "courses": self.courses,
                "jobs": [job_view(j) for j in self.jobs.values()],
                "recent": [job_view(j) for j in self.recent],
                "logs": [e for e in self.logs if e["seq"] > since],
                "seq": self.seq,
                "selected": [c["title"] for c in self.selected],
                "selected_keys": [_course_key(c) for c in self.selected],
            }


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------
def _safe_name(phone: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "_", phone) or "account"


class Acct:
    def __init__(self, phone: str, name: str = "", selected=None):
        self.phone = phone
        self.name = name
        self.selected: list[str] = list(selected or [])
        self.password = ""  # 只保存在内存中
        self.auth = "unknown"  # unknown / checking / ok / failed
        self.auth_msg = ""
        self.courses: list[dict] = []
        self.progress: dict[str, dict] = {}
        self.progress_gen = 0
        self.progress_loading = False
        self.lock = threading.RLock()
        self.run = Run(self)

    @property
    def cookies_path(self) -> Path:
        return COOKIE_DIR / f"{_safe_name(self.phone)}.txt"

    @property
    def log_path(self) -> Path:
        return LOG_DIR / f"worker-{_safe_name(self.phone)}.log"

    def display(self) -> str:
        return self.name or mask_phone(self.phone)

    def to_json(self):
        return {"phone": self.phone, "name": self.name, "selected": self.selected}

    def summary(self):
        run = self.run
        with run.lock:
            finished, total = run.counts()
            return {
                "phone": self.phone, "name": self.name, "auth": self.auth, "auth_msg": self.auth_msg,
                "status": run.status, "phase": run.phase, "error": run.error,
                "finished": finished, "total": total,
                "selected_count": len(self.selected),
                "queue": SCHED.estimate(self.phone, active_count()) if run.status == "queued" else None,
            }


def mask_phone(p: str) -> str:
    return p[:3] + "****" + p[-4:] if len(p) >= 7 else p


ACCOUNTS: dict[str, Acct] = {}
ACC_LOCK = threading.RLock()


def save_accounts():
    with ACC_LOCK:
        data = [a.to_json() for a in ACCOUNTS.values()]
    tmp = ACCOUNTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")
    os.replace(tmp, ACCOUNTS_FILE)


def load_accounts():
    if ACCOUNTS_FILE.exists():
        try:
            for item in json.loads(ACCOUNTS_FILE.read_text(encoding="utf8")):
                if item.get("phone"):
                    ACCOUNTS[item["phone"]] = Acct(item["phone"], item.get("name", ""), item.get("selected"))
        except Exception as e:
            sys.stderr.write(f"读取账号列表失败: {e}\n")
        return
    # 首次运行：沿用 config.ini 里的账号和根目录的 cookies.txt（命令行版留下的登录状态）
    cfg = configio.read_config(str(CONFIG)).get("common", {})
    phone = cfg.get("username", "").strip()
    if phone and phone not in PLACEHOLDERS:
        acct = Acct(phone)
        if LEGACY_COOKIES.exists() and not acct.cookies_path.exists():
            shutil.copyfile(LEGACY_COOKIES, acct.cookies_path)
        pwd = cfg.get("password", "").strip()
        if pwd and pwd not in PLACEHOLDERS:
            acct.password = pwd
        ACCOUNTS[phone] = acct
        save_accounts()


def get_acct(phone: str) -> Acct:
    acct = ACCOUNTS.get(phone)
    if not acct:
        abort(404)
    return acct


def do_login(acct: Acct, password: str, use_cookies: bool) -> tuple[bool, str]:
    with net_as(acct):
        try:
            res = Chaoxing(account=Account(acct.phone, password)).login(login_with_cookies=use_cookies)
        except Exception as e:
            return False, f"连接学习通失败：{type(e).__name__}，请检查网络后重试"
        if not res.get("status"):
            return False, res.get("msg") or "登录失败"
        try:
            name = Chaoxing.get_name()
            if name:
                acct.name = name
        except Exception:
            pass
    return True, "登录成功"


def check_login(acct: Acct):
    """用保存的 cookie 或钥匙串密码自动登录。"""
    acct.auth, acct.auth_msg = "checking", ""
    pwd = acct.password or keychain.load_password(acct.phone) or ""
    has_cookie = acct.cookies_path.exists()
    if not has_cookie and not pwd:
        acct.auth, acct.auth_msg = "failed", "需要重新登录"
        return
    success, msg = do_login(acct, pwd, use_cookies=has_cookie)
    acct.auth = "ok" if success else "failed"
    acct.auth_msg = "" if success else msg
    if success:
        acct.password = pwd
        save_accounts()


def _auto_login_all():
    for acct in list(ACCOUNTS.values()):
        if acct.auth == "unknown":
            check_login(acct)


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------
SCHED = Scheduler()


def scheduler_settings(cfg=None):
    g = (cfg or configio.read_config(str(CONFIG))).get("gui", {})
    max_parallel = max(1, min(10, _num(g.get("max_parallel_accounts"), int, 2)))
    lo = max(0.0, _num(g.get("stagger_min_minutes"), float, 2))
    hi = max(lo, _num(g.get("stagger_max_minutes"), float, 5))
    return max_parallel, lo, hi


def apply_scheduler_settings():
    max_parallel, lo, hi = scheduler_settings()
    SCHED.configure(max_parallel, (lo * 60, hi * 60))


def active_count() -> int:
    return sum(1 for a in ACCOUNTS.values() if a.run.status in ACTIVE)


def _scheduler_loop():
    while True:
        try:
            for phone in SCHED.due(active_count()):
                acct = ACCOUNTS.get(phone)
                if acct and acct.run.status == "queued":
                    with acct.run.lock:  # 先标记为启动中，避免加载模型期间被重复计入空位
                        acct.run.status, acct.run.started = "starting", time.time()
                    threading.Thread(target=acct.run.launch, daemon=True).start()
            busy = any(a.run.status in BUSY for a in ACCOUNTS.values())
            for backend, model in UNLOADER.tick(busy):
                threading.Thread(target=unload_local_model, args=(backend, model), daemon=True).start()
        except Exception as e:
            sys.stderr.write(f"scheduler error: {e}\n")
        time.sleep(1)


# ---------------------------------------------------------------------------
# 本地大模型自动加载 / 卸载
# ---------------------------------------------------------------------------
UNLOADER = llm_manager.AutoUnloader(grace=15)
MODEL_LOCK = threading.Lock()


def auto_manage_enabled(cfg=None) -> bool:
    g = (cfg or configio.read_config(str(CONFIG))).get("gui", {})
    return _bool(g.get("auto_manage_local_model"), True)


# ---------------------------------------------------------------------------
# 本地搜索服务（SearXNG）：联网搜索地址指向本机且服务没开时，用配置的启动命令拉起，应用退出时一起关闭
# ---------------------------------------------------------------------------
SEARCH_PROC: subprocess.Popen | None = None
SEARCH_LOCK = threading.Lock()


def _search_alive(url: str) -> bool:
    import urllib.request
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机服务不走系统代理
        with opener.open(f"{url.rstrip('/')}/healthz", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def prepare_search(run: "Run", cfg: dict):
    global SEARCH_PROC
    tiku = cfg.get("tiku", {})
    url = (tiku.get("ai_search_url") or "").strip()
    providers = [p.strip() for p in str(tiku.get("provider", "")).split(",")]
    if not url or "AI" not in providers or llm_manager.urlparse(url).hostname not in llm_manager.LOCAL_HOSTS:
        return
    with SEARCH_LOCK:
        if _search_alive(url):
            return
        command = (cfg.get("gui", {}).get("searxng_command") or "").strip()
        if not command or not Path(command).exists():
            run.add_log("WARNING", f"联网搜索服务 {url} 没有运行，本次不使用搜索（可在设置里填写 SearXNG 启动脚本，自动启动）")
            return
        with run.lock:
            run.phase = "正在启动本地搜索服务…"
        if SEARCH_PROC is None or SEARCH_PROC.poll() is not None:
            log = open(LOG_DIR / "searxng.log", "a", encoding="utf8")
            SEARCH_PROC = subprocess.Popen([command], cwd=str(Path(command).parent), stdout=log, stderr=log)
            log.close()
        for _ in range(60):
            if _search_alive(url):
                run.add_log("INFO", f"已启动本地搜索服务 {url}")
                return
            if SEARCH_PROC.poll() is not None:
                break
            time.sleep(0.5)
        run.add_log("WARNING", f"本地搜索服务启动失败，本次不使用搜索，详见 {LOG_DIR / 'searxng.log'}")


def prepare_local_model(run: "Run", cfg: dict):
    """题库使用本机 LM Studio 时，在启动刷课进程前确保模型已加载。"""
    if not auto_manage_enabled(cfg):
        return
    target = llm_manager.local_target(cfg.get("tiku", {}))
    if not target:
        return
    root, model = target
    backend = llm_manager.LMStudio(root)
    if not backend.probe():
        run.add_log("WARNING", f"连不上本地大模型服务 {root}，请确认 LM Studio 已打开并启动了本地服务")
        return
    with run.lock:
        run.phase = "正在加载本地大模型…"
    with MODEL_LOCK:  # 多个账号同时启动时只加载一次
        try:
            t0 = time.time()
            if backend.ensure_loaded(model):
                run.add_log("INFO", f"已加载本地模型 {model}（用时 {time.time() - t0:.0f} 秒）")
            else:
                run.add_log("INFO", f"本地模型 {model} 已在运行")
            UNLOADER.used(backend, model)
        except Exception as e:
            run.add_log("WARNING", f"加载本地模型 {model} 失败：{e}")


def unload_local_model(backend: "llm_manager.LMStudio", model: str):
    with MODEL_LOCK:
        try:
            n = backend.unload(model)
        except Exception as e:
            sys.stderr.write(f"卸载本地模型失败: {e}\n")
            return
    if n:
        msg = f"所有账号已结束，已卸载本地模型 {model}，释放内存"
        for acct in list(ACCOUNTS.values()):
            if acct.run.status in ("done", "stopped", "error"):
                acct.run.add_log("INFO", msg)


def enqueue(acct: Acct, keys: list[str]) -> str | None:
    """把账号加入排队，返回错误信息或 None。"""
    if acct.auth != "ok":
        return "这个账号还没有登录成功"
    selected = [c for c in acct.courses if _course_key(c) in set(keys)]
    if not selected:
        return "请至少选择一门课程"
    with acct.run.lock:
        if acct.run.status in BUSY:
            return "这个账号已经在学习或排队中了"
        acct.run.reset()
        acct.run.status, acct.run.phase, acct.run.queued_at = "queued", "排队中", time.time()
        acct.run.selected = selected
    acct.selected = [_course_key(c) for c in selected]
    save_accounts()
    SCHED.enqueue(acct.phone)
    return None


def cancel_or_stop(acct: Acct):
    if SCHED.cancel(acct.phone) or acct.run.status == "queued":
        with acct.run.lock:
            acct.run.reset()
        return
    acct.run.stop()


def terminate(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# 接口：账号
# ---------------------------------------------------------------------------
@app.get("/api/state")
def api_state():
    max_parallel, lo, hi = scheduler_settings()
    accounts = [a.summary() for a in ACCOUNTS.values()]
    return ok(accounts=accounts, can_remember=keychain.available(),
              scheduler={"max_parallel": max_parallel, "stagger_min": lo, "stagger_max": hi,
                         "active": active_count(), "queued": len(SCHED.queue)},
              any_busy=any(a["status"] in BUSY for a in accounts))


@app.post("/api/accounts")
def api_add_account():
    """添加账号或重新登录已有账号。"""
    data = request.get_json(force=True) or {}
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))
    remember = bool(data.get("remember", True))
    if not phone or not password:
        return fail("请填写手机号和密码")
    with ACC_LOCK:
        existing = ACCOUNTS.get(phone)
        if existing and existing.run.status in BUSY:
            return fail("这个账号正在学习中，请先停止")
        acct = existing or Acct(phone)
        try:
            acct.cookies_path.unlink()
        except FileNotFoundError:
            pass
        success, msg = do_login(acct, password, use_cookies=False)
        if not success:
            if existing:
                existing.auth, existing.auth_msg = "failed", msg
            return fail(msg)
        acct.password, acct.auth, acct.auth_msg = password, "ok", ""
        ACCOUNTS[phone] = acct
        save_accounts()
    if remember:
        keychain.save_password(phone, password)
    else:
        keychain.delete_password(phone)
    return ok(account=acct.summary())


@app.post("/api/accounts/<phone>/delete")
def api_delete_account(phone):
    acct = get_acct(phone)
    if acct.run.status in BUSY:
        return fail("这个账号正在学习或排队中，请先停止")
    with ACC_LOCK:
        ACCOUNTS.pop(phone, None)
        acct.progress_gen += 1
        save_accounts()
    keychain.delete_password(phone)
    try:
        acct.cookies_path.unlink()
    except FileNotFoundError:
        pass
    return ok()


@app.post("/api/accounts/<phone>/check")
def api_check_account(phone):
    acct = get_acct(phone)
    if acct.auth != "checking":
        check_login(acct)
    return ok(account=acct.summary())


# ---------------------------------------------------------------------------
# 接口：课程
# ---------------------------------------------------------------------------
def _load_progress(acct: Acct, gen: int, courses: list[dict]):
    acct.progress_loading = True
    try:
        for c in courses:
            if gen != acct.progress_gen:
                return
            key = _course_key(c)
            if key in acct.progress:
                continue
            try:
                with net_as(acct):
                    pts = Chaoxing().get_course_point(c["courseId"], c["clazzId"], c["cpi"])["points"]
                acct.progress[key] = {
                    "total": len(pts),
                    "done": sum(1 for p in pts if p.get("has_finished")),
                    "locked": any(p.get("need_unlock") for p in pts),
                }
            except Exception as e:
                acct.progress[key] = {"error": type(e).__name__}
            time.sleep(0.3)
    finally:
        if gen == acct.progress_gen:
            acct.progress_loading = False


@app.get("/api/accounts/<phone>/courses")
def api_courses(phone):
    acct = get_acct(phone)
    if acct.auth != "ok":
        return fail("请先登录这个账号", 401)
    refresh = request.args.get("refresh") == "1"
    with acct.lock:
        if refresh or not acct.courses:
            try:
                with net_as(acct):
                    raw = Chaoxing().get_course_list()
            except Exception as e:
                return fail(f"读取课程失败：{type(e).__name__}，可能是登录已过期，请重新登录")
            seen, courses = set(), []
            for c in raw:
                k = _course_key(c)
                if k not in seen:
                    seen.add(k)
                    courses.append(c)
            acct.courses = courses
            acct.progress_gen += 1
            if refresh:
                acct.progress = {}
            threading.Thread(target=_load_progress, args=(acct, acct.progress_gen, list(courses)),
                             daemon=True).start()
    payload = [
        {**{k: c.get(k, "") for k in ("courseId", "clazzId", "title", "teacher", "desc")},
         "key": _course_key(c), "progress": acct.progress.get(_course_key(c))}
        for c in acct.courses
    ]
    return ok(courses=payload, loading=acct.progress_loading, selected=acct.selected)


@app.post("/api/accounts/<phone>/selection")
def api_selection(phone):
    acct = get_acct(phone)
    acct.selected = [str(k) for k in (request.get_json(force=True) or {}).get("keys", [])]
    save_accounts()
    return ok()


# ---------------------------------------------------------------------------
# 接口：任务
# ---------------------------------------------------------------------------
@app.post("/api/accounts/<phone>/start")
def api_start(phone):
    acct = get_acct(phone)
    keys = (request.get_json(force=True) or {}).get("keys") or acct.selected
    err = enqueue(acct, keys)
    return fail(err) if err else ok(account=acct.summary())


@app.post("/api/accounts/<phone>/stop")
def api_stop(phone):
    cancel_or_stop(get_acct(phone))
    return ok()


@app.post("/api/accounts/<phone>/clear")
def api_clear(phone):
    acct = get_acct(phone)
    with acct.run.lock:
        if acct.run.status in BUSY:
            return fail("正在学习或排队中")
        acct.run.reset()
    return ok()


@app.get("/api/accounts/<phone>/run")
def api_run_state(phone):
    acct = get_acct(phone)
    since = _num(request.args.get("since"), int, 0)
    est = SCHED.estimate(phone, active_count()) if acct.run.status == "queued" else None
    return ok(run=acct.run.snapshot(since, est))


@app.post("/api/start_all")
def api_start_all():
    started, skipped = [], []
    for acct in list(ACCOUNTS.values()):
        if acct.run.status in BUSY:
            continue
        if acct.auth != "ok":
            skipped.append(f"{acct.display()}（未登录）")
            continue
        if not acct.courses:  # 还没打开过课程列表时，用保存的选择即可，但需要课程信息
            try:
                with net_as(acct):
                    acct.courses = Chaoxing().get_course_list()
            except Exception:
                skipped.append(f"{acct.display()}（读取课程失败）")
                continue
        err = enqueue(acct, acct.selected)
        (skipped if err else started).append(acct.display() + (f"（{err}）" if err else ""))
    return ok(started=started, skipped=skipped)


@app.post("/api/stop_all")
def api_stop_all():
    for acct in list(ACCOUNTS.values()):
        if acct.run.status in BUSY:
            cancel_or_stop(acct)
    return ok()


# ---------------------------------------------------------------------------
# 接口：设置
# ---------------------------------------------------------------------------
EDITABLE = {
    "common": {"speed", "jobs", "notopen_action", "retry_interval", "add_learning_count",
               "target_count", "work_redo_enabled", "work_max_retries", "work_min_score", "work_recheck_finished"},
    "tiku": {"provider", "submit", "cover_rate", "delay", "tokens", "url", "go_authorization",
             "endpoint", "key", "model", "min_interval_seconds", "http_proxy", "siliconflow_key",
             "siliconflow_model", "siliconflow_endpoint", "check_llm_connection", "likeapi_model",
             "likeapi_search", "likeapi_vision", "ai_vision", "ai_timeout", "ai_max_tokens",
             "ai_disable_thinking", "ai_search_url", "ai_search_results"},
    "notification": {"provider", "url", "tg_chat_id"},
    "gui": {"max_parallel_accounts", "stagger_min_minutes", "stagger_max_minutes", "auto_manage_local_model",
            "searxng_command"},
}


@app.get("/api/settings")
def api_settings():
    cfg = configio.read_config(str(CONFIG))
    max_parallel, lo, hi = scheduler_settings(cfg)
    settings = {sec: {k: v for k, v in cfg.get(sec, {}).items() if k in keys} for sec, keys in EDITABLE.items()}
    for k, v in {"ai_vision": "true", "ai_timeout": "120", "ai_disable_thinking": "false"}.items():
        settings["tiku"].setdefault(k, v)  # 旧配置文件里没有这些键时，显示答题代码的默认值
    settings["gui"] = {"max_parallel_accounts": str(max_parallel),
                       "stagger_min_minutes": f"{lo:g}", "stagger_max_minutes": f"{hi:g}",
                       "auto_manage_local_model": "true" if auto_manage_enabled(cfg) else "false",
                       "searxng_command": cfg.get("gui", {}).get("searxng_command", "")}
    return ok(settings=settings)


@app.post("/api/settings")
def api_save_settings():
    data = request.get_json(force=True) or {}
    updates = {}
    for sec, keys in EDITABLE.items():
        part = data.get(sec) or {}
        updates[sec] = {k: v for k, v in part.items() if k in keys}
    configio.update_config(str(CONFIG), updates)
    apply_scheduler_settings()
    return api_settings()


def common_from_config(cfg: dict) -> dict:
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
        "work_min_score": max(0.0, min(100.0, _num(c.get("work_min_score"), float, 100.0))),
        "work_recheck_finished": _bool(c.get("work_recheck_finished")),
    }


@app.post("/api/client_log")
def api_client_log():
    """界面与后台的连接中断恢复后上报的情况，写入 server.log 便于排查。"""
    data = request.get_json(force=True) or {}
    failures = data.get("failures") or []
    paths = sorted({str(f.get("path", ""))[:60] for f in failures})
    errors = sorted({str(f.get("err", ""))[:80] for f in failures})
    sys.stderr.write(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 界面连接中断 {float(data.get('seconds', 0)):.1f} 秒后恢复，"
        f"失败 {len(failures)} 次{'（期间电脑可能处于睡眠）' if data.get('slept') else ''}；"
        f"接口: {', '.join(paths)}；错误: {'; '.join(errors)}\n")
    return ok()


@app.post("/api/reveal")
def api_reveal():
    data = request.get_json(force=True) or {}
    what = data.get("what")
    if what == "worker_log" and data.get("phone") in ACCOUNTS:
        path = ACCOUNTS[data["phone"]].log_path
    else:
        path = {"config": CONFIG, "log": ROOT / "chaoxing.log", "folder": ROOT, "logs": LOG_DIR}.get(what)
    if path:
        platform_utils.reveal(path)
    return ok()


# ---------------------------------------------------------------------------
# 启动 / 退出
# ---------------------------------------------------------------------------
def _shutdown(*_):
    for acct in list(ACCOUNTS.values()):
        proc = acct.run.proc
        if proc and proc.poll() is None:
            acct.run.stop_requested = True
            terminate(proc)
    if SEARCH_PROC is not None and SEARCH_PROC.poll() is None:  # 由本应用启动的搜索服务一起关闭
        terminate(SEARCH_PROC)
    for backend, model in UNLOADER.take_all():  # 刷课用过的本地模型随应用退出一起卸载
        try:
            backend.unload(model)
        except Exception:
            pass
    os._exit(0)


def _watch_parent(ppid: int):
    while True:
        time.sleep(2)
        if os.getppid() != ppid:
            _shutdown()


def main():
    parser = argparse.ArgumentParser(description="刷课助手图形界面")
    parser.add_argument("--port", type=int, default=0, help="监听端口，默认随机")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    if os.environ.get("CXGUI_WATCH_PARENT") == "1":
        threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()

    load_accounts()
    apply_scheduler_settings()
    threading.Thread(target=_auto_login_all, daemon=True).start()
    threading.Thread(target=_scheduler_loop, daemon=True).start()

    server = make_server("127.0.0.1", args.port, app, threaded=True)
    port = server.server_port
    url = f"http://127.0.0.1:{port}/?t={TOKEN}"
    _real_stdout.write(f"CXGUI_READY {port}\n")
    _real_stdout.write(f"刷课助手已启动，在浏览器中打开: {url}\n按 Ctrl+C 退出\n")
    _real_stdout.flush()
    # 由 macOS 外壳启动时（设置了 CXGUI_TOKEN）不打开浏览器
    if not args.no_open and not os.environ.get("CXGUI_TOKEN"):
        platform_utils.open_url(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
