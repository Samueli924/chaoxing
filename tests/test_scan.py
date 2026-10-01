# -*- coding: utf-8 -*-
"""
开始前扫描 + 刷课数量语义 + 只刷讨论 的离线回归。

数量语义（用户最关心的）：
  数字 = 本次刷多少个「还没完成」的任务点，已完成的自动跳过，不会重刷。
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-scan-"))

import main as main_mod  # noqa: E402
from api import scan  # noqa: E402


class CountSemanticsTestCase(unittest.TestCase):
    """共 300 节、前 150 节已完成：填 150 应该是把后 150 节刷完"""

    @staticmethod
    def _points():
        return [{"title": "第%d节" % i, "has_finished": i <= 150} for i in range(1, 301)]

    def test_number_means_next_unfinished_points(self):
        finished, pending, selected = main_mod.select_points_for_course(self._points(), 150)
        self.assertEqual(len(finished), 150)
        self.assertEqual(len(pending), 150)
        self.assertEqual(len(selected), 150)
        self.assertEqual(selected[0]["title"], "第151节")
        self.assertEqual(selected[-1]["title"], "第300节")
        self.assertTrue(all(not p["has_finished"] for p in selected))

    def test_number_larger_than_pending_means_all(self):
        _finished, _pending, selected = main_mod.select_points_for_course(self._points(), 500)
        self.assertEqual(len(selected), 150)

    def test_zero_means_all_pending(self):
        _finished, _pending, selected = main_mod.select_points_for_course(self._points(), 0)
        self.assertEqual(len(selected), 150)


class FakeTaskCenter:
    """最小可用的任务中心替身"""

    def __init__(self, groups, plans_by_group, finished_ids=()):
        self._groups = groups
        self._plans = plans_by_group
        self._finished = set(finished_ids)

    def get_course_tasks(self, course):
        return [{"name": "第1章", "id": 1}]

    def open_task(self, task):
        return {"encryTaskUserId": "u1"}

    def get_groups(self, encry):
        return self._groups

    def get_plans(self, encry, group_id):
        return self._plans.get(group_id, [])

    def plan_finished(self, plan):
        return str(plan.get("planId")) in self._finished


class ScanRenderTestCase(unittest.TestCase):
    def test_chapter_row_counts(self):
        row = scan.chapter_row({"title": "示例课程"},
                               [{"has_finished": True, "title": "1.1"},
                                {"has_finished": False, "title": "2.1"}])
        self.assertEqual(row["total"], 2)
        self.assertEqual(row["finished"], 1)
        self.assertEqual(row["pending"], 1)
        self.assertEqual(row["first"], "2.1")

    def test_report_mentions_missing_items(self):
        chapter_rows = [scan.chapter_row({"title": "示例课程"},
                                         [{"has_finished": True, "title": "1.1"},
                                          {"has_finished": False, "title": "2.1"}])]
        tc_rows = [{
            "title": "示例课程", "tasks": 3, "done": 1, "todo": 1, "locked": 1,
            "by_type": {"作业": 1}, "locked_by_type": {"主题讨论": 1},
            "unsupported": ["思考题"], "error": "",
        }]
        out = scan.render(chapter_rows, tc_rows, True, True)
        self.assertIn("开始前扫描", out)
        self.assertIn("待刷 1", out)
        self.assertIn("作业 1", out)
        self.assertIn("思考题 暂不支持", out)
        self.assertIn("被前面的分组锁着", out)

    def test_scan_task_center_classifies(self):
        groups = [{"encryptGroupId": "g1", "groupAllowStudy": True}]
        plans = {"g1": [
            {"planId": 1, "planType": 4, "name": "作业"},
            {"planId": 2, "planType": 14, "name": "讨论"},
            {"planId": 3, "planType": 9, "name": "思考题"},
        ]}
        fake = FakeTaskCenter(groups, plans, finished_ids=["1"])
        with mock.patch("api.task_center.TaskCenter", return_value=fake):
            rows = scan.scan_task_center(object(), [{"title": "示例课程"}], {})
        row = rows[0]
        self.assertEqual(row["done"], 1)
        self.assertEqual(row["todo"], 1)          # 只有讨论是可学的待完成
        self.assertIn("思考题", row["unsupported"])
        self.assertEqual(row["by_type"].get("主题讨论"), 1)

    def test_scan_failure_is_soft(self):
        with mock.patch("api.task_center.TaskCenter", side_effect=RuntimeError("boom")):
            rows = scan.scan_task_center(object(), [{"title": "课"}], {})
        self.assertEqual(rows, [])
        with mock.patch.object(scan, "scan_task_center", side_effect=RuntimeError("boom")):
            out = scan.run(object(), [{"title": "课"}], {}, [], True, True)
        self.assertIn("开始前扫描", out)


class OnlyDiscussionTestCase(unittest.TestCase):
    """只刷讨论：其它类型的任务点本次跳过，并且不判失败"""

    def test_non_discussion_plans_are_skipped(self):
        groups = [{"encryptGroupId": "g1", "groupAllowStudy": True}]
        plans = {"g1": [
            {"planId": 1, "planType": 4, "name": "作业"},
            {"planId": 2, "planType": 14, "name": "讨论"},
        ]}
        fake = FakeTaskCenter(groups, plans)
        stats = {"skipped_other": 0}
        handled = []

        def fake_complete(tc, chaoxing, course, plan, info, config, point_map):
            handled.append(int(plan.get("planType")))
            fake._finished.add(str(plan.get("planId")))   # 处理后即完成，避免无限循环
            return True

        with mock.patch.object(main_mod, "_complete_teaching_plan", side_effect=fake_complete), \
             mock.patch.object(main_mod, "_load_course_point_map", return_value={}):
            main_mod._process_teaching_task(
                fake, object(), {"title": "课", "courseId": "1"}, {"name": "第1章"},
                {}, {}, only_discussion=True, stats=stats,
            )
        self.assertEqual(handled, [14])
        self.assertEqual(stats["skipped_other"], 1)



    def test_skip_discussion_skips_task_discussions(self):
        """board 模式：任务中心里跳过主题讨论（之前 skip_discussion 未定义直接 NameError）"""
        groups = [{"encryptGroupId": "g1", "groupAllowStudy": True}]
        plans = {"g1": [
            {"planId": 1, "planType": 14, "name": "讨论"},
            {"planId": 2, "planType": 4, "name": "作业"},
        ]}
        fake = FakeTaskCenter(groups, plans)
        stats = {"skipped_other": 0}
        handled = []

        def fake_complete(tc, chaoxing, course, plan, info, config, point_map):
            handled.append(int(plan.get("planType")))
            fake._finished.add(str(plan.get("planId")))
            return True

        with mock.patch.object(main_mod, "_complete_teaching_plan", side_effect=fake_complete), \
             mock.patch.object(main_mod, "_load_course_point_map", return_value={}):
            main_mod._process_teaching_task(
                fake, object(), {"title": "课", "courseId": "1"}, {"name": "第1章"},
                {}, {}, skip_discussion=True, stats=stats,
            )
        self.assertEqual(handled, [4])
        self.assertEqual(stats["skipped_other"], 1)

    def test_main_assigns_skip_discussion(self):
        """main() 里必须有 skip_discussion 赋值，否则任务中心阶段每次 NameError"""
        source = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"),
            encoding="utf-8").read()
        self.assertIn("skip_discussion = board_mode", source)


if __name__ == "__main__":
    unittest.main()
