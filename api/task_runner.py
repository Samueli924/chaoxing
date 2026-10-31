import queue
import threading
import time
import uuid
from typing import Any, Optional


class TaskStateHub:
    """运行时单例状态总线，协调动态倍速、大屏监控与手动答题队列."""

    _STATUS_INTERVAL = 0.25

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "TaskStateHub":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_hub()
            return cls._instance

    def _init_hub(self) -> None:
        self._lock = threading.Lock()
        self._web_mode = False
        self._is_task_running = False
        self._last_status_broadcast = 0.0
        self._flush_timer: Optional[threading.Timer] = None
        self._global_speed = 1.0
        self._worker_speeds: dict[str, float] = {}
        self._workers: dict[str, dict[str, Any]] = {}
        self._logs: list[dict[str, str]] = []
        self._pending_questions: dict[str, dict[str, Any]] = {}
        self._listeners: list[queue.Queue] = []
        self._overall_stats = {
            "completed_jobs": 0,
            "total_jobs": 0,
            "passed_tests": 0,
            "start_time": time.time(),
        }

    def is_web_mode(self) -> bool:
        return self._web_mode

    def set_web_mode(self, enabled: bool) -> None:
        with self._lock:
            self._web_mode = enabled

    def set_global_speed(self, speed: float) -> None:
        speed = max(1.0, min(2.0, float(speed)))
        with self._lock:
            self._global_speed = speed
        self.broadcast_event("SPEED_CHANGE", {"type": "GLOBAL", "speed": speed})

    def get_global_speed(self) -> float:
        with self._lock:
            return self._global_speed

    def set_worker_speed(self, worker_id: str, speed: float) -> None:
        speed = max(1.0, min(2.0, float(speed)))
        with self._lock:
            self._worker_speeds[worker_id] = speed
        self.broadcast_event("SPEED_CHANGE", {"type": "WORKER", "worker_id": worker_id, "speed": speed})

    def get_effective_speed(self, worker_id: str) -> float:
        with self._lock:
            return self._worker_speeds.get(worker_id, self._global_speed)

    def update_worker_state(self, worker_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            if worker_id not in self._workers:
                self._workers[worker_id] = {"id": worker_id}
            self._workers[worker_id].update(data)
            self._workers[worker_id]["updated_at"] = time.time()
            worker_copy = dict(self._workers[worker_id])
        self.broadcast_event("WORKER_UPDATE", worker_copy)

    def remove_worker(self, worker_id: str) -> None:
        """从看板中移除已结束的视频播放工作线程."""
        with self._lock:
            self._workers.pop(worker_id, None)
            self._worker_speeds.pop(worker_id, None)
        self.broadcast_event("WORKER_REMOVED", {"id": worker_id})
        self.broadcast_event("STATUS_UPDATE", self.get_snapshot())

    def clear_workers(self) -> None:
        """任务结束时清空工作线程状态并广播更新."""
        with self._lock:
            self._workers.clear()
            self._worker_speeds.clear()
        self.broadcast_event("STATUS_UPDATE", self.get_snapshot())

    def set_task_running(self, running: bool, stopped: bool = False) -> None:
        """更新全局任务运行态并在结束时通知前端."""
        with self._lock:
            was_running = self._is_task_running
            self._is_task_running = running
            if running:
                self._cancel_flush_locked()
                self._overall_stats["start_time"] = time.time()
                self._overall_stats["completed_jobs"] = 0
                self._overall_stats["total_jobs"] = 0
                self._overall_stats["passed_tests"] = 0
                self._overall_stats["all_finished"] = False
            else:
                for entry in self._pending_questions.values():
                    entry["answer"] = None
                    entry["resolved"] = True
                    entry["event"].set()
        self.broadcast_event("STATUS_UPDATE", self.get_snapshot())
        if was_running and not running:
            self.broadcast_event("TASK_FINISHED", {"status": "stopped" if stopped else "finished"})

    def is_task_running(self) -> bool:
        with self._lock:
            return self._is_task_running

    def set_total_jobs(self, total: int, all_finished: bool = False, completed_base: int = 0) -> None:
        """写入任务总数，并可用课程页统计值作为已完成起始值，使看板与课程列表同源."""
        with self._lock:
            self._overall_stats["total_jobs"] = total
            self._overall_stats["completed_jobs"] = max(0, min(completed_base, total))
            self._overall_stats["all_finished"] = bool(all_finished and total == 0)
        self.broadcast_event("STATUS_UPDATE", self.get_snapshot())

    def increment_completed_jobs(self) -> None:
        with self._lock:
            total = self._overall_stats["total_jobs"]
            if total > 0:
                self._overall_stats["completed_jobs"] = min(self._overall_stats["completed_jobs"] + 1, total)
            else:
                self._overall_stats["completed_jobs"] += 1
            now = time.time()
            due = now - self._last_status_broadcast
            if due >= self._STATUS_INTERVAL or self._overall_stats["completed_jobs"] >= total:
                self._last_status_broadcast = now
                self._cancel_flush_locked()
                fire_now = True
            else:
                fire_now = False
                if self._flush_timer is None:
                    self._flush_timer = threading.Timer(self._STATUS_INTERVAL - due, self._flush_status_update)
                    self._flush_timer.daemon = True
                    self._flush_timer.start()
        if fire_now:
            self.broadcast_event("STATUS_UPDATE", self.get_snapshot())

    def _cancel_flush_locked(self) -> None:
        """丢弃待触发的尾沿补推，调用方须持有锁."""
        if self._flush_timer is not None:
            self._flush_timer.cancel()
            self._flush_timer = None

    def _flush_status_update(self) -> None:
        """补推被限流吞掉的最后一次递增，避免进度条停在旧值."""
        with self._lock:
            self._flush_timer = None
            self._last_status_broadcast = time.time()
        self.broadcast_event("STATUS_UPDATE", self.get_snapshot())

    def increment_passed_tests(self) -> None:
        with self._lock:
            self._overall_stats["passed_tests"] += 1
        self.broadcast_event("STATUS_UPDATE", self.get_snapshot())

    def append_log(self, level: str, message: str) -> None:
        now_str = time.strftime("%H:%M:%S")
        entry = {"timestamp": now_str, "level": level.upper(), "message": message}
        with self._lock:
            self._logs.append(entry)
            if len(self._logs) > 200:
                self._logs.pop(0)
        self.broadcast_event("LOG_APPEND", entry)

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            workers_list = list(self._workers.values())
            logs_copy = list(self._logs)
            elapsed = int(time.time() - self._overall_stats["start_time"])
            completed = self._overall_stats["completed_jobs"]
            total = self._overall_stats["total_jobs"]
            if total > 0:
                progress = round((completed / total * 100), 1)
            elif self._overall_stats.get("all_finished"):
                progress = 100.0
            else:
                progress = 0.0
            return {
                "is_running": self._is_task_running,
                "overall_progress": progress,
                "completed_jobs": completed,
                "total_jobs": total,
                "passed_tests": self._overall_stats["passed_tests"],
                "elapsed_seconds": elapsed,
                "global_speed": self._global_speed,
                "workers": workers_list,
                "logs": logs_copy,
            }

    def request_manual_answer(self, prompt_data: dict[str, Any], timeout: float = 120.0) -> Optional[str]:
        prompt_id = str(uuid.uuid4())
        event = threading.Event()
        entry = {
            "prompt_id": prompt_id,
            "data": prompt_data,
            "event": event,
            "answer": None,
            "resolved": False,
            "created_at": time.time(),
        }
        with self._lock:
            self._pending_questions[prompt_id] = entry

        broadcast_payload = {"prompt_id": prompt_id}
        broadcast_payload.update(prompt_data)
        self.broadcast_event("MANUAL_QUESTION_REQUEST", broadcast_payload)

        event.wait(timeout=timeout)

        with self._lock:
            res_entry = self._pending_questions.pop(prompt_id, None)

        self.broadcast_event("MANUAL_QUESTION_RESOLVED", {"prompt_id": prompt_id})

        if res_entry and res_entry["resolved"]:
            return res_entry["answer"]
        return None

    def submit_manual_answer(self, prompt_id: str, answer: str) -> bool:
        with self._lock:
            entry = self._pending_questions.get(prompt_id)
            if not entry:
                return False
            entry["answer"] = answer
            entry["resolved"] = True
            entry["event"].set()
            return True

    def skip_manual_answer(self, prompt_id: str) -> bool:
        with self._lock:
            entry = self._pending_questions.get(prompt_id)
            if not entry:
                return False
            entry["answer"] = None
            entry["resolved"] = True
            entry["event"].set()
            return True

    def get_pending_questions(self) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for prompt_id, entry in self._pending_questions.items():
                if not entry["resolved"]:
                    item = {"prompt_id": prompt_id}
                    item.update(entry["data"])
                    results.append(item)
            return results

    def subscribe_events(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            self._listeners.append(q)
        return q

    def unsubscribe_events(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def broadcast_event(self, event_type: str, data: dict[str, Any]) -> None:
        msg = {"event": event_type, "data": data}
        with self._lock:
            for q in list(self._listeners):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    # 队列满时丢弃最旧数据包，避免并发日志洪峰中断 SSE 连接
                    try:
                        q.get_nowait()
                        q.put_nowait(msg)
                    except Exception:
                        pass
