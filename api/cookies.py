# -*- coding: utf-8 -*-
import os
import threading
from typing import Optional

import requests

from api.config import GlobalConst as gc

# 全局 Cookie 文件锁，保证读写安全
cookie_lock = threading.RLock()

# 学习通登录 cookie 的作用域，加载时统一设置，避免与服务器下发的同名 cookie 重复
COOKIE_DOMAIN = ".chaoxing.com"


def save_cookies(session: requests.Session, path: Optional[str] = None) -> None:
    path = path or gc.COOKIES_PATH
    with cookie_lock:
        pairs: dict[str, str] = {}
        for cookie in session.cookies:
            pairs[cookie.name] = cookie.value
        buffer = "; ".join(f"{k}={v}" for k, v in pairs.items())
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # cookies 等同于登录凭据，仅允许当前用户读写
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(buffer)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def parse_cookie_string(buffer: str) -> dict[str, str]:
    """解析 "k=v; k2=v2" 格式的 cookie 字符串，兼容从浏览器直接复制的 "Cookie: ..." 内容."""
    buffer = buffer.strip()
    if buffer.lower().startswith("cookie:"):
        buffer = buffer[len("cookie:"):]
    cookies: dict[str, str] = {}
    for item in buffer.replace("\n", ";").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def use_cookies(path: Optional[str] = None) -> dict[str, str]:
    path = path or gc.COOKIES_PATH
    with cookie_lock:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return parse_cookie_string(f.read())
        except (OSError, UnicodeDecodeError):
            return {}


def apply_cookies(session: requests.Session, cookies: dict[str, str]) -> None:
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=COOKIE_DOMAIN, path="/")


def get_cookie(session: requests.Session, name: str, default=None):
    """安全读取 cookie：同名 cookie 存在多个作用域时不抛出 CookieConflictError."""
    for cookie in session.cookies:
        if cookie.name == name:
            return cookie.value
    return default
