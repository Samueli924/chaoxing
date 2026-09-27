import unittest
from unittest.mock import Mock, patch
import requests
from api.base import Chaoxing, StudyResult, MAX_END_REPORTS, _build_session
from api.runtime import runtime
from api.scheduler import process_job, process_chapter, ChapterResult, JobProcessor, ChapterTask
from api.decode import _process_video_task


class VideoEfficiencyTest(unittest.TestCase):
    def tearDown(self):
        runtime.reset()

    def simulate(self, replies, resume=599000, duration=600, speed=1, restriction=None, info=None):
        cx = Chaoxing()
        clock = [0.0]
        job = {'playTime': resume, 'doublespeed': restriction}
        with patch.object(cx, '_fetch_media_status', return_value={'status': 'success', 'duration': duration, 'dtoken': 'test'}), patch.object(cx, 'video_progress_log', side_effect=replies) as report, patch('api.base.runtime.should_stop', side_effect=lambda: clock[0] >= 120), patch('api.base.runtime.sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), patch('api.base.time.monotonic', side_effect=lambda: clock[0]), patch('api.base.SessionManager.get_session'), patch('api.base.tqdm'):
            result = cx.study_video({}, job, info or {}, _speed=speed)
        return result, report.call_args_list, clock[0]

    def test_end_confirmation_is_bounded_and_not_success(self):
        result, calls, elapsed = self.simulate(lambda *a, **k: (False, 200))
        self.assertEqual(result, StudyResult.TIMEOUT)
        self.assertEqual(len(calls), MAX_END_REPORTS + 1)
        self.assertEqual([c.kwargs['_isdrag'] for c in calls], [3, 4, 4, 4])
        self.assertLess(elapsed, 10)

    def test_success_returns_without_an_extra_sleep(self):
        result, calls, elapsed = self.simulate([(False, 200), (True, 200)])
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(elapsed, 1)

    def test_transient_error_retries_same_resume_position(self):
        result, calls, elapsed = self.simulate([requests.ReadTimeout('private'), (False, 200), (True, 200)])
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual([c.args[6] for c in calls], [599, 599, 600])

    def test_network_retry_budget_does_not_restart_video(self):
        result, calls, elapsed = self.simulate(lambda *a, **k: (_ for _ in ()).throw(requests.ReadTimeout('private')))
        self.assertEqual(result, StudyResult.TIMEOUT)
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[6] for c in calls], [599] * 3)
        self.assertEqual(elapsed, 6)

    def test_platform_restriction_caps_requested_speed(self):
        _, _, normal = self.simulate([(False, 200), (True, 200)], resume=590000)
        _, _, restricted = self.simulate([(False, 200), (True, 200)], resume=590000, speed=2, restriction='0')
        _, _, allowed = self.simulate([(False, 200), (True, 200)], resume=590000, speed=2, restriction='1')
        self.assertEqual(normal, restricted)
        self.assertLess(allowed, normal)
        self.assertEqual(_process_video_task({'mid': 'test', 'property': {'doublespeed': '0'}})['doublespeed'], '0')

    def test_video_routes_disable_transport_retries(self):
        with patch('api.base.use_cookies', return_value={}):
            session = _build_session()
        try:
            for url in ('https://mooc1.chaoxing.com/ananas/status/test', 'https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/test'):
                self.assertEqual(session.get_adapter(url).max_retries.total, 0)
            self.assertEqual(session.get_adapter('https://example.test/').max_retries.total, 5)
        finally:
            session.close()

    def test_media_failure_never_falls_back_to_another_media_type(self):
        cx = Mock()
        for result in (StudyResult.FORBIDDEN, StudyResult.TIMEOUT, StudyResult.ERROR):
            cx.study_video.reset_mock()
            cx.study_video.return_value = result
            self.assertEqual(process_job(cx, {}, {'type': 'video'}, {}, 1), result)
            cx.study_video.assert_called_once()
            self.assertEqual(cx.study_video.call_args.kwargs['_type'], 'Video')

    def test_failed_media_finalizes_once_instead_of_replaying_chapter(self):
        cx = Mock()
        point = {'title': 'test', 'id': 'test'}
        course = {'title': 'test', 'courseId': 'test'}
        cx.get_job_list.return_value = ([{'type': 'video'}], {})
        cx.study_video.return_value = StudyResult.TIMEOUT
        result = process_chapter(cx, course, point, 1)
        self.assertEqual(result, ChapterResult.BLOCKED)
        task = ChapterTask(index=0, point=point, course=course)
        processor = JobProcessor(cx, [task], {'jobs': 1})
        with patch.object(processor, '_push') as requeue:
            processor._handle_result(task, result)
        requeue.assert_not_called()
        self.assertEqual(len(processor.failed_tasks), 1)

    def test_success_report_without_fresh_card_is_not_completed(self):
        cx = Mock()
        cx.get_job_list.return_value = ([{'type': 'video', 'jobid': 'v'}], {})
        cx.study_video.return_value = StudyResult.SUCCESS
        cx.iter_card_pages.return_value = iter([(0, 'mArg = {"attachments": [{"jobid": "v", "isPassed": false}]};')])
        self.assertEqual(process_chapter(cx, {}, {'title': 'test'}, 1), ChapterResult.BLOCKED)

    def test_native_interval_uses_wall_time_even_at_double_speed(self):
        result, calls, elapsed = self.simulate([(False, 200), (True, 200)], resume=0, duration=1000, speed=2, restriction='1')
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(elapsed, 60)
        self.assertGreaterEqual(calls[-1].args[6], 118)
        self.assertEqual(calls[-1].kwargs['_isdrag'], 0)

    def test_explicit_platform_interval_is_honoured(self):
        result, calls, elapsed = self.simulate([(False, 200), (True, 200)], resume=0, duration=1000, info={'reportTimeInterval': 30})
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(elapsed, 30)

    def test_invalid_interval_uses_native_default(self):
        for interval in ('bad', -1, float('inf'), 999999):
            _, _, elapsed = self.simulate([(False, 200), (True, 200)], resume=0, duration=1000, info={'reportTimeInterval': interval})
            self.assertEqual(elapsed, 60)

    def test_false_string_completion_does_not_skip_pending_video(self):
        from api.decode import decode_course_card
        html = 'mArg = {"defaults": {"knowledgeid": "c"}, "attachments": [{"type": "video", "jobid": "v", "mid": "m", "job": true, "isPassed": "false", "property": {}}]};'
        jobs, _ = decode_course_card(html)
        self.assertEqual([job['jobid'] for job in jobs], ['v'])
