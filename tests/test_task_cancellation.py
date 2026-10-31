import unittest
from unittest.mock import MagicMock
from api.base import Chaoxing, StudyResult
from api.task_runner import TaskStateHub
from main import stop_study_task


class TestTaskCancellation(unittest.TestCase):
    def setUp(self):
        self.hub = TaskStateHub()
        self.hub.set_web_mode(True)
        self.hub.set_task_running(True)

    def tearDown(self):
        self.hub.set_task_running(False)
        self.hub.set_web_mode(False)
        self.hub.clear_workers()

    def test_study_video_aborts_immediately_when_stopped(self):
        cx = Chaoxing()
        mock_session = MagicMock()
        cx._session = mock_session

        info_resp = MagicMock()
        info_resp.json.return_value = {
            "status": "success",
            "dtoken": "tok1",
            "duration": 100,
            "crc": "",
            "key": "",
        }
        mock_session.get.return_value = info_resp

        cx.video_progress_log = MagicMock(return_value=(False, 200))
        self.hub.set_task_running(False)

        res = cx.study_video(
            {"clazzId": "1", "courseId": "2", "cpi": "3", "title": "测试课程"},
            {"jobid": "1", "objectid": "obj1", "name": "测试视频", "playTime": 0},
            {},
        )
        self.assertEqual(res, StudyResult.ERROR)

    def test_stop_study_task_handles_none_processor(self):
        import main
        with main._task_run_lock:
            main._is_task_running = True
            main._current_study_processor = None

        self.assertTrue(stop_study_task())
        self.assertFalse(self.hub.is_task_running())

    def test_job_processor_exits_cleanly_on_cancellation_during_work(self):
        import threading
        import time
        import main

        started_evt = threading.Event()

        class SlowAbortChaoxing:
            def __init__(self):
                self.rate_limiter = MagicMock()

            def get_job_list(self, course, point):
                started_evt.set()
                time.sleep(0.15)
                return [{"type": "unknown"}], {}

        tasks = [
            main.ChapterTask(index=i, point={"title": f"p{i}", "has_finished": False}, course={"title": "c1"})
            for i in range(4)
        ]
        processor = main.JobProcessor(
            SlowAbortChaoxing(),
            tasks,
            {"speed": 1.0, "jobs": 2, "notopen_action": "retry", "retry_interval": 0.05},
        )
        with main._task_run_lock:
            main._is_task_running = True
            main._current_study_processor = processor

        runner_thread = threading.Thread(target=processor.run, daemon=True)
        runner_thread.start()
        self.assertTrue(started_evt.wait(timeout=2.0))
        self.assertTrue(stop_study_task())
        runner_thread.join(timeout=2.0)
        self.assertFalse(runner_thread.is_alive())

    def test_cancel_while_task_in_retry_queue_does_not_deadlock(self):
        import threading
        import time
        import main

        class FailOnceChaoxing:
            def __init__(self):
                self.rate_limiter = MagicMock()

            def get_job_list(self, course, point):
                return [{"type": "unknown"}], {}

        tasks = [
            main.ChapterTask(index=0, point={"title": "p0", "has_finished": False}, course={"title": "c1"})
        ]
        processor = main.JobProcessor(
            FailOnceChaoxing(),
            tasks,
            {"speed": 1.0, "jobs": 1, "notopen_action": "retry", "retry_interval": 10.0},
        )
        with main._task_run_lock:
            main._is_task_running = True
            main._current_study_processor = processor

        runner_thread = threading.Thread(target=processor.run, daemon=True)
        runner_thread.start()
        time.sleep(0.1)
        self.assertTrue(stop_study_task())
        runner_thread.join(timeout=2.0)
        self.assertFalse(runner_thread.is_alive())
        self.assertEqual(processor.task_queue.unfinished_tasks, 0)

    def test_cancel_unblocks_pending_manual_question(self):
        import threading
        import time
        import main

        res_box = []
        entered_evt = threading.Event()

        def worker():
            entered_evt.set()
            ans = self.hub.request_manual_answer({"title": "阻塞题", "type": "single"}, timeout=30.0)
            res_box.append(ans)

        with main._task_run_lock:
            main._is_task_running = True
            main._current_study_processor = None

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        self.assertTrue(entered_evt.wait(timeout=1.0))
        time.sleep(0.05)
        self.assertTrue(stop_study_task())
        t.join(timeout=1.0)
        self.assertFalse(t.is_alive())
        self.assertEqual(res_box, [None])


if __name__ == "__main__":
    unittest.main()
