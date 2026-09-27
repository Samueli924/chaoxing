# -*- coding: utf-8 -*-
"""配置加载.

优先级（后者覆盖前者）：内置默认值 < 配置文件 < 环境变量 < 命令行参数。
所有配置项都有默认值，最少只需要提供手机号和密码（也可以运行后再输入）。

环境变量：
    CHAOXING_USERNAME / CHAOXING_PASSWORD / CHAOXING_COURSE_LIST (或 CHAOXING_COURSES)
    CHAOXING_SPEED / CHAOXING_JOBS / CHAOXING_NOTOPEN_ACTION ... ([common] 中的任意配置项)
    CHAOXING_TIKU_<配置项>        例如 CHAOXING_TIKU_PROVIDER=TikuGo、CHAOXING_TIKU_SUBMIT=true
    CHAOXING_NOTIFICATION_<配置项> 例如 CHAOXING_NOTIFICATION_PROVIDER=ServerChan
    CHAOXING_CONFIG               配置文件路径
"""
import configparser
import os
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from api.config import DATA_DIR, PROJECT_ROOT
from api.logger import logger

ENV_PREFIX = "CHAOXING_"

COMMON_DEFAULTS: dict[str, Any] = {
    "use_cookies": False,
    "username": "",
    "password": "",
    "course_list": [],
    "speed": 1.0,
    "jobs": 4,
    "max_duration": 0,
    "notopen_action": "retry",
    "retry_interval": 1.0,
    "work_max_retries": 3,
    "add_learning_count": False,
    "target_count": 100,
}
NOTOPEN_ACTIONS = ("retry", "ask", "continue")
COMMON_ENV_ALIASES = {"courses": "course_list", "phone": "username"}

# 配置模板中的占位内容，视为未填写
_PLACEHOLDERS = {"手机号", "密码", "课程id", "your_username", "your_password", "username", "password"}


@dataclass
class Settings:
    common: dict[str, Any]
    tiku: dict[str, str] = field(default_factory=dict)
    notification: dict[str, str] = field(default_factory=dict)
    config_path: Optional[str] = None


def is_placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if len(text) >= 3 and set(text.lower()) <= {"x", "*"}:
        return True
    return text.lower() in _PLACEHOLDERS


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on"}


def app_dir() -> Path:
    """程序所在目录（打包为 exe 时为 exe 所在目录）."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def find_config_file(explicit: Optional[str] = None) -> Optional[Path]:
    """按顺序查找配置文件：-c 参数 > CHAOXING_CONFIG > 当前目录 > 数据目录 > 程序目录."""
    for candidate in (explicit, os.environ.get(f"{ENV_PREFIX}CONFIG")):
        if candidate:
            path = Path(candidate).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"找不到配置文件: {path}")
            return path
    seen = set()
    for directory in (Path.cwd(), DATA_DIR, app_dir()):
        path = (directory / "config.ini").resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.is_file():
            return path
    return None


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    # Windows 记事本保存的文件可能带 BOM，或使用 GBK 编码
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_config_file(path: Path) -> dict[str, dict[str, str]]:
    # 关闭插值：密码中出现 % 时 ConfigParser 默认会报错
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(_read_text(path), source=str(path))
    return {section.lower(): dict(parser.items(section)) for section in parser.sections()}


def env_overrides(environ: Optional[dict] = None) -> dict[str, dict[str, str]]:
    environ = os.environ if environ is None else environ
    sections: dict[str, dict[str, str]] = {"common": {}, "tiku": {}, "notification": {}}
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        key = name[len(ENV_PREFIX):].lower()
        if key.startswith("tiku_"):
            sections["tiku"][key[len("tiku_"):]] = value
        elif key.startswith("notification_"):
            sections["notification"][key[len("notification_"):]] = value
        else:
            key = COMMON_ENV_ALIASES.get(key, key)
            if key in COMMON_DEFAULTS:
                sections["common"][key] = value
    return sections


def split_course_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else re.split(r"[,，\s]+", str(value))
    return [str(item).strip() for item in items if str(item).strip() and not is_placeholder(item)]


def _number(key: str, value: Any, cast, default, minimum=None, maximum=None):
    try:
        number = cast(float(str(value).strip())) if cast is int else cast(str(value).strip())
        if not math.isfinite(number):
            raise ValueError("non-finite number")
    except (TypeError, ValueError, OverflowError):
        logger.warning(f"配置项 {key}={value!r} 无效，使用默认值 {default}")
        return default
    if minimum is not None and number < minimum:
        logger.warning(f"配置项 {key}={number} 小于最小值 {minimum}，已调整为 {minimum}")
        number = minimum
    if maximum is not None and number > maximum:
        logger.warning(f"配置项 {key}={number} 大于最大值 {maximum}，已调整为 {maximum}")
        number = maximum
    return number


def normalize_common(raw: dict[str, Any]) -> dict[str, Any]:
    common = dict(COMMON_DEFAULTS)
    for key, value in raw.items():
        if value is None or key not in COMMON_DEFAULTS:
            continue
        if isinstance(value, str) and not value.strip() and key not in ("username", "password"):
            continue
        if key in ("username", "password"):
            text = str(value).strip()
            common[key] = "" if is_placeholder(text) else text
        elif key == "course_list":
            common[key] = split_course_list(value)
        elif key == "speed":
            common[key] = _number(key, value, float, 1.0, 1.0, 2.0)
        elif key == "max_duration":
            common[key] = _number(key, value, int, 0, 0, 86400)
        elif key == "jobs":
            common[key] = _number(key, value, int, 4, 1, 16)
        elif key == "retry_interval":
            common[key] = _number(key, value, float, 1.0, 0.0, 60.0)
        elif key == "work_max_retries":
            common[key] = _number(key, value, int, 3, 0, 10)
        elif key == "target_count":
            common[key] = _number(key, value, int, 100, 1)
        elif key == "notopen_action":
            action = str(value).strip().lower()
            if action not in NOTOPEN_ACTIONS:
                logger.warning(f"配置项 notopen_action={value!r} 无效，可选 {'/'.join(NOTOPEN_ACTIONS)}，使用默认值 retry")
                action = "retry"
            common[key] = action
        elif key in ("use_cookies", "add_learning_count"):
            common[key] = to_bool(value)
    return common


def _clean_section(section: dict[str, Any]) -> dict[str, str]:
    cleaned = {}
    for key, value in section.items():
        text = "" if value is None else str(value).strip()
        cleaned[key.lower()] = "" if is_placeholder(text) else text
    return cleaned


def load_settings(config: Optional[str] = None, cli_common: Optional[dict[str, Any]] = None,
                  environ: Optional[dict] = None) -> Settings:
    path = find_config_file(config)
    file_sections = read_config_file(path) if path else {}
    if path:
        logger.info(f"已加载配置文件: {path}")
    env_sections = env_overrides(environ)

    raw_common: dict[str, Any] = {}
    raw_common.update(file_sections.get("common", {}))
    raw_common.update(env_sections["common"])
    raw_common.update({k: v for k, v in (cli_common or {}).items() if v is not None})

    return Settings(
        common=normalize_common(raw_common),
        tiku=_clean_section({**file_sections.get("tiku", {}), **env_sections["tiku"]}),
        notification=_clean_section({**file_sections.get("notification", {}), **env_sections["notification"]}),
        config_path=str(path) if path else None,
    )
