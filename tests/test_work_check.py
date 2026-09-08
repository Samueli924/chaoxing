# -*- coding: utf-8 -*-
"""章节检测判分修复的回归测试: 答案归一化、宽松正则解析与 parse_ok 标记."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.base import _parse_work_record_detail, normalize_answer_text  # noqa: E402


class NormalizeAnswerTextTest(unittest.TestCase):
    def test_judgement_variants(self):
        """对/错 与 true/false 两套表述应归一到同一值."""
        self.assertEqual(normalize_answer_text('true'), normalize_answer_text('对'))
        self.assertEqual(normalize_answer_text('false'), normalize_answer_text('错误'))
        self.assertNotEqual(normalize_answer_text('true'), normalize_answer_text('false'))

    def test_letter_answer_kept(self):
        """纯字母答案不能被前缀剥离破坏."""
        self.assertEqual(normalize_answer_text('B'), 'B')
        self.assertEqual(normalize_answer_text('a'), 'A')
        self.assertEqual(normalize_answer_text('10'), '10')

    def test_letter_prefix_stripped(self):
        """'B.按ESC键' 与 '按ESC键' 应视为同一答案."""
        self.assertEqual(normalize_answer_text('B. 按 ESC 键'), normalize_answer_text('按ESC键'))

    def test_same_format_multi_choice(self):
        """同格式的多选答案归一后必然相等(跨格式差异由分数兜底, 见方案 F2 局限)."""
        self.assertEqual(normalize_answer_text('A、B、C'), normalize_answer_text('A、B、C'))
        self.assertEqual(normalize_answer_text('A,B,C'), normalize_answer_text('ABC'))

    def test_empty_and_none(self):
        self.assertEqual(normalize_answer_text(None), '')
        self.assertEqual(normalize_answer_text(''), '')


def _detail_html(answer_block):
    return (
        '<div class="TiMu singleQuesId" data="100">'
        '<div class="Zy_TItle"><div>题干</div></div>'
        + answer_block +
        '</div>'
    )


class ParseWorkRecordDetailTest(unittest.TestCase):
    def test_exact_structure(self):
        """原有精确结构必须继续命中(向后兼容)."""
        html = _detail_html(
            '<span>我的答案：</span><div class="fl answerCon"> B </div>'
            '<span>正确答案：</span><div class="fl answerCon"> B </div>')
        qs = _parse_work_record_detail(html)
        self.assertEqual(len(qs), 1)
        self.assertTrue(qs[0]['parse_ok'])
        self.assertEqual(qs[0]['my_answer'], 'B')

    def test_extra_class_variant(self):
        """answerCon 带额外 class 的页面变体应命中宽松模式."""
        html = _detail_html(
            '<span>我的答案：</span><div class="fl answerCon colorDeep">A</div>'
            '<span>正确答案：</span><div class="fl answerCon colorGreen">B</div>')
        qs = _parse_work_record_detail(html)
        self.assertTrue(qs[0]['parse_ok'])
        self.assertEqual(qs[0]['my_answer'], 'A')
        self.assertEqual(qs[0]['correct_answer'], 'B')

    def test_span_variant(self):
        """答案写在 span 而非 div 的页面变体应命中."""
        html = _detail_html(
            '<span>我的答案：</span><span class="colorRed">true</span>'
            '<span>正确答案：</span><span class="colorGreen">对</span>')
        qs = _parse_work_record_detail(html)
        self.assertTrue(qs[0]['parse_ok'])
        self.assertEqual(qs[0]['my_answer'], 'true')

    def test_missing_answer_marks_unknown(self):
        """任一侧未命中 → parse_ok=False, 避免空串比较误判全错."""
        html = _detail_html('<span>我的答案：</span><div class="fl answerCon">A</div>')
        qs = _parse_work_record_detail(html)
        self.assertFalse(qs[0]['parse_ok'])
        self.assertEqual(qs[0]['my_answer'], 'A')
        self.assertEqual(qs[0]['correct_answer'], '')


if __name__ == '__main__':
    unittest.main()
