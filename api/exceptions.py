from loguru import logger

class BaseException(Exception):
    def __init__(self, _msg: str = None):
        if _msg:
            logger.error(_msg)

class LoginError(BaseException):
    pass

class FormatError(Exception):
    pass