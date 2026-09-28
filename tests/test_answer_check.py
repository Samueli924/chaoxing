import unittest

from api.answer_check import check_answer, check_multiple, check_single, cut


class FakeTiku:
    is_manual = False
    skip_answer_validation = False
    true_list = ['正确', '对']
    false_list = ['错误', '错']


class TestCheckSingleDunhaoFix(unittest.TestCase):
    def test_answer_with_dunhao_not_rejected_as_multiple(self):
        self.assertTrue(check_single('坚持独立负责、不参与国际组织的活动'))
        self.assertTrue(check_single('点面结合、标本兼治'))

    def test_comma_is_sentence_punctuation(self):
        self.assertTrue(check_single('对,错'))
        self.assertTrue(check_single('对，错'))

    def test_strong_delimiters_still_reject(self):
        self.assertFalse(check_single('答案1\n答案2'))
        self.assertFalse(check_single('答案1|答案2'))
        self.assertFalse(check_single('答案1#答案2'))
        self.assertFalse(check_single('答案1\t答案2'))
        self.assertFalse(check_single('答案1\r答案2'))

    def test_plain_answers(self):
        self.assertTrue(check_single('生态文明'))
        self.assertFalse(check_single(None))
        self.assertFalse(check_single('   '))


class TestCutStillSplitsOnDunhao(unittest.TestCase):
    def test_cut_splits_multiple_answers(self):
        self.assertEqual(cut('尊重自然、顺应自然、保护自然'),
                         ['尊重自然', '顺应自然', '保护自然'])

    def test_check_multiple_with_dunhao(self):
        self.assertTrue(check_multiple('尊重自然、顺应自然'))


class TestCheckAnswerWithFakeTiku(unittest.TestCase):
    def setUp(self):
        self.tiku = FakeTiku()

    def test_single_with_dunhao_passes(self):
        self.assertTrue(check_answer('坚持独立负责、不参与国际组织的活动', 'single', self.tiku))

    def test_single_judgement_word_rejected(self):
        self.assertFalse(check_answer('正确', 'single', self.tiku))

    def test_manual_mode_trusted(self):
        self.tiku.is_manual = True
        self.assertTrue(check_answer('任意内容', 'single', self.tiku))


if __name__ == '__main__':
    unittest.main()
