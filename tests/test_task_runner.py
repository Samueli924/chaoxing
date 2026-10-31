import threading
import time
import unittest
from api.task_runner import TaskStateHub


class TestTaskStateHub(unittest.TestCase):
    def setUp(self):
        self.hub = TaskStateHub()
        self.hub._pending_questions.clear()
        self.hub._workers.clear()
        self.hub._logs.clear()
        self.hub._last_status_broadcast = 0.0
        self.hub.set_task_running(False)

    @staticmethod
    def _last_status(q):
        last = None
        while not q.empty():
            msg = q.get_nowait()
            if msg["event"] == "STATUS_UPDATE":
                last = msg["data"]
        return last

    def test_speed_dispatch(self):
        self.hub.set_global_speed(1.5)
        self.assertEqual(self.hub.get_global_speed(), 1.5)
        self.assertEqual(self.hub.get_effective_speed("worker_1"), 1.5)

        self.hub.set_worker_speed("worker_1", 1.8)
        self.assertEqual(self.hub.get_effective_speed("worker_1"), 1.8)
        self.assertEqual(self.hub.get_effective_speed("worker_2"), 1.5)

    def test_manual_question_submit(self):
        prompt_data = {
            "title": "测试一阶微分方程",
            "type": "single",
            "options": ["A. 选项1", "B. 选项2"]
        }
        res_container = []

        def worker():
            ans = self.hub.request_manual_answer(prompt_data, timeout=3.0)
            res_container.append(ans)

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)

        pending = self.hub.get_pending_questions()
        self.assertEqual(len(pending), 1)
        prompt_id = pending[0]["prompt_id"]

        success = self.hub.submit_manual_answer(prompt_id, "A")
        self.assertTrue(success)
        t.join(timeout=2.0)
        self.assertEqual(res_container, ["A"])

    def test_manual_question_skip(self):
        prompt_data = {"title": "跳过题目", "type": "judgement"}
        res_container = []

        def worker():
            ans = self.hub.request_manual_answer(prompt_data, timeout=3.0)
            res_container.append(ans)

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.1)

        pending = self.hub.get_pending_questions()
        prompt_id = pending[0]["prompt_id"]
        self.hub.skip_manual_answer(prompt_id)
        t.join(timeout=2.0)
        self.assertEqual(res_container, [None])

    def test_task_running_state_and_snapshot(self):
        self.assertFalse(self.hub.is_task_running())
        self.assertFalse(self.hub.get_snapshot()["is_running"])

        self.hub.set_task_running(True)
        self.assertTrue(self.hub.is_task_running())
        self.assertTrue(self.hub.get_snapshot()["is_running"])

        self.hub.set_task_running(False)
        self.assertFalse(self.hub.is_task_running())
        self.assertFalse(self.hub.get_snapshot()["is_running"])

    def test_set_total_jobs_accepts_page_baseline(self):
        self.hub.set_task_running(True)
        self.hub.set_total_jobs(265, completed_base=263)
        snap = self.hub.get_snapshot()
        self.assertEqual(snap["total_jobs"], 265)
        self.assertEqual(snap["completed_jobs"], 263)
        self.assertEqual(snap["overall_progress"], 99.2)

        self.hub.increment_completed_jobs()
        self.assertEqual(self.hub.get_snapshot()["completed_jobs"], 264)

    def test_completed_jobs_never_exceed_total(self):
        self.hub.set_task_running(True)
        self.hub.set_total_jobs(5, completed_base=4)
        for _ in range(10):
            self.hub.increment_completed_jobs()
        snap = self.hub.get_snapshot()
        self.assertEqual(snap["completed_jobs"], 5)
        self.assertEqual(snap["overall_progress"], 100.0)

    def test_completed_jobs_burst_flushes_final_value(self):
        self.hub.set_task_running(True)
        self.hub.set_total_jobs(5)
        q = self.hub.subscribe_events()
        try:
            for _ in range(3):
                self.hub.increment_completed_jobs()
            time.sleep(0.4)
            last = self._last_status(q)
            self.assertIsNotNone(last)
            self.assertEqual(last["completed_jobs"], 3)
            self.assertEqual(last["overall_progress"], 60.0)
        finally:
            self.hub.unsubscribe_events(q)

    def test_event_burst_does_not_evict_listener(self):
        q = self.hub.subscribe_events()
        try:
            # 模拟超出队列上限的突发日志
            for i in range(2500):
                self.hub.append_log("INFO", f"burst log {i}")

            # 监听器未被异常剔除，且能正常读取最新消息
            self.assertIn(q, self.hub._listeners)
            self.assertFalse(q.empty())
            last_msg = None
            while not q.empty():
                last_msg = q.get_nowait()
            self.assertIsNotNone(last_msg)
            self.assertEqual(last_msg["event"], "LOG_APPEND")
            self.assertEqual(last_msg["data"]["message"], "burst log 2499")
        finally:
            self.hub.unsubscribe_events(q)
