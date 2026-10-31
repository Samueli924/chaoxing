import unittest
from unittest.mock import MagicMock, patch

from main import parse_args


class TestCliWebFlag(unittest.TestCase):
    def test_webui_flag_default(self):
        args = parse_args([])
        self.assertFalse(args.webui)

    def test_webui_flag_enabled(self):
        args = parse_args(["--webui"])
        self.assertTrue(args.webui)
        self.assertEqual(args.port, 5000)

    def test_custom_port(self):
        args = parse_args(["--webui", "--port", "8080", "--host", "0.0.0.0"])
        self.assertTrue(args.webui)
        self.assertEqual(args.port, 8080)
        self.assertEqual(args.host, "0.0.0.0")

    def test_unicode_em_dash_tolerance(self):
        args1 = parse_args(["—-webui"])
        self.assertTrue(args1.webui)
        args2 = parse_args(["—webui"])
        self.assertTrue(args2.webui)

    @patch("main.Tiku.get_tiku_from_config")
    def test_init_chaoxing_boolean_check_llm(self, mock_get_tiku):
        from main import init_chaoxing
        mock_tiku_inst = MagicMock()
        mock_tiku_inst.check_llm_connection.return_value = True
        mock_get_tiku.return_value = mock_tiku_inst

        common_config = {
            "username": "13800000000",
            "password": "pwd",
            "use_cookies": False,
            "daily_watch_limit_minutes": 45,
            "topic_auto_reply": False,
            "topic_reply_content": "自定义讨论内容",
        }
        tiku_config = {"provider": "AI", "check_llm_connection": True}
        cx = init_chaoxing(common_config, tiku_config)
        self.assertIsNotNone(cx)
        mock_tiku_inst.check_llm_connection.assert_called_once()
        self.assertEqual(cx.kwargs.get("daily_watch_limit_minutes"), 45)
        self.assertFalse(cx.kwargs.get("topic_auto_reply"))
        self.assertEqual(cx.kwargs.get("topic_reply_content"), "自定义讨论内容")
