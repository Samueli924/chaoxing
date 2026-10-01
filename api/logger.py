import os
import sys

from loguru import logger
from tqdm import tqdm
from api.privacy import patch_record

tqdm_stream = sys.stderr

# 日志缓冲区，用于在手动答题时缓存后台日志，答题结束后统一输出
log_buffer = []
MAX_LOG_BUFFER_SIZE = 1000

# 刷课期间的控制台静音开关。
# 刷课时打开：控制台只显示 WARNING 及以上，避免 TRACE/DEBUG 刷屏；
# 日志文件默认记 DEBUG（够排查且不刷屏），需要逐请求排查时用
# 环境变量 CX_LOG_LEVEL=TRACE 打开全量。
_quiet = False


def set_quiet(enabled: bool):
    """刷课期间开启/关闭控制台静音"""
    global _quiet
    _quiet = bool(enabled)


def is_quiet() -> bool:
    return _quiet


def _console_filter(record) -> bool:
    """静音时过滤掉 WARNING 以下的日志（文件日志不受影响）"""
    # 用 log_file_only() 发的日志只进文件，控制台由 print 统一输出，避免同一句话出现两遍
    if record["extra"].get("file_only"):
        return False
    try:
        if _quiet:
            # 刷课期间：只留 WARNING 以上
            return record["level"].no >= logger.level("WARNING").no
        # 非刷课阶段：控制台只显示 INFO 以上，DEBUG/TRACE 只进日志文件
        return record["level"].no >= logger.level("INFO").no
    except Exception:
        return True


def _console_format(record) -> str:
    """
    控制台输出格式：去掉时间戳、模块名、行号，只保留可读信息。

      非刷课阶段：  消息内容
      刷课阶段：    ⚠ 警告 / ✘ 错误（且只显示 WARNING 及以上）

    【重要】loguru 会把这里返回的字符串再当成模板做一次 format_map，
    因此消息里原生的 { } 必须转义，否则会抛 KeyError（例如 API 返回的
    JSON 报错里带 {'error': ...} 就会让日志线程崩溃）。
    """
    level = record["level"].name
    msg = str(record["message"]).rstrip()

    if _quiet:
        # 刷课阶段：极简格式，只可能出现警告和错误
        icon = "⚠" if level == "WARNING" else "✘"
        text = "  " + icon + " " + msg
    elif level in ("ERROR", "CRITICAL"):
        text = "  ✘ " + msg
    elif level == "WARNING":
        text = "  ⚠ " + msg
    else:
        text = "  " + msg

    # 转义花括号，交给 loguru 的 format_map 还原成字面量
    text = text.replace("{", "{{").replace("}", "}}")
    return text + chr(10)


def log_file_only(message, level="ERROR"):
    """
    只写日志文件，不在控制台显示。

    控制台的提示语统一用 print 输出（顺序确定、排版可控），
    日志文件里再留一份记录，避免同一句话在屏幕上出现两遍。
    """
    try:
        logger.bind(file_only=True).log(level, message)
    except Exception:
        pass


def tqdm_sink(msg):
    manual_locked = False
    try:
        # 动态获取 api.answer 模块中的 TikuManual 锁，避免循环导入
        if 'api.answer' in sys.modules:
            TikuManual = getattr(sys.modules['api.answer'], 'TikuManual', None)
            if TikuManual and getattr(TikuManual, '_manual_lock', None):
                manual_locked = TikuManual._manual_lock.locked()
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


logger.remove()
logger.configure(patcher=patch_record)
logger.add(tqdm_sink, colorize=False, enqueue=True, filter=_console_filter,
           format=_console_format, diagnose=False)

# 日志文件放在用户数据目录，升级代码不会丢掉历史日志
try:
    from api import paths as _paths
    _LOG_FILE = _paths.log_path()
except Exception:
    _LOG_FILE = "chaoxing.log"
logger.add(_LOG_FILE, rotation="10 MB",
           level=(os.environ.get("CX_LOG_LEVEL") or "DEBUG").strip().upper(),
           diagnose=False)
try:
    os.chmod(_LOG_FILE, 0o600)
except OSError:
    pass
