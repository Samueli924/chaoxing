import unittest
from unittest.mock import Mock, patch
import requests
from api.base import Chaoxing, StudyResult, _build_session, DOCUMENT_URLS, READ_URLS, WORK_RETEST_URL
from api.runtime import runtime
from api.scheduler import process_chapter, ChapterResult, ChapterTask, JobProcessor


class ResourceCompletionTest(unittest.TestCase):
    def setUp(self):
        runtime.reset()
        self.addCleanup(runtime.reset)

    def run_finish(self, *responses):
        session = Mock()
        session.get.side_effect = responses
        with patch('api.base.SessionManager.get_session', return_value=session):
            result = Chaoxing()._finish_job_via(('primary', 'legacy'), {}, 'resource')
        return result, session

    @staticmethod
    def response(status=200, value=True):
        response = Mock(status_code=status)
        response.json.return_value = {'status': value, 'msg': 'private server text'}
        return response

    def test_false_status_never_passes(self):
        for value in (False, 'false', '0', 0, None, [], {}, 'unexpected'):
            with self.subTest(value=value):
                result, session = self.run_finish(self.response(value=value))
                self.assertEqual(result, StudyResult.ERROR)
                self.assertEqual(session.get.call_count, 1)

    def test_explicit_success_values(self):
        for value in (True, 'true', '1', 1):
            self.assertEqual(self.run_finish(self.response(value=value))[0], StudyResult.SUCCESS)

    def test_http_errors_cannot_pass_or_replay(self):
        for status in (401, 403, 429, 500):
            result, session = self.run_finish(self.response(status=status))
            self.assertTrue(result.is_failure())
            self.assertEqual(session.get.call_count, 1)

    def test_missing_route_can_use_legacy_once(self):
        result, session = self.run_finish(self.response(status=404), self.response())
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(session.get.call_count, 2)

    def test_ambiguous_response_or_timeout_does_not_replay(self):
        malformed = self.response()
        malformed.json.side_effect = ValueError('invalid JSON')
        for response in (malformed, requests.Timeout('private URL')):
            result, session = self.run_finish(response)
            self.assertTrue(result.is_failure())
            self.assertEqual(session.get.call_count, 1)

    def test_stop_prevents_request(self):
        runtime.request_stop()
        result, session = self.run_finish(self.response())
        self.assertEqual(result, StudyResult.CANCELLED)
        session.get.assert_not_called()

    def test_resource_failure_cannot_restart_chapter(self):
        for kind in ('document', 'read', 'workid'):
            cx = Mock()
            cx.get_job_list.return_value = ([{'type': kind, 'jobid': 'synthetic'}], {})
            getattr(cx, 'study_' + ('work' if kind == 'workid' else kind)).return_value = StudyResult.TIMEOUT
            self.assertEqual(process_chapter(cx, {'title': 'synthetic'}, {'title': 'synthetic'}, 1), ChapterResult.BLOCKED)

    def test_transport_does_not_retry_completion_gets(self):
        with patch('api.base.use_cookies', return_value={}):
            session = _build_session()
        self.addCleanup(session.close)
        for endpoint in (*DOCUMENT_URLS, *READ_URLS, WORK_RETEST_URL):
            self.assertEqual(session.get_adapter(endpoint + '?jobid=test').max_retries.total, 0)

    def test_failed_resource_is_not_requeued_and_downshifts(self):
        cx = Mock()
        cx.get_job_list.return_value = ([{'type': 'document', 'jobid': 'synthetic'}], {})
        cx.study_document.return_value = StudyResult.TIMEOUT
        task = ChapterTask(index=0, point={'title': 'synthetic'},
                           course={'title': 'synthetic', 'courseId': 'c', 'clazzId': 'z'})
        processor = JobProcessor(cx, [task], {'jobs': 2, 'speed': 1, 'interactive': False})
        processor.run()
        cx.study_document.assert_called_once()
        self.assertIn(task, processor.failed_tasks)
        self.assertEqual(processor.concurrency_limit, 1)
        self.assertEqual(processor.pending_count, 0)
