import io
import sys
import unittest
from unittest import mock
import main

class ConsoleTest(unittest.TestCase):
    def test_windows_redirected_output_preserves_chinese(self):
        raw = io.BytesIO()
        output = io.TextIOWrapper(raw, encoding="cp1252")
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(sys, "stdout", output), mock.patch.object(sys, "stderr", output):
            main.configure_console()
            print("中文帮助")
            output.flush()
            self.assertEqual(raw.getvalue().decode("utf-8"), "中文帮助\n")
