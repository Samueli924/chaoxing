# -*- coding: utf-8 -*-
"""
离线回归测试：平台文本 / 填空题提交 / 大模型连接检查 / 视频并发开关

对应上游 issue：
  #602 课程名含 &nbsp;(\xa0) 时控制台编码崩溃
  #615 #575 填空题答案保存后为空
  #603 思考模型连接检查误判失败
  #588 视频并发导致进度回退（提供串行开关）
全部测试不联网、不读写用户真实数据。
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 必须在导入 api 之前指定数据目录，避免碰到用户真实配置
os.environ.setdefault("CX_DATA_HOME", tempfile.mkdtemp(prefix="cx-test-"))

import main  # noqa: E402
from api import answer as answer_mod  # noqa: E402
from api import guard  # noqa: E402
from api import paths  # noqa: E402
from api.answer import CacheDAO  # noqa: E402
from api.base import (  # noqa: E402
    Account,
    Chaoxing,
    StudyResult,
    _parse_progress_passed,
    answers_equal,
    build_completion_fields,
    build_multiple_answer,
    clean_res,
    evaluate_work_detail,
    split_completion_answer,
)
from requests import RequestException  # noqa: E402
from api.decode import (  # noqa: E402
    _get_question_type,
    clean_text,
    decode_course_card,
    decode_course_folder,
    decode_course_list,
    decode_course_point,
    decode_questions_info,
    _extract_choices,
)


class CleanTextTestCase(unittest.TestCase):
    """#602：特殊空白字符在 GBK 控制台会直接把程序打崩"""

    def test_nbsp_becomes_space(self):
        self.assertEqual(clean_text("数据\xa0结构"), "数据 结构")

    def test_exotic_spaces_and_zero_width(self):
        self.assertEqual(clean_text("a\u3000b"), "a b")
        self.assertEqual(clean_text("a\u200bb"), "ab")

    def test_none_and_blank(self):
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text("   "), "")

    def test_normal_text_kept(self):
        self.assertEqual(clean_text("第一章 绪论"), "第一章 绪论")

    def test_course_title_is_cleaned(self):
        html = (
            '<div class="course" id="1" info="i" roleid="2">'
            '<input class="clazzId" value="9"><input class="courseId" value="8">'
            '<a href="x?cpi=123&y=1"></a>'
            '<span class="course-name" title="数据结构\xa0与算法"></span>'
            '<p class="margint10" title="描述"></p><p class="color3" title="张老师"></p></div>'
        )
        courses = decode_course_list(html)
        self.assertEqual(courses[0]["title"], "数据结构 与算法")


class DecodeRobustnessTestCase(unittest.TestCase):
    """平台改版导致字段缺失时不能直接崩（#58 / #293 / #392 / #593 这类报错）"""

    GOOD_COURSE = (
        '<div class="course" id="1" info="i" roleid="2">'
        '<input class="clazzId" value="9"><input class="courseId" value="8">'
        '<a href="x?cpi=123&y=1"></a>'
        '<span class="course-name" title="数据结构"></span>'
        '<p class="margint10" title="描述"></p><p class="color3" title="张老师"></p></div>'
    )

    def test_course_list_skips_broken_entries(self):
        broken = [
            # 缺 input
            '<div class="course" id="1"><a href="x?cpi=1&y=1"></a><span class="course-name" title="A"></span></div>',
            # 缺 cpi
            '<div class="course" id="2"><input class="clazzId" value="9"><input class="courseId" value="8">'
            '<a href="x"></a><span class="course-name" title="B"></span></div>',
            # 缺标题
            '<div class="course" id="3"><input class="clazzId" value="9"><input class="courseId" value="8">'
            '<a href="x?cpi=1&y=1"></a><span class="course-name"></span></div>',
        ]
        courses = decode_course_list(self.GOOD_COURSE + "".join(broken))
        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["courseId"], "8")

    def test_course_list_empty_html(self):
        self.assertEqual(decode_course_list(""), [])

    def test_course_point_keeps_valid_and_skips_broken(self):
        html = (
            '<div class="chapter_unit"><ul>'
            '<li><div id="cur111"><a class="clicktitle">1.1 绪论</a>'
            '<input class="knowledgeJobCount" value="2"></div></li>'
            '<li><div id="cur222"><a></a></div></li>'
            '<li><div id="badid"><a class="clicktitle">没有数字 id</a></div></li>'
            '<li><div><a class="clicktitle">完全没有 id</a></div></li>'
            '</ul></div>'
        )
        points = decode_course_point(html)["points"]
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["title"], "1.1 绪论")
        self.assertEqual(points[0]["jobCount"], "2")
        # 标题缺失时用占位名字，不能是 None
        self.assertEqual(points[1]["title"], "未命名章节")

    def test_course_point_empty_html(self):
        self.assertEqual(decode_course_point("")["points"], [])

    def test_course_folder_skips_broken_entries(self):
        html = ('<ul class="file-list">'
                '<li fileid="111"><input class="rename-input" value="我的文件夹"></li>'
                '<li fileid="222"><b>缺 rename-input</b></li>'
                '<li><input class="rename-input" value="缺 fileid"></li>'
                '</ul>')
        folders = decode_course_folder(html)
        self.assertEqual([f["id"] for f in folders], ["111"])
        self.assertEqual(folders[0]["rename"], "我的文件夹")
        self.assertEqual(decode_course_folder(""), [])

    def test_course_card_invalid_marg_json(self):
        # mArg 片段不是合法 JSON 时按读取失败处理，不能抛异常（#313 / #417 附带项）
        for html in ("mArg={bad json;", 'mArg={{"x":1};'):
            jobs, info = decode_course_card(html)
            self.assertEqual(jobs, [])
            self.assertTrue(info.get("parseError"), info)

    def test_course_card_without_marg_marks_parse_error(self):
        # 登录页 / 空页面取不到 mArg，必须标记 parseError，
        # 让上层按"读取失败"重试，而不是当成"这个章节没有任务点"（#223 / #357）
        for html in ("", "<html>登录页</html>", "<html><body>403</body></html>"):
            jobs, info = decode_course_card(html)
            self.assertEqual(jobs, [])
            self.assertTrue(info.get("parseError"), info)

    def test_course_card_with_empty_marg_is_empty_chapter(self):
        # mArg 存在但为空 = 这一章确实没有卡片，走正常的"空章节"流程
        jobs, info = decode_course_card("mArg={};")
        self.assertEqual(jobs, [])
        self.assertFalse(info.get("parseError"), info)

    def test_quiz_page_without_form(self):
        # 接口返回登录页 / 空页面时不能抛 NoneType 异常（#593）
        for html in ("", "<html><body>请登录</body></html>", "<html><div>题目</div></html>"):
            result = decode_questions_info(html)
            self.assertEqual(result.get("questions"), [])

    def test_question_block_without_timu(self):
        html = ('<html><form><div class="singleQuesId" data="1">'
                '<div class="Zy_TItle">题目</div></div></form></html>')
        result = decode_questions_info(html)
        self.assertIsInstance(result.get("questions"), list)


class AnswerEqualityTestCase(unittest.TestCase):
    """#627：判断题/多选题/填空题的答案写法不同，不能被判成答错"""

    def test_identical(self):
        self.assertTrue(answers_equal("A", "A"))

    def test_judgement_variants(self):
        for mine, right in (("对", "正确"), ("对", "√"), ("√", "正确"), ("错", "×"), ("错误", "不正确")):
            self.assertTrue(answers_equal(mine, right, "判断题"), f"{mine} vs {right}")
        self.assertFalse(answers_equal("对", "错", "判断题"))

    def test_multiple_choice_order_and_separators(self):
        self.assertTrue(answers_equal("ABD", "A,B,D", "多选题"))
        self.assertTrue(answers_equal("ABD", "b,a,d", "多选题"))
        self.assertFalse(answers_equal("AB", "A", "多选题"))
        self.assertFalse(answers_equal("AB", "ABD", "多选题"))

    def test_completion_separators(self):
        self.assertTrue(answers_equal("并发#线程", "并发；线程", "填空题"))
        self.assertTrue(answers_equal("并发#线程", "并发 线程", "填空题"))
        self.assertFalse(answers_equal("并发", "并发 线程", "填空题"))

    def test_hash_is_not_dropped(self):
        # 分隔符不能直接删掉，否则 "C#" 和 "C" 会被判成一样
        self.assertFalse(answers_equal("C#", "C", "填空题"))

    def test_fullwidth_and_html(self):
        self.assertTrue(answers_equal("Ａ", "A"))
        self.assertTrue(answers_equal("A&nbsp;B", "A B"))
        self.assertTrue(answers_equal("<span>A</span>", "A"))

    def test_empty_values(self):
        self.assertTrue(answers_equal("", ""))
        self.assertFalse(answers_equal("", "A"))


class MultipleChoiceAnswerTestCase(unittest.TestCase):
    """#427 #502：题库返回字母串（"AC"/"ABD"）时不能漏选或退化成随机"""

    OPTIONS = "A 甲选项\nB 乙选项\nC 丙选项\nD 丁选项"

    def test_letter_run_is_kept_whole(self):
        self.assertEqual(clean_res("AC"), ["AC"])
        self.assertEqual(clean_res("ABD"), ["ABD"])
        self.assertEqual(clean_res("A"), ["A"])
        # "B. 选项内容" 这种前缀仍然要去掉（单个字母的答案不受影响）
        self.assertEqual(clean_res("B. 某个选项"), ["某个选项"])
        self.assertEqual(clean_res("B"), ["B"])

    def test_build_multiple_answer(self):
        cases = [
            ("AC", "AC"),
            ("ABD", "ABD"),
            ("A,B,D", "ABD"),
            ("A、B、D", "ABD"),
            ("b,a,d", "ABD"),
            ("C", "C"),
            ("甲选项#丙选项", "AC"),
            ("完全无关的答案", ""),
        ]
        for raw, expected in cases:
            self.assertEqual(build_multiple_answer(raw, self.OPTIONS), expected, raw)


class OptionImageTestCase(unittest.TestCase):
    """#457：选项本身是图片时要把图片地址带上，否则题库只看到一串字母"""

    def test_image_option_keeps_url(self):
        element = BeautifulSoup('<li aria-label="A"><img src="https://x/a.png"></li>', "lxml").li
        result = _extract_choices(element)
        self.assertTrue(result.startswith("A"))
        self.assertIn("<img src=", result)

    def test_image_only_option(self):
        element = BeautifulSoup('<li><img src="https://x/b.png"></li>', "lxml").li
        self.assertIn("<img src=", _extract_choices(element))

    def test_text_option_has_no_noise(self):
        element = BeautifulSoup('<li aria-label="B 某个文字选项"></li>', "lxml").li
        self.assertEqual(_extract_choices(element), "B 某个文字选项")

    def test_mixed_option_keeps_text(self):
        element = BeautifulSoup('<li aria-label="C 看图作答"><img src="https://x/c.png"></li>', "lxml").li
        self.assertEqual(_extract_choices(element), "C 看图作答")


class WorkDetailEvaluationTestCase(unittest.TestCase):
    """#627：页面没渲染出「我的答案」时判定不可信，不能当成答错去重做"""

    def test_empty_my_answer_is_unjudgeable(self):
        detail = [{"title": "题1", "type_label": "判断题", "my_answer": "", "correct_answer": "√"}]
        result = evaluate_work_detail(detail)
        self.assertFalse(result["all_correct"])
        self.assertTrue(result["unjudgeable"])

    def test_same_meaning_counts_as_correct(self):
        detail = [{"title": "题1", "type_label": "判断题", "my_answer": "对", "correct_answer": "√"}]
        result = evaluate_work_detail(detail)
        self.assertTrue(result["all_correct"])
        self.assertFalse(result["unjudgeable"])

    def test_real_wrong_answer_is_judged(self):
        detail = [{"title": "题1", "type_label": "判断题", "my_answer": "错", "correct_answer": "√"}]
        result = evaluate_work_detail(detail)
        self.assertFalse(result["all_correct"])
        self.assertFalse(result["unjudgeable"])
        self.assertEqual(len(result["feedback"]), 1)

    def test_partial_wrong_still_judged(self):
        detail = [
            {"title": "题1", "type_label": "判断题", "my_answer": "错", "correct_answer": "√"},
            {"title": "题2", "type_label": "判断题", "my_answer": "", "correct_answer": "√"},
        ]
        result = evaluate_work_detail(detail)
        self.assertFalse(result["all_correct"])
        self.assertFalse(result["unjudgeable"])


class CompletionAnswerTestCase(unittest.TestCase):
    """#615 / #575：填空题必须按空提交，否则网页端显示答案为空"""

    def test_split_two_blanks(self):
        self.assertEqual(split_completion_answer("并发#线程", 2), ["并发", "线程"])

    def test_single_blank_keeps_hash(self):
        # 只有一个空时不能按 # 拆，否则 "C# 语言" 会被切坏
        self.assertEqual(split_completion_answer("C# 语言", 1), ["C# 语言"])

    def test_unknown_count_splits_by_hash(self):
        self.assertEqual(split_completion_answer("a#b", 0), ["a", "b"])

    def test_more_expected_than_answers(self):
        self.assertEqual(split_completion_answer("a#b#c", 2), ["a", "b#c"])

    def test_list_answer(self):
        self.assertEqual(split_completion_answer(["a", "b"], 2), ["a", "b"])

    def test_empty_inputs(self):
        self.assertEqual(split_completion_answer(None, 2), [])
        self.assertEqual(split_completion_answer("", 2), [])

    @staticmethod
    def _question(qid="42", qtype="completion", atype="2", source="cover"):
        return {
            "id": qid,
            "type": qtype,
            "answerField": {f"answer{qid}": "", f"answertype{qid}": atype},
            f"answerSource{qid}": source,
        }

    def test_completion_fields_built(self):
        form = {"workId": "1", "tiankongsize42": "2", "answer42": "并发#线程"}
        build_completion_fields(form, self._question())
        self.assertEqual(form["answerEditor421"], "并发")
        self.assertEqual(form["answerEditor422"], "线程")
        self.assertEqual(form["tiankongsize42"], 2)
        self.assertNotIn("answer42", form)

    def test_single_blank_payload(self):
        form = {"tiankongsize42": "1", "answer42": "C# 语言"}
        build_completion_fields(form, self._question())
        self.assertEqual(form["answerEditor421"], "C# 语言")
        self.assertEqual(form["tiankongsize42"], 1)

    def test_missing_declared_count(self):
        form = {"answer42": "a#b"}
        build_completion_fields(form, self._question())
        self.assertEqual(form["answerEditor421"], "a")
        self.assertEqual(form["answerEditor422"], "b")
        self.assertEqual(form["tiankongsize42"], 2)

    def test_empty_answer_still_reports_blanks(self):
        form = {"tiankongsize42": "2", "answer42": ""}
        build_completion_fields(form, self._question(source="random"))
        self.assertEqual(form["answerEditor421"], "")
        self.assertEqual(form["answerEditor422"], "")
        self.assertEqual(form["tiankongsize42"], 2)

    def test_type_code_10_is_completion(self):
        self.assertEqual(_get_question_type("10"), "completion")
        form = {"tiankongsize42": "1", "answer42": "x"}
        build_completion_fields(form, self._question(atype="10"))
        self.assertEqual(form["answerEditor421"], "x")

    def test_other_types_untouched(self):
        form = {"answer42": "A", "answertype42": "0"}
        build_completion_fields(form, self._question(qtype="single", atype="0"))
        self.assertEqual(form["answer42"], "A")
        self.assertNotIn("tiankongsize42", form)


class _FakeResponse:
    status_code = 200
    text = "ok"

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class VideoProgressParseTestCase(unittest.TestCase):
    """#175 #298：视频进度上报接口返回非 JSON 时不能抛异常打断整章"""

    class _Resp:
        def __init__(self, payload=None, raw=False):
            self._payload = payload
            self._raw = raw

        def json(self):
            if self._raw:
                raise ValueError("Expecting value: line 1 column 1")
            return self._payload

    def test_is_passed_variants(self):
        self.assertTrue(_parse_progress_passed(self._Resp({"isPassed": True})))
        self.assertFalse(_parse_progress_passed(self._Resp({"isPassed": False})))
        self.assertFalse(_parse_progress_passed(self._Resp({"other": 1})))
        self.assertFalse(_parse_progress_passed(self._Resp(raw=True)))
        self.assertFalse(_parse_progress_passed(self._Resp([1, 2])))


class ChapterReadFailureTestCase(unittest.TestCase):
    """#223 #357：任务点读取失败不能被当成"章节已完成"静默打勾"""

    class _Cx:
        class _Limiter:
            @staticmethod
            def limit_rate(**kwargs):
                return None

        rate_limiter = _Limiter()

        def get_job_list(self, course, point):
            return None, {}

    class _CxEmpty(_Cx):
        def get_job_list(self, course, point):
            return [], {"notOpen": False}

    POINT = {"title": "1.1 章节", "has_finished": False}

    def test_read_failure_returns_error(self):
        result = main.process_chapter(self._Cx(), {"title": "课"}, self.POINT, 1.0)
        self.assertEqual(result, main.ChapterResult.ERROR)

    def test_empty_chapter_still_succeeds(self):
        result = main.process_chapter(self._CxEmpty(), {"title": "课"}, self.POINT, 1.0)
        self.assertEqual(result, main.ChapterResult.SUCCESS)


class LlmConnectionTestCase(unittest.TestCase):
    """#603：思考模型只返回 reasoning_content 时不能误判为连接失败"""

    def setUp(self):
        self._orig_post = answer_mod.requests.post

    def tearDown(self):
        answer_mod.requests.post = self._orig_post

    def _provider(self):
        provider = answer_mod.SiliconFlow()
        provider.config_set({
            "siliconflow_key": "k",
            "siliconflow_model": "m",
            "siliconflow_endpoint": "http://example.invalid",
        })
        provider._init_tiku()
        provider.min_interval = 0
        return provider

    def test_reasoning_content_counts_as_success(self):
        answer_mod.requests.post = lambda *a, **kw: _FakeResponse(
            {"choices": [{"message": {"content": "", "reasoning_content": "1+1=2"}}]}
        )
        self.assertTrue(self._provider().check_llm_connection())

    def test_malformed_response_does_not_raise(self):
        answer_mod.requests.post = lambda *a, **kw: _FakeResponse({})
        self.assertFalse(self._provider().check_llm_connection())

    def test_400_has_readable_message(self):
        message = answer_mod.brief_error(Exception("Error code: 400 - bad request"))
        self.assertIn("400", message)


class CacheDAOTestCase(unittest.TestCase):
    """#552：CacheDAO 每次查询都新建实例，锁必须是类级的，否则并发写会互相覆盖"""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="cx-cache-"), "cache.json")
        CacheDAO(self.path)

    def test_concurrent_writes_do_not_lose_entries(self):
        threads = [
            threading.Thread(target=lambda i=i: CacheDAO(self.path).add_cache(f"q_{i}", f"a_{i}"))
            for i in range(40)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with open(self.path, encoding="utf8") as fp:
            data = json.load(fp)
        self.assertEqual(len(data), 40)

    def test_non_dict_cache_is_ignored(self):
        with open(self.path, "w", encoding="utf8") as fp:
            fp.write("[1, 2, 3]")
        dao = CacheDAO(self.path)
        self.assertIsNone(dao.get_cache("q_1"))
        dao.add_cache("q_new", "a")
        self.assertEqual(CacheDAO(self.path).get_cache("q_new"), "a")

    def test_null_cache_does_not_crash(self):
        with open(self.path, "w", encoding="utf8") as fp:
            fp.write("null")
        self.assertIsNone(CacheDAO(self.path).get_cache("x"))


class StartupGuardTestCase(unittest.TestCase):
    """#567：纯命令行模式没有 -c 配置文件，不能被启动检查拦死"""

    CONFIG = {"username": "13800000000", "password": "pw", "course_list": ["111"]}
    TIKU = {"provider": "TikuManual"}

    def test_cli_mode_without_config_file_is_allowed(self):
        guard.check_before_run(dict(self.CONFIG), self.TIKU, {}, None, skip_confirm=True)

    def test_explicit_missing_config_file_still_stops(self):
        missing = os.path.join(tempfile.mkdtemp(prefix="cx-cfg-"), "not-exist.ini")
        with self.assertRaises(guard.UserAbort):
            guard.check_before_run(dict(self.CONFIG), self.TIKU, {}, missing, skip_confirm=True)


class CliModeConfigTestCase(unittest.TestCase):
    """命令行模式（不带 -c）也要能读到用户配置里的题库设置，否则会被误拦"""

    def test_reads_tiku_from_default_config(self):
        config_path = paths.config_path()
        original = None
        if os.path.exists(config_path):
            with open(config_path, encoding="utf8") as fp:
                original = fp.read()
        try:
            with open(config_path, "w", encoding="utf8") as fp:
                fp.write("[common]\nusername = 13800000000\n\n"
                         "[tiku]\nprovider = TikuManual\ncheck_llm_connection = false\n")
            tiku_config, notification_config = main._load_default_tiku_and_notification()
            self.assertEqual(tiku_config.get("provider"), "TikuManual")
            self.assertIsInstance(notification_config, dict)
        finally:
            if original is None:
                if os.path.exists(config_path):
                    os.remove(config_path)
            else:
                with open(config_path, "w", encoding="utf8") as fp:
                    fp.write(original)


class NetworkRetryTestCase(unittest.TestCase):
    """#124 #166 #192 #226：主流程网络抖动要重试，重试耗尽给友好提示"""

    def test_retries_then_succeeds(self):
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise RequestException("网络抖动")
            return "ok"

        self.assertEqual(main.with_network_retry(flaky, what="测试", delay=0), "ok")
        self.assertEqual(state["n"], 3)

    def test_exhausted_retries_raise_friendly_error(self):
        def always_fail():
            raise RequestException("一直失败")

        with self.assertRaises(main.NetworkRetryFailed):
            main.with_network_retry(always_fail, what="测试", times=2, delay=0)


class LoginRobustnessTestCase(unittest.TestCase):
    """#163 #164 #220：登录接口没超时 / 返回非 JSON 时不能崩或挂死"""

    class _FakeResponse:
        status_code = 200
        text = "blocked"

        def __init__(self, payload=None, raw=False):
            self._payload = payload
            self._raw = raw

        def json(self):
            if self._raw:
                raise ValueError("Expecting value: line 1 column 1")
            return self._payload

    def setUp(self):
        self._orig_post = requests.Session.post
        self.cx = Chaoxing(account=Account("13800000000", "pw"), tiku=None)

    def tearDown(self):
        requests.Session.post = self._orig_post

    def test_non_json_response(self):
        # 注意：第一个参数是 Session 实例，别用 self 命名（会遮住测试用例的 self）
        fake = self._FakeResponse
        requests.Session.post = lambda session, *a, **kw: fake(raw=True)
        result = self.cx.login()
        self.assertFalse(result["status"])
        self.assertTrue(result["msg"])

    def test_missing_msg2(self):
        fake = self._FakeResponse
        requests.Session.post = lambda session, *a, **kw: fake({"status": False})
        result = self.cx.login()
        self.assertFalse(result["status"])
        self.assertTrue(result["msg"])

    def test_network_timeout(self):
        def boom(self, *a, **kw):
            raise RequestException("连接超时")

        requests.Session.post = boom
        result = self.cx.login()
        self.assertFalse(result["status"])
        self.assertIn("网络", result["msg"])


class VideoSerialTestCase(unittest.TestCase):
    """#588：serial_video = true 时同一个进程一次只播一个视频"""

    def setUp(self):
        self._orig = Chaoxing._study_video
        self.counter = {"now": 0, "max": 0}
        self._lock = threading.Lock()

        counter = self.counter
        lock = self._lock

        # 注意：第一个参数是被替换方法里的 Chaoxing 实例，别用 self 命名，免得遮住测试用例
        def fake_play(chaoxing_self, _course, _job, _job_info, _speed=1.0, _type="Video"):
            with lock:
                counter["now"] += 1
                counter["max"] = max(counter["max"], counter["now"])
            time.sleep(0.05)
            with lock:
                counter["now"] -= 1
            return StudyResult.SUCCESS

        Chaoxing._study_video = fake_play

    def tearDown(self):
        Chaoxing._study_video = self._orig

    def _run(self, serial, workers=4):
        cx = Chaoxing(account=None, tiku=None, serial_video=serial)
        threads = [
            threading.Thread(target=cx.study_video, args=({}, {}, {}))
            for _ in range(workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_serial_mode_runs_one_video(self):
        self._run(True)
        self.assertEqual(self.counter["max"], 1)

    def test_default_mode_allows_concurrency(self):
        self._run(False)
        self.assertGreater(self.counter["max"], 1)


class VideoReplayTestCase(unittest.TestCase):
    """进度已到结尾但平台未通过时，必须从头回看（决 D3：不够就回看）"""

    def test_full_but_unpassed_video_replays_from_start(self):
        from unittest import mock
        from api import base as base_mod

        cx = base_mod.Chaoxing()
        recorded = []
        state = {"calls": 0}

        def fake_log(session, course, job, job_info, dtoken, duration, playing,
                     _type="Video", **kwargs):
            recorded.append(playing)
            state["calls"] += 1
            # 第 1 次是"瞬间完成"检查；回看后的第一次心跳就让它通过
            return state["calls"] >= 2, 200

        class Sess:
            cookies = {}

            def get(self, url, **kwargs):
                class R:
                    status_code = 200

                    @staticmethod
                    def json():
                        return {"status": "success", "dtoken": "d", "duration": 100}

                return R()

        job = {"jobid": "j", "objectid": "o", "otherinfo": "nodeId_k",
               "videoFaceCaptureEnc": "", "attDuration": "", "attDurationEnc": "",
               "rt": "1", "playTime": 100000, "name": "测试视频"}
        with mock.patch.object(base_mod.SessionManager, "get_session", return_value=Sess()), \
             mock.patch.object(cx, "video_progress_log", side_effect=fake_log), \
             mock.patch.object(base_mod.random, "uniform", return_value=0), \
             mock.patch.object(base_mod.time, "sleep", return_value=None):
            result = cx._study_video(
                {"clazzId": "1", "courseId": "2", "cpi": "3"}, job, {}, 1.0
            )

        self.assertEqual(result, base_mod.StudyResult.SUCCESS)
        self.assertEqual(recorded[0], 100)
        self.assertTrue(
            any(p < 100 for p in recorded[1:]),
            "回看后必须从更早的位置重新上报，实际序列: %s" % recorded,
        )

    def test_video_not_at_end_keeps_normal_playback(self):
        from unittest import mock
        from api import base as base_mod

        cx = base_mod.Chaoxing()
        recorded = []
        state = {"calls": 0}

        def fake_log(session, course, job, job_info, dtoken, duration, playing,
                     _type="Video", **kwargs):
            recorded.append(playing)
            state["calls"] += 1
            return state["calls"] >= 2, 200

        class Sess:
            cookies = {}

            def get(self, url, **kwargs):
                class R:
                    status_code = 200

                    @staticmethod
                    def json():
                        return {"status": "success", "dtoken": "d", "duration": 100}

                return R()

        job = {"jobid": "j", "objectid": "o", "otherinfo": "nodeId_k",
               "videoFaceCaptureEnc": "", "attDuration": "", "attDurationEnc": "",
               "rt": "1", "playTime": 30000, "name": "测试视频"}
        with mock.patch.object(base_mod.SessionManager, "get_session", return_value=Sess()), \
             mock.patch.object(cx, "video_progress_log", side_effect=fake_log), \
             mock.patch.object(base_mod.random, "uniform", return_value=0), \
             mock.patch.object(base_mod.time, "sleep", return_value=None):
            result = cx._study_video(
                {"clazzId": "1", "courseId": "2", "cpi": "3"}, job, {}, 1.0
            )
        self.assertEqual(result, base_mod.StudyResult.SUCCESS)
        # 没有到结尾：第一次心跳仍然是原始进度（30s），不触发回看
        self.assertEqual(recorded[0], 100)
        self.assertEqual(recorded[1], 30)


if __name__ == "__main__":
    unittest.main()
