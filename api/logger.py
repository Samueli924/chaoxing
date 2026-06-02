import sys

from loguru import logger
from tqdm import tqdm

tqdm_stream = sys.stderr

# 日志缓冲区，用于在手动答题时缓存后台日志，答题结束后统一输出
log_buffer = []
MAX_LOG_BUFFER_SIZE = 1000


def tqdm_sink(msg):
    manual_locked = False
    try:
        # 动态获取 api.answer 模块中的 TikuManual 锁，避免循环导入
        if 'api.answer' in sys.modules:
            TikuManual = getattr(sys.modules['api.answer'], 'TikuManual', None)
            if TikuManual and getattr(TikuManual, '_manual_lock', None):
                manual_locked = TikuManual._manual_lock.locked()
    except Exception:
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
logger.add(tqdm_sink, colorize=True, enqueue=True)
logger.add("chaoxing.log", rotation="10 MB", level="TRACE")
