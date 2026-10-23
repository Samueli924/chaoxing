"""视频续播位置与任务完成状态的回归测试"""
import unittest
from itertools import count
from unittest.mock import Mock, patch

from api.base import Chaoxing, StudyResult
from api.decode import decode_course_card


class VideoProgressTest(unittest.TestCase):
    def setUp(self):
        self.chaoxing = Chaoxing.__new__(Chaoxing)
        self.chaoxing.get_fid = Mock(return_value="test-fid")
        self.session = Mock()
        self.session.get.return_value.json.return_value = {
            "status": "success",
            "duration": 663,
            "dtoken": "test-token",
            "crc": "test-crc",
            "key": "test-key",
        }
        self.job = {"name": "12.13.mp4", "objectid": "test-object", "playTime": 0}

    def _study(self):
        with (
            patch("api.base.SessionManager.get_session", return_value=self.session),
            patch("api.base.tqdm"),
            patch("api.base.time.sleep"),
            patch("api.base.time.time", side_effect=count()),
            patch("api.base.random.uniform", return_value=30),
        ):
            return self.chaoxing.study_video({}, self.job, {})

    def test_initial_report_matches_official_resume_position(self):
        cases = ((0, 0), (120000, 120), (662999, 662), (663000, 0), (800000, 0), ("663000", 0))
        for position_ms, expected_seconds in cases:
            with self.subTest(position_ms=position_ms):
                self.job["playTime"] = position_ms
                report = Mock(return_value=(True, 200))
                self.chaoxing.video_progress_log = report

                self.assertEqual(self._study(), StudyResult.SUCCESS)
                self.assertEqual(report.call_count, 1)
                self.assertEqual(report.call_args.args[5:7], (663, expected_seconds))
                self.assertNotEqual(report.call_args.kwargs.get("_isdrag"), 4)

    def test_end_position_does_not_imply_completion(self):
        self.job["playTime"] = 663000
        report = Mock(side_effect=[(False, 200), (True, 200)])
        self.chaoxing.video_progress_log = report

        self.assertEqual(self._study(), StudyResult.SUCCESS)
        self.assertEqual(report.call_count, 2)
        self.assertEqual(report.call_args_list[0].args[6], 0)
        self.assertGreater(report.call_args_list[1].args[6], 0)
        self.assertLess(report.call_args_list[1].args[6], 663)

    def test_initial_report_failure_is_not_ignored(self):
        self.chaoxing.video_progress_log = Mock(return_value=(False, 500))

        self.assertEqual(self._study(), StudyResult.ERROR)
        self.chaoxing.video_progress_log.assert_called_once()

    def test_initial_forbidden_response_recovers_before_retry(self):
        self.job["playTime"] = 120000
        self.chaoxing.video_progress_log = Mock(side_effect=[(False, 403), (True, 200)])
        recover = Mock(return_value={"dtoken": "refreshed-token", "duration": 663})
        self.chaoxing._recover_after_forbidden = recover

        self.assertEqual(self._study(), StudyResult.SUCCESS)
        recover.assert_called_once_with(self.session, self.job, "Video")
        retry_args = self.chaoxing.video_progress_log.call_args.args
        self.assertEqual(retry_args[4], "refreshed-token")
        self.assertEqual(retry_args[6], 120)

    def test_recovered_progress_uses_milliseconds_and_official_end_rule(self):
        for position_ms, expected_seconds in ((45000, 45), (663000, 0)):
            with self.subTest(position_ms=position_ms):
                self.chaoxing.video_progress_log = Mock(side_effect=[(False, 403), (True, 200)])
                self.chaoxing._recover_after_forbidden = Mock(return_value={
                    "dtoken": "refreshed-token", "duration": 663, "playTime": position_ms,
                })

                self.assertEqual(self._study(), StudyResult.SUCCESS)
                self.assertEqual(self.chaoxing.video_progress_log.call_args.args[6], expected_seconds)

    def test_recovery_reports_reset_position_after_an_earlier_successful_report(self):
        """已有上报记录时，403 恢复后也应立即上报重置后的续播位置"""
        for position_ms in (0, 663000):
            with self.subTest(position_ms=position_ms):
                self.job["playTime"] = 120000
                report = Mock(side_effect=[(False, 200), (False, 403), (True, 200)])
                self.chaoxing.video_progress_log = report
                recover = Mock(return_value={
                    "dtoken": "refreshed-token", "duration": 663, "playTime": position_ms,
                })
                self.chaoxing._recover_after_forbidden = recover

                self.assertEqual(self._study(), StudyResult.SUCCESS)
                recover.assert_called_once_with(self.session, self.job, "Video")
                self.assertEqual(report.call_count, 3)
                self.assertEqual(report.call_args_list[0].args[6], 120)
                self.assertGreaterEqual(report.call_args_list[1].args[6], 150)
                self.assertEqual(report.call_args_list[2].args[4], "refreshed-token")
                self.assertEqual(report.call_args_list[2].args[6], 0)

    def test_unpassed_card_at_end_remains_a_pending_job(self):
        html = 'mArg={"attachments":[{"type":"video","job":true,"mid":"test-mid",'
        html += '"isPassed":false,"playTime":663000,"headOffset":663000,'
        html += '"property":{"name":"12.13.mp4"}}]};'

        jobs, _ = decode_course_card(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["playTime"], 663000)


if __name__ == "__main__":
    unittest.main()
