# -*- coding: utf-8 -*-
"""多模态题目解析与 OpenAI 兼容请求回归测试."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup  # noqa: E402

from api import answer  # noqa: E402
from api.base import Chaoxing, StudyResult, _strict_judgement_answer  # noqa: E402
from api.decode import _extract_choices  # noqa: E402


class _ImageResponse:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "image/png"}
        self.chunks = list(chunks if chunks is not None else [b"fake-png-content"])
        self.closed = False
        self.iterated = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def iter_content(self, chunk_size=None):
        self.iterated = True
        yield from self.chunks

    def raise_for_status(self):
        return None


class MultimodalContentTestCase(unittest.TestCase):
    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_image_html_becomes_data_url_parts(self, _get):
        content, has_images, images_available = answer._multimodal_content(
            '题目：函数图像<img src="http://example.test/q.png">\n选项：A'
        )

        self.assertTrue(has_images)
        self.assertTrue(images_available)
        self.assertIsInstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "题目：函数图像"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    @patch("api.answer._get_image_response")
    def test_mixed_content_type_header_finds_image_mime(self, get):
        response = _ImageResponse()
        response.headers = {"Content-Type": "application/octet-stream, image/jpeg;charset=UTF-8"}
        get.return_value = response

        result = answer._image_data_url("https://mooc1.chaoxing.com/ananas/latex/p/19507")

        self.assertTrue(result.startswith("data:image/jpeg;base64,"))

    def test_plain_html_becomes_text(self):
        content, has_images, images_available = answer._multimodal_content("题目：x<sup>2</sup>+1")

        self.assertFalse(has_images)
        self.assertTrue(images_available)
        self.assertEqual(content, "题目：x2+1")

    def test_choice_parser_preserves_image(self):
        soup = BeautifulSoup('<li>A <img src="http://example.test/a.png"></li>', "lxml")

        choice = _extract_choices(soup.li)

        self.assertIn("A", choice)
        self.assertIn('<img src="http://example.test/a.png">', choice)

    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_external_image_request_has_no_session_cookies(self, get):
        result = answer._image_data_url("https://example.test/q.png")

        self.assertTrue(result.startswith("data:image/png;base64,"))
        self.assertIsNone(get.call_args.kwargs["cookies"])
        self.assertNotIn("Referer", get.call_args.kwargs["headers"])

    @patch("api.cookies.use_cookies", return_value={"session": "secret"})
    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_chaoxing_request_uses_scoped_cookie_jar(self, get, _cookies):
        result = answer._image_data_url("https://p.ananas.chaoxing.com/q.png")

        self.assertTrue(result.startswith("data:image/png;base64,"))
        jar = get.call_args.kwargs["cookies"]
        self.assertEqual(jar.get("session"), "secret")
        self.assertEqual(list(jar)[0].domain, ".chaoxing.com")
        for url, expected in [
            ("https://chaoxing.com/q.png", "session=secret"),
            ("https://p.ananas.chaoxing.com/q.png", "session=secret"),
            ("https://example.test/q.png", None),
            ("https://chaoxing.com.example.test/q.png", None),
        ]:
            with self.subTest(url=url):
                prepared = requests.Request("GET", url, cookies=jar).prepare()
                self.assertEqual(prepared.headers.get("Cookie"), expected)

    @patch("api.cookies.use_cookies", return_value={"session": "secret"})
    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_http_image_is_upgraded_before_request(self, get, _cookies):
        result = answer._image_data_url("http://p.ananas.chaoxing.com/q.png")

        self.assertTrue(result.startswith("data:image/png;base64,"))
        self.assertEqual(get.call_args.args[0], "https://p.ananas.chaoxing.com/q.png")

    @patch("api.cookies.use_cookies", return_value={"session": "secret"})
    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_relative_formula_image_uses_https_work_origin(self, get, _cookies):
        """Resolve quiz formula paths before validating the scheme and cookies."""
        result = answer._image_data_url("/ananas/latex/p/test-formula")

        self.assertTrue(result.startswith("data:image/png;base64,"))
        self.assertEqual(get.call_args.args[0], "https://mooc1.chaoxing.com/ananas/latex/p/test-formula")
        self.assertEqual(list(get.call_args.kwargs["cookies"])[0].domain, ".chaoxing.com")

    @patch("api.cookies.use_cookies")
    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_protocol_relative_external_image_has_no_cookies(self, get, cookies):
        """Resolving protocol-relative URLs must retain the off-origin boundary."""
        result = answer._image_data_url("//external.test/q.png")

        self.assertTrue(result.startswith("data:image/png;base64,"))
        self.assertEqual(get.call_args.args[0], "https://external.test/q.png")
        self.assertIsNone(get.call_args.kwargs["cookies"])
        cookies.assert_not_called()

    @patch("api.answer._get_image_response")
    def test_http_redirect_is_rejected_without_followup_request(self, get):
        get.return_value = _ImageResponse(
            status_code=302, headers={"Location": "http://external.test/q.png"}
        )

        self.assertIsNone(answer._image_data_url("https://p.ananas.chaoxing.com/q.png"))
        get.assert_called_once()

    @patch("api.cookies.use_cookies", return_value={"session": "secret"})
    @patch("api.answer._get_image_response")
    def test_redirect_to_external_host_drops_cookies(self, get, _cookies):
        """A redirect from Chaoxing to another host must not carry cookies."""
        get.side_effect = [
            _ImageResponse(status_code=302, headers={"Location": "https://external.test/q.png"}),
            _ImageResponse(),
        ]

        self.assertTrue(answer._image_data_url("https://p.ananas.chaoxing.com/q.png").startswith("data:"))
        first, second = get.call_args_list
        self.assertIsInstance(first.kwargs["cookies"], requests.cookies.RequestsCookieJar)
        self.assertIsNone(second.kwargs["cookies"])
        self.assertNotIn("Referer", second.kwargs["headers"])
        self.assertFalse(first.kwargs["allow_redirects"])
        self.assertFalse(second.kwargs["allow_redirects"])

    @patch("api.cookies.use_cookies")
    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_spoofed_chaoxing_hosts_never_load_cookies(self, get, cookies):
        """A hostname containing the domain is not sufficient for authentication."""
        for host in ("chaoxing.com.external.test", "fakechaoxing.com"):
            with self.subTest(host=host):
                answer._image_data_url(f"https://{host}/q.png")
                self.assertIsNone(get.call_args.kwargs["cookies"])
        cookies.assert_not_called()

    @patch("api.answer._MAX_IMAGE_BYTES", 4)
    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    def test_oversized_image_is_unavailable(self, _get):
        """Oversized downloads and inline images must never pass through as URLs."""
        self.assertIsNone(answer._image_data_url("https://example.test/q.png"))
        self.assertIsNone(answer._image_data_url("data:image/png;base64,YWJjZGU="))

    @patch("api.cookies.use_cookies", return_value={"session": "secret"})
    @patch("api.answer._get_image_response", side_effect=requests.RequestException("403"))
    def test_unavailable_image_is_not_passed_to_model(self, _get, _cookies):
        content, has_images, images_available = answer._multimodal_content(
            '题目<img src="https://p.ananas.chaoxing.com/q.png">'
        )

        self.assertTrue(has_images)
        self.assertFalse(images_available)
        self.assertFalse(any(part["type"] == "image_url" for part in content))


class ImageDownloadSecurityTestCase(unittest.TestCase):
    def test_private_and_special_addresses_are_rejected(self):
        for host in (
            "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1",
            "169.254.169.254", "100.64.0.1", "224.0.0.1",
            "::1", "fc00::1", "fe80::1", "255.255.255.255",
        ):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    answer._public_image_address(host, 443)

    def test_dns_results_are_all_checked_before_selecting_an_address(self):
        records = [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("192.168.1.20", 443)),
        ]
        with patch("api.answer.socket.getaddrinfo", return_value=records):
            with self.assertRaises(ValueError):
                answer._public_image_address("image.example", 443)

    def test_adapter_pins_numeric_address_and_keeps_tls_hostname(self):
        request = requests.Request("GET", "https://image.example/path").prepare()
        adapter = answer._PublicImageAdapter()
        with patch("api.answer._public_image_address", return_value="93.184.216.34") as resolve:
            pool = adapter.get_connection_with_tls_context(request, True, proxies={})

        resolve.assert_called_once_with("image.example", 443)
        self.assertEqual(pool.host, "93.184.216.34")
        self.assertEqual(pool.assert_hostname, "image.example")
        self.assertEqual(pool.conn_kw["server_hostname"], "image.example")
        self.assertEqual(request.headers["Host"], "image.example")

    @patch("api.answer._MAX_IMAGE_BYTES", 4)
    def test_streaming_download_stops_before_buffering_past_limit(self):
        response = _ImageResponse(chunks=[b"abc", b"de", b"never-read"])
        with patch("api.answer._get_image_response", return_value=response):
            self.assertIsNone(answer._image_data_url("https://image.example/q.png"))
        self.assertTrue(response.closed)
        self.assertTrue(response.iterated)

    @patch("api.answer._MAX_IMAGE_BYTES", 4)
    def test_content_length_limit_avoids_reading_body(self):
        response = _ImageResponse(
            headers={"Content-Type": "image/png", "Content-Length": "5"},
            chunks=[b"never-read"],
        )
        with patch("api.answer._get_image_response", return_value=response):
            self.assertIsNone(answer._image_data_url("https://image.example/q.png"))
        self.assertTrue(response.closed)
        self.assertFalse(response.iterated)


class AIRequestTestCase(unittest.TestCase):
    def test_providers_skip_requests_when_one_image_is_unavailable(self):
        """Neither provider may guess from an incomplete set of images."""
        question = {
            "type": "single",
            "title": '<img src="https://example.test/q.png">',
            "options": 'A 0\nB <img src="https://example.test/b.png">',
        }
        ai = answer.AI()
        ai.endpoint = "https://example.test/v1"
        ai.key = "test-key"
        ai.http_proxy = ""
        siliconflow = answer.SiliconFlow()
        siliconflow.api_key = "test-key"
        with patch("api.answer.OpenAI") as client, patch("api.answer.requests.post") as post:
            for provider in (ai, siliconflow):
                with self.subTest(provider=provider.name):
                    with patch("api.answer._image_data_url", side_effect=["data:image/png;base64,YQ==", None]):
                        self.assertIsNone(provider._query_locked(question))
            client.return_value.chat.completions.create.assert_not_called()
            post.assert_not_called()

    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    @patch("api.answer.OpenAI")
    def test_ai_sends_multimodal_user_content(self, openai_cls, _get):
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"Answer":["正确"]}'))]
                )

        openai_cls.return_value.chat.completions = FakeCompletions()
        ai = answer.AI()
        ai.endpoint = "https://example.test/v1"
        ai.key = "test-key"
        ai.model = "vision-model"
        ai.http_proxy = ""
        ai.min_interval_seconds = 0

        result = ai._query_locked({
            "type": "judgement",
            "title": '<img src="http://example.test/q.png">',
            "options": "正确\n错误",
        })

        self.assertEqual(result, "正确")
        user_message = captured["messages"][-1]
        self.assertIsInstance(user_message["content"], list)
        self.assertTrue(any(part["type"] == "image_url" for part in user_message["content"]))

    @patch("api.answer._get_image_response", return_value=_ImageResponse())
    @patch("api.answer.OpenAI")
    def test_image_choice_requests_and_returns_option_letter(self, openai_cls, _get):
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"Answer":["B"]}'))]
                )

        openai_cls.return_value.chat.completions = FakeCompletions()
        ai = answer.AI()
        ai.endpoint = "https://example.test/v1"
        ai.key = "test-key"
        ai.model = "vision-model"
        ai.http_proxy = ""
        ai.min_interval_seconds = 0

        result = ai._query_locked({
            "type": "single",
            "title": "请选择正确图形",
            "options": 'A <img src="http://example.test/a.png">\nB <img src="http://example.test/b.png">',
        })

        self.assertEqual(result, "B")
        system_message = captured["messages"][0]["content"]
        self.assertIn("只输出 JSON", system_message)
        user_message = captured["messages"][-1]
        self.assertTrue(any(part["type"] == "image_url" for part in user_message["content"]))

    def test_image_choice_rejects_formula_text(self):
        question = {
            "type": "single",
            "title": '<img src="question.png">',
            "options": 'A <img src="a.png">\nB <img src="b.png">',
        }
        self.assertEqual(answer._choice_letters("f(x)=1/x", question), "")
        self.assertEqual(answer._choice_letters("A", question), "A")

    def test_title_image_also_uses_letter_mode(self):
        question = {
            "type": "single",
            "title": '<img src="question.png">',
            "options": "A 1.\nB -1.\nC 0.\nD 不存在.",
        }
        self.assertTrue(answer._image_choice(question))
        self.assertEqual(answer._choice_letters("B", question), "B")


class ImageSubmissionTestCase(unittest.TestCase):
    def test_strict_judgement_keeps_recognized_values(self):
        tiku = SimpleNamespace(true_list=[], false_list=[])
        self.assertEqual(_strict_judgement_answer(tiku, "正确"), "true")
        self.assertEqual(_strict_judgement_answer(tiku, "false"), "false")
        self.assertEqual(_strict_judgement_answer(tiku, "无法判断"), "")

    def test_unrecognized_image_judgement_is_saved_blank(self):
        client = Chaoxing.__new__(Chaoxing)
        client.kwargs = {}
        client.rollback_times = 1
        client.tiku = Mock(DISABLE=False, COVER_RATE=0, is_manual=False)
        client.tiku.query_all.return_value = ["无法判断"]
        client.tiku.get_submit_params.return_value = ""  # Submit enabled.
        questions = {
            "questions": [{
                "id": "judgement-id",
                "title": '<img src="https://example.test/q.png">',
                "type": "judgement",
                "options": "正确\n错误",
                "answerField": {
                    "answerjudgement-id": "0",
                    "answertypejudgement-id": "0",
                },
            }],
        }
        session = Mock()
        session.get.return_value = SimpleNamespace(status_code=200, text="test HTML")
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"status": True, "msg": "saved"}
        with patch("api.base.SessionManager.get_session", return_value=session), \
                patch("api.base.decode_questions_info", return_value=questions), \
                patch("api.base.random_answer") as random_answer:
            result = client.study_work(
                {"courseId": "test-course", "clazzId": "test-class"},
                {"jobid": "work-test", "enc": "test-enc"},
                {"knowledgeid": "test-chapter", "ktoken": "test-token", "cpi": "test-cpi"},
            )

        self.assertEqual(result, StudyResult.SUCCESS)
        random_answer.assert_not_called()
        data = session.post.call_args.kwargs["data"]
        self.assertEqual(data["pyFlag"], "1")
        self.assertEqual(data["answerjudgement-id"], "")

    def test_missing_image_answers_save_blank_without_random_fallback(self):
        """Choice and judgement images without answers must force save-only mode."""
        for question_type in ("single", "multiple", "judgement"):
            with self.subTest(question_type=question_type):
                client = Chaoxing.__new__(Chaoxing)
                client.kwargs = {}
                client.rollback_times = 1
                client.tiku = Mock(DISABLE=False, COVER_RATE=0, is_manual=False)
                client.tiku.query_all.return_value = [None]
                client.tiku.get_submit_params.return_value = ""  # Submit enabled.
                questions = {
                    "questions": [{
                        "id": "test-id",
                        "title": '<img src="https://example.test/q.png">',
                        "type": question_type,
                        "options": "A 1\nB 0",
                        "answerField": {"answertypetest-id": "0"},
                    }],
                }
                session = Mock()
                session.get.return_value = SimpleNamespace(status_code=200, text="test HTML")
                session.post.return_value.status_code = 200
                session.post.return_value.json.return_value = {"status": True, "msg": "saved"}
                with patch("api.base.SessionManager.get_session", return_value=session), \
                        patch("api.base.decode_questions_info", return_value=questions), \
                        patch("api.base.random_answer") as random_answer:
                    result = client.study_work(
                        {"courseId": "test-course", "clazzId": "test-class"},
                        {"jobid": "work-test", "enc": "test-enc"},
                        {"knowledgeid": "test-chapter", "ktoken": "test-token", "cpi": "test-cpi"},
                    )
                self.assertEqual(result, StudyResult.SUCCESS)
                random_answer.assert_not_called()
                data = session.post.call_args.kwargs["data"]
                self.assertEqual(data["pyFlag"], "1")
                self.assertEqual(data["answertest-id"], "")


if __name__ == "__main__":
    unittest.main()
