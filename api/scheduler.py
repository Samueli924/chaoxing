# -*- coding: utf-8 -*-
"""章节任务调度.

多个章节并发处理；对“章节未开放”的处理规则：
1. 同一课程中还有更靠前的章节未处理完时，先等待（闯关模式下前面的章节完成后才会解锁）；
2. 前面的章节都处理完后仍未开放，再按配置处理：continue 跳过 / retry 退避重试 / ask 询问用户。
任何异常都只会让当前章节按失败重试，不会导致线程退出或整个程序卡死。
"""
import enum
import heapq
import itertools
import sys
import threading
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Optional

from api.base import Chaoxing, StudyResult
from api.live import Live
from api.live_process import LiveProcessor
from api.logger import logger
from api.runtime import interactive_lock, runtime


class ChapterResult(enum.Enum):
    SUCCESS = 0
    ERROR = 1
    NOT_OPEN = 2
    PENDING = 3
    CANCELLED = 4


def process_job(chaoxing: Chaoxing, course: dict, job: dict, job_info: dict, speed: float) -> StudyResult:
    """处理单个任务点"""
    job_type = job.get("type")
    if job_type == "video":
        # 音频任务点同样以 video 类型返回，优先按识别出的类型处理，失败后再尝试另一种
        first, second = ("Audio", "Video") if job.get("audio") else ("Video", "Audio")
        logger.trace(f"识别到{first}任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        result = chaoxing.study_video(course, job, job_info, _speed=speed, _type=first)
        if result in (StudyResult.ERROR, StudyResult.FORBIDDEN) and not runtime.should_stop():
            logger.warning(f"按{first}任务处理失败, 正在尝试按{second}任务处理")
            result = chaoxing.study_video(course, job, job_info, _speed=speed, _type=second)
        if result.is_failure() and result != StudyResult.CANCELLED:
            logger.warning(f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}, 稍后重试")
        return result
    if job_type == "document":
        logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        return chaoxing.study_document(course, job, job_info)
    if job_type == "workid":
        logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
        return chaoxing.study_work(course, job, job_info)
    if job_type == "read":
        logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
        return chaoxing.study_read(course, job, job_info)
    if job_type == "live":
        logger.trace(f"识别到直播任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        try:
            defaults = {
                "userid": chaoxing.get_uid(),
                "clazzId": course.get("clazzId"),
                "knowledgeid": job_info.get("knowledgeid"),
            }
            live = Live(attachment=job, defaults=defaults, course_id=course.get("courseId"))
            if LiveProcessor.run_live(live, speed):
                return StudyResult.SUCCESS
            return StudyResult.CANCELLED if runtime.should_stop() else StudyResult.ERROR
        except Exception as e:
            logger.error(f"处理直播任务时出错: {e}")
            return StudyResult.ERROR

    logger.error(f"未知任务类型: {job_type}")
    return StudyResult.ERROR


def process_chapter(chaoxing: Chaoxing, course: dict[str, Any], point: dict[str, Any], speed: float,
                    on_job_result: Optional[Callable[[dict, StudyResult], None]] = None) -> ChapterResult:
    """处理单个章节"""
    logger.info(f'当前章节: {point["title"]}')
    if point.get("has_finished"):
        logger.info(f'章节：{point["title"]} 已完成所有任务点')
        return ChapterResult.SUCCESS

    # 随机等待，避免请求过快
    chaoxing.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)

    jobs, job_info = chaoxing.get_job_list(course, point)
    if job_info.get("notOpen", False):
        return ChapterResult.NOT_OPEN

    failed = False
    for job in jobs:
        if runtime.should_stop():
            return ChapterResult.CANCELLED
        result = process_job(chaoxing, course, job, job_info, speed)
        if on_job_result:
            on_job_result(job, result)
        if result == StudyResult.CANCELLED:
            return ChapterResult.CANCELLED
        if result.is_failure():
            failed = True

    return ChapterResult.ERROR if failed else ChapterResult.SUCCESS


@dataclass
class ChapterTask:
    index: int
    point: dict[str, Any]
    course: dict[str, Any]
    result: ChapterResult = ChapterResult.PENDING
    tries: int = 0

    def __lt__(self, other):
        """比较两个任务的索引大小，用于优先级队列排序."""
        if not isinstance(other, ChapterTask):
            return NotImplemented
        return self.index < other.index

    @property
    def course_key(self) -> tuple:
        return self.course.get("courseId"), self.course.get("clazzId")

    @property
    def label(self) -> str:
        return f'{self.course.get("title", "")} - {self.point.get("title", "")}'


class JobProcessor:
    def __init__(self, chaoxing: Chaoxing, tasks: list[ChapterTask], config: dict[str, Any],
                 ask_callback: Optional[Callable[[ChapterTask], str]] = None):
        """初始化任务处理器.

        Args:
            chaoxing: 已登录的 Chaoxing 实例
            tasks: 待处理的章节
            config: 运行配置（speed / jobs / notopen_action / retry_interval / interactive）
            ask_callback: notopen_action=ask 时用于询问用户的函数，返回 "skip" / "retry" / "stop"
        """
        self.chaoxing = chaoxing
        self.tasks = list(tasks)
        self.config = config
        self.speed = float(config.get("speed") or 1.0)
        try:
            self.worker_num = max(1, int(config.get("jobs") or 4))
        except (TypeError, ValueError):
            self.worker_num = 4
        self.notopen_action = str(config.get("notopen_action") or "retry").lower()
        try:
            self.retry_interval = max(0.0, float(config.get("retry_interval", 1.0)))
        except (TypeError, ValueError):
            self.retry_interval = 1.0
        self.max_tries = 5
        interactive = config.get("interactive")
        self.interactive = _stdin_is_tty() if interactive is None else bool(interactive)
        self.ask_callback = ask_callback or self._ask_in_terminal

        self.done_tasks: list[ChapterTask] = []
        self.failed_tasks: list[ChapterTask] = []
        self.skipped_tasks: list[ChapterTask] = []
        self.cancelled_tasks: list[ChapterTask] = []
        self.skipped_works = 0

        self._cond = threading.Condition()
        self._heap: list[tuple[float, int, int, ChapterTask]] = []
        self._seq = itertools.count()
        self._pending: dict[tuple, set[int]] = defaultdict(set)
        self._blocked: dict[tuple, list[ChapterTask]] = defaultdict(list)
        self._auto_skip: set[tuple] = set()
        self._stopped_courses: set[tuple] = set()
        self._remaining = 0

    # ------------------------------------------------------------------
    @property
    def pending_count(self) -> int:
        with self._cond:
            return self._remaining

    def run(self):
        with self._cond:
            for task in self.tasks:
                self._pending[task.course_key].add(task.index)
                self._push(task, 0.0)
            self._remaining = len(self.tasks)
        self._report_progress()
        if not self.tasks:
            return

        threads = [
            threading.Thread(target=self._worker, name=f"chapter-worker-{i + 1}", daemon=True)
            for i in range(min(self.worker_num, len(self.tasks)))
        ]
        for thread in threads:
            thread.start()
        try:
            # 带超时的 join，保证在 Windows 上也能及时响应 Ctrl+C
            while any(thread.is_alive() for thread in threads):
                for thread in threads:
                    thread.join(0.5)
        except KeyboardInterrupt:
            runtime.request_stop()
            raise

    def summary(self) -> dict[str, Any]:
        return {
            "total": len(self.tasks),
            "done": len(self.done_tasks),
            "failed": [t.label for t in self.failed_tasks],
            "skipped": [t.label for t in self.skipped_tasks],
            "cancelled": len(self.cancelled_tasks),
            "skipped_works": self.skipped_works,
        }

    # ------------------------------------------------------------------
    def _push(self, task: ChapterTask, delay: float) -> None:
        heapq.heappush(self._heap, (time.monotonic() + delay, task.index, next(self._seq), task))

    def _backoff(self, tries: int) -> float:
        return min(60.0, self.retry_interval * (2 ** max(0, tries - 1)))

    def _report_progress(self) -> None:
        runtime.update_counts(
            total=len(self.tasks),
            done=len(self.done_tasks),
            failed=len(self.failed_tasks),
            skipped=len(self.skipped_tasks),
        )

    def _finalize(self, task: ChapterTask, bucket: list[ChapterTask]) -> None:
        self._pending[task.course_key].discard(task.index)
        bucket.append(task)
        self._remaining -= 1
        self._release_blocked(task.course_key)
        self._report_progress()

    def _has_earlier_pending(self, task: ChapterTask) -> bool:
        return any(i < task.index for i in self._pending[task.course_key])

    def _release_blocked(self, course_key: tuple) -> None:
        """前面的章节都处理完后，放出等待中的第一个未开放章节重新检查."""
        blocked = self._blocked.get(course_key)
        if not blocked:
            return
        blocked.sort(key=lambda t: t.index)
        first = blocked[0]
        if not any(i < first.index for i in self._pending[course_key]):
            blocked.pop(0)
            self._push(first, 0.0)

    def _cancel_everything(self) -> None:
        while self._heap:
            _, _, _, task = heapq.heappop(self._heap)
            self._finalize(task, self.cancelled_tasks)
        for course_key in list(self._blocked):
            while self._blocked[course_key]:
                self._finalize(self._blocked[course_key].pop(0), self.cancelled_tasks)

    def _stop_course(self, course_key: tuple) -> None:
        self._stopped_courses.add(course_key)
        for task in self._blocked.pop(course_key, []):
            self._finalize(task, self.skipped_tasks)

    def _next_task(self) -> Optional[ChapterTask]:
        with self._cond:
            while True:
                if self._remaining <= 0:
                    self._cond.notify_all()
                    return None
                if runtime.should_stop():
                    self._cancel_everything()
                    self._cond.notify_all()
                    if self._remaining <= 0:
                        return None
                    self._cond.wait(0.5)
                    continue
                if self._heap:
                    ready_at, _, _, task = self._heap[0]
                    now = time.monotonic()
                    if ready_at <= now:
                        heapq.heappop(self._heap)
                        if task.course_key in self._stopped_courses:
                            self._finalize(task, self.skipped_tasks)
                            continue
                        return task
                    self._cond.wait(min(ready_at - now, 1.0))
                else:
                    self._cond.wait(1.0)

    def _on_job_result(self, job: dict, result: StudyResult) -> None:
        if job.get("type") == "workid" and result == StudyResult.SKIPPED:
            with self._cond:
                self.skipped_works += 1

    def _worker(self):
        while True:
            task = self._next_task()
            if task is None:
                return
            try:
                result = process_chapter(self.chaoxing, task.course, task.point, self.speed,
                                         on_job_result=self._on_job_result)
            except Exception as e:
                logger.error(f"处理章节出错: {task.label}: {type(e).__name__}: {e}")
                logger.debug(traceback.format_exc())
                result = ChapterResult.ERROR
            task.result = result
            self._handle_result(task, result)

    def _handle_result(self, task: ChapterTask, result: ChapterResult) -> None:
        course_key = task.course_key
        need_ask = False
        with self._cond:
            if result == ChapterResult.SUCCESS:
                logger.debug("Task success: {}", task.label)
                self._auto_skip.discard(course_key)
                self._finalize(task, self.done_tasks)
            elif result == ChapterResult.CANCELLED or runtime.should_stop():
                self._finalize(task, self.cancelled_tasks)
            elif result == ChapterResult.NOT_OPEN:
                if self._has_earlier_pending(task):
                    logger.info("章节未开放, 等待前面的章节完成后再检查: {}", task.label)
                    self._blocked[course_key].append(task)
                    self._release_blocked(course_key)
                elif self.notopen_action == "continue" or course_key in self._auto_skip:
                    logger.warning("章节未开放: {}, 已跳过", task.label)
                    self._finalize(task, self.skipped_tasks)
                elif self.notopen_action == "ask" and self.interactive:
                    need_ask = True
                else:
                    task.tries += 1
                    if task.tries >= self.max_tries:
                        logger.error(
                            "章节未开放: {} 可能由于上一章节的章节检测未完成, 也可能由于该章节因为时效已关闭，"
                            "请手动检查完成并提交再重试。或者在配置中配置(自动跳过关闭章节/开启题库并启用提交)",
                            task.label)
                        self._finalize(task, self.skipped_tasks)
                    else:
                        delay = self._backoff(task.tries)
                        logger.info("章节未开放: {}, {:.0f} 秒后重新检查 ({}/{})", task.label, delay, task.tries,
                                    self.max_tries)
                        self._push(task, delay)
            elif result == ChapterResult.ERROR:
                self._auto_skip.discard(course_key)
                task.tries += 1
                logger.warning("重试任务 {} ({}/{} 次尝试)", task.label, task.tries, self.max_tries)
                if task.tries >= self.max_tries:
                    logger.error("任务重试次数达到上限: {}", task.label)
                    self._finalize(task, self.failed_tasks)
                else:
                    self._push(task, self._backoff(task.tries))
            else:
                logger.error("任务 {} 的状态无效 {}", task.label, result)
                self._finalize(task, self.failed_tasks)
            self._cond.notify_all()

        if not need_ask:
            return
        try:
            decision = self.ask_callback(task)
        except Exception as e:
            logger.warning(f"询问用户失败, 按跳过处理: {e}")
            decision = "skip"
        with self._cond:
            if decision == "retry":
                task.tries += 1
                if task.tries >= self.max_tries:
                    self._finalize(task, self.skipped_tasks)
                else:
                    self._push(task, self._backoff(task.tries))
            elif decision == "stop":
                logger.warning("已停止课程: {}", task.course.get("title", ""))
                self._finalize(task, self.skipped_tasks)
                self._stop_course(course_key)
            else:
                logger.warning("章节未开放: {}, 已跳过 (后续连续未开放的章节将自动跳过)", task.label)
                self._auto_skip.add(course_key)
                self._finalize(task, self.skipped_tasks)
            self._cond.notify_all()

    @staticmethod
    def _ask_in_terminal(task: ChapterTask) -> str:
        with interactive_lock:
            print(f"\n章节未开放: {task.label}")
            print("可能是上一章节的章节检测未提交，也可能是该章节尚未开放或已关闭。")
            while True:
                try:
                    choice = input("请选择 [S]跳过, 后续连续的未开放章节也自动跳过(默认) / [R]稍后重试 / [Q]停止该课程: ")
                except EOFError:
                    return "skip"
                choice = choice.strip().lower()
                if choice in ("", "s", "skip", "y", "yes", "c", "continue"):
                    return "skip"
                if choice in ("r", "retry"):
                    return "retry"
                if choice in ("q", "stop", "n", "no"):
                    return "stop"


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
