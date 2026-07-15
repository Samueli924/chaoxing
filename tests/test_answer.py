import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api.answer import AI, SiliconFlow, TikuLike


class TikuLikeConfigTests(unittest.TestCase):
    def test_string_boolean_options_are_parsed(self):
        provider = TikuLike()
        provider.config_set(
            {
                "likeapi_search": "false",
                "likeapi_vision": "true",
                "likeapi_retry": "false",
                "likeapi_retry_times": "4",
            }
        )

        provider.load_config()

        self.assertIs(provider._search, False)
        self.assertIs(provider._vision, True)
        self.assertIs(provider._retry, False)
        self.assertEqual(provider._retry_times, 4)


class LlmConnectionTests(unittest.TestCase):
    @patch("api.answer.OpenAI")
    def test_openai_compatible_reasoning_content_counts_as_response(self, openai_cls):
        message = SimpleNamespace(content="", reasoning_content="thinking")
        completion = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        create = openai_cls.return_value.chat.completions.create
        create.return_value = completion

        provider = AI()
        provider.endpoint = "https://example.invalid/v1"
        provider.key = "key"
        provider.model = "reasoner"
        provider.http_proxy = ""
        provider.min_interval_seconds = 0

        self.assertTrue(provider.check_llm_connection())
        self.assertEqual(create.call_args.kwargs["max_tokens"], 200)

    @patch("api.answer.requests.post")
    def test_siliconflow_reasoning_content_counts_as_response(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "", "reasoning_content": "thinking"}}]
        }
        post.return_value = response

        provider = SiliconFlow()
        provider.api_endpoint = "https://example.invalid/v1/chat/completions"
        provider.api_key = "key"
        provider.model_name = "reasoner"

        self.assertTrue(provider.check_llm_connection())
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 200)

    @patch("api.answer.OpenAI")
    def test_empty_choices_fall_back_to_no_answer(self, openai_cls):
        openai_cls.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[]
        )
        provider = AI()
        provider.endpoint = "https://example.invalid/v1"
        provider.key = "key"
        provider.model = "model"
        provider.http_proxy = ""
        provider.min_interval_seconds = 0

        result = provider._query(
            {"type": "single", "title": "Question", "options": "A Option"}
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
