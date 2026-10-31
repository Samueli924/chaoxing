import configparser
import os
import shutil
import threading
from typing import Any


class ConfigManager:
    """管理指定 INI 文件的全量配置读取与原子化更新."""

    BOOL_KEYS = {
        "use_cookies", "work_redo_enabled", "add_learning_count",
        "check_llm_connection", "submit", "likeapi_search",
        "likeapi_vision", "likeapi_retry", "topic_auto_reply"
    }

    INT_KEYS = {
        "jobs", "work_max_retries", "target_count",
        "likeapi_retry_times", "go_retry_times", "min_interval_seconds",
        "daily_watch_limit_minutes"
    }

    FLOAT_KEYS = {
        "speed", "retry_interval", "cover_rate", "delay",
        "go_min_interval", "go_retry_backoff"
    }

    def __init__(self, config_path: str, template_path: str = "config_template.ini") -> None:
        """初始化配置管理器并在缺少目标配置时从模板同步."""
        self.config_path = config_path
        self.template_path = template_path
        self._lock = threading.Lock()
        if not os.path.exists(self.config_path) and os.path.exists(self.template_path):
            temp_file = None
            try:
                target_dir = os.path.dirname(os.path.abspath(self.config_path)) or "."
                os.makedirs(target_dir, exist_ok=True)
                temp_file = f"{self.config_path}.{os.getpid()}.{threading.get_ident()}.tmp"
                shutil.copyfile(self.template_path, temp_file)
                try:
                    os.replace(temp_file, self.config_path)
                except OSError:
                    pass
            except Exception:
                pass
            finally:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except OSError:
                        pass

    def get_course_list(self) -> list[str]:
        with self._lock:
            cfg = self._read_ini(self.config_path)
            val = cfg.get("common", "course_list", fallback="")
            if not val:
                return []
            return [
                item.strip()
                for item in val.split(",")
                if item.strip() and item.strip().lower() != "xxx"
            ]

    def set_course_list(self, course_ids: list[str]) -> None:
        with self._lock:
            cfg = self._read_ini(self.config_path)
            if not cfg.has_section("common"):
                cfg.add_section("common")
            cfg.set("common", "course_list", ",".join(course_ids))
            self._write_ini(cfg, self.config_path)

    def get_full_config(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            template_cfg = self._read_ini(self.template_path) if os.path.exists(self.template_path) else None
            target_cfg = self._read_ini(self.config_path)

            sections = ["common", "tiku", "notification"]
            result: dict[str, dict[str, Any]] = {}

            for sec in sections:
                result[sec] = {}
                if template_cfg and template_cfg.has_section(sec):
                    for k, v in template_cfg.items(sec):
                        if str(v).strip() in ("xxx", "xxx,xxx,xxx", "XXXXXX"):
                            result[sec][k] = ""
                        else:
                            result[sec][k] = self._cast_value(k, v)

                if target_cfg.has_section(sec):
                    for k, v in target_cfg.items(sec):
                        if str(v).strip() in ("xxx", "xxx,xxx,xxx", "XXXXXX"):
                            result[sec][k] = ""
                        else:
                            result[sec][k] = self._cast_value(k, v)

            return result

    def update_full_config(self, config_dict: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            cfg = self._read_ini(self.config_path)

            for sec, items in config_dict.items():
                if not isinstance(items, dict):
                    continue
                if not cfg.has_section(sec):
                    cfg.add_section(sec)
                for k, v in items.items():
                    if isinstance(v, bool):
                        val_str = "true" if v else "false"
                    elif isinstance(v, list):
                        val_str = ",".join(str(x) for x in v)
                    elif v is None:
                        val_str = ""
                    else:
                        val_str = str(v)
                    cfg.set(sec, str(k), val_str)

            self._write_ini(cfg, self.config_path)

    @classmethod
    def _cast_value(cls, key: str, value: str) -> Any:
        if value is None:
            return ""
        val_str = str(value).strip()
        if key in cls.BOOL_KEYS:
            return val_str.lower() in ("1", "true", "yes", "on")
        if key in cls.INT_KEYS:
            try:
                return int(val_str)
            except ValueError:
                return 0
        if key in cls.FLOAT_KEYS:
            try:
                return float(val_str)
            except ValueError:
                return 0.0
        return val_str

    @staticmethod
    def _read_ini(path: str) -> configparser.ConfigParser:
        cfg = configparser.ConfigParser(interpolation=None)
        if os.path.exists(path):
            cfg.read(path, encoding="utf8")
        return cfg

    @staticmethod
    def _write_ini(cfg: configparser.ConfigParser, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf8") as f:
            cfg.write(f)
        os.replace(temp_path, path)
