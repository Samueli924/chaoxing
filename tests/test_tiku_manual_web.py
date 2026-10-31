import unittest
from unittest.mock import patch
from api.answer import TikuManual
from api.task_runner import TaskStateHub


class TestTikuManualWeb(unittest.TestCase):
    def setUp(self):
        self.hub = TaskStateHub()
        self.hub.set_web_mode(True)
        self.tiku = TikuManual()

    def tearDown(self):
        self.hub.set_web_mode(False)

    @patch("api.task_runner.TaskStateHub.request_manual_answer")
    def test_single_query_delegates_to_hub_in_web_mode(self, mock_request):
        mock_request.return_value = "A"
        q = {
            "title": "下列哪个是协议？",
            "type": "single",
            "options": ["A. HTTP", "B. CPU"]
        }
        ans = self.tiku._single_query(q)
        self.assertEqual(ans, "A")
        mock_request.assert_called_once()

    @patch("api.task_runner.TaskStateHub.request_manual_answer")
    def test_single_query_handles_skip_in_web_mode(self, mock_request):
        mock_request.return_value = None
        q = {
            "title": "难题跳过",
            "type": "single",
            "options": ["A. 1", "B. 2"]
        }
        ans = self.tiku._single_query(q)
        self.assertIsNone(ans)

    def test_base_tiku_query_all_is_manual_mode_property(self):
        from api.answer import Tiku
        class DummyTiku(Tiku):
            def _query(self, q_info):
                return "A"
        dummy = DummyTiku()
        res = dummy._query_all([{"title": "测试题目1", "type": "single"}])
        self.assertEqual(res, ["A"])
