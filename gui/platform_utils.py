# -*- coding: utf-8 -*-
"""与操作系统相关的小功能：系统通知、防止休眠、在文件管理器中显示文件。都是尽力而为，失败不影响刷课。"""
import os
import subprocess
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")


def notify(title: str, message: str) -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    try:
        if IS_MAC:
            subprocess.Popen(["/usr/bin/osascript", "-e",
                              f'display notification "{esc(message)}" with title "{esc(title)}" sound name "Glass"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["notify-send", title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def keep_awake_for(pid: int):
    """进程 pid 运行期间阻止系统休眠（macOS: caffeinate；Linux: systemd-inhibit）。返回守护进程或 None。"""
    try:
        if IS_MAC:
            return subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(pid)])
        if sys.platform.startswith("linux"):
            return subprocess.Popen(
                ["systemd-inhibit", "--what=sleep", "--why=chaoxing", "--mode=block",
                 "tail", f"--pid={pid}", "-f", "/dev/null"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return None


def keep_awake_self() -> None:
    """Windows 下由刷课进程自己声明不休眠，进程退出后自动失效。"""
    if not IS_WIN:
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:
        pass


def reveal(path: Path) -> None:
    """在文件管理器中显示文件或打开文件夹。"""
    path = Path(path)
    if not path.exists():
        return
    try:
        if IS_MAC:
            subprocess.Popen(["/usr/bin/open", str(path)] if path.is_dir() else ["/usr/bin/open", "-R", str(path)])
        elif IS_WIN:
            if path.is_dir():
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
    except Exception:
        pass


def open_url(url: str) -> None:
    import webbrowser
    webbrowser.open(url)
