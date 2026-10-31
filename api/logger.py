import logging
import os
import sys

from loguru import logger
from tqdm import tqdm

tqdm_stream = sys.stderr

if getattr(sys, "frozen", False):
    BASE_DIR = os.getcwd()
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_LOG_DIR = os.path.join(BASE_DIR, "logs", "cli")
GUI_LOG_DIR = os.path.join(BASE_DIR, "logs", "gui")

os.makedirs(CLI_LOG_DIR, exist_ok=True)
os.makedirs(GUI_LOG_DIR, exist_ok=True)

CLI_LOG_FILE = os.path.join(CLI_LOG_DIR, "chaoxing.log")
GUI_LOG_FILE = os.path.join(GUI_LOG_DIR, "webui.log")

log_buffer: list = []
MAX_LOG_BUFFER_SIZE = 1000

_current_log_level = "INFO"


def get_log_level() -> str:
    """获取当前 WebUI 看板日志展示级别."""
    return _current_log_level


def set_log_level(level: str) -> None:
    """动态更新 WebUI 看板日志级别."""
    global _current_log_level
    lvl = level.upper()
    if lvl in ("TRACE", "DEBUG", "INFO", "WARNING", "ERROR"):
        _current_log_level = lvl


def tqdm_sink(msg):
    manual_locked = False
    try:
        if "api.answer" in sys.modules:
            tiku_manual = getattr(sys.modules["api.answer"], "TikuManual", None)
            if tiku_manual and getattr(tiku_manual, "_manual_lock", None):
                manual_locked = tiku_manual._manual_lock.locked()
    except (AttributeError, KeyError, ImportError):
        pass

    if manual_locked:
        if len(log_buffer) < MAX_LOG_BUFFER_SIZE:
            log_buffer.append(msg)
    else:
        if log_buffer:
            for buffered_msg in log_buffer:
                tqdm.write(buffered_msg.rstrip(), file=tqdm_stream)
            log_buffer.clear()
        tqdm.write(msg.rstrip(), file=tqdm_stream)
    tqdm_stream.flush()

    if "api.task_runner" in sys.modules:
        hub = sys.modules["api.task_runner"].TaskStateHub()
        if hub.is_web_mode():
            rec = msg.record
            hub.append_log(rec["level"].name, rec["message"])


def setup_webui_logging() -> None:
    """切换为 WebUI 专属日志：控制台静默，输出至 logs/gui/webui.log 及前端看板队列."""
    logger.remove()

    def web_hub_sink(msg):
        if "api.task_runner" in sys.modules:
            rec = msg.record
            try:
                min_no = logger.level(_current_log_level).no
                if rec["level"].no < min_no:
                    return
            except Exception:
                pass
            hub = sys.modules["api.task_runner"].TaskStateHub()
            hub.append_log(rec["level"].name, rec["message"])

    logger.add(web_hub_sink, enqueue=True)
    logger.add(GUI_LOG_FILE, rotation="10 MB", level="DEBUG", encoding="utf-8")

    # 屏蔽 Werkzeug 控制台回显，重定向至 GUI 日志文件
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.propagate = False
    for handler in list(werkzeug_logger.handlers):
        werkzeug_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    file_handler = logging.FileHandler(GUI_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    werkzeug_logger.addHandler(file_handler)


def setup_cli_logging() -> None:
    """恢复 CLI 日志模式：控制台 tqdm 输出并持久化至 logs/cli/chaoxing.log."""
    logger.remove()
    logger.add(tqdm_sink, colorize=True, enqueue=True)
    logger.add(CLI_LOG_FILE, rotation="10 MB", level="TRACE", encoding="utf-8")


# 默认按 CLI 模式初始化
setup_cli_logging()
