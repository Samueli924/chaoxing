import errno
import gzip
import json
import os
import shutil
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests
from urllib3.exceptions import NewConnectionError, MaxRetryError
from api.transport import CurlAdapter, CompatibleHTTPAdapter, _connect_bad_fd


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/result')
            self.send_header('Set-Cookie', 'first=one; Path=/')
            self.send_header('Set-Cookie', 'second=two; Path=/')
            self.end_headers()
            return
        payload = json.dumps({'method': 'GET', 'cookie': self.headers.get('Cookie', '')}).encode()
        if self.path == '/gzip':
            payload = gzip.compress(payload)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        if self.path == '/gzip':
            self.send_header('Content-Encoding', 'gzip')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/post-redirect':
            self.send_response(303)
            self.send_header('Location', '/result')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps({'body': body.decode(), 'cookie': self.headers.get('Cookie', '')}).encode())


@unittest.skipUnless(shutil.which('curl'), 'system curl required')
class CurlRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def setUp(self):
        self.s = requests.Session(); self.s.trust_env = False
        self.s.mount('http://', CurlAdapter())
        self.addCleanup(self.s.close)

    def test_redirect_and_multiple_cookies(self):
        r = self.s.get(self.url + '/redirect', timeout=2)
        self.assertEqual(len(r.history), 1)
        self.assertIn('first=one', r.json()['cookie'])
        self.assertIn('second=two', r.json()['cookie'])
        self.assertEqual(len(self.s.cookies), 2)

    def test_encoded_post_and_cookie_readback(self):
        self.s.get(self.url + '/redirect', timeout=2)
        r = self.s.post(self.url + '/echo', data={'answer': '中文 & + " \\ \n'}, timeout=2)
        self.assertEqual(r.json()['body'], requests.Request('POST', self.url, data={'answer': '中文 & + " \\ \n'}).prepare().body)
        self.assertIn('second=two', r.json()['cookie'])

    def test_utf8_json_and_config_escaping(self):
        body = '@literal\nurl = "https://invalid.example"\n中文'
        r = self.s.post(self.url + '/echo', data=body.encode(), timeout=2)
        self.assertEqual(r.json()['body'], body)

    def test_post_redirect_changes_method(self):
        r = self.s.post(self.url + '/post-redirect', data={'a': 'b'}, timeout=2)
        self.assertEqual(r.json()['method'], 'GET')

    def test_gzip(self):
        self.assertEqual(self.s.get(self.url + '/gzip', timeout=2).json()['method'], 'GET')


class TransportFailureTest(unittest.TestCase):
    def request(self):
        return requests.Request('POST', 'https://example.test/?private=value', data={'secret': 'private'}).prepare()

    def test_secrets_not_in_arguments(self):
        response = subprocess.CompletedProcess([], 0, b'HTTP/1.1 200 OK\r\n\r\nok', b'')
        with patch('api.transport.shutil.which', return_value='/usr/bin/curl'), patch('api.transport.subprocess.run', return_value=response) as run:
            CurlAdapter().send(self.request(), timeout=1)
        self.assertEqual(run.call_args.args[0], ['/usr/bin/curl', '--disable', '--config', '-'])
        self.assertIn(b'secret=private', run.call_args.kwargs['input'])

    def test_timeout_and_stderr_redaction(self):
        with patch('api.transport.shutil.which', return_value='curl'), patch('api.transport.subprocess.run', return_value=subprocess.CompletedProcess([], 28, b'', b'private=value')):
            with self.assertRaises(requests.Timeout) as caught:
                CurlAdapter().send(self.request(), timeout=1)
        self.assertNotIn('private', str(caught.exception))

    def test_tls_verification_cannot_be_disabled(self):
        with self.assertRaises(ValueError):
            CurlAdapter().send(self.request(), verify=False)

    def test_only_preconnect_bad_fd_can_fallback(self):
        reason = NewConnectionError(None, 'failed')
        reason.__cause__ = OSError(errno.EBADF, 'bad descriptor')
        error = requests.ConnectionError(MaxRetryError(None, '/private', reason))
        self.assertTrue(_connect_bad_fd(error))
        with patch.dict(os.environ, {'CHAOXING_HTTP_TRANSPORT': 'auto'}):
            adapter = CompatibleHTTPAdapter()
        with patch('requests.adapters.HTTPAdapter.send', side_effect=error), patch.object(adapter._curl, 'send', return_value='ok') as fallback:
            self.assertEqual(adapter.send(self.request()), 'ok')
            fallback.assert_called_once()
        for error in [requests.ConnectionError('connection reset'), requests.ReadTimeout('read timed out'), requests.ConnectionError(OSError(errno.EBADF, 'after send'))]:
            with patch.dict(os.environ, {'CHAOXING_HTTP_TRANSPORT': 'auto'}):
                adapter = CompatibleHTTPAdapter()
            with patch('requests.adapters.HTTPAdapter.send', side_effect=error), patch.object(adapter._curl, 'send') as fallback:
                with self.assertRaises(type(error)):
                    adapter.send(self.request())
                fallback.assert_not_called()

    def test_requests_mode_disables_fallback(self):
        reason = NewConnectionError(None, 'failed'); reason.__cause__ = OSError(errno.EBADF, 'bad descriptor')
        with patch.dict(os.environ, {'CHAOXING_HTTP_TRANSPORT': 'requests'}):
            adapter = CompatibleHTTPAdapter()
        with patch('requests.adapters.HTTPAdapter.send', side_effect=requests.ConnectionError(reason)), patch.object(adapter._curl, 'send') as fallback:
            with self.assertRaises(requests.ConnectionError):adapter.send(self.request())
            fallback.assert_not_called()


class VideoResumeTest(unittest.TestCase):
    def test_start_reports_resume_position_not_duration(self):
        from api.base import Chaoxing, StudyResult
        cx = Chaoxing()
        with patch.object(cx, '_fetch_media_status', return_value={'status': 'success', 'duration': 600, 'dtoken': 'test'}), patch.object(cx, 'video_progress_log', return_value=(False, 200)) as report, patch('api.base.runtime.should_stop', return_value=True), patch('api.base.SessionManager.get_session'):
            result = cx.study_video({'courseId': 'test'}, {'jobid': 'test', 'playTime': 12000}, {})
        self.assertEqual(result, StudyResult.CANCELLED)
        self.assertEqual(report.call_args.args[5:7], (600, 12))
        self.assertEqual(report.call_args.kwargs['_isdrag'], 3)

    def test_resumed_video_reports_progress_before_time_limit(self):
        from api.base import Chaoxing, StudyResult
        cx = Chaoxing()
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        with patch.object(cx, '_fetch_media_status', return_value={'status': 'success', 'duration': 1000, 'dtoken': 'test'}), patch.object(cx, 'video_progress_log', return_value=(False, 200)) as report, patch('api.base.runtime.should_stop', side_effect=lambda: clock[0] >= 70), patch('api.base.runtime.sleep', side_effect=sleep), patch('api.base.time.monotonic', side_effect=lambda: clock[0]), patch('api.base.SessionManager.get_session'), patch('api.base.tqdm'):
            result = cx.study_video({'courseId': 'test'}, {'jobid': 'test', 'playTime': 822000}, {})
        self.assertEqual(result, StudyResult.CANCELLED)
        positions = [call.args[6] for call in report.call_args_list]
        self.assertEqual(positions, [822, 882])
        self.assertEqual([call.kwargs['_isdrag'] for call in report.call_args_list], [3, 0])

    def test_initial_forbidden_does_not_start_playback(self):
        from api.base import Chaoxing, StudyResult
        cx = Chaoxing()
        with patch.object(cx, '_fetch_media_status', return_value={'status': 'success', 'duration': 600, 'dtoken': 'test'}), patch.object(cx, 'video_progress_log', return_value=(False, 403)) as report, patch('api.base.runtime.sleep') as sleep, patch('api.base.SessionManager.get_session'):
            result = cx.study_video({}, {'playTime': 12000}, {})
        self.assertEqual(result, StudyResult.FORBIDDEN)
        report.assert_called_once()
        sleep.assert_not_called()

    def test_reached_end_sends_completion_event(self):
        from api.base import Chaoxing, StudyResult
        cx = Chaoxing()
        clock = [0.0]
        with patch.object(cx, '_fetch_media_status', return_value={'status': 'success', 'duration': 600, 'dtoken': 'test'}), patch.object(cx, 'video_progress_log', side_effect=[(False, 200), (True, 200)]) as report, patch('api.base.runtime.should_stop', return_value=False), patch('api.base.runtime.sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)), patch('api.base.time.monotonic', side_effect=lambda: clock[0]), patch('api.base.SessionManager.get_session'), patch('api.base.tqdm'):
            result = cx.study_video({}, {'playTime': 599000}, {})
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual([call.kwargs['_isdrag'] for call in report.call_args_list], [3, 4])
        self.assertEqual(report.call_args.args[6], 600)

    def test_end_bookmark_does_not_claim_watched_completion(self):
        from api.base import Chaoxing, StudyResult
        cx = Chaoxing()
        with patch.object(cx, '_fetch_media_status', return_value={'status': 'success', 'duration': 600, 'dtoken': 'test'}), patch.object(cx, 'video_progress_log', return_value=(False, 200)) as report, patch('api.base.runtime.should_stop', return_value=True), patch('api.base.SessionManager.get_session'):
            result = cx.study_video({}, {'playTime': 600000}, {})
        self.assertEqual(result, StudyResult.CANCELLED)
        self.assertEqual(report.call_args.args[6], 0)
