# -*- coding: utf-8 -*-
"""去 AI 味文案生成器的离线测试（不联网）."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-test-"))

from api.ai_writer import HumanLikeWriter  # noqa: E402


class CleanTestCase(unittest.TestCase):
    def test_strips_ai_smell(self):
        raw = "首先，我们要明白战略管理的意义。其次，它很重要。\n\n总而言之，谢谢。"
        out = HumanLikeWriter.clean(raw)
        for word in ("首先", "其次", "总而言之"):
            self.assertNotIn(word, out)
        self.assertIn("战略管理的意义", out)

    def test_strips_markdown_noise(self):
        raw = "下面是回答：\n\n" + chr(96) * 3 + "python\ncode\n" + chr(96) * 3 + "\n- 第一条\n1. 第二条\n## 小标题"
        out = HumanLikeWriter.clean(raw)
        self.assertNotIn(chr(96), out)
        self.assertNotIn("##", out)
        self.assertIn("第一条", out)

    def test_style_reference(self):
        text = HumanLikeWriter.style_reference([
            {"content": "我觉得战略就是取舍"},
            "先活下去再谈发展",
        ])
        self.assertIn("1. 我觉得战略就是取舍", text)
        self.assertIn("2. 先活下去再谈发展", text)


class WriterTestCase(unittest.TestCase):
    def setUp(self):
        self.writer = HumanLikeWriter({"endpoint": "https://example.com/v1",
                                       "key": "sk-test", "model": "test-model"})

    def test_available(self):
        self.assertTrue(self.writer.available)
        self.assertFalse(HumanLikeWriter({}).available)

    def test_answer_prompt_includes_question_and_refs(self):
        captured = {}

        def fake_chat(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return "首先，我觉得战略管理就是帮公司在不确定里做选择。总之就这样。"

        with mock.patch.object(self.writer, "_chat", side_effect=fake_chat):
            out = self.writer.answer("什么是战略管理？", requirement="结合实际",
                                     references=[{"content": "战略是取舍"}])
        self.assertIn("战略管理", captured["user"])
        self.assertIn("战略是取舍", captured["user"])
        self.assertIn("不能有 AI 腔", captured["system"])
        self.assertNotIn("首先", out)
        self.assertNotIn("总之", out)

    def test_discussion_uses_existing_posts(self):
        captured = {}

        def fake_chat(system, user, **kwargs):
            captured["user"] = user
            return "我赞同前面同学的看法，使命是长期方向，愿景更像目标画面。"

        posts = [{"content": "我认为使命是长期方向"}, {"content": "愿景更像是目标画面"}]
        with mock.patch.object(self.writer, "_chat", side_effect=fake_chat):
            out = self.writer.discussion("企业使命与愿景的区别", existing_posts=posts)
        self.assertIn("我认为使命是长期方向", captured["user"])
        # 用户要求：讨论回复必须是"班里中等水平"的普通回复，不许抖机灵/写成小论文
        self.assertIn("中等水平", captured["user"])
        self.assertIn("不要写巧妙的类比", captured["user"])
        self.assertIn("不要编造个人经历", captured["user"])
        self.assertTrue(out.startswith("我赞同"))

    def test_practice_answer_uses_context(self):
        captured = {}

        def fake_chat(system, user, **kwargs):
            captured["user"] = user
            return "我觉得这个选择要看企业的资源和外部环境。"

        with mock.patch.object(self.writer, "_chat", side_effect=fake_chat):
            out = self.writer.practice_answer(
                "企业应该如何选择战略？", requirement="结合案例", context="竞争优势"
            )
        self.assertIn("竞争优势", captured["user"])
        self.assertIn("结合案例", captured["user"])
        self.assertEqual(out, "我觉得这个选择要看企业的资源和外部环境。")

    def test_choose_options_returns_normalized_letters(self):
        with mock.patch.object(self.writer, "_chat", return_value="答案是 C、A"):
            self.assertEqual(
                self.writer.choose_options(
                    "哪项属于战略选择？",
                    [{"option": "A", "optionContent": "方向"},
                     {"option": "B", "optionContent": "颜色"},
                     {"option": "C", "optionContent": "取舍"}],
                    multiple=True,
                ),
                "AC",
            )

    def test_choose_judgement_is_strict(self):
        with mock.patch.object(self.writer, "_chat", return_value="对"):
            self.assertEqual(self.writer.choose_judgement("战略需要取舍"), "对")
        with mock.patch.object(self.writer, "_chat", return_value="这个说法错"):
            self.assertEqual(self.writer.choose_judgement("战略没有成本"), "错")

    def test_no_config_raises(self):
        writer = HumanLikeWriter({})
        with self.assertRaises(RuntimeError):
            writer.answer("问题")


class ThinkingPolicyPayloadTestCase(unittest.TestCase):
    """Thinking 策略."""
    # auto（默认）= 第一次请求不带 thinking，让 V4.1 flash 自己推理；
    # 正文为空才自动降级成 thinking=disabled 再试一次。

    @staticmethod
    def _fake_response(content):
        class R:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return R()

    def test_auto_keeps_thinking_untouched(self):
        writer = HumanLikeWriter({"endpoint": "https://api.deepseek.com/v1",
                                  "key": "sk-test", "model": "deepseek-flash"})
        captured = {}

        def fake_post(url, headers=None, json=None, **kwargs):
            captured["payload"] = json
            return self._fake_response("拿到正文了")

        with mock.patch("api.ai_writer.requests.post", side_effect=fake_post):
            out = writer._chat("system", "user", max_tokens=64)
        self.assertEqual(out, "拿到正文了")
        self.assertNotIn("thinking", captured["payload"])

    def test_empty_content_falls_back_to_thinking_disabled(self):
        writer = HumanLikeWriter({"endpoint": "https://api.deepseek.com/v1",
                                  "key": "sk-test", "model": "deepseek-flash"})
        payloads = []

        def fake_post(url, headers=None, json=None, **kwargs):
            payloads.append(dict(json or {}))   # 复制快照：payload 会被原地复用
            if len(payloads) == 1:
                return self._fake_response("")      # 老版本：正文为空
            return self._fake_response("第二次拿到正文")

        with mock.patch("api.ai_writer.requests.post", side_effect=fake_post), \
             mock.patch("api.ai_writer.time.sleep", return_value=None):
            out = writer._chat("system", "user", max_tokens=64)
        self.assertEqual(out, "第二次拿到正文")
        self.assertNotIn("thinking", payloads[0])
        self.assertEqual(payloads[1]["thinking"], {"type": "disabled"})

    def test_off_mode_disables_thinking_first(self):
        writer = HumanLikeWriter({"endpoint": "https://api.deepseek.com/v1",
                                  "key": "sk-test", "model": "deepseek-flash",
                                  "thinking": "off"})
        captured = {}

        def fake_post(url, headers=None, json=None, **kwargs):
            captured["payload"] = json
            return self._fake_response("ok")

        with mock.patch("api.ai_writer.requests.post", side_effect=fake_post):
            writer._chat("system", "user", max_tokens=64)
        self.assertEqual(captured["payload"]["thinking"], {"type": "disabled"})

    def test_empty_content_raises_after_retry(self):
        writer = HumanLikeWriter({"endpoint": "https://api.deepseek.com/v1",
                                  "key": "sk-test", "model": "deepseek-flash"})
        calls = {"n": 0}

        def fake_post(url, headers=None, json=None, **kwargs):
            calls["n"] += 1
            return self._fake_response("")

        with mock.patch("api.ai_writer.requests.post", side_effect=fake_post), \
             mock.patch("api.ai_writer.time.sleep", return_value=None):
            with self.assertRaises(RuntimeError):
                writer._chat("system", "user", max_tokens=64)
        self.assertEqual(calls["n"], 2)


class ExamPromptTestCase(unittest.TestCase):
    """AI 实践的选择/判断题要按“先判断再给答案”的格式解析，避免误读推理过程里的字母."""

    def _writer(self):
        return HumanLikeWriter({"endpoint": "https://api.deepseek.com/v1",
                                "key": "sk-test", "model": "deepseek-flash"})

    def test_extract_letters_prefers_answer_marker(self):
        raw = "B 项说的是职能层，C 项把公司层和业务层混在一起了。\n答案：AC"
        self.assertEqual(HumanLikeWriter._extract_letters(raw, {"A", "B", "C"}),
                         ["A", "C"])

    def test_extract_letters_falls_back_to_last_line(self):
        raw = "这题考查公司层战略。\nB"
        self.assertEqual(HumanLikeWriter._extract_letters(raw, {"A", "B"}), ["B"])

    def test_choose_options_keeps_single_letter(self):
        w = self._writer()
        with mock.patch.object(w, "_chat", return_value="先排除 B、D。\n答案：C"):
            self.assertEqual(
                w.choose_options("关于公司层战略的说法正确的是？",
                                 [{"option": "A", "optionContent": "x"},
                                  {"option": "C", "optionContent": "y"}]),
                "C",
            )

    def test_choose_judgement_reads_marker(self):
        w = self._writer()
        with mock.patch.object(w, "_chat", return_value="这句话把两个概念混在一起。\n答案：错"):
            self.assertEqual(w.choose_judgement("公司层战略就是业务层战略。"), "错")

    def test_choose_judgement_rejects_vague_output(self):
        w = self._writer()
        with mock.patch.object(w, "_chat", return_value="这道题要看具体情况。"):
            with self.assertRaises(ValueError):
                w.choose_judgement("公司层战略就是业务层战略。")



    def test_recent_feedback_extracts_platform_explanation(self):
        data = {"messageList": [
            {"role": 2, "content": json.dumps({"questionStem": "q1", "preAppendContent": "回答正确！本题考核公司层战略。"})},
            {"role": 1, "content": json.dumps({"content": "B"})},
            {"role": 2, "content": json.dumps({"questionStem": "q2",
                                               "preAppendContent": "真遗憾，回答错误了呢。公司层战略是企业最高管理层制定的面向企业整体的总体战略，核心是确定经营领域。"})},
        ]}
        hints = HumanLikeWriter._recent_feedback(data)
        self.assertIn("公司层战略", hints)
        self.assertIn("真遗憾", hints)

    def test_recent_feedback_ignores_non_feedback(self):
        data = {"messageList": [{"role": 2, "content": json.dumps({"questionStem": "只有题目"})}]}
        self.assertEqual(HumanLikeWriter._recent_feedback(data), "")

    def test_choice_vote_takes_majority(self):
        w = self._writer()
        outputs = iter(["答案：A", "答案：B", "答案：A", "答案：A"])
        with mock.patch.object(w, "_chat", side_effect=lambda *a, **k: next(outputs)):
            self.assertEqual(
                w.choose_options("关于公司层战略的说法正确的是？",
                                 [{"option": "A", "optionContent": "x"},
                                  {"option": "B", "optionContent": "y"}]),
                "A",
            )

    def test_judgement_vote_takes_majority(self):
        w = self._writer()
        outputs = iter(["答案：对", "答案：错", "答案：对", "答案：对"])
        with mock.patch.object(w, "_chat", side_effect=lambda *a, **k: next(outputs)):
            self.assertEqual(w.choose_judgement("公司层战略就是业务层战略。"), "对")

    def test_vote_survives_partial_failures(self):
        w = self._writer()
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("网络抖动")
            return "答案：错"

        with mock.patch.object(w, "_chat", side_effect=flaky):
            self.assertEqual(w.choose_judgement("这句话对吗？"), "错")


if __name__ == "__main__":
    unittest.main()
