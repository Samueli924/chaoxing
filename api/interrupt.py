# -*- coding: utf-8 -*-
"""
刷课过程中的一键终止

刷课时后台起一个线程监听键盘，用户按 q 或 Ctrl+C，立即终止程序。

实现方式：termios + select，不依赖任何第三方库。
只有在真正的终端里才启用；非交互环境（定时任务/管道）自动跳过。

**让出 stdin**：提交确认要调用 input() 时，必须先把监听线程停下来、把终端恢复成
行缓冲 + 回显，否则两者同抢 stdin——实测逐字输入 "yes" 会被吃成 "ye"/"ys"（按取消
处理），甚至让 input() 永久挂住、用户还看不到自己敲了什么。
用 stdin_for_prompt() 包住提示即可。
"""

import os
import sys
import threading
from contextlib import contextmanager

# 全局终止标志
_stop_event = threading.Event()
_watcher_started = False
_watcher_alive = False
_lock = threading.Lock()
# 轮次编号：避免上一轮的监听线程影响新一轮
_generation = 0

# 让出 stdin 的开关与回执
_pause = threading.Event()
_pause_ack = threading.Event()


def should_stop():
    """外部查询：是否已被要求终止"""
    return _stop_event.is_set()


def request_stop(reason=""):
    """请求终止（也可由别的模块调用）"""
    _stop_event.set()


def reset():
    """
    开始新一轮刷课前调用：清除终止标志、允许重新启动监听。

    没有这一步的话，用户上一次按 q 终止后，标志一直是 set 状态，
    下一次刷课会立刻停止。
    """
    global _watcher_started, _generation
    with _lock:
        _stop_event.clear()
        _generation += 1
        _watcher_started = False
        # 上一轮如果停在"让出 stdin"的状态，别把它带进新一轮
        _pause.clear()
        _pause_ack.set()


def _watch_stdin(my_generation):
    """后台线程：读键盘，遇到 q 或 Ctrl+C 就请求终止

    _pause 置位时让出 stdin：先把终端属性恢复成普通行缓冲 + 回显，
    再停止读取，让 input()（提交确认）拿到完整、能看见的输入。
    """
    global _watcher_alive
    import select
    import termios
    import time
    import tty

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except Exception:
        _watcher_alive = False
        _pause_ack.set()
        return

    paused_here = False
    try:
        tty.setcbreak(fd)   # 按键立即到达程序，不用等回车
        while not _stop_event.is_set() and my_generation == _generation:
            if _pause.is_set():
                if not paused_here:
                    try:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    except Exception:
                        pass
                    paused_here = True
                    _pause_ack.set()
                time.sleep(0.05)
                continue
            if paused_here:
                try:
                    tty.setcbreak(fd)
                except Exception:
                    pass
                paused_here = False
                _pause_ack.clear()
            try:
                r, _, _ = select.select([fd], [], [], 0.3)
            except Exception:
                break
            if not r:
                continue
            try:
                ch = os.read(fd, 1)
            except Exception:
                break
            if not ch:
                break
            try:
                c = ch.decode("utf-8", "ignore").lower()
            except Exception:
                continue
            if c == "q" or c == chr(3):
                _stop_event.set()
                print()
                print()
                print("  >>> 收到退出指令，正在终止刷课...")
                print()
                break
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass
        _watcher_alive = False
        _pause_ack.set()


def pause_watcher(timeout=2.0):
    """暂停键盘监听并等它真的让出 stdin；返回是否已经让出。

    没有监听线程时（非交互终端、或还没 start_watcher）直接返回 True。
    """
    if not _watcher_alive:
        return True
    _pause.set()
    return _pause_ack.wait(timeout if timeout and timeout > 0 else 0.01)


def resume_watcher():
    """恢复键盘监听（确认提示结束后调用）"""
    _pause.clear()


@contextmanager
def stdin_for_prompt():
    """确认提示期间把 stdin 让给 input()：先暂停监听线程，结束后再恢复。"""
    paused = pause_watcher()
    try:
        yield paused
    finally:
        resume_watcher()


def start_watcher():
    """启动键盘监听（只在交互终端里生效，重复调用无副作用）"""
    global _watcher_started, _watcher_alive
    with _lock:
        if _watcher_started:
            return False
        _watcher_started = True

    try:
        if not sys.stdin.isatty():
            return False
    except Exception:
        return False

    if os.name == "nt":
        return False

    _pause.clear()
    _pause_ack.clear()
    _watcher_alive = True
    t = threading.Thread(target=_watch_stdin, args=(_generation,), daemon=True)
    t.start()
    return True


def wait_stop(timeout=None):
    """等待终止信号（给需要阻塞的地方用）"""
    return _stop_event.wait(timeout)


def print_hint():
    """刷课前提示怎么退出（一行，不画横幅）"""
    print("  随时按 q 停止（立即生效，不用回车）；也可以 Ctrl + C。")
