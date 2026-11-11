# -*- coding: utf-8 -*-
"""图形界面多账号排队调度的单元测试."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.scheduler import Scheduler  # noqa: E402


class FakeClock:
    def __init__(self):
        """从 0 开始计时."""
        self.t = 1000.0

    def __call__(self):
        return self.t


class SchedulerTest(unittest.TestCase):
    def make(self, max_parallel=2, stagger=(60, 120)):
        self.clock = FakeClock()
        return Scheduler(max_parallel, stagger, clock=self.clock, rng=random.Random(1))  # nosec B311  # 只用于错开启动时间，不涉及安全

    def test_first_starts_immediately(self):
        s = self.make()
        s.enqueue("a")
        self.assertEqual(s.due(active=0), ["a"])

    def test_stagger_between_starts(self):
        s = self.make()
        for x in "abc":
            s.enqueue(x)
        self.assertEqual(s.due(0), ["a"])
        self.assertEqual(s.due(1), [])  # 还在间隔期内
        self.assertTrue(60 <= s.gap <= 120)
        self.clock.t += s.gap
        self.assertEqual(s.due(1), ["b"])

    def test_respects_max_parallel(self):
        s = self.make(max_parallel=1, stagger=(0, 0))
        s.enqueue("a")
        s.enqueue("b")
        self.assertEqual(s.due(0), ["a"])
        self.assertEqual(s.due(1), [])  # 名额已满
        self.assertEqual(s.due(0), ["b"])  # a 结束后放行

    def test_zero_stagger_starts_up_to_limit_at_once(self):
        s = self.make(max_parallel=3, stagger=(0, 0))
        for x in "abcd":
            s.enqueue(x)
        self.assertEqual(s.due(0), ["a", "b", "c"])

    def test_cancel_and_duplicates(self):
        s = self.make()
        self.assertTrue(s.enqueue("a"))
        self.assertFalse(s.enqueue("a"))
        self.assertTrue(s.cancel("a"))
        self.assertFalse(s.cancel("a"))
        self.assertEqual(s.due(0), [])

    def test_estimate(self):
        s = self.make(max_parallel=2, stagger=(60, 120))
        for x in "abc":
            s.enqueue(x)
        s.due(0)  # a 启动
        est_b = s.estimate("b", active=1)
        self.assertEqual(est_b["position"], 1)
        self.assertAlmostEqual(est_b["eta"], s.next_allowed())
        self.assertIsNone(s.estimate("c", active=1)["eta"])  # 要等名额
        self.assertIsNone(s.estimate("zzz", active=1))

    def test_configure_clamps_existing_gap(self):
        s = self.make(stagger=(100, 200))
        s.enqueue("a")
        s.enqueue("b")
        s.due(0)
        s.configure(2, (0, 10))
        self.assertLessEqual(s.gap, 10)
        self.clock.t += 10
        self.assertEqual(s.due(1), ["b"])


if __name__ == "__main__":
    unittest.main()
