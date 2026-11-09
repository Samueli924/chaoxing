# -*- coding: utf-8 -*-
"""
把登录密码存进系统凭据库，而不是明文写在配置文件里。
macOS 使用钥匙串（security 命令）；其他系统在安装了 keyring 库时使用它
（Windows 凭据管理器 / Linux Secret Service），否则不保存密码，只靠 cookie 自动登录。
"""
import subprocess
import sys

SERVICE = "chaoxing-gui"

try:  # 可选依赖
    import keyring as _keyring  # type: ignore
except Exception:  # pragma: no cover
    _keyring = None

IS_MAC = sys.platform == "darwin"


def available() -> bool:
    return IS_MAC or _keyring is not None


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_password(account: str, password: str) -> bool:
    if not account:
        return False
    if IS_MAC:
        # 通过 security -i 从标准输入传命令，避免密码出现在进程参数里
        cmd = f"add-generic-password -U -a {_quote(account)} -s {_quote(SERVICE)} -w {_quote(password)}\n"
        try:
            r = subprocess.run(["/usr/bin/security", "-i"], input=cmd, text=True,
                               capture_output=True, timeout=10)
            return r.returncode == 0
        except Exception:
            return False
    if _keyring:
        try:
            _keyring.set_password(SERVICE, account, password)
            return True
        except Exception:
            return False
    return False


def load_password(account: str) -> str | None:
    if not account:
        return None
    if IS_MAC:
        try:
            r = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-a", account, "-s", SERVICE, "-w"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return None
        return r.stdout.rstrip("\n") if r.returncode == 0 else None
    if _keyring:
        try:
            return _keyring.get_password(SERVICE, account)
        except Exception:
            return None
    return None


def delete_password(account: str) -> None:
    if not account:
        return
    if IS_MAC:
        try:
            subprocess.run(["/usr/bin/security", "delete-generic-password", "-a", account, "-s", SERVICE],
                           capture_output=True, timeout=10)
        except Exception:
            pass
    elif _keyring:
        try:
            _keyring.delete_password(SERVICE, account)
        except Exception:
            pass
