# -*- coding: utf-8 -*-
"""章节检测：解析批改结果、按对错标记重做（/work/retest）、排除已答错的选项（不访问网络）。"""
import os
import sys
import tempfile
import unittest
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api.answer as answer_mod  # noqa: E402
from api import base, decode  # noqa: E402
from api.answer import Tiku  # noqa: E402
from api.base import Chaoxing, StudyResult, evaluate_work_detail  # noqa: E402

GRADED_TEMPLATE = """
<input type="hidden" id="courseId" value="2" /><input type="hidden" id="classId" value="1" />
<input type="hidden" id="cpi" value="5" /><input type="hidden" id="workId" value="777" />
<input type="hidden" id="workAnswerId" value="888" /><input type="hidden" id="knowledgeid" value="11" />
<input type="hidden" id="jobid" value="work-abc" /><input type="hidden" id="originJobId" value="work-abc" />
<input type="hidden" id="enc" value="encv" />
<span>本次成绩<i>{score}</i>分</span>
{questions}
"""
GRADED_QUESTION = """
<div class="TiMu newTiMu ans-cc singleQuesId" data="{qid}">
  <div class="Zy_TItle clearfix"><i class="fl">1</i>
    <div class="clearfix fontLabel"><span class="newZy_TItle">【{label}】</span><p>{title}</p></div></div>
  <ul class="Zy_ulTop qtDetail">{options}</ul>
  <div class="newAnswerBx"><div class="myAnswerBx"><div class="myAnswer">
    <span class="answerFont fl">我的答案：</span><div class="fl answerCon"> {mine} </div></div>
    <div class="answerScore"><div class="CorrectOrNot fl"><span class="{mark}"></span></div>
    <div class="fr newAnswerScore"><span class="scoreNum">{qscore}</span>分</div></div></div>
    {correct}
  </div>
</div>
"""
WORK_PAGE = """
<form>
  <input name="workAnswerId" value="888"><input name="workRelationId" value="777"><input name="pyFlag" value="">
  <div class="singleQuesId" data="q1"><div class="TiMu" data="0">
    <div class="Zy_TItle">1【单选题】下列哪个是水果？</div>
    <ul><li aria-label="A 石头">A</li><li aria-label="B 苹果">B</li><li aria-label="C 铁块">C</li></ul></div></div>
  <div class="singleQuesId" data="q2"><div class="TiMu" data="3">
    <div class="Zy_TItle">2【判断题】太阳从东边升起。</div>
    <ul><li aria-label="对">对</li><li aria-label="错">错</li></ul></div></div>
</form>
"""


def graded(score, items):
    parts = []
    for qid, label, title, mine, mark, correct in items:
        options = "".join(f'<li><i class="fl">{k}、</i><a><p>{v}</p></a></li>' for k, v in (("A", "石头"), ("B", "苹果"), ("C", "铁块"))) \
            if label == "单选题" else ""
        correct_html = (f'<div class="correctAnswerBx"><div class="correctAnswer"><span>正确答案：</span>'
                        f'<div class="fl answerCon">{correct}</div></div></div>') if correct else ""
        parts.append(GRADED_QUESTION.format(qid=qid, label=label, title=title, options=options, mine=mine,
                                            mark=mark, qscore=50 if mark == "marking_dui" else 0, correct=correct_html))
    return GRADED_TEMPLATE.format(score=score, questions="".join(parts))


class DecodeWorkResultTestCase(unittest.TestCase):
    def test_marks_answers_and_inputs(self):
        html = graded(50, [("q1", "单选题", "下列哪个是水果？", "A", "marking_cuo", ""),
                           ("q2", "判断题", "太阳从东边升起。", "对", "marking_dui", "")])
        result = decode.decode_work_result(html)
        self.assertEqual(result["score"], 50.0)
        self.assertEqual(result["inputs"]["workId"], "777")
        self.assertEqual(result["inputs"]["enc"], "encv")
        q1, q2 = result["questions"]
        self.assertEqual((q1["id"], q1["type_label"], q1["title"], q1["my_answer"], q1["correct"]),
                         ("q1", "【单选题】", "下列哪个是水果？", "A", False))
        self.assertEqual(q1["options"][1], "B、 苹果")
        self.assertTrue(q2["correct"])
        self.assertEqual(evaluate_work_detail(result["questions"])["wrong"][0]["id"], "q1")

    def test_partial_and_revealed_answer(self):
        html = graded(0, [("q1", "单选题", "下列哪个是水果？", "A", "marking_bandui", "B")])
        q = decode.decode_work_result(html)["questions"][0]
        self.assertFalse(q["correct"])
        self.assertTrue(q["partial"])
        self.assertEqual(q["correct_answer"], "B")

    def test_no_marks_falls_back_to_correct_answer(self):
        detail = [{"id": "1", "type_label": "【单选题】", "my_answer": "A", "correct_answer": "B", "correct": None},
                  {"id": "2", "type_label": "【单选题】", "my_answer": "C", "correct_answer": "", "correct": None}]
        evaluation = evaluate_work_detail(detail)
        self.assertEqual([q["id"] for q in evaluation["wrong"]], ["1"])
        self.assertIsNone(evaluate_work_detail([detail[1]]))

    def test_record_list_times_start_from_zero(self):
        html = """<ul class="viewMenuList">
          <li onclick="showRecord('0', this)"><div><span class="viewNum">第1次</span></div><span class="viewScore">60.0分</span></li>
          <li onclick="showRecord('1', this)"><div><span class="viewNum">第2次</span></div><span class="viewScore">100.0分</span></li>
        </ul>"""
        self.assertEqual(decode.decode_work_record_list(html), [("0", 60.0), ("1", 100.0)])


class _DummyTiku(Tiku):
    """什么都搜不到的题库（模拟免费题库未命中），答题只能靠随机与排除."""

    def __init__(self):
        super().__init__()
        self.name = "测试题库"
        self.SUBMIT = True
        self.COVER_RATE = 0.0
        self.true_list = ["正确", "对", "true"]
        self.false_list = ["错误", "错", "false"]

    def _query(self, q_info):
        return None


class _Resp:
    def __init__(self, text, url="https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew", status=200):
        self.text = text
        self.url = url
        self.status_code = status
        self.history = []
        self.headers = {}

    def json(self):
        import json
        return json.loads(self.text)


class _FakeWorkServer:
    """模拟章节检测的服务端：正确答案为 单选B、判断 对；允许重做."""

    CORRECT = {"q1": "B", "q2": "true"}

    def __init__(self):
        self.state = "open"  # open -> graded -> open ...
        self.submissions = []
        self.retests = 0

    def _graded_page(self):
        answers = self.submissions[-1]
        items = []
        for qid, label, title in (("q1", "单选题", "下列哪个是水果？"), ("q2", "判断题", "太阳从东边升起。")):
            mine = answers[f"answer{qid}"]
            ok = mine == self.CORRECT[qid]
            items.append((qid, label, title, mine, "marking_dui" if ok else "marking_cuo", ""))
        score = 50 * sum(1 for q in ("q1", "q2") if answers[f"answer{q}"] == self.CORRECT[q])
        return graded(score, items)

    def get(self, url, params=None, headers=None, **kwargs):
        path = urlparse(url).path
        if path.endswith("/api/work") or path.endswith("/doHomeWorkNew"):
            if self.state == "open":
                return _Resp(WORK_PAGE)
            return _Resp(self._graded_page(), url="https://mooc1.chaoxing.com/mooc-ans/work/selectWorkQuestionYiPiYue")
        if path.endswith("/work/retest"):
            assert params["workId"] == "777" and params["enc"] == "encv", params
            self.retests += 1
            self.state = "open"
            return _Resp('{"status": true, "url": "/mooc-ans/work/doHomeWorkNew?redo=1"}', url=url)
        if path.endswith("/work/record-list"):
            items = "".join(f'<li onclick="showRecord(\'{i}\', this)"><span class="viewScore">0分</span></li>'
                            for i in range(len(self.submissions)))
            return _Resp(f'<ul class="viewMenuList">{items}</ul>', url=url)
        if path.endswith("/work/record-detail"):
            times = int(params["times"])
            assert times == len(self.submissions) - 1, "应请求最新一次作答（times 从 0 开始）"
            return _Resp(self._graded_page(), url=url)
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, data=None, **kwargs):
        assert url.endswith("/work/addStudentWorkNew")
        if data["pyFlag"] == "":
            self.submissions.append(dict(data))
            self.state = "graded"
        return _Resp('{"status": true, "msg": "ok"}', url=url)


class WorkRedoTestCase(unittest.TestCase):
    def setUp(self):
        # 题库缓存写到临时目录，避免污染工作目录（data_path 遇到绝对路径时直接使用该路径）
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = answer_mod.CacheDAO.DEFAULT_CACHE_FILE
        answer_mod.CacheDAO.DEFAULT_CACHE_FILE = os.path.join(tmp.name, "cache.json")
        self.addCleanup(setattr, answer_mod.CacheDAO, "DEFAULT_CACHE_FILE", original)

    def _run(self, server, max_redo=3):
        cx = Chaoxing(tiku=_DummyTiku(), work_max_retries=max_redo)
        original = base.SessionManager.get_session
        base.SessionManager.get_session = classmethod(lambda cls: server)
        self.addCleanup(setattr, base.SessionManager, "get_session", original)
        original_sleep = base.time.sleep
        base.time.sleep = lambda s: None
        self.addCleanup(setattr, base.time, "sleep", original_sleep)
        course = {"courseId": "2", "clazzId": "1", "cpi": "5", "title": "课程"}
        job = {"type": "workid", "jobid": "work-abc", "enc": "encv", "name": "测验"}
        return cx.study_work(course, job, {"knowledgeid": 11, "cpi": "5"})

    def test_redo_until_full_marks(self):
        server = _FakeWorkServer()
        result = self._run(server)
        self.assertEqual(result, StudyResult.SUCCESS)
        last = server.submissions[-1]
        self.assertEqual((last["answerq1"], last["answerq2"]), ("B", "true"))
        # 单选 3 个选项、判断 2 个选项：最多 3 次提交必然全对
        self.assertLessEqual(len(server.submissions), 3)
        self.assertEqual(server.retests, len(server.submissions) - 1)
        # 已判定错误的答案不会再次提交；答对的题目沿用原答案
        for qid, correct in _FakeWorkServer.CORRECT.items():
            answers = [s[f"answer{qid}"] for s in server.submissions]
            wrong = [a for a in answers if a != correct]
            self.assertEqual(len(wrong), len(set(wrong)), answers)
            if correct in answers:
                self.assertTrue(all(a == correct for a in answers[answers.index(correct):]), answers)

    def test_stops_when_redo_not_allowed(self):
        server = _FakeWorkServer()

        def refuse(url, params=None, headers=None, **kwargs):
            if urlparse(url).path.endswith("/work/retest"):
                return _Resp('{"status": false, "msg": "重做次数已用完"}', url=url)
            return _FakeWorkServer.get(server, url, params=params, headers=headers)

        server.get = refuse
        # 固定首轮随机答案为错误答案，确保需要重做
        original_random = base.random_answer
        base.random_answer = lambda options, q_type: "A" if q_type == "single" else "false"
        self.addCleanup(setattr, base, "random_answer", original_random)
        result = self._run(server)
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(len(server.submissions), 1)


class AlternativeAnswerTestCase(unittest.TestCase):
    def setUp(self):
        self.cx = Chaoxing(tiku=_DummyTiku())

    def test_judgement_flips(self):
        q = {"type": "judgement", "options": ""}
        self.assertEqual(self.cx._alternative_answer(q, [True]), ("false", False))
        self.assertEqual(self.cx._alternative_answer(q, [True, False]), ("", None))

    def test_single_skips_tried_options(self):
        q = {"type": "single", "options": "A 石头\nB 苹果\nC 铁块"}
        self.assertEqual(self.cx._alternative_answer(q, [["石头"]]), ("B", ["苹果"]))
        self.assertEqual(self.cx._alternative_answer(q, [["石头"], ["苹果"]]), ("C", ["铁块"]))

    def test_multiple_tries_combinations_with_superset_hint(self):
        q = {"type": "multiple", "options": "A 甲\nB 乙\nC 丙\nD 丁"}
        self.assertEqual(self.cx._alternative_answer(q, []), ("ABCD", ["甲", "乙", "丙", "丁"]))
        letters, _ = self.cx._alternative_answer(q, [["甲", "乙", "丙", "丁"]])
        self.assertEqual(len(letters), 3)
        # 部分正确：正确答案一定包含已选的 甲、乙
        letters, answer = self.cx._alternative_answer(q, [["甲", "乙"], ["甲", "乙", "丙", "丁"]],
                                                      superset_of=frozenset(["甲", "乙"]))
        self.assertIn(letters, ("ABC", "ABD"))
        self.assertTrue({"甲", "乙"} < set(answer))


if __name__ == "__main__":
    unittest.main()
