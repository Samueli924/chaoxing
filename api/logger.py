from loguru import logger
from tqdm import tqdm
import sys

tqdm_stream = sys.stderr

def tqdm_sink(msg):
    tqdm.write(msg.rstrip(), file=tqdm_stream)
    tqdm_stream.flush()

logger.remove()
_console_sink_id = logger.add(tqdm_sink, colorize=True, enqueue=True, level="INFO")
logger.add("chaoxing.log", rotation="10 MB", level="TRACE")


def set_console_log_level(level: str):
    global _console_sink_id
    logger.remove(_console_sink_id)
    _console_sink_id = logger.add(tqdm_sink, colorize=True, enqueue=True, level=level)
