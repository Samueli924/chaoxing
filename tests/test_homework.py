# -*- coding: utf-8 -*-
"""
任务中心作业任务点（planType=4）离线回归

覆盖：
  * 新版作业页（mooc2/work/dowork）解析：题型、题干、选项、表单字段、提交地址
  * study_homework：选择题/填空题作答 + 提交表单字段 + 填空题按空提交
  * 失败不假装成功：页面无题目 / 简答题无写作器 / confirm 模式无终端
  * get_job_list 多页解析：num>=1 无 mArg 时按预期跳过，仍能读出 num=0 的任务点
全部离线，不联网、不碰真实数据。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-hw-"))

from api import base as base_mod  # noqa: E402
from api import decode as decode_mod  # noqa: E402
from api.task_center import TaskCenter  # noqa: E402

HOMEWORK_PAGE = """
<html><head><title>作业作答</title></head><body>
<form action="/mooc-ans/work/addStudentWorkNewWeb?_classId=1000002&courseid=1000001&token=TOK&totalQuestionNum=TQN" method="post" id="submitForm" name="submitForm">
<input type="hidden" id="courseId" name="courseId" value="1000001" />
<input type="hidden" id="classId" name="classId" value="1000002" />
<input type="hidden" id="knowledgeId" name="knowledgeid" value="0" />
<input type="hidden" id="cpi" name="cpi" value="1000003"/>
<input type="hidden" id="workId" name="workRelationId" value="54765819" />
<input type="hidden" id="answerId" name="workAnswerId" value="57787942"/>
<input type="hidden" id="jobid" name="jobid" value=""/>
<input type="hidden" id="standardEnc" name="standardEnc" value="STDENC"/>
<input type="hidden" id="pyFlag" name="pyFlag" value="" />
<input type="hidden" id="questionIds" name="answerwqbid" value="" />
<div class="padBom50 questionLi fontLabel singleQuesId" typeName="多选题" id="questionq1" data="q1">
  <h3 class="mark_name"><span>(多选题)</span><p>以下属于战略管理特征的有哪些？</p></h3>
  <input type="hidden" id="answertypeq1" name="answertypeq1" value="1" />
  <input type="hidden" id="answerq1" name="answerq1" value="" />
  <div class="stem_answer">
    <div class="answerBg" aria-label="A 战略管理具有全局性"><span data="A">A</span></div>
    <div class="answerBg" aria-label="B 战略管理具有长远性"><span data="B">B</span></div>
  </div>
</div>
<div class="padBom50 questionLi fontLabel singleQuesId" typeName="填空题" id="questionq2" data="q2">
  <h3 class="mark_name"><p>环境分析的内容有___、___。</p></h3>
  <input type="hidden" id="answertypeq2" name="answertypeq2" value="2" />
  <input type="hidden" name="tiankongsizeq2" value="2" />
  <div class="stem_answer">
    <textarea name="answerEditorq21"></textarea>
    <textarea name="answerEditorq22"></textarea>
  </div>
</div>
</form></body></html>
"""

HOMEWORK_URL = "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=54765819"

SHORTANSWER_PAGE = (
    HOMEWORK_PAGE
    .replace('typeName="填空题"', 'typeName="简答题"')
    .replace('id="answertypeq2" name="answertypeq2" value="2"',
             'id="answertypeq2" name="answertypeq2" value="4"')
)


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


class FakeTiku:
    DISABLE = False

    def __init__(self, answers):
        self.answers = answers

    def query_all(self, questions, query_delay=0.0):
        return list(self.answers)

    def judgement_select(self, answer):
        return str(answer).strip().lower() in ("对", "正确", "true", "1", "是")


class HomeworkDecodeTestCase(unittest.TestCase):
    def test_title_survives_invalid_h3_nesting(self):
        """真实页面把 <p> 嵌在 <h3> 里，lxml 会提前闭合 h3；题干不能丢"""
        page = decode_mod.decode_homework_page(HOMEWORK_PAGE)
        self.assertIn("以下属于战略管理特征的有哪些？", page["questions"][0]["title"])
        self.assertIn("环境分析的内容有", page["questions"][1]["title"])

    def test_parses_questions_and_form_fields(self):
        page = decode_mod.decode_homework_page(HOMEWORK_PAGE)
        self.assertEqual([q["id"] for q in page["questions"]], ["q1", "q2"])
        self.assertEqual(page["questions"][0]["type"], "multiple")
        self.assertEqual(page["questions"][1]["type"], "completion")
        self.assertIn("A 战略管理具有全局性", page["questions"][0]["options"])
        self.assertEqual(page["answerwqbid"], "q1,q2,")
        self.assertTrue(page["form_action"].startswith("/mooc-ans/work/addStudentWorkNewWeb"))
        self.assertEqual(page["workRelationId"], "54765819")
        self.assertEqual(page["cpi"], "1000003")

    def test_missing_form_is_not_parsed_as_finished(self):
        page = decode_mod.decode_homework_page("<html><body>请登录</body></html>")
        self.assertEqual(page["questions"], [])
        self.assertEqual(page["answerwqbid"], "")


class StudyHomeworkTestCase(unittest.TestCase):
    def _tc(self, page, answers, submit_mode="auto", writer=None):  # noqa: D102
        cx = mock.Mock()
        cx.tiku = FakeTiku(answers)
        tc = TaskCenter(cx, {"task_center_submit_mode": submit_mode}, writer=writer)
        tc.session = FakeSession([
            ("mooc2/work/task", FakeResponse(text=page)),
            ("addStudentWorkNewWeb", FakeResponse(payload={"status": True, "msg": "提交成功"})),
        ])
        return tc

    def test_submits_objective_and_completion_answers(self):
        # 题库对多选题返回字母串，对填空题返回按空拆分的列表
        tc = self._tc(HOMEWORK_PAGE, ["AB", ["水", "土"]])
        ok = tc.study_homework(
            "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=54765819",
            {"name": "第1章作业"},
        )
        self.assertTrue(ok)
        data = [kw["data"] for kw in tc.session.kwargs_calls if "data" in kw][-1]
        self.assertEqual(data["answerq1"], "AB")
        self.assertEqual(data["answertypeq1"], "1")
        self.assertEqual(data["answerEditorq21"], "水")
        self.assertEqual(data["answerEditorq22"], "土")
        self.assertNotIn("answerq2", data)  # 填空题按空提交
        self.assertEqual(data["pyFlag"], "")
        self.assertEqual(data["workRelationId"], "54765819")
        self.assertEqual(data["answerwqbid"], "q1,q2,")
        post_urls = [url for method, url in tc.session.calls if method == "post"]
        self.assertEqual(len(post_urls), 1)
        self.assertIn("addStudentWorkNewWeb", post_urls[0])
        self.assertIn("pyFlag=&ua=pc", post_urls[0])

    def test_submit_rejected_by_platform_is_not_success(self):
        cx = mock.Mock()
        cx.tiku = FakeTiku(["AB", ["水", "土"]])
        tc = TaskCenter(cx, {"task_center_submit_mode": "auto"})
        tc.session = FakeSession([
            ("mooc2/work/task", FakeResponse(text=HOMEWORK_PAGE)),
            ("addStudentWorkNewWeb", FakeResponse(payload={"status": False, "msg": "重复提交"})),
        ])
        self.assertFalse(tc.study_homework(HOMEWORK_URL, {"name": "作业"}))

    def test_recent_submission_is_not_repeated(self):
        """本地台账里有近期提交记录：不再重复提交（平台状态有延迟）"""
        tc = self._tc(HOMEWORK_PAGE, ["AB", ["水", "土"]])
        plan = {"name": "第1章作业", "planId": "plan-ledger-1"}
        tc._mark_submitted(plan)
        self.assertTrue(tc._recently_submitted(plan))
        self.assertTrue(tc.study_homework(HOMEWORK_URL, plan))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))

    def test_other_plan_is_not_affected(self):
        tc = self._tc(HOMEWORK_PAGE, ["AB", ["水", "土"]])
        tc._mark_submitted({"planId": "plan-a"})
        self.assertFalse(tc._recently_submitted({"planId": "plan-b"}))

    def test_page_without_questions_does_not_submit(self):
        tc = self._tc("<html><form id='submitForm' action='/x'></form></html>", [])
        self.assertFalse(tc.study_homework(HOMEWORK_URL, {"name": "作业"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))

    def test_shortanswer_without_writer_does_not_submit(self):
        writer = mock.Mock()
        writer.available = False
        tc = self._tc(SHORTANSWER_PAGE, [None], writer=writer)
        self.assertFalse(tc.study_homework(HOMEWORK_URL, {"name": "作业"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))

    def test_confirm_mode_without_tty_does_not_submit(self):
        tc = self._tc(HOMEWORK_PAGE, ["AB", ["水", "土"]], submit_mode="confirm")
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertFalse(tc.study_homework(HOMEWORK_URL, {"name": "作业"}))
        self.assertFalse(any(method == "post" for method, _ in tc.session.calls))


class JobListParseTestCase(unittest.TestCase):
    CARD_PAGE = (
        'mArg={"attachments":[{"type":"workid","jobid":"w-1","enc":"e2","job":{"a":1}}],'
        '"defaults":{"ktoken":"k","cpi":"3","knowledgeid":"9"}};'
    )

    def _run(self, pages):
        cx = base_mod.Chaoxing()

        class Sess:
            def get(self, url, params=None, **kwargs):
                num = str((params or {}).get("num", ""))
                return FakeResponse(text=pages.get(num, ""))

        with mock.patch.object(base_mod.SessionManager, "get_session", return_value=Sess()):
            return cx.get_job_list(
                {"clazzId": "1", "courseId": "2", "cpi": "3"}, {"id": "9", "title": "t"}
            )

    def test_reads_jobs_when_later_pages_have_no_marg(self):
        pages = {"0": self.CARD_PAGE}
        for num in "123456":
            pages[num] = "<html>mArg = $mArg;</html>"
        jobs, info = self._run(pages)
        self.assertEqual([j["jobid"] for j in jobs], ["w-1"])
        self.assertEqual(info.get("knowledgeid"), "9")

    def test_all_pages_without_marg_is_read_failure(self):
        jobs, info = self._run({"0": "no json here"})
        self.assertIsNone(jobs)
        self.assertTrue(info.get("parseError"))

    def test_missing_pages_are_summarized_once(self):
        """逐页无 mArg 不再逐条刷日志，每章汇总成一条"""
        pages = {"0": self.CARD_PAGE}
        for num in "123456":
            pages[num] = "<html>mArg = $mArg;</html>"
        messages = []
        sink_id = base_mod.logger.add(
            lambda message: messages.append(message.record["message"]), level="DEBUG"
        )
        try:
            jobs, _info = self._run(pages)
        finally:
            base_mod.logger.remove(sink_id)
        self.assertEqual([j["jobid"] for j in jobs], ["w-1"])
        self.assertFalse([m for m in messages if "找不到 mArg" in m], messages)
        self.assertEqual(len([m for m in messages if "无 mArg" in m]), 1, messages)

    def test_duplicate_jobids_across_pages_are_deduped(self):
        jobs, _info = self._run({"0": self.CARD_PAGE, "1": self.CARD_PAGE})
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
