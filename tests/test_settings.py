# -*- coding: utf-8 -*-
"""配置加载与优先级测试。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import settings as st  # noqa: E402


class SettingsTestCase(unittest.TestCase):
    def _write(self, text: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_placeholder_detection(self):
        self.assertTrue(st.is_placeholder("xxx"))
        self.assertTrue(st.is_placeholder("XXXX"))
        self.assertTrue(st.is_placeholder("手机号"))
        self.assertFalse(st.is_placeholder("13800138000"))
        self.assertFalse(st.is_placeholder(""))

    def test_defaults_when_no_file(self):
        s = st.load_settings(cli_common={}, environ={})
        self.assertEqual(s.common["speed"], 1.0)
        self.assertEqual(s.common["jobs"], 4)
        self.assertEqual(s.common["notopen_action"], "retry")
        self.assertEqual(s.common["course_list"], [])

    def test_placeholders_treated_as_empty(self):
        path = self._write("[common]\nusername = xxx\npassword = xxx\ncourse_list = xxx,xxx\n")
        s = st.load_settings(config=path, environ={})
        self.assertEqual(s.common["username"], "")
        self.assertEqual(s.common["password"], "")
        self.assertEqual(s.common["course_list"], [])

    def test_priority_env_over_file_cli_over_env(self):
        path = self._write("[common]\nusername = 111\nspeed = 1.5\n")
        env = {"CHAOXING_USERNAME": "222", "CHAOXING_SPEED": "2"}
        s = st.load_settings(config=path, cli_common={"username": "333"}, environ=env)
        self.assertEqual(s.common["username"], "333")  # CLI 最高优先级
        self.assertEqual(s.common["speed"], 2.0)       # 环境变量覆盖配置文件

    def test_speed_and_jobs_clamped(self):
        path = self._write("[common]\nspeed = 9\njobs = 0\n")
        s = st.load_settings(config=path, environ={})
        self.assertEqual(s.common["speed"], 2.0)
        self.assertEqual(s.common["jobs"], 1)

    def test_invalid_notopen_action_falls_back(self):
        path = self._write("[common]\nnotopen_action = foo\n")
        s = st.load_settings(config=path, environ={})
        self.assertEqual(s.common["notopen_action"], "retry")

    def test_password_with_percent(self):
        # 密码含 % 不应导致 ConfigParser 解析失败
        path = self._write("[common]\nusername = 13800138000\npassword = ab%cd12\n")
        s = st.load_settings(config=path, environ={})
        self.assertEqual(s.common["password"], "ab%cd12")

    def test_course_list_various_separators(self):
        self.assertEqual(st.split_course_list("1, 2，3  4"), ["1", "2", "3", "4"])
        self.assertEqual(st.split_course_list(["1", " 2 ", ""]), ["1", "2"])

    def test_tiku_env_override(self):
        env = {"CHAOXING_TIKU_PROVIDER": "TikuGo", "CHAOXING_TIKU_SUBMIT": "true"}
        s = st.load_settings(environ=env)
        self.assertEqual(s.tiku["provider"], "TikuGo")
        self.assertEqual(s.tiku["submit"], "true")


if __name__ == "__main__":
    unittest.main()
