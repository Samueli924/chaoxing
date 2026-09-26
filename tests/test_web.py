# -*- coding: utf-8 -*-
"""网页控制台的接口与安全测试（起真实 HTTP 服务，但登录被打桩，不访问学习通）。"""
import json
import os
import sys
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import web  # noqa: E402
from api.settings import Settings  # noqa: E402


def _settings():
    from api.settings import COMMON_DEFAULTS
    return Settings(common=dict(COMMON_DEFAULTS), tiku={}, notification={})


class WebServerTestCase(unittest.TestCase):
    def setUp(self):
        self.server = web.create_server(_settings(), "127.0.0.1", 0, token=None)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path, headers=None):
        req = Request(self._url(path), headers=headers or {})
        try:
            with urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def _post(self, path, body, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        req = Request(self._url(path), data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_index_served(self):
        req = Request(self._url("/"))
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn(b"<!doctype html>", resp.read()[:200].lower())

    def test_ping(self):
        status, data = self._get("/api/ping")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertFalse(data["token_required"])

    def test_state_defaults(self):
        status, data = self._get("/api/state")
        self.assertEqual(status, 200)
        self.assertFalse(data["logged_in"])
        self.assertTrue(any(p["id"] == "TikuGo" for p in data["providers"]))

    def test_post_requires_csrf_header(self):
        # 缺少自定义头（模拟跨站请求）应被拒绝
        status, data = self._post("/api/login", {"username": "x"})
        self.assertEqual(status, 403)

    def test_login_validation(self):
        status, data = self._post("/api/login", {"username": ""}, headers={"X-Requested-With": "chaoxing-web"})
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])

    def test_start_without_login(self):
        status, data = self._post("/api/start", {"courses": ["1_2"]}, headers={"X-Requested-With": "chaoxing-web"})
        self.assertFalse(data["ok"])
        self.assertIn("登录", data["msg"])


class WebTokenTestCase(unittest.TestCase):
    def setUp(self):
        self.server = web.create_server(_settings(), "127.0.0.1", 0, token="secret123")
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def test_state_requires_token(self):
        req = Request(f"http://127.0.0.1:{self.port}/api/state")
        try:
            with urlopen(req) as resp:
                self.fail("应要求口令")
        except HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_state_with_token(self):
        req = Request(f"http://127.0.0.1:{self.port}/api/state", headers={"X-Token": "secret123"})
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)


class TikuOverridesTestCase(unittest.TestCase):
    def test_skip_mode(self):
        self.assertEqual(web.WebApp._tiku_overrides({"work_mode": "skip"}), {"provider": ""})

    def test_submit_mode(self):
        ov = web.WebApp._tiku_overrides({"work_mode": "submit", "provider": "TikuGo"})
        self.assertEqual(ov["provider"], "TikuGo")
        self.assertEqual(ov["submit"], "true")

    def test_only_known_fields(self):
        ov = web.WebApp._tiku_overrides({"work_mode": "save", "provider": "AI",
                                         "tiku": {"key": "k", "evil": "x", "endpoint": " "}})
        self.assertEqual(ov["key"], "k")
        self.assertNotIn("evil", ov)
        self.assertNotIn("endpoint", ov)  # 空白值忽略


if __name__ == "__main__":
    unittest.main()
