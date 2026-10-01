# -*- coding: utf-8 -*-
"""真人化回归：任何"提交给平台"的文本都不能露出 AI/机器痕迹（不联网）."""
#
# 需要防止的错误格式：AI实践选择题被拼成
# "选 D。D：……。依据：回答正确！……平台判据：……" —— 既不是人的作答格式，
# 又把平台自己的判分反馈回显了出来。
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-test-"))

from api.ai_writer import HumanLikeWriter  # noqa: E402
from api.task_center import TaskCenter  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "audit"))
import importlib.util  # noqa: E402

_AUDIT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "audit", "01_human_likeness_audit.py",
)
_spec = importlib.util.spec_from_file_location("human_audit", _AUDIT_PATH)
human_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(human_audit)


class ObjectiveAnswerTestCase(unittest.TestCase):
    """选择题/判断题只提交字母或对错，不能带解释、不能回显平台反馈."""

    class Writer:
        def __init__(self, choice="D", judge="对"):
            """Initialize configuration and runtime state."""
            self.choice = choice
            self.judge = judge

        def choose_options(self, question, options, multiple=False, context="", exclude=None):
            return self.choice

        def choose_judgement(self, question, context="", exclude=None):
            return self.judge

    def _turn(self, qtype, options):
        return {
            "questionStem": "关于公司层战略的说法正确的是？",
            "questionTypeInt": qtype,
            "options": options,
            "preAppendContent": "真遗憾，回答错误了呢。本题考核知识点为公司层战略。",
        }

    def test_single_choice_returns_bare_letter(self):
        tc = TaskCenter(object(), {}, writer=self.Writer(choice="D"))
        answer = tc._ai_answer(
            self._turn("0", [{"option": "C", "optionContent": "c"}, {"option": "D", "optionContent": "d"}]),
            {"messageList": []},
        )
        self.assertEqual(answer, "D")

    def test_single_choice_retry_still_bare_letter(self):
        tc = TaskCenter(object(), {}, writer=self.Writer(choice="D"))
        answer = tc._ai_answer(
            self._turn("0", [{"option": "C", "optionContent": "c"}, {"option": "D", "optionContent": "d"}]),
            {"messageList": []},
            exclude={"D"},
        )
        self.assertRegex(answer, r"^[A-E]$")

    def test_multiple_choice_returns_letters_only(self):
        tc = TaskCenter(object(), {}, writer=self.Writer(choice="BD"))
        answer = tc._ai_answer(
            self._turn("1", [{"option": "A", "optionContent": "a"},
                             {"option": "B", "optionContent": "b"},
                             {"option": "D", "optionContent": "d"}]),
            {"messageList": []},
        )
        self.assertRegex(answer, r"^[A-E]+$")

    def test_no_platform_feedback_leaks_into_answer(self):
        tc = TaskCenter(object(), {}, writer=self.Writer(choice="D"))
        answer = tc._ai_answer(
            self._turn("0", [{"option": "D", "optionContent": "d"}]),
            {"messageList": [{"role": 2, "content": json.dumps(
                {"preAppendContent": "回答正确！本题考核知识点为公司层战略。"})}]},
        )
        for word in ("依据", "回答正确", "考核知识点", "平台判据"):
            self.assertNotIn(word, answer)


class AuditToolTestCase(unittest.TestCase):
    def test_flags_the_real_incident(self):
        bad = [{
            "kind": "AI实践客观题",
            "text": "选 D。D：职能层战略需要支撑企业总体战略。依据：回答正确！",
        }]
        self.assertGreater(human_audit.audit_all(bad)["problems"], 0)

    def test_clean_text_passes(self):
        good = [{
            "kind": "主题讨论",
            "text": "使命和考核对不上，墙上那句话很快就没人提了，这个反差课下聊起来挺有意思。",
        }]
        self.assertEqual(human_audit.audit_all(good)["problems"], 0)

    def test_flags_fabricated_resume(self):
        """在校学生的"我实习那家公司"就是编的（AGENTS.md 4.9 明确禁止）."""
        bad = [{"kind": "主题讨论",
                "text": "我之前实习那家公司就这样，使命写得挺响，实际考核全是拉新和续费。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("编造的个人琐事", rules)
        self.assertTrue(HumanLikeWriter.style_problems(
            "我之前实习那家公司就这样，使命写得挺响，实际考核全是拉新和续费。"))

    def test_flags_fabricated_part_time_job(self):
        """实测模型会写"我在奶茶店做过兼职"——同样是没有依据的个人经历."""
        text = "我在奶茶店做过兼职，店长从来不提什么使命，但排班先照顾谁心里有数。"
        rules = {rule for item in human_audit.audit_all(
            [{"kind": "主题讨论", "text": text}])["items"] for rule, _ in item["issues"]}
        self.assertIn("编造的个人琐事", rules)
        self.assertTrue(HumanLikeWriter.style_problems(text))

    def test_flags_ai_connectors_and_markdown(self):
        bad = [{
            "kind": "思考题",
            "text": "首先，使命很重要。其次，愿景也很重要。\n- 第一点\n- 第二点",
        }]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("AI 腔", rules)
        self.assertIn("排版痕迹", rules)

    def test_flags_closing_cliche(self):
        bad = [{"kind": "思考题",
                "text": "课上讲了不少，我觉得关键还是先把概念分清楚，真正难的是让下面的人知道明天改什么。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("金句", rules)

    def test_flags_unsourced_specifics(self):
        bad = [{"kind": "主题讨论",
                "text": "上学期我们小组做过一个校园二手平台的案例分析，三个月只成交几十单，后来才慢慢跑起来。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("无来源的假具体", rules)

    def test_flags_uniform_habits(self):
        bad = [{"kind": "思考题",
                "text": "我觉得这块挺重要的，其实老师上课讲过，反正考试大概率会考，可能还是要记一下。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("口癖分布过密", rules)

    def test_single_sample_does_not_trigger_batch_rules(self):
        one = [{"kind": "主题讨论",
                "text": "使命和考核对不上，墙上那句话很快就没人提了，这个反差课下聊起来挺有意思。"}]
        self.assertEqual(human_audit.audit_all(one)["problems"], 0)

    def test_flags_batch_level_fingerprint(self):
        batch = [
            {"kind": "思考题", "text": "我觉得这门课挺有用的，其实老师讲过好几个例子。"},
            {"kind": "作业简答", "text": "我觉得重点是环境分析，其实课上举过不少例子。"},
        ]
        rules = {rule for item in human_audit.audit_all(batch)["items"] for rule, _ in item["issues"]}
        self.assertIn("整批口癖雷同", rules)

    def test_flags_structure_cliche(self):
        bad = [{"kind": "思考题",
                "text": "课上讲过这几层的关系。使命管的是为什么干，愿景管的是干成什么样，目标管的是今年先干什么。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("三层排比/对偶", rules)

    def test_flags_fake_personal_anecdote(self):
        bad = [{"kind": "作业简答",
                "text": "我上个月注册一个App，光隐私协议就弹了三次，说明合规成本确实在涨。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("编造的个人琐事", rules)

    def test_flags_dangling_reference_without_context(self):
        bad = [{"kind": "主题讨论",
                "text": "奶茶店那个例子挺直观的。我觉得使命和愿景确实容易混。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("引用不存在的前文", rules)

    def test_dangling_reference_ok_only_with_real_refs(self):
        ok = [{"kind": "主题讨论",
               "context_refs": ["我觉得奶茶店那个例子挺直观的，使命就是让大家喝到便宜好喝的奶茶。"],
               "text": "奶茶店那个例子挺直观的。我觉得使命和愿景确实容易混着说。"}]
        rules = {rule for item in human_audit.audit_all(ok)["items"] for rule, _ in item["issues"]}
        self.assertNotIn("引用不存在的前文", rules)

    def test_context_flag_alone_is_not_enough(self):
        """光声明 has_context 不行：必须真带上被引用的原文."""
        bad = [{"kind": "主题讨论", "has_context": True,
                "text": "奶茶店那个例子挺直观的。我觉得使命和愿景确实容易混着说。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("引用不存在的前文", rules)

    def test_flags_weak_ending_tic(self):
        bad = [{"kind": "思考题",
                "text": "课上讲过这三者的关系。使命是企业存在的理由，愿景是将来变成什么样。不过这块我其实没太想明白。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("示弱收尾口癖", rules)

    def test_flags_claimed_community_experience(self):
        bad = [{"kind": "主题讨论",
                "text": "使命和愿景容易混。我们小组上次讨论时也卡在这里，有人觉得愿景要写长一点。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("认领共同经历", rules)

    def test_flags_missing_course_anchor(self):
        bad = [{"kind": "思考题",
                "text": "使命是企业存在的理由，回答的是为什么要做这件事。愿景是往远处看的一个画面，说清楚将来想变成什么样子。目标则更落地，把愿景拆成一段时间内能做到的事。"}]
        rules = {rule for item in human_audit.audit_all(bad)["items"] for rule, _ in item["issues"]}
        self.assertIn("没有课程锚点", rules)

    def test_batch_structure_repetition(self):
        batch = [
            {"kind": "思考题", "text": "先说使命。使命管的是为什么干，愿景管的是干成什么样，目标管的是今年干什么。"},
            {"kind": "作业简答", "text": "换个说法。使命管的是为什么要做，愿景管的是做到什么程度，目标管的是当下先做什么。"},
        ]
        rules = {rule for item in human_audit.audit_all(batch)["items"] for rule, _ in item["issues"]}
        self.assertIn("整批结构雷同", rules)


if __name__ == "__main__":
    unittest.main()
