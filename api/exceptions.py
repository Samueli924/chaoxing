try:
    from requests.exceptions import JSONDecodeError
except:  # noqa: E722
    from json import JSONDecodeError


class LoginError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class FormatError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)

class MaxRollBackError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)
        