# -*- coding: utf-8 -*-
"""
Cookie 读写（按账号隔离）

【为什么按账号隔离】
原来所有账号共用一个 cookies.txt，A 登录写的 cookie 会被 B 覆盖，
一旦启用 cookie 登录，就可能拿着 B 的登录态去刷 A 的课（串号）。

现在每个账号有独立的 cookie 文件，从结构上杜绝串号：
    accounts/cookies/<手机号>.txt

未指定账号时（老的单人模式）仍回退到项目根目录的 cookies.txt，保持兼容。
"""

import os
import os.path
import re
import threading

import requests

from api import paths
from api.config import GlobalConst as gc

# 定义全局 Cookie 文件锁，保证读写绝对安全
cookie_lock = threading.RLock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# cookie 文件按账号隔离，统一放在用户数据目录下（~/.chaoxing/accounts/cookies/）
COOKIES_DIR = paths.cookies_dir()

# 当前会话使用的账号（由 main 在登录前设置）
_current_account = None


def _safe(name):
    return re.sub(r"[^0-9A-Za-z_\-]", "_", str(name).strip())


def set_current_account(username):
    """设置当前账号；之后 cookie 读写都会用这个账号专属的文件"""
    global _current_account
    _current_account = str(username).strip() if username else None


def current_account():
    return _current_account


def cookie_path(username=None):
    """返回该账号的 cookie 文件路径"""
    who = username or _current_account
    if who:
        os.makedirs(COOKIES_DIR, exist_ok=True)
        return os.path.join(COOKIES_DIR, _safe(who) + ".txt")
    return gc.COOKIES_PATH


def save_cookies(session: requests.Session, username=None):
    from api.privacy import register_secret
    for value in session.cookies.values():
        register_secret(value)
    with cookie_lock:
        buffer = ""
        for k, v in session.cookies.items():
            buffer += f"{k}={v};"
        buffer = buffer.removesuffix(";")
        path = cookie_path(username)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            f.write(buffer)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass


def use_cookies(username=None) -> dict:
    with cookie_lock:
        path = cookie_path(username)
        if not os.path.exists(path):
            return {}
        cookies = {}
        try:
            with open(path, "r") as f:
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
        from api.privacy import register_secret
        for value in cookies.values():
            register_secret(value)
        return cookies


def clear_cookies(username=None):
    """清掉某账号的 cookie（用于强制重新登录）"""
    with cookie_lock:
        path = cookie_path(username)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except Exception:
                return False
        return False
