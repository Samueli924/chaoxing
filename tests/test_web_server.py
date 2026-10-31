import os
import shutil
import unittest

from api.web_server import create_app


class TestWebServer(unittest.TestCase):
    def setUp(self):
        self.test_acc_dir = os.path.abspath(os.path.join("tests", "test_web_accounts"))
        if os.path.exists(self.test_acc_dir):
            shutil.rmtree(self.test_acc_dir)
        self.app = create_app({"TESTING": True, "ACCOUNTS_DIR": self.test_acc_dir})
        self.client = self.app.test_client()

    def tearDown(self):
        from api.task_runner import TaskStateHub
        hub = TaskStateHub()
        hub.set_task_running(False)
        hub.set_web_mode(False)
        if os.path.exists(self.test_acc_dir):
            shutil.rmtree(self.test_acc_dir)

    def test_routes_exist(self):
        resp_acc = self.client.get("/api/accounts")
        self.assertEqual(resp_acc.status_code, 200)
        data = resp_acc.get_json()
        self.assertIn("accounts", data)

        resp_cfg = self.client.get("/api/config/full")
        self.assertEqual(resp_cfg.status_code, 200)
        cfg_data = resp_cfg.get_json()
        self.assertIn("common", cfg_data)

        resp_pending = self.client.get("/api/manual/pending")
        self.assertEqual(resp_pending.status_code, 200)
        pending_data = resp_pending.get_json()
        self.assertIn("questions", pending_data)

        resp_status = self.client.get("/api/status")
        self.assertEqual(resp_status.status_code, 200)

        resp_courses = self.client.get("/api/courses")
        self.assertEqual(resp_courses.status_code, 200)
        self.assertIn("courses", resp_courses.get_json())
        self.assertIn("selected_ids", resp_courses.get_json())

        resp_prog = self.client.get("/api/courses/progress")
        self.assertEqual(resp_prog.status_code, 200)
        self.assertIn("progress", resp_prog.get_json())

    def test_speed_api(self):
        resp = self.client.post("/api/speed/global", json={"speed": 1.5})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["global_speed"], 1.5)

        resp_worker = self.client.post("/api/speed/worker", json={"worker_id": "worker_1", "speed": 1.7})
        self.assertEqual(resp_worker.status_code, 200)
        self.assertEqual(resp_worker.get_json()["speed"], 1.7)

    def test_manual_api(self):
        resp_ans = self.client.post("/api/manual/answer", json={"prompt_id": "non_exist", "answer": "A"})
        self.assertIn(resp_ans.status_code, [200, 404])

        resp_skip = self.client.post("/api/manual/skip", json={"prompt_id": "non_exist"})
        self.assertIn(resp_skip.status_code, [200, 404])

    def test_task_control_api(self):
        resp_start = self.client.post("/api/task/start")
        self.assertIn(resp_start.status_code, [200, 400, 409])

        resp_stop = self.client.post("/api/task/stop")
        self.assertEqual(resp_stop.status_code, 200)

    def test_log_level_api(self):
        resp = self.client.get("/api/log/level")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("level", resp.get_json())

        resp_post = self.client.post("/api/log/level", json={"level": "DEBUG"})
        self.assertEqual(resp_post.status_code, 200)
        self.assertEqual(resp_post.get_json()["level"], "DEBUG")

        resp_inv = self.client.post("/api/log/level", json={"level": "INVALID"})
        self.assertEqual(resp_inv.status_code, 400)

    def test_account_delete_api(self):
        resp_del = self.client.post("/api/accounts/delete", json={"account_id": "non_exist"})
        self.assertEqual(resp_del.status_code, 404)
        resp_missing = self.client.post("/api/accounts/delete", json={})
        self.assertEqual(resp_missing.status_code, 400)
