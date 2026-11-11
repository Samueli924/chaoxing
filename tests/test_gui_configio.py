# -*- coding: utf-8 -*-
"""图形界面配置读写的单元测试：只改指定键，保留注释和顺序."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui import configio  # noqa: E402

SAMPLE = """[common]
; 视频播放倍速
speed = 1
jobs=4

[tiku]
; min_interval_seconds = 3 这是注释，不应被修改
provider=
min_interval_seconds=3
"""


class ConfigIOTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(fd, "w", encoding="utf8") as f:
            f.write(SAMPLE)

    def tearDown(self):
        os.remove(self.path)

    def read_text(self):
        with open(self.path, encoding="utf8") as f:
            return f.read()

    def test_updates_values_and_keeps_comments(self):
        configio.update_config(self.path, {"common": {"speed": 1.5}, "tiku": {"provider": "AI", "min_interval_seconds": 5}})
        text = self.read_text()
        self.assertIn("; 视频播放倍速", text)
        self.assertIn("; min_interval_seconds = 3 这是注释，不应被修改", text)
        cfg = configio.read_config(self.path)
        self.assertEqual(cfg["common"]["speed"], "1.5")
        self.assertEqual(cfg["common"]["jobs"], "4")
        self.assertEqual(cfg["tiku"]["provider"], "AI")
        self.assertEqual(cfg["tiku"]["min_interval_seconds"], "5")

    def test_appends_missing_keys_and_sections(self):
        configio.update_config(self.path, {"common": {"add_learning_count": True}, "gui": {"max_parallel_accounts": 3}})
        cfg = configio.read_config(self.path)
        self.assertEqual(cfg["common"]["add_learning_count"], "true")
        self.assertEqual(cfg["gui"]["max_parallel_accounts"], "3")
        # 新键应该落在 [common] 小节内，而不是文件末尾
        text = self.read_text()
        self.assertLess(text.index("add_learning_count"), text.index("[tiku]"))

    def test_values_with_percent_sign(self):
        configio.update_config(self.path, {"tiku": {"provider": "100%ok"}})
        self.assertEqual(configio.read_config(self.path)["tiku"]["provider"], "100%ok")


if __name__ == "__main__":
    unittest.main()
