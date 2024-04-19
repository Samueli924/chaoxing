from loguru import logger

try:
    from requests.exceptions import JSONDecodeError
except:  # noqa: E722
    from json import JSONDecodeError

class BaseException(Exception):
    def __init__(self, _msg: str = None):
        if _msg:
            logger.error(_msg)


class LoginError(BaseException):
    pass


class FormatError(Exception):
    pass