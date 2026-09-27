# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

# 项目根目录（源码运行时为仓库根目录；PyInstaller 打包后为解压出的临时目录）
PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

# 数据目录：保存 cookies.txt / cache.json / chaoxing.log，默认为当前工作目录，
# Docker 等部署场景可通过环境变量 CHAOXING_DATA_DIR 指定（例如 /data）
DATA_DIR = Path(os.environ.get("CHAOXING_DATA_DIR") or os.getcwd())


def resource_path(*parts: str) -> str:
    """返回随程序分发的资源文件路径，与当前工作目录无关.

    依次在打包目录 / 仓库根目录 / api 上级目录 / 当前目录中查找，
    以兼容源码运行、PyInstaller 打包和 pip 安装等不同布局。
    """
    candidates = [
        PROJECT_ROOT,
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
    ]
    seen = set()
    for base in candidates:
        if base in seen:
            continue
        seen.add(base)
        path = base.joinpath(*parts)
        if path.exists():
            return str(path)
    # 找不到时返回基于打包目录的路径（交由调用方处理不存在的情况）
    return str(PROJECT_ROOT.joinpath(*parts))


def data_path(name: str) -> str:
    """返回数据文件路径（目录在写入时再创建）."""
    return str(DATA_DIR / name)


class GlobalConst:
    AESKey = "u2oh6Vu^HWe4_AES"
    COOKIES_PATH = data_path("cookies.txt")

    # 全程使用同一个浏览器标识，避免不同请求出现不一致的 UA
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    )
    HEADERS = {
        "User-Agent": USER_AGENT,
        "sec-ch-ua": '"Chromium";v="140", "Google Chrome";v="140", "Not=A?Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    VIDEO_HEADERS = {
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=2025-0725-1842",
    }
    AUDIO_HEADERS = {
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/audio/index_new.html?v=2025-0725-1842",
    }

    # 默认请求超时（秒），单个请求可以显式覆盖
    REQUEST_TIMEOUT = 15
    THRESHOLD = 1

    LOGIN_PAGE = "https://passport2.chaoxing.com/login?fid=&newversion=true&refer=https%3A%2F%2Fi.chaoxing.com"
    LOGIN_URL = "https://passport2.chaoxing.com/fanyalogin"
    COURSE_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
    INTERACTION_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
