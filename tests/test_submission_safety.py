"""Submission ordering, cancellation and validation must be observable offline."""

import tempfile
import unittest
from unittest import mock

from api.ai_writer import HumanLikeWriter
from api import review
from api.task_center import TaskCenter
from tests.test_homework import FakeSession, FakeResponse, FakeTiku, SHORTANSWER_PAGE, HOMEWORK_URL


class SubmissionSafetyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = mock.patch.dict("os.environ", {"CX_DATA_HOME": self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_discussion_is_durable_before_request(self):
        session = mock.Mock()
        def post(*args, **kwargs):
            items = review.load()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["status"], "待提交")
            return FakeResponse(payload={"status": True, "datas": {"id": "test"}})
        session.post.side_effect = post
        tc = TaskCenter(object(), {})
        tc.session = session
        self.assertTrue(tc.submit_reply("test-board", "test-topic", reply="概念要和具体问题联系起来。", echo=False))
        self.assertIn("平台已接受", review.load()[0]["status"])

    def test_failed_review_prevents_discussion_request(self):
        session = mock.Mock()
        tc = TaskCenter(object(), {})
        tc.session = session
        with mock.patch("api.task_center.review.record", return_value=None):
            self.assertFalse(tc.submit_reply("test-board", "test-topic", reply="待审核正文", echo=False))
        session.post.assert_not_called()

    def _homework(self):
        session = FakeSession([(HOMEWORK_URL, FakeResponse(text=SHORTANSWER_PAGE))])
        writer = mock.Mock(available=True)
        writer.answer.return_value = "专业化可以先把现有业务做好。"
        cx = type("CX", (), {"tiku": FakeTiku([None])})()
        tc = TaskCenter(cx, {"task_center_submit_mode": "confirm"}, writer=writer)
        tc.session = session
        return tc

    def test_cancelled_homework_is_not_marked_submitted(self):
        tc = self._homework()
        with mock.patch.object(tc, "confirm_submission", return_value=False):
            self.assertFalse(tc.study_homework(HOMEWORK_URL, {"name": "测试作业"}))
        self.assertEqual(review.load()[0]["status"], "用户取消，未提交")
        self.assertFalse(any(method == "post" for method, url in tc.session.calls))

    def test_homework_review_failure_blocks_request(self):
        tc = self._homework()
        with mock.patch("api.task_center.review.record", return_value=None):
            self.assertFalse(tc.study_homework(HOMEWORK_URL, {"name": "测试作业"}))
        self.assertFalse(any(method == "post" for method, url in tc.session.calls))

    def test_later_generation_failure_finishes_earlier_draft(self):
        tc = self._homework()
        questions = [
            {"id": 1, "type": "shortanswer", "title": "第一题", "options": "", "answerField": {}},
            {"id": 2, "type": "shortanswer", "title": "第二题", "options": "", "answerField": {}},
        ]
        tc.writer.answer.side_effect = ["专业化先做好已有业务。", RuntimeError("无法生成")]
        tc.chaoxing.tiku = FakeTiku([None, None])
        with mock.patch("api.task_center.decode_homework_page", return_value={"questions": questions}):
            self.assertFalse(tc.study_homework(HOMEWORK_URL, {"name": "测试作业"}))
        self.assertEqual(review.load()[0]["status"], "生成或复核失败，未提交")
        self.assertFalse(any(method == "post" for method, url in tc.session.calls))

    def test_invented_experience_and_source_fail_after_all_retries(self):
        for text in ("我们小组上次讨论过这个问题。", "老师提过这个例子。", "教材上写过这个例子。",
                     "老师在课堂中强调控制成本。", "根据教材第三章的论述，企业要控制成本。",
                     "我们小组曾经做过成本调查。", "我去年参加过企业培训。",
                     "教材第二章明确写道，成本需要分摊。", "我参加过一次企业培训。", "我理解这个问题，是因为曾经参加过企业培训。",
                     "我认为去年参加的企业培训很有帮助。", "教授在授课时明确提及固定成本不会随产量变化。",
                     "本章原文写道，固定成本不会随产量变化。",
                     "我认为亲自经营过店铺以后，更能理解成本。",
                     "讲义中将固定成本定义为不随产量变化的成本。"):
            writer = HumanLikeWriter({})
            with mock.patch.object(writer, "_chat", return_value=text) as chat:
                with self.assertRaises(RuntimeError):
                    writer.answer("解释一个概念")
                self.assertEqual(chat.call_count, 3)

    def test_final_truncated_text_is_checked(self):
        writer = HumanLikeWriter({})
        with mock.patch.object(writer, "_chat", return_value="老师提过这个例子。" * 20):
            with self.assertRaises(RuntimeError):
                writer._generate_text("解释概念", 20)

    def test_ai_numeric_types_and_stem_agree(self):
        for value, expected in ((0, "single"), (1, "multiple"), (3, "judgement"), (4, "shortanswer")):
            turn = {"questionTypeInt": value, "questionStem": "测试题干"}
            self.assertEqual(TaskCenter._ai_turn_type(turn), expected)
            self.assertEqual(TaskCenter._ai_turn_title(turn), "测试题干")
