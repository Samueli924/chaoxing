# -*- coding: utf-8 -*-
"""运行时共享状态：停止信号、进度信息与交互锁，命令行与网页控制台共用."""
import threading
import time
from typing import Any

# 等待用户在终端输入时持有此锁：日志会暂存、进度条会隐藏，避免打乱输入提示
interactive_lock = threading.Lock()


class Runtime:
    def __init__(self) -> None:
        """初始化停止信号与进度表."""
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}
        self._stage = ""
        self._counts: dict[str, int] = {}

    def reset(self) -> None:
        self.stop_event.clear()
        with self._lock:
            self._items.clear()
            self._stage = ""
            self._counts = {}

    def update_counts(self, **counts: int) -> None:
        with self._lock:
            self._counts.update(counts)

    def should_stop(self) -> bool:
        return self.stop_event.is_set()

    def request_stop(self) -> None:
        self.stop_event.set()

    def sleep(self, seconds: float) -> bool:
        """等待指定秒数；收到停止信号时提前返回 True."""
        if seconds <= 0:
            return self.stop_event.is_set()
        return self.stop_event.wait(seconds)

    def set_stage(self, text: str) -> None:
        with self._lock:
            self._stage = text

    def update_item(self, key: str, name: str, current: float, total: float, kind: str = "video") -> None:
        with self._lock:
            self._items[key] = {
                "name": name,
                "current": round(float(current), 1),
                "total": round(float(total), 1),
                "kind": kind,
                "updated": time.time(),
            }

    def remove_item(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stage": self._stage,
                "counts": dict(self._counts),
                "items": [dict(v, key=k) for k, v in self._items.items()],
            }


runtime = Runtime()
