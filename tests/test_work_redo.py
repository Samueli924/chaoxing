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

    def test_redo_fetch_error_is_retried_later(self):
        # 申请重做成功后取题遇到临时错误：不能算成功，返回失败让章节稍后重试（审查意见）
        session = FakeSession([graded_page(65.0, 2), "<html>服务器繁忙</html>"],
                              retest_json={"status": True, "url": "/mooc-ans/work/doHomeWorkNew?x=1"})
        _, result = self.run_work(session, work_min_score=90)
        self.assertEqual(result, StudyResult.ERROR)

    def test_retest_rejected(self):
        session = FakeSession([graded_page(65.0, 2)], retest_json={"status": False, "msg": "已超过截止时间"})
        _, result = self.run_work(session, work_min_score=90)
        self.assertEqual(result, StudyResult.SUCCESS)


class ManualMarkingTest(StudyWorkTest):
    """回查阶段与「需手动完成」标注."""

    def run_collect(self, session, recheck_only=False, **kwargs):
        cx = Chaoxing(tiku=self.tiku, work_redo_enabled=True, work_max_retries=3, work_min_score=90, **kwargs)
        results = []
        cx.work_result_callback = results.append
        with mock.patch.object(base.SessionManager, "get_session", return_value=session), \
                mock.patch.object(Chaoxing, "get_uid", return_value="u1"), \
                mock.patch.object(base.time, "sleep"):
            r = cx.study_work(self.course, self.job, self.job_info, recheck_only=recheck_only)
        return cx, r, results

    def test_codes(self):
        self.assertEqual(decide_work_redo(65, 1, 90, True, 3)[2], "last_chance")
        self.assertEqual(decide_work_redo(65, 0, 90, True, 3)[2], "no_redo")
        self.assertEqual(decide_work_redo(65, 2, 90, True, 0)[2], "rounds_exhausted")
        self.assertEqual(decide_work_redo(65, 2, 90, True, 3, uncertain=True)[2], "uncertain")
        self.assertEqual(decide_work_redo(95, 2, 90, True, 3)[2], "pass")
        self.assertEqual(decide_work_redo(65, 2, 90, True, 3)[2], "redo")
        self.assertIn("联网搜索", decide_work_redo(65, 2, 90, True, 3)[1])

    def test_last_chance_marked_manual(self):
        _, r, results = self.run_collect(FakeSession([graded_page(65.0, 1)]), recheck_only=True)
        self.assertEqual(r, StudyResult.SUCCESS)
        self.assertEqual([(x["status"], x["code"], x["score"], x["remaining"]) for x in results],
                         [("manual", "last_chance", 65.0, 1)])
        self.assertEqual(results[0]["chapter_id"], "555")
        self.assertEqual(results[0]["target"], 90)

    def test_still_low_after_redo_marked_manual(self):
        session = FakeSession([graded_page(65.0, 2), graded_page(70.0, 1)],
                              retest_json={"status": True, "url": "/mooc-ans/work/doHomeWorkNew?x=1"})
        _, _, results = self.run_collect(session, recheck_only=True)
        self.assertEqual([x["status"] for x in results], ["redoing", "manual"])
        self.assertIn("自动重做后仍未达到 90 分", results[-1]["reason"])

    def test_retest_failure_marked_manual(self):
        session = FakeSession([graded_page(65.0, 2)], retest_json={"status": False, "msg": "已截止"})
        _, _, results = self.run_collect(session, recheck_only=True)
        self.assertEqual(results[-1]["code"], "retest_failed")

    def test_unsubmitted_quiz_left_for_learning_phase(self):
        session = FakeSession(["<html>可作答页面</html>"])
        with mock.patch.object(base, "decode_questions_info",
                               return_value={"questions": [{"id": "1"}], "answerwqbid": "1,"}):
            cx, r, results = self.run_collect(session, recheck_only=True)
        self.assertEqual(r, StudyResult.SUCCESS)
        self.assertEqual(results, [])
        self.tiku.query_all.assert_not_called()  # 回查阶段不作答
        self.assertNotIn("work-333", cx._rechecked_jobs)  # 刷课阶段还要处理

    def test_rechecked_quiz_skipped_in_learning_phase(self):
        cx, _, _ = self.run_collect(FakeSession([graded_page(65.0, 1)]), recheck_only=True)
        session = FakeSession([graded_page(65.0, 1)])
        with mock.patch.object(base.SessionManager, "get_session", return_value=session):
            self.assertEqual(cx.study_work(self.course, self.job, self.job_info), StudyResult.SUCCESS)
        self.assertEqual(session.calls, [])  # 没有再次请求


class DecodeSubmittedWorkTest(unittest.TestCase):
    """已提交的章节检测卡片没有 job 字段（实测音乐鉴赏 2.4 章节测验），回查时也要识别出来."""

    def cards_html(self, cards):
        import json as _json
        data = {"attachments": cards, "defaults": {"knowledgeid": 1, "ktoken": "k", "cpi": 1, "clazzId": 1}}
        return "<script>mArg=" + _json.dumps(data) + ";</script>"

    def test_submitted_work_without_job_field(self):
        from api.decode import decode_course_card
        card = {"type": "workid", "jobid": "work-123", "enc": "e", "aid": 1, "mid": "m", "otherInfo": "x",
                "property": {"workid": "123", "title": "章节测验"}}
        html = self.cards_html([card])
        self.assertEqual(decode_course_card(html)[0], [])  # 刷课阶段：已提交的检测不再作答
        jobs, _ = decode_course_card(html, include_passed_work=True)
        self.assertEqual([(j["type"], j["jobid"], j.get("submitted")) for j in jobs], [("workid", "work-123", True)])


class RecheckCoursesTest(unittest.TestCase):
    """main.recheck_courses：先回查全部课程，统计需手动完成的数量，并利用缓存跳过已确认的章节."""

    def test_flow(self):
        import main
        cache = {}
        calls = []
        cx = mock.Mock()
        cx.work_result_callback = None
        cx.work_cache_get.side_effect = cache.get
        cx.work_cache_set.side_effect = cache.__setitem__
        cx.get_course_point.side_effect = lambda cid, clz, cpi: {"points": [
            {"id": f"{cid}-1", "title": "1.1"}, {"id": f"{cid}-2", "title": "1.2"},
            {"id": f"{cid}-3", "title": "1.3", "has_finished": True}, {"id": f"{cid}-4", "title": "1.4"}]}

        def get_job_list(course, point, include_passed_work=False, study_empty=True):
            self.assertTrue(include_passed_work)
            self.assertFalse(study_empty)
            if point["id"].endswith("-3") or point["id"].endswith("-4"):
                return [{"type": "video", "jobid": "v"}], {}
            return [{"type": "workid", "jobid": "work-" + point["id"]}], {"knowledgeid": point["id"]}
        cx.get_job_list.side_effect = get_job_list

        def study_work(course, job, job_info, recheck_only=False):
            calls.append((job["jobid"], recheck_only))
            if job["jobid"].endswith("-1"):
                cache["work:" + job["jobid"]] = 95.0  # 达标
            else:
                cx.work_result_callback({"status": "manual"})
            return StudyResult.SUCCESS
        cx.study_work.side_effect = study_work

        progress = []
        courses = [{"courseId": "A", "clazzId": "1", "cpi": "1", "title": "课程A"},
                   {"courseId": "B", "clazzId": "1", "cpi": "1", "title": "课程B"}]
        stats = main.recheck_courses(cx, courses, progress=lambda t, i, n: progress.append((t, i, n)))
        self.assertEqual(calls, [("work-A-1", True), ("work-A-2", True), ("work-B-1", True), ("work-B-2", True)])
        self.assertEqual(stats, {"chapters": 8, "works": 4, "manual": 2})
        self.assertEqual(progress[0], ("课程A", 1, 4))
        self.assertEqual(cache["chapter:A:A-1"], "ok")
        self.assertEqual(cache["chapter:A:A-3"], "no-work")
        self.assertNotIn("chapter:A:A-4", cache)  # 未完成章节不记「没有检测」
        self.assertNotIn("chapter:A:A-2", cache)  # 需手动完成的章节下次还会回查

        calls.clear()
        main.recheck_courses(cx, courses)
        self.assertEqual(calls, [("work-A-2", True), ("work-B-2", True)])  # 已确认的章节被跳过


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
