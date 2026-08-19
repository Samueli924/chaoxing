# -*- coding: utf-8 -*-
"""Issue #612 的回归测试：未开放章节不再无限重试."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


class DummyChaoxing:
    """仅提供 process_chapter 所需的最小接口，不发任何网络请求."""

    def __init__(self, job_info):
        """初始化测试替身，保存固定的任务点数据."""
        self.job_info = job_info
        self.rate_limiter = _NoopRateLimiter()

    def get_job_list(self, course, point):
        return self.job_info["jobs"], self.job_info["job_info"]


class _NoopRateLimiter:
    def limit_rate(self, *args, **kwargs):
        return None


class JobProcessorTestCase(unittest.TestCase):
    def setUp(self):
        main.logger.remove()  # 关闭所有 handler，避免测试日志刷屏

    def _make_processor(self, job_info, notopen_action="retry", max_tries=3):
        course = {"title": "课程"}
        point = {"title": "章节", "has_finished": False}
        task = main.ChapterTask(index=0, point=point, course=course)
        config = {
            "speed": 1.0,
            "jobs": 1,
            "notopen_action": notopen_action,
            "retry_interval": 0.01,
        }
        processor = main.JobProcessor(DummyChaoxing(job_info), [task], config)
        processor.max_tries = max_tries
        return processor, task

    def _run_with_timeout(self, processor, timeout=5.0):
        """在独立线程中运行 run()，超时抛出异常，避免旧代码无限重试导致测试永久卡死."""
        exception = {}

        def target():
            try:
                processor.run()
            except BaseException as exc:  # noqa: BLE001 - 子线程异常需在主线程重新抛出
                exception["exc"] = exc

        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self.fail(
                f"JobProcessor.run() 超过 {timeout}s 未返回，疑似无限重试（Issue #612）"
            )
        if exception:
            raise exception["exc"]

    def _not_open_job_info(self):
        return {"jobs": [], "job_info": {"notOpen": True}}

    def _error_job_info(self):
        # 未知任务类型会走 ERROR 分支，不依赖网络。
        return {"jobs": [{"type": "unknown"}], "job_info": {}}

    def test_not_open_does_not_retry_forever(self):
        processor, _ = self._make_processor(self._not_open_job_info(), max_tries=3)
        self._run_with_timeout(processor)

    def test_not_open_tries_increment(self):
        processor, task = self._make_processor(self._not_open_job_info(), max_tries=3)
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 3)

    def test_not_open_stops_after_max_tries(self):
        processor, task = self._make_processor(self._not_open_job_info(), max_tries=3)
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 3)
        self.assertTrue(processor.task_queue.empty())
        self.assertTrue(processor.retry_queue.empty())
        self.assertEqual(processor.task_queue.unfinished_tasks, 0)

    def test_not_open_queue_joins_normally(self):
        for _ in range(3):
            processor, _ = self._make_processor(self._not_open_job_info(), max_tries=3)
            self._run_with_timeout(processor)

    def test_not_open_continue_skips_without_retry(self):
        processor, task = self._make_processor(
            self._not_open_job_info(), notopen_action="continue", max_tries=3
        )
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 0)
        self.assertTrue(processor.retry_queue.empty())

    def test_error_retry_behavior_unchanged(self):
        processor, task = self._make_processor(self._error_job_info(), max_tries=3)
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 3)
        self.assertIn(task, processor.failed_tasks)

    def test_success_does_not_retry(self):
        # 已完成章节直接 SUCCESS，不应有任何重试。
        course = {"title": "课程"}
        point = {"title": "章节", "has_finished": True}
        task = main.ChapterTask(index=0, point=point, course=course)
        config = {
            "speed": 1.0,
            "jobs": 1,
            "notopen_action": "retry",
            "retry_interval": 0.01,
        }
        processor = main.JobProcessor(DummyChaoxing(self._not_open_job_info()), [task], config)
        processor.max_tries = 3
        self._run_with_timeout(processor)
        self.assertEqual(task.tries, 0)
        self.assertTrue(processor.retry_queue.empty())


if __name__ == "__main__":
    unittest.main()