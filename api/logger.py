from loguru import logger
from tqdm import tqdm
import sys

tqdm_stream = sys.stdout

def tqdm_sink(msg):
    tqdm.write(msg.rstrip(), file=tqdm_stream)
    tqdm_stream.flush()

logger.remove()
logger.add(tqdm_sink, colorize=True, enqueue=True)
logger.add("chaoxing.log", rotation="10 MB", level="TRACE")
