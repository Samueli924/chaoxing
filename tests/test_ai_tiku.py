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

    def test_invalid_values_fall_back(self):
        for bad in ("0", "-5", "nan", "inf", "abc"):
            ai = make_ai(ai_timeout=bad, ai_search_timeout=bad, ai_redo_timeout=bad)
            self.assertEqual((ai.request_timeout, ai.search_timeout, ai.redo_timeout), (120, 10, 300), bad)
        self.assertEqual(make_ai(ai_max_tokens="-1").max_tokens, 4096)
        self.assertEqual(make_ai(ai_max_tokens="0").max_tokens, 0)  # 0 表示不限制

    def test_token_parameter(self):
        ai = make_ai()
        self.assertEqual(ai._completion_kwargs(model="m", max_tokens=100), {"model": "m", "max_tokens": 100})
        self.assertEqual(ai._completion_kwargs(model="m", max_tokens=0), {"model": "m"})
        ai.endpoint = "https://api.openai.com/v1"
        self.assertEqual(ai._completion_kwargs(model="m", max_tokens=100), {"model": "m", "max_completion_tokens": 100})

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
        # 审查意见：非列表的 Answer 不能报错
        self.assertEqual(p('{"Answer": true}'), "True")
        self.assertEqual(p('{"Answer": 5}'), "5")
        self.assertIsNone(p('{"Answer": null}'))
        self.assertEqual(p('{"Answer": ["A", null, ""]}'), "A")


class ImageUrlTest(unittest.TestCase):
    def test_resolve_relative_and_absolute(self):
        r = AI._resolve_image_url
        self.assertEqual(r("/ananas/latex/p/635513"), "https://mooc1.chaoxing.com/ananas/latex/p/635513")
        self.assertEqual(r("//p.ananas.chaoxing.com/a.png"), "https://p.ananas.chaoxing.com/a.png")
        self.assertEqual(r("https://p.ananas.chaoxing.com/a.png"), "https://p.ananas.chaoxing.com/a.png")
        self.assertEqual(r("http://p.ananas.chaoxing.com/a.png"), "http://p.ananas.chaoxing.com/a.png")
        self.assertEqual(r(" /ananas/latex/p/1?a=1&amp;b=2 "), "https://mooc1.chaoxing.com/ananas/latex/p/1?a=1&b=2")

    def test_image_type_detection(self):
        t = AI._image_type
        self.assertEqual(t(b"\xff\xd8\xff\xe0rest", "application/octet-stream, image/jpeg"), "image/jpeg")
        self.assertEqual(t(b"\x89PNG\r\n\x1a\nrest", "application/octet-stream"), "image/png")
        self.assertEqual(t(b"RIFF1234WEBPVP8 ", ""), "image/webp")
        self.assertEqual(t(b"unknown", "application/octet-stream, image/jpeg"), "image/jpeg")
        self.assertIsNone(t(b"<html>403</html>", "text/html"))
        self.assertIsNone(t(b"", "image/png"))

    def fetch(self, ai, url, responses):
        """模拟图片下载：responses 依次返回；记录每次请求的地址和是否带了登录 cookie."""
        import requests as _requests
        logged_in = _requests.Session()
        logged_in.cookies.set("_uid", "secret-uid")
        calls = []
        responses = list(responses)

        def fake_get(self_session, url, **kw):
            calls.append((url, self_session.cookies.get("_uid"), kw.get("allow_redirects"), kw.get("timeout")))
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("api.base.SessionManager.get_session", return_value=logged_in), \
                mock.patch.object(answer_mod.requests.Session, "get", fake_get):
            data = ai._fetch_image(url)
        return data, calls

    @staticmethod
    def resp(status=200, content=b"\xff\xd8\xffjpeg", ctype="application/octet-stream, image/jpeg", location=None):
        headers = {"Content-Type": ctype}
        if location:
            headers["Location"] = location
        return SimpleNamespace(status_code=status, headers=headers, content=content)

    def test_fetch_uses_resolved_url(self):
        data, calls = self.fetch(make_ai(), "/ananas/latex/p/635513", [self.resp()])
        self.assertEqual(calls[0][0], "https://mooc1.chaoxing.com/ananas/latex/p/635513")
        self.assertEqual(calls[0][1], "secret-uid")  # 学习通域名带登录 cookie
        self.assertFalse(calls[0][2])  # 不自动跟随跳转
        self.assertEqual(calls[0][3], (5, 15))
        self.assertTrue(data.startswith("data:image/jpeg;base64,"))

    def test_no_cookies_for_other_hosts_or_redirects(self):
        _, calls = self.fetch(make_ai(), "https://evil.example/a.png", [self.resp()])
        self.assertIsNone(calls[0][1])
        _, calls = self.fetch(make_ai(), "https://p.ananas.chaoxing.com/a.png",
                              [self.resp(302, b"", "text/html", "https://evil.example/b.png"), self.resp()])
        self.assertEqual([c[1] for c in calls], ["secret-uid", None])  # 跳到外站后不再带 cookie
        self.assertEqual(calls[1][0], "https://evil.example/b.png")

    def test_transient_failures_not_cached(self):
        ai = make_ai()
        data, _ = self.fetch(ai, "https://p.ananas.chaoxing.com/a.png", [OSError("timeout")])
        self.assertIsNone(data)
        data, calls = self.fetch(ai, "https://p.ananas.chaoxing.com/a.png", [self.resp(503, b"", "text/html")])
        self.assertEqual(len(calls), 1)  # 超时没有缓存，再次尝试
        data, calls = self.fetch(ai, "https://p.ananas.chaoxing.com/a.png", [self.resp()])
        self.assertTrue(data)  # 5xx 也没有缓存，第三次成功
        _, calls = self.fetch(ai, "https://p.ananas.chaoxing.com/a.png", [])
        self.assertEqual(calls, [])  # 成功结果命中缓存
        self.fetch(ai, "https://p.ananas.chaoxing.com/404.png", [self.resp(404, b"", "text/html")])
        _, calls = self.fetch(ai, "https://p.ananas.chaoxing.com/404.png", [])
        self.assertEqual(calls, [])  # 4xx 缓存，不再重试


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

    def test_vision_kept_when_text_retry_also_fails(self):
        ai = make_ai()
        with mock.patch.object(AI, "_fetch_image", return_value="data:image/png;base64,xx"):
            ans, client = self.run_query(ai, [bad_request(), bad_request()])
        self.assertIsNone(ans)
        self.assertTrue(ai._vision_ok)  # 不是图片导致的 400，不关闭识图

    def test_timeout_skips_question(self):
        ai = make_ai(ai_vision="false")
        ans, _ = self.run_query(ai, [APITimeoutError(request=httpx.Request("POST", "http://x"))])
        self.assertIsNone(ans)

    def test_length_limit_returns_none(self):
        ai = make_ai(ai_vision="false")
        ans, _ = self.run_query(ai, [completion("", finish="length")])  # 没有思考内容可用
        self.assertIsNone(ans)

    def test_length_limit_forces_answer_from_reasoning(self):
        ai = make_ai(ai_vision="false", ai_disable_thinking="true")
        truncated = completion("", finish="length")
        truncated.choices[0].message.reasoning_content = "先求导，v=4-4t，代入 t=1 得 0，" * 500
        ans, client = self.run_query(ai, [truncated, completion('{"Answer": ["0"]}')])
        self.assertEqual(ans, "0")
        second = client.calls[1]
        self.assertEqual(second["max_tokens"], 512)
        last = second["messages"][-1]
        self.assertEqual(last["role"], "assistant")
        self.assertIn("思考时间已用完", last["content"])
        self.assertLessEqual(len(last["content"]), 6100)  # 思考内容被截短
        self.assertEqual(sum(m["role"] == "assistant" for m in second["messages"]), 1)  # 去掉了空思考预填

    def test_reasoning_inline_think_tag(self):
        msg = SimpleNamespace(content="<think>推理过程到一半", model_extra={})
        self.assertEqual(AI._reasoning_of(msg), "推理过程到一半")
        msg2 = SimpleNamespace(content="", model_extra={"reasoning_content": "附加字段里的推理"})
        self.assertEqual(AI._reasoning_of(msg2), "附加字段里的推理")

    def test_force_answer_failure_returns_none(self):
        ai = make_ai(ai_vision="false")
        truncated = completion("", finish="length")
        truncated.choices[0].message.reasoning_content = "想了很久"
        ans, _ = self.run_query(ai, [truncated, completion("还是不知道")])
        self.assertIsNone(ans)

    def test_disable_thinking_appends_no_think(self):
        ai = make_ai(ai_vision="false", ai_disable_thinking="true")
        q = {"type": "judgement", "title": "泊松分布的期望等于方差", "options": ""}
        _, client = self.run_query(ai, [completion('{"Answer": ["正确"]}')], q=q)
        messages = client.calls[0]["messages"]
        self.assertEqual(messages[-1], {"role": "assistant", "content": "<think>\n\n</think>\n\n"})
        self.assertTrue(messages[-2]["content"].endswith("/no_think"))

    def test_thinking_enabled_by_default(self):
        ai = make_ai(ai_vision="false")
        q = {"type": "judgement", "title": "泊松分布的期望等于方差", "options": ""}
        _, client = self.run_query(ai, [completion('{"Answer": ["正确"]}')], q=q)
        self.assertEqual(client.calls[0]["messages"][-1]["role"], "user")

    def test_vision_fallback_with_thinking_disabled(self):
        ai = make_ai(ai_disable_thinking="true")
        with mock.patch.object(AI, "_fetch_image", return_value="data:image/png;base64,xx"):
            ans, client = self.run_query(ai, [bad_request(), completion('{"Answer": ["6m/s"]}')])
        self.assertEqual(ans, "6m/s")
        retry = client.calls[1]["messages"]
        self.assertEqual(retry[-1]["role"], "assistant")
        self.assertIsInstance(retry[-2]["content"], str)

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


class AnswerCheckTest(unittest.TestCase):
    def test_numeric_option_answers_kept(self):
        from api.answer_check import check_answer
        tiku = SimpleNamespace(true_list=["正确", "对"], false_list=["错误", "错"])
        self.assertTrue(check_answer("0", "single", tiku))
        self.assertTrue(check_answer("1", "single", tiku))
        self.assertTrue(check_answer("30 m/s", "single", tiku))
        self.assertFalse(check_answer("正确", "single", tiku))  # 选择题答成判断仍然舍弃
        self.assertFalse(check_answer("错误", "multiple", tiku))
        self.assertTrue(check_answer("0", "judgement", tiku))


class ImageOptionTest(unittest.TestCase):
    """公式图片选项：解析时保留图片、要求模型用字母作答、按字母精确匹配."""

    def test_decode_keeps_option_images(self):
        from bs4 import BeautifulSoup
        from api.decode import _extract_choices
        li = BeautifulSoup('<li aria-label="B选择"><span>B</span><div><img src="/ananas/latex/p/1"></div></li>', "lxml").li
        self.assertEqual(_extract_choices(li), 'B<img src="/ananas/latex/p/1">')
        li2 = BeautifulSoup('<li aria-label="A 2dx选择"><span>A</span>2dx</li>', "lxml").li
        self.assertEqual(_extract_choices(li2), "A 2dx")

    def test_exact_option_letter(self):
        from api.base import exact_option_letter
        opts = ['A<img src="https://p.example/abc.png">', 'B<img src="https://p.example/bbb.png">']
        self.assertEqual(exact_option_letter("B", opts), "B")
        self.assertEqual(exact_option_letter("B.", opts), "B")
        self.assertEqual(exact_option_letter(opts[0], opts), "A")
        self.assertEqual(exact_option_letter("b", ["A b", "B a"]), "A")  # 按内容匹配，而不是当作字母
        self.assertEqual(exact_option_letter("2dx", ["A 2dx", "B 6dx"]), "A")
        # 审查意见：内容优先于字母；数字和包含关系不能靠模糊匹配
        self.assertEqual(exact_option_letter("B", ["A B", "B C"]), "A")
        self.assertEqual(exact_option_letter("0", ["A10", "B0"]), "B")
        self.assertEqual(exact_option_letter("乙丙", ["A甲乙丙", "B乙丙"]), "B")
        self.assertEqual(exact_option_letter("C.", ["A甲", "B乙", "C丙"]), "C")
        self.assertEqual(exact_option_letter("x", ["A甲", "B乙"]), "")

    def test_numeric_answers_not_fuzzy_matched(self):
        from api.base import _is_numeric_answer
        self.assertTrue(_is_numeric_answer("0"))
        self.assertTrue(_is_numeric_answer("-1.5"))
        self.assertFalse(_is_numeric_answer("0 m/s"))
        self.assertFalse(_is_numeric_answer(""))

    def test_prompt_asks_for_letters_when_options_are_images(self):
        ai = make_ai()
        q = {"type": "single", "title": "函数的导数为",
             "options": 'A<img src="https://p.example/a.png">\nB<img src="https://p.example/b.png">'}
        with mock.patch.object(AI, "_fetch_image", return_value="data:image/png;base64,xx"):
            content = ai._build_user_content(q)
        text = content[0]["text"]
        self.assertIn("A. [图1]", text)
        self.assertIn("B. [图2]", text)
        self.assertIn("请用选项字母作答", text)
        self.assertEqual(len(content), 3)


class ImagePrepareTest(unittest.TestCase):
    """公式图片：透明背景铺白底、小图放大（审查实际刷课日志发现模型读错透明背景的公式）."""

    def decode(self, data_url):
        import base64, io
        from PIL import Image
        return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))

    def test_transparent_small_formula(self):
        import io
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (74, 19), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((2, 2), "x=4t-2t2", fill=(0, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out = self.decode(AI._to_data_url(buf.getvalue(), "image/jpeg"))
        self.assertEqual(out.mode, "RGB")
        self.assertEqual(out.getpixel((0, 0)), (255, 255, 255))  # 透明处变成白色
        self.assertGreaterEqual(out.height, 64)  # 放大
        self.assertEqual(out.format, "PNG")

    def test_normal_image_untouched(self):
        import io
        from PIL import Image
        img = Image.new("RGB", (400, 300), "white")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw = buf.getvalue()
        url = AI._to_data_url(raw, "image/jpeg")
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        import base64
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), raw)  # 正常图片原样发送

    def test_large_image_downscaled(self):
        import io
        from PIL import Image
        img = Image.new("RGB", (3000, 1000), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out = self.decode(AI._to_data_url(buf.getvalue(), "image/png"))
        self.assertLessEqual(max(out.size), 1280)


class WebSearchTest(unittest.TestCase):
    def make_session(self, payload=None, exc=None):
        session = mock.Mock()
        if exc:
            session.get.side_effect = exc
        else:
            resp = mock.Mock()
            resp.json.return_value = payload
            resp.raise_for_status.return_value = None
            session.get.return_value = resp
        return session

    def test_search_results_added_to_prompt(self):
        ai = make_ai(ai_vision="false", ai_search_url="http://127.0.0.1:8888", ai_search_results="2")
        payload = {"results": [
            {"title": "黄河大合唱", "content": "1939年冼星海作曲"},
            {"title": "空结果", "content": ""},
            {"title": "冼星海", "content": "中国作曲家"},
            {"title": "多余", "content": "不应出现"},
        ]}
        session = self.make_session(payload)
        q = {"type": "single", "title": "【单选题】《黄河大合唱》的作曲者是", "options": "A冼星海\nB聂耳"}
        with mock.patch.object(answer_mod.requests, "Session", return_value=session):
            text = ai._build_user_content(q)
            ai._build_user_content(q)  # 同一题第二次走缓存
        self.assertEqual(session.get.call_count, 1)
        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["format"], "json")
        self.assertNotIn("【", params["q"])
        self.assertFalse(session.trust_env)
        self.assertIn("1. 黄河大合唱：1939年冼星海作曲", text)
        self.assertIn("2. 冼星海：中国作曲家", text)
        self.assertNotIn("不应出现", text)

    def test_search_failure_does_not_block(self):
        ai = make_ai(ai_vision="false", ai_search_url="http://127.0.0.1:8888")
        session = self.make_session(exc=OSError("connection refused"))
        q = {"type": "judgement", "title": "牛顿第一定律又称惯性定律", "options": ""}
        with mock.patch.object(answer_mod.requests, "Session", return_value=session):
            text = ai._build_user_content(q)
        self.assertNotIn("参考资料", text)

    def test_search_retries_once_on_timeout_and_does_not_cache_failures(self):
        import requests as _requests
        ai = make_ai(ai_vision="false", ai_search_url="http://127.0.0.1:8888")
        ok = mock.Mock()
        ok.json.return_value = {"results": [{"title": "惯性定律", "content": "牛顿第一定律又称惯性定律"}]}
        ok.raise_for_status.return_value = None
        session = mock.Mock()
        session.get.side_effect = [_requests.ReadTimeout("slow"), ok]
        q = {"type": "judgement", "title": "牛顿第一定律又称惯性定律", "options": ""}
        with mock.patch.object(answer_mod.requests, "Session", return_value=session):
            text = ai._build_user_content(q)
        self.assertEqual(session.get.call_count, 2)  # 超时后重试成功
        self.assertIn("惯性定律：牛顿第一定律又称惯性定律", text)

        ai2 = make_ai(ai_vision="false", ai_search_url="http://127.0.0.1:8888")
        failing = mock.Mock()
        failing.get.side_effect = _requests.ReadTimeout("slow")
        with mock.patch.object(answer_mod.requests, "Session", return_value=failing):
            ai2._build_user_content(q)
            ai2._build_user_content(q)
        self.assertEqual(failing.get.call_count, 4)  # 两次都失败（各重试一次），失败结果没有缓存

    def test_search_off_by_default(self):
        ai = make_ai(ai_vision="false")
        with mock.patch.object(answer_mod.requests, "Session") as sess:
            ai._build_user_content({"type": "judgement", "title": "牛顿第一定律又称惯性定律", "options": ""})
        sess.assert_not_called()


class QuizOrderTest(unittest.TestCase):
    """多个章节检测同时作答时，一个检测答完再答下一个，并上报进度."""

    def test_quizzes_answered_one_after_another(self):
        import threading
        import time as _time
        ai = make_ai(ai_vision="false")
        order, events = [], []
        ai.progress_callback = lambda done, total, waiting=False: events.append((threading.current_thread().name, done, total, waiting))

        def fake_query(q):
            order.append(q["title"][:1])
            _time.sleep(0.02)
            return "正确"

        quiz_a = [{"type": "judgement", "title": f"A{i}题目", "options": ""} for i in range(3)]
        quiz_b = [{"type": "judgement", "title": f"B{i}题目", "options": ""} for i in range(3)]
        with mock.patch.object(AI, "_query", side_effect=fake_query), \
                mock.patch.object(answer_mod.CacheDAO, "get_cache", return_value=None), \
                mock.patch.object(answer_mod.CacheDAO, "add_cache"), \
                mock.patch.object(answer_mod, "check_answer", return_value=True):
            ta = threading.Thread(target=ai.query_all, args=(quiz_a,), name="A")
            tb = threading.Thread(target=ai.query_all, args=(quiz_b,), name="B")
            ta.start()
            _time.sleep(0.01)
            tb.start()
            ta.join()
            tb.join()
        self.assertEqual("".join(order), "AAABBB")
        self.assertIn(("B", 0, 3, True), events)  # B 排队等待时上报 waiting
        self.assertEqual([e[1] for e in events if e[0] == "A"], [0, 1, 2, 3])
        self.assertEqual(events[-1], ("B", 3, 3, False))


if __name__ == "__main__":
    unittest.main()
