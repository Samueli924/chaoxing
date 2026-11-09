# -*- coding: utf-8 -*-
"""本地大模型自动加载 / 卸载的单元测试：用一个模拟的 LM Studio 接口."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.llm_manager import AutoUnloader, LMStudio, LocalLLMError, local_target  # noqa: E402


class FakeLMStudio(BaseHTTPRequestHandler):
    loaded: dict = {}  # instance_id -> model key
    calls: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/v1/models":
            models = []
            for key in ("qwen-27b", "other-model"):
                models.append({"key": key, "loaded_instances": [
                    {"id": i} for i, k in self.loaded.items() if k == key]})
            return self._send(200, {"models": models})
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLMStudio.calls.append((self.path, body))
        if self.path == "/api/v1/models/load":
            if body["model"] not in ("qwen-27b", "other-model"):
                return self._send(404, {"error": {"message": f"Model {body['model']} not found"}})
            self.loaded[body["model"]] = body["model"]
            return self._send(200, {"instance_id": body["model"], "status": "loaded"})
        if self.path == "/api/v1/models/unload":
            if self.loaded.pop(body["instance_id"], None) is None:
                return self._send(404, {"error": {"message": "not loaded"}})
            return self._send(200, {"instance_id": body["instance_id"]})
        self._send(404, {"error": {"message": "not found"}})


class LMStudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeLMStudio)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.root = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        FakeLMStudio.loaded = {}
        FakeLMStudio.calls = []
        self.lm = LMStudio(self.root)

    def test_probe(self):
        self.assertTrue(self.lm.probe())
        self.assertFalse(LMStudio("http://127.0.0.1:9").probe())

    def test_ensure_loaded_only_when_needed(self):
        self.assertTrue(self.lm.ensure_loaded("qwen-27b"))
        self.assertFalse(self.lm.ensure_loaded("qwen-27b"))
        loads = [c for c in FakeLMStudio.calls if c[0].endswith("/load")]
        self.assertEqual(len(loads), 1)

    def test_unload_only_matching_model(self):
        FakeLMStudio.loaded = {"qwen-27b": "qwen-27b", "qwen-27b:2": "qwen-27b", "other-model": "other-model"}
        self.assertEqual(self.lm.unload("qwen-27b"), 2)
        self.assertEqual(FakeLMStudio.loaded, {"other-model": "other-model"})
        self.assertEqual(self.lm.unload("qwen-27b"), 0)

    def test_load_unknown_model_raises(self):
        with self.assertRaises(LocalLLMError) as ctx:
            self.lm.ensure_loaded("missing")
        self.assertIn("not found", str(ctx.exception))


class LocalTargetTest(unittest.TestCase):
    def test_detects_local_ai_endpoint(self):
        conf = {"provider": "AI", "endpoint": "http://127.0.0.1:1234/v1", "model": "qwen-27b"}
        self.assertEqual(local_target(conf), ("http://127.0.0.1:1234", "qwen-27b"))
        conf["provider"] = "TikuYanxi,AI"
        self.assertIsNotNone(local_target(conf))

    def test_ignores_remote_or_other_provider(self):
        self.assertIsNone(local_target({"provider": "AI", "endpoint": "https://api.example.com/v1", "model": "x"}))
        self.assertIsNone(local_target({"provider": "TikuYanxi", "endpoint": "http://127.0.0.1:1234/v1", "model": "x"}))
        self.assertIsNone(local_target({"provider": "AI", "endpoint": "http://localhost:1234/v1", "model": ""}))


class AutoUnloaderTest(unittest.TestCase):
    def setUp(self):
        self.t = 0.0
        self.u = AutoUnloader(grace=15, clock=lambda: self.t)
        self.lm = LMStudio("http://127.0.0.1:1234")

    def test_unloads_after_grace_period(self):
        self.u.used(self.lm, "qwen")
        self.assertEqual(self.u.tick(busy=True), [])
        self.assertEqual(self.u.tick(busy=False), [])  # 开始计时
        self.t = 10
        self.assertEqual(self.u.tick(busy=False), [])
        self.t = 15
        self.assertEqual(self.u.tick(busy=False), [(self.lm, "qwen")])
        self.assertEqual(self.u.tick(busy=False), [])  # 只卸载一次

    def test_new_run_during_grace_cancels(self):
        self.u.used(self.lm, "qwen")
        self.u.tick(busy=False)
        self.t = 10
        self.u.tick(busy=True)  # 「再来一次」
        self.t = 20
        self.assertEqual(self.u.tick(busy=False), [])
        self.t = 35
        self.assertEqual(len(self.u.tick(busy=False)), 1)

    def test_nothing_used_nothing_unloaded(self):
        self.u.tick(busy=False)
        self.t = 100
        self.assertEqual(self.u.tick(busy=False), [])


if __name__ == "__main__":
    unittest.main()
