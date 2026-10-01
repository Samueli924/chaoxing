# -*- coding: utf-8 -*-
"""
多用户账号管理

把每个用户的账号密码单独保存在用户数据目录（~/.chaoxing/accounts/）下，互不干扰。
放在用户主目录而不是项目目录，升级代码 / git 操作都不会影响账号数据。
账号文件格式（ini）：
    [account]
    username = 13800000000
    password = xxxxx
    name     = 张三          ; 登录后自动记录，用于列表显示
    last_used = YYYY-MM-DD     ; 最后使用时间
"""

import configparser
import os
import re
import time

from api import paths
from api.configfile import read_config_file

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
# 账号目录：用户数据目录下的 accounts/（由 api.paths 统一管理）
ACCOUNTS_DIR = paths.accounts_dir()


def ensure_dir():
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)


def _safe_name(username):
    """用手机号当文件名，去掉不安全的字符"""
    return re.sub(r"[^0-9A-Za-z_\-]", "_", str(username).strip())


def account_path(username):
    return os.path.join(ACCOUNTS_DIR, _safe_name(username) + ".ini")


def save_account(username, password, name="", course_ids=None, last_plan=None):
    """保存（或更新）一个账号；未传的字段沿用已有值"""
    ensure_dir()
    path = account_path(username)
    username = str(username).strip()

    old = {}
    if os.path.exists(path):
        try:
            old = load_account(username) or {}
        except Exception:
            old = {}

    cfg = configparser.ConfigParser()
    cfg["account"] = {
        "username": username,
        "password": str(password),
        "name": name or old.get("name", ""),
        "last_used": time.strftime("%Y-%m-%d %H:%M"),
    }
    # 记住上次选的课程和方案，方便下次沿用
    cids = course_ids if course_ids is not None else old.get("course_ids", "")
    plan = last_plan if last_plan is not None else old.get("last_plan", "")
    if cids:
        cfg["account"]["course_ids"] = cids
    if plan:
        cfg["account"]["last_plan"] = plan

    with open(path, "w", encoding="utf8") as f:
        cfg.write(f)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def load_account(username):
    """
    读取一个账号，返回 dict 或 None。

    文件内容损坏（手改坏、写到一半断电等）时返回 None，
    而不是抛异常拖垮整个账号列表。
    """
    path = account_path(username)
    if not os.path.exists(path):
        return None
    cfg, _broken = read_config_file(path)
    if not cfg.has_section("account"):
        return None

    # 上次选的课程/任务点数，下次可沿用
    course_ids = cfg.get("account", "course_ids", fallback="")
    last_plan = cfg.get("account", "last_plan", fallback="")

    return {
        "username": cfg.get("account", "username", fallback=""),
        "password": cfg.get("account", "password", fallback=""),
        "name": cfg.get("account", "name", fallback=""),
        "last_used": cfg.get("account", "last_used", fallback=""),
        "course_ids": course_ids,
        "last_plan": last_plan,
    }


def list_accounts():
    """列出所有已保存的账号，最近使用的排前面"""
    ensure_dir()
    items = []
    for fn in os.listdir(ACCOUNTS_DIR):
        if not fn.endswith(".ini"):
            continue
        # 单个账号文件损坏不该让整个列表打不开，跳过即可
        try:
            acc = load_account(fn[:-4])
        except Exception:
            continue
        if acc and acc.get("username"):
            items.append(acc)
    items.sort(key=lambda a: a.get("last_used") or "", reverse=True)
    return items


def latest_run_config():
    """最近使用的账号专属配置路径（cx discuss 这类命令没给 -c 时用它）"""
    for item in list_accounts():
        path = os.path.join(ACCOUNTS_DIR, "run_" + _safe_name(item["username"]) + ".ini")
        if os.path.exists(path):
            return path
    return ""


def delete_account(username):
    path = account_path(username)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def touch(username, name=None):
    """更新最后使用时间（以及昵称）"""
    acc = load_account(username)
    if not acc:
        return
    save_account(acc["username"], acc["password"], name or acc.get("name", ""))
