class LoginError(Exception):
    """登录失败或登录状态失效."""


class InputFormatError(Exception):
    """用户输入格式错误."""


class FontDecodeError(Exception):
    """加密字体解析失败."""
