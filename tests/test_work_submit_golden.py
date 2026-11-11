# -*- coding: utf-8 -*-
"""章节检测作答与提交的对照测试：固定题目和题库答案，检查提交给学习通的表单内容."""
import copy
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api.base as base  # noqa: E402
from api.base import Chaoxing, StudyResult  # noqa: E402


def q(qid, qtype, code, options, title="题目"):
    return {"id": qid, "title": title, "options": options, "type": qtype,
            "answerField": {f"answer{qid}": "", f"answertype{qid}": code}}


QUESTIONS = {
    "courseId": "111", "classId": "222", "workAnswerId": "444", "pyFlag": "",
    "questions": [
        q("1", "single", "0", "A 2dx\nB 6dx\nC 8dx\nD 12dx"),
        q("2", "single", "0", "A10\nB0\nC4\nD8"),
        q("3", "single", "0", 'A<img src="/a.png">\nB<img src="/b.png">\nC<img src="/c.png">'),
        q("4", "multiple", "1", "A二项分布\nB泊松分布\nC正态分布\nD几何分布"),
        q("5", "multiple", "1", "A甲\nB乙\nC丙"),
        q("6", "judgement", "3", ""),
        q("7", "completion", "2", ""),
        q("8", "single", "0", "A苹果\nB香蕉"),
        q("9", "single", "0", "A苹果\nB香蕉"),
    ],
}
ANSWERS = ["6dx", "0", "B", "二项分布\n泊松分布\n几何分布", "B.\nC.", "正确", "辩证唯物主义", "完全无关的答案", None]


class FakeSession:
    def __init__(self, page_text):
        """记录作答页内容和提交过的表单."""
        self.page_text = page_text
        self.posts = []

    def get(self, url, params=None, timeout=None, **kw):
        return SimpleNamespace(text=self.page_text, status_code=200, url=url)

    def post(self, url, data=None, headers=None, **kw):
        self.posts.append(copy.deepcopy(data))
        return SimpleNamespace(status_code=200, json=lambda: {"status": True, "msg": "success"}, text="")


class GoldenSubmitTest(unittest.TestCase):
    def run_once(self, submit="", rollback=0, cover=0.9):
        tiku = mock.Mock(DISABLE=False, COVER_RATE=cover)
        tiku.query_all.return_value = list(ANSWERS)
        tiku.get_submit_params.return_value = submit
        tiku.judgement_select.side_effect = lambda r: r in ("正确", "对", "true")
        tiku.is_manual = False
        cx = Chaoxing(tiku=tiku)
        cx.rollback_times = rollback
        session = FakeSession("<html>作答页</html>")
        course = {"courseId": "111", "clazzId": "222", "cpi": "666", "title": "课程"}
        job = {"jobid": "work-333", "enc": "abc", "name": "章节测验"}
        job_info = {"knowledgeid": "555", "ktoken": "t", "cpi": "666"}
        with mock.patch.object(base.SessionManager, "get_session", return_value=session), \
                mock.patch.object(base, "decode_questions_info", return_value=copy.deepcopy(QUESTIONS)), \
                mock.patch.object(base.Chaoxing, "_check_work_result", return_value=None), \
                mock.patch.object(base, "random_answer", side_effect=lambda opts, t: "RANDOM"), \
                mock.patch.object(base.time, "sleep"):
            result = cx.study_work(course, job, job_info)
        return result, session.posts

    def answers_of(self, form):
        return {k: v for k, v in form.items() if k.startswith("answer") and not k.startswith("answertype")
                and k != "answerwqbid"}

    def test_submitted_form(self):
        result, posts = self.run_once()
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(len(posts), 1)
        form = posts[0]
        self.assertEqual(form["pyFlag"], "1")  # 9 题中 2 题随机，覆盖率 78% < 90%，只保存
        self.assertEqual(self.answers_of(form), {
            "answer1": "B", "answer2": "B", "answer3": "B", "answer4": "ABD", "answer5": "BC",
            "answer6": "true", "answer7": "辩证唯物主义", "answer8": "", "answer9": "",
        })
        self.assertEqual(form["answertype4"], "1")
        self.assertNotIn("questions", form)
        self.assertEqual(form["courseId"], "111")

    def test_submit_when_cover_rate_reached(self):
        _, posts = self.run_once(cover=0.7)
        form = posts[0]
        self.assertEqual(form["pyFlag"], "")
        self.assertEqual(form["answer8"], "RANDOM")  # 提交时随机作答的题也一并提交
        self.assertEqual(form["answer9"], "RANDOM")

    def test_save_only_mode(self):
        _, posts = self.run_once(submit="1", cover=0.5)
        self.assertEqual(posts[0]["pyFlag"], "1")

    def test_rollback_forces_submit(self):
        _, posts = self.run_once(rollback=1)
        self.assertEqual(posts[0]["pyFlag"], "")


if __name__ == "__main__":
    unittest.main()
