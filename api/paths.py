# -*- coding: utf-8 -*-
"""
数据目录统一管理

用户数据（配置、账号、cookie）存放在用户主目录，而不是项目目录。
这样升级代码、git 操作、清理项目目录都不会影响用户配置。

默认位置：~/.chaoxing/
可用环境变量 CX_DATA_HOME 覆盖。

首次使用时会自动从项目目录迁移旧文件（config.ini / accounts/ / cookies.txt）。
"""

import os
import shutil

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    """用户数据根目录（不存在则创建）"""
    d = os.environ.get("CX_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".chaoxing"
    )
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except Exception:
        pass
    return d


def config_path():
    return os.path.join(data_dir(), "config.ini")


def accounts_dir():
    d = os.path.join(data_dir(), "accounts")
    os.makedirs(d, exist_ok=True)
    return d


def cookies_dir():
    d = os.path.join(accounts_dir(), "cookies")
    os.makedirs(d, exist_ok=True)
    return d


def legacy_cookies_path():
    return os.path.join(data_dir(), "cookies.txt")


def reviews_dir():
    """AI 生成内容的复核记录目录（Markdown + JSONL 索引）"""
    return os.path.join(data_dir(), "reviews")


def submissions_path():
    """已提交任务点记录：用于本地去重，避免平台完成状态延迟导致重复提交"""
    return os.path.join(data_dir(), "submissions.json")


def log_path():
    return os.path.join(data_dir(), "chaoxing.log")


def cache_path():
    """题库答案缓存文件"""
    return os.path.join(data_dir(), "cache.json")


def backups_dir():
    """配置备份目录"""
    d = os.path.join(data_dir(), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def backup_config(keep=15):
    """
    写入配置前先备份，保留最近 keep 份。
    这样即使被误覆盖（比如被测试脚本写坏），也能从 backups/ 恢复。
    """
    try:
        import time
        src = config_path()
        if not os.path.exists(src):
            return None
        dst = os.path.join(backups_dir(), "config-" + time.strftime("%Y%m%d-%H%M%S") + ".ini")
        # 同一秒内多次写入只保留第一份，避免刷屏
        if os.path.exists(dst):
            return dst
        shutil.copy2(src, dst)

        # 清理多余的旧备份
        files = sorted(
            (f for f in os.listdir(backups_dir()) if f.startswith("config-")),
            reverse=True,
        )
        for old in files[keep:]:
            try:
                os.remove(os.path.join(backups_dir(), old))
            except Exception:
                pass
        return dst
    except Exception:
        return None


def _migrate_once():
    """把项目目录里的旧数据搬到数据目录（只搬一次，不覆盖已有）"""
    try:
        # config.ini
        old_cfg = os.path.join(PROJECT_DIR, "config.ini")
        new_cfg = config_path()
        if os.path.exists(old_cfg) and not os.path.exists(new_cfg):
            shutil.copy2(old_cfg, new_cfg)

        # accounts/ 整个目录
        old_acc = os.path.join(PROJECT_DIR, "accounts")
        new_acc = accounts_dir()
        if os.path.isdir(old_acc):
            for item in os.listdir(old_acc):
                src = os.path.join(old_acc, item)
                dst = os.path.join(new_acc, item)
                if os.path.exists(dst):
                    continue
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

        # 旧 cookies.txt
        old_ck = os.path.join(PROJECT_DIR, "cookies.txt")
        new_ck = legacy_cookies_path()
        if os.path.exists(old_ck) and not os.path.exists(new_ck):
            shutil.copy2(old_ck, new_ck)

        # 旧答案缓存 cache.json
        old_cache = os.path.join(PROJECT_DIR, "cache.json")
        new_cache = cache_path()
        if os.path.exists(old_cache) and not os.path.exists(new_cache):
            shutil.copy2(old_cache, new_cache)
    except Exception:
        # 迁移失败不能影响主流程
        pass


def init():
    """启动时调用：确保数据目录存在并完成一次迁移"""
    d = data_dir()
    _migrate_once()
    return d
