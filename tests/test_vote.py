import unittest
from unittest.mock import MagicMock, patch

from api.base import Chaoxing, StudyResult
from api.decode import _process_attachment_cards, _process_vote_task

_VOTE_HTML = """
<script>
var questionlist = [{'answer':[{'name':'A','content':'\\u662F'},{'name':'B','content':'\\u5426'}],'content':'\\u53D9\\u4E8B\\u6027\\u9996\\u9970\\u662F\\u5728\\u8BB2\\u6545\\u4E8B\\u5417','haveAnswer':false,'id':5000081433064,'type':0,'ismust':None}];
var questionhtml = init(questionlist);
</script>
"""

_ANSWERED_HTML = """
<script>
var questionlist = [{'answer':[{'name':'A','content':'\\u662F'},{'name':'B','content':'\\u5426'}],'content':'\\u9898\\u76EE','haveAnswer':true,'id':5000081433064,'type':0}];
var questionhtml = init(questionlist);
</script>
"""


class TestVoteTask(unittest.TestCase):
    def test_process_vote_card(self):
        card = {
            "type": "vote",
            "jobid": "1708075980862804",
            "jtoken": "417aa8672b75b0e15c16f68994093cc0",
            "otherInfo": "nodeId_1195051747-cpi_513340956",
            "property": {
                "id": "5000167075899",
                "module": "insertvote",
                "title": "叙事性首饰是在讲故事吗",
                "mid": "4032610145671708075980865",
            },
            "mid": "4032610145671708075980865",
            "aid": 2331108443,
        }
        res = _process_vote_task(card)
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "vote")
        self.assertEqual(res["active_id"], "5000167075899")
        self.assertEqual(res["jobid"], "1708075980862804")
        self.assertEqual(res["jtoken"], "417aa8672b75b0e15c16f68994093cc0")
        self.assertEqual(res["title"], "叙事性首饰是在讲故事吗")

    def test_attachment_cards_recognize_vote(self):
        cards = [
            {
                "type": "vote",
                "job": True,
                "jobid": "job_vote_1",
                "property": {
                    "id": "5000167075899",
                    "module": "insertvote",
                    "title": "投票题",
                },
            }
        ]
        jobs = _process_attachment_cards(cards)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["type"], "vote")

    @patch("api.base.SessionManager.get_session")
    def test_study_vote_submit(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = _VOTE_HTML
        get_resp.url = "https://mobilelearn.chaoxing.com/widget/chaptervote/goChapterSubmit?activeId=5000167075899"
        mock_session.get.return_value = get_resp
        mock_session.cookies = {"UID": "419769884"}

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"isresult": 0}
        mock_session.post.return_value = post_resp

        cx = Chaoxing()
        course = {"courseId": "265467268", "clazzId": "152196416", "cpi": "513340956", "title": "饰品设计与制作"}
        job = {
            "type": "vote",
            "jobid": "1708075980862804",
            "jtoken": "417aa8672b75b0e15c16f68994093cc0",
            "otherinfo": "nodeId_1195051747-cpi_513340956",
            "active_id": "5000167075899",
            "title": "叙事性首饰是在讲故事吗",
        }
        res = cx.study_vote(course, job, {})
        self.assertEqual(res, StudyResult.SUCCESS)

        post_call = mock_session.post.call_args
        self.assertIn("doQuestion", post_call[0][0])
        payload = post_call[1]["data"]
        self.assertEqual(payload["activeId"], "5000167075899")
        self.assertEqual(payload["questionId"], "5000081433064")
        self.assertIn("answer5000081433064", payload)

    @patch("api.base.SessionManager.get_session")
    def test_study_vote_already_answered_skips_submit(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = _ANSWERED_HTML
        get_resp.url = "https://mobilelearn.chaoxing.com/widget/chaptervote/goChapterSubmit"
        mock_session.get.return_value = get_resp

        cx = Chaoxing()
        course = {"courseId": "c1", "clazzId": "cl1", "cpi": "cp1"}
        job = {"type": "vote", "jobid": "j1", "active_id": "a1", "title": "已答题"}
        res = cx.study_vote(course, job, {})
        self.assertEqual(res, StudyResult.SUCCESS)
        mock_session.post.assert_not_called()

    @patch("api.base.SessionManager.get_session")
    def test_study_vote_network_error_returns_error(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.side_effect = RuntimeError("network down")

        cx = Chaoxing()
        course = {"courseId": "c1", "clazzId": "cl1", "cpi": "cp1"}
        job = {"type": "vote", "jobid": "j1", "active_id": "a1", "title": "异常"}
        res = cx.study_vote(course, job, {})
        self.assertEqual(res, StudyResult.ERROR)


if __name__ == "__main__":
    unittest.main()
