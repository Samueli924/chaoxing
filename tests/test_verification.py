"""Completion must follow independent server evidence, not worker return values."""
import json
import unittest
from unittest.mock import patch

from api.runtime import runtime
from api.runner import Runner, format_summary
from api.settings import Settings
from api.verification import verify_course, confirm_video
from main import run_cli, parse_args

COURSE = {"courseId": "course", "clazzId": "class", "cpi": "local", "title": "Fixture course"}
MISSING = 'mArg = ""; try{ mArg = $mArg; }catch(e){}'


def card(*attachments):
    return 'mArg = ' + json.dumps({"defaults": {"knowledgeid": "chapter"}, "attachments": list(attachments)}) + ';'


class FakeCourse:
    def __init__(self, pages, progress=None, after=None):
        self.pages = pages
        self.progress = {"done": 1, "total": 1} if progress is None else progress
        self.after = after
        self.outlines = 0
        self.reads = []

    def get_course_point(self, *args):
        self.outlines += 1
        return {"points": [{"id": "chapter", "title": "Fixture", "has_finished": True}],
                "jobProgress": self.after if self.outlines > 1 and self.after is not None else self.progress}

    def iter_card_pages(self, course, point):
        for i, page in enumerate(self.pages):
            self.reads.append(i)
            if isinstance(page, Exception):
                raise page
            yield i, page

    def get_job_list(self, *args):
        raise AssertionError("Read-only audit called a mutating reader")

    def study_emptypage(self, *args):
        raise AssertionError("Read-only audit marked a page studied")


class VerificationTests(unittest.TestCase):
    def setUp(self):
        runtime.reset()
        self.addCleanup(runtime.reset)

    def test_complete_course_includes_completed_test_and_optional_resources(self):
        cx = FakeCourse([card({"type": "video", "isPassed": True, "jobid": "v"},
                              {"type": "workid", "jobid": "w"},
                              {"type": "document"}, {"type": "read"}), MISSING])
        report = verify_course(cx, COURSE)
        self.assertTrue(report["complete"])
        self.assertEqual(report["pending"], {})
        self.assertEqual(report["attachments"], {"video": 1, "workid": 1, "document": 1, "read": 1})
        self.assertEqual(report["chapters_checked"], 1)

    def test_full_aggregate_cannot_hide_unknown_pending_task(self):
        cx = FakeCourse([card({"type": "new_platform_task", "job": "true"}), MISSING])
        report = verify_course(cx, COURSE)
        self.assertFalse(report["complete"])
        self.assertEqual(report["pending"], {"new_platform_task": 1})

    def test_second_tab_is_checked_even_when_outline_claims_finished(self):
        cx = FakeCourse([card({"type": "video", "isPassed": True}),
                         card({"type": "workid", "job": True}), MISSING])
        report = verify_course(cx, COURSE)
        self.assertFalse(report["complete"])
        self.assertEqual(report["pending"], {"workid": 1})
        self.assertEqual(cx.reads, [0, 1, 2])

    def test_partial_aggregate_cannot_pass_empty_pending_list(self):
        report = verify_course(FakeCourse([card(), MISSING], {"done": 0, "total": 1}), COURSE)
        self.assertFalse(report["complete"])

    def test_unrecognised_or_locked_or_unterminated_cards_fail_closed(self):
        for pages in (["<html>changed platform</html>"], ["章节未开放"], [card()]):
            with self.subTest(pages=pages):
                report = verify_course(FakeCourse(pages), COURSE)
                self.assertFalse(report["complete"])
                self.assertTrue(report["errors"])

    def test_missing_and_invalid_progress_fail_closed(self):
        for progress in ({}, {"done": 2, "total": 1}, {"done": True, "total": 1}):
            report = verify_course(FakeCourse([card(), MISSING], progress), COURSE)
            self.assertFalse(report["complete"])
            self.assertTrue(report["errors"])

    def test_progress_changes_during_audit_require_another_read(self):
        report = verify_course(FakeCourse([card(), MISSING], {"done": 0, "total": 1},
                                         {"done": 1, "total": 1}), COURSE)
        self.assertFalse(report["complete"])
        self.assertTrue(report["errors"])

    def test_request_exception_does_not_disclose_url_or_secret(self):
        report = verify_course(FakeCourse([RuntimeError("https://private/?token=secret")]), COURSE)
        self.assertFalse(report["complete"])
        self.assertNotIn("secret", json.dumps(report))
        self.assertIn("RuntimeError", report["errors"][0])

    def test_stop_does_not_read_or_claim_success(self):
        runtime.request_stop()
        cx = FakeCourse([card(), MISSING])
        self.assertFalse(verify_course(cx, COURSE)["complete"])
        self.assertEqual(cx.outlines, 0)

    def test_duplicate_pending_attachment_counted_once(self):
        item = {"type": "video", "job": True, "jobid": "video"}
        report = verify_course(FakeCourse([card(item), card(item), MISSING]), COURSE)
        self.assertEqual(report["pending"], {"video": 1})

    def test_video_requires_positive_passed_even_without_pending_job_flag(self):
        report = verify_course(FakeCourse([card({"type": "video", "jobid": "v", "isPassed": "false"}), MISSING]), COURSE)
        self.assertFalse(report["complete"])
        self.assertEqual(report["pending"], {"video": 1})

    def test_independent_media_confirmation_matches_exact_job(self):
        for value, expected in ((True, True), ("true", True), ("false", False), (False, False), (None, False)):
            cx = FakeCourse([card({"type": "video", "jobid": "v", "isPassed": value}), MISSING])
            self.assertEqual(confirm_video(cx, COURSE, {}, {"jobid": "v"}), expected)
            self.assertFalse(confirm_video(cx, COURSE, {}, {"jobid": "different"}))

    def test_legacy_read_job_without_job_flag_remains_pending(self):
        report = verify_course(FakeCourse([card({"type": "read", "jobid": "legacy"}), MISSING]), COURSE)
        self.assertFalse(report["complete"])
        self.assertEqual(report["pending"], {"read": 1})

    def test_verify_cli_accepts_verified_course_without_notifications(self):
        with patch("main.Runner") as cls, patch("main.stdin_is_interactive", return_value=False):
            runner = cls.return_value
            runner.login.return_value = {"status": True}
            runner.list_courses.return_value = [COURSE]
            runner.verify_courses.return_value = {"complete": True, "courses": []}
            self.assertEqual(run_cli(Settings(common={"username": "fixture", "password": "fixture"}), True), 0)
            runner.run.assert_not_called()
            runner.notify.assert_not_called()
        text = format_summary({"verification_only": True, "courses": 1, "complete": True})
        self.assertIn("只读任务校验", text)
        self.assertNotIn("章节数: 0", text)

    def test_verify_cli_cannot_pass_without_courses(self):
        with patch("main.Runner") as cls, patch("main.stdin_is_interactive", return_value=False):
            runner = cls.return_value
            runner.login.return_value = {"status": True}
            runner.list_courses.return_value = []
            self.assertEqual(run_cli(Settings(common={"username": "fixture", "password": "fixture"}), True), 1)
            runner.notify.assert_not_called()

    def test_invalid_attachment_format_fails_closed(self):
        report = verify_course(FakeCourse(['mArg = {"attachments": [null]};', MISSING]), COURSE)
        self.assertFalse(report["complete"])
        self.assertTrue(report["errors"])

    def test_scheduler_success_cannot_override_incomplete_server(self):
        runner = Runner(Settings(common={}, notification={"provider": ""}), interactive=False)
        runner.chaoxing = FakeCourse([card({"type": "video", "job": True}), MISSING],
                                    {"done": 0, "total": 1})
        with patch("api.runner.JobProcessor") as processor:
            processor.return_value.summary.return_value = {"total": 1, "done": 1, "failed": [],
                                                           "skipped": [], "cancelled": 0, "skipped_works": 0}
            summary = runner.run([COURSE])
        self.assertFalse(summary["complete"])
        self.assertIn("未通过", format_summary(summary))
        self.assertEqual(runtime.snapshot()["stage"], "未完成或未通过校验")

    def test_successful_runner_requires_verified_server(self):
        runner = Runner(Settings(common={}, notification={"provider": ""}), interactive=False)
        runner.chaoxing = FakeCourse([card({"type": "video", "isPassed": True}), MISSING])
        with patch("api.runner.JobProcessor") as processor:
            processor.return_value.summary.return_value = {"total": 1, "done": 1, "failed": [],
                                                           "skipped": [], "cancelled": 0, "skipped_works": 0}
            summary = runner.run([COURSE])
        self.assertTrue(summary["complete"])
        self.assertEqual(runtime.snapshot()["stage"], "已完成并校验")

    def test_no_courses_cannot_be_verified(self):
        runner = Runner(Settings(common={}, notification={"provider": ""}), interactive=False)
        runner.chaoxing = FakeCourse([])
        self.assertFalse(runner.verify_courses([])["complete"])

    def test_verify_cli_is_read_only_and_returns_nonzero_when_incomplete(self):
        settings = Settings(common={"username": "fixture", "password": "fixture"},
                            tiku={"provider": "AI"}, notification={"provider": "email"})
        with patch("main.Runner") as cls, patch("main.stdin_is_interactive", return_value=False):
            runner = cls.return_value
            runner.login.return_value = {"status": True}
            runner.list_courses.return_value = [COURSE]
            runner.verify_courses.return_value = {"complete": False, "courses": []}
            self.assertEqual(run_cli(settings, verify_only=True), 1)
            runner.run.assert_not_called()
            runner.notify.assert_not_called()
            used = cls.call_args.args[0]
            self.assertEqual(used.tiku, {"provider": ""})
            self.assertEqual(used.notification, {"provider": ""})
        self.assertEqual(settings.tiku["provider"], "AI")
        self.assertTrue(parse_args(["--verify"] ).verify)

    def test_normal_cli_does_not_exit_success_for_incomplete_or_stopped_run(self):
        for summary in ({"complete": False, "failed": []}, {"stopped": True, "failed": []}):
            with patch("main.Runner") as cls, patch("main.stdin_is_interactive", return_value=False):
                runner = cls.return_value
                runner.login.return_value = {"status": True}
                runner.list_courses.return_value = [COURSE]
                runner.run.return_value = summary
                self.assertEqual(run_cli(Settings(common={"username": "fixture", "password": "fixture"})), 1)


if __name__ == "__main__":
    unittest.main()
