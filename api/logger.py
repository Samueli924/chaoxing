import sys

from loguru import logger
from tqdm import tqdm

from api.config import data_path
from api.runtime import interactive_lock

tqdm_stream = sys.stderr
LOG_FILE = data_path("chaoxing.log")

# 日志缓冲区：等待用户在终端输入（手动答题/询问）时暂存后台日志，输入结束后统一输出
log_buffer = []
MAX_LOG_BUFFER_SIZE = 1000

CONSOLE_FORMAT = "<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>"


def tqdm_sink(msg):
    if interactive_lock.locked():
        if len(log_buffer) < MAX_LOG_BUFFER_SIZE:
            log_buffer.append(msg)
        return
    if log_buffer:
        for buffered_msg in log_buffer:
            tqdm.write(buffered_msg.rstrip(), file=tqdm_stream)
        log_buffer.clear()
    tqdm.write(msg.rstrip(), file=tqdm_stream)
    tqdm_stream.flush()


_handler_ids: list[int] = []


def setup_logging(verbose: bool = False) -> None:
    """配置日志输出.

    终端默认输出 INFO 级别，开启 --verbose 后输出 DEBUG；
    日志文件默认记录 DEBUG，开启 --verbose 后记录 TRACE（包含原始网页内容，便于排错）。
    """
    for handler_id in _handler_ids:
        try:
            logger.remove(handler_id)
        except ValueError:
            pass
    _handler_ids.clear()
    _handler_ids.append(
        logger.add(tqdm_sink, level="DEBUG" if verbose else "INFO", colorize=True, enqueue=True,
                   format=CONSOLE_FORMAT)
    )
    _handler_ids.append(
        logger.add(LOG_FILE, level="TRACE" if verbose else "DEBUG", rotation="10 MB", retention=3,
                   encoding="utf-8", enqueue=True)
    )


logger.remove()
setup_logging(verbose=False)
