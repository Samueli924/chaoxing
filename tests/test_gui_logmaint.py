# -*- coding: utf-8 -*-
"""日志清理的单元测试：过期删除、总量上限、活跃日志只裁剪不删除."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.logmaint import MB, enforce, trim_keep_tail  # noqa: E402


class LogMaintTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.now = time.time()

    def make(self, name, size, age_days=0):
        p = self.dir / name
        line = b"x" * 99 + b"\n"
        p.write_bytes(line * (size // 100))
        t = self.now - age_days * 86400
        os.utime(p, (t, t))
        return p

    def test_expired_files_deleted_but_active_kept(self):
        old = self.make("worker-old.log", 1000, age_days=10)
        server = self.make("server.log", 1000, age_days=10)
        recent = self.make("worker-new.log", 1000, age_days=1)
        res = enforce([old, server, recent], max_bytes=10 * MB, keep_days=7, active=[server], now=self.now)
        self.assertFalse(old.exists())
        self.assertTrue(server.exists())
        self.assertTrue(recent.exists())
        self.assertEqual(res["deleted"], [old])

    def test_over_budget_deletes_oldest_inactive_first(self):
        a = self.make("chaoxing.1.log", 4 * MB, age_days=3)
        b = self.make("chaoxing.2.log", 4 * MB, age_days=2)
        c = self.make("worker-x.log", 4 * MB, age_days=1)
        res = enforce([a, b, c], max_bytes=10 * MB, keep_days=7, now=self.now)
        self.assertFalse(a.exists())
        self.assertTrue(b.exists() and c.exists())
        self.assertLessEqual(res["total"], 10 * MB)

    def test_active_files_trimmed_keep_latest_lines(self):
        server = self.dir / "server.log"
        server.write_bytes(b"".join(f"line {i:07d}\n".encode() for i in range(400000)))  # 约 5.3 MB
        worker = self.make("worker-run.log", 6 * MB)
        res = enforce([server, worker], max_bytes=4 * MB, keep_days=7, active=[server, worker], now=self.now)
        self.assertTrue(server.exists() and worker.exists())
        self.assertLessEqual(res["total"], 4 * MB)
        content = server.read_bytes()
        self.assertTrue(content.endswith(b"line 0399999\n"))  # 保留了最新内容
        self.assertTrue(content.startswith(b"line "))  # 从整行开始

    def test_trim_keep_tail_small_file_untouched(self):
        p = self.make("a.log", 1000)
        trim_keep_tail(p, 5000)
        self.assertEqual(p.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
