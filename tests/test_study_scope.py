# -*- coding: utf-8 -*-
"""
刷课范围（章节 / 任务中心）回归：

- main.py 的 chapter_study 开关（命令行 > 配置文件 > 默认开启）
- 向导里的「刷什么内容」选择与写出的账号配置

不联网、不碰真实用户数据（CX_DATA_HOME 指向临时目录）。
"""

import configparser
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-scope-"))

import main as main_mod  # noqa: E402
import setup_wizard as wizard  # noqa: E402


class ChapterStudyFlagTestCase(unittest.TestCase):
    """chapter_study：命令行 > 配置文件 > 默认开启"""

    def test_default_on(self):
        args = mock.Mock(chapter_study=None)
        self.assertTrue(main_mod._chapter_study_enabled({}, args))
        self.assertTrue(main_mod._chapter_study_enabled({"chapter_study": None}, args))

    def test_config_values(self):
        args = mock.Mock(chapter_study=None)
        self.assertFalse(main_mod._chapter_study_enabled({"chapter_study": "false"}, args))
        self.assertFalse(main_mod._chapter_study_enabled({"chapter_study": False}, args))
        self.assertTrue(main_mod._chapter_study_enabled({"chapter_study": "true"}, args))

    def test_cli_overrides_config(self):
        self.assertFalse(
            main_mod._chapter_study_enabled({"chapter_study": True}, mock.Mock(chapter_study=False))
        )
        self.assertTrue(
            main_mod._chapter_study_enabled({"chapter_study": "false"}, mock.Mock(chapter_study=True))
        )

    def test_cli_flags_parse(self):
        with mock.patch.object(sys, "argv", ["main.py", "--no-chapters"]):
            self.assertFalse(main_mod.parse_args().chapter_study)
        with mock.patch.object(sys, "argv", ["main.py", "--chapters"]):
            self.assertTrue(main_mod.parse_args().chapter_study)
        with mock.patch.object(sys, "argv", ["main.py"]):
            self.assertIsNone(main_mod.parse_args().chapter_study)

    def test_config_file_parses_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            with open(path, "w", encoding="utf8") as f:
                f.write(
                    "[common]\nusername = 13800000000\npassword = pw\n"
                    "course_list = 1\nchapter_study = false\ntask_center = true\n"
                )
            common, _tiku, _notify = main_mod.load_config_from_file(path)
        self.assertFalse(common["chapter_study"])
        self.assertTrue(common["task_center"])


class TaskCountConfigTestCase(unittest.TestCase):
    """max_tasks_per_course 复用 max_points_per_course 的解析规则"""

    def test_per_course_format(self):
        mapping, default, bad = main_mod._parse_max_points("1:2,3:0")
        self.assertEqual(mapping, {"1": 2, "3": 0})
        self.assertEqual(default, 0)
        self.assertEqual(bad, [])

    def test_plain_number_and_empty(self):
        self.assertEqual(main_mod._parse_max_points("3"), ({}, 3, []))
        self.assertEqual(main_mod._parse_max_points(None), ({}, 0, []))
        self.assertEqual(main_mod._parse_max_points(""), ({}, 0, []))

    def test_bad_value_is_flagged_not_defaulted(self):
        mapping, default, bad = main_mod._parse_max_points("abc")
        self.assertEqual(mapping, {})
        self.assertEqual(default, 0)
        self.assertEqual(bad, ["abc"])


class WizardScopeTestCase(unittest.TestCase):
    """向导里的范围选择与写出的账号配置"""

    def test_scope_table(self):
        self.assertEqual(wizard.STUDY_SCOPES["1"], (True, True, False))
        self.assertEqual(wizard.STUDY_SCOPES["2"], (True, False, False))
        self.assertEqual(wizard.STUDY_SCOPES["3"], (False, True, False))
        self.assertEqual(wizard.STUDY_SCOPES["4"], (False, False, True))   # 只刷讨论

    def test_choose_scope_mapping(self):
        cases = [
            ("1", "1", (True, True, False, "task")),      # 章节 + 任务中心 + 讨论自动
            ("1", "2", (True, True, False, "board")),     # 章节 + 任务中心 + 讨论区挑帖
            ("2", "", (True, False, False, "")),          # 只刷章节：不问讨论
            ("3", "1", (False, True, False, "task")),     # 只刷任务中心
            ("4", "2", (False, False, True, "board")),    # 只刷讨论：讨论区挑帖
            ("4", "1", (False, False, True, "task")),     # 只刷讨论：任务讨论自动
        ]
        for scope, mode, expect in cases:
            answers = [scope] + ([mode] if mode else [])
            with mock.patch.object(wizard, "ask",
                                   side_effect=lambda *a, **k: answers.pop(0) if answers else "1"), \
                 mock.patch("builtins.print"):
                self.assertEqual(wizard.choose_study_scope(), expect, (scope, mode))

    def test_choose_scope_reprompts_on_bad_input(self):
        answers = iter(["9", "2"])
        with mock.patch.object(wizard, "ask",
                               side_effect=lambda *a, **k: next(answers)), \
             mock.patch("builtins.print"):
            self.assertEqual(wizard.choose_study_scope(), (True, False, False, ""))


    def test_only_discussion_keeps_task_center_enabled(self):
        """只刷讨论必须写成 task_center = true，否则启动检查会拦下"""
        plan = [({"courseId": 1, "clazzId": 2, "title": "测试课"}, 0, 0)]
        path = wizard.build_config("13800000000", "pw", plan,
                                   chapters_enabled=False, task_center_enabled=False,
                                   only_discussion=True, discussion_mode="board")
        text = open(path, encoding="utf-8").read()
        self.assertIn("task_center = true", text)
        self.assertIn("chapter_study = false", text)
        self.assertIn("only_discussion = true", text)
        self.assertIn("discussion_mode = board", text)

    @staticmethod
    def _empty_cfg():
        import configparser
        cfg = configparser.ConfigParser()
        cfg.add_section("tiku")
        return cfg

    def test_question_bank_mode_does_not_ask_ai_key(self):
        """选言溪题库不该被追问 DeepSeek Key（表结构解包顺序回归）"""
        with mock.patch.object(wizard, "read_config", return_value=self._empty_cfg()), \
             mock.patch.object(wizard, "ask", side_effect=["2", "tok-123"]), \
             mock.patch.object(wizard, "ask_deepseek_key") as key_ask, \
             mock.patch.object(wizard, "update_config"), \
             mock.patch("builtins.print"):
            provider, result = wizard.setup_answer_mode(force=True)
        self.assertEqual(provider, "TikuYanxi")
        self.assertEqual(result.get("tokens"), "tok-123")
        key_ask.assert_not_called()

    def test_key_step_downgrade_keeps_question_bank_tokens(self):
        """在 Key 步骤选「不做测验」时，不能把刚填好的题库 token 丢掉"""
        with mock.patch.object(wizard, "read_config", return_value=self._empty_cfg()), \
             mock.patch.object(wizard, "ask", side_effect=["4", "tok-9"]), \
             mock.patch.object(wizard, "ask_deepseek_key", return_value=""), \
             mock.patch.object(wizard, "update_config"), \
             mock.patch("builtins.print"):
            provider, result = wizard.setup_answer_mode(force=True)
        self.assertEqual(provider, "TikuYanxi")
        self.assertEqual(result.get("tokens"), "tok-9")

    def test_choose_courses_skips_points_for_task_center_only(self):
        course = {"courseId": 1, "clazzId": 2, "title": "测试课"}
        cx = mock.Mock()
        cx.get_course_list.return_value = [course]
        with mock.patch.object(wizard, "ask", return_value="1"), \
             mock.patch("builtins.print"):
            plan = wizard.choose_courses(cx, ask_points=False, ask_tasks=False)
        self.assertEqual(plan, [(course, 0, 0)])

    def test_choose_courses_asks_both_counts(self):
        """章节 + 任务中心都刷时，每门课分别问两个数量"""
        course = {"courseId": 1, "clazzId": 2, "title": "测试课"}
        cx = mock.Mock()
        cx.get_course_list.return_value = [course]
        answers = iter(["1", "2", "3"])   # 选课 / 章节前 2 个 / 教学任务前 3 个
        with mock.patch.object(wizard, "ask", side_effect=lambda *a, **k: next(answers)), \
             mock.patch("builtins.print"):
            plan = wizard.choose_courses(cx)
        self.assertEqual(plan, [(course, 2, 3)])

    def test_ask_count_all_alias(self):
        for raw, expect in (("all", 0), ("全部", 0), ("0", 0), ("5", 5)):
            with mock.patch.object(wizard, "ask", return_value=raw), \
                 mock.patch("builtins.print"):
                self.assertEqual(wizard._ask_count("x"), expect)

    def test_ask_count_empty_input_uses_all_default(self):
        """回车走 ask 的默认值 all（mock 里模拟 ask 的默认值行为）"""
        with mock.patch.object(
            wizard, "ask",
            side_effect=lambda prompt, default=None: str(default),
        ) as m, mock.patch("builtins.print"):
            self.assertEqual(wizard._ask_count("x"), 0)
        self.assertEqual(m.call_args.kwargs.get("default"), "all")

    def test_ask_count_reprompts_on_bad_input(self):
        answers = iter(["abc", "-1", "4"])
        with mock.patch.object(wizard, "ask",
                               side_effect=lambda *a, **k: next(answers)), \
             mock.patch("builtins.print"):
            self.assertEqual(wizard._ask_count("x"), 4)

    def test_build_config_writes_scope(self):
        plan = [({"courseId": 1, "clazzId": 2, "title": "测试课"}, 0, 0)]
        path = wizard.build_config("13800000000", "pw", plan,
                                   chapters_enabled=False, task_center_enabled=True)
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf8")
        self.assertEqual(cfg.get("common", "chapter_study"), "false")
        self.assertEqual(cfg.get("common", "task_center"), "true")

    def test_chapters_only_clears_previous_discussion_mode(self):
        """连续下一轮只刷章节时，绝不能把上一轮 board 留在运行配置里。"""
        plan = [({"courseId": 1, "clazzId": 2, "title": "测试课"}, 1, 0)]
        path = wizard.build_config("13800000003", "pw", plan,
                                   chapters_enabled=True, task_center_enabled=False,
                                   discussion_mode="board")
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf8")
        self.assertEqual(cfg.get("common", "discussion_mode"), "none")


class DiscussionScopeIsolationTestCase(unittest.TestCase):
    """运行时也必须隔离旧配置，而不仅依赖向导正确写文件。"""

    def test_chapter_only_ignores_stale_board_setting(self):
        self.assertEqual(
            main_mod._discussion_mode_for_run({"discussion_mode": "board"}, False, False),
            "none",
        )

    def test_task_center_keeps_explicit_board_setting(self):
        self.assertEqual(
            main_mod._discussion_mode_for_run({"discussion_mode": "board"}, True, False),
            "board",
        )

    def test_invalid_discussion_mode_falls_back_to_task(self):
        self.assertEqual(
            main_mod._discussion_mode_for_run({"discussion_mode": "unexpected"}, True, False),
            "task",
        )

    def test_build_config_uses_recommended_defaults(self):
        """向导不再逐项问配置：写出的运行配置直接用推荐值"""
        plan = [({"courseId": 1, "clazzId": 2, "title": "测试课"}, 3, 2)]
        path = wizard.build_config("13800000002", "pw", plan)
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf8")
        common = cfg["common"]
        self.assertEqual(common["speed"], "2")
        self.assertEqual(common["jobs"], "2")
        self.assertEqual(common["work_max_retries"], "3")
        self.assertEqual(common["notopen_action"], "continue")
        self.assertEqual(common["task_center_submit_mode"], "auto")

    def test_prefs_do_not_ask(self):
        """已经配置过：正常启动不再问任何东西"""
        import configparser
        cfg = configparser.ConfigParser()
        cfg.add_section("cx")
        cfg.set("cx", "prefs_done", "yes")
        cfg.set("cx", "prefs_version", "2")
        with mock.patch.object(wizard, "read_config", return_value=cfg), \
             mock.patch.object(wizard, "setup_notification",
                               side_effect=AssertionError("不该问通知")), \
             mock.patch.object(wizard, "ask",
                               side_effect=AssertionError("不该问刷课参数")), \
             mock.patch("builtins.print"):
            wizard.ensure_global_prefs(force=False)

    def test_first_run_asks_optional_notification(self):
        """第一次运行会问一次可选的通知设置（直接回车＝不用）"""
        import configparser
        cfg = configparser.ConfigParser()
        cfg.add_section("cx")
        with mock.patch.object(wizard, "read_config", return_value=cfg), \
             mock.patch.object(wizard, "setup_notification",
                               return_value=("", "", "")) as notify, \
             mock.patch.object(wizard, "update_config"), \
             mock.patch("builtins.print"):
            wizard.ensure_global_prefs(force=False)
        self.assertTrue(notify.called)

    def test_setup_only_asks_notification(self):
        """cx setup 也只问可选的通知，不问刷课参数"""
        with mock.patch.object(wizard, "setup_notification",
                               return_value=("", "", "")) as notify, \
             mock.patch.object(wizard, "ask",
                               side_effect=AssertionError("不该问刷课参数")), \
             mock.patch("builtins.print"):
            wizard.ensure_global_prefs(force=True)
        notify.assert_called_once()

    def test_prefs_summary_is_short(self):
        line = wizard.prefs_summary()
        self.assertLessEqual(WizardDisplayTestCase._width(line), 76)
        self.assertIn("自动提交", line)

    def test_build_config_defaults_both_on(self):
        plan = [({"courseId": 1, "clazzId": 2, "title": "测试课"}, 3, 2)]
        path = wizard.build_config("13800000001", "pw", plan)
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf8")
        self.assertEqual(cfg.get("common", "chapter_study"), "true")
        self.assertEqual(cfg.get("common", "task_center"), "true")
        self.assertEqual(cfg.get("common", "max_points_per_course"), "1:3")
        self.assertEqual(cfg.get("common", "max_tasks_per_course"), "1:2")


class WizardDisplayTestCase(unittest.TestCase):
    """向导页面展示回归：简洁（不超宽、不双空行）且关键信息在"""

    @staticmethod
    def _width(text):
        import unicodedata
        return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)

    def _render(self, inputs):
        import io
        from contextlib import redirect_stdout
        course = {"courseId": 1, "clazzId": 2, "title": "示例课程"}
        answers = iter(inputs)

        def fake_input(prompt=""):
            try:
                val = next(answers)
            except StopIteration:
                val = "3"
            print(prompt + val)
            return val

        cx = mock.Mock()
        cx.get_course_list.return_value = [course]
        buf = io.StringIO()
        with mock.patch.object(wizard, "ensure_api_key"), \
             mock.patch.object(wizard, "ensure_global_prefs"), \
             mock.patch.object(wizard, "pick_user",
                               return_value=("13800000000", "pw", cx, "测试用户")), \
             mock.patch.object(wizard, "build_config", return_value="/tmp/cx-ui-test.ini"), \
             mock.patch.object(wizard, "ask_after_run", return_value="exit"), \
             mock.patch("builtins.input", fake_input), \
             redirect_stdout(buf):
            wizard._main_inner()
        return buf.getvalue()

    def test_pages_stay_concise(self):
        # 只刷任务中心 / 讨论自动 / 课程 1 / 教学任务 3 个 / 取消
        out = self._render(["3", "1", "1", "3", "n", "3"])
        for line in out.splitlines():
            self.assertLessEqual(self._width(line), 76, f"页面行超过 76 列: {line!r}")
        self.assertNotIn("\n\n\n", out, "不要连续两个空行")

    def test_key_information_is_shown(self):
        # 章节 + 任务中心 / 讨论自动 / 课程 1 / 章节 2 / 教学任务全部 / 取消
        out = self._render(["1", "1", "1", "2", "all", "n", "3"])
        self.assertIn("刷什么内容", out)
        self.assertIn("数字 = 本次刷多少个「还没完成」的，已完成的自动跳过、不会重刷。", out)
        self.assertIn("all 或直接回车 = 没完成的全部刷完。", out)
        self.assertIn("范围  章节 + 任务中心", out)
        self.assertIn("章节 2 个未完成 · 教学任务全部", out)
        self.assertIn("讨论怎么刷", out)
        self.assertIn("任务里的主题讨论（自动，按课程要求的顺序做）", out)
        self.assertIn("讨论区（自己挑帖子回复）", out)


class WizardFlowTestCase(unittest.TestCase):
    """登录后先问范围、再选课；只刷任务中心时不问任务点数，--yes 透传给 main.py"""

    def _run_flow(self, argv, scope, submit_answer=None):
        course = {"courseId": 1, "clazzId": 2, "title": "测试课"}
        seen = {}

        def fake_choose_courses(cx, ask_points=True, ask_tasks=True, only_discussion=False,
                                discussion_mode=""):
            seen["ask_points"] = ask_points
            seen["ask_tasks"] = ask_tasks
            seen["only_discussion"] = only_discussion
            seen["discussion_mode"] = discussion_mode
            return [(course, 0, 0)]

        def fake_build_config(username, password, plan,
                              chapters_enabled=True, task_center_enabled=True,
                              only_discussion=False, discussion_mode="task"):
            seen["scope"] = (chapters_enabled, task_center_enabled, only_discussion)
            seen["discussion_mode"] = discussion_mode
            return "/tmp/cx-test-run.ini"

        def fake_run_main():
            seen["argv"] = list(sys.argv)

        with mock.patch.object(wizard, "ensure_api_key"), \
             mock.patch.object(wizard, "ensure_global_prefs"), \
             mock.patch.object(wizard, "pick_user",
                               return_value=("13800000000", "pw", mock.Mock(), "测试用户")), \
             mock.patch.object(wizard, "choose_study_scope", return_value=scope), \
             mock.patch.object(wizard, "choose_courses", side_effect=fake_choose_courses), \
             mock.patch.object(wizard, "build_config", side_effect=fake_build_config), \
             mock.patch.object(wizard, "ask_after_run", return_value="exit"), \
             mock.patch.object(wizard, "ask_yes_no", return_value=submit_answer), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.dict(sys.modules, {"main": mock.Mock(main=fake_run_main)}):
            self.assertEqual(wizard._main_inner(), 0)
        return seen

    def test_task_center_only_forwards_yes(self):
        seen = self._run_flow(["setup_wizard.py", "--yes"], (False, True, False, "task"))
        self.assertFalse(seen["ask_points"])
        self.assertTrue(seen["ask_tasks"])
        self.assertEqual(seen["scope"], (False, True, False))
        self.assertEqual(seen["argv"], ["main.py", "-c", "/tmp/cx-test-run.ini", "--yes"])

    def test_chapters_and_task_center_without_yes(self):
        seen = self._run_flow(["setup_wizard.py"], (True, True, False, "task"), submit_answer=True)
        self.assertTrue(seen["ask_points"])
        self.assertTrue(seen["ask_tasks"])
        self.assertEqual(seen["scope"], (True, True, False))
        self.assertEqual(seen["argv"], ["main.py", "-c", "/tmp/cx-test-run.ini"])

    def test_chapters_only_does_not_ask_tasks(self):
        seen = self._run_flow(["setup_wizard.py"], (True, False, False, ""), submit_answer=True)
        self.assertTrue(seen["ask_points"])
        self.assertFalse(seen["ask_tasks"])

    def test_cancel_does_not_run_main(self):
        seen = self._run_flow(["setup_wizard.py"], (True, False, False, ""), submit_answer=False)
        self.assertNotIn("argv", seen)

    def test_continue_after_board_round_uses_fresh_chapter_only_scope(self):
        """“继续刷其他课程”必须重新取本轮范围，不能沿用上一轮讨论区模式。"""
        course = {"courseId": 1, "clazzId": 2, "title": "测试课"}
        scopes = iter([(False, False, True, "board"), (True, False, False, "")])
        actions = iter(["again", "exit"])
        written = []
        ran = []

        def fake_choose_courses(cx, **kwargs):
            return [(course, 0, 0)]

        def fake_build_config(username, password, plan, chapters_enabled=True,
                              task_center_enabled=True, only_discussion=False,
                              discussion_mode="task"):
            written.append((chapters_enabled, task_center_enabled,
                            only_discussion, discussion_mode))
            return "/tmp/cx-test-run.ini"

        def fake_run_main():
            ran.append(list(sys.argv))

        with mock.patch.object(wizard, "ensure_api_key"), \
             mock.patch.object(wizard, "ensure_global_prefs"), \
             mock.patch.object(wizard, "pick_user",
                               return_value=("13800000000", "pw", mock.Mock(), "测试用户")), \
             mock.patch.object(wizard, "choose_study_scope", side_effect=lambda: next(scopes)), \
             mock.patch.object(wizard, "choose_courses", side_effect=fake_choose_courses), \
             mock.patch.object(wizard, "build_config", side_effect=fake_build_config), \
             mock.patch.object(wizard, "ask_after_run", side_effect=lambda *a, **k: next(actions)), \
             mock.patch.object(wizard, "ask_yes_no", return_value=True), \
             mock.patch.object(sys, "argv", ["setup_wizard.py"]), \
             mock.patch.dict(sys.modules, {"main": mock.Mock(main=fake_run_main)}):
            self.assertEqual(wizard._main_inner(), 0)

        self.assertEqual(written, [
            (False, False, True, "board"),
            (True, False, False, ""),
        ])
        self.assertEqual(len(ran), 2)


if __name__ == "__main__":
    unittest.main()
