from loguru import logger
logger.add("chaoxing.log", rotation="10 MB", level="TRACE")