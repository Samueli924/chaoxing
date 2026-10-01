# -*- coding: utf-8 -*-
"""
大模型调用策略（api/llm.py）与答题解析/投票回归。

背景：DeepSeek flash 不同版本的 thinking 行为不同——旧版正文为空、新版默认带推理。
代码不能再写死"永远关 thinking"（会降低正确率），也不能假设一定有 content。
全部离线，不联网。
"""
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-llm-"))

from api import llm  # noqa: E402
from api.answer import AI, parse_answer_text  # noqa: E402


class FakeMessage:
    def __init__(self, content="", reasoning=""):
        self.content = content
        self.reasoning_content = reasoning


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class FakeClient:
    """按脚本依次返回响应或抛错"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                item = outer.script.pop(0) if outer.script else FakeResponse(FakeMessage(""))
                if isinstance(item, BaseException):
                    raise item
                return item

        self.chat = type("Chat", (), {"completions": Completions()})()


class ThinkingPolicyTestCase(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(llm.normalize_thinking(None), "auto")
        self.assertEqual(llm.normalize_thinking("ON"), "on")
        self.assertEqual(llm.normalize_thinking("off"), "off")
        self.assertEqual(llm.normalize_thinking("bogus"), "auto")

    def test_steps(self):
        self.assertEqual(llm.thinking_steps("auto"), ["auto", "off"])
        self.assertEqual(llm.thinking_steps("on"), ["on", "auto"])
        self.assertEqual(llm.thinking_steps("off"), ["off", "auto"])

    def test_extract_text(self):
        self.assertEqual(llm.extract_text(FakeMessage(" a ", " b ")), ("a", "b"))
        self.assertEqual(llm.extract_text({"content": "x"}), ("x", ""))

    def test_thinking_param_error(self):
        self.assertTrue(llm.is_thinking_param_error(Exception("Unsupported parameter: thinking")))
        self.assertFalse(llm.is_thinking_param_error(Exception("timeout")))


class CreateCompletionTestCase(unittest.TestCase):
    def test_returns_content(self):
        client = FakeClient([FakeResponse(FakeMessage('{"Answer": ["A"]}'))])
        out = llm.create_completion(client, model="m", messages=[], thinking="auto")
        self.assertEqual(out, '{"Answer": ["A"]}')
        self.assertNotIn("extra_body", client.calls[0])  # auto 不显式指定 thinking

    def test_reasoning_fallback_only_for_answer_path(self):
        client = FakeClient([FakeResponse(FakeMessage("", "答案是 A"))])
        self.assertEqual(
            llm.create_completion(client, model="m", messages=[],
                                  allow_reasoning_fallback=True),
            "答案是 A",
        )
        client2 = FakeClient([FakeResponse(FakeMessage("", "答案是 A")),
                              FakeResponse(FakeMessage("正常正文"))])
        self.assertEqual(llm.create_completion(client2, model="m", messages=[]), "正常正文")

    def test_empty_content_falls_back_to_thinking_off(self):
        client = FakeClient([FakeResponse(FakeMessage("")), FakeResponse(FakeMessage("ok"))])
        out = llm.create_completion(client, model="m", messages=[], thinking="auto")
        self.assertEqual(out, "ok")
        self.assertEqual(client.calls[0].get("extra_body"), None)
        self.assertEqual(client.calls[1].get("extra_body"), {"thinking": {"type": "disabled"}})

    def test_param_error_retries_without_thinking(self):
        client = FakeClient([Exception("400 Unsupported parameter: thinking"),
                             FakeResponse(FakeMessage("ok"))])
        out = llm.create_completion(client, model="m", messages=[], thinking="off")
        self.assertEqual(out, "ok")
        self.assertNotIn("extra_body", client.calls[1])


class ParseAnswerTestCase(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(parse_answer_text('{"Answer": ["A"]}'), "A")
        self.assertEqual(parse_answer_text('\u0060\u0060\u0060json\n{"Answer": ["A","C"]}\n\u0060\u0060\u0060'), "A\nC")
        self.assertEqual(parse_answer_text('["A", "B"]'), "A\nB")
        self.assertEqual(parse_answer_text("答案：A"), "A")
        self.assertEqual(parse_answer_text("A"), "A")
        self.assertEqual(parse_answer_text(""), "")


class VotingTestCase(unittest.TestCase):
    def _ai(self, script, votes=3):
        tiku = AI.__new__(AI)
        tiku.name = "AI大模型答题"
        tiku.model = "test-model"
        tiku.thinking = "auto"
        tiku.objective_votes = votes
        tiku.min_interval_seconds = 0
        tiku.last_request_time = None
        tiku._lock = threading.Lock()
        tiku.work_feedback = None
        tiku._wait_for_interval = lambda: None
        tiku._build_work_feedback_text = lambda: ""
        seq = iter(script)

        def fake_complete(messages, **kwargs):
            item = next(seq)
            if isinstance(item, BaseException):
                raise item
            return item

        tiku._complete = fake_complete
        return tiku

    def test_majority_wins(self):
        tiku = self._ai(["A", '{"Answer": ["A", "C"]}', "A、C"])
        out = tiku._query_locked({"type": "multiple", "title": "t", "options": "A x\nB y\nC z"})
        self.assertEqual(out, "A\nC")

    def test_single_question_uses_one_vote(self):
        tiku = self._ai(["B"], votes=3)
        out = tiku._query_locked({"type": "single", "title": "t", "options": "A x\nB y"})
        self.assertEqual(out, "B")

    def test_all_calls_failed_returns_none(self):
        tiku = self._ai([Exception("boom"), Exception("boom"), Exception("boom")])
        self.assertIsNone(
            tiku._query_locked({"type": "multiple", "title": "t", "options": "A x"})
        )


if __name__ == "__main__":
    unittest.main()
