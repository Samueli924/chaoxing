import unittest
from unittest.mock import MagicMock, patch

from api.answer import AI


def make_conf(**overrides):
    conf = {
        'endpoint': 'https://example.com/v1',
        'key': 'test-key',
        'model': 'test-model',
        'http_proxy': '',
        'min_interval_seconds': '0',
        'extra_body': '',
        'json_mode': '',
    }
    conf.update(overrides)
    return conf


def make_ai(**conf_overrides):
    ai = AI()
    ai._conf = make_conf(**conf_overrides)
    ai._init_tiku()
    return ai


def make_completion(content):
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=content, reasoning_content=None))]
    return completion


class TestExtraBodyDefault(unittest.TestCase):
    def test_missing_uses_default(self):
        conf = make_conf()
        del conf['extra_body']
        ai = AI()
        ai._conf = conf
        ai._init_tiku()
        self.assertEqual(ai.extra_body, {'thinking': {'type': 'disabled'}})

    def test_empty_uses_default(self):
        self.assertEqual(make_ai(extra_body='').extra_body,
                         {'thinking': {'type': 'disabled'}})

    def test_default_constant_is_valid_object(self):
        import json
        self.assertIsInstance(json.loads(AI.DEFAULT_EXTRA_BODY), dict)

    def test_empty_object_kept(self):
        self.assertEqual(make_ai(extra_body='{}').extra_body, {})

    def test_valid_json_parsed(self):
        self.assertEqual(make_ai(extra_body='{"enable_thinking": false}').extra_body,
                         {'enable_thinking': False})

    def test_invalid_json_ignored(self):
        self.assertEqual(make_ai(extra_body='not-json').extra_body, {})

    def test_non_object_ignored(self):
        self.assertEqual(make_ai(extra_body='[1, 2]').extra_body, {})


class TestExtraBodyMerge(unittest.TestCase):
    def setUp(self):
        self.ai = make_ai(extra_body='{"a": 1}')

    def test_injected_into_kwargs(self):
        kwargs = self.ai._completion_kwargs(model='m')
        self.assertEqual(kwargs['extra_body'], {'a': 1})

    def test_merges_with_caller_kwargs(self):
        kwargs = self.ai._completion_kwargs(model='m', extra_body={'b': 2})
        self.assertEqual(kwargs['extra_body'], {'a': 1, 'b': 2})

    def test_no_extra_body_no_key(self):
        ai = make_ai(extra_body='{}')
        self.assertNotIn('extra_body', ai._completion_kwargs(model='m'))


class TestJsonModeParsing(unittest.TestCase):
    def test_missing_is_false(self):
        conf = make_conf()
        del conf['json_mode']
        ai = AI()
        ai._conf = conf
        ai._init_tiku()
        self.assertFalse(ai.json_mode)

    def test_empty_is_false(self):
        self.assertFalse(make_ai(json_mode='').json_mode)

    def test_false_is_false(self):
        self.assertFalse(make_ai(json_mode='false').json_mode)
        self.assertFalse(make_ai(json_mode='False').json_mode)

    def test_true_is_true(self):
        self.assertTrue(make_ai(json_mode='true').json_mode)
        self.assertTrue(make_ai(json_mode='True').json_mode)

    def test_invalid_is_false(self):
        self.assertFalse(make_ai(json_mode='yes').json_mode)


class TestJsonModeKwargs(unittest.TestCase):
    def test_response_format_injected(self):
        ai = make_ai(json_mode='true')
        kwargs = ai._completion_kwargs(model='m')
        self.assertEqual(kwargs['response_format'], {'type': 'json_object'})

    def test_setdefault_does_not_override_caller(self):
        ai = make_ai(json_mode='true')
        explicit = {'type': 'text'}
        kwargs = ai._completion_kwargs(model='m', response_format=explicit)
        self.assertEqual(kwargs['response_format'], explicit)

    def test_no_response_format_when_disabled(self):
        ai = make_ai(json_mode='false')
        self.assertNotIn('response_format', ai._completion_kwargs(model='m'))

    def test_combined_with_extra_body(self):
        ai = make_ai(json_mode='true', extra_body='{"a": 1}')
        kwargs = ai._completion_kwargs(model='m')
        self.assertEqual(kwargs['response_format'], {'type': 'json_object'})
        self.assertEqual(kwargs['extra_body'], {'a': 1})


class TestQueryIntegration(unittest.TestCase):
    """通过 mock OpenAI 客户端验证配置确实透传到请求参数."""

    def setUp(self):
        self.q_info = {'type': 'single', 'title': '测试题', 'options': 'A 甲\nB 乙'}

    @patch('api.answer.OpenAI')
    def test_query_parses_json_answer(self, mock_openai):
        ai = make_ai()
        client = mock_openai.return_value
        client.chat.completions.create.return_value = make_completion('{"Answer": ["乙"]}')
        self.assertEqual(ai._query(self.q_info), '乙')

    @patch('api.answer.OpenAI')
    def test_query_passes_json_mode_and_extra_body(self, mock_openai):
        ai = make_ai(json_mode='true', extra_body='{"thinking": {"type": "disabled"}}')
        client = mock_openai.return_value
        client.chat.completions.create.return_value = make_completion('{"Answer": ["乙"]}')
        ai._query(self.q_info)
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs['response_format'], {'type': 'json_object'})
        self.assertEqual(create_kwargs['extra_body'], {'thinking': {'type': 'disabled'}})
        self.assertEqual(create_kwargs['model'], 'test-model')

    @patch('api.answer.OpenAI')
    def test_query_without_json_mode_has_no_response_format(self, mock_openai):
        ai = make_ai(extra_body='{}')
        client = mock_openai.return_value
        client.chat.completions.create.return_value = make_completion('{"Answer": ["乙"]}')
        ai._query(self.q_info)
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertNotIn('response_format', create_kwargs)
        self.assertNotIn('extra_body', create_kwargs)

    @patch('api.answer.OpenAI')
    def test_check_llm_connection_message_contains_json_word(self, mock_openai):
        ai = make_ai(json_mode='true')
        client = mock_openai.return_value
        client.chat.completions.create.return_value = make_completion('2')
        self.assertTrue(ai.check_llm_connection())
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs['response_format'], {'type': 'json_object'})
        content = create_kwargs['messages'][0]['content']
        self.assertIn('json', content.lower())


if __name__ == '__main__':
    unittest.main()
