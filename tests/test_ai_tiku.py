# -*- coding: utf-8 -*-
"""AI 大模型答题：图片题、超时、关闭思考和输出解析的单元测试（使用模拟的 OpenAI 客户端）."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from openai import APITimeoutError, BadRequestError  # noqa: E402

import api.answer as answer_mod  # noqa: E402
from api.answer import AI  # noqa: E402

BASE_CONF = {
    "provider": "AI", "endpoint": "http://127.0.0.1:1234/v1", "key": "k", "model": "m",
    "http_proxy": "", "min_interval_seconds": "0", "submit": "false", "cover_rate": "0.9",
    "true_list": "正确,对", "false_list": "错误,错",
}


def make_ai(**extra):
    ai = AI()
    ai.config_set({**BASE_CONF, **extra})
    ai.init_tiku()
    return ai


def completion(content, finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)])


class FakeClient:
    """记录请求参数，按顺序返回预设结果（异常则抛出）。"""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def bad_request():
    req = httpx.Request("POST", "http://x")
    return BadRequestError("image not supported", response=httpx.Response(400, request=req), body=None)


IMG_Q = {"type": "single", "title": '【单选题】如图<img src="https://img.example/a.png">所示，速度为',
         "options": 'A2m/s\nB<img src="https://img.example/b.png">\nC6m/s'}


class ConfigTest(unittest.TestCase):
    def test_defaults_when_missing(self):
        ai = make_ai()
        self.assertTrue(ai.vision)
        self.assertFalse(ai.disable_thinking)
        self.assertEqual(ai.request_timeout, 120)
        self.assertEqual(ai.max_tokens, 4096)

    def test_custom_values(self):
        ai = make_ai(ai_vision="false", ai_disable_thinking="true", ai_timeout="30", ai_max_tokens="1000")
        self.assertFalse(ai.vision)
        self.assertTrue(ai.disable_thinking)
        self.assertEqual(ai.request_timeout, 30)
        self.assertEqual(ai.max_tokens, 1000)


class ParseTest(unittest.TestCase):
    def test_variants(self):
        p = AI._parse_answer
        self.assertEqual(p('{"Answer": ["4m/s"]}'), "4m/s")
        self.assertEqual(p('\n\n```json\n{"Answer": ["A", "B"]}\n```'), "A\nB")
        self.assertEqual(p('<think>想一想</think>{"Answer": ["正确"]}'), "正确")
        self.assertEqual(p('答案如下：{"Answer": ["鸦片歌"]} 希望有帮助'), "鸦片歌")
        self.assertEqual(p('{"Answer": "单个字符串"}'), "单个字符串")
        self.assertIsNone(p(''))
        self.assertIsNone(p(None))
        self.assertIsNone(p('我不知道'))


class QueryTest(unittest.TestCase):
    def run_query(self, ai, results, q=IMG_Q):
        client = FakeClient(results)
        with mock.patch.object(AI, "_client", return_value=client):
            return ai._query(dict(q)), client

    def test_images_sent_to_model(self):
        ai = make_ai()
        with mock.patch.object(AI, "_fetch_image", side_effect=lambda u: f"data:image/png;base64,{u[-5:]}"):
            ans, client = self.run_query(ai, [completion('{"Answer": ["2m/s"]}')])
        self.assertEqual(ans, "2m/s")
        content = client.calls[0]["messages"][-1]["content"]
        self.assertIsInstance(content, list)
        self.assertIn("[图1]", content[0]["text"])
        self.assertIn("[图2]", content[0]["text"])
        self.assertNotIn("<img", content[0]["text"])
        self.assertEqual([c["type"] for c in content[1:]], ["image_url", "image_url"])
        self.assertEqual(client.calls[0]["max_tokens"], 4096)

    def test_image_download_failure_falls_back_to_text(self):
        ai = make_ai()
        with mock.patch.object(AI, "_fetch_image", return_value=None):
            ans, client = self.run_query(ai, [completion('{"Answer": ["2m/s"]}')])
        content = client.calls[0]["messages"][-1]["content"]
        self.assertIsInstance(content, str)
        self.assertIn("图片无法提供", content)

    def test_vision_disabled(self):
        ai = make_ai(ai_vision="false")
        with mock.patch.object(AI, "_fetch_image") as fetch:
            self.run_query(ai, [completion('{"Answer": ["2m/s"]}')])
        fetch.assert_not_called()

    def test_model_without_vision_retries_as_text(self):
        ai = make_ai()
        with mock.patch.object(AI, "_fetch_image", return_value="data:image/png;base64,xx"):
            ans, client = self.run_query(ai, [bad_request(), completion('{"Answer": ["6m/s"]}')])
            self.assertEqual(ans, "6m/s")
            self.assertIsInstance(client.calls[1]["messages"][-1]["content"], str)
            self.assertFalse(ai._vision_ok)
            # 之后的题目不再尝试发送图片
            _, client2 = self.run_query(ai, [completion('{"Answer": ["6m/s"]}')])
        self.assertIsInstance(client2.calls[0]["messages"][-1]["content"], str)

    def test_timeout_skips_question(self):
        ai = make_ai(ai_vision="false")
        ans, _ = self.run_query(ai, [APITimeoutError(request=httpx.Request("POST", "http://x"))])
        self.assertIsNone(ans)

    def test_length_limit_returns_none(self):
        ai = make_ai(ai_vision="false")
        ans, _ = self.run_query(ai, [completion("", finish="length")])
        self.assertIsNone(ans)

    def test_disable_thinking_appends_no_think(self):
        ai = make_ai(ai_vision="false", ai_disable_thinking="true")
        q = {"type": "judgement", "title": "泊松分布的期望等于方差", "options": ""}
        _, client = self.run_query(ai, [completion('{"Answer": ["正确"]}')], q=q)
        self.assertTrue(client.calls[0]["messages"][-1]["content"].endswith("/no_think"))

    def test_text_question_unchanged(self):
        ai = make_ai()
        q = {"type": "single", "title": "1+1=", "options": "A1\nB2"}
        _, client = self.run_query(ai, [completion('{"Answer": ["2"]}')], q=q)
        self.assertEqual(client.calls[0]["messages"][-1]["content"], "题目：1+1=\n选项：1\n2")

    def test_client_uses_timeout_without_retries(self):
        ai = make_ai(ai_timeout="45")
        with mock.patch.object(answer_mod, "OpenAI") as ctor:
            ai._client()
        kwargs = ctor.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 45)
        self.assertEqual(kwargs["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
