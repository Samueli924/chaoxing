import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from api.answer import CacheDAO, Tiku, TikuFallback
from api.base import Chaoxing, SessionManager, StudyResult, resolve_question_answer


DEFAULTS = dict(submit='false', cover_rate='0.9', true_list='正确,对,√,是', false_list='错误,错,×,否,不对,不正确')


class Provider(Tiku):
    def __init__(self, name, answers):
        super().__init__()
        self.name = name
        self.answers = answers
        self.calls = []
        self.config_set(dict(DEFAULTS))

    def _query(self, question):
        self.calls.append(question['title'])
        answer = self.answers.get(question['title'])
        if isinstance(answer, Exception):
            raise answer
        return answer


class AnswerFallbackTests(unittest.TestCase):
    def setUp(self):
        for name in ('api.answer.logger', 'api.base.logger'):
            logger_patch = patch(name)
            logger_patch.start()
            self.addCleanup(logger_patch.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache = CacheDAO(Path(folder.name) / 'cache.json')
        cache_patch = patch('api.answer.CacheDAO', return_value=self.cache)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.question = dict(title='人口分界线', type='single', options='A.黑河，腾冲\nB.北京，广州')

    def chain(self, primary_answers, fallback_answers):
        first = Provider('主题库', primary_answers)
        second = Provider('AI备用', fallback_answers)
        chain = TikuFallback([first, second])
        chain.config_set(dict(DEFAULTS))
        chain.init_tiku()
        return chain, first, second

    def query(self, chain, questions=None):
        return chain.query_all(questions or [self.question.copy()],
                               answer_validator=lambda q, answer, provider: bool(resolve_question_answer(q, answer, provider)))

    def test_unmatched_primary_answer_uses_ai(self):
        chain, first, second = self.chain({'人口分界线': '无法对应的地点'}, {'人口分界线': '黑河，腾冲'})
        self.assertEqual(self.query(chain), ['黑河，腾冲'])
        self.assertEqual(second.calls, ['人口分界线'])
        self.assertEqual(self.cache.get_cache('人口分界线'), '黑河，腾冲')

    def test_matched_primary_does_not_call_ai(self):
        chain, first, second = self.chain({'人口分界线': '黑河，腾冲'}, {'人口分界线': '北京，广州'})
        self.assertEqual(self.query(chain), ['黑河，腾冲'])
        self.assertEqual(second.calls, [])

    def test_unmatched_cached_answer_does_not_block_fallback(self):
        self.cache.add_cache('人口分界线', '错误缓存内容')
        chain, first, second = self.chain({'人口分界线': '另一段无关内容'}, {'人口分界线': '黑河，腾冲'})
        self.assertEqual(self.query(chain), ['黑河，腾冲'])
        self.assertEqual(second.calls, ['人口分界线'])
        self.assertEqual(self.cache.get_cache('人口分界线'), '黑河，腾冲')

    def test_only_unresolved_questions_reach_ai(self):
        other = dict(title='另一题', type='single', options='A.地理学\nB.历史学')
        chain, first, second = self.chain({'人口分界线': '黑河，腾冲'}, {'另一题': '历史学'})
        self.assertEqual(self.query(chain, [self.question.copy(), other]), ['黑河，腾冲', '历史学'])
        self.assertEqual(second.calls, ['另一题'])

    def test_ai_failure_stays_unresolved(self):
        chain, first, second = self.chain({}, {'人口分界线': RuntimeError('provider unavailable')})
        self.assertEqual(self.query(chain), [None])
        self.assertIsNone(self.cache.get_cache('人口分界线'))

    def test_letter_answer_is_resolved(self):
        chain, first, second = self.chain({'人口分界线': 'A'}, {})
        self.assertEqual(self.query(chain), ['A'])
        self.assertEqual(resolve_question_answer(self.question, 'A', first), 'A')
        self.assertEqual(second.calls, [])

    def test_multiple_choice_requires_all_fragments_to_match(self):
        question = dict(title='多选', type='multiple', options='A.地理学\nB.历史学\nC.化学')
        chain, first, second = self.chain({'多选': '地理学\n不存在的学科'}, {'多选': '地理学\n历史学'})
        self.assertEqual(self.query(chain, [question]), ['地理学\n历史学'])
        self.assertEqual(resolve_question_answer(question, '地理学\n历史学', second), 'AB')
        self.assertEqual(second.calls, ['多选'])

    def test_unrecognized_judgement_reaches_ai(self):
        question = dict(title='判断', type='judgement', options='正确\n错误')
        chain, first, second = self.chain({'判断': '无法判断'}, {'判断': '错误'})
        self.assertEqual(self.query(chain, [question]), ['错误'])
        self.assertEqual(resolve_question_answer(question, '错误', second), 'false')

    def test_letter_spacing_and_list_results(self):
        provider = Provider('测试', {})
        question = dict(title='多选', type='multiple', options='A.地理学\nB.历史学\nC.化学')
        self.assertEqual(resolve_question_answer(question, 'A B', provider), 'AB')
        self.assertEqual(resolve_question_answer(question, ['地理学', '历史学'], provider), 'AB')


    def test_all_unmatched_answers_remain_unresolved_and_uncached(self):
        chain, first, second = self.chain({'人口分界线': '无关的地点'}, {'人口分界线': '其他的地点'})
        self.assertEqual(self.query(chain), [None])
        self.assertEqual(first.calls, ['人口分界线'])
        self.assertEqual(second.calls, ['人口分界线'])
        self.assertIsNone(self.cache.get_cache('人口分界线'))

    def test_valid_cached_answer_skips_all_providers(self):
        self.cache.add_cache('人口分界线', '黑河，腾冲')
        chain, first, second = self.chain({}, {})
        self.assertEqual(self.query(chain), ['黑河，腾冲'])
        self.assertEqual(first.calls, [])
        self.assertEqual(second.calls, [])

    def test_legacy_query_without_validator_keeps_type_only_validation(self):
        chain, first, second = self.chain({'人口分界线': '无法对应的地点'}, {'人口分界线': '黑河，腾冲'})
        self.assertEqual(chain.query_all([self.question.copy()]), ['无法对应的地点'])
        self.assertEqual(second.calls, [])

    def test_legacy_batch_override_without_validator_keyword(self):
        class LegacyProvider(Provider):
            def _query_all(self, questions, query_delay=0.0):
                return [self._query(question) for question in questions]

        provider = LegacyProvider('旧题库', {'人口分界线': '黑河，腾冲'})
        self.assertEqual(provider.query_all([self.question.copy()]), ['黑河，腾冲'])

    def run_study(self, primary, fallback):
        chain, first, second = self.chain(primary, fallback)
        cx = Chaoxing(tiku=chain)
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.text = '<test-form>'
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'status': True, 'msg': 'ok'}
        question = dict(self.question, id='1', answerField={'answertype1': '0'})
        form = {'workId': 'test', 'questions': [question]}
        with patch.object(SessionManager, 'get_session', return_value=session), \
             patch('api.base.decode_questions_info', return_value=form), \
             patch('api.base.random_answer', return_value='B') as guess:
            result = cx.study_work({'courseId': '1', 'clazzId': '2'},
                                   {'jobid': 'test', 'enc': 'test'},
                                   {'knowledgeid': '3', 'ktoken': 'test', 'cpi': '4'})
        self.assertEqual(result, StudyResult.SUCCESS)
        self.assertEqual(session.post.call_count, 1)
        return session.post.call_args.kwargs['data'], guess, second

    def test_study_work_saves_matched_fallback_without_random_guess(self):
        payload, guess, second = self.run_study({'人口分界线': '无关地点'}, {'人口分界线': '黑河，腾冲'})
        self.assertEqual(payload['pyFlag'], '1')
        self.assertEqual(payload['answer1'], 'A')
        self.assertEqual(second.calls, ['人口分界线'])
        guess.assert_not_called()

    def test_study_work_keeps_unresolved_answers_blank_in_save_mode(self):
        payload, guess, second = self.run_study({'人口分界线': '无关地点'}, {'人口分界线': '其他地点'})
        self.assertEqual(payload['pyFlag'], '1')
        self.assertEqual(payload['answer1'], '')
        self.assertEqual(second.calls, ['人口分界线'])
        guess.assert_called_once()
