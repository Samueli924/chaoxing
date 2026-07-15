import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import main
from api.base import StudyResult
from api.exceptions import InputFormatError


class CourseFilterTests(unittest.TestCase):
    def test_unknown_course_id_does_not_fall_back_to_all_courses(self):
        courses = [
            {"courseId": "101", "clazzId": "1", "title": "First"},
            {"courseId": "202", "clazzId": "2", "title": "Second"},
        ]

        with self.assertRaises(InputFormatError):
            main.filter_courses(courses, ["missing"])

    def test_explicit_all_marker_keeps_all_courses(self):
        courses = [
            {"courseId": "101", "clazzId": "1", "title": "First"},
            {"courseId": "202", "clazzId": "2", "title": "Second"},
        ]

        self.assertEqual(main.filter_courses(courses, ["*"]), courses)

    def test_empty_course_selection_requires_explicit_all_marker(self):
        courses = [{"courseId": "101", "clazzId": "1", "title": "First"}]

        with self.assertRaises(InputFormatError):
            main.filter_courses(courses, [""])


class JobProcessorTests(unittest.TestCase):
    @staticmethod
    def _processor(notopen_action="retry"):
        task = main.ChapterTask(index=0, point={"id": "1", "title": "Chapter", "has_finished": False})
        processor = main.JobProcessor(
            Mock(),
            {"title": "Course"},
            [task],
            {"jobs": 1, "speed": 1.0, "notopen_action": notopen_action},
        )
        processor.retry_delay = 0
        return processor, task

    @patch("main.process_chapter", return_value=main.ChapterResult.NOT_OPEN)
    def test_not_open_retry_is_bounded_and_reported(self, process_chapter):
        processor, task = self._processor()
        processor.max_tries = 3

        self.assertFalse(processor.run())
        self.assertEqual(process_chapter.call_count, 3)
        self.assertEqual(task.tries, 3)
        self.assertEqual(processor.failed_tasks, [task])

    @patch("main.process_chapter", side_effect=RuntimeError("boom"))
    def test_worker_exception_is_retried_without_deadlocking(self, process_chapter):
        processor, task = self._processor()
        processor.max_tries = 2

        self.assertFalse(processor.run())
        self.assertEqual(process_chapter.call_count, 2)
        self.assertEqual(processor.failed_tasks, [task])

    @patch("main.process_chapter", return_value=main.ChapterResult.SUCCESS)
    def test_successful_run_returns_true(self, process_chapter):
        processor, _ = self._processor()

        self.assertTrue(processor.run())
        process_chapter.assert_called_once()

    def test_retried_task_is_not_processed_concurrently(self):
        processor, _ = self._processor()
        processor.worker_num = 2
        processor.max_tries = 2
        state_lock = threading.Lock()
        calls = 0
        active = 0
        max_active = 0

        def fake_process(*args):
            nonlocal calls, active, max_active
            with state_lock:
                calls += 1
                active += 1
                max_active = max(max_active, active)
                current_call = calls
            time.sleep(0.02)
            with state_lock:
                active -= 1
            return (
                main.ChapterResult.ERROR
                if current_call == 1
                else main.ChapterResult.SUCCESS
            )

        with patch("main.process_chapter", side_effect=fake_process):
            self.assertTrue(processor.run())

        self.assertEqual(calls, 2)
        self.assertEqual(max_active, 1)


class ProcessJobTests(unittest.TestCase):
    def test_video_jobs_are_serialized(self):
        state_lock = threading.Lock()
        active = 0
        max_active = 0

        class FakeChaoxing:
            def study_video(self, *args, **kwargs):
                nonlocal active, max_active
                with state_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.03)
                with state_lock:
                    active -= 1
                return StudyResult.SUCCESS

        job = {"type": "video", "jobid": "job", "name": "Video"}
        course = {"title": "Course"}
        chaoxing = FakeChaoxing()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: main.process_job(chaoxing, course, job, {}, 1.0),
                    range(2),
                )
            )

        self.assertEqual(results, [StudyResult.SUCCESS, StudyResult.SUCCESS])
        self.assertEqual(max_active, 1)

    @patch("main.LiveProcessor.run_live", return_value=False)
    def test_live_failure_is_propagated(self, run_live):
        chaoxing = Mock()
        chaoxing.get_uid.return_value = "user"
        course = {"title": "Course", "courseId": "10", "clazzId": "20"}
        job = {"type": "live", "jobid": "live", "property": {}}

        result = main.process_job(
            chaoxing,
            course,
            job,
            {"knowledgeid": "30"},
            1.0,
        )

        self.assertEqual(result, StudyResult.ERROR)
        run_live.assert_called_once()


class ProcessChapterTests(unittest.TestCase):
    def test_job_list_transport_error_is_not_reported_as_success(self):
        chaoxing = Mock()
        chaoxing.rate_limiter = Mock()
        chaoxing.get_job_list.return_value = ([], {"error": "HTTP 500"})

        result = main.process_chapter(
            chaoxing,
            {"title": "Course"},
            {"id": "1", "title": "Chapter", "has_finished": False},
            1.0,
        )

        self.assertEqual(result, main.ChapterResult.ERROR)


class ProcessCourseTests(unittest.TestCase):
    @patch("main.JobProcessor")
    def test_locked_course_runs_sequentially_and_propagates_failures(self, processor_cls):
        chaoxing = Mock()
        chaoxing.get_course_point.return_value = {
            "hasLocked": True,
            "points": [
                {
                    "id": "1",
                    "title": "Chapter",
                    "has_finished": False,
                    "need_unlock": True,
                }
            ],
        }
        processor = processor_cls.return_value
        processor.run.return_value = False
        processor.failed_tasks = [
            main.ChapterTask(
                index=0,
                point={"id": "1", "title": "Chapter", "has_finished": False},
            )
        ]

        result = main.process_course(
            chaoxing,
            {"title": "Course", "courseId": "2", "clazzId": "3", "cpi": "4"},
            {"jobs": 4, "speed": 1.0, "notopen_action": "retry"},
        )

        self.assertFalse(result)
        passed_config = processor_cls.call_args.args[3]
        self.assertEqual(passed_config["jobs"], 1)


if __name__ == "__main__":
    unittest.main()
