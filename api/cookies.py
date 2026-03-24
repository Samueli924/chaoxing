# -*- coding: utf-8 -*-
import os.path
from typing import Protocol

from api.config import GlobalConst as gc


class CookieContainer(Protocol):
    def items(self): ...


class CookieSession(Protocol):
    cookies: CookieContainer


def save_cookies(session: CookieSession):
    buffer=""
    with open(gc.COOKIES_PATH, "w") as f:
        for k, v in session.cookies.items():
            buffer += f"{k}={v};"
        buffer = buffer.removesuffix(";")
        f.write(buffer)


def use_cookies() -> dict:
    if not os.path.exists(gc.COOKIES_PATH):
        return {}

    cookies={}
    with open(gc.COOKIES_PATH, "r") as f:
        buffer = f.read().strip()
        for item in buffer.split(";"):
            k, v = item.strip().split("=")
            cookies[k] = v

    return cookies
