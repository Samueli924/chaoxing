# -*- coding: utf-8 -*-
"""AI 大模型题库解析响应的回归测试: content 为空、答案只在 reasoning_content 时也要能作答."""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.answer import AI, message_answer_text  # noqa: E402

ANSWER_JSON = json.dumps({"Answer": ["光合作用"]}, ensure_ascii=False)


class MessageAnswerTextTest(unittest.TestCase):
    def test_prefers_content(self):
        msg = SimpleNamespace(content=ANSWER_JSON, reasoning_content='思考过程')
        self.assertEqual(message_answer_text(msg), ANSWER_JSON)

    def test_falls_back_to_reasoning_content(self):
        msg = SimpleNamespace(content=None, reasoning_content=ANSWER_JSON)
        self.assertEqual(message_answer_text(msg), ANSWER_JSON)

    def test_blank_content_falls_back(self):
        msg = SimpleNamespace(content='   \n', reasoning_content=ANSWER_JSON)
        self.assertEqual(message_answer_text(msg), ANSWER_JSON)

    def test_missing_attributes(self):
        self.assertEqual(message_answer_text(SimpleNamespace()), '')


def _make_ai():
    ai = AI()
    ai.config_set({
        'endpoint': 'http://127.0.0.1:9/v1',
        'key': 'test-key',
        'model': 'test-model',
        'http_proxy': '',
        'min_interval_seconds': '0',
    })
    ai._init_tiku()
    return ai


class AIQueryTest(unittest.TestCase):
    Q_INFO = {'type': 'single', 'title': '植物吸收光能转化为什么?', 'options': 'A. 光合作用\nB. 呼吸作用'}

    def _run(self, message):
        client = mock.MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=message)]
        )
        with mock.patch('api.answer.OpenAI', return_value=client):
            return _make_ai()._query(self.Q_INFO)

    def test_reasoning_only_response_is_parsed(self):
        """思考模式正文为空时, 旧代码只会报「无法解析大模型输出内容」并返回 None."""
        msg = SimpleNamespace(content=None, reasoning_content=ANSWER_JSON)
        self.assertEqual(self._run(msg), '光合作用')

    def test_normal_response_still_parsed(self):
        msg = SimpleNamespace(content=ANSWER_JSON, reasoning_content=None)
        self.assertEqual(self._run(msg), '光合作用')

    def test_markdown_wrapped_response(self):
        msg = SimpleNamespace(content='```json\n' + ANSWER_JSON + '\n```', reasoning_content=None)
        self.assertEqual(self._run(msg), '光合作用')

    def test_unparsable_response_returns_none(self):
        msg = SimpleNamespace(content='抱歉，我无法回答', reasoning_content=None)
        self.assertIsNone(self._run(msg))

    def test_unparsable_response_is_not_logged(self):
        """模型输出可能带有题干与个人信息, 解析失败只记异常类型和长度."""
        msg = SimpleNamespace(content='抱歉，无法作答，题干含考生张三', reasoning_content=None)
        with mock.patch('api.answer.logger') as fake_logger:
            self.assertIsNone(self._run(msg))
        logged = ' '.join(
            str(arg) for call in fake_logger.error.call_args_list for arg in call.args
        )
        self.assertIn('JSONDecodeError', logged)
        self.assertIn('长度', logged)
        self.assertNotIn('张三', logged)


if __name__ == '__main__':
    unittest.main()
