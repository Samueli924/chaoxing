import sys

from loguru import logger
from tqdm import tqdm

tqdm_stream = sys.stderr

def tqdm_sink(msg):
    tqdm.write(msg.rstrip(), file=tqdm_stream)
    tqdm_stream.flush()

logger.remove()
logger.add(tqdm_sink, colorize=True, enqueue=True)
logger.add(
    "chaoxing.log",
    rotation="10 MB",
    retention="14 days",
    encoding="utf-8",
    level="TRACE",
)
