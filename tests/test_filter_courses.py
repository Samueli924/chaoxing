# -*- coding: utf-8 -*-
"""course_list 过滤的回归测试: 配置写错时不得静默扩大到全部课程."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import filter_courses  # noqa: E402
from api.exceptions import InputFormatError  # noqa: E402

ALL_COURSE = [
    {"courseId": "267844236", "clazzId": "156654129", "cpi": "405606059", "title": "舌尖上的植物学"},
    {"courseId": "2151141", "clazzId": "111", "cpi": "1", "title": "大学生心理健康教育"},
    # 同一 courseId 下的第二个班级
    {"courseId": "2151141", "clazzId": "222", "cpi": "2", "title": "大学生心理健康教育"},
]


class FilterCoursesTest(unittest.TestCase):
    def test_match_single_course(self):
        """命中 courseId 时只学习该课程."""
        task = filter_courses(ALL_COURSE, ["267844236"])
        self.assertEqual([c["courseId"] for c in task], ["267844236"])

    def test_same_course_id_multiple_classes(self):
        """同一 courseId 的多个班级应分别保留."""
        task = filter_courses(ALL_COURSE, ["2151141"])
        self.assertEqual(sorted(c["clazzId"] for c in task), ["111", "222"])

    def test_unmatched_id_raises_instead_of_learning_all(self):
        """填了课程名而不是 courseId: 必须报错, 不能回退成全部课程."""
        with self.assertRaises(InputFormatError) as ctx:
            filter_courses(ALL_COURSE, ["舌尖上的植物学"])
        msg = str(ctx.exception)
        self.assertIn("舌尖上的植物学", msg)
        self.assertIn("267844236", msg)

    def test_partial_match_reports_only_unmatched(self):
        """部分命中时仍应报错, 且只列出未命中的 ID."""
        with self.assertRaises(InputFormatError) as ctx:
            filter_courses(ALL_COURSE, ["267844236", "999999"])
        self.assertIn("999999", str(ctx.exception))

    def test_explicit_all(self):
        """显式 all / * 才学习全部课程, 并按班级去重."""
        for keyword in ("all", "*"):
            task = filter_courses(ALL_COURSE, [keyword])
            self.assertEqual(len(task), len(ALL_COURSE))

    def test_all_mixed_with_ids_raises(self):
        """显式 all / * 不能与具体ID混写, 否则同列表里填错的ID会被全部课程静默吞掉."""
        for items in (["all", "999999"], ["267844236", "*"]):
            with self.assertRaises(InputFormatError) as ctx:
                filter_courses(ALL_COURSE, items)
            self.assertIn("all / *", str(ctx.exception))

    def test_empty_course_list_with_manual_input(self):
        """交互式输入为空时应报错, 并提示如何学习全部课程."""
        with redirect_stdout(io.StringIO()):
            with mock.patch("builtins.input", return_value=" \n,"):
                with self.assertRaises(InputFormatError):
                    filter_courses(ALL_COURSE, [])

    def test_manual_input_respects_typed_ids(self):
        """交互式输入应清洗空白并按逗号切分."""
        with redirect_stdout(io.StringIO()):
            with mock.patch("builtins.input", return_value=" 267844236 , 2151141"):
                task = filter_courses(ALL_COURSE, [])
        self.assertEqual(len(task), 3)

    def test_whitespace_config_items(self):
        """配置里的空格不应导致匹配失败."""
        task = filter_courses(ALL_COURSE, [" 267844236 "])
        self.assertEqual([c["courseId"] for c in task], ["267844236"])


if __name__ == "__main__":
    unittest.main()
