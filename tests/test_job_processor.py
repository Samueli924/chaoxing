# -*- coding: utf-8 -*-
"""章节调度器回归测试：未开放章节不会无限重试、会等待前序章节、可跳过。"""
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import scheduler  # noqa: E402
from api.runtime import runtime  # noqa: E402
from api.scheduler import ChapterResult, ChapterTask, JobProcessor  # noqa: E402


class _NoopRateLimiter:
    def limit_rate(self, *args, **kwargs):
        return None


class DummyChaoxing:
    """仅提供 process_chapter 所需的最小接口，不发任何网络请求。"""

    def __init__(self, job_info):
        self.job_info = job_info
        self.rate_limiter = _NoopRateLimiter()

    def get_job_list(self, course, point):
        return self.job_info["jobs"], self.job_info["job_info"]


class JobProcessorTestCase(unittest.TestCase):
    def setUp(self):
        runtime.reset()
        self.addCleanup(runtime.reset)

    def _make_processor(self, job_info, notopen_action="retry", max_tries=3, tasks=None):
        if tasks is None:
            point = {"title": "章节", "has_finished": False}
            tasks = [ChapterTask(index=0, point=point, course={"title": "课程", "courseId": "c", "clazzId": "z"})]
        config = {"speed": 1.0, "jobs": 1, "notopen_action": notopen_action,
                  "retry_interval": 0.01, "interactive": False}
        processor = JobProcessor(DummyChaoxing(job_info), tasks, config)
        processor.max_tries = max_tries
        return processor, tasks[0]

    def _run_with_timeout(self, processor, timeout=5.0):
        exc = {}

        def target():
            try:
                processor.run()
            except BaseException as e:  # noqa: BLE001
                exc["e"] = e

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self.fail(f"JobProcessor.run() 超过 {timeout}s 未返回，疑似无限重试")
        if exc:
            raise exc["e"]

    @staticmethod
    def _not_open():
        return {"jobs": [], "job_info": {"notOpen": True}}

    @staticmethod
    def _error():
        return {"jobs": [{"type": "unknown"}], "job_info": {}}

    @staticmethod
    def _empty():
        return {"jobs": [], "job_info": {}}

    def test_nonfinite_scheduler_config_is_normalized(self):
        processor, _ = self._make_processor(self._not_open(), max_tries=1)
        processor = JobProcessor(processor.chaoxing, processor.tasks,
                                 {'retry_interval': float('nan'), 'jobs': float('inf'), 'speed': float('nan')})
        processor.max_tries = 1
        self._run_with_timeout(processor)
        self.assertEqual(processor.pending_count, 0)

    def test_errors_step_down_all_tiers_and_exhaust_retry_budget(self):
        p, task = self._make_processor(self._error(), max_tries=5)
        p.worker_num = p.concurrency_limit = 12
        self._run_with_timeout(p)
        self.assertEqual([(r['from'], r['to']) for r in p.concurrency_changes], [(12, 8), (8, 4), (4, 2), (2, 1)])
        self.assertEqual(p.pending_count, 0)
        self.assertEqual(p._active, 0)
        self.assertIn(task, p.failed_tasks)

    def test_downshift_waits_for_inflight_tasks_then_continues(self):
        import time
        course = {'courseId': 'c', 'clazzId': 'z', 'title': 'course'}
        tasks = [ChapterTask(i, {'title': str(i)}, course) for i in range(3)]
        p = JobProcessor(DummyChaoxing(self._empty()), tasks, {'jobs': 2})
        second_started, release_second, third_started = threading.Event(), threading.Event(), threading.Event()
        def process(cx, course, point, speed, **kwargs):
            if point['title'] == '0':
                if not second_started.wait(2): raise AssertionError('second task not started')
                return ChapterResult.BLOCKED
            if point['title'] == '1':
                second_started.set()
                if not release_second.wait(3): raise AssertionError('release missing')
            else:
                third_started.set()
            return ChapterResult.SUCCESS
        with patch.object(scheduler, 'process_chapter', side_effect=process):
            thread = threading.Thread(target=p.run, daemon=True)
            thread.start()
            try:
                self.assertTrue(second_started.wait(2))
                deadline = time.monotonic() + 2
                while p.concurrency_limit != 1 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(p.concurrency_limit, 1)
                self.assertFalse(third_started.is_set())
            finally:
                release_second.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertTrue(third_started.is_set())
        self.assertEqual(p.pending_count, 0)
        self.assertEqual(len(p.failed_tasks), 1)
        self.assertEqual(len(p.done_tasks), 2)

    def test_not_open_does_not_retry_forever(self):
        processor, _ = self._make_processor(self._not_open(), max_tries=3)
        self._run_with_timeout(processor)

    def test_not_open_stops_after_max_tries(self):
        processor, task = self._make_processor(self._not_open(), max_tries=3)
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 3)
        self.assertEqual(processor.pending_count, 0)
        self.assertIn(task, processor.skipped_tasks)

    def test_not_open_continue_skips_without_retry(self):
        processor, task = self._make_processor(self._not_open(), notopen_action="continue", max_tries=3)
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 0)
        self.assertIn(task, processor.skipped_tasks)

    def test_error_retry_behavior(self):
        processor, task = self._make_processor(self._error(), max_tries=3)
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 3)
        self.assertIn(task, processor.failed_tasks)

    def test_success_does_not_retry(self):
        point = {"title": "章节", "has_finished": True}
        task = ChapterTask(index=0, point=point, course={"title": "课程", "courseId": "c", "clazzId": "z"})
        processor, _ = self._make_processor(self._not_open(), tasks=[task])
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 0)
        self.assertIn(task, processor.done_tasks)

    def test_empty_chapter_is_success(self):
        processor, task = self._make_processor(self._empty())
        self._run_with_timeout(processor)
        self.assertIn(task, processor.done_tasks)

    def test_not_open_waits_for_earlier_chapter(self):
        # 第 0 章未完成且能成功；第 1 章未开放，应等到第 0 章完成后再检查，而不是立刻重试
        course = {"title": "课程", "courseId": "c", "clazzId": "z"}
        tasks = [
            ChapterTask(index=0, point={"title": "第一章", "has_finished": True}, course=course),
            ChapterTask(index=1, point={"title": "第二章", "has_finished": False}, course=course),
        ]
        processor, _ = self._make_processor(self._not_open(), notopen_action="continue", tasks=tasks)
        self._run_with_timeout(processor)
        self.assertIn(tasks[0], processor.done_tasks)
        self.assertIn(tasks[1], processor.skipped_tasks)

    def test_stop_event_cancels(self):
        course = {"title": "课程", "courseId": "c", "clazzId": "z"}
        tasks = [ChapterTask(index=i, point={"title": f"第{i}章", "has_finished": False}, course=course)
                 for i in range(5)]
        processor, _ = self._make_processor(self._not_open(), tasks=tasks)
        runtime.request_stop()
        self._run_with_timeout(processor)
        self.assertEqual(processor.pending_count, 0)

    def test_ask_mode_skip(self):
        course = {"title": "课程", "courseId": "c", "clazzId": "z"}
        task = ChapterTask(index=0, point={"title": "章节", "has_finished": False}, course=course)
        config = {"speed": 1.0, "jobs": 1, "notopen_action": "ask", "retry_interval": 0.01, "interactive": True}
        processor = JobProcessor(DummyChaoxing(self._not_open()), [task], config,
                                 ask_callback=lambda t: "skip")
        self._run_with_timeout(processor)
        self.assertIn(task, processor.skipped_tasks)


if __name__ == "__main__":
    unittest.main()
