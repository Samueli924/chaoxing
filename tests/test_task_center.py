# -*- coding: utf-8 -*-
"""任务中心（教学任务）离线测试."""
#
# 覆盖：
# * 教学任务列表 / 分组 / 任务点的解析与失败处理
# * 任务引擎视频打点节奏（0=开始 / 1=心跳 / 2=结束）
# * 文档任务 readEnd
# * 分组顺序解锁：上一组完成后才继续下一组
# * 不支持的类型（作业/思考题/讨论/未完成证据的章节）不会被假装成已完成
#
# 全部测试不联网、不读写用户真实数据。
import json
import os
from contextlib import contextmanager
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 必须在导入 api 之前指定数据目录，避免碰到用户真实配置
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-test-"))

import main  # noqa: E402
from api import task_center as tc_mod  # noqa: E402
from api.task_center import TaskCenter  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None, url=None, lines=None):
        """Initialize configuration and runtime state."""
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.url = url
        self._lines = lines

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def iter_lines(self, decode_unicode=False):
        if self._lines is None:
            raise AttributeError("not a stream response")
        return iter(self._lines)


class FakeSession:
    """按 URL 关键字路由的假 session，记录所有请求."""

    def __init__(self, routes):
        """Initialize configuration and runtime state."""
        self.routes = routes
        self.calls = []
        self.kwargs_calls = []

    def _dispatch(self, method, url, params=None, **kwargs):
        self.calls.append((method, url, params or {}))
        self.kwargs_calls.append(kwargs)
        for key, handler in self.routes:
            if key in url:
                if callable(handler):
                    return handler(method, url, params or {})
                return handler
        return FakeResponse(status_code=404)

    def get(self, url, params=None, **kwargs):
        return self._dispatch("get", url, params, **kwargs)

    def post(self, url, params=None, **kwargs):
        return self._dispatch("post", url, params, **kwargs)


LEARN_PAGE = (
    '<script>const videoLearnVo = {"encryId":"E1","resourceId":"R1",'
    '"currentTime":0,"farthestTimeValue":0,'
    '"videoInfo":{"success":true,"videoName":"测试视频","duration":12}};</script>'
    '<script>const isMobile = false;</script>'
)


def make_task_center(routes, config=None):
    tc = TaskCenter(chaoxing=object(), config=config or {"speed": 1.0})
    tc.session = FakeSession(routes)
    return tc


class CourseTasksTestCase(unittest.TestCase):
    def setUp(self):
        main.logger.remove()

    def test_reads_task_list(self):
        tc = make_task_center([
            ("taskSignupList", FakeResponse(payload={"status": True, "data": [{"id": 1, "name": "开学第一课"}]})),
        ])
        tasks = tc.get_course_tasks({"courseId": "1", "clazzId": "2", "cpi": "3"})
        self.assertEqual([t["id"] for t in tasks], [1])

    def test_no_permission_returns_empty(self):
        tc = make_task_center([
            ("taskSignupList", FakeResponse(payload={"status": False, "msg": "无权限"})),
        ])
        self.assertEqual(tc.get_course_tasks({"courseId": "1"}), [])

    def test_network_error_returns_empty(self):
        def boom(method, url, params):
            raise RuntimeError("boom")

        tc = make_task_center([("taskSignupList", boom)])
        self.assertEqual(tc.get_course_tasks({"courseId": "1"}), [])
        self.assertTrue(tc.last_read_failed)

    def test_http_failure_returns_empty_and_is_marked(self):
        tc = make_task_center([
            ("taskSignupList", FakeResponse(status_code=503, payload={"status": True, "data": []})),
        ])
        self.assertEqual(tc.get_course_tasks({"courseId": "1"}), [])
        self.assertTrue(tc.last_read_failed)

    def test_non_list_task_data_returns_empty(self):
        tc = make_task_center([
            ("taskSignupList", FakeResponse(payload={"status": True, "data": {}})),
        ])
        self.assertEqual(tc.get_course_tasks({"courseId": "1"}), [])
        self.assertTrue(tc.last_read_failed)

    def test_plan_read_business_failure_is_distinguishable_from_empty_group(self):
        tc = make_task_center([
            ("getPlanDataByGroupId", FakeResponse(payload={"result": False, "message": "拒绝"})),
        ])
        self.assertEqual(tc.get_plans("task", "group"), [])
        self.assertTrue(tc.last_plan_read_failed)

    def test_group_http_failure_is_not_an_empty_group(self):
        tc = make_task_center([
            ("getGroupData", FakeResponse(status_code=502, payload={"result": True, "data": []})),
        ])
        self.assertIsNone(tc.get_groups("task-user"))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.FAILED)


class ChapterSyncTestCase(unittest.TestCase):
    def setUp(self):
        main.logger.remove()

    def test_payload_matches_task_page_shape(self):
        payload = TaskCenter.chapter_sync_payload(
            "TASK@USER+1",
            {
                "uid": "U1",
                "finishCount": 2,
                "clazzId": "C1",
                "enc": "E1",
                "time": 123,
                "jobCount": "3",
                "knowledgeId": "K1",
            },
        )
        self.assertEqual(payload["encryTaskUserId"], "TASK@USER+1")
        self.assertEqual(
            list(payload),
            [
                "encryTaskUserId", "uid", "finishCount", "clazzId", "enc",
                "time", "jobCount", "knowledgeId",
            ],
        )

    def test_sync_requires_explicit_result_true(self):
        tc = make_task_center([
            ("autoPullChapterScore", FakeResponse(payload={"result": True})),
        ])
        self.assertTrue(
            tc.sync_chapter_plan(
                "TASK@USER",
                {"uid": "U1", "clazzId": "C1", "knowledgeId": "K1"},
            )
        )

    def test_sync_does_not_treat_http_200_as_success(self):
        tc = make_task_center([
            ("autoPullChapterScore", FakeResponse(payload={"code": 200})),
        ])
        self.assertFalse(
            tc.sync_chapter_plan(
                "TASK@USER",
                {"uid": "U1", "clazzId": "C1", "knowledgeId": "K1"},
            )
        )


class VideoTestCase(unittest.TestCase):
    def setUp(self):
        main.logger.remove()

    def test_reports_full_duration(self):
        route_handler = {}

        def data_log(method, url, params):
            route_handler.setdefault("dots", []).append(url.rsplit("/", 3)[-3:])
            return FakeResponse(payload={"result": True})

        tc = make_task_center([
            ("videoStudy/learnPage", FakeResponse(text=LEARN_PAGE)),
            ("videoDataLog/dataLog", data_log),
            ("planUserSchedule", FakeResponse(payload={"result": True})),
        ])
        with mock.patch("time.sleep", return_value=None):
            self.assertTrue(tc.study_video("https://task.chaoxing.com/videoStudy/learnPage?x=1"))

        dots = route_handler["dots"]
        # 0=开始, 1=心跳, 2=结束；最后一条必须是完整时长 12 秒
        self.assertEqual(dots[0], ["12", "0", "0"])
        self.assertEqual(dots[-1], ["12", "12", "2"])
        self.assertIn(["12", "6", "1"], dots)

    def test_rejected_dot_fails(self):
        tc = make_task_center([
            ("videoStudy/learnPage", FakeResponse(text=LEARN_PAGE)),
            ("videoDataLog/dataLog", FakeResponse(payload={"result": False, "message": "no"})),
        ])
        with mock.patch("time.sleep", return_value=None):
            self.assertFalse(tc.study_video("https://task.chaoxing.com/videoStudy/learnPage?x=1"))

    def test_rejected_end_dot_does_not_finish(self):
        def data_log(method, url, params):
            status = int(url.rsplit("/", 1)[-1])
            return FakeResponse(payload={"result": status != 2})

        tc = make_task_center([
            ("videoStudy/learnPage", FakeResponse(text=LEARN_PAGE)),
            ("videoDataLog/dataLog", data_log),
        ])
        with mock.patch("time.sleep", return_value=None):
            self.assertFalse(tc.study_video("https://task.chaoxing.com/videoStudy/learnPage?x=1"))

    def test_broken_page_fails(self):
        tc = make_task_center([("videoStudy/learnPage", FakeResponse(text="<html>login</html>"))])
        self.assertFalse(tc.study_video("https://task.chaoxing.com/videoStudy/learnPage?x=1"))


class DocumentTestCase(unittest.TestCase):
    def setUp(self):
        main.logger.remove()

    def test_calls_read_end(self):
        doc_page = '<script>const encryPlanUserId = "BEDC@abc";</script>'
        tc = make_task_center([
            ("documentStudy/learnPage", FakeResponse(text=doc_page)),
            ("documentStudy/readEnd", FakeResponse(payload={"result": True})),
        ])
        plan = {"planBreakthroughSet": {"enableCompleteRead": 1}}
        self.assertTrue(tc.study_document("https://task.chaoxing.com/documentStudy/learnPage?x=1", plan))
        read_end = [c for c in tc.session.calls if "readEnd" in c[1]]
        self.assertEqual(read_end[0][2]["encryPlanUserId"], "BEDC@abc")

    def test_does_not_call_read_end_without_completion_flag(self):
        doc_page = '<script>const encryPlanUserId = "BEDC@abc";</script>'
        tc = make_task_center([
            ("documentStudy/learnPage", FakeResponse(text=doc_page)),
            ("documentStudy/readEnd", FakeResponse(payload={"result": True})),
        ])
        self.assertTrue(tc.study_document(
            "https://task.chaoxing.com/documentStudy/learnPage?x=1",
            {"planBreakthroughSet": {"enableCompleteRead": 0}},
        ))
        self.assertFalse(any("readEnd" in c[1] for c in tc.session.calls))

    def test_read_end_rejected(self):
        doc_page = '<script>const encryPlanUserId = "BEDC@abc";</script>'
        tc = make_task_center([
            ("documentStudy/learnPage", FakeResponse(text=doc_page)),
            ("documentStudy/readEnd", FakeResponse(payload={"result": False, "message": "未读完"})),
        ])
        self.assertFalse(tc.study_document(
            "https://task.chaoxing.com/documentStudy/learnPage?x=1",
            {"planBreakthroughSet": {"enableCompleteRead": 1}},
        ))


class FakeGroupEngine:
    """Simulate sequential group unlocks without contacting a server."""
    def __init__(self, plans_by_group):
        """Initialize configuration and runtime state."""
        self.plans_by_group = plans_by_group
        self.finished = set()
        self.studied = []
        self.round = 0
        self.last_outcome = None
        self.waiting_confirmation = False

    def open_task(self, task):
        self.round += 1
        return {"encryTaskUserId": "u", "encryTaskId": "t"}

    def get_groups(self, etui):
        groups = []
        for index in range(len(self.plans_by_group)):
            allow = index == 0 or all(
                p["planId"] in self.finished for p in self.plans_by_group[index - 1]
            )
            groups.append({
                "encryptGroupId": f"g{index}",
                "groupAllowStudy": allow,
                "taskGroup": {"id": index, "name": f"分组{index}"},
            })
        return groups

    def get_plans(self, etui, group_id):
        index = int(group_id[1:])
        return self.plans_by_group[index]

    def plan_finished(self, plan):
        return plan["planId"] in self.finished

    def get_study_url(self, etui, encrypt_plan_id):
        return f"https://task.chaoxing.com/videoStudy/learnPage?enc={encrypt_plan_id}"

    def _finish(self, url):
        """按 encryptPlanId 找到对应任务点并标记完成（模拟服务端同步）."""
        enc = url.rsplit("=", 1)[-1]
        for plans in self.plans_by_group:
            for plan in plans:
                if plan["encryptPlanId"] == enc:
                    self.studied.append(plan["planId"])
                    self.finished.add(plan["planId"])

    def study_video(self, url, plan=None):
        self._finish(url)
        return True

    def study_document(self, url, plan=None):
        self._finish(url)
        return True

    def study_ai_practice(self, url, plan=None):
        self._finish(url)
        return True

    def study_homework(self, url, plan=None, course=None):
        self._finish(url)
        return True

    def study_discussion(self, url, plan=None, course=None):
        self._finish(url)
        return True

    def wait_plan_finished(self, etui, group_id, plan_id, tries=3, interval=2.0):
        return plan_id in self.finished


class GroupUnlockTestCase(unittest.TestCase):
    """任务点按分组解锁：只有做完当前组，下一组才会允许学习."""

    def setUp(self):
        main.logger.remove()

    def _make_fake_tc(self, plans_by_group):
        return FakeGroupEngine(plans_by_group)

    def test_cancelled_homework_stops_before_next_plan(self):
        """A cancelled submission cannot continue with another task in the group."""
        tc = self._make_fake_tc([[{
            "planId": "p1", "planType": 4, "name": "作业",
            "encryptPlanId": "e1", "encryptGroupId": "g0",
        }, {
            "planId": "p2", "planType": 10, "name": "视频",
            "encryptPlanId": "e2", "encryptGroupId": "g0",
        }]])
        def cancel(*args, **kwargs):
            tc.last_outcome = tc_mod.TaskOutcome.WAITING_CONFIRMATION
            return False
        tc.study_homework = cancel
        with mock.patch.object(main.interrupt, "should_stop", return_value=False):
            ok, _ = main._process_teaching_task(tc, object(), self._course(),
                    {"name": "教学任务"}, {"speed": 1}, {})
        self.assertFalse(ok)
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.WAITING_CONFIRMATION)
        self.assertEqual(tc.studied, [])

    def _course(self):
        return {"title": "示例课程", "courseId": "1", "clazzId": "2", "cpi": "3"}

    def test_runs_all_groups_in_order(self):
        plans = [
            [{"planId": "p1", "planType": 10, "name": "视频1", "encryptPlanId": "e1",
              "encryptGroupId": "g0", "isFinish": False}],
            [{"planId": "p2", "planType": 11, "name": "文档1", "encryptPlanId": "e2",
              "encryptGroupId": "g1", "isFinish": False}],
        ]
        fake = self._make_fake_tc(plans)
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(fake.studied, ["p1", "p2"])

    def _two_task_case(self, config):
        plans = [
            [{"planId": "p1", "planType": 10, "name": "视频1", "encryptPlanId": "e1",
              "encryptGroupId": "g0", "isFinish": False}],
        ]
        fake = self._make_fake_tc(plans)
        fake_tasks = [
            {"id": 1, "name": "第1章", "taskStudyProgress": 0.0},
            {"id": 2, "name": "第2章", "taskStudyProgress": 0.0},
        ]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}):
            return main.run_task_center_phase(object(), [self._course()], config)

    def test_max_tasks_limits_pending_teaching_tasks(self):
        """Max_tasks_per_course=1：只刷第 1 个待完成教学任务，其余不算失败."""
        stats = self._two_task_case({"speed": 1.0, "max_tasks_per_course": 1})
        self.assertEqual(stats["tasks"], 1)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["limited"], 1)

    def test_max_tasks_zero_means_all(self):
        stats = self._two_task_case({"speed": 1.0, "max_tasks_per_course": 0})
        self.assertEqual(stats["tasks"], 2)
        self.assertEqual(stats["limited"], 0)

    def test_max_tasks_supports_per_course_format(self):
        stats = self._two_task_case({"speed": 1.0, "max_tasks_per_course": "1:1"})
        self.assertEqual(stats["tasks"], 1)
        self.assertEqual(stats["limited"], 1)
        # 别的课程没被指定时用默认值 0 = 全部
        stats_other = self._two_task_case({"speed": 1.0, "max_tasks_per_course": "999:1"})
        self.assertEqual(stats_other["tasks"], 2)
        self.assertEqual(stats_other["limited"], 0)

    def test_homework_plan_runs_through_orchestration(self):
        """PlanType=4 必须走 study_homework，并在引擎复查通过后才算完成."""
        plans = [[{"planId": "p1", "planType": 4, "name": "第1章作业", "encryptPlanId": "e1",
                   "encryptGroupId": "g0", "isFinish": False}]]
        fake = self._make_fake_tc(plans)
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(fake.studied, ["p1"])

    def test_task_center_phase_quiets_console(self):
        """任务中心阶段的内部日志只进文件，控制台交还给 print 的结果行."""
        calls = []
        with mock.patch("main.set_console_quiet", side_effect=calls.append), \
             mock.patch("main.run_task_center_phase", return_value={"ok": 1}) as inner:
            result = main._run_task_center_quiet(object(), [], {}, None)
        self.assertEqual(calls, [True, False])
        self.assertEqual(result, {"ok": 1})
        inner.assert_called_once()

    def test_unsupported_plan_is_not_retried(self):
        """暂不支持的 task point 只尝试一次，不跟着解锁轮次反复重试/刷日志."""
        plans = [
            [{"planId": "p1", "planType": 10, "name": "视频1", "encryptPlanId": "e1",
              "encryptGroupId": "g0", "isFinish": False}],
            [{"planId": "p2", "planType": 9, "name": "思考题", "encryptPlanId": "e2",
              "encryptGroupId": "g1", "isFinish": False}],
            [{"planId": "p3", "planType": 8, "name": "章节", "encryptPlanId": "e3",
              "encryptGroupId": "g2", "isFinish": False}],
        ]
        fake = self._make_fake_tc(plans)
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}), \
             mock.patch("main.time.sleep", return_value=None), \
             mock.patch.object(main, "_complete_teaching_plan",
                               wraps=main._complete_teaching_plan) as spy:
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["unsupported"], 1)
        self.assertEqual(spy.call_count, 2)   # p1 + p2 各一次；p2 不跟着轮次重试

    def test_result_lines_are_concise(self):
        """结果行不再重复教学任务名（名字已在 ▸ 行展示）."""
        plans = [[{"planId": "p1", "planType": 10, "name": "视频1", "encryptPlanId": "e1",
                   "encryptGroupId": "g0", "isFinish": False}]]
        fake = self._make_fake_tc(plans)
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        printed = []
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}), \
             mock.patch("builtins.print",
                        side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertIn("      ✓ 完成", printed)
        self.assertFalse([line for line in printed if "✓ 完成：" in line])

    def test_discussion_plan_runs_through_orchestration(self):
        """PlanType=14 必须走 study_discussion，并在引擎复查通过后才算完成."""
        plans = [[{"planId": "p1", "planType": 14, "name": "主题讨论", "encryptPlanId": "e1",
                   "encryptGroupId": "g0", "isFinish": False}]]
        fake = self._make_fake_tc(plans)
        fake_tasks = [{"id": 1, "name": "第2章", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(fake.studied, ["p1"])

    def test_already_finished_task_is_reported_as_completed(self):
        """全部任务点都已完成时是"完成"，last_outcome 不能停在 FAILED."""
        plans = [[{"planId": "p1", "planType": 15, "name": "AI实践", "encryptPlanId": "e1",
                   "encryptGroupId": "g0", "isFinish": True}]]
        fake = self._make_fake_tc(plans)
        fake.finished.add("p1")
        fake.last_outcome = None
        fake_tasks = [{"id": 1, "name": "开学第一课", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(fake.last_outcome, tc_mod.TaskOutcome.COMPLETED)
        self.assertEqual(fake.studied, [])

    def test_locked_groups_are_reported_as_locked(self):
        plans = [
            [{"planId": "p1", "planType": 10, "name": "视频1", "encryptPlanId": "e1",
              "encryptGroupId": "g0", "isFinish": False}],
        ]
        fake = self._make_fake_tc(plans)
        fake.get_groups = lambda etui: [{
            "encryptGroupId": "g0", "groupAllowStudy": False,
            "taskGroup": {"id": 0, "name": "锁定分组"},
        }]
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}), \
             mock.patch("main.time.sleep", return_value=None):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 0)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["locked"], 1)
        self.assertEqual(fake.last_outcome, tc_mod.TaskOutcome.LOCKED)

    def test_unsupported_type_is_not_faked(self):
        plans = [
            [{"planId": "p1", "planType": 10, "name": "视频1", "encryptPlanId": "e1",
              "encryptGroupId": "g0", "isFinish": False}],
            # 9 思考题是目前唯一还不支持的类型；AI实践（15）/主题讨论（14）都已支持，
            # 拿它们当反例会让套件在支持被摘掉时依然全绿。
            [{"planId": "p2", "planType": 9, "name": "思考题", "encryptPlanId": "e2",
              "encryptGroupId": "g1", "isFinish": False}],
        ]
        fake = self._make_fake_tc(plans)
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}), \
             mock.patch("time.sleep", return_value=None):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 0)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["unsupported"], 1)
        self.assertNotIn("p2", fake.studied)

    def _run_task_case(self, fake):
        fake_tasks = [{"id": 1, "name": "开学第一课", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}), \
             mock.patch("main.time.sleep", return_value=None):
            return main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})

    def test_ai_practice_plan_runs_through_orchestration(self):
        """PlanType=15 必须真的走 study_ai_practice，并在引擎复查通过后才算完成."""
        plans = [[{"planId": "p1", "planType": 15, "name": "AI实践", "encryptPlanId": "e1",
                   "encryptGroupId": "g0", "isFinish": False}]]
        fake = self._make_fake_tc(plans)
        stats = self._run_task_case(fake)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(fake.studied, ["p1"])
        self.assertEqual(fake.last_outcome, tc_mod.TaskOutcome.COMPLETED)

    def test_failed_plan_is_not_retried_within_run(self):
        """同一个任务点失败后不再借"等解锁"的轮次反复重试（AI实践一局要几分钟）."""
        plans = [[
            {"planId": "p1", "planType": 15, "name": "AI实践", "encryptPlanId": "e1",
             "encryptGroupId": "g0", "isFinish": False},
            {"planId": "p2", "planType": 10, "name": "视频1", "encryptPlanId": "e2",
             "encryptGroupId": "g0", "isFinish": False},
        ]]
        fake = self._make_fake_tc(plans)
        calls = []

        def fail_ai(url, plan=None):
            calls.append(url)
            return False

        fake.study_ai_practice = fail_ai
        stats = self._run_task_case(fake)
        self.assertEqual(len(calls), 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["done"], 0)
        self.assertEqual(fake.studied, ["p2"])

    def _chapter_plan(self):
        return {
            "planId": "p1", "planType": 8, "name": "章节1", "encryptPlanId": "e1",
            "encryptGroupId": "g0", "externalDataId": "k1", "isFinish": False,
        }

    def _run_chapter_case(self, fake, point_map, chaoxing=None, side_effect=None):
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        chaoxing = chaoxing if chaoxing is not None else object()
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value=point_map), \
             mock.patch("main.process_chapter", side_effect=side_effect):
            return main.run_task_center_phase(chaoxing, [self._course()], {"speed": 1.0})

    def test_chapter_type_target_missing_is_failed_not_unsupported(self):
        """章节点在目录里找不到对应章节：算失败，不能算"暂不支持"或假装完成."""
        fake = self._make_fake_tc([[self._chapter_plan()]])
        stats = self._run_chapter_case(fake, point_map={})
        self.assertEqual(stats["done"], 0)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["unsupported"], 0)
        self.assertEqual(fake.studied, [])

    def test_chapter_type_syncs_platform_stujobinfo(self):
        """章节刷完 + 平台下发 stuJobInfo → 必须调 sync_chapter_plan 且带引擎标记."""
        fake = self._make_fake_tc([[self._chapter_plan()]])
        synced = []
        stu_job_info = {
            "knowledgeId": "k1", "uid": "100000001", "finishCount": 3, "clazzId": "2",
            "enc": "17414ced7cd27f99c3ffcb39fbccdc3d", "time": 1789612363218, "jobCount": 3,
        }

        class FakeChaoxing:
            last_student_job_info = None

        chaoxing = FakeChaoxing()
        seen = {}

        def fake_process_chapter(cx, course, point, speed, engine_info=False):
            seen["engine_info"] = engine_info
            seen["point"] = point
            cx.last_student_job_info = dict(stu_job_info)
            fake.finished.add("p1")
            return main.ChapterResult.SUCCESS

        fake.sync_chapter_plan = (
            lambda etui, data: synced.append((etui, dict(data))) or True
        )
        stats = self._run_chapter_case(
            fake, point_map={"k1": {"id": "k1", "title": "章节1"}},
            chaoxing=chaoxing, side_effect=fake_process_chapter,
        )
        self.assertTrue(seen.get("engine_info"))
        self.assertEqual(seen.get("point", {}).get("id"), "k1")
        self.assertEqual(len(synced), 1)
        self.assertEqual(synced[0][0], "u")
        self.assertEqual(
            {k: synced[0][1].get(k) for k in
             ("uid", "finishCount", "clazzId", "enc", "time", "jobCount", "knowledgeId")},
            {k: stu_job_info.get(k) for k in
             ("uid", "finishCount", "clazzId", "enc", "time", "jobCount", "knowledgeId")},
        )
        self.assertEqual(stats["done"], 1)

    def test_chapter_type_without_stujobinfo_does_not_fake_sync(self):
        """平台没下发同步数据：不能自己拼 enc，也不能报完成."""
        fake = self._make_fake_tc([[self._chapter_plan()]])
        synced = []
        fake.sync_chapter_plan = lambda etui, data: synced.append(data) or True

        class FakeChaoxing:
            last_student_job_info = None

        def fake_process_chapter(cx, course, point, speed, engine_info=False):
            # 不设置 last_student_job_info：模拟平台没有下发
            return main.ChapterResult.SUCCESS

        stats = self._run_chapter_case(
            fake, point_map={"k1": {"id": "k1", "title": "章节1"}},
            chaoxing=FakeChaoxing(), side_effect=fake_process_chapter,
        )
        self.assertEqual(synced, [])
        self.assertEqual(stats["done"], 0)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["unsupported"], 0)

    def test_plan_finished_reads_both_fields(self):
        self.assertTrue(TaskCenter.plan_finished({"isFinish": True}))
        self.assertTrue(TaskCenter.plan_finished({"planUser": {"finish": 1}}))
        self.assertFalse(TaskCenter.plan_finished({"isFinish": False, "planUser": {"finish": 0}}))
        self.assertFalse(TaskCenter.plan_finished({"isFinish": "false", "planUser": {"finish": "0"}}))
        self.assertFalse(TaskCenter.plan_finished(None))

    def test_task_list_read_failure_is_not_reported_as_completion(self):
        class FailedTC:
            last_read_failed = True

            def get_course_tasks(self, course):
                return []

        with mock.patch("main.TaskCenter", return_value=FailedTC()):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 0)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["read_failed"], 1)

    def test_plan_read_failure_is_not_reported_as_completion(self):
        plans = [[{
            "planId": "p1", "planType": 10, "name": "视频1", "encryptPlanId": "e1",
            "encryptGroupId": "g0", "isFinish": False,
        }]]
        fake = self._make_fake_tc(plans)
        fake.last_plan_read_failed = True
        fake_tasks = [{"id": 1, "name": "第1章", "taskStudyProgress": 0.0}]
        with mock.patch.object(fake, "get_course_tasks", lambda course: fake_tasks, create=True), \
             mock.patch("main.TaskCenter", return_value=fake), \
             mock.patch("main._load_course_point_map", return_value={}):
            stats = main.run_task_center_phase(object(), [self._course()], {"speed": 1.0})
        self.assertEqual(stats["done"], 0)
        self.assertEqual(stats["failed"], 1)


class SwitchTestCase(unittest.TestCase):
    def setUp(self):
        main.logger.remove()

    def test_cli_overrides_config(self):
        args = mock.Mock(task_center=False)
        self.assertFalse(main._task_center_enabled({"task_center": True}, args))
        args = mock.Mock(task_center=True)
        self.assertTrue(main._task_center_enabled({"task_center": "false"}, args))

    def test_config_and_default(self):
        self.assertTrue(main._task_center_enabled({}, mock.Mock(task_center=None)))
        self.assertTrue(main._task_center_enabled({"task_center": None}, mock.Mock(task_center=None)))
        self.assertFalse(main._task_center_enabled({"task_center": "false"}, mock.Mock(task_center=None)))
        self.assertTrue(main._task_center_enabled({"task_center": "true"}, mock.Mock(task_center=None)))

    def test_task_finished_flag(self):
        self.assertTrue(main._teaching_task_finished({"taskStudyProgress": 1.0}))
        self.assertFalse(main._teaching_task_finished({"taskStudyProgress": 0.0}))
        self.assertFalse(main._teaching_task_finished({"taskStudyProgress": "oops"}))

    def test_cli_submit_mode_overrides_config_file(self):
        args = type("Args", (), {
            "config": os.path.join(tempfile.gettempdir(), 'config.ini'),
            "task_center": None,
            "task_center_submit_mode": "auto",
        })()
        with mock.patch.object(main, "parse_args", return_value=args), \
             mock.patch.object(
                 main, "load_config_from_file",
                 return_value=({"task_center_submit_mode": "confirm"}, {}, {}),
             ):
            common, _tiku, _notification, _path, _args = main.init_config()
        self.assertEqual(common["task_center_submit_mode"], "auto")


class VideoWatchDurationTestCase(unittest.TestCase):
    """有时长要求的视频：按 1 倍速播完还不够时要回看."""

    def setUp(self):
        main.logger.remove()

    def test_replays_until_watch_duration_met(self):
        dots = []

        def data_log(method, url, params):
            dots.append(url.rsplit("/", 3)[-3:])
            return FakeResponse(payload={"result": True})

        tc = make_task_center([
            ("videoStudy/learnPage", FakeResponse(text=LEARN_PAGE)),
            ("videoDataLog/dataLog", data_log),
            ("planUserSchedule", FakeResponse(payload={"result": True})),
        ], config={"speed": 2.0})
        plan = {"planBreakthroughSet": {"enableVideoWatchDuration": 1, "videoWatchDuration": 0.4}}
        with mock.patch.object(tc_mod.time, "sleep", lambda s: None):
            ok = tc.study_video("https://task.chaoxing.com/videoStudy/learnPage?x=1", plan)
        self.assertTrue(ok)
        starts = [d for d in dots if d[2] == "0"]
        # 12 秒的视频要 24 秒时长 -> 必须回看一遍
        self.assertEqual(len(starts), 2)
        self.assertEqual(dots[0], ["12", "0", "0"])
        self.assertEqual(dots[-1], ["12", "12", "2"])

    def test_need_seconds_parsing(self):
        self.assertEqual(
            TaskCenter.need_seconds({"planBreakthroughSet": {"enableDocumentWatchDuration": 1,
                                                             "documentWatchDuration": 5.0}},
                                    "enableDocumentWatchDuration", "documentWatchDuration"),
            300,
        )
        self.assertEqual(
            TaskCenter.need_seconds({"planBreakthroughSet": {"enableDocumentWatchDuration": 0,
                                                             "documentWatchDuration": 5.0}},
                                    "enableDocumentWatchDuration", "documentWatchDuration"),
            0,
        )
        self.assertEqual(TaskCenter.need_seconds(None, "enableVideoWatchDuration", "videoWatchDuration"), 0)


DOC_LEARN_PAGE = (
    '<script>const docStudyUrlInfo = {"supperSwitch":false,"readType":0,'
    '"yunPanUrl":"https://pan-yz.chaoxing.com/screen/v2/file_abc?x=1","wpsUrl":null};</script>'
    '<script>const encryPlanUserId = "BEDC@planuser";</script>'
)
DOC_READER_PAGE = (
    '<div id="markDataStr" style="display: none">'
    '{"resourceID":"OBJ1","resourceType":"doc","from":4,"passportUID":"123","t":"20260916120000",'
    '"location":1,"curPage":1,"totalPage":2,"ext":"{\\"rwyq_doc\\":1,\\"pId\\":2,\\"oId\\":\\"OBJ1\\",\\"mrId\\":0}",'
    '"token":"tok"}</div>'
    '<script>var pagenum = eval("2");</script>'
)


class DocumentWatchDurationTestCase(unittest.TestCase):
    """文档：按阅读时长打点，凑够时间再收尾."""

    def setUp(self):
        main.logger.remove()

    def _make(self):
        return make_task_center([
            ("documentStudy/learnPage", FakeResponse(text=DOC_LEARN_PAGE)),
            ("pan-yz.chaoxing.com/screen/v2", FakeResponse(text=DOC_READER_PAGE)),
            ("data-xxt.aichaoxing.com/analysis/ac_mark", FakeResponse(text="")),
            ("documentStudy/readEnd", FakeResponse(payload={"result": True})),
        ])

    def test_pings_until_required_seconds(self):
        tc = self._make()
        clock = type("Clock", (), {"t": 0.0,
                                   "now": lambda self: self.t,
                                   "sleep": lambda self, s: setattr(self, "t", self.t + s)})()
        plan = {"name": "案例文档", "planBreakthroughSet": {
            "enableDocumentWatchDuration": 1,
            "documentWatchDuration": 0.1,
            "enableCompleteRead": 1,
        }}
        with mock.patch.object(tc_mod.time, "time", clock.now), \
             mock.patch.object(tc_mod.time, "sleep", clock.sleep):
            ok = tc.study_document("https://task.chaoxing.com/documentStudy/learnPage?x=1", plan)
        self.assertTrue(ok)
        pings = [c for c in tc.session.calls if "ac_mark" in c[1]]
        self.assertGreaterEqual(len(pings), 2)
        self.assertEqual(pings[0][2]["f"], "readPoint")
        self.assertEqual(pings[0][2]["u"], "123")
        self.assertIn("rwyq_doc", pings[0][2]["d"])
        self.assertEqual(json.loads(pings[0][2]["d"])["s"], 1)
        self.assertEqual(json.loads(pings[1][2]["d"])["s"], 2)
        self.assertEqual([c for c in tc.session.calls if "readEnd" in c[1]][0][2]["encryPlanUserId"], "BEDC@planuser")

    def test_requires_reader_mark(self):
        """拿不到打点信息时不能假装完成."""
        tc = make_task_center([
            ("documentStudy/learnPage", FakeResponse(text='<script>const encryPlanUserId = "X";</script>')),
            ("documentStudy/readEnd", FakeResponse(payload={"result": True})),
        ])
        plan = {"planBreakthroughSet": {"enableDocumentWatchDuration": 1, "documentWatchDuration": 5.0}}
        self.assertFalse(tc.study_document("https://task.chaoxing.com/documentStudy/learnPage?x=1", plan))

    def test_rejected_read_point_does_not_finish_document(self):
        tc = make_task_center([
            ("documentStudy/learnPage", FakeResponse(text=DOC_LEARN_PAGE)),
            ("pan-yz.chaoxing.com/screen/v2", FakeResponse(text=DOC_READER_PAGE)),
            ("data-xxt.aichaoxing.com/analysis/ac_mark", FakeResponse(status_code=403)),
            ("documentStudy/readEnd", FakeResponse(payload={"result": True})),
        ])
        plan = {"planBreakthroughSet": {"enableDocumentWatchDuration": 1, "documentWatchDuration": 0.1}}
        with mock.patch.object(tc_mod.time, "time", side_effect=[0.0, 0.0]):
            self.assertFalse(tc.study_document("https://task.chaoxing.com/documentStudy/learnPage?x=1", plan))
        self.assertFalse(any("readEnd" in c[1] for c in tc.session.calls))

    def test_enc_matches_synthetic_known_answer(self):
        """Only synthetic identifiers are needed for the protocol digest fixture."""
        sample = {"f": "readPoint", "u": "test-user", "d": "test-document",
                  "t": "20000101000000000"}
        self.assertEqual(tc_mod._read_point_enc(sample), "9b94f9c71e8f85c82f316cafbdbe129f")

    def test_timestamp_and_enc_are_generated_together(self):
        tc = make_task_center([])
        mark = {
            "resourceID": "OBJ1",
            "resourceType": "doc",
            "from": 4,
            "passportUID": "123",
            "location": 1,
            "curPage": 1,
            "totalPage": 2,
            "ext": "{\"rwyq_doc\":1}",
        }
        with mock.patch.object(tc_mod.time, "time", return_value=1_757_000_123.456):
            self.assertFalse(tc._send_read_point(mark, 1))
        params = tc.session.calls[0][2]
        self.assertRegex(params["t"], r"^\d{17}$")
        self.assertEqual(params["enc"], tc_mod._read_point_enc(params))

    def test_read_point_uses_browser_origin_headers(self):
        tc = make_task_center([])
        seen = {}

        class HeaderSession:
            def get(self, url, params=None, **kwargs):
                seen.update(kwargs)
                return FakeResponse(status_code=403)

        tc.session = HeaderSession()
        self.assertFalse(tc._send_read_point({"resourceID": "OBJ1"}, 1))
        self.assertEqual(seen["headers"], tc_mod.READ_POINT_HEADERS)


class SubmitModeTestCase(unittest.TestCase):
    def test_default_mode_is_auto(self):
        """默认自动提交（挂后台刷课）；只有显式 confirm 才逐次询问."""
        self.assertEqual(tc_mod.normalize_submit_mode(None), "auto")
        self.assertEqual(tc_mod.normalize_submit_mode(""), "auto")
        self.assertEqual(tc_mod.normalize_submit_mode("unexpected"), "auto")
        self.assertEqual(tc_mod.normalize_submit_mode("AUTO"), "auto")
        self.assertEqual(tc_mod.normalize_submit_mode("confirm"), "confirm")

    def test_confirm_mode_without_tty_does_not_submit(self):
        tc = make_task_center([], config={"task_center_submit_mode": "confirm"})
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertFalse(tc._ai_submit(
                {
                    "courseid": "c",
                    "clazzid": "z",
                    "cpi": "p",
                    "publishRelationUuid": "r",
                },
                "record",
                "预览内容",
            ))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.WAITING_CONFIRMATION)
        self.assertFalse(any("answer/submit" in call[1] for call in tc.session.calls))


class ConfirmPromptStdinTestCase(unittest.TestCase):
    """确认提示必须先让键盘监听让出 stdin."""
    #
    # 终端并发约束：章节阶段起的键盘监听线程会把终端设成
    # cbreak 并一直 os.read(stdin,1)，与 input() 抢字符——逐字敲 "yes" 会被
    # 吃成 "ye"/"ys"（按取消处理），甚至让 input() 永久挂住且看不到回显。

    def test_confirm_prompt_runs_inside_stdin_guard(self):
        events = []

        @contextmanager
        def fake_guard():
            events.append("pause")
            try:
                yield True
            finally:
                events.append("resume")

        class FakeTTY:
            def isatty(self):
                return True

        tc = TaskCenter(object(), {"task_center_submit_mode": "confirm"})
        with mock.patch.object(tc_mod.sys, "stdin", FakeTTY()), \
             mock.patch.object(tc_mod.interrupt, "stdin_for_prompt", fake_guard), \
             mock.patch("builtins.input", side_effect=lambda prompt="": (events.append("input"), "y")[1]):
            self.assertTrue(tc.confirm_submission("AI实践", "预览"))
        self.assertEqual(events, ["pause", "input", "resume"])

    def test_paused_watcher_leaves_stdin_for_input(self):
        """暂停期间监听线程不再消费 stdin；恢复后又能按 q 终止."""
        import select as _select
        import termios as _termios
        import time as _time

        if os.name == "nt":
            self.skipTest("termios 只测 POSIX")
        try:
            import pty
        except ImportError:
            self.skipTest("没有 pty")

        master, slave = pty.openpty()
        # 关掉回显：pty 的 master 端没人读，回显会把输出缓冲写满，
        # 之后 termios 改属性（等输出排空）和 close 都会永久阻塞。
        attrs = _termios.tcgetattr(slave)
        attrs[3] = attrs[3] & ~_termios.ECHO
        _termios.tcsetattr(slave, _termios.TCSANOW, attrs)
        fake_stdin = os.fdopen(os.dup(slave), "rb", buffering=0)
        old_stdin = sys.stdin
        sys.stdin = fake_stdin
        try:
            self.assertTrue(tc_mod.interrupt.start_watcher())
            self.assertTrue(tc_mod.interrupt.pause_watcher(2.0))
            # 监听让开以后，写进终端的内容应该原样被读到
            os.write(master, b"hello\n")
            ready, _, _ = _select.select([slave], [], [], 2.0)
            self.assertTrue(ready, "暂停期间 stdin 仍被监听线程消费")
            with os.fdopen(os.dup(slave), "rb", buffering=0) as reader:
                self.assertEqual(reader.readline(), b"hello\n")
            # 恢复监听后按 q 依旧能终止
            tc_mod.interrupt.resume_watcher()
            _time.sleep(0.2)
            os.write(master, b"q")
            deadline = _time.time() + 3.0
            while _time.time() < deadline and not tc_mod.interrupt.should_stop():
                _time.sleep(0.05)
            self.assertTrue(tc_mod.interrupt.should_stop(), "恢复后按 q 没有生效")
        finally:
            sys.stdin = old_stdin
            tc_mod.interrupt.reset()
            fake_stdin.close()
            os.close(master)
            os.close(slave)


class AIPracticeTestCase(unittest.TestCase):
    PAGE_URL = (
        "https://mooc2-ans-vue.example/think-ladder/answer/pc-index?"
        "courseid=c1&clazzid=z1&cpi=p1&publishRelationUuid=pub1&aiEnc=enc1"
    )

    @staticmethod
    def _event(content, event_type=None):
        event = {"content": content}
        if event_type:
            event["type"] = event_type
        return b"data:" + json.dumps(event, ensure_ascii=False).encode("utf-8")

    def test_sse_parser_keeps_fields_and_special_marks(self):
        lines = [
            b": heartbeat",
            self._event("单选题", "questionType"),
            self._event("0", "questionTypeInt"),
            self._event("企业战略", "dimension"),
            self._event("战略选择", "knowledgePoint"),
            self._event("题目内容", "questionStem"),
            self._event("选项一", "option-A"),
            self._event("补充", "option-A"),
            self._event("选项二", "option-B"),
            self._event("SonQuestion"),
            b"data: [DONE]",
        ]
        result = TaskCenter.parse_ai_sse(lines)
        self.assertTrue(result["had_data"])
        self.assertTrue(result["stream_closed"])
        self.assertEqual(result["questionTypeInt"], "0")
        self.assertEqual(result["questionStem"], "题目内容")
        self.assertEqual(result["options"][0]["optionContent"], "选项一补充")
        self.assertIn("SonQuestion", result["special_marks"])

    def test_ai_practice_submits_only_after_status_and_score_readback(self):
        state = {"loads": 0, "streams": 0}

        def load_data(method, url, params):
            state["loads"] += 1
            if state["loads"] == 1:
                payload = {
                    "recordStatus": 0,
                    "recordUuid": "record-1",
                    "answerUuid": "answer-1",
                    "unCompleteTopic": ["topic-1"],
                }
            elif state["loads"] == 2:
                payload = {
                    "recordStatus": 0,
                    "recordUuid": "record-1",
                    "answerUuid": "answer-1",
                    "unCompleteTopic": [],
                }
            else:
                payload = {
                    "recordStatus": 2,
                    "recordUuid": "record-1",
                    "answerUuid": "answer-1",
                    "answerScore": 90,
                    "answerRecords": [{"recordUuid": "record-1", "score": 90}],
                    "unCompleteTopic": [],
                }
            return FakeResponse(payload={"status": True, "data": payload})

        def talk(method, url, params):
            state["streams"] += 1
            if state["streams"] == 1:
                lines = [
                    self._event("单选题", "questionType"),
                    self._event("0", "questionTypeInt"),
                    self._event("题目：战略的核心是什么？", "questionStem"),
                    self._event("方向", "option-A"),
                    self._event("规模", "option-B"),
                ]
            else:
                lines = [self._event("SummaryTopic")]
            return FakeResponse(lines=lines)

        class Writer:
            def choose_options(self, question, options, multiple=False, context=""):
                return "A"

        tc = TaskCenter(
            object(),
            {"task_center_submit_mode": "auto", "ai_practice_min_score": 85,
             "ai_practice_max_rounds": 1},
            writer=Writer(),
        )
        tc.session = FakeSession([
            ("pc-index", FakeResponse(url=self.PAGE_URL, text="")),
            ("load-data", load_data),
            ("main-talk", talk),
            ("answer/submit", FakeResponse(payload={"status": True, "data": 2})),
        ])
        with mock.patch.object(tc_mod.interrupt, "should_stop", return_value=False), \
             mock.patch.object(tc_mod.time, "sleep", return_value=None):
            self.assertTrue(tc.study_ai_practice(self.PAGE_URL))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.COMPLETED)
        submit_calls = [call for call in tc.session.calls if "answer/submit" in call[1]]
        self.assertEqual(len(submit_calls), 1)
        submit_index = [i for i, call in enumerate(tc.session.calls) if "answer/submit" in call[1]][0]
        self.assertEqual(tc.session.kwargs_calls[submit_index]["data"], {})
        stream_indexes = [i for i, call in enumerate(tc.session.calls) if "main-talk" in call[1]]
        self.assertEqual(tc.session.kwargs_calls[stream_indexes[0]]["data"], {"userMessage": ""})
        stream_index = stream_indexes[-1]
        self.assertEqual(tc.session.kwargs_calls[stream_index]["data"], {"userMessage": "A"})
        self.assertEqual(tc.session.kwargs_calls[stream_index]["headers"], tc_mod.AI_STREAM_HEADERS)
        self.assertEqual(tc.session.kwargs_calls[stream_index]["timeout"], tc_mod.AI_STREAM_TIMEOUT)
        self.assertTrue(tc.session.kwargs_calls[stream_index]["stream"])
        self.assertEqual(
            tc.session.kwargs_calls[submit_index]["headers"], tc_mod.AI_FORM_HEADERS
        )

    def test_ai_practice_rejects_http_200_without_business_success(self):
        tc = TaskCenter(object(), {"task_center_submit_mode": "auto"})
        tc.session = FakeSession([
            ("pc-index", FakeResponse(url=self.PAGE_URL)),
            ("load-data", FakeResponse(payload={"status": False, "msg": "拒绝"})),
        ])
        self.assertFalse(tc.study_ai_practice(self.PAGE_URL))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.FAILED)

    def test_ai_submit_rejects_http_200_without_business_success(self):
        tc = TaskCenter(object(), {"task_center_submit_mode": "auto"})
        tc.session = FakeSession([
            ("answer/submit", FakeResponse(payload={"status": True, "data": 0})),
        ])
        self.assertFalse(tc._ai_submit({
            "courseid": "c", "clazzid": "z", "cpi": "p", "publishRelationUuid": "r",
        }, "record"))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.FAILED)

    def test_ai_practice_retries_low_score_with_new_record(self):
        state = {"loads": 0, "streams": 0, "inits": 0, "submits": 0}

        def load_data(method, url, params):
            state["loads"] += 1
            if state["loads"] in {1, 4}:
                record = "record-1" if state["loads"] == 1 else "record-2"
                return FakeResponse(payload={
                    "status": True,
                    "data": {
                        "recordStatus": 0,
                        "recordUuid": record,
                        "answerUuid": "answer-" + record[-1],
                        "unCompleteTopic": ["topic-1"],
                    },
                })
            if state["loads"] == 2:
                data = {
                    "recordStatus": 0,
                    "recordUuid": "record-1",
                    "answerUuid": "answer-1",
                    "unCompleteTopic": [],
                }
            elif state["loads"] == 3:
                data = {
                    "recordStatus": 2,
                    "recordUuid": "record-1",
                    "answerUuid": "answer-1",
                    "answerScore": 40,
                    "answerRecords": [{"recordUuid": "record-1", "score": 40}],
                    "remainAnswerCount": 1,
                    "unCompleteTopic": [],
                }
            elif state["loads"] == 5:
                data = {
                    "recordStatus": 0,
                    "recordUuid": "record-2",
                    "answerUuid": "answer-2",
                    "unCompleteTopic": [],
                }
            else:
                data = {
                    "recordStatus": 2,
                    "recordUuid": "record-2",
                    "answerUuid": "answer-2",
                    "answerScore": 90,
                    "answerRecords": [{"recordUuid": "record-2", "score": 90}],
                    "remainAnswerCount": 0,
                    "unCompleteTopic": [],
                }
            return FakeResponse(payload={"status": True, "data": data})

        def init_data(method, url, params):
            state["inits"] += 1
            return FakeResponse(payload={
                "status": True,
                "data": {"recordUuid": "record-2", "answerUuid": "answer-2"},
            })

        def talk(method, url, params):
            state["streams"] += 1
            if state["streams"] % 2:
                lines = [
                    self._event("单选题", "questionType"),
                    self._event("0", "questionTypeInt"),
                    self._event("题目：战略的核心是什么？", "questionStem"),
                    self._event("方向", "option-A"),
                    self._event("规模", "option-B"),
                ]
            else:
                lines = [self._event("SummaryTopic")]
            return FakeResponse(lines=lines)

        def submit(method, url, params):
            state["submits"] += 1
            return FakeResponse(payload={"status": True, "data": state["submits"]})

        class Writer:
            def choose_options(self, question, options, multiple=False, context=""):
                return "A"

        tc = TaskCenter(
            object(),
            {"task_center_submit_mode": "auto", "ai_practice_min_score": 85,
             "ai_practice_max_rounds": 2},
            writer=Writer(),
        )
        tc.session = FakeSession([
            ("pc-index", FakeResponse(url=self.PAGE_URL)),
            ("load-data", load_data),
            ("answer/init", init_data),
            ("main-talk", talk),
            ("answer/submit", submit),
        ])
        with mock.patch.object(tc_mod.interrupt, "should_stop", return_value=False), \
             mock.patch.object(tc_mod.time, "sleep", return_value=None):
            self.assertTrue(tc.study_ai_practice(self.PAGE_URL))
        self.assertEqual(state["inits"], 1)
        self.assertEqual(state["submits"], 2)
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.COMPLETED)


class ChapterEngineInfoTestCase(unittest.TestCase):
    """任务引擎「章节」上下文：打点带 courseEngineInfo，平台的 stuJobInfo 要暂存."""

    def setUp(self):
        main.logger.remove()

    def _chaoxing(self):
        from api import base as base_mod
        cx = base_mod.Chaoxing()
        cx.video_log_limiter = base_mod.RateLimiter(0)
        cx.get_uid = lambda: "100000001"
        cx.get_fid = lambda: "1336"
        return cx

    @staticmethod
    def _job():
        return {
            "jobid": "1548984627901674",
            "objectid": "011155377179e72459aae8a97edbfbe8",
            "otherinfo": "nodeId_100001-cpi_1000003-rt_d-ds_0-ff_1-be_0_0-vt_1-v_6-enc_c64478",
            "videoFaceCaptureEnc": "",
            "attDuration": "",
            "attDurationEnc": "",
            "rt": "0.9",
            "name": "测试视频",
        }

    def _run_log(self, cx, engine_info, payload):
        calls = []

        class Sess:
            def get(self, url, params=None, **kwargs):
                calls.append(dict(params or {}))
                return FakeResponse(payload=payload)

        passed, state = cx.video_progress_log(
            Sess(), {"clazzId": "1000002", "courseId": "1000001", "cpi": "1000003"},
            self._job(), {}, "dtoken-x", 696, 696, "Video", headers={},
            engine_info=engine_info,
        )
        return passed, state, calls

    def test_engine_info_adds_course_engine_info_param(self):
        cx = self._chaoxing()
        stu = {"knowledgeId": 100001, "uid": "100000001", "finishCount": 3,
               "clazzId": 1000002, "enc": "17414ced", "time": 1, "jobCount": 3}
        passed, state, calls = self._run_log(
            cx, True, {"isPassed": True, "stuJobInfo": stu}
        )
        self.assertTrue(passed)
        self.assertEqual(state, 200)
        self.assertEqual(calls[0].get("courseEngineInfo"), "true")
        self.assertEqual(cx.last_student_job_info, stu)

    def test_forbidden_request_falls_back_to_curl(self):
        """Requests 被客户端指纹拦截（403）时，用 curl 原样重放并采用其结果."""
        from api import base as base_mod
        cx = self._chaoxing()
        calls = []

        class Sess:
            def get(self, url, params=None, **kwargs):
                calls.append(dict(params or {}))
                return FakeResponse(status_code=403, text="403 错误页")

        with mock.patch.object(base_mod, "_curl_get",
                               return_value=base_mod._CurlResponse(
                                   200, '{"isPassed": true}', "https://x/log")):
            passed, state = cx.video_progress_log(
                Sess(), {"clazzId": "1000002", "courseId": "1000001", "cpi": "1000003"},
                self._job(), {}, "dtoken-x", 696, 696, "Video", headers={},
                engine_info=True,
            )
        self.assertTrue(passed)
        self.assertEqual(state, 200)

    def test_curl_replay_parses_body_and_status(self):
        from api import base as base_mod

        class FakeProc:
            stdout = '{"isPassed": true}\n200'
            returncode = 0

        class FakeSession:
            cookies = {}

        with mock.patch("shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("subprocess.run", return_value=FakeProc()):
            res = base_mod._curl_get(FakeSession(), "https://x/y", {"a": 1},
                                     {"Referer": "https://r"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["isPassed"])

    def test_plain_log_has_no_engine_param_and_no_capture(self):
        cx = self._chaoxing()
        passed, _state, calls = self._run_log(
            cx, False, {"isPassed": True, "stuJobInfo": {"enc": "不应被暂存"}}
        )
        self.assertTrue(passed)
        self.assertNotIn("courseEngineInfo", calls[0])
        self.assertIsNone(cx.last_student_job_info)


class EngineDocumentSyncTestCase(unittest.TestCase):
    """文档在任务引擎上下文里：完成后要请求 /mooc-ans/job/document 并暂存 stuJobInfo."""

    def setUp(self):
        main.logger.remove()

    def _sess(self, calls, stu):
        class Sess:
            def get(self, url, params=None, **kwargs):
                calls.append((url, dict(params or {})))
                if "mooc-ans/job/document" in url:
                    return FakeResponse(payload={"status": True, "msg": "考核点已经完成",
                                                 "stuJobInfo": stu})
                return FakeResponse(payload={"status": True})

        return Sess()

    def test_study_document_engine_context_captures_stujobinfo(self):
        from api import base as base_mod
        calls = []
        stu = {"knowledgeId": 100001, "uid": "100000001", "finishCount": 3,
               "clazzId": 1000002, "enc": "17414ced", "time": 1, "jobCount": 3}
        cx = base_mod.Chaoxing()
        with mock.patch.object(base_mod.SessionManager, "get_session",
                               return_value=self._sess(calls, stu)):
            result = cx.study_document(
                {"courseId": "1000001", "clazzId": "1000002"},
                {"jobid": "10001",
                 "otherinfo": "nodeId_100001-cpi_1000003",
                 "jtoken": "test-document-token"},
                engine_info=True,
            )
        self.assertEqual(result, base_mod.StudyResult.SUCCESS)
        engine_calls = [c for c in calls if "mooc-ans/job/document" in c[0]]
        self.assertEqual(len(engine_calls), 1)
        self.assertEqual(engine_calls[0][1].get("courseEngineInfo"), "true")
        self.assertEqual(engine_calls[0][1].get("checkMicroTopic"), "true")
        self.assertEqual(engine_calls[0][1].get("knowledgeid"), "100001")
        self.assertEqual(cx.last_student_job_info, stu)

    def test_study_document_without_engine_context_keeps_old_behavior(self):
        from api import base as base_mod
        calls = []
        cx = base_mod.Chaoxing()
        with mock.patch.object(base_mod.SessionManager, "get_session",
                               return_value=self._sess(calls, {"enc": "不应被暂存"})):
            result = cx.study_document(
                {"courseId": "1000001", "clazzId": "1000002"},
                {"jobid": "10001",
                 "otherinfo": "nodeId_100001-cpi_1000003",
                 "jtoken": "jtoken-x"},
            )
        self.assertEqual(result, base_mod.StudyResult.SUCCESS)
        self.assertFalse([c for c in calls if "mooc-ans/job/document" in c[0]])
        self.assertIsNone(cx.last_student_job_info)

class AIPendingTurnTestCase(unittest.TestCase):
    """过期题目不能当成 pending：平台出总结后，局已经结束."""

    def _msg(self, role, payload):
        return {"role": role, "content": json.dumps(payload, ensure_ascii=False)}

    def test_summary_after_question_means_done(self):
        data = {"messageList": [
            self._msg("2", {"questionStem": "旧题", "questionTypeInt": "0",
                            "questionOptions": [{"option": "A", "optionContent": "a"}]}),
            self._msg("1", {"content": "D"}),
            self._msg("2", {"content": "# 怎样才能具备CEO的思维和能力知识点解析\n\n## 一、战略管理"}),
        ]}
        self.assertIsNone(TaskCenter._ai_pending_turn(data))

    def test_question_after_answer_is_pending(self):
        data = {"messageList": [
            self._msg("2", {"questionStem": "新题", "questionTypeInt": "0",
                            "questionOptions": [{"option": "A", "optionContent": "a"}]}),
        ]}
        turn = TaskCenter._ai_pending_turn(data)
        self.assertIsNotNone(turn)
        self.assertEqual(turn["questionStem"], "新题")


class AIReportScoreTestCase(unittest.TestCase):
    """成绩是"学习质量评估报告"现算出来的：提交后必须请求它，否则永远不出分."""

    PAGE_URL = AIPracticeTestCase.PAGE_URL

    def test_report_sse_parses_score_from_split_lines(self):
        lines = [
            'data:{"id":"score","content":"92"}',
            'data:{"id":"学习怎样成为一个中层管理者","content":"亮点"}',
            'data:{"id":"学习怎样成为一个中层管理者',
            '","content":"表现：答得好"}',
            "data:[DONE]",
        ]
        result = TaskCenter.parse_ai_report_sse(lines)
        self.assertTrue(result["had_data"])
        self.assertTrue(result["stream_closed"])
        self.assertEqual(result["score"], 92.0)
        self.assertIn("亮点", result["sections"]["学习怎样成为一个中层管理者"])

    def test_report_sse_without_score_is_not_a_score(self):
        result = TaskCenter.parse_ai_report_sse(['data:{"id":"other","content":"x"}'])
        self.assertIsNone(result["score"])

    def test_ai_practice_uses_report_score_when_state_is_not_backfilled(self):
        state = {"loads": 0, "streams": 0, "submitted": False}

        def load_data(method, url, params):
            state["loads"] += 1
            if state["submitted"]:
                # 平台状态接口回填慢：这里故意永远不把本条记录放进 answerRecords
                payload = {
                    "recordStatus": 1,
                    "recordUuid": "record-1",
                    "answerScore": 30,
                    "answerRecords": [{"recordUuid": "old", "score": 30}],
                    "unCompleteTopic": [],
                }
            elif state["loads"] == 1:
                payload = {
                    "recordStatus": 0,
                    "recordUuid": "record-1",
                    "unCompleteTopic": ["topic-1"],
                }
            else:
                payload = {
                    "recordStatus": 0,
                    "recordUuid": "record-1",
                    "unCompleteTopic": [],
                }
            return FakeResponse(payload={"status": True, "data": payload})

        def talk(method, url, params):
            state["streams"] += 1
            if state["streams"] == 1:
                lines = [
                    AIPracticeTestCase._event("单选题", "questionType"),
                    AIPracticeTestCase._event("0", "questionTypeInt"),
                    AIPracticeTestCase._event("题目：战略的核心是什么？", "questionStem"),
                    AIPracticeTestCase._event("方向", "option-A"),
                    AIPracticeTestCase._event("规模", "option-B"),
                ]
            else:
                lines = [AIPracticeTestCase._event("SummaryTopic")]
            return FakeResponse(lines=lines)

        def report(method, url, params):
            self.assertEqual(params.get("recordUuid"), "record-1")
            return FakeResponse(lines=['data:{"id":"score","content":"92"}', "data:[DONE]"])

        def submit(method, url, params):
            state["submitted"] = True
            return FakeResponse(payload={"status": True, "data": 1})

        class Writer:
            def choose_options(self, question, options, multiple=False, context="", exclude=None):
                return "A"

        tc = TaskCenter(
            object(),
            {"task_center_submit_mode": "auto", "ai_practice_min_score": 85,
             "ai_practice_max_rounds": 1},
            writer=Writer(),
        )
        tc.session = FakeSession([
            ("pc-index", FakeResponse(url=self.PAGE_URL, text="")),
            ("load-data", load_data),
            ("main-talk", talk),
            ("answer/submit", submit),
            ("end-report", report),
        ])
        with mock.patch.object(tc_mod.interrupt, "should_stop", return_value=False), \
             mock.patch.object(tc_mod.time, "sleep", return_value=None):
            self.assertTrue(tc.study_ai_practice(self.PAGE_URL))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.COMPLETED)
        report_calls = [call for call in tc.session.calls if "end-report" in call[1]]
        self.assertEqual(len(report_calls), 1)
        # 报告已经给了成绩：提交后最多再读一次状态，不能固定轮询 19 次×30s
        submit_index = [i for i, call in enumerate(tc.session.calls)
                        if "answer/submit" in call[1]][0]
        loads_after_submit = [
            i for i, call in enumerate(tc.session.calls)
            if "load-data" in call[1] and i > submit_index
        ]
        self.assertLessEqual(len(loads_after_submit), 2)
        submit_index = [i for i, call in enumerate(tc.session.calls) if "answer/submit" in call[1]][0]
        report_index = [i for i, call in enumerate(tc.session.calls) if "end-report" in call[1]][0]
        self.assertGreater(report_index, submit_index)


class AIObjectiveAnswerTestCase(unittest.TestCase):
    """客观题必须有客观题的作答形态：平台没给题型也不能写成小作文."""

    def test_options_without_type_are_answered_as_choice(self):
        class Writer:
            def choose_options(self, question, options, multiple=False, context="", exclude=None):
                return "B"

            def answer(self, *args, **kwargs):
                raise AssertionError("带选项的题目不能走简答")

        tc = TaskCenter(object(), {}, writer=Writer())
        turn = {
            "questionStem": "公司层战略的核心特征是什么？",
            "questionType": "未知题型",
            "questionTypeInt": "",
            "options": [
                {"option": "A", "optionContent": "单一业务板块的运营流程优化"},
                {"option": "B", "optionContent": "业务领域选择与业务组合管理"},
            ],
        }
        self.assertEqual(tc._ai_answer(turn, {}), "B")

    def test_unknown_numeric_type_with_options_is_still_choice(self):
        """题型编码没见过（如 "2"）但题目给了选项：按客观题作答，不写小作文."""

        class Writer:
            def choose_options(self, question, options, multiple=False, context="", exclude=None):
                return "A"

            def answer(self, *args, **kwargs):
                raise AssertionError("带选项的题目不能走简答")

        tc = TaskCenter(object(), {}, writer=Writer())
        turn = {
            "questionStem": "下列哪项正确？",
            "questionType": "单选题",
            "questionTypeInt": "2",
            "options": [
                {"option": "A", "optionContent": "甲"},
                {"option": "B", "optionContent": "乙"},
            ],
        }
        self.assertEqual(tc._ai_answer(turn, {}), "A")

    def test_chinese_judgement_label_answers_with_dui_cuo(self):
        class Writer:
            def choose_judgement(self, question, context="", exclude=None):
                return "错"

        tc = TaskCenter(object(), {}, writer=Writer())
        turn = {
            "questionStem": "中层管理者只需要做执行，不需要战略分析。",
            "questionType": "判断题",
            "questionTypeInt": "",
            "options": [
                {"option": "A", "optionContent": "正确"},
                {"option": "B", "optionContent": "错误"},
            ],
        }
        self.assertEqual(tc._ai_answer(turn, {}), "错")


class AIPracticeLoopGuardTestCase(unittest.TestCase):
    """平台拿自己的大模型判分，会把标准答案判错并反复推回同一题."""
    #
    # 实测被推回 15 次、整局拖到 112 题。知识点答完后必须及时收手。

    PAGE_URL = AIPracticeTestCase.PAGE_URL
    QUESTION = [
        b'data:' + json.dumps({"content": "单选题", "type": "questionType"},
                              ensure_ascii=False).encode("utf-8"),
        b'data:' + json.dumps({"content": "0", "type": "questionTypeInt"},
                              ensure_ascii=False).encode("utf-8"),
        b'data:' + json.dumps({"content": "公司层战略的核心特征是什么？", "type": "questionStem"},
                              ensure_ascii=False).encode("utf-8"),
        b'data:' + json.dumps({"content": "单一业务板块运营优化", "type": "option-A"},
                              ensure_ascii=False).encode("utf-8"),
        b'data:' + json.dumps({"content": "业务领域选择与组合管理", "type": "option-B"},
                              ensure_ascii=False).encode("utf-8"),
        b'data:' + json.dumps({"content": "细分市场营销方案", "type": "option-C"},
                              ensure_ascii=False).encode("utf-8"),
        b'data:' + json.dumps({"content": "部门绩效考核", "type": "option-D"},
                              ensure_ascii=False).encode("utf-8"),
    ]

    def _run(self, state, load_data, talk, submit):
        class Writer:
            def choose_options(self, question, options, multiple=False, context="", exclude=None):
                banned = {str(item).upper() for item in (exclude or [])}
                for letter in "ABCD":
                    if letter not in banned:
                        return letter
                raise AssertionError("同一道题不该有第五次作答")

        tc = TaskCenter(
            object(),
            {"task_center_submit_mode": "auto", "ai_practice_min_score": 85,
             "ai_practice_max_rounds": 1},
            writer=Writer(),
        )
        tc.session = FakeSession([
            ("pc-index", FakeResponse(url=self.PAGE_URL, text="")),
            ("load-data", load_data),
            ("main-talk", talk),
            ("answer/submit", submit),
        ])
        with mock.patch.object(tc_mod.interrupt, "should_stop", return_value=False), \
             mock.patch.object(tc_mod.time, "sleep", return_value=None):
            ok = tc.study_ai_practice(self.PAGE_URL)
        answers = [
            tc.session.kwargs_calls[index]["data"]["userMessage"]
            for index, call in enumerate(tc.session.calls)
            if "main-talk" in call[1]
        ]
        return tc, ok, answers

    def test_rejected_question_is_not_retried_forever(self):
        """平台每答一次都记一条消息（messageList 变长）但继续推回同一题：按次数收手."""
        state = {"loads": 0, "msgs": 0, "submitted": False}

        def load_data(method, url, params):
            state["loads"] += 1
            if state["submitted"]:
                payload = {
                    "recordStatus": 2,
                    "recordUuid": "record-1",
                    "answerScore": 90,
                    "answerRecords": [
                        {"recordUuid": "record-1", "score": 90, "statusMsg": "已评估"}
                    ],
                    "unCompleteTopic": [],
                }
            else:
                payload = {
                    "recordStatus": 0,
                    "recordUuid": "record-1",
                    "messageList": [{"role": "1", "content": "{}"}] * state["msgs"],
                    "unCompleteTopic": ["topic-1"] if state["loads"] == 1 else [],
                }
            return FakeResponse(payload={"status": True, "data": payload})

        def talk(method, url, params):
            state["msgs"] += 2
            return FakeResponse(lines=self.QUESTION)

        def submit(method, url, params):
            state["submitted"] = True
            return FakeResponse(payload={"status": True, "data": 1})

        tc, ok, answers = self._run(state, load_data, talk, submit)
        self.assertTrue(ok)
        # 一次空消息开题 + 每题最多试满一轮选项（4 个），然后直接提交
        self.assertEqual(answers, ["", "A", "B", "C", "D"])
        submit_calls = [call for call in tc.session.calls if "answer/submit" in call[1]]
        self.assertEqual(len(submit_calls), 1)
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.COMPLETED)

    def test_stale_question_after_last_topic_is_not_answered_forever(self):
        """知识点答完后平台把最后一道题推回来、又不收录作答：连续两次无新消息就收手."""
        #
        # 真实踩坑：一整局 9 道题都答对了、unCompleteTopic 也空了，平台却继续把
        # 最后那道判断题推回来，本地"错/对"来回换了十几次，记录里一条都没多。
        SUMMARY = b'data:' + json.dumps(
            {"content": "# 知识点解析\n\n## 一、战略管理"}, ensure_ascii=False
        ).encode("utf-8")
        state = {"loads": 0, "submitted": False}

        def load_data(method, url, params):
            state["loads"] += 1
            if state["submitted"]:
                payload = {
                    "recordStatus": 2, "recordUuid": "record-1", "answerScore": 88,
                    "answerRecords": [{"recordUuid": "record-1", "score": 88,
                                       "statusMsg": "已评估"}],
                    "unCompleteTopic": [],
                }
            else:
                payload = {
                    "recordStatus": 0,
                    "recordUuid": "record-1",
                    # 平台快照一直停在"9 题 + 总结"，不再增长
                    "messageList": [{"role": "2", "content": json.dumps(
                        {"content": "# 知识点解析\n"}, ensure_ascii=False)}] * 19,
                    "unCompleteTopic": ["topic-1"] if state["loads"] == 1 else [],
                }
            return FakeResponse(payload={"status": True, "data": payload})

        def talk(method, url, params):
            return FakeResponse(lines=self.QUESTION + [SUMMARY])

        def submit(method, url, params):
            state["submitted"] = True
            return FakeResponse(payload={"status": True, "data": 1})

        tc, ok, answers = self._run(state, load_data, talk, submit)
        self.assertTrue(ok)
        self.assertEqual(answers[:2], ["", "A"])
        self.assertLessEqual(len(answers), 4)
        submit_calls = [call for call in tc.session.calls if "answer/submit" in call[1]]
        self.assertEqual(len(submit_calls), 1)
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.COMPLETED)


class AIAverageScoreTestCase(unittest.TestCase):
    """页面写的达标口径是"多次练习平均分"：单次满分不够，历史低分要补回来."""

    PAGE_URL = AIPracticeTestCase.PAGE_URL

    def test_reports_average_and_keeps_answering_for_low_history(self):
        QUESTION = AIPracticeLoopGuardTestCase.QUESTION
        state = {
            "records": [
                {"recordUuid": "old-1", "score": 30},
                {"recordUuid": "old-2", "score": 60},
            ],
            "submitted": False,
            "round": 0,
            "answered": 0,
            "current": "record-1",
        }

        def load_data(method, url, params):
            ru = str(params.get("recordUuid") or state["current"])
            payload = {
                "recordStatus": 2 if state["submitted"] else 0,
                "recordUuid": ru,
                "answerRecords": list(state["records"]),
                "messageList": [],
                "unCompleteTopic": [] if state["answered"] else ["topic-1"],
            }
            return FakeResponse(payload={"status": True, "data": payload})

        def talk(method, url, params):
            if params and params.get("recordUuid") == state["current"] and state["answered"]:
                return FakeResponse(lines=[b'data:{"content":"SummaryTopic"}'])
            state["answered"] = 1
            return FakeResponse(lines=QUESTION)

        def init(method, url, params):
            state["round"] += 1
            state["submitted"] = False
            state["answered"] = 0
            state["current"] = f"record-{state['round'] + 1}"
            return FakeResponse(payload={"status": True, "data": {
                "recordUuid": state["current"], "answerUuid": "answer-1"}})

        def submit(method, url, params):
            state["submitted"] = True
            state["records"] = state["records"] + [
                {"recordUuid": state["current"], "score": 95}
            ]
            return FakeResponse(payload={"status": True, "data": 1})

        def report(method, url, params):
            return FakeResponse(lines=['data:{"id":"score","content":"95"}', "data:[DONE]"])

        class Writer:
            def choose_options(self, question, options, multiple=False, context="", exclude=None):
                return "A"

        tc = TaskCenter(
            object(),
            {"task_center_submit_mode": "auto", "ai_practice_min_score": 85,
             "ai_practice_max_rounds": 2},
            writer=Writer(),
        )
        tc.session = FakeSession([
            ("pc-index", FakeResponse(url=self.PAGE_URL, text="")),
            ("answer/init", init),
            ("load-data", load_data),
            ("main-talk", talk),
            ("answer/submit", submit),
            ("end-report", report),
        ])
        with mock.patch.object(tc_mod.interrupt, "should_stop", return_value=False), \
             mock.patch.object(tc_mod.time, "sleep", return_value=None):
            self.assertTrue(tc.study_ai_practice(self.PAGE_URL))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.COMPLETED)
        # 第一轮 95 分但历史平均只有 61.7：补第二轮；第二轮后平均 70 仍未达标，
        # 但本轮已达标且重答次数用尽，按"完成 + 如实告警"处理。
        self.assertEqual(len([c for c in tc.session.calls if "answer/submit" in c[1]]), 2)
        self.assertEqual(len([c for c in tc.session.calls if "end-report" in c[1]]), 2)

    def test_already_submitted_record_is_never_submitted_twice(self):
        """平台把同一条已提交记录再交回来时，绝不能对同一条记录二次 submit."""
        records = [
            {"recordUuid": "old-1", "score": 30},
            {"recordUuid": "old-2", "score": 60},
            {"recordUuid": "record-1", "score": 95},
        ]

        def load_data(method, url, params):
            payload = {
                "recordStatus": 2,
                "recordUuid": "record-1",
                "answerRecords": list(records),
                "messageList": [],
                "unCompleteTopic": [],
            }
            return FakeResponse(payload={"status": True, "data": payload})

        def init(method, url, params):
            # 平台拒绝开新记录，把已提交的那条交回来
            return FakeResponse(payload={"status": True, "data": {
                "recordUuid": "record-1", "answerUuid": "answer-1"}})

        tc = TaskCenter(
            object(),
            {"task_center_submit_mode": "auto", "ai_practice_min_score": 85,
             "ai_practice_max_rounds": 2},
        )
        tc.session = FakeSession([
            ("pc-index", FakeResponse(url=self.PAGE_URL, text="")),
            ("answer/init", init),
            ("load-data", load_data),
            ("main-talk", FakeResponse(lines=[b'data:{"content":"SummaryTopic"}'])),
            ("answer/submit", FakeResponse(payload={"status": True, "data": 1})),
            ("end-report", FakeResponse(lines=['data:{"id":"score","content":"95"}'])),
        ])
        with mock.patch.object(tc_mod.interrupt, "should_stop", return_value=False), \
             mock.patch.object(tc_mod.time, "sleep", return_value=None):
            self.assertTrue(tc.study_ai_practice(self.PAGE_URL))
        self.assertEqual(tc.last_outcome, tc_mod.TaskOutcome.COMPLETED)
        self.assertEqual(
            [c for c in tc.session.calls if "answer/submit" in c[1]], []
        )

    def test_score_never_falls_back_to_another_record(self):
        """问"这一条记录多少分"时，本条还没评估就必须返回 None，不能拿旧分顶替."""
        data = {
            "answerScore": 90,
            "answerRecords": [{"recordUuid": "old", "score": 90}],
        }
        self.assertIsNone(TaskCenter._ai_score(data, "record-1"))
        self.assertEqual(TaskCenter._ai_score(data), 90.0)
        self.assertEqual(
            TaskCenter._ai_score(
                {"answerRecords": [{"recordUuid": "record-1", "score": 77}]}, "record-1"
            ),
            77.0,
        )

    def test_average_score_ignores_missing_values(self):
        data = {"answerRecords": [
            {"recordUuid": "a", "score": 90},
            {"recordUuid": "b", "score": None},
            {"recordUuid": "c", "score": "70"},
            "junk",
        ]}
        self.assertEqual(TaskCenter._ai_record_scores(data), [90.0, 70.0])
        self.assertEqual(TaskCenter._ai_average_score(data), 80.0)
        self.assertIsNone(TaskCenter._ai_average_score({}))


if __name__ == "__main__":
    unittest.main()
