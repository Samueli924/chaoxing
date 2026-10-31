import configparser
import glob
import json
import os
import sys
import threading
import time
from typing import Optional

from api.cookies import parse_cookie_string


def extract_uid_from_data(data: dict) -> str:
    uid = str(data.get("uid") or "").strip()
    if uid and uid.isdigit():
        return uid
    cookies = parse_cookie_string(data.get("cookies"))
    for key in ("_uid", "UID"):
        value = cookies.get(key, "").strip()
        if value and value.isdigit():
            return value
    return ""


class AccountManager:
    """管理独立账号配置文件的存储与切换."""

    _lock = threading.Lock()

    @staticmethod
    def _safe_name(account_id: str, default: str = "") -> str:
        """过滤账号 ID 中的非法文件名字符."""
        return "".join(c for c in str(account_id) if c.isalnum() or c in ("_", "-")) or default

    def __init__(self, accounts_dir: str = "accounts", auto_import_legacy: bool = True) -> None:
        self.accounts_dir = accounts_dir
        os.makedirs(self.accounts_dir, exist_ok=True)
        self._active_account_id: Optional[str] = None
        if getattr(sys, "frozen", False):
            base_dir = os.getcwd()
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_dir = os.path.join(base_dir, "accounts")
        if auto_import_legacy and os.path.abspath(self.accounts_dir) == os.path.abspath(default_dir):
            self._import_legacy_if_needed()

    def _import_legacy_if_needed(self) -> None:
        """账号目录为空时从项目根目录迁移已有配置与Cookie."""
        ini_files = glob.glob(os.path.join(self.accounts_dir, "*.ini"))
        if ini_files:
            return

        if getattr(sys, "frozen", False):
            base_dir = os.getcwd()
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_file = os.path.join(base_dir, "config.ini")
        cookies_file = os.path.join(base_dir, "cookies.txt")

        legacy_data = {}
        username = ""

        if os.path.exists(cfg_file):
            cfg = configparser.ConfigParser(interpolation=None)
            try:
                cfg.read(cfg_file, encoding="utf8")
                if cfg.has_section("common"):
                    raw_common = dict(cfg.items("common"))
                    for k, v in raw_common.items():
                        if str(v).strip() not in ("xxx", "xxx,xxx,xxx", "XXXXXX"):
                            legacy_data[k] = v
                    raw_user = str(legacy_data.get("username", "")).strip()
                    if raw_user and raw_user != "xxx":
                        username = raw_user
            except Exception:
                pass

        has_cookies = False
        if os.path.exists(cookies_file):
            try:
                with open(cookies_file, "r", encoding="utf8") as f:
                    c_txt = f.read().strip()
                if c_txt:
                    legacy_data["cookies"] = c_txt
                    legacy_data["use_cookies"] = "true"
                    has_cookies = True
            except Exception:
                pass

        if username or has_cookies:
            self.save_account(username or "default", legacy_data)

    def list_accounts(self) -> list[dict]:
        ini_files = glob.glob(os.path.join(self.accounts_dir, "*.ini"))
        results = []
        for file_path in ini_files:
            file_name = os.path.basename(file_path)
            acc_id = os.path.splitext(file_name)[0]
            config = configparser.ConfigParser(interpolation=None)
            try:
                config.read(file_path, encoding="utf8")
            except configparser.Error as e:
                from api.logger import logger
                logger.error(f"配置文件解析失败 {file_path}: {e}")
                raise

            common_dict = dict(config.items("common")) if config.has_section("common") else {}
            uid = extract_uid_from_data(common_dict)

            # 统一迁移历史手机号文件至超星唯一UID命名
            if uid and acc_id != uid:
                new_path = os.path.join(self.accounts_dir, f"{uid}.ini")
                if not os.path.exists(new_path):
                    try:
                        os.replace(file_path, new_path)
                        file_path = new_path
                        file_name = f"{uid}.ini"
                        acc_id = uid
                    except OSError:
                        pass

            raw_username = config.get("common", "username", fallback="").strip()
            username = raw_username if raw_username and raw_username != "xxx" else (uid or acc_id)
            alias = config.get("common", "alias", fallback="").strip()
            results.append({
                "id": acc_id,
                "uid": uid or acc_id,
                "username": username,
                "alias": alias,
                "display_name": alias or uid or acc_id,
                "file": file_name,
                "path": file_path,
                "active": (acc_id == self._active_account_id),
            })

        if results and self._active_account_id is None:
            self._active_account_id = results[0]["id"]
            results[0]["active"] = True

        return results

    def get_active_account(self) -> Optional[dict]:
        accounts = self.list_accounts()
        if not accounts:
            return None
        for acc in accounts:
            if acc["id"] == self._active_account_id:
                cfg = configparser.ConfigParser(interpolation=None)
                cfg.read(acc["path"], encoding="utf8")
                res = dict(acc)
                if cfg.has_section("common"):
                    res.update(dict(cfg.items("common")))
                res["id"] = acc["id"]
                res["uid"] = acc["uid"]
                res["username"] = acc["username"]
                res["file"] = acc["file"]
                res["path"] = acc["path"]
                return res
        return None

    def switch_account(self, account_id: str) -> Optional[dict]:
        self._active_account_id = account_id
        return self.get_active_account()

    def delete_account(self, account_id: str) -> bool:
        """删除指定账号的配置文件."""
        safe_name = self._safe_name(account_id)
        if not safe_name:
            return False
        file_path = os.path.join(self.accounts_dir, f"{safe_name}.ini")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                return False
            if self._active_account_id == safe_name:
                self._active_account_id = None
                remaining = self.list_accounts()
                if remaining:
                    self._active_account_id = remaining[0]["id"]
            return True
        return False

    def set_alias(self, account_id: str, alias: str) -> bool:
        """写入用户自定义昵称，空字符串表示恢复默认展示."""
        name = str(alias).strip()
        safe_name = self._safe_name(account_id)
        if not safe_name:
            return False
        file_path = os.path.join(self.accounts_dir, f"{safe_name}.ini")
        if not os.path.exists(file_path):
            return False

        with self._lock:
            config = configparser.ConfigParser(interpolation=None)
            config.read(file_path, encoding="utf8")
            if not config.has_section("common"):
                config.add_section("common")
            if config.get("common", "alias", fallback="") == name:
                return True
            if name:
                config.set("common", "alias", name)
            else:
                config.remove_option("common", "alias")
            try:
                with open(file_path, "w", encoding="utf8") as f:
                    config.write(f)
            except OSError:
                return False
        return True

    def save_account(self, username: str, data: dict) -> str:
        # 提取超星原生UID作为文件名以合并扫码与账号登录配置
        uid = extract_uid_from_data(data)
        if not uid and str(username).strip().isdigit() and len(str(username).strip()) < 11:
            uid = str(username).strip()

        account_id = uid or username
        safe_name = self._safe_name(account_id, "default")
        file_path = os.path.join(self.accounts_dir, f"{safe_name}.ini")

        config = configparser.ConfigParser(interpolation=None)
        if os.path.exists(file_path):
            config.read(file_path, encoding="utf8")

        if not config.has_section("common"):
            config.add_section("common")

        if uid:
            config.set("common", "uid", uid)
        if "username" in data and str(data["username"]).strip():
            config.set("common", "username", str(data["username"]).strip())
        elif not config.has_option("common", "username") or not config.get("common", "username").strip():
            config.set("common", "username", username)

        for key, value in data.items():
            if value is not None and key != "username":
                config.set("common", str(key), str(value))

        with open(file_path, "w", encoding="utf8") as f:
            config.write(f)

        self._active_account_id = safe_name
        return file_path

    def get_daily_watched_seconds(self, username: str) -> float:
        """获取指定账号今日已观看视频的累计时长."""
        today_str = time.strftime("%Y-%m-%d")
        safe_name = self._safe_name(username, "default")
        stats_file = os.path.join(self.accounts_dir, "daily_watch.json")
        try:
            if os.path.exists(stats_file):
                with open(stats_file, "r", encoding="utf8") as f:
                    data = json.load(f)
                return float(data.get(f"{safe_name}_{today_str}", 0.0))
        except Exception:
            pass
        return 0.0

    def add_daily_watched_seconds(self, username: str, seconds: float) -> float:
        """累加指定账号今日观看视频时长并持久化."""
        today_str = time.strftime("%Y-%m-%d")
        safe_name = self._safe_name(username, "default")
        key = f"{safe_name}_{today_str}"
        stats_file = os.path.join(self.accounts_dir, "daily_watch.json")
        with self._lock:
            data = {}
            try:
                if os.path.exists(stats_file):
                    with open(stats_file, "r", encoding="utf8") as f:
                        data = json.load(f)
            except Exception:
                data = {}
            new_val = round(float(data.get(key, 0.0)) + float(seconds), 2)
            data[key] = new_val
            try:
                temp_file = f"{stats_file}.{os.getpid()}.tmp"
                with open(temp_file, "w", encoding="utf8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                try:
                    os.replace(temp_file, stats_file)
                except OSError:
                    # Windows文件系统短暂锁回退直接写
                    with open(stats_file, "w", encoding="utf8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except OSError:
                            pass
            except Exception:
                pass
            return new_val
