# -*- coding: utf-8 -*-
"""把登录密码存进 macOS 钥匙串，而不是明文写在 config.ini 里。"""
import subprocess

SERVICE = "chaoxing-gui"


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_password(account: str, password: str) -> bool:
    # 通过 security -i 从标准输入传命令，避免密码出现在进程参数里
    cmd = f"add-generic-password -U -a {_quote(account)} -s {_quote(SERVICE)} -w {_quote(password)}\n"
    try:
        r = subprocess.run(["/usr/bin/security", "-i"], input=cmd, text=True,
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def load_password(account: str) -> str | None:
    if not account:
        return None
    try:
        r = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", account, "-s", SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.rstrip("\n")


def delete_password(account: str) -> None:
    if not account:
        return
    try:
        subprocess.run(
            ["/usr/bin/security", "delete-generic-password", "-a", account, "-s", SERVICE],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass
