import unittest
from unittest.mock import MagicMock, patch
from api.captcha import CxCaptcha


class TestCaptchaAnd403(unittest.TestCase):
    def test_cxcaptcha_handles_404_gracefully(self):
        solver = CxCaptcha(user_agent="test_ua", cookies="k=v", ocr=None)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        solver.s.get = MagicMock(return_value=mock_resp)

        self.assertIsNone(solver.getCaptcha())
        self.assertFalse(solver.try_pass())

    @patch("api.captcha.CxCaptcha")
    def test_perform_request_skips_captcha_on_9011_forbidden(self, mock_captcha_cls):
        from api.base import Chaoxing
        cx = Chaoxing(cookies={"_uid": "1", "fid": "1"})
        cx.video_log_limiter = MagicMock()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "【9011】很抱歉，您没有权限访问这个页面！code=7"
        mock_resp.url = "https://mooc1.chaoxing.com/test"
        mock_session.get.return_value = mock_resp
        mock_session.headers = {}

        course = {"clazzId": "1", "courseId": "2", "cpi": "3"}
        job = {
            "jobid": "10",
            "objectid": "obj1",
            "otherinfo": "nodeId_1-cpi_3-rt_1",
            "rt": "1",
            "videoFaceCaptureEnc": "",
            "attDuration": 100,
            "attDurationEnc": "",
        }
        passed, status = cx.video_progress_log(
            mock_session, course, job, {}, "token", 100, 10
        )

        self.assertFalse(passed)
        self.assertEqual(status, 403)
        mock_captcha_cls.assert_not_called()

    def test_rt_switch_on_403(self):
        from api.base import Chaoxing
        cx = Chaoxing(cookies={"_uid": "1", "fid": "1"})
        cx.video_log_limiter = MagicMock()
        mock_session = MagicMock()
        mock_session.headers = {}

        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "forbidden rt mismatch"
        resp_403.url = "https://mooc1.chaoxing.com/test"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = '{"isPassed": true}'
        resp_200.json.return_value = {"isPassed": True}
        resp_200.url = "https://mooc1.chaoxing.com/test"

        mock_session.get.side_effect = [resp_403, resp_200]

        course = {"clazzId": "1", "courseId": "2", "cpi": "3"}
        job = {
            "jobid": "10",
            "objectid": "obj1",
            "otherinfo": "nodeId_1-cpi_3-rt_1",
            "rt": "1",
            "videoFaceCaptureEnc": "",
            "attDuration": 100,
            "attDurationEnc": "",
        }
        passed, status = cx.video_progress_log(
            mock_session, course, job, {}, "token", 100, 10
        )

        self.assertTrue(passed)
        self.assertEqual(status, 200)
        self.assertEqual(job["rt"], "0.9")

    def test_chaoxing_session_isolation(self):
        from api.base import Chaoxing
        cx1 = Chaoxing(cookies={})
        cx2 = Chaoxing(cookies={})
        cx1.get_session().cookies.set("user", "alice")
        cx2.get_session().cookies.set("user", "bob")
        self.assertEqual(cx1.get_session().cookies.get("user"), "alice")
        self.assertEqual(cx2.get_session().cookies.get("user"), "bob")


if __name__ == "__main__":
    unittest.main()
