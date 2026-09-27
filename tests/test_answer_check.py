# -*- coding: utf-8 -*-
"""答案匹配与题库解析测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import answer_check as ac  # noqa: E402
from api.answer import resolve_provider_name, TikuGo, DummyTiku, _extract_llm_answer  # noqa: E402


class MatchChoiceTestCase(unittest.TestCase):
    OPTIONS = "A. 苹果\nB. 香蕉\nC. 橙子\nD. 西瓜"

    def test_letter_answer(self):
        self.assertEqual(ac.match_choice("C", self.OPTIONS), "C")
        self.assertEqual(ac.match_choice("c", self.OPTIONS), "C")

    def test_text_answer(self):
        self.assertEqual(ac.match_choice("橙子", self.OPTIONS), "C")
        self.assertEqual(ac.match_choice("C. 橙子", self.OPTIONS), "C")

    def test_multiple_letters(self):
        self.assertEqual(ac.match_choice("ABD", self.OPTIONS, multiple=True), "ABD")
        self.assertEqual(ac.match_choice("A,C", self.OPTIONS, multiple=True), "AC")
        self.assertEqual(ac.match_choice("苹果#橙子", self.OPTIONS, multiple=True), "AC")

    def test_single_rejects_multiletter(self):
        # 单选题不应把 "AB" 当成选项字母
        self.assertEqual(ac.match_choice("AB", self.OPTIONS), "")

    def test_no_false_prefix_strip(self):
        # 答案 "Python" 不应被当作选项编号 P 去掉首字母
        opts = "A. Java\nB. Python\nC. C++"
        self.assertEqual(ac.match_choice("Python", opts), "B")

    def test_prefix_vs_exact(self):
        # 精确匹配优先于包含匹配
        opts = "A. 北京\nB. 北京大学"
        self.assertEqual(ac.match_choice("北京", opts), "A")
        self.assertEqual(ac.match_choice("北京大学", opts), "B")

    def test_letter_that_is_also_body(self):
        # 纯字母答案恰好等于某选项正文时，按正文匹配
        opts = "A. DNA\nB. RNA\nC. 蛋白质"
        self.assertEqual(ac.match_choice("DNA", opts), "A")

    def test_unmatched_returns_empty(self):
        self.assertEqual(ac.match_choice("完全不相关的答案xyz", self.OPTIONS), "")


class ComparableAnswerTestCase(unittest.TestCase):
    def test_judgement(self):
        self.assertEqual(ac.comparable_answer("√", "判断题"), ac.comparable_answer("正确", "判断题"))
        self.assertNotEqual(ac.comparable_answer("对", "判断题"), ac.comparable_answer("错", "判断题"))

    def test_multiple_order_insensitive(self):
        self.assertEqual(ac.comparable_answer("B A D", "多选题"), ac.comparable_answer("A,B,D", "多选题"))

    def test_empty(self):
        self.assertEqual(ac.comparable_answer("", "单选题"), "")


class CutTestCase(unittest.TestCase):
    def test_strong_delimiter_priority(self):
        # 逗号是句内标点，答案含换行时应优先按换行切分
        self.assertEqual(ac.cut("甲、乙、丙"), ["甲", "乙", "丙"])
        self.assertEqual(ac.cut("改革开放，是关键一招\n另一句"), ["改革开放，是关键一招", "另一句"])

    def test_single_kept(self):
        self.assertEqual(ac.cut("整段答案没有分隔符"), ["整段答案没有分隔符"])


class ProviderTestCase(unittest.TestCase):
    def test_resolve_names(self):
        self.assertEqual(resolve_provider_name("TikuGo"), "TikuGo")
        self.assertEqual(resolve_provider_name("tikugo"), "TikuGo")
        self.assertEqual(resolve_provider_name("go"), "TikuGo")
        self.assertEqual(resolve_provider_name("AI"), "AI")
        self.assertIsNone(resolve_provider_name("不存在的题库"))
        self.assertIsNone(resolve_provider_name(""))

    def test_dummy_disabled(self):
        self.assertTrue(DummyTiku().DISABLE)

    def test_tikugo_defaults_no_crash(self):
        # 未提供任何 tiku 配置时也应能初始化（GO题无需 token）
        tiku = TikuGo()
        tiku.config_set({"submit": "false", "cover_rate": "0.9"})
        tiku.init_tiku()
        self.assertFalse(tiku.DISABLE)


class LLMAnswerTestCase(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(_extract_llm_answer('{"Answer": ["北京"]}'), "北京")

    def test_markdown_wrapped(self):
        self.assertEqual(_extract_llm_answer('```json\n{"Answer": ["A", "B"]}\n```'), "A\nB")

    def test_with_think_block(self):
        self.assertEqual(_extract_llm_answer('<think>思考中...</think>{"Answer": ["对"]}'), "对")

    def test_garbage(self):
        self.assertIsNone(_extract_llm_answer("无法解析的内容"))
        self.assertIsNone(_extract_llm_answer(""))


class TikuCustomTestCase(unittest.TestCase):
    """自建题库服务器（/api/search 接口约定）."""

    def _tiku(self, responses):
        from api import answer
        tiku = answer.TikuCustom()
        tiku.config_set({"custom_url": "http://127.0.0.1:8001/api/search", "custom_key": "k"})
        tiku.init_tiku()
        sent = []

        class _Resp:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200
                self.text = str(payload)

            def json(self):
                return self.payload

        def fake_post(url, json=None, timeout=None):
            sent.append((url, json))
            return _Resp(responses.pop(0))

        original = answer.requests.post
        answer.requests.post = fake_post
        self.addCleanup(setattr, answer.requests, "post", original)
        return tiku, sent

    def test_request_and_nested_answer(self):
        tiku, sent = self._tiku([{"code": -1, "msg": "查询成功", "data": {"answer": "A#C", "num": "1"}}])
        answer = tiku._query({"title": "【多选题】以下哪些是安全防护措施？", "type": "multiple",
                              "options": "A 戴安全帽\nB 酒后作业\nC 系安全带"})
        self.assertEqual(answer, "A#C")
        url, payload = sent[0]
        self.assertEqual(payload, {"question": "以下哪些是安全防护措施？", "type": "1",
                                   "options": ["戴安全帽", "酒后作业", "系安全带"], "key": "k"})
        self.assertEqual(ac.match_choice(answer, ["A 戴安全帽", "B 酒后作业", "C 系安全带"], multiple=True), "AC")

    def test_flat_answer_and_miss(self):
        tiku, _ = self._tiku([{"code": 1, "answer": "正确"}, {"code": 0, "msg": "未找到答案", "data": {}}])
        self.assertEqual(tiku._query({"title": "判断", "type": "judgement", "options": ""}), "正确")
        self.assertIsNone(tiku._query({"title": "没有的题", "type": "single", "options": "A 1\nB 2"}))

    def test_disabled_without_url(self):
        from api import answer
        tiku = answer.TikuCustom()
        tiku.config_set({"custom_key": "k"})
        tiku.init_tiku()
        self.assertTrue(tiku.DISABLE)


if __name__ == "__main__":
    unittest.main()
