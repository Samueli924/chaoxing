# -*- coding: utf-8 -*-
"""审计修复的离线回归."""
#
# * 直播任务失败/被终止时不再报成功
# * 没有题库的章节测验不再被记为完成（返回 ERROR）
# * 向导确认页回车 = 取消（安全默认）
# * main() 在任务中心阶段被终止时不会走到"全部完成"
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-audit-"))

from api import base as base_mod  # noqa: E402
from api import task_center as tc_mod  # noqa: E402
from api.task_center import TaskCenter  # noqa: E402
from api import interrupt  # noqa: E402
from api.live_process import LiveProcessor  # noqa: E402
import setup_wizard as wizard  # noqa: E402


class FakeLive:
    def __init__(self, status=True, duration=60, finish=True):
        """Initialize configuration and runtime state."""
        self.name = "测试直播"
        self._status = status
        self._duration = duration
        self._finish = finish
        self.calls = 0

    def get_status(self):
        if not self._status:
            return None
        return {"temp": {"data": {"duration": self._duration}}}

    def do_finish(self):
        self.calls += 1
        return self._finish


class LiveProcessorTestCase(unittest.TestCase):
    def test_failed_status_is_not_success(self):
        self.assertFalse(LiveProcessor.run_live(FakeLive(status=False), speed=1.0))

    def test_failed_submit_is_not_success(self):
        live = FakeLive(finish=False)
        with mock.patch("api.live_process.time.sleep", return_value=None):
            self.assertFalse(LiveProcessor.run_live(live, speed=1.0))
        self.assertGreaterEqual(live.calls, 2)   # 失败会重试一次，但仍返回失败

    def test_interrupt_stops_and_reports_failure(self):
        live = FakeLive()
        with mock.patch.object(interrupt, "should_stop", return_value=True):
            self.assertFalse(LiveProcessor.run_live(live, speed=1.0))
        self.assertEqual(live.calls, 0)

    def test_success_only_after_all_minutes(self):
        live = FakeLive(duration=60)
        with mock.patch("api.live_process.time.sleep", return_value=None):
            self.assertTrue(LiveProcessor.run_live(live, speed=2.0))  # 倍速被忽略，仍按真实时间


class NoTikuQuizTestCase(unittest.TestCase):
    def test_no_tiku_returns_error(self):
        cx = base_mod.Chaoxing()
        cx.tiku = mock.Mock(DISABLE=True)
        result = cx.study_work({"title": "测试课"}, {"name": "章节测验"}, {})
        self.assertEqual(result, base_mod.StudyResult.ERROR)


class ConfirmDefaultTestCase(unittest.TestCase):
    def test_enter_cancels_by_default(self):
        with mock.patch.object(wizard, "_read_line", return_value=""), \
             mock.patch("builtins.print"):
            self.assertFalse(wizard.ask_yes_no("确认开始刷课吗？"))

    def test_y_confirms(self):
        with mock.patch.object(wizard, "_read_line", return_value="y"), \
             mock.patch("builtins.print"):
            self.assertTrue(wizard.ask_yes_no("确认开始刷课吗？"))

    def test_default_yes_variant(self):
        with mock.patch.object(wizard, "_read_line", return_value=""), \
             mock.patch("builtins.print"):
            self.assertTrue(wizard.ask_yes_no("重新输入吗？", default_no=False))


class SituationalDialogueTestCase(unittest.TestCase):
    """新版 AI 实践（情景对话）要明确报"暂不支持"，不能只说参数缺失."""

    def test_detected_as_unsupported_subtype(self):
        tc = TaskCenter(object(), {})

        class Resp:
            status_code = 200
            url = "https://mooc2-ans.chaoxing.com/mooc2-ans-vue/situationalDialogue?courseid=1"
            text = "<html>situationalDialogue</html>"

        class Sess:
            def get(self, url, **kwargs):
                return Resp()

        tc.session = Sess()
        messages = []
        with mock.patch.object(tc_mod.logger, "warning",
                               side_effect=lambda msg, *a, **k: messages.append(str(msg))), \
             mock.patch("builtins.print"):
            ok = tc.study_ai_practice("https://mooc2-ans.chaoxing.com/ai-evaluate/v2/answer?x=1")
        self.assertFalse(ok)
        self.assertTrue(any("情景对话" in m for m in messages), messages)


class NoFakeSuccessTestCase(unittest.TestCase):
    """独立审计新发现的"可能假完成"路径：一律不能返回成功（铁律 1）."""

    def test_unknown_card_type_is_collected(self):
        from api.decode import _process_attachment_cards
        jobs, unknown = _process_attachment_cards(
            [{"job": {"id": 1}, "type": "weird-new-type", "property": {}}]
        )
        self.assertEqual(jobs, [])
        self.assertEqual(unknown, ["weird-new-type"])

    def test_get_job_list_fails_on_unknown_card_types(self):
        cx = base_mod.Chaoxing()

        class Resp:
            status_code = 200
            text = "<html></html>"

        class Sess:
            def get(self, *args, **kwargs):
                return Resp()

        with mock.patch.object(base_mod.SessionManager, "get_session", return_value=Sess()), \
             mock.patch.object(base_mod, "decode_course_card",
                               return_value=([], {"unknownCardTypes": ["weird"]})):
            jobs, info = cx.get_job_list(
                {"courseId": "1", "clazzId": "2", "cpi": "3"},
                {"id": "9", "title": "第1章"},
            )
        self.assertIsNone(jobs)
        self.assertEqual(info.get("unknownCardTypes"), ["weird"])

    def test_chapter_document_result_false_is_error(self):
        cx = base_mod.Chaoxing()

        class Resp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"result": False, "msg": "任务未完成"}

        class Sess:
            def get(self, *args, **kwargs):
                return Resp()

        with mock.patch.object(base_mod.SessionManager, "get_session", return_value=Sess()):
            result = cx.study_document(
                {"courseId": "1", "clazzId": "2"},
                {"jobid": "1", "otherinfo": "nodeId_9-cpi_1", "jtoken": "t"},
            )
        self.assertEqual(result, base_mod.StudyResult.ERROR)

    def test_read_non_json_is_error(self):
        cx = base_mod.Chaoxing()

        class Resp:
            status_code = 200
            text = "<html>login</html>"

            def json(self):
                raise ValueError("not json")

        class Sess:
            def get(self, *args, **kwargs):
                return Resp()

        with mock.patch.object(base_mod.SessionManager, "get_session", return_value=Sess()):
            result = cx.study_read(
                {"courseId": "1", "clazzId": "2"},
                {"jobid": "1", "jtoken": "t"},
                {"knowledgeid": "9"},
            )
        self.assertEqual(result, base_mod.StudyResult.ERROR)


class TerminationGuardTestCase(unittest.TestCase):
    def test_stop_branch_exists_before_completion_notice(self):
        source = open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"),
            encoding="utf-8",
        ).read()
        stop_idx = source.rfind("已终止刷课")
        done_idx = source.rfind("超星刷课：全部完成")
        self.assertGreater(stop_idx, 0)
        self.assertGreater(done_idx, 0)
        self.assertLess(stop_idx, done_idx, "终止分支必须出现在'全部完成'通知之前")


if __name__ == "__main__":
    unittest.main()
