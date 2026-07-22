# -*- coding: utf-8 -*-
import os.path
import threading

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


def use_cookies() -> dict:
    with cookie_lock:
        if not os.path.exists(gc.COOKIES_PATH):
            return {}

        cookies = {}
        try:
            with open(gc.COOKIES_PATH, "r") as f:
                buffer = f.read().strip()
                if not buffer:
                    return {}
                for item in buffer.split(";"):
                    item = item.strip()
                    if not item:
                        continue
                    parts = item.split("=", 1)
                    if len(parts) == 2:
                        cookies[parts[0]] = parts[1]
        except Exception:
            return {}

        return cookies
