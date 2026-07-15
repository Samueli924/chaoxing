import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from requests import RequestException

from api.answer import CacheDAO
from api.base import (
    Account,
    Chaoxing,
    SessionManager,
    StudyResult,
    build_work_submit_form,
    split_completion_answer,
)
from api.exceptions import LoginError


class SessionManagerTests(unittest.TestCase):
    def setUp(self):
        instance = SessionManager._instance
        if instance is not None and hasattr(instance, "_session"):
            instance._session.close()
        SessionManager._instance = None

    def tearDown(self):
        instance = SessionManager._instance
        if instance is not None and hasattr(instance, "_session"):
            instance._session.close()
        SessionManager._instance = None

    def test_get_session_reuses_session_and_preserves_cookies(self):
        first = SessionManager.get_session()
        first.cookies.set("test-cookie", "kept")

        second = SessionManager.get_session()

        self.assertIs(first, second)
        self.assertEqual(second.cookies.get("test-cookie"), "kept")


class WorkSubmitFormTests(unittest.TestCase):
    @staticmethod
    def _questions(answer, *, py_flag="", source="cover", type_code="2", blank_count="2"):
        return {
            "pyFlag": py_flag,
            "tiankongsize42": blank_count,
            "questions": [
                {
                    "id": "42",
                    "type": "completion",
                    "answerField": {
                        "answer42": answer,
                        "answertype42": type_code,
                    },
                    "answerSource42": source,
                }
            ],
        }

    def test_split_completion_answer_supports_newlines_hashes_and_lists(self):
        self.assertEqual(split_completion_answer("first\nsecond"), ["first", "second"])
        self.assertEqual(
            split_completion_answer("first # second#third", expected_count=3),
            ["first", "second", "third"],
        )
        self.assertEqual(split_completion_answer(["first", "second"]), ["first", "second"])

    def test_completion_uses_editor_fields_in_submit_mode(self):
        payload = build_work_submit_form(self._questions("first\nsecond"))

        self.assertNotIn("questions", payload)
        self.assertNotIn("answer42", payload)
        self.assertEqual(payload["answerEditor421"], "first")
        self.assertEqual(payload["answerEditor422"], "second")
        self.assertEqual(payload["tiankongsize42"], 2)
        self.assertEqual(payload["answertype42"], "2")

    def test_completion_uses_hash_delimiter_and_type_code_10(self):
        payload = build_work_submit_form(
            self._questions("one#two#three", type_code="10", blank_count="3")
        )

        self.assertEqual(payload["answerEditor421"], "one")
        self.assertEqual(payload["answerEditor422"], "two")
        self.assertEqual(payload["answerEditor423"], "three")
        self.assertEqual(payload["tiankongsize42"], 3)

    def test_save_mode_does_not_persist_random_completion_answer(self):
        payload = build_work_submit_form(
            self._questions("guessed", py_flag="1", source="random", blank_count="2")
        )

        self.assertEqual(payload["answerEditor421"], "")
        self.assertEqual(payload["answerEditor422"], "")
        self.assertEqual(payload["tiankongsize42"], 2)

    def test_single_blank_preserves_hash_characters(self):
        payload = build_work_submit_form(
            self._questions("C# and foo#bar", blank_count="1")
        )

        self.assertEqual(payload["answerEditor421"], "C# and foo#bar")
        self.assertEqual(payload["tiankongsize42"], 1)


class CacheLockTests(unittest.TestCase):
    def test_cache_instances_share_the_same_process_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cache.json"
            first = CacheDAO(str(cache_path))
            second = CacheDAO(str(cache_path))

            self.assertIs(first._lock, second._lock)


class StudyWorkTests(unittest.TestCase):
    @patch("api.base.decode_questions_info")
    @patch("api.base.SessionManager.get_session")
    def test_completion_payload_is_used_and_failed_score_is_propagated(
        self, get_session, decode_questions
    ):
        session = Mock()
        page_response = Mock(status_code=200, text="work page")
        submit_response = Mock(status_code=200)
        submit_response.json.return_value = {
            "status": True,
            "msg": "success!",
            "stuStatus": 5,
        }
        session.get.return_value = page_response
        session.post.return_value = submit_response
        get_session.return_value = session

        decode_questions.return_value = {
            "pyFlag": "",
            "tiankongsize42": "2",
            "questions": [
                {
                    "id": "42",
                    "title": "Fill in",
                    "options": "",
                    "type": "completion",
                    "answerField": {"answer42": "", "answertype42": "2"},
                }
            ],
        }

        tiku = Mock(DISABLE=False, COVER_RATE=0)
        tiku.query.return_value = "first#second"
        tiku.get_submit_params.return_value = ""
        chaoxing = Chaoxing(Account("user", "password"), tiku, query_delay=0)

        result = chaoxing.study_work(
            {"clazzId": "1", "courseId": "2"},
            {"jobid": "work-3", "enc": "enc"},
            {"knowledgeid": "4", "ktoken": "k", "cpi": "5"},
        )

        self.assertEqual(result, StudyResult.ERROR)
        payload = session.post.call_args.kwargs["data"]
        self.assertNotIn("answer42", payload)
        self.assertEqual(payload["answerEditor421"], "first")
        self.assertEqual(payload["answerEditor422"], "second")
        self.assertEqual(payload["tiankongsize42"], 2)


class CoursePointTests(unittest.TestCase):
    @patch("api.base.SessionManager.get_session")
    def test_course_point_http_error_is_explicit(self, get_session):
        get_session.return_value.get.return_value = Mock(status_code=500, text="error")
        chaoxing = Chaoxing(Account("user", "password"), Mock())

        with self.assertRaises(RequestException):
            chaoxing.get_course_point("1", "2", "3")

    @patch("api.base.SessionManager.get_session")
    def test_course_point_login_page_is_explicit(self, get_session):
        get_session.return_value.get.return_value = Mock(
            status_code=200,
            text='<form action="https://passport2.chaoxing.com/fanyalogin"></form>',
        )
        chaoxing = Chaoxing(Account("user", "password"), Mock())

        with self.assertRaises(LoginError):
            chaoxing.get_course_point("1", "2", "3")

    @patch("api.base.SessionManager.get_session")
    def test_course_point_empty_parse_is_not_success(self, get_session):
        get_session.return_value.get.return_value = Mock(
            status_code=200, text="<html><body>unexpected response</body></html>"
        )
        chaoxing = Chaoxing(Account("user", "password"), Mock())

        with self.assertRaises(ValueError):
            chaoxing.get_course_point("1", "2", "3")


if __name__ == "__main__":
    unittest.main()
