# -*- coding: utf-8 -*-
"""
多账号排队调度：限制同时运行的账号数量，并让相邻两次启动之间随机间隔一段时间。
纯逻辑，不涉及进程和网络，方便单元测试。
"""
import random
import threading
import time
from typing import Callable, Optional


class Scheduler:
    def __init__(self, max_parallel: int = 2, stagger: tuple[float, float] = (120, 300),
                 clock: Callable[[], float] = time.time, rng: Optional[random.Random] = None):
        self._lock = threading.RLock()
        self._clock = clock
        self._rng = rng or random.Random()
        self.queue: list[str] = []
        self.last_start: Optional[float] = None
        self.gap = 0.0  # 上次启动后需要等待的秒数（启动时随机生成）
        self.max_parallel = 1
        self.stagger = (0.0, 0.0)
        self.configure(max_parallel, stagger)

    def configure(self, max_parallel: int, stagger: tuple[float, float]):
        with self._lock:
            self.max_parallel = max(1, int(max_parallel))
            lo, hi = (max(0.0, float(x)) for x in stagger)
            self.stagger = (min(lo, hi), max(lo, hi))
            # 已经生成的间隔不能超过新的上限
            self.gap = min(self.gap, self.stagger[1])

    def enqueue(self, item: str) -> bool:
        with self._lock:
            if item in self.queue:
                return False
            self.queue.append(item)
            return True

    def cancel(self, item: str) -> bool:
        with self._lock:
            if item in self.queue:
                self.queue.remove(item)
                return True
            return False

    def next_allowed(self) -> float:
        with self._lock:
            return 0.0 if self.last_start is None else self.last_start + self.gap

    def due(self, active: int) -> list[str]:
        """返回现在应该启动的账号（会从队列中移除）。active 为正在运行的账号数。"""
        with self._lock:
            started: list[str] = []
            now = self._clock()
            while self.queue and active + len(started) < self.max_parallel and now >= self.next_allowed():
                started.append(self.queue.pop(0))
                self.last_start = now
                self.gap = self._rng.uniform(*self.stagger)
            return started

    def estimate(self, item: str, active: int) -> Optional[dict]:
        """
        估计排队账号的启动时间。
        返回 {"position": 第几位(从1开始), "eta": 预计时间戳或 None}；eta 为 None 表示要等别的账号学完腾出位置。
        """
        with self._lock:
            if item not in self.queue:
                return None
            pos = self.queue.index(item)
            free = self.max_parallel - active
            if pos >= free:
                return {"position": pos + 1, "eta": None}
            start = max(self._clock(), self.next_allowed())
            avg = sum(self.stagger) / 2
            return {"position": pos + 1, "eta": start + pos * avg}
