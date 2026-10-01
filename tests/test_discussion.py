# -*- coding: utf-8 -*-
"""
任务中心「主题讨论」（planType=14）离线回归

覆盖：
  * 话题页解析（urlToken/标题/正文，window.obj.topic 是 JS 字面量）
  * study_discussion：读已有回复 → 写作器生成 → 提交 addReplys（参数与网页端一致）
  * 失败不假装成功：缺 urlToken / 写作器不可用 / 生成器报错 / 平台拒绝 / confirm 无终端
全部离线，不联网、不碰真实数据。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, quote, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-discuss-"))

from api import task_center as tc_mod  # noqa: E402
from api.task_center import TaskCenter  # noqa: E402

STUDY_URL = ("https://groupweb.chaoxing.com/pc/topic/jumpToTopicDetail"
             "?bbsid=bbs-1&uuid=topic-uuid-1&classId=1000002")

DISCUSS_PAGE = """
<html><head><title>话题详情</title></head><body>
<script>
window.obj = {
  user:{"puid":100000001},
  topic:{"fid":1336,"title":"讨论任务B","uuid":"topic-uuid-1",
         "content":"企业使命、愿景、目标是高层管理者制定的，你认为企业普通员工需要了解这些吗？谈谈你的想法。"},
  circle:{"bbsid":"bbs-1"},
  urlToken:'token-abc',
};
</script>
</body></html>
"""

NO_TOKEN_PAGE = DISCUSS_PAGE.replace("urlToken:'token-abc',", "")

REPLIES = {
    "status": True,
    "datas": [
        {"uuid": "r1", "content": "我觉得普通员工也需要了解，不然方向对不上。"},
        {"uuid": "r2", "content": "知道一点有用，但不用背下来。"},
    ],
}
POST_OK = {"status": True, "msg": "回复成功", "datas": {"urlToken": "new-token"}}


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.kwargs_calls = []

    def _dispatch(self, method, url, **kwargs):
        self.calls.append((method, url))
        self.kwargs_calls.append(kwargs)
        for key, resp in self.routes:
            if key in url:
                return resp
        return FakeResponse(status_code=404)

    def get(self, url, **kwargs):
        return self._dispatch("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._dispatch("post", url, **kwargs)


class FakeWriter:
    available = True

    def __init__(self):
        self.existing = None
        self.error = None

    def discussion(self, topic, requirement="", existing_posts=None, max_chars=160):
        self.existing = existing_posts
        if self.error:
            raise RuntimeError(self.error)
        return "使命和愿景写在官网上是一回事，员工知不知道是另一回事，我先说说自己的理解。"


class DiscussionDecodeTestCase(unittest.TestCase):
    def test_extracts_token_title_content(self):
        info = tc_mod._extract_discussion_topic(DISCUSS_PAGE)
        self.assertEqual(info["url_token"], "token-abc")
        self.assertEqual(info["title"], "讨论任务B")
        self.assertIn("普通员工需要了解", info["content"])

    def test_missing_token_is_empty(self):
        info = tc_mod._extract_discussion_topic(NO_TOKEN_PAGE)
        self.assertEqual(info["url_token"], "")


class StudyDiscussionTestCase(unittest.TestCase):
    def _tc(self, page=DISCUSS_PAGE, submit_mode="auto", writer=None, post=None):
        cx = mock.Mock()
        writer = writer if writer is not None else FakeWriter()
        tc = TaskCenter(cx, {"task_center_submit_mode": submit_mode}, writer=writer)
        tc.session = FakeSession([
            ("jumpToTopicDetail", FakeResponse(text=page)),
            ("getReplyList", FakeResponse(payload=REPLIES)),
            ("addReplys", FakeResponse(payload=post or POST_OK)),
        ])
        return tc, writer

    def test_replies_with_reference_and_correct_payload(self):
        tc, writer = self._tc()
        ok = tc.study_discussion(STUDY_URL, {"name": "讨论任务B"},
                                 {"courseId": "1000001", "clazzId": "1000002"})
        self.assertTrue(ok)
        self.assertEqual(writer.existing, [r["content"] for r in REPLIES["datas"]])
        posts = [kw for method, _url in tc.session.calls
                 for kw in tc.session.kwargs_calls if "data" in kw]
        payload = posts[-1]["data"]
        self.assertEqual(payload["replyId"], -1)
        self.assertEqual(payload["bbsid"], "bbs-1")
        self.assertEqual(payload["urlToken"], "token-abc")
        self.assertEqual(payload["courseId"], "1000001")
        self.assertEqual(payload["classId"], "1000002")
        # 网页端先 encodeURIComponent 一次，requests 再编码一次
        self.assertIn("使命和愿景", unquote(payload["topic_content"]))
        post_urls = [url for method, url in tc.session.calls if method == "post"]
        self.assertIn("/pc/invitation/topic-uuid-1/addReplys", post_urls[0])

    def test_already_replied_does_not_post_again(self):
        """自己已经回复过：不再重复发帖（重复运行不能刷讨论区）"""
        replies = {
            "status": True,
            "datas": [
                {"uuid": "mine", "createrPuid": 100000001, "content": "我之前的回复。"},
                {"uuid": "r1", "createrPuid": 999, "content": "同学的回复。"},
            ],
        }
        cx = mock.Mock()
        writer = FakeWriter()
        tc = TaskCenter(cx, {"task_center_submit_mode": "auto"}, writer=writer)
        tc.session = FakeSession([
            ("jumpToTopicDetail", FakeResponse(text=DISCUSS_PAGE)),
            ("getReplyList", FakeResponse(payload=replies)),
            ("addReplys", FakeResponse(payload=POST_OK)),
        ])
        self.assertTrue(tc.study_discussion(STUDY_URL, {"name": "讨论"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))

    def test_missing_token_does_not_submit(self):
        tc, _writer = self._tc(page=NO_TOKEN_PAGE)
        self.assertFalse(tc.study_discussion(STUDY_URL, {"name": "讨论"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))

    def test_writer_unavailable_does_not_submit(self):
        writer = mock.Mock()
        writer.available = False
        tc, _writer = self._tc(writer=writer)
        self.assertFalse(tc.study_discussion(STUDY_URL, {"name": "讨论"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))

    def test_writer_hard_failure_does_not_submit(self):
        writer = FakeWriter()
        writer.error = "生成内容里仍在编造个人经历"
        tc, _writer = self._tc(writer=writer)
        self.assertFalse(tc.study_discussion(STUDY_URL, {"name": "讨论"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))

    def test_platform_rejects_reply(self):
        tc, _writer = self._tc(post={"status": False, "msg": "该话题你最多回复N条"})
        self.assertFalse(tc.study_discussion(STUDY_URL, {"name": "讨论"}))

    def test_confirm_mode_without_tty_does_not_submit(self):
        tc, _writer = self._tc(submit_mode="confirm")
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertFalse(tc.study_discussion(STUDY_URL, {"name": "讨论"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.WAITING_CONFIRMATION)


if __name__ == "__main__":
    unittest.main()
