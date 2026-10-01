# -*- coding: utf-8 -*-
"""
复核环节（api/review.py）回归：留痕、列表、正文渲染，以及写作钩子。

留痕必须落盘可查，且写失败/空内容不能污染记录；钩子要真的把
"会被平台看到的文字"记下来（简答题/讨论/实践作答）。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-review-"))

from api import review  # noqa: E402


class ReviewLogTestCase(unittest.TestCase):
    def test_record_and_load_roundtrip(self):
        item = review.record("讨论回复", "我觉得波特五力里最难判断的是替代品。",
                             course="示例课程", task="讨论任务A")
        self.assertIsNotNone(item)
        items = review.load()
        self.assertTrue(items)
        latest = items[0]
        self.assertEqual(latest["kind"], "讨论回复")
        self.assertEqual(latest["course"], "示例课程")
        self.assertIn("替代品", latest["text"])
        self.assertEqual(latest["chars"], len(latest["text"]))

    def test_markdown_file_keeps_human_readable_copy(self):
        review.record("作业简答", "我倾向于先把主业做扎实，再考虑多元化。",
                      course="示例课程", task="总体战略对比分析")
        path = review.markdown_path()
        self.assertTrue(os.path.exists(path))
        body = open(path, encoding="utf-8").read()
        self.assertIn("总体战略对比分析", body)
        self.assertIn("先把主业做扎实", body)

    def test_empty_text_is_not_recorded(self):
        before = len(review.load())
        self.assertIsNone(review.record("讨论回复", "   "))
        self.assertEqual(len(review.load()), before)

    def test_render_index_lists_items(self):
        review.record("测验简答", "企业应该根据自身资源做权变选择。",
                      course="示例课程", task="1.2 章节测验")
        text = review.render_index(review.load(limit=1))
        self.assertIn("测验简答", text)
        self.assertIn("示例课程", text)

    def test_render_item_wraps_and_shows_meta(self):
        long_text = "这是一段比较长的回答。" * 12
        review.record("AI实践作答", long_text, course="示例课程", task="AI实践任务A")
        text = review.render_item(review.load(limit=1)[0], "[1/1]")
        self.assertIn("AI实践任务A", text)
        self.assertIn("AI实践作答", text)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 80)

    def test_empty_state_is_friendly(self):
        text = review.render_index([])
        self.assertIn("还没有可复核的内容", text)

    def test_count_today_counts_todays_records(self):
        before = review.count_today()
        review.record("讨论回复", "随便说两句，凑个字数。")
        self.assertEqual(review.count_today(), before + 1)

    def test_cli_list_mode_returns_zero(self):
        with mock.patch("builtins.print"):
            self.assertEqual(review.review_cli(["--list"]), 0)


class FakeTiku:
    DISABLE = False

    def query_all(self, questions, query_delay=0):
        return [None] * len(questions)


class FakeWriter:
    available = True

    def __init__(self):
        self.calls = []

    def answer(self, question, **kwargs):
        self.calls.append(question)
        return "我觉得专业化更稳一些，先把主业做扎实。"


class HomeworkShortAnswerHookTestCase(unittest.TestCase):
    def test_short_answer_is_recorded(self):
        from api.task_center import TaskCenter
        tc = TaskCenter(object(), {})
        tc.chaoxing = type("CX", (), {"tiku": FakeTiku()})()
        tc.writer = FakeWriter()
        questions = [{"id": 7, "type": "shortanswer", "title": "你更支持哪种战略？",
                      "options": "", "answerField": {}}]
        with mock.patch("api.task_center.review.record") as recorder:
            failure = tc._fill_homework_answers(questions, course={"title": "示例课程"},
                                                task_name="总体战略对比分析")
        self.assertIsNone(failure)
        self.assertTrue(recorder.called)
        args, kwargs = recorder.call_args
        self.assertEqual(args[0], "作业简答")
        self.assertIn("专业化", args[1])
        self.assertEqual(kwargs.get("course"), "示例课程")
        self.assertEqual(kwargs.get("task"), "总体战略对比分析")


class LiveTraceTestCase(unittest.TestCase):
    """运行中实时留痕：控制台看得到、普通运行日志也留一份"""

    def test_answer_line_formats_letters_and_types(self):
        from api.display import answer_line, answers_header
        self.assertEqual(answers_header("总体战略对比分析", 4), "  作答 · 总体战略对比分析（4 题）")
        line = answer_line(1, "single", "A", "以下属于波特五力的是")
        self.assertIn("1. 选择", line)
        self.assertIn("A", line)

    def test_long_answer_is_clipped_with_char_count(self):
        from api.display import answer_line
        long_text = "我觉得应该先把主业做扎实再考虑多元化。" * 5
        line = answer_line(3, "shortanswer", long_text)
        self.assertIn("字）", line)
        self.assertLessEqual(len(line), 80)

    def test_emit_writes_console_and_run_log(self):
        """留痕要同时进控制台和运行日志（这里校验调用契约，避免异步写盘抖动）"""
        import contextlib
        import io
        from api import display
        from api import logger as logger_mod
        buf = io.StringIO()
        with mock.patch.object(logger_mod, "log_file_only") as file_log, \
             contextlib.redirect_stdout(buf):
            display.emit("留痕测试：第 1 题选择 A")
        self.assertIn("留痕测试", buf.getvalue())
        file_log.assert_called_once()
        self.assertIn("留痕测试：第 1 题选择 A", file_log.call_args.args[0])

    def test_homework_emits_one_line_per_question(self):
        from api.task_center import TaskCenter
        tc = TaskCenter(object(), {})
        tc.chaoxing = type("CX", (), {"tiku": FakeTiku()})()
        tc.writer = FakeWriter()
        questions = [
            {"id": 1, "type": "shortanswer", "title": "你更支持哪种战略？",
             "options": "", "answerField": {}},
        ]
        with mock.patch("api.task_center.emit") as emitter:
            failure = tc._fill_homework_answers(questions, course={"title": "示例课程"},
                                                task_name="总体战略对比分析")
        self.assertIsNone(failure)
        printed = [str(c.args[0]) for c in emitter.call_args_list if c.args]
        self.assertTrue(any("作答 · 总体战略对比分析" in line for line in printed))
        self.assertTrue(any("简答" in line for line in printed))


if __name__ == "__main__":
    unittest.main()
