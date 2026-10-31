import unittest
from unittest.mock import MagicMock, patch

from api.base import Chaoxing, StudyResult
from api.decode import _process_attachment_cards, _process_topic_task


class TestTopicTask(unittest.TestCase):
    def test_process_topic_card(self):
        card = {
            "type": "topic",
            "jobid": "123456",
            "property": {
                "id": "789",
                "title": "测试话题讨论",
                "content": "<p>请发表观点</p>",
                "bbsid": "bbs_111",
                "uuid": "uuid_222",
            },
        }
        res = _process_topic_task(card)
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "topic")
        self.assertEqual(res["topic_id"], "789")
        self.assertEqual(res["topic_uuid"], "uuid_222")
        self.assertEqual(res["bbsid"], "bbs_111")
        self.assertEqual(res["title"], "测试话题讨论")

    def test_attachment_cards_recognize_topic(self):
        cards = [
            {
                "type": "topic",
                "job": True,
                "jobid": "job_topic_1",
                "property": {
                    "id": "t_101",
                    "title": "课堂讨论",
                    "uuid": "u_101",
                    "bbsid": "b_101",
                },
            }
        ]
        jobs = _process_attachment_cards(cards)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["type"], "topic")

    @patch("api.base.SessionManager.get_session")
    def test_study_topic_already_replied(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<div creater_id="123456" class="reply_item">已回复</div>'
        mock_session.cookies = {"UID": "123456"}
        mock_session.get.return_value = mock_resp

        cx = Chaoxing()
        course = {"courseId": "c1", "clazzId": "cl1", "cpi": "cp1", "title": "测试课程"}
        job = {
            "type": "topic",
            "jobid": "j1",
            "title": "话题1",
            "topic_uuid": "u1",
            "bbsid": "b1",
        }
        res = cx.study_topic(course, job, {})
        self.assertEqual(res, StudyResult.SUCCESS)

    @patch("api.base.SessionManager.get_session")
    def test_study_topic_post_success(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.text = 'var urlToken = "token_xyz";'
        mock_session.get.return_value = mock_get_resp
        mock_session.cookies = {"UID": "999"}

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"status": True, "msg": "回复成功"}
        mock_session.post.return_value = mock_post_resp

        mock_tiku = MagicMock()
        mock_tiku.generate_topic_reply.return_value = "题库大模型生成的讨论回答内容"

        cx = Chaoxing(tiku=mock_tiku)
        course = {"courseId": "c1", "clazzId": "cl1", "cpi": "cp1", "title": "测试课程"}
        job = {
            "type": "topic",
            "jobid": "j1",
            "title": "话题1",
            "topic_uuid": "u1",
            "bbsid": "b1",
        }
        res = cx.study_topic(course, job, {})
        self.assertEqual(res, StudyResult.SUCCESS)
        mock_tiku.generate_topic_reply.assert_called_once()
        call_payload = mock_session.post.call_args[1]["data"]
        self.assertEqual(call_payload["topic_content"], "题库大模型生成的讨论回答内容")

    @patch("api.base.SessionManager.get_session")
    def test_study_topic_post_405_skips(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.text = '<html></html>'
        mock_session.get.return_value = mock_get_resp
        mock_session.cookies = {"UID": "999"}

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 405
        mock_session.post.return_value = mock_post_resp

        cx = Chaoxing()
        course = {"courseId": "c1", "clazzId": "cl1", "cpi": "cp1", "title": "测试课程"}
        job = {
            "type": "topic",
            "jobid": "j1",
            "title": "已过期话题",
            "topic_uuid": "u1",
            "bbsid": "b1",
        }
        res = cx.study_topic(course, job, {})
        self.assertEqual(res, StudyResult.SUCCESS)

    @patch("api.base.SessionManager.get_session")
    def test_study_topic_disabled_skips_request(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        cx = Chaoxing(topic_auto_reply=False)
        course = {"courseId": "c1", "clazzId": "cl1", "cpi": "cp1", "title": "测试课程"}
        job = {"type": "topic", "jobid": "j1", "title": "测试跳过话题"}
        res = cx.study_topic(course, job, {})
        self.assertEqual(res, StudyResult.SUCCESS)
        mock_session.get.assert_not_called()
        mock_session.post.assert_not_called()

    def test_non_llm_tiku_does_not_generate_topic_reply(self):
        from api.answer import TikuYanxi, TikuManual, AI
        yanxi = TikuYanxi()
        self.assertIsNone(yanxi.generate_topic_reply("测试话题"))
        manual = TikuManual()
        self.assertIsNone(manual.generate_topic_reply("测试话题"))

        ai_tiku = AI()
        ai_tiku.DISABLE = False
        ai_tiku._query = MagicMock(return_value="大模型针对本章节讨论议题生成的分析观点")
        with patch("api.answer.CacheDAO") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get_cache.return_value = None
            mock_cache_cls.return_value = mock_cache
            ans = ai_tiku.generate_topic_reply("测试话题")
            self.assertEqual(ans, "大模型针对本章节讨论议题生成的分析观点")

