# -*- coding: utf-8 -*-
"""
讨论区浏览（模式 2）回归：列表解析、渲染、板块解析、只列不回复。

模式 1（任务里的主题讨论）在 tests/test_discussion.py 里；两者共用
TaskCenter.reply_topic，所以这里的重点是"能不能把讨论区的帖子列出来并选中"。
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-board-"))

from api import discussion  # noqa: E402


class FakeResp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = "{}"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResp(self.payload)


def _topic_item(**over):
    item = {
        "uuid": "uuid-1",
        "id": 711682418,
        "title": "",
        "content": "企业外部环境存在机会，是否就代表企业一定可以抓住机会？",
        "createrName": "张三",
        "reply_count": 1,
        "ftime": "2小时前",
        "lastReply": {"name": "张三", "formattime": "2小时前"},
    }
    item.update(over)
    return item


class NormalizeTopicTestCase(unittest.TestCase):
    def test_title_falls_back_to_content(self):
        topic = discussion.normalize_topic(_topic_item())
        self.assertIn("企业外部环境", topic["title"])
        self.assertEqual(topic["author"], "张三")
        self.assertEqual(topic["reply_count"], 1)

    def test_real_title_wins(self):
        topic = discussion.normalize_topic(_topic_item(title="这是标题"))
        self.assertEqual(topic["title"], "这是标题")


class FetchTopicsTestCase(unittest.TestCase):
    def test_parses_topic_list(self):
        payload = {"status": True, "datas": [_topic_item(), _topic_item(uuid="uuid-2")]}
        session = FakeSession(payload)
        topics = discussion.fetch_topics(session, "bbs-1", page=1)
        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]["uuid"], "uuid-1")
        url, kwargs = session.calls[0]
        self.assertIn("/pc/topic/topiclist/bbs-1/getTopicList", url)
        self.assertEqual(kwargs["params"]["page"], 1)

    def test_platform_rejection_returns_empty(self):
        topics = discussion.fetch_topics(FakeSession({"status": False, "msg": "无权访问"}), "bbs-1")
        self.assertEqual(topics, [])

    def test_non_json_returns_empty(self):
        topics = discussion.fetch_topics(FakeSession(ValueError("not json")), "bbs-1")
        self.assertEqual(topics, [])

    def test_items_without_uuid_are_skipped(self):
        payload = {"status": True, "datas": [{"content": "没有 uuid"}, _topic_item()]}
        topics = discussion.fetch_topics(FakeSession(payload), "bbs-1")
        self.assertEqual([t["uuid"] for t in topics], ["uuid-1"])


class RenderTopicsTestCase(unittest.TestCase):
    def test_list_view_has_numbers_and_body(self):
        topics = [discussion.normalize_topic(_topic_item()),
                  discussion.normalize_topic(_topic_item(uuid="u2", createrName="李四"))]
        out = discussion.render_topics(topics, page=1)
        self.assertIn("第 1 页", out)
        self.assertIn("1.", out)
        self.assertIn("张三", out)
        self.assertIn("企业外部环境", out)

    def test_empty_page_is_friendly(self):
        self.assertIn("没有帖子", discussion.render_topics([], page=3))


class FakeTaskCenter:
    def __init__(self, session, bbsid="2a4b2fff0f67dd5b88099bcd5c2a941e"):
        self.session = session
        self._bbsid = bbsid

    def get_course_tasks(self, course):
        return [{"name": "第1章"}]

    def open_task(self, task):
        return {"encryTaskUserId": "u1"}

    def get_groups(self, encry):
        return [{"encryptGroupId": "g1"}]

    def get_plans(self, encry, group):
        return [{"planType": 14, "encryptPlanId": "p1"}]

    def get_study_url(self, encry, plan_id):
        return ("https://groupweb.chaoxing.com/pc/topic/jumpToTopicDetail?"
                "bbsid=" + self._bbsid + "&uuid=topic-uuid")


class ResolveBbsidTestCase(unittest.TestCase):
    def test_bbsid_from_task_center(self):
        tc = FakeTaskCenter(FakeSession({"status": True, "datas": []}))
        self.assertEqual(discussion.resolve_bbsid(tc, {"title": "课"}),
                         "2a4b2fff0f67dd5b88099bcd5c2a941e")

    def test_direct_bbsid_wins(self):
        tc = FakeTaskCenter(FakeSession({"status": True, "datas": []}))
        self.assertEqual(discussion.resolve_bbsid(tc, {"bbsid": "direct"}), "direct")

    def test_missing_board_returns_empty(self):
        class EmptyTC:
            def get_course_tasks(self, course):
                return []
        self.assertEqual(discussion.resolve_bbsid(EmptyTC(), {"title": "课"}), "")


class DiscussCliListOnlyTestCase(unittest.TestCase):
    def test_list_only_prints_topics_and_returns_zero(self):
        payload = {"status": True, "datas": [_topic_item()]}
        session = FakeSession(payload)
        tc = FakeTaskCenter(session)
        chaoxing = mock.Mock()
        chaoxing.get_course_list.return_value = [{"courseId": "1", "title": "示例课程"}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = discussion.discuss_cli(chaoxing, tc, {}, list_only=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sent"], 0)
        out = buf.getvalue()
        self.assertIn("讨论区 · 示例课程", out)
        self.assertIn("企业外部环境", out)

    def test_course_without_board_falls_through_to_next(self):
        payload = {"status": True, "datas": [_topic_item()]}
        session = FakeSession(payload)
        tc = FakeTaskCenter(session)

        class Chaoxing:
            def get_course_list(self):
                return [{"courseId": "1", "title": "没讨论区的课"},
                        {"courseId": "2", "title": "示例课程"}]

        real_resolve = discussion.resolve_bbsid
        calls = []

        def fake_resolve(tc_, course):
            calls.append(course.get("title"))
            return "2a4b2fff0f67dd5b88099bcd5c2a941e" if course.get("courseId") == "2" else ""

        with mock.patch.object(discussion, "resolve_bbsid", side_effect=fake_resolve):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = discussion.discuss_cli(Chaoxing(), tc, {}, list_only=True)
        self.assertTrue(result["ok"])
        self.assertEqual(calls[:2], ["没讨论区的课", "示例课程"])
        self.assertIn("示例课程", buf.getvalue())



class ParseSelectionTestCase(unittest.TestCase):
    """用户挑帖子：支持 1,3,5 / 1-3 / all"""

    def test_commas_and_ranges(self):
        self.assertEqual(discussion.parse_selection("1,3,5", 10), [1, 3, 5])
        self.assertEqual(discussion.parse_selection("1-3", 10), [1, 2, 3])
        self.assertEqual(discussion.parse_selection("3-1", 10), [1, 2, 3])
        self.assertEqual(discussion.parse_selection("1，2、4", 10), [1, 2, 4])

    def test_all_and_dedup(self):
        self.assertEqual(discussion.parse_selection("all", 3), [1, 2, 3])
        self.assertEqual(discussion.parse_selection("1,1,2", 5), [1, 2])

    def test_out_of_range_and_invalid(self):
        self.assertEqual(discussion.parse_selection("9", 3), None)
        self.assertIsNone(discussion.parse_selection("abc", 3))
        self.assertIsNone(discussion.parse_selection("", 3))


class FetchAllTopicsTestCase(unittest.TestCase):
    def test_stops_at_short_page(self):
        pages = {
            1: [_topic_item(uuid="u%d" % i) for i in range(discussion.DEFAULT_PAGE_SIZE)],
            2: [_topic_item(uuid="last")],
        }

        class Sess:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                page = kwargs["params"]["page"]
                self.calls.append(page)
                return FakeResp({"status": True, "datas": pages.get(page, [])})

        session = Sess()
        topics, capped = discussion.fetch_all_topics(session, "bbs")
        self.assertEqual(len(topics), discussion.DEFAULT_PAGE_SIZE + 1)
        self.assertFalse(capped)
        self.assertEqual(session.calls, [1, 2])

    def test_reports_capped_when_page_limit_reached(self):
        class Sess:
            def get(self, url, **kwargs):
                return FakeResp({"status": True,
                                 "datas": [_topic_item(uuid="u%d" % kwargs["params"]["page"])]
                                 * discussion.DEFAULT_PAGE_SIZE})

        topics, capped = discussion.fetch_all_topics(Sess(), "bbs", max_pages=2)
        self.assertTrue(capped)
        self.assertEqual(len(topics), discussion.DEFAULT_PAGE_SIZE * 2)


class FakeBoardTaskCenter:
    def __init__(self, draft):
        self.session = FakeSession({"status": True, "datas": []})
        self._draft = draft
        self.drafts = []
        self.submitted = []

    def get_course_tasks(self, course):
        return [{"name": "第1章"}]

    def open_task(self, task):
        return {"encryTaskUserId": "u1"}

    def get_groups(self, encry):
        return [{"encryptGroupId": "g1"}]

    def get_plans(self, encry, group):
        return [{"planType": 14, "encryptPlanId": "p1"}]

    def get_study_url(self, encry, plan_id):
        return ("https://groupweb.chaoxing.com/pc/topic/jumpToTopicDetail?"
                "bbsid=2a4b2fff0f67dd5b88099bcd5c2a941e&uuid=topic-uuid")

    def draft_reply(self, bbsid, topic_uuid, course=None, name="", referer="",
                    revision_hint="", previous_reply=""):
        self.drafts.append((topic_uuid, name, revision_hint, previous_reply))
        if revision_hint:
            revised = dict(self._draft)
            revised["reply"] = "按要求重写后的回复。"
            return revised
        return self._draft

    def submit_reply(self, bbsid, topic_uuid, **kwargs):
        self.submitted.append(topic_uuid)
        return True


class DiscussCliInteractiveTestCase(unittest.TestCase):
    """挑帖 → 草稿 → 确认 → 逐条发送"""

    def _run(self, inputs, draft=None, auto_yes=False):
        payload = {"status": True, "datas": [_topic_item(uuid="u1"), _topic_item(uuid="u2")]}
        tc = FakeBoardTaskCenter(draft or {
            "topic_info": {"url_token": "tok"}, "title": "标题",
            "reply": "我觉得吧，机会和能不能抓住是两回事。", "has_replied": False,
            "referer": "https://groupweb.chaoxing.com/pc/topic/jumpToTopicDetail?x=1",
        })
        tc.session = FakeSession(payload)
        chaoxing = mock.Mock()
        chaoxing.get_course_list.return_value = [{"courseId": "1", "title": "示例课程"}]
        answers = list(inputs)

        def fake_input(prompt=""):
            return answers.pop(0) if answers else "q"

        buf = io.StringIO()
        with mock.patch("builtins.input", fake_input), contextlib.redirect_stdout(buf):
            code = discussion.discuss_cli(chaoxing, tc, {}, auto_yes=auto_yes)
        return code, tc, buf.getvalue()

    def test_confirm_yes_sends_one(self):
        result, tc, out = self._run(["1", "y"])
        self.assertEqual(result["sent"], 1)
        self.assertEqual(tc.submitted, ["u1"])
        self.assertIn("我觉得吧", out)          # 草稿给用户看了
        self.assertIn("发送 1 条", out)

    def test_confirm_no_skips(self):
        result, tc, out = self._run(["1", "n"])
        self.assertEqual(tc.submitted, [])
        self.assertIn("已跳过这条", out)

    def test_multi_select_sends_one_by_one(self):
        result, tc, out = self._run(["1-2", "y", "y"])
        self.assertEqual(tc.submitted, ["u1", "u2"])
        self.assertIn("[1/2]", out)
        self.assertIn("[2/2]", out)

    def test_already_replied_is_skipped(self):
        draft = {"topic_info": {"url_token": "tok"}, "title": "标题", "reply": "",
                 "has_replied": True, "referer": ""}
        result, tc, out = self._run(["1", "y"], draft=draft)
        self.assertEqual(tc.submitted, [])
        self.assertIn("已经回复过", out)

    def test_auto_yes_does_not_auto_send(self):
        """--yes 只跳过启动确认；把 AI 回复发到公开讨论区必须逐条确认"""
        result, tc, out = self._run(["1"], auto_yes=True)
        self.assertEqual(tc.submitted, [])
        self.assertEqual(result["sent"], 0)

    def test_rewrite_with_hint_previews_new_draft_before_send(self):
        result, tc, out = self._run(["1", "r", "更短一点，别举案例", "y"])
        self.assertEqual(result["sent"], 1)
        self.assertEqual(tc.submitted, ["u1"])
        self.assertIn("按要求重写后的回复", out)
        self.assertIn("已按你的方向重写", out)
        self.assertEqual(tc.drafts[1][2], "更短一点，别举案例")
        self.assertIn("机会和能不能抓住", tc.drafts[1][3])

    def test_rewrite_never_submits_original_when_user_skips(self):
        result, tc, out = self._run(["1", "r", "语气更平实", "n"])
        self.assertEqual(result["sent"], 0)
        self.assertEqual(tc.submitted, [])
        self.assertIn("按要求重写后的回复", out)

    def test_revision_hint_is_capped(self):
        result, tc, out = self._run(["1", "r", "很" * 130, "n"])
        self.assertEqual(result["sent"], 0)
        self.assertEqual(len(tc.drafts[1][2]), discussion.MAX_REVISION_HINT_LENGTH)
        self.assertIn("优化方向过长", out)


class DraftSubmitSplitTestCase(unittest.TestCase):
    """模式 2 的草稿/提交拆分：草稿不提交，提交才发请求"""

    def _tc(self):
        from api.task_center import TaskCenter
        tc = TaskCenter(object(), {})

        class Sess:
            def __init__(self):
                self.posts = []

            def get(self, url, **kwargs):
                return FakeResp({"status": True})

            def post(self, url, **kwargs):
                self.posts.append(url)
                return FakeResp({"status": True, "datas": [{"id": 1}]})

        tc.session = Sess()
        tc.writer = mock.Mock(available=True)
        tc.writer.discussion.return_value = "先说观点：机会不等于结果，能不能抓住看自身资源。"
        return tc

    def test_draft_does_not_post(self):
        tc = self._tc()
        info = {"url_token": "tok", "title": "标题", "content": "正文", "user_puid": "1"}
        with mock.patch("api.task_center._extract_discussion_topic", return_value=info), \
             mock.patch.object(type(tc), "_load_discussion_replies", return_value=([], False)):
            draft = tc.draft_reply("bbs", "uuid", course={"title": "课"}, name="帖子")
        self.assertEqual(tc.session.posts, [])
        self.assertIn("机会不等于结果", draft["reply"])

    def test_redraft_passes_hint_and_previous_reply_to_writer(self):
        tc = self._tc()
        info = {"url_token": "tok", "title": "标题", "content": "正文", "user_puid": "1"}
        with mock.patch("api.task_center._extract_discussion_topic", return_value=info), \
             mock.patch.object(type(tc), "_load_discussion_replies", return_value=([], False)):
            tc.draft_reply("bbs", "uuid", course={"title": "课"}, name="帖子",
                           revision_hint="更简洁", previous_reply="原稿")
        self.assertEqual(tc.writer.discussion.call_args.kwargs["revision_hint"], "更简洁")
        self.assertEqual(tc.writer.discussion.call_args.kwargs["previous_reply"], "原稿")

    def test_submit_posts_and_records(self):
        tc = self._tc()
        with mock.patch("api.task_center.review.record") as recorder:
            ok = tc.submit_reply("bbs", "uuid", course={"title": "课"}, name="帖子",
                                 topic_info={"url_token": "tok"}, reply="正文内容",
                                 referer="https://x/y", echo=False)
        self.assertTrue(ok)
        self.assertEqual(len(tc.session.posts), 1)
        self.assertTrue(recorder.called)


if __name__ == "__main__":
    unittest.main()
