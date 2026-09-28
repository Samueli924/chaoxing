# -*- coding: utf-8 -*-
"""
超星学习通自动化 - 本地图形化控制界面

运行方式:
    python webgui.py
然后浏览器打开 http://127.0.0.1:5000

说明:
- 网站只监听本机 127.0.0.1，不会暴露到局域网/公网。
- 页面上填写的配置会写入同目录 config_gui.ini，点击"开始"后以子进程方式运行 main.py，
  子进程的输出通过 SSE 实时推送到网页日志控制台。
"""
import configparser
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

# 网站自身及它启动的刷课子进程都不在主程序目录留下 __pycache__ 缓存
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from flask import Flask, jsonify, render_template, request, Response

BASE_DIR = Path(__file__).resolve().parent


def _detect_project_dir() -> Path:
    """定位刷课主程序目录(需包含 main.py 和 api 包)。

    查找顺序: 环境变量 CHAOXING_HOME -> webgui 同目录 -> 同级的 chaoxing-main 目录。
    这样把 webgui.py 和 templates 移动到其他文件夹后仍可正常运行。
    """
    candidates = []
    env_dir = os.environ.get("CHAOXING_HOME")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates += [BASE_DIR, BASE_DIR.parent / "chaoxing-main"]
    for directory in candidates:
        if (directory / "main.py").is_file() and (directory / "api").is_dir():
            return directory.resolve()
    return BASE_DIR


PROJECT_DIR = _detect_project_dir()
# webgui 被移动到主程序目录之外时, 仍需导入 main 和 api 包
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
# 主程序里的 resource 字体表、cookies.txt、日志等都按相对路径读写, 统一切到主程序目录
os.chdir(PROJECT_DIR)

CONFIG_PATH = BASE_DIR / "config_gui.ini"

app = Flask(__name__)

# ---------------------------------------------------------------------------
# 子进程管理
# ---------------------------------------------------------------------------
PROC_LOCK = threading.RLock()  # 可重入: api_start 持锁后会调用 is_running()
PROC = None  # 当前运行中的 main.py 子进程

# 日志广播: 每个 SSE 客户端一个队列; ring 保存最近 500 行用于新客户端补播
CLIENTS: set[queue.Queue] = set()
RING: deque[tuple[str, str]] = deque(maxlen=500)
RING_LOCK = threading.Lock()


def broadcast(kind: str, text: str) -> None:
    """kind: 'log' 普通日志 | 'progress' 进度条 | 'system' 系统提示"""
    item = (kind, text)
    with RING_LOCK:
        RING.append(item)
    dead = []
    for q in list(CLIENTS):
        try:
            q.put_nowait(item)
        except queue.Full:
            dead.append(q)
    for q in dead:
        CLIENTS.discard(q)


def reader_thread(proc: subprocess.Popen) -> None:
    """持续读取子进程输出, 按 \\n / \\r 拆分成日志行和进度条片段后广播。"""
    raw = proc.stdout  # 二进制 BufferedReader, read1 有数据立即返回
    leftover_bytes = b""   # 末尾不完整的 UTF-8 多字节字符
    pending_text = ""      # 还没遇到换行的半行文本(跨读取块累积)
    while True:
        try:
            chunk_b = raw.read1(512)
        except ValueError:
            break
        if not chunk_b:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
            continue
        text, leftover_bytes = _decode_partial(leftover_bytes + chunk_b)
        # 关键: Windows 正常换行是 \r\n, 先归一化为 \n;
        # 剩下的孤立 \r 才是 tqdm 进度条刷新, 不能把正常日志行尾误判成进度
        text = text.replace("\r\n", "\n")
        # 原样输出到网站自己的控制台窗口(保留 \r 进度刷新), 黑窗口里看实时反馈
        sys.stdout.write(text)
        sys.stdout.flush()

        pending_text += text
        # 先按 \n 换行拆, 每段内部再按 \r(tqdm 进度条)拆
        while "\n" in pending_text:
            line, pending_text = pending_text.split("\n", 1)
            # 行尾残留的单个 \r 是跨块 CRLF 的前半, 剥掉而不是当进度
            if line.endswith("\r"):
                line = line[:-1]
            _emit_cr_segment(line + "\n")
        # 处理滞留在缓冲区中的孤立 \r 进度片段;
        # 但末尾 \r 可能是跨块 CRLF 的前半(\n 在下一块), 此时保留不动
        if pending_text.rpartition("\r")[2]:
            head, _, tail = pending_text.rpartition("\r")
            if head:
                _emit_cr_segment(head)
            pending_text = tail

    if pending_text.strip():
        _emit_cr_segment(pending_text)
    code = proc.wait()
    global PROC
    with PROC_LOCK:
        if PROC is proc:
            PROC = None
    print(f"[webgui] 刷课任务已结束, 退出码 {code}", flush=True)
    broadcast("system", f"子进程已结束, 退出码 {code}")
    # 通知所有打开的页面刷新运行状态(任务自然跑完或被停止都会走到这里)
    broadcast("status", '{"running": false}')


def _decode_partial(data: bytes) -> tuple[str, bytes]:
    """解码尽量多的完整 UTF-8 字节, 末尾不完整的多字节序列留到下一轮。"""
    for cut in range(len(data), max(len(data) - 4, 0) - 1, -1):
        try:
            return data[:cut].decode("utf-8"), data[cut:]
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), b""


def _emit_cr_segment(segment: str) -> None:
    """一段文本里可能混着多个 \\r 进度刷新, 只发送最后一个进度片段 + 其余普通行。"""
    parts = segment.split("\r")
    for part in parts[:-1]:
        if part.strip():
            broadcast("progress", _strip_ansi(part.strip()))
    tail = parts[-1]
    if tail.strip():
        broadcast("log", _strip_ansi(tail.rstrip("\n")))


# loguru 输出里带的终端颜色转义序列(如 [32m), 网页无法渲染, 广播前剥掉
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def is_running() -> bool:
    with PROC_LOCK:
        return PROC is not None and PROC.poll() is None


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------
# 表单字段 -> (section, key, 默认值)
FIELDS = {
    "use_cookies": ("common", "use_cookies", "false"),
    "username": ("common", "username", ""),
    "password": ("common", "password", ""),
    "course_list": ("common", "course_list", ""),
    "speed": ("common", "speed", "1"),
    "jobs": ("common", "jobs", "1"),
    "notopen_action": ("common", "notopen_action", "retry"),
    "retry_interval": ("common", "retry_interval", "1.0"),
    "chapter_delay_min": ("common", "chapter_delay_min", "3"),
    "chapter_delay_max": ("common", "chapter_delay_max", "8"),
    "api_interval": ("common", "api_interval", "1.0"),
    "video_log_interval": ("common", "video_log_interval", "3"),
    "work_max_retries": ("common", "work_max_retries", "3"),
    "add_learning_count": ("common", "add_learning_count", "false"),
    "target_count": ("common", "target_count", "100"),

    "tiku_enabled": ("_gui", "tiku_enabled", "false"),
    "provider": ("tiku", "provider", ""),
    "submit": ("tiku", "submit", "false"),
    "cover_rate": ("tiku", "cover_rate", "0.9"),
    "tiku_delay": ("tiku", "delay", "1.0"),
    "tokens": ("tiku", "tokens", ""),
    "endpoint": ("tiku", "endpoint", ""),
    "key": ("tiku", "key", ""),
    "model": ("tiku", "model", ""),
    "url": ("tiku", "url", ""),

    "notify_enabled": ("_gui", "notify_enabled", "false"),
    "notify_provider": ("notification", "provider", "ServerChan"),
    "notify_url": ("notification", "url", ""),
    "tg_chat_id": ("notification", "tg_chat_id", ""),
}

# 启用题库时必须存在的字段(init_tiku 会直接读取, 缺失会报错)
TIKU_REQUIRED_DEFAULTS = {
    "true_list": "正确,对,√,是",
    "false_list": "错误,错,×,否,不对,不正确",
}


def read_config() -> dict:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH, encoding="utf8")
    result = {}
    for field, (section, key, default) in FIELDS.items():
        if section == "_gui":
            value = default
            if field == "tiku_enabled":
                value = "true" if cfg.has_option("tiku", "provider") and cfg.get(
                    "tiku", "provider", fallback="").strip() else "false"
            elif field == "notify_enabled":
                value = "true" if cfg.has_option("notification", "url") and cfg.get(
                    "notification", "url", fallback="").strip() else "false"
        else:
            value = cfg.get(section, key, fallback=default)
        result[field] = value
    return result


def write_config(data: dict) -> None:
    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # 保留大小写

    cfg["common"] = {}
    for field, (section, key, default) in FIELDS.items():
        if section != "common":
            continue
        # 数字类输入框被清空时回落到默认值, 避免 main.py 解析空字符串报错
        value = str(data.get(field, "")).strip() or default
        cfg["common"][key] = value

    # 题库
    use_tiku = data.get("tiku_enabled") in (True, "true", "on", "1")
    if use_tiku:
        cfg["tiku"] = dict(TIKU_REQUIRED_DEFAULTS)
        for field, (section, key, default) in FIELDS.items():
            if section == "tiku":
                value = str(data.get(field, "")).strip()
                if value:
                    cfg["tiku"][key] = value
        # GUI 题库开关本身不写入 ini

    # 通知
    use_notify = data.get("notify_enabled") in (True, "true", "on", "1")
    if use_notify:
        cfg["notification"] = {}
        for field, (section, key, default) in FIELDS.items():
            if section == "notification":
                value = str(data.get(field, "")).strip()
                if value:
                    cfg["notification"][key] = value

    tmp = CONFIG_PATH.with_suffix(".ini.tmp")
    with open(tmp, "w", encoding="utf8") as f:
        cfg.write(f)
    os.replace(tmp, CONFIG_PATH)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(read_config())


@app.route("/api/save", methods=["POST"])
def api_save():
    if is_running():
        return jsonify(ok=False, msg="任务运行中, 请先停止再修改配置"), 400
    data = request.get_json(force=True, silent=True) or {}
    write_config(data)
    return jsonify(ok=True, msg="配置已保存")


@app.route("/api/start", methods=["POST"])
def api_start():
    global PROC
    with PROC_LOCK:
        if is_running():
            return jsonify(ok=False, msg="任务已在运行中"), 400

        data = request.get_json(force=True, silent=True) or {}
        try:
            write_config(data)
        except Exception as e:
            return jsonify(ok=False, msg=f"写配置失败: {e}"), 500

        # -u 关闭缓冲, 否则管道模式下子进程输出会积压看不到日志
        cmd = [sys.executable, "-u", str(PROJECT_DIR / "main.py"), "-c", str(CONFIG_PATH)]
        creationflags = 0
        if os.name == "nt":
            # 独立进程组, 方便整组终止
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        # 强制子进程按 UTF-8 输出中文: 中文 Windows 默认是 GBK, 不强制就会乱码
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=env,
        )
        PROC = proc

    threading.Thread(target=reader_thread, args=(proc,), daemon=True).start()
    broadcast("system", f"任务已启动 (PID {proc.pid}), 配置文件: {CONFIG_PATH.name}")
    print(f"[webgui] 刷课任务已启动 (PID {proc.pid})", flush=True)
    return jsonify(ok=True, pid=proc.pid)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with PROC_LOCK:
        proc = PROC
        if proc is None or proc.poll() is not None:
            return jsonify(ok=False, msg="当前没有运行中的任务"), 400
        proc.terminate()
    broadcast("system", "已发送停止信号, 等待子进程退出...")
    return jsonify(ok=True)


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify(running=is_running())


@app.route("/api/courses", methods=["POST"])
def api_courses():
    """用当前填写的账号登录, 拉取课程列表供用户选择课程 ID。"""
    if is_running():
        return jsonify(ok=False, msg="任务运行中, 无法重复登录"), 400
    data = request.get_json(force=True, silent=True) or {}
    try:
        write_config(data)
        # 延迟导入, 避免缺少依赖时整个网站打不开
        from api.base import Chaoxing, Account
        from api.answer import Tiku

        common, _, _ = load_config_for_gui()
        use_cookies = common.get("use_cookies", False)
        account = Account(common.get("username", ""), common.get("password", ""))
        tiku = Tiku.get_tiku_from_config({}, config_path=str(CONFIG_PATH))
        tiku.init_tiku()
        cx = Chaoxing(account=account, tiku=tiku)

        state = cx.login(login_with_cookies=use_cookies)
        if not state.get("status"):
            return jsonify(ok=False, msg=f"登录失败: {state.get('msg', '未知错误')}"), 200

        courses = cx.get_course_list() or []
        result = [{
            "courseId": str(c.get("courseId", "")),
            "clazzId": str(c.get("clazzId", "")),
            "title": c.get("title", ""),
        } for c in courses]
        broadcast("system", f"拉取到 {len(result)} 个班级课程, 已填入课程 ID 框, 可删改后再开始")
        return jsonify(ok=True, courses=result)
    except Exception as e:
        return jsonify(ok=False, msg=f"读取课程失败: {type(e).__name__}: {e}"), 200


def load_config_for_gui():
    """复用 main.py 的配置解析, 返回 (common, tiku, notification)。"""
    from main import load_config_from_file
    return load_config_from_file(str(CONFIG_PATH))


@app.route("/api/stream")
def api_stream():
    def generate():
        q: queue.Queue = queue.Queue(maxsize=2000)
        CLIENTS.add(q)
        try:
            # 连接建立先补发缓存日志
            with RING_LOCK:
                backlog = list(RING)
            for kind, text in backlog:
                yield f"event: {kind}\ndata: {_sse_escape(text)}\n\n"
            yield f"event: status\ndata: {{\"running\": {str(is_running()).lower()}}}\n\n"

            while True:
                try:
                    kind, text = q.get(timeout=15)
                    yield f"event: {kind}\ndata: {_sse_escape(text)}\n\n"
                except queue.Empty:
                    # 心跳, 防止代理断开连接
                    yield ": ping\n\n"
        finally:
            CLIENTS.discard(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


if __name__ == "__main__":
    import atexit
    import socket

    # 黑窗口按系统代码页(中文 Windows 为 GBK)渲染, 保持默认编码即可正确显示中文;
    # 仅把出错策略改为 replace, 避免个别特殊字符触发崩溃
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    PORT = 5000
    # 单实例保护: 端口已被占用说明网站已在运行, 直接退出,
    # 避免两个实例抢占同一端口导致请求时好时坏
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            print("=" * 60)
            print(f"端口 {PORT} 已被占用 —— 网站很可能已经在运行了。")
            print("请直接在浏览器打开: http://127.0.0.1:5000")
            print("如需重启, 先双击「关闭网站.bat」再运行本程序。")
            print("=" * 60)
            time.sleep(8)
            sys.exit(1)

    # 记录进程号, 供「关闭网站.bat」精确停止; 残留的过期 PID 直接覆盖
    PID_PATH = BASE_DIR / "webgui.pid"
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: PID_PATH.unlink(missing_ok=True))

    print("超星学习通图形化界面已启动, 请用浏览器访问: http://127.0.0.1:5000")
    print("网站目录:", BASE_DIR)
    print("刷课主程序目录:", PROJECT_DIR)
    print("配置文件位置:", CONFIG_PATH)
    print("关闭方式: 双击「关闭网站.bat」, 或直接关闭本窗口")
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False)
