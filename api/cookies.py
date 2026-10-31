# -*- coding: utf-8 -*-
import os.path
import threading
from typing import Optional

import requests

from api.config import GlobalConst as gc

# 定义全局 Cookie 文件锁，保证读写绝对安全
cookie_lock = threading.RLock()


def save_cookies(session: requests.Session):
    with cookie_lock:
        buffer = ""
        for k, v in session.cookies.items():
            buffer += f"{k}={v};"
        buffer = buffer.removesuffix(";")
        with open(gc.COOKIES_PATH, "w") as f:
            f.write(buffer)


def parse_cookie_string(raw: Optional[str]) -> dict[str, str]:
    """解析 `k=v; k=v` 形式的 cookie 字符串."""
    cookies = {}
    for item in str(raw or "").split(";"):
        key, sep, value = item.strip().partition("=")
        if sep and key.strip():
            cookies[key.strip()] = value.strip()
    return cookies


def use_cookies() -> dict:
    with cookie_lock:
        if not os.path.exists(gc.COOKIES_PATH):
            return {}

        try:
            with open(gc.COOKIES_PATH, "r") as f:
                return parse_cookie_string(f.read())
        except Exception:
            return {}
