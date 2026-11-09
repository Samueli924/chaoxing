# -*- coding: utf-8 -*-
"""章节检测目标分数、思考重做、剩余次数和回查的单元测试（模拟学习通页面与会话）."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api.base as base  # noqa: E402
from api.base import Chaoxing, StudyResult, decide_work_redo, parse_graded_work  # noqa: E402


def graded_page(score, remaining=None, passing=60):
    redo = (f'<a href="#" onclick="redoTest()" class="jb_btn_bg">重做 <i>(剩余 {remaining} 次)</i></a>'
            if remaining is not None else "")
    return f"""<html><script>
    var courseId = "111"; var classId = "222"; var workId = "333"; var workAnswerId = "444";
    var knowledgeid = "555"; var jobid = "work-333"; var originJobId = "work-333"; var enc = "abc"; var cpi = "666";
    var passingStandard = "{passing}"; var stuScore = "{score}";
    </script><span>本次成绩<i>{score}</i>分</span>{redo}</html>"""


class ParseGradedTest(unittest.TestCase):
    def test_parse(self):
        info = parse_graded_work(graded_page(65.0, 2))
        self.assertEqual(info["score"], 65.0)
        self.assertEqual(info["remaining"], 2)
        self.assertTrue(info["can_redo"])
        self.assertEqual(info["params"]["workAnswerId"], "444")
        self.assertEqual(len(info["params"]), 9)

    def test_no_redo_button(self):
        info = parse_graded_work(graded_page(80.0))
        self.assertIsNone(info["remaining"])
        self.assertFalse(info["can_redo"])

    def test_editable_page_is_not_graded(self):
        self.assertIsNone(parse_graded_work('<form><input name="answerwqbid" value="1,2,"></form>'))
        self.assertIsNone(parse_graded_work(""))


class DecideTest(unittest.TestCase):
    def test_rules(self):
        d = decide_work_redo
        self.assertEqual(d(95, 2, 90, True, 3)[0], "pass")
        self.assertEqual(d(90, 2, 90, True, 3)[0], "pass")
        self.assertEqual(d(65, 2, 90, True, 3)[0], "redo")
        self.assertEqual(d(65, 1, 90, True, 3)[0], "keep")  # 只剩最后一次：跳过
        self.assertIn("最后 1 次", d(65, 1, 90, True, 3)[1])
        self.assertEqual(d(65, None, 90, True, 3)[0], "keep")  # 没有重做按钮
        self.assertEqual(d(65, 0, 90, True, 3)[0], "keep")
        self.assertEqual(d(65, 2, 90, False, 3)[0], "keep")  # 未开启自动重做
        self.assertEqual(d(65, 2, 90, True, 0)[0], "keep")  # 重做轮数用完
        self.assertEqual(d(0, 2, 90, True, 3, uncertain=True)[0], "keep")  # 批改结果无法确认
        self.assertEqual(d(None, 2, 90, True, 3)[0], "keep")


class FakeSession:
    """按地址返回预设页面：api/work 依次返回 pages 中的内容，retest 返回 retest_json."""

    def __init__(self, pages, retest_json=None):
        self.pages = list(pages)
        self.retest_json = retest_json
        self.calls = []

    def get(self, url, params=None, timeout=None, **kw):
        self.calls.append(url)
        if url.endswith("/work/retest"):
            return SimpleNamespace(json=lambda: self.retest_json, status_code=200, text="")
        text = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        return SimpleNamespace(text=text, status_code=200, url=url)


class StudyWorkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache_patch = mock.patch.object(Chaoxing, "WORK_CACHE_FILE", os.path.join(self.tmp, "cache.json"))
        self.cache_patch.start()
        self.tiku = mock.Mock(DISABLE=False)
        self.course = {"courseId": "111", "clazzId": "222", "cpi": "666", "title": "测试课程"}
        self.job = {"jobid": "work-333", "enc": "abc", "name": "章节测验"}
        self.job_info = {"knowledgeid": "555", "ktoken": "t", "cpi": "666"}

    def tearDown(self):
        self.cache_patch.stop()

    def run_work(self, session, **kwargs):
        cx = Chaoxing(tiku=self.tiku, work_redo_enabled=True, work_max_retries=3, **kwargs)
        with mock.patch.object(base.SessionManager, "get_session", return_value=session), \
                mock.patch.object(Chaoxing, "get_uid", return_value="u1"), \
                mock.patch.object(base.time, "sleep"):
            return cx, cx.study_work(self.course, self.job, self.job_info)

    def test_submitted_score_above_target_passes_and_is_cached(self):
        session = FakeSession([graded_page(95.0, 2)])
        cx, result = self.run_work(session, work_min_score=90)
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertFalse(any(u.endswith("/work/retest") for u in session.calls))
        with open(Chaoxing.WORK_CACHE_FILE, encoding="utf8") as f:
            self.assertEqual(json.load(f), {"u1:work:work-333": 95.0})

    def test_last_redo_chance_is_kept(self):
        session = FakeSession([graded_page(65.0, 1)])
        _, result = self.run_work(session, work_min_score=90)
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertFalse(any(u.endswith("/work/retest") for u in session.calls))
        self.tiku.set_redo_mode.assert_called_with(False)  # 从未开启思考重做

    def test_low_score_requests_redo_with_thinking(self):
        # 首次拿到 65 分批改页 -> 申请重做 -> 重做页面仍拿不到题目（模拟） -> 再次读到批改页（剩余 1 次）后停止
        session = FakeSession([graded_page(65.0, 2), graded_page(65.0, 1)],
                              retest_json={"status": True, "url": "/mooc-ans/work/doHomeWorkNew?x=1"})
        _, result = self.run_work(session, work_min_score=90)
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(sum(u.endswith("/work/retest") for u in session.calls), 1)
        self.assertIn("https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?x=1", session.calls)
        self.tiku.set_redo_mode.assert_any_call(True)
        self.tiku.set_redo_mode.assert_called_with(False)  # 结束后关闭

    def test_default_target_is_full_marks(self):
        session = FakeSession([graded_page(95.0, 1)])
        _, result = self.run_work(session)  # 未设置 work_min_score，默认要求满分；只剩 1 次所以保留
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertFalse(any(u.endswith("/work/retest") for u in session.calls))

    def test_retest_rejected(self):
        session = FakeSession([graded_page(65.0, 2)], retest_json={"status": False, "msg": "已超过截止时间"})
        _, result = self.run_work(session, work_min_score=90)
        self.assertEqual(result, StudyResult.SUCCESS)


class AiRedoModeTest(unittest.TestCase):
    def test_redo_mode_turns_thinking_on_per_thread(self):
        import threading
        from api.answer import AI
        ai = AI()
        ai.config_set({"provider": "AI", "endpoint": "http://x/v1", "key": "k", "model": "m", "http_proxy": "",
                       "min_interval_seconds": "0", "submit": "false", "cover_rate": "0.9", "true_list": "对",
                       "false_list": "错", "ai_disable_thinking": "true", "ai_timeout": "60"})
        ai.init_tiku()
        self.assertTrue(ai._thinking_off())
        ai.set_redo_mode(True)
        ai.set_work_feedback(["- 题目：x"])
        self.assertFalse(ai._thinking_off())
        self.assertEqual(ai._timeout(), 300)
        other = {}
        t = threading.Thread(target=lambda: other.update(off=ai._thinking_off(), fb=ai.work_feedback))
        t.start()
        t.join()
        self.assertEqual(other, {"off": True, "fb": None})  # 其他线程（其他章节检测）不受影响
        ai.set_redo_mode(False)
        self.assertTrue(ai._thinking_off())


if __name__ == "__main__":
    unittest.main()
