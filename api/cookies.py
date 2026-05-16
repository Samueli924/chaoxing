# -*- coding: utf-8 -*-
import os.path

import requests

from api.config import GlobalConst as gc


def save_cookies(session: requests.Session):
    buffer=""
    with open(gc.COOKIES_PATH, "w", encoding="utf8") as f:
        for k, v in session.cookies.items():
            buffer += f"{k}={v};"
        buffer = buffer.removesuffix(";")
        f.write(buffer)


def use_cookies() -> dict:
    if not os.path.exists(gc.COOKIES_PATH):
        return {}

    cookies={}
    with open(gc.COOKIES_PATH, "r", encoding="utf8") as f:
        buffer = f.read().strip()
        for item in buffer.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            cookies[k] = v

    return cookies
