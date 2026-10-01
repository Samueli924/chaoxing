# -*- coding: utf-8 -*-
import functools
import json
import random
import secrets
import re
from html import unescape
import threading
import time
from difflib import SequenceMatcher
from enum import Enum, IntEnum
from hashlib import md5
from typing import Optional, Literal

import requests
from loguru import logger
from requests import RequestException
from requests.adapters import HTTPAdapter
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception
from tqdm import tqdm

from api.answer import Tiku, TikuManual
from api.answer_check import cut
from api.cipher import AESCipher
from api.config import GlobalConst as gc
from api.cookies import save_cookies, use_cookies
from api.decode import (
    decode_course_list,
    decode_course_point,
    decode_course_card,
    decode_course_folder,
    decode_questions_info,
)


# 验证码冷却：连续识别失败后，短时间内不再对每个任务点硬撞验证码
_CAPTCHA_COOLDOWN_SECONDS = 60
_captcha_cooldown_until = 0.0


def _short_title(text, limit: int = 24) -> str:
    """进度条上的任务名截断：长文件名会把整行撑爆，这里统一收短。"""
    name = str(text or "").strip()
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def get_timestamp():
    return str(int(time.time() * 1000))


class SessionManager:
    _instance = None
    _login_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 单例只需初始化一次。
        # 注意：__new__ 返回单例后 __init__ 仍会被调用，若不拦截，
        # 每次 get_session() 都会重建 Session 并从 cookie 文件重新加载登录态，
        # 导致「cookie 文件丢失 = 登录态丢失 = 抛 Cannot get uid 崩溃」。
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(max_retries=10))
        self._session.mount("http://", HTTPAdapter(max_retries=10))
        self._session.request = functools.partial(self._session.request, timeout=5)
        # For debug purposes
        # self._session.verify=False
        self._session.headers.clear()
        self._session.headers.update(gc.HEADERS)
        self._session.cookies.update(use_cookies())

    @classmethod
    def get_instance(cls) -> "SessionManager":
        return cls()

    @classmethod
    def get_session(cls) -> requests.Session:
        """返回同一个 Session 实例（不会重建）"""
        instance = cls.get_instance()
        return instance._session

    @classmethod
    def update_cookies(cls):
        """把磁盘上的 cookie 合并进当前 session（不清空已有的）"""
        cls.get_instance()._session.cookies.update(use_cookies())

    @classmethod
    def reset(cls):
        """显式重置会话（仅在确实需要全新会话时调用）"""
        inst = cls.get_instance()
        inst._initialized = False
        inst.__init__()

    @classmethod
    def relogin_if_needed(cls, chaoxing_instance) -> bool:
        with cls._login_lock:
            # 检查 cookie 会话是否仍然无效
            if chaoxing_instance._validate_cookie_session():
                return True

            logger.info("Cookie session invalid, attempting thread-safe relogin...")
            if chaoxing_instance.account and chaoxing_instance.account.username and chaoxing_instance.account.password:
                login_result = chaoxing_instance.login(login_with_cookies=False)
                if login_result.get("status"):
                    cls.update_cookies()
                    logger.info("Thread-safe relogin succeeded")
                    return True
                else:
                    logger.warning(f"Thread-safe relogin failed: {login_result.get('msg')}")
            return False


class Account:
    username = None
    password = None
    last_login = None
    isSuccess = None

    def __init__(self, _username, _password):
        from api.privacy import register_secret
        register_secret(_username)
        register_secret(_password)
        self.username = _username
        self.password = _password


class RateLimiter:
    def __init__(self, call_interval):
        self.last_call = time.time()
        self.lock = threading.Lock()
        self.call_interval = call_interval

    def limit_rate(self, random_time=False, random_min=0.0, random_max=1.0):
        with self.lock:
            now = time.time()
            base_wait = max(self.last_call + self.call_interval - now, 0)
            extra_wait = random.uniform(random_min, random_max) if random_time else 0
            call_wait = base_wait + extra_wait
            self.last_call = now + call_wait

        time.sleep(call_wait)


class StudyResult(Enum):
    SUCCESS = 0
    FORBIDDEN = 1  # 403
    ERROR = 2
    TIMEOUT = 3

    def is_success(self):
        return self == StudyResult.SUCCESS

    def is_failure(self):
        return self != StudyResult.SUCCESS


class SignType(IntEnum):
    NORMAL = 0
    GESTURE = 3
    LOCATION = 4


class ActivityStatus(IntEnum):
    ACTIVE = 1
    INACTIVE = 2


class ActivityType(IntEnum):
    SIGNIN = 2


# 填空题的题型代码（2 = 普通填空，10 = 新版填空）
_COMPLETION_TYPE_CODES = frozenset({"2", "10"})


def _positive_int(value, default=0) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def split_completion_answer(answer, expected_count=0) -> list:
    """
    把填空题答案拆成"每个空一个值"。

    题库返回的多个空一般用 # 或换行分隔，但答案本身也可能含 # （比如 C#），
    所以：
      · 网页明确写了空数时，只按这个数量切（1 个空就整段不切）
      · 没写空数时才按 # / 换行切
    """
    if answer is None:
        return []

    if isinstance(answer, (list, tuple)):
        items = [str(item).strip() for item in answer if str(item).strip()]
        if expected_count == 1:
            return ["\n".join(items)] if items else []
        if expected_count > 1 and len(items) > expected_count:
            return items[:expected_count - 1] + ["\n".join(items[expected_count - 1:])]
        return items

    text = str(answer).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    if expected_count == 1:
        # 网页只有一个空：整段都是这一空的答案，不能按 # 拆（例如 "C# 语言"）
        return [text]

    if expected_count > 1:
        # 网页写了空数：按空数切，多的部分并进最后一空
        max_split = expected_count - 1
        pattern = r"[\n#]"
    else:
        # 网页没写空数：按换行 / # 切，能切出几段就当几个空
        max_split = 0
        pattern = r"[\n#]"

    return [piece.strip() for piece in re.split(pattern, text, maxsplit=max_split) if piece.strip()]


def build_completion_fields(form: dict, question: dict):
    """
    填空题按空提交（#615 / #575）。

    学习通要求填空题提交 answerEditor{题目id}{第几空}（从 1 开始），
    并用 tiankongsize{题目id} 声明空数；只发 answer{题目id} 的话，
    网页端会显示"答案为空"，测验永远不及格。
    非填空题原样返回，不做任何改动。
    """
    question_id = str(question.get("id") or "")
    if not question_id:
        return

    answer_field = question.get("answerField") or {}
    answer_type = str(answer_field.get(f"answertype{question_id}", ""))
    if question.get("type") != "completion" and answer_type not in _COMPLETION_TYPE_CODES:
        return

    # 已经在上面按 cover/随机 的规则算好了该提交什么，直接取用
    answer = form.get(f"answer{question_id}", "")
    declared = _positive_int(form.get(f"tiankongsize{question_id}"))
    parts = split_completion_answer(answer, expected_count=declared)
    blank_count = declared or max(len(parts), 1)

    form.pop(f"answer{question_id}", None)
    form[f"tiankongsize{question_id}"] = blank_count
    for index in range(1, blank_count + 1):
        form[f"answerEditor{question_id}{index}"] = parts[index - 1] if index <= len(parts) else ""


def multi_cut(answer: str, origin_html_content="", logger=logger):
    """
    将多选题答案字符串按特定字符进行切割, 并返回切割后的答案列表
    """
    res = cut(answer)
    if res is None:
        logger.warning(
            f"未能从网页中提取题目信息, 以下为相关信息：\n\t{answer}\n\n{origin_html_content}\n"
        )
        logger.warning("未能正确提取题目选项信息! 请反馈并提供以上信息")
        return None
    else:
        return res


def clean_res(res):
    cleaned_res = []
    if isinstance(res, str):
        res = [res]
    for c in res:
        text = str(c).strip()
        if re.fullmatch(r"[A-Za-z]{2,}", text):
            # 纯字母串（"AC" / "ABD"）是"多个选项字母"，不是"A. 选项内容"这种前缀。
            # 以前会把首字母当编号删掉，导致漏选（"AC"->"C"）
            # 或者整题匹配失败转随机（"ABD"->"BD"）（#427 / #502）
            cleaned_res.append(text)
            continue
        # 仅在字符串长度大于1时才尝试去除开头的字母编号，防止误删单个字母答案
        cleaned = re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*|[.,!?;:，。！？；：]', '', c) if len(c) > 1 else c
        cleaned_res.append(cleaned.strip())
    return cleaned_res


def build_multiple_answer(res, options, origin_html_content="") -> str:
    """
    把题库返回的多选答案转成"要提交的选项字母串"。

    题库返回的形式很杂：
      "ABD"                 -> 直接就是字母
      "A,B,D" / "A、B、D"    -> 带分隔符的字母
      "选项一的文字#选项二"    -> 只能按文字匹配回字母
    返回空串表示一个都没匹配上（调用方会退化成随机作答）。
    """
    options_list = multi_cut(options, origin_html_content)
    res_list = multi_cut(res, origin_html_content)
    if res_list is None or options_list is None:
        return ""

    answer = ""
    for item in clean_res(res_list):
        # 纯字母串（"AC" / "ABD"）就是选项字母，逐个采用（#427 / #502）
        if re.fullmatch(r"[A-Za-z]{2,}", item):
            answer += item.upper()
            continue

        matched = False
        for option in options_list:
            if is_subsequence(item, option):
                # 去掉各种符号和前面ABCD之后，答案应当是选项的子序列
                answer += option[:1]
                matched = True
                break  # 找到匹配项后立即停止，防止重复添加
        if not matched:
            best_letter = best_option_by_similarity(item, options_list, threshold=0.8)
            if best_letter:
                answer += best_letter

    # 对答案进行排序, 否则会提交失败
    return "".join(sorted(set(answer)))


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    # 统一常见异体字符，降低“风/⻛”类差异导致的匹配失败。
    char_map = str.maketrans({
        '⻛': '风',
        '⻔': '门',
        '⻋': '车',
        '⻢': '马',
    })
    normalized = text.translate(char_map)
    normalized = re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*', '', normalized)
    normalized = re.sub(r'\s+', '', normalized)
    normalized = re.sub(r'[，。！？；：,.!?;:()（）\[\]【】"“”‘’\-_/\\|]', '', normalized)
    return normalized.lower()


def get_option_text(option: str) -> str:
    return re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*', '', option).strip()


def best_option_by_similarity(target: str, options: list, threshold: float = 0.8) -> str:
    if not target or not options:
        return ""
    target_norm = normalize_text(target)
    if not target_norm:
        return ""

    best_letter = ""
    best_score = 0.0
    for option in options:
        option_text = get_option_text(option)
        option_norm = normalize_text(option_text)
        if not option_norm:
            continue
        score = SequenceMatcher(None, target_norm, option_norm).ratio()
        if score > best_score:
            best_score = score
            best_letter = option[:1]

    if best_score >= threshold:
        logger.info(f"相似度兜底匹配成功: {best_letter} (score={best_score:.2f}, threshold={threshold:.2f})")
        return best_letter
    return ""


def is_subsequence(a, o):
    iter_o = iter(o.lower())
    return all(c in iter_o for c in a.lower())


def random_answer(options: str, q_type: str) -> str:
    answer = ""
    if not options:
        return answer

    if q_type == "multiple":
        logger.debug(f"当前选项列表[cut前] -> {options}")
        _op_list = multi_cut(options)
        logger.debug(f"当前选项列表[cut后] -> {_op_list}")

        if not _op_list:
            logger.error(
                "选项为空, 未能正确提取题目选项信息! 请反馈并提供以上信息"
            )
            return answer

        available_options = len(_op_list)
        select_count = 0

        # 根据可用选项数量调整可能选择的选项数
        if available_options <= 1:
            select_count = available_options
        else:
            max_possible = min(4, available_options)
            min_possible = min(2, available_options)

            weights_map = {
                2: [1.0],
                3: [0.3, 0.7],
                4: [0.1, 0.5, 0.4],
                5: [0.1, 0.4, 0.3, 0.2],
            }

            weights = weights_map.get(max_possible, [0.3, 0.4, 0.3])
            possible_counts = list(range(min_possible, max_possible + 1))

            weights = weights[:len(possible_counts)]

            weights_sum = sum(weights)
            if weights_sum > 0:
                weights = [w / weights_sum for w in weights]

            select_count = random.choices(possible_counts, weights=weights, k=1)[0]

        selected_options = random.sample(_op_list, select_count) if select_count > 0 else []

        for option in selected_options:
            answer += option[:1]  # 取首字为答案，例如A或B

        answer = "".join(sorted(answer))
    elif q_type == "single":
        answer = random.choice(options.split("\n"))[:1]  # 取首字为答案, 例如A或B
    # 判断题处理
    elif q_type == "judgement":
        answer = "true" if random.choice([True, False]) else "false"
    logger.trace(f"随机选择 -> {answer}")
    return answer


def _parse_work_record_list(html_text: str) -> list[tuple[int, float]]:
    """
    解析章节检测作答记录列表页面（/work/record-list）。

    Args:
        html_text: record-list 页面 HTML

    Returns:
        作答记录列表，元素为 (作答序号times, 成绩score)，例如 [(0, 80.0), (1, 100.0)]
    """
    records = []
    times_list = re.findall(r'viewNum">第(\d+)次', html_text)
    scores = re.findall(r'viewScore">([\d.]+)分', html_text)
    if len(times_list) != len(scores):
        # 次数/成绩数量不齐时 zip 会错位, 成绩按 0 处理(放弃分数捷径, 仅做逐题比对)
        logger.warning(f"作答记录次数/成绩数量不匹配({len(times_list)}/{len(scores)}), 成绩按0处理")
        scores = ['0'] * len(times_list)
    for t, s in zip(times_list, scores):
        try:
            records.append((int(t), float(s)))
        except ValueError:
            continue
    return records


def _parse_work_record_detail(html_text: str) -> list[dict]:
    """
    解析章节检测单次作答详情页面（/work/record-detail）。

    Args:
        html_text: record-detail 页面 HTML

    Returns:
        每题信息列表：{id, title, type_label, my_answer, correct_answer}
    """
    questions = []
    for qm in re.finditer(r'<div class="TiMu[^"]*singleQuesId" data="(\d+)"[^>]*>(.*?)(?=<div class="TiMu|$)', html_text, re.S):
        qid = qm.group(1)
        qb = qm.group(2)

        # 题型 + 题目
        tm = re.search(r'newZy_TItle">(.*?)</span>(.*?)</div>', qb, re.S)
        if tm:
            type_label = re.sub(r'<[^>]+>', '', tm.group(1)).strip()
            title = re.sub(r'<[^>]+>', '', tm.group(2))
        else:
            type_label = ""
            title = ""
        title = re.sub(r'\s+', ' ', title).strip()

        # 我的答案/正确答案: 多模式匹配, 兼容属性顺序变化与额外 class 的页面变体
        ans_patterns = [
            r'{label}[:：]</span>\s*<div class="fl answerCon">\s*(.*?)\s*</div>',
            r'{label}[:：]\s*</span>\s*<div[^>]*class="[^"]*answerCon[^"]*"[^>]*>\s*(.*?)\s*</div>',
            r'{label}[:：]\s*</span>\s*<span[^>]*>\s*(.*?)\s*</span>',
        ]

        def _extract_answer(label):
            for pat in ans_patterns:
                m = re.search(pat.format(label=label), qb, re.S)
                if m:
                    return re.sub(r'<[^>]+>', '', m.group(1)).strip()
            return None

        my_raw = _extract_answer('我的答案')
        correct_raw = _extract_answer('正确答案')

        questions.append({
            "id": qid,
            "title": title,
            "type_label": type_label,
            "my_answer": my_raw or '',
            "correct_answer": correct_raw or '',
            "parse_ok": my_raw is not None and correct_raw is not None,
        })
    return questions


# 判断题的各种写法
_TRUE_WORDS = {"对", "正确", "是", "√", "✓", "true", "t", "yes", "y", "1", "a", "ture"}
_FALSE_WORDS = {"错", "错误", "否", "×", "✗", "x", "false", "f", "no", "n", "0", "不对", "不正确", "b"}

_FULLWIDTH_MAP = str.maketrans(
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
)


def capture_student_job_info(owner, payload) -> None:
    """把平台在任务引擎上下文里下发的章节同步数据暂存到 owner 上（没有就保持原值）

    任务引擎的"章节"任务点在网页上的同步链路是：视频打点 / job/document
    的响应里带 stuJobInfo，章节页把它 postMessage 给任务中心父页面，
    父页面再 POST autoPullChapterScore。这里的 stuJobInfo 就是那个
    唯一真实的请求体来源，不能自己拼 enc。
    """
    if not isinstance(payload, dict):
        return
    info = payload.get("stuJobInfo")
    if isinstance(info, dict) and info:
        owner.last_student_job_info = info


class _CurlResponse:
    """curl 重放请求的返回值，接口和 requests.Response 保持最小兼容"""

    def __init__(self, status_code: int, text: str, url: str):
        self.status_code = status_code
        self.text = text
        self.url = url

    def json(self):
        return json.loads(self.text)


def _curl_get(session, url, params, headers=None, timeout: int = 20):
    """用系统 curl 原样重放一次 GET（cookie 走 stdin，不进命令行参数）。

    存在的意义：部分网络环境下 urllib3/OpenSSL 的 TLS 指纹会被超星风控在
    mooc 视频打点接口上拒绝，返回 403 错误页；同一时刻用相同的 URL、查询参数、
    Cookie、User-Agent 走 curl（SecureTransport/LibreSSL）却是 200（）。
    所以这里只在 requests 拿到 403 时做一次等价重放，不影响正常环境。
    """
    import shutil
    import subprocess

    curl = shutil.which("curl")
    if not curl:
        logger.debug("系统里没有 curl，跳过视频打点的 curl 重放")
        return None
    try:
        prepared_url = requests.Request("GET", url, params=params).prepare().url
    except Exception as e:  # pragma: no cover - 构造 URL 失败极少见
        logger.debug("curl 重放前构造 URL 失败: {}", e)
        return None

    config_lines = [
        'url = "%s"' % prepared_url.replace('"', '\\"'),
        "silent",
        "show-error",
        "max-time = %d" % int(timeout),
        'write-out = "\\n%{http_code}"',
    ]
    for key, value in (headers or {}).items():
        config_lines.append('header = "%s: %s"' % (key, str(value).replace('"', '\\"')))
    cookie = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    if cookie:
        config_lines.append('cookie = "%s"' % cookie.replace('"', '\\"'))

    try:
        proc = subprocess.run(
            [curl, "-K", "-"],
            input="\n".join(config_lines),
            capture_output=True,
            text=True,
            timeout=int(timeout) + 10,
        )
    except Exception as e:
        logger.debug("curl 重放视频打点失败: {}", e)
        return None

    out = proc.stdout or ""
    body, sep, status = out.rpartition("\n")
    if not sep:
        logger.debug("curl 重放输出没有状态码: {}", out[:200])
        return None
    try:
        code = int(status.strip())
    except ValueError:
        logger.debug("curl 重放状态码解析失败: {}", status[:50])
        return None
    return _CurlResponse(code, body, prepared_url)


def _parse_progress_passed(resp, owner=None) -> bool:
    """
    解析视频进度上报响应里的 isPassed。

    上报接口被风控时可能返回 200 + 登录页/验证码页（不是 JSON），
    或者 JSON 里没有 isPassed；以前直接取下标会抛异常把整个章节中断（#175 / #298），
    这里统一按"还没通过"处理。

    顺带把平台下发的任务引擎同步数据（stuJobInfo）记到 owner 上。
    """
    try:
        payload = resp.json()
    except ValueError:
        logger.warning("视频进度上报返回的不是 JSON（可能被风控或需要验证码），按未通过处理")
        return False
    if not isinstance(payload, dict):
        logger.warning("视频进度上报返回格式异常，按未通过处理")
        return False
    if owner is not None:
        capture_student_job_info(owner, payload)
    return bool(payload.get("isPassed", False))


def _clean_answer_text(text) -> str:
    """去掉答案里的 HTML 标签、实体和特殊空白"""
    value = re.sub(r"<[^>]+>", "", str(text or ""))
    value = unescape(value)
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    return value.translate(_FULLWIDTH_MAP).strip()


def _letters_key(text) -> str:
    """多选答案只比较字母集合：ABD / A,B,D / b,a,d 都算一样"""
    return "".join(sorted(set(re.findall(r"[A-Za-z]", str(text or "").upper()))))


def _judge_key(text) -> str:
    """判断题归一化成 对/错"""
    squeezed = re.sub(r"[\s。.、,，;；:：]", "", _clean_answer_text(text)).lower()
    if squeezed in _TRUE_WORDS:
        return "T"
    if squeezed in _FALSE_WORDS:
        return "F"
    return squeezed


def answers_equal(my_answer, correct_answer, type_label="") -> bool:
    """
    判断"我的答案"和"正确答案"是否一致。

    页面上这两种写法的格式经常不一样（判断题 对/√、多选 ABD/A,B,D、
    填空里空格和分号混用），直接做字符串比较会把答对的判成答错，
    导致明明通过了还要重做，最后甚至被记成失败（#627）。
    """
    mine = _clean_answer_text(my_answer)
    right = _clean_answer_text(correct_answer)
    if not mine or not right:
        return mine == right
    if mine == right:
        return True

    label = str(type_label or "")
    if "判断" in label:
        return _judge_key(mine) == _judge_key(right)
    if "多选" in label:
        key_mine = _letters_key(mine)
        return bool(key_mine) and key_mine == _letters_key(right)

    # 其它题型：把各种分隔符统一成 |，忽略句读和全半角差异。
    # 注意不能直接把分隔符删掉："C#" 和 "C" 删完就一样了，会误判成答对。
    def squeeze(value):
        value = re.sub(r"""[\s#|｜，,、;；:：]+""", "|", value)
        value = re.sub(r"""[。.！!？?（）()【】\[\]"“”'’]+""", "", value)
        # 不把首尾分隔符删掉："C#" 和 "C" 删完会变成同一个字符串，那就把错的判成对了
        return value.lower()

    squeezed_mine = squeeze(mine)
    return bool(squeezed_mine) and squeezed_mine == squeeze(right)


def evaluate_work_detail(detail) -> dict:
    """
    逐题比较"我的答案"和"正确答案"（写法差异由 answers_equal 归一化）。

    返回 {"all_correct": bool, "feedback": [...], "unjudgeable": bool}

    unjudgeable=True 表示所有"不一致"的题目里，我们这边的答案是空的 ——
    也就是页面根本没渲染出"我的答案"（可能只给了图标）。这种情况判定不可信，
    调用方要按"拿不到成绩"处理，不能当成答错去重做（#627）。
    """
    feedback = []
    all_correct = True
    mismatched = 0
    empty_mine = 0
    unknown = 0

    for q in detail:
        if not q.get("parse_ok", True):
            unknown += 1
            all_correct = False
            continue
        my_ans = (q.get("my_answer") or "").strip()
        correct_ans = (q.get("correct_answer") or "").strip()
        if answers_equal(my_ans, correct_ans, q.get("type_label")):
            continue
        all_correct = False
        mismatched += 1
        if not my_ans:
            empty_mine += 1
        feedback.append(
            f"- 题目：{q.get('title', '')}\n"
            f"  题型：{q.get('type_label', '')}\n"
            f"  你的上次答案：{my_ans or '(空)'}\n"
            f"  正确答案：{correct_ans or '(空)'}"
        )

    return {
        "all_correct": all_correct,
        "feedback": feedback,
        "unjudgeable": bool(mismatched) and empty_mine == mismatched,
        "unknown": unknown,
    }
_JUDGE_TRUE_SET = {'TRUE', 'T', '1', '对', '正确', '√', '是', 'YES', 'Y'}
_JUDGE_FALSE_SET = {'FALSE', 'F', '0', '错', '错误', '×', 'X', '否', 'NO', 'N', '不对', '不正确'}


def normalize_answer_text(ans) -> str:
    """作答详情答案归一化: 消除 对/错与true/false、全半角标点等格式差异.

    归一化是确定性的, 两侧同格式必然相等; 跨格式差异(如字母 vs 选项全文)
    交由调用方的满分分数兜底处理.
    """
    s = re.sub(r'\s+', '', str(ans or '')).upper()
    if s in _JUDGE_TRUE_SET:
        return 'TRUE'
    if s in _JUDGE_FALSE_SET:
        return 'FALSE'
    if re.fullmatch(r'[A-Z0-9]+', s):
        return s
    s = re.sub(r'^[A-Z][.、:：)?）]', '', s)
    s = re.sub(r'[，。、！？；：,.!?;:()（）\[\]【】"“”‘’\-_/\\|]', '', s)
    return s


class Chaoxing:
    def __init__(self, account: Account = None, tiku: Tiku = None, **kwargs):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku
        self.kwargs = kwargs
        self.rollback_times = 0
        self.rate_limiter = RateLimiter(0.5)  # 其他接口速率限制比较松
        self.video_log_limiter = RateLimiter(2)  # 上报进度极其容易卡验证码，限制2s一次
        # 任务引擎的"章节"任务点：平台在视频/文档完成后，会把给任务引擎的
        # 同步数据（uid/finishCount/clazzId/enc/time/jobCount/knowledgeId）
        # 塞在视频打点或 /mooc-ans/job/document 的响应里（字段名 stuJobInfo）。
        # 只有从任务引擎打开的章节页（isEngineNode=1）才会下发，这里暂存给上层做同步。
        self.last_student_job_info = None

    def login(self, login_with_cookies=False):
        # 关键：把当前账号告诉 cookie 模块，之后 cookie 读写都落到该账号专属文件，
        # 避免多账号之间互相覆盖（串号）。
        if self.account and self.account.username:
            from api.cookies import set_current_account
            set_current_account(self.account.username)

        if login_with_cookies:
            logger.info("Logging in with cookies")
            SessionManager.update_cookies()
            logger.debug("Cookie session loaded")
            if not self._validate_cookie_session():
                logger.warning("Cookie 登录校验失败，尝试使用账号密码重新登录")
                if self.account and self.account.username and self.account.password:
                    return self.login(login_with_cookies=False)
                return {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}
            logger.info("登录成功...")
            try:
                realname = self.get_name()
                if realname:
                    logger.info(f"当前登录用户: {realname}")
            except Exception as e:
                logger.debug(f"获取当前登录用户名失败: {e}")
            return {"status": True, "msg": "登录成功"}

        _session = requests.Session()
        _url = "https://passport2.chaoxing.com/fanyalogin"
        _data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(self.account.username),
            "password": self.cipher.encrypt(self.account.password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": True,
            "forbidotherlogin": 0,
            "validate": "",
            "doubleFactorLogin": 0,
            "independentId": 0,
        }
        logger.trace("正在尝试登录...")
        # 登录接口一定要带超时：以前没带，服务器卡住时表现为
        # "输入完密码后没反应"，进程会一直挂着（#163 / #220）
        try:
            resp = _session.post(_url, headers=gc.HEADERS, data=_data, timeout=15)
        except RequestException as e:
            return {"status": False, "msg": f"连接登录服务器失败（{type(e).__name__}），请检查网络后重试"}

        # 风控/验证码情况下返回的可能不是 JSON，或者 JSON 里没有 status/msg2，
        # 以前直接取下标会抛 JSONDecodeError / KeyError（#164），这里统一兜底
        try:
            payload = resp.json()
        except ValueError:
            logger.warning("登录接口返回的不是 JSON（可能被风控或需要验证码），状态码: {}", resp.status_code)
            return {"status": False, "msg": "登录接口返回异常（可能需要验证码或触发了风控），请稍后重试"}

        if not isinstance(payload, dict):
            return {"status": False, "msg": "登录接口返回格式异常，请稍后重试"}

        if payload.get("status") is True:
            save_cookies(_session)
            SessionManager.update_cookies()
            logger.info("登录成功...")
            try:
                realname = self.get_name()
                if realname:
                    logger.info(f"当前登录用户: {realname}")
            except Exception as e:
                logger.debug(f"获取当前登录用户名失败: {e}")
            return {"status": True, "msg": "登录成功"}

        return {"status": False, "msg": str(payload.get("msg2") or "登录失败，请检查手机号 / 密码")}

    @staticmethod
    def get_name() -> str:
        _session = SessionManager.get_session()
        try:
            resp = _session.get("https://passport2.chaoxing.com/mooc/accountManage", timeout=10)
            if resp.status_code == 200:
                match = re.search(r'id="messageName"\s+value="([^"]*)"', resp.text)
                if match:
                    return match.group(1).strip()
        except Exception as e:
            logger.debug(f"获取用户名失败: {e}")
        return ""

    def _validate_cookie_session(self) -> bool:
        session = SessionManager.get_instance()._session
        if not session.cookies.get("_uid"):
            return False

        test_session = requests.Session()
        test_session.headers.update(gc.HEADERS)
        test_session.cookies.update(session.cookies.get_dict())

        try:
            resp = test_session.post(
                "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata",
                data={"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0},
                timeout=8,
            )
        except RequestException as exc:
            logger.debug("Cookie validation request failed: {}", exc)
            return False

        if resp.status_code != 200:
            return False

        if "passport2.chaoxing.com" in resp.text or "login" in resp.text.lower():
            return False

        return True

    def get_fid(self):
        _session = SessionManager.get_session()
        return _session.cookies.get("fid", 1024)

    def get_uid(self):
        s = SessionManager.get_session()
        if "_uid" in s.cookies:
            return s.cookies["_uid"]
        if "UID" in s.cookies:
            return s.cookies["UID"]
        raise ValueError("Cannot get uid !")

    def get_course_list(self):
        _session = SessionManager.get_session()
        _url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
        _data = {"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0}
        logger.trace("正在读取所有的课程列表...")

        # 接口突然抽风, 增加headers
        # 有可能只是referer的问题
        _headers = {
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
        }
        _resp = _session.post(_url, headers=_headers, data=_data)
        # logger.trace(f"原始课程列表内容:\n{_resp.text}")
        logger.info("课程列表读取完毕...")
        course_list = decode_course_list(_resp.text)

        _interaction_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
        _interaction_resp = _session.get(_interaction_url)
        course_folder = decode_course_folder(_interaction_resp.text)
        for folder in course_folder:
            _data = {
                "courseType": 1,
                "courseFolderId": folder["id"],
                "query": "",
                "superstarClass": 0,
            }
            # 和上面首个请求一样带上 Referer，否则接口容易返回非课程列表页，
            # 目录里的课程会被静默漏掉（#313 / #417）
            _resp = _session.post(_url, headers=_headers, data=_data)
            folder_courses = decode_course_list(_resp.text)
            if not folder_courses:
                logger.warning("课程目录《{}》没有解析到课程，已跳过",
                               folder.get("rename", folder.get("id", "")))
            course_list += folder_courses
        return course_list

    def get_activity_list(self, course: dict) -> list[dict]:
        s = SessionManager.get_session()
        url = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist"
        params = {
            "fid": self.get_fid(),
            "courseId": course["courseId"],
            "classId": course["clazzId"],
            "showNotStartedActive": 0,
            "_": get_timestamp()
        }
        resp = s.get(url, params=params, allow_redirects=False)
        if resp.status_code != 200:
            logger.error("Failed to get activity list, return code: " + str(resp.status_code))
            logger.debug("Request url: " + resp.url)
            return []

        data = resp.json()
        if data["result"] != 1:
            logger.error("Unknown status: {} {}", data["result"], data["errorMsg"])
            logger.debug("Request url: " + resp.url)
            return []

        return data["data"]["activeList"]

    def pre_sign(self, course: dict, activity_id):
        s = SessionManager.get_session()
        params = {
            "general": 1,
            "sys": 1,
            "ls": 1,
            "appType": 15,
            "tid": '',
            "ut": 's',
            "uid": self.get_uid(),
            "activePrimaryId": activity_id,
            "courseId": course["courseId"],
            "classId": course["clazzId"],
        }
        resp = s.get('https://mobilelearn.chaoxing.com/newsign/preSign', params=params)
        resp_txt = resp.text
        logger.debug("Request url" + resp.url)
        if resp.status_code != 200:
            logger.error("Failed to get sign in, return code: " + str(resp.status_code) + "message: " + resp_txt)

        return resp_txt

    def sign_in_normal(self, course: dict, activity_id, name="", obj_id="aaa", lat=-1, lon=-1, type_=SignType.NORMAL):
        s = SessionManager.get_session()
        params = {
            "activeId": activity_id,
            "uid": self.get_uid(),
            "fid": self.get_fid(),
            "courseId": course["courseId"],
            "classId": course["clazzId"],
            "clientip": "",
            "objectId": obj_id,
            "name": name,
            "useragent": "",
            "latitude": lat,
            "longitude": lon,
            "appType": "15",
        }

        resp = s.get("https://mobilelearn.chaoxing.com/pptSign/stuSignajax", params=params)

        resp_txt = resp.text
        if resp.status_code != 200:
            logger.error("Failed to get sign in, return code: " + str(resp.status_code) + "message: " + resp_txt)

        if type_ != SignType.LOCATION:
            return resp_txt

        pattern = r"[^0-9\.]*(.+)米[^0-9\.]*"
        msg = re.match(pattern, resp_txt)
        logger.warning(f"距离签到位置 {msg}m")
        # TOD0: Implement triangulation for location signs
        return resp_txt

    def get_course_point(self, _courseid, _clazzid, _cpi):
        _session = SessionManager.get_session()
        _url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={_courseid}&clazzid={_clazzid}&cpi={_cpi}&ut=s"
        logger.trace("URL: " + _url)
        logger.trace("开始读取课程所有章节...")
        _resp = _session.get(_url)

        logger.trace(f"原始章节列表内容:\n{_resp.text}")
        # 章节读取成功的提示交给 main.py 统一输出（一行汇总，避免刷屏）
        logger.trace("课程章节读取成功...")
        return decode_course_point(_resp.text)

    def get_job_list(self, course: dict, point: dict) -> tuple[list[dict], dict]:
        _session = SessionManager.get_session()
        self.rate_limiter.limit_rate()
        job_list = []
        job_info = {}
        cards_params = {
            "clazzid": course["clazzId"],
            "courseid": course["courseId"],
            "knowledgeid": point["id"],
            "ut": "s",
            "cpi": course["cpi"],
            "v": "2025-0424-1038-3",
            "mooc2": 1
        }

        # 学习界面任务卡片数, 很少有3个的, 但是对于章节解锁任务点少一个都不行, 可以从API /mooc-ans/mycourse/studentstudyAjax获取值, 或者干脆直接加, 但二者都会造成额外的请求
        parsed_any = False
        _page0_parse_error = False
        _missing_pages = []
        for _possible_num in "0123456":

            logger.trace("开始读取章节所有任务点...")

            cards_params.update({"num": _possible_num})
            _resp = _session.get("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards", params=cards_params)
            if _resp.status_code != 200:
                # 返回 None 表示"没读到"，和"这一章本来就空"是两回事
                logger.error(f"章节任务点读取失败: HTTP {_resp.status_code}")
                logger.debug(_resp.text[:500])
                return None, {}

            _job_list, _job_info = decode_course_card(_resp.text)
            if _job_info.get("notOpen", False):
                # 直接返回, 节省一次请求
                logger.info("该章节未开放")
                return [], _job_info
            if _job_info.get("parseError"):
                # 新版泛雅把 num>=1 的页面改成 mArg = $mArg（由脚本注入），
                # 页面里没有可解析的 JSON。这种页面跳过就行，不能因为它
                # 把整章判成"读取失败"，否则新版课程一个任务点都刷不了。
                #
                # 日志分级：num=0 失败才是真正的异常信号（登录失效/验证码/改版），
                # num>=1 失败是每章都会发生的正常形态，只记 TRACE，避免刷屏误导。
                if _possible_num == "0":
                    _page0_parse_error = True
                    logger.warning(
                        "任务点第 0 页解析不出 mArg（可能是登录失效、验证码页或页面改版）"
                    )
                else:
                    _missing_pages.append(_possible_num)
                continue

            parsed_any = True
            job_list += _job_list
            job_info.update(_job_info)

        if _missing_pages:
            # 每章汇总成一条 DEBUG，不再逐页刷屏（新版 num>=1 本来就没有 JSON）
            logger.debug(
                "任务点第 {} 页无 mArg（新版只有第 0 页带全量），已跳过",
                "、".join(_missing_pages),
            )

        # 一页都没解析出来才算读取失败（登录页 / 验证码页 / 彻底改版）
        if not parsed_any:
            return None, {"parseError": True}
        if _page0_parse_error:
            logger.warning(
                "任务点第 0 页没解析出 mArg，但后续页有数据；下次整章读不到任务点时先检查登录状态"
            )

        # 同一批卡片可能跨页重复（新版 num=0 就带全量），按 jobid 去重
        seen_ids = set()
        unique_jobs = []
        for _job in job_list:
            _key = str(_job.get("jobid") or _job.get("id") or _job)
            if _key in seen_ids:
                continue
            seen_ids.add(_key)
            unique_jobs.append(_job)
        job_list = unique_jobs

        unknown_types = job_info.get("unknownCardTypes") or []
        if unknown_types:
            # 铁律 1：不认识的卡片不能当成"已完成"，宁可报读取失败让人来看
            logger.error(
                "章节 [{}] 出现未知任务点类型 {}：为避免把未完成记成完成，按读取失败处理",
                point.get("title", ""), "、".join(str(t) for t in unknown_types),
            )
            return None, job_info

        if not job_list:
            # 空章节也要把"访问"这一步做成功才算完成；失败同样按读取失败处理
            empty_result = self.study_emptypage(course, point)
            if empty_result is not None and empty_result.is_failure():
                logger.error("空页面任务未完成，按读取失败处理: {}", point.get("title", ""))
                return None, job_info

        logger.trace("章节任务点读取成功...")

        return job_list, job_info

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{playingTime * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]"
            .encode()).hexdigest()

    def video_progress_log(
            self,
            _session,
            _course,
            _job,
            _job_info,
            _dtoken,
            _duration,
            _playingTime,
            _type: str = "Video",
            _isdrag: int = 3,
            headers: Optional[dict] = None,
            engine_info: bool = False,
    ) -> tuple[bool, int]:

        if headers is None:
            logger.warning("null headers")
            headers = gc.VIDEO_HEADERS

        self.video_log_limiter.limit_rate(random_time=True, random_max=2)

        if "courseId" in _job["otherinfo"]:
            logger.error(_job["otherinfo"])
            raise RuntimeError("this is not possible")

        enc = self.get_enc(_course["clazzId"], _job["jobid"], _job["objectid"], _playingTime, _duration, self.get_uid())
        params = {
            "clazzId": _course["clazzId"],
            "playingTime": _playingTime,
            "duration": _duration,
            "clipTime": f"0_{_duration}",
            "objectId": _job["objectid"],
            "otherInfo": _job["otherinfo"],
            "courseId": _course["courseId"],
            "jobid": _job["jobid"],
            "userid": self.get_uid(),
            "isdrag": _isdrag,
            "view": "pc",
            "enc": enc,
            "dtype": _type
        }
        # 任务引擎的"章节"任务点要求带上 courseEngineInfo=true，
        # 章节刷完时平台才会在响应里下发 stuJobInfo（见类初始化里的说明）。
        if engine_info:
            params["courseEngineInfo"] = "true"

        _url = (
            f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/"
            f"{_course['cpi']}/"
            f"{_dtoken}"
        )

        face_capture_enc = _job["videoFaceCaptureEnc"]
        att_duration = _job["attDuration"]
        att_duration_enc = _job["attDurationEnc"]

        if face_capture_enc:
            params["videoFaceCaptureEnc"] = face_capture_enc
        if att_duration:
            params["attDuration"] = att_duration
        if att_duration_enc:
            params["attDurationEnc"] = att_duration_enc

        def perform_request(rt_val):
            params.update({"rt": rt_val, "_t": get_timestamp()})
            res = _session.get(_url, params=params, headers=headers)
            if res.status_code == 403:
                # 少数网络环境下 urllib3/OpenSSL 会被这个接口的风控按客户端指纹拒绝
                # （403 + 错误页），同一参数走 curl 或浏览器都是 200。先原样重放一次，
                # 重放成功就不算失败；重放也失败再走下面的验证码/403 分支。
                curl_res = _curl_get(_session, _url, params, headers)
                if curl_res is not None and curl_res.status_code == 200:
                    logger.info(
                        "视频打点被客户端指纹拦截，已用 curl 重放成功: jobid={}",
                        _job.get("jobid"),
                    )
                    res = curl_res
                elif curl_res is not None:
                    logger.debug("curl 重放视频打点仍然失败: HTTP {}", curl_res.status_code)
            if res.status_code == 403 or '验证码' in res.text or 'validate' in res.text:
                global _captcha_cooldown_until
                remain = _captcha_cooldown_until - time.time()
                if remain > 0:
                    logger.debug("验证码冷却中，等待 {:.0f} 秒再试", remain)
                    time.sleep(min(remain, _CAPTCHA_COOLDOWN_SECONDS))
                logger.warning("触发验证码，正在自动识别…")
                try:
                    from api.captcha import CxCaptcha
                    cookies_str = "; ".join([f"{k}={v}" for k, v in _session.cookies.items()])
                    ua = headers.get("User-Agent", gc.HEADERS.get("User-Agent"))
                    ocr_inst = getattr(self, '_ocr', None)
                    if ocr_inst is None:
                        from api.captcha import ocr_init
                        ocr_inst = ocr_init()
                        if ocr_inst:
                            self._ocr = ocr_inst
                    captcha_solver = CxCaptcha(user_agent=ua, cookies=cookies_str, ocr=ocr_inst)
                    solved = False
                    for attempt in range(3):
                        logger.debug("第 {} 次尝试通关验证码…", attempt + 1)
                        if captcha_solver.try_pass():
                            logger.info("验证码已通过")
                            solved = True
                            break
                        else:
                            logger.debug("验证码识别失败，重试中…")
                            time.sleep(2)
                    if solved:
                        _session.cookies.update(captcha_solver.s.cookies)
                        res = _session.get(_url, params=params, headers=headers)
                    else:
                        _captcha_cooldown_until = time.time() + _CAPTCHA_COOLDOWN_SECONDS
                        logger.warning(
                            "验证码多次识别失败，该任务点先跳过；{} 秒内不再重试验证码（稍后自动重试）",
                            _CAPTCHA_COOLDOWN_SECONDS,
                        )
                except Exception as e:
                    logger.error(f"验证码通关逻辑异常: {e}")
            return res

        rt = _job['rt']
        if not rt:
            rt_search = re.search(r"-rt_([1d])", _job['otherinfo'])
            if rt_search:
                rt_char = rt_search.group(1)
                rt = "0.9" if rt_char == "d" else "1"
                logger.trace(f"Got rt from otherinfo: {rt}")

        if rt:
            logger.trace(f"Got rt: {rt}")
            _job['rt'] = rt
            resp = perform_request(rt)
        else:
            logger.warning("Failed to get rt")
            for rt in [0.9, 1]:
                resp = perform_request(rt)
                if resp.status_code == 200:
                    logger.trace(resp.text)
                    return _parse_progress_passed(resp, owner=self if engine_info else None), 200
                elif resp.status_code == 403:
                    logger.warning("出现403报错, 正常尝试切换rt")
                else:
                    logger.warning("未知错误 jobid={}, status_code={}, 摘要:\n{}",
                                   _job.get("jobid"),
                                   resp.status_code,
                                   resp.text[:200])
                    break

        if resp.status_code == 200:
            logger.trace(resp.text)
            return _parse_progress_passed(resp, owner=self if engine_info else None), 200

        elif resp.status_code == 403:
            logger.debug(
                "视频进度上报返回403, jobid={}, 摘要={}",
                _job.get("jobid"),
                resp.text[:200],
            )

            # 若出现两个rt参数都返回403的情况, 则跳过当前任务
            logger.warning("这个任务被平台临时拦了一下，已跳过（稍后会自动重试；详情见日志文件）")
            logger.debug("403 请求 url: {}", resp.url)
            logger.debug("403 请求头: {}", dict(_session.headers) | headers)
            return False, 403

        logger.error(f"未知错误: {resp.status_code}")
        logger.debug("请求 url: {}", resp.url)
        logger.debug("请求头: {}", dict(_session.headers) | headers)
        return False, resp.status_code

    def _refresh_video_status(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]) \
            -> Optional[dict]:
        self.rate_limiter.limit_rate(random_time=True, random_max=0.2)
        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        info_url = (
            f"https://mooc1.chaoxing.com/ananas/status/{job['objectid']}?"
            f"k={self.get_fid()}&flag=normal"
        )
        try:
            resp = session.get(info_url, timeout=8, headers=headers)
        except RequestException as exc:
            logger.debug("刷新视频状态失败: {}", exc)
            return None

        if resp.status_code != 200:
            logger.debug("刷新视频状态返回码异常: {}" % resp.status_code)
            logger.debug(resp.text)
            return None

        try:
            data = resp.json()
        except ValueError as exc:
            logger.debug("解析视频状态响应失败: {}", exc)
            return None

        if data.get("status") == "success":
            return data

        return None

    def _recover_after_forbidden(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]):
        SessionManager.update_cookies()
        refreshed = self._refresh_video_status(session, job, _type)
        if refreshed:
            return refreshed

        if SessionManager.relogin_if_needed(self):
            return self._refresh_video_status(session, job, _type)

        return None

    @staticmethod
    def _close_pbar_safe(pbar_ref):
        if pbar_ref is not None:
            try:
                pbar_ref.leave = False
                pbar_ref.close()
            except Exception as e:
                logger.trace(f"关闭进度条失败: {e}")
        return None

    # 视频串行开关的进程级锁（见 study_video 说明）
    _video_lock = threading.Lock()

    def study_video(self, _course, _job, _job_info, _speed: float = 1.0,
                    _type: Literal["Video", "Audio"] = "Video",
                    engine_info: bool = False) -> StudyResult:
        """
        播放视频 / 音频任务。

        serial_video = true 时，同一个进程里一次只播一个视频。
        超星现在有心跳检测，多个视频同时播放容易被判定异常、把已刷的进度回退（#588），
        所以遇到"刷完又变回没刷"的用户可以打开它换取稳定；
        默认仍是并发（保持原来的速度），需要时在 config.ini 里设 serial_video = true。
        """
        # engine_info 只在需要时多传一个参数：社区里有测试/扩展会替换 _study_video，
        # 保持 5 参数调用形态，避免插件式猴子补丁被新参数打断。
        args = (_course, _job, _job_info, _speed, _type)
        if engine_info:
            args = args + (True,)
        if not self.kwargs.get("serial_video", False):
            return self._study_video(*args)
        with Chaoxing._video_lock:
            return self._study_video(*args)

    def _study_video(self, _course, _job, _job_info, _speed: float = 1.0,
                     _type: Literal["Video", "Audio"] = "Video",
                     engine_info: bool = False) -> StudyResult:
        _session = SessionManager.get_session()

        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        _info_url = f"https://mooc1.chaoxing.com/ananas/status/{_job['objectid']}?k={self.get_fid()}&flag=normal"
        # 视频信息接口偶尔会返回非 JSON（登录页 / 错误页），或者 status=failed 时
        # 干脆不带 dtoken、duration 这些字段。以前直接取键会抛 KeyError 把整个任务
        # 打挂（#290），这里统一按"这个任务读不到信息"处理，交给上层重试。
        try:
            _video_info = _session.get(_info_url, headers=headers).json()
        except Exception as e:
            logger.error(f"读取视频信息失败（{type(e).__name__}），跳过该任务点: {e}")
            return StudyResult.ERROR

        if not isinstance(_video_info, dict):
            logger.error("视频信息格式异常（不是 JSON 对象），跳过该任务点")
            return StudyResult.ERROR

        if _video_info.get("status") != "success":
            logger.error(f"视频信息状态异常（status={_video_info.get('status', '缺失')}），跳过该任务点")
            return StudyResult.ERROR

        _dtoken = _video_info.get("dtoken")
        if not _dtoken:
            logger.error("视频信息缺少 dtoken，跳过该任务点")
            return StudyResult.ERROR

        # Time in the real world: last_iter, gc.THRESHOLD
        # Time in the video (can be scaled with the speed factor): duration, play_time, last_log_time, wait_time

        try:
            duration = int(_video_info.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        if duration <= 0:
            logger.error("视频信息缺少时长（视频可能还没转码完成），跳过该任务点")
            return StudyResult.ERROR
        play_time = int(_job["playTime"]) // 1000
        last_log_time = 0
        last_iter = time.time()
        wait_time = int(random.uniform(30, 90))

        logger.info(f"开始任务: {_job['name']}, 总时长: {duration}s, 已进行: {play_time}s")

        forbidden_retry = 0
        max_forbidden_retry = 2

        passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration, duration,
                                                _type, headers=headers, _isdrag=4,
                                                engine_info=engine_info)
        if passed:
            logger.info("任务瞬间完成: {}", _job['name'])
            return StudyResult.SUCCESS

        # 平台记的 playTime 是"看到的位置"，通过与否要看真实累计观看时长：
        # 进度显示 100% 但没通过（例如上一次的结束上报被风控/指纹挡掉）时，
        # 在结尾反复重报没有意义，必须从头回看一遍（决 D3：不够就回看）。
        replay_used = False
        if play_time >= duration:
            logger.info(
                "任务 {} 进度已到结尾({}s/{}s)但平台未通过，从头回看一遍",
                _job.get("name", "?"), play_time, duration,
            )
            play_time = 0
            replay_used = True

        pbar = None
        # 服务器一直返回"200 但未通过"时不能无限循环（#358 / #451）：
        # 正常播放需要的理论时间 + 5 分钟缓冲，超了就当作失败交给上层重试。
        remaining = duration if replay_used else max(duration - play_time, 0)
        play_deadline = time.time() + remaining / max(_speed, 0.1) + 300
        stuck_reports = 0
        max_stuck_reports = 30
        try:
            while not passed:
                if time.time() > play_deadline:
                    logger.error(
                        "任务 {} 进度上报一直未被通过（已超过预计时间），先跳过，稍后重试",
                        _job.get("name", "?"),
                    )
                    return StudyResult.ERROR

                # Sometimes the last request needs to be sent several times to complete the task
                if play_time - last_log_time >= wait_time or play_time == duration:

                    passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration,
                                                            int(play_time), _type, headers=headers,
                                                            engine_info=engine_info)

                    if state == 403:
                        if forbidden_retry >= max_forbidden_retry:
                            logger.warning("403重试失败, 跳过当前任务")
                            return StudyResult.FORBIDDEN
                        forbidden_retry += 1
                        logger.warning(
                            "出现403报错, 正在尝试刷新会话状态 (第{}次)",
                            forbidden_retry,
                        )
                        time.sleep(random.uniform(2, 4))
                        refreshed_meta = self._recover_after_forbidden(_session, _job, _type)
                        if refreshed_meta and refreshed_meta.get("dtoken") and refreshed_meta.get(
                                "duration") is not None:
                            _dtoken = refreshed_meta["dtoken"]
                            duration = int(refreshed_meta["duration"])
                            refreshed_play_time = refreshed_meta.get("playTime")
                            if refreshed_play_time is not None:
                                play_time = int(refreshed_play_time)

                            logger.debug("视频令牌已刷新，持续时间: {}, 播放时间: {}", duration, play_time)
                            pbar = self._close_pbar_safe(pbar)
                            continue
                        else:
                            logger.error("会话恢复失败，刷新后的元数据缺少必要字段 (dtoken, duration)")
                            return StudyResult.ERROR

                    elif not passed and state != 200:
                        return StudyResult.ERROR

                    # 已经播到结尾、平台却一直不确认"通过"时，重报几次就放弃，
                    # 否则会在这里无限重报（#358 / #451）
                    if not passed and play_time >= duration:
                        stuck_reports += 1
                        if stuck_reports >= max_stuck_reports:
                            logger.error(
                                "任务 {} 已播放到结尾，但平台连续 {} 次未确认通过，先跳过稍后重试",
                                _job.get("name", "?"), stuck_reports,
                            )
                            return StudyResult.ERROR

                    wait_time = int(random.uniform(30, 90))
                    last_log_time = play_time

                    logger.trace("Progress logged")

                # Uploading the progress takes time, we assume that the video is still playing in the background, this manually calculates the time elapsed
                dt = (time.time() - last_iter) * _speed
                last_iter = time.time()
                play_time = min(duration, play_time + dt)

                # 检查手动模式锁是否被锁定
                manual_locked = False
                try:
                    manual_locked = TikuManual._manual_lock.locked()
                except Exception as e:
                    logger.trace(f"无法检查手动锁状态: {e}")

                if manual_locked:
                    pbar = self._close_pbar_safe(pbar)
                else:
                    if pbar is None:
                        pbar = tqdm(total=duration, initial=int(play_time), desc=_short_title(_job.get("name")),
                                    unit_scale=True, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}', leave=False)
                    pbar.n = int(play_time)
                    pbar.refresh()

                time.sleep(gc.THRESHOLD)
        finally:
            pbar = self._close_pbar_safe(pbar)

        logger.info("任务完成: {}", _job['name'])
        return StudyResult.SUCCESS

    def study_document(self, _course, _job, engine_info: bool = False) -> StudyResult:
        """
        Study a document in Chaoxing platform.

        This method makes a GET request to fetch document information for a given course and job.

        Args:
            _course (dict): Dictionary containing course information with keys:
                - courseId: ID of the course
                - clazzId: ID of the class
            _job (dict): Dictionary containing job information with keys:
                - jobid: ID of the job
                - otherinfo: String containing node information
                - jtoken: Authentication token for the job
            engine_info (bool): 是否处于任务引擎的"章节"任务点上下文。为 True 时，
                额外走一次引擎的 job/document 接口，平台可能因此下发 stuJobInfo
                （章节同步数据），由上层调用 autoPullChapterScore。

        Returns:
            requests.Response: Response object from the GET request

        Note:
            This method requires the following helper functions:
            - init_session(): To initialize a new session
            - get_timestamp(): To get current timestamp
            - re module for regular expression matching
        """
        _session = SessionManager.get_session()
        # otherinfo 里没有 nodeId 时不能直接 [0] 取（#22 / #374 这类 IndexError）
        node_ids = re.findall(r"nodeId_(.*?)-", str(_job.get("otherinfo", "")))
        if not node_ids:
            logger.error("文档任务缺少 nodeId 信息，跳过该任务点: {}", str(_job)[:200])
            return StudyResult.ERROR
        _url = (f"https://mooc1.chaoxing.com/ananas/job/document?jobid={_job.get('jobid', '')}"
                f"&knowledgeid={node_ids[0]}&courseid={_course.get('courseId', '')}"
                f"&clazzid={_course.get('clazzId', '')}&jtoken={_job.get('jtoken', '')}"
                f"&_dc={get_timestamp()}")
        _resp = _session.get(_url)
        if _resp.status_code != 200:
            logger.error("章节文档打开失败 -> [{}]{}", _resp.status_code, str(_resp.text)[:120])
            return StudyResult.ERROR
        # 只看 HTTP 200 会把平台拒绝当成功：能解析出 result=false 就判失败
        try:
            _doc_data = _resp.json()
        except ValueError:
            _doc_data = None
        if isinstance(_doc_data, dict) and _doc_data.get("result") is False:
            logger.error("章节文档未完成 -> {}", str(_doc_data.get("msg") or _doc_data)[:160])
            return StudyResult.ERROR
        logger.info("章节文档完成: {}", _job.get("name") or node_ids[0])
        if engine_info:
            # 任务引擎节点下，浏览器读完文档走的正是这个接口；它会返回
            # stuJobInfo（章节同步数据）。拿不到不影响文档本身的学习结果。
            self.finish_engine_document_job(_course, _job)
        return StudyResult.SUCCESS

    def finish_engine_document_job(self, _course, _job) -> Optional[dict]:
        """任务引擎上下文的文档完成接口，返回并暂存平台下发的 stuJobInfo。

        网页端（ananas/ueditor/documentJob.js 的 finishJob）在文档读完时请求
        /mooc-ans/job/document?...&courseEngineInfo=true，响应里的
        allowSendStuJobInfoMsg / stuJobInfo 会被回传给任务中心父页面，
        父页面再 POST autoPullChapterScore。这里是 CLI 侧等价复现。
        """
        node_ids = re.findall(r"nodeId_(.*?)-", str(_job.get("otherinfo", "")))
        if not node_ids:
            return None
        _session = SessionManager.get_session()
        params = {
            "jobid": _job.get("jobid", ""),
            "knowledgeid": node_ids[0],
            "courseid": _course.get("courseId", ""),
            "clazzid": _course.get("clazzId", ""),
            "jtoken": _job.get("jtoken", ""),
            "checkMicroTopic": "true",
            "microTopicId": _job.get("microTopicId", ""),
            "courseEngineInfo": "true",
        }
        try:
            resp = _session.get("https://mooc1.chaoxing.com/mooc-ans/job/document",
                                params=params, timeout=15)
        except Exception as e:
            logger.warning("文档任务引擎同步接口请求失败: {}", e)
            return None
        if getattr(resp, "status_code", 0) != 200:
            logger.warning("文档任务引擎同步接口返回异常: HTTP {}", getattr(resp, "status_code", "?"))
            return None
        try:
            payload = resp.json()
        except ValueError:
            logger.warning("文档任务引擎同步接口返回的不是 JSON，本次不同步章节成绩")
            return None
        if not isinstance(payload, dict):
            return None
        # 和网页端 documentJob.js 的 finishJob 一致：只有 status 为真才算接口成功
        if not payload.get("status"):
            logger.debug("文档任务引擎同步接口未被接受: {}", str(payload)[:200])
            return None
        capture_student_job_info(self, payload)
        return payload.get("stuJobInfo") if isinstance(payload.get("stuJobInfo"), dict) else None

    def study_work(self, _course, _job, _job_info) -> StudyResult:
        if self.tiku.DISABLE or not self.tiku:
            # 铁律：没有题库就不能把测验记成完成（历史 issue #223/#357）。
            # 返回 ERROR 会让这个任务点显示未完成，需要答题解锁的章节会停在这里。
            logger.error(
                "章节测验 [{} - {}] 未作答：没有可用题库；该任务点不会记为完成。",
                _course.get("title", "?"), _job.get("name", "?")
            )
            return StudyResult.ERROR

        _session = SessionManager.get_session()
        _url = "https://mooc1.chaoxing.com/mooc-ans/api/work"

        def is_not_permission_error(exception):
            return not isinstance(exception, PermissionError)

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
            retry=retry_if_exception(is_not_permission_error),
            reraise=True
        )
        def fetch_response_with_retry():
            _resp = _session.get(
                _url,
                params={
                    "api": "1",
                    "workId": _job["jobid"].replace("work-", ""),
                    "jobid": _job["jobid"],
                    "originJobId": _job["jobid"],
                    "needRedirect": "true",
                    "skipHeader": "true",
                    "knowledgeid": str(_job_info["knowledgeid"]),
                    "ktoken": _job_info["ktoken"],
                    "cpi": _job_info["cpi"],
                    "ut": "s",
                    "clazzId": _course["clazzId"],
                    "type": "",
                    "enc": _job["enc"],
                    "mooc2": "1",
                    "courseid": _course["courseId"],
                }
            )

            # 未创建完成该测验则不进行答题，目前遇到的情况是未创建完成等同于没题目
            if '教师未创建完成该测验' in _resp.text:
                raise PermissionError("教师未创建完成该测验")

            questions = decode_questions_info(_resp.text)

            if _resp.status_code == 200 and questions.get("questions"):
                return _resp, questions

            logger.warning(
                f"无效响应 (Code: {getattr(_resp, 'status_code', 'Unknown')}), 重试中...")
            raise RuntimeError(f"请求返回无效数据 (Code: {_resp.status_code})")

        # 章节检测最大重做次数（答错后收集错误反馈并重新提交，直到全对）
        # work_redo_enabled=false 时为单轮模式: 提交+检查+报告成绩, 不自动重做(适用于只允许作答一次的课程)
        if bool(self.kwargs.get("work_redo_enabled", False)):
            try:
                max_retries = max(1, int(self.kwargs.get("work_max_retries", 3)))
            except (TypeError, ValueError):
                max_retries = 3
        else:
            max_retries = 0
        query_delay = self.kwargs.get("query_delay", 0)
        feedback_history = None
        last_submitted_score = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.warning(
                    f"章节检测重做第 {attempt}/{max_retries} 轮，携带上一轮错误反馈重新作答")
                time.sleep(2)

            # 1. 获取题目
            final_resp = {}
            questions = {}
            try:
                final_resp, questions = fetch_response_with_retry()
            except PermissionError as e:
                logger.warning(f"跳过章节检测: {e}")
                return StudyResult.SUCCESS
            except Exception as e:
                if attempt > 0:
                    logger.error(f"重做轮无法获取题目(上一轮提交成绩 {last_submitted_score} 分), "
                                 f"该课程可能仅允许作答一次: {e}")
                else:
                    logger.error(f"获取章节检测题目失败, 达到最大重试次数: {e}")
                return StudyResult.ERROR

            _ORIGIN_HTML_CONTENT = final_resp.text  # 用于配合输出网页源码, 帮助修复#391错误

            # 2. 设置上一轮错误反馈（供AI重新作答时参考）
            if feedback_history and hasattr(self.tiku, 'set_work_feedback'):
                try:
                    self.tiku.set_work_feedback(feedback_history)
                    logger.debug("已将上一轮错误反馈设置到题库")
                except Exception as e:
                    logger.warning(f"设置题库错误反馈失败: {e}")

            # 3. 搜题
            total_questions = len(questions["questions"])
            found_answers = 0
            answers = self.tiku.query_all(questions["questions"], query_delay=query_delay)

            if not isinstance(answers, list):
                logger.error("题库 query_all 返回的数据格式异常，期望列表。将采用随机答案答题")
                answers = [None] * total_questions
            elif len(answers) != total_questions:
                logger.error(
                    f"题库返回的答案数量（{len(answers)}）与题目数量（{total_questions}）不匹配，正在补齐或截断以防错位！")
                answers = list(answers) + [None] * (total_questions - len(answers))
                answers = answers[:total_questions]

            from api.display import answer_line as _answer_line, answers_header as _answers_header, emit as _emit, emit_block as _emit_block
            _emit(_answers_header(str(_job.get("name") or "章节测验"), len(questions["questions"])))
            for _qi, (q, res) in enumerate(zip(questions["questions"], answers), 1):
                logger.debug(f"当前题目信息 -> {q}")
                answer = ""
                if not res:
                    # 随机答题
                    answer = random_answer(q["options"], q["type"])
                    q[f'answerSource{q["id"]}'] = "random"
                else:
                    # 根据响应结果选择答案
                    if q["type"] == "multiple":
                        # 多选处理（拆分 + 匹配逻辑见 build_multiple_answer）
                        answer = build_multiple_answer(res, q["options"], _ORIGIN_HTML_CONTENT)
                        # 匹配不到就往下走，由统一的"答案为空的兜底"改为随机作答
                    elif q["type"] == "single":
                        # 单选也进行切割，主要是防止返回的答案有异常字符
                        options_list = multi_cut(q["options"], _ORIGIN_HTML_CONTENT)
                        if options_list is not None:
                            t_res = clean_res(res)
                            for o in options_list:
                                if is_subsequence(t_res[0], o):
                                    answer = o[:1]
                                    break
                            if not answer and t_res:
                                answer = best_option_by_similarity(t_res[0], options_list, threshold=0.8)
                    elif q["type"] == "judgement":
                        answer = "true" if self.tiku.judgement_select(res) else "false"
                    elif q["type"] == "completion":
                        if isinstance(res, list):
                            # 多个空必须用 # 隔开，否则会被当成一个空的答案
                            answer = "#".join(str(x).strip() for x in res if str(x).strip())
                        elif isinstance(res, str):
                            answer = res
                    else:
                        # 其他类型直接使用答案 （目前仅知有简答题，待补充处理）
                        answer = res

                    if not answer:  # 检查 answer 是否为空
                        logger.debug(f"找到答案但答案未能匹配 -> {res}\t随机选择答案")
                        answer = random_answer(q["options"], q["type"])  # 如果为空，则随机选择答案
                        q[f'answerSource{q["id"]}'] = "random"
                    else:
                        logger.info(f"成功获取到答案：{answer}")
                        q[f'answerSource{q["id"]}'] = "cover"
                        found_answers += 1
                # 填充答案 + 实时留痕（控制台与运行日志各一份）
                q["answerField"][f'answer{q["id"]}'] = answer
                _emit(_answer_line(_qi, q.get("type"), answer, q.get("title")))
                if q.get("type") == "shortanswer":
                    _emit_block(f"简答 {_qi}", answer)
                logger.debug(f'{q["title"]} 填写答案为 {answer}')
            cover_rate = (found_answers / total_questions) * 100
            logger.info(f"章节检测题库覆盖率： {cover_rate:.0f}%")
            # 提交模式  现在与题库绑定,留空直接提交, 1保存但不提交
            is_manual_mode = (
                    getattr(self.tiku, 'is_manual', False) or
                    self.tiku.__class__.__name__ == 'TikuManual' or
                    (self.tiku.__class__.__name__ == 'TikuFallback' and any(
                        getattr(p, 'is_manual', False) or p.__class__.__name__ == 'TikuManual' for p in
                        getattr(self.tiku, 'providers', [])))
            )
            if self.tiku.get_submit_params() == "1":
                questions["pyFlag"] = "1"
            elif is_manual_mode or cover_rate >= self.tiku.COVER_RATE * 100 or self.rollback_times >= 1:
                questions["pyFlag"] = ""
            else:
                questions["pyFlag"] = "1"
                logger.info(f"章节检测题库覆盖率低于{self.tiku.COVER_RATE * 100:.0f}%，不予提交")
            # 组建提交表单
            if questions["pyFlag"] == "1":
                for q in questions["questions"]:
                    questions.update(
                        {
                            f'answer{q["id"]}':
                                q["answerField"][f'answer{q["id"]}'] if q[f'answerSource{q["id"]}'] == "cover" else '',
                            f'answertype{q["id"]}': q["answerField"][f'answertype{q["id"]}'],
                        }
                    )
            else:
                for q in questions["questions"]:
                    questions.update(
                        {
                            f'answer{q["id"]}': q["answerField"][f'answer{q["id"]}'],
                            f'answertype{q["id"]}': q["answerField"][f'answertype{q["id"]}'],
                        }
                    )

            # 填空题必须按空提交：answerEditor{id}1、answerEditor{id}2 … + tiankongsize{id}。
            # 只发 answer{id} 的话网页端会显示答案为空（#615 / #575）。
            for _q in questions["questions"]:
                if isinstance(_q, dict):
                    build_completion_fields(questions, _q)

            from api import review as _review
            review_items = []
            for question in questions["questions"]:
                if question.get("type") != "shortanswer":
                    continue
                text = questions.get(f"answer{question['id']}", "")
                if text:
                    item = _review.record(_review.KIND_QUIZ, text,
                                          course=_course.get("title", ""), task=_job.get("name", ""),
                                          status="待提交" if questions["pyFlag"] == "" else "待保存")
                    if not item:
                        for previous in review_items:
                            _review.update(previous, "复核写入失败，未提交")
                        logger.error("简答题复核记录写入失败，本次不提交")
                        return StudyResult.ERROR
                    review_items.append(item)

            del questions["questions"]

            # 4. 提交
            accepted = False
            try:
                res = _session.post(
                    "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew",
                    data=questions,
                    headers={
                        "Host": "mooc1.chaoxing.com",
                        "sec-ch-ua-platform": '"Windows"',
                        "X-Requested-With": "XMLHttpRequest",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "sec-ch-ua-mobile": "?0",
                        "Origin": "https://mooc1.chaoxing.com",
                        "Sec-Fetch-Site": "same-origin",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Dest": "empty",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
                    },
                )
                if res.status_code == 200:
                    res_json = res.json()
                    if res_json["status"]:
                        accepted = True
                        logger.info(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题成功 -> {res_json["msg"]}')
                    else:
                        logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {res_json["msg"]}')
                        return StudyResult.ERROR
                else:
                    logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {res.text}')
                    return StudyResult.ERROR

            finally:
                for item in review_items:
                    _review.update(item, ("平台已接受提交" if questions["pyFlag"] == "" else "平台已保存，未提交") if accepted else "请求失败或平台未确认")

            # 5. 只保存未提交：平台不会把任务点记为完成，不能返回成功（铁律 1）
            if questions["pyFlag"] == "1":
                logger.warning("章节检测已保存但未提交（submit=false），本任务点不记为完成")
                return StudyResult.ERROR

            # 6. 提交后检查成绩：若未全部正确，则收集错误反馈并重新作答提交
            result_info = None
            for _try in range(3):
                result_info = self._check_work_result(_session, _course, _job, _job_info, questions)
                if result_info is not None:
                    break
                time.sleep(2)
            if result_info is None:
                # 读不到成绩就不能说通过（铁律 1）：重试 3 次后按失败处理
                logger.error("提交后连续 3 次读不到章节检测成绩，本任务点不记为完成")
                return StudyResult.ERROR

            score = float(result_info.get("score", 0.0) or 0.0)
            unknown = int(result_info.get("unknown", 0) or 0)
            if result_info.get("all_correct", False):
                logger.info(f"章节检测全部正确（成绩 {score} 分），通过！")
                return StudyResult.SUCCESS
            if score >= 99.95:
                # 逐题比对存在格式差异或解析失配, 但满分成绩说明实际全对, 以分数为准
                if unknown > 0:
                    logger.warning(f"成绩 {score} 分达到满分, 以分数为准通过"
                                   f"（{unknown} 题答案字段未能解析, 建议人工复核）")
                else:
                    logger.info(f"逐题比对存在格式差异, 但成绩 {score} 分达到满分, 以分数为准, 通过！")
                return StudyResult.SUCCESS
            if unknown > 0:
                # 解析失配且未达满分: 判定不可信, 不触发重做, 保留已提交成绩
                logger.warning(f"{unknown} 题答案字段解析失败且成绩 {score} 分未达满分, 跳过重做判定")
                return StudyResult.SUCCESS

            # 7. 未全对：收集错误反馈，进入下一轮重做
            feedback_history = result_info.get("feedback", [])
            wrong_count = len(feedback_history)
            if attempt >= max_retries:
                # 已是最后一轮(含单轮模式), 保留已提交成绩, 不再触发无意义的重做
                logger.warning(f"章节检测有 {wrong_count}/{total_questions} 题回答错误（成绩 {score} 分），"
                               f"已保留本次成绩, 请人工检查处理")
                return StudyResult.SUCCESS
            logger.warning(
                f"章节检测有 {wrong_count}/{total_questions} 题回答错误（成绩 {score} 分），"
                f"已将错误反馈给AI，准备重新作答提交 (第 {attempt + 1}/{max_retries + 1} 轮)"
            )
            self.rollback_times += 1
            last_submitted_score = score

        # 达到最大重试次数仍未全对
        logger.error(f"章节检测重试 {max_retries + 1} 次仍未全部正确，请人工检查处理")
        return StudyResult.ERROR

    def _check_work_result(self, _session, _course, _job, _job_info, questions) -> Optional[dict]:
        """
        章节检测提交后，查询最新一次作答的成绩与对错详情，供判断是否需要重做。

        Args:
            _session: 当前会话
            _course: 课程信息
            _job: 任务点信息
            questions: 提交时使用的表单数据（含 workId / workAnswerId 等）

        Returns:
            {"all_correct": bool, "feedback": list[str], "score": float, "times": int}
            或 None（无法获取成绩详情时返回 None）
        """
        work_id = str(
            questions.get("workId", "")
            or questions.get("workRelationId", "")
            or _job["jobid"].replace("work-", "")
        )
        work_answer_id = str(questions.get("workAnswerId", "") or "")
        course_id = str(_course.get("courseId", ""))
        class_id = str(_course.get("clazzId", ""))
        cpi = str(_course.get("cpi", "") or questions.get("cpi", ""))

        # 1. 获取作答记录列表（提交后服务端异步生成记录，需稍作等待并多次重试）
        records = None
        for attempt in range(5):
            try:
                resp = _session.get(
                    "https://mooc1.chaoxing.com/mooc-ans/work/record-list",
                    params={
                        "courseId": course_id,
                        "classId": class_id,
                        "workId": work_id,
                        "workAnswerId": work_answer_id,
                        "cpi": cpi,
                        "api": "1",
                        "mooc2": "1",
                        "ut": "s",
                    },
                    timeout=20,
                )
                records = _parse_work_record_list(resp.text)
                if records:
                    break
            except Exception as e:
                logger.warning(f"获取章节检测作答记录失败 (第{attempt + 1}次): {e}")
            if attempt < 4:
                time.sleep(1.5)

        if not records:
            # 兜底：重新访问题目页判断是否已通过（详情页=已提交有成绩；可编辑页=未通过可重做）
            logger.warning("无法获取章节检测作答记录，尝试通过题目页状态判断")
            try:
                resp = _session.get(
                    "https://mooc1.chaoxing.com/mooc-ans/api/work",
                    params={
                        "api": "1",
                        "workId": _job["jobid"].replace("work-", ""),
                        "jobid": _job["jobid"],
                        "originJobId": _job["jobid"],
                        "needRedirect": "true",
                        "skipHeader": "true",
                        "knowledgeid": str(_job_info.get("knowledgeid", "") or _job.get("knowledgeid", "")),
                        "ktoken": str(_job_info.get("ktoken", "") or _job.get("ktoken", "")),
                        "cpi": str(_job_info.get("cpi", "") or _job.get("cpi", "") or cpi),
                        "ut": "s",
                        "clazzId": class_id,
                        "type": "",
                        "enc": str(_job.get("enc", "")),
                        "mooc2": "1",
                        "courseid": course_id,
                    },
                    timeout=20,
                )
                html = resp.text
                if 'answerwqbid' in html:
                    # 可编辑页面：说明未全部正确，可重新作答（该判定为页面状态推断, 未核对实际成绩）
                    logger.warning("题目页仍可编辑, 推断章节检测未全部正确(未核对成绩)")
                    return {
                        "all_correct": False,
                        "feedback": [],
                        "score": 0.0,
                        "times": 0,
                    }
                elif '正确答案' in html and '我的答案' in html:
                    # 已提交详情页：解析成绩与对错
                    detail = _parse_work_record_detail(html)
                    if detail:
                        evaluated = evaluate_work_detail(detail)
                        if evaluated["unjudgeable"]:
                            logger.warning("页面没有渲染出「我的答案」，无法逐题判断对错，本项等待复查")
                            return None
                        m = re.search(r'本次成绩<i>([\d.]+)</i>分', html)
                        score = float(m.group(1)) if m else 0.0
                        return {
                            "all_correct": evaluated["all_correct"],
                            "feedback": evaluated["feedback"],
                            "score": score,
                            "times": 0,
                            "unknown": evaluated["unknown"],
                        }
                return None
            except Exception as e:
                logger.warning(f"兜底判断章节检测状态失败: {e}")
                return None

        latest_times = max(r[0] for r in records)
        latest_score = dict(records).get(latest_times, 0.0)

        # 2. 获取最新一次作答详情（含每道题对错与正确答案）
        try:
            resp = _session.get(
                "https://mooc1.chaoxing.com/mooc-ans/work/record-detail",
                params={
                    "courseId": course_id,
                    "classId": class_id,
                    "workId": work_id,
                    "workAnswerId": work_answer_id,
                    "times": str(latest_times),
                    "cpi": cpi,
                    "ut": "s",
                    "isdisplaytable": "0",
                    "firstHeader": "2",
                    "isWork": "false",
                    "workSystem": "0",
                    "api": "1",
                    "archive": "false",
                    "mooc2": "1",
                },
                timeout=20,
            )
            detail = _parse_work_record_detail(resp.text)
        except Exception as e:
            logger.warning(f"获取章节检测作答详情失败: {e}")
            return None

        if not detail:
            logger.warning("章节检测作答详情解析为空，跳过成绩检查")
            return None

        # 3. 逐题判断对错，收集错误反馈
        evaluated = evaluate_work_detail(detail)
        if evaluated["unjudgeable"]:
            # 页面没给出"我的答案"（只渲染了图标之类），判定不可信
            logger.warning("作答详情里没有「我的答案」，无法逐题判断对错，本项等待复查")
            return None

        logger.debug(
            "章节检测成绩: {} 分, 全部正确: {}, 错题数: {}",
            latest_score, evaluated["all_correct"], len(evaluated["feedback"]),
        )
        return {
            "all_correct": evaluated["all_correct"],
            "feedback": evaluated["feedback"],
            "score": latest_score,
            "times": latest_times,
            "unknown": evaluated["unknown"],
        }

    def study_read(self, _course, _job, _job_info) -> StudyResult:
        """
        阅读任务学习, 仅完成任务点, 并不增长时长
        """
        _session = SessionManager.get_session()
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/ananas/job/readv2",
            params={
                "jobid": _job["jobid"],
                "knowledgeid": _job_info["knowledgeid"],
                "jtoken": _job["jtoken"],
                "courseid": _course["courseId"],
                "clazzid": _course["clazzId"],
            },
        )
        if _resp.status_code != 200:
            logger.error(f"阅读任务学习失败 -> [{_resp.status_code}]{_resp.text}")
            return StudyResult.ERROR
        try:
            _resp_json = _resp.json()
        except ValueError:
            logger.error("阅读任务返回非 JSON，无法确认结果，按失败处理")
            return StudyResult.ERROR
        if isinstance(_resp_json, dict) and _resp_json.get("result") is False:
            logger.error("阅读任务未完成 -> {}", str(_resp_json.get("msg") or _resp_json)[:160])
            return StudyResult.ERROR
        _msg = _resp_json.get("msg", "成功") if isinstance(_resp_json, dict) else "成功"
        logger.info(f"阅读任务学习 -> {_msg}")
        return StudyResult.SUCCESS

    def _send_monitor_heartbeat(self, course, point):
        """
        发送章节监控心跳包到 detect.chaoxing.com。

        模拟真实浏览器的 JSONP 打点请求，佐证访问行为的真人属性。

        Args:
            course: 课程信息字典
            point: 当前章节信息字典
        """
        version = get_timestamp()
        callback = f"jsonp{secrets.randbelow(10**21 - 10**20) + 10**20}"
        params = {
            "version": version,
            "refer": "http://i.mooc.chaoxing.com",
            "from": "",
            "fid": self.get_fid(),
            "jsoncallback": callback,
            "t": get_timestamp(),
        }
        referer_url = (
            f"https://mooc1.chaoxing.com/mycourse/studentstudy?"
            f"chapterId={point['id']}&courseId={course['courseId']}"
            f"&clazzid={course['clazzId']}&cpi={course['cpi']}&mooc2=1"
        )
        try:
            session = SessionManager.get_session()
            resp = session.get(
                "https://detect.chaoxing.com/api/monitor",
                params=params,
                headers={"Referer": referer_url},
                timeout=5,
            )
            logger.trace(f"Monitor heartbeat sent -> {resp.status_code}")
        except Exception as e:
            logger.trace(f"Monitor heartbeat failed (non-critical): {e}")

    def study_emptypage(self, _course, point):
        _session = SessionManager.get_session()
        # &cpi=0&verificationcode=&mooc2=1&microTopicId=0&editorPreview=0
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax",
            params={
                "courseId": _course["courseId"],
                "clazzid": _course["clazzId"],
                "chapterId": point["id"],
                "cpi": _course["cpi"],
                "verificationcode": "",
                "mooc2": 1,
                "microTopicId": 0,
                "editorPreview": 0,
            },
            timeout=8,
        )
        if _resp.status_code != 200:
            logger.error(f"空页面任务失败 -> [{_resp.status_code}]{point['title']}")
            return StudyResult.ERROR
        else:
            logger.info(f"空页面任务完成 -> {point['title']}")
            return StudyResult.SUCCESS

    def _access_chapter_for_count(self, _course, point):
        _session = SessionManager.get_session()
        # &cpi=0&verificationcode=&mooc2=1&microTopicId=0&editorPreview=0
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax",
            params={
                "courseId": _course["courseId"],
                "clazzid": _course["clazzId"],
                "chapterId": point["id"],
                "cpi": _course["cpi"],
                "verificationcode": "",
                "mooc2": 1,
                "microTopicId": 0,
                "editorPreview": 0,
            },
            timeout=8,
        )
        if _resp.status_code != 200:
            logger.error(f"章节访问失败 -> [{_resp.status_code}]{point['title']}")
            return None
        else:
            logger.info(f"章节访问成功 -> {point['title']}")
            return _resp.text

    def _extract_and_send_setlog(self, html_text):
        """
        从 studentstudyAjax 返回的 HTML 中提取 setlog URL 并执行。

        该 URL 包含服务端生成的 encode 参数，是记录章节学习次数的关键 API。

        Args:
            html_text: studentstudyAjax 返回的 HTML 内容
        """
        match = re.search(
            r'<script[^>]+src="(https://fystat-ans\.chaoxing\.com/log/setlog[^"]+)"',
            html_text
        )
        if not match:
            logger.trace("未在响应中找到 setlog URL")
            return

        setlog_url = match.group(1)
        try:
            session = SessionManager.get_session()
            resp = session.get(setlog_url, timeout=5)
            logger.trace(f"Setlog sent -> {resp.status_code}")
        except Exception as e:
            logger.trace(f"Setlog failed (non-critical): {e}")

    def increase_chapter_learning_count(self, course, points, target_count):
        """
        增加课程章节学习次数。

        循环遍历课程的所有章节，每访问一个章节页面：
        1. 调 studentstudyAjax 获取页面 HTML（含服务端生成的 setlog URL）
        2. 提取并执行 setlog URL（记录学习次数）
        3. 立即发送 monitor 心跳包（模拟 fn() 首次心跳）
        4. 停留 30 秒（模拟前端 setInterval(fn, 30000) 的间隔）
        5. 再次发送 monitor 心跳包（模拟 30s 后的第二次心跳）
        6. 计数器 +1，继续下一个章节

        Args:
            course: 课程信息字典
            points: 课程所有章节列表
            target_count: 目标总次数

        Returns:
            StudyResult: 操作结果
        """
        total = 0
        consecutive_failures = 0
        max_consecutive_failures = 10
        logger.info(f"开始增加章节学习次数, 目标总次数: {target_count}, 章节数: {len(points)}")
        if not points:
            logger.warning("章节列表为空, 跳过章节学习次数增加")
            return StudyResult.SUCCESS
        while total < target_count:
            for point in points:
                if total >= target_count:
                    break
                self.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)
                html_text = self._access_chapter_for_count(course, point)
                if not html_text:
                    logger.error(f"章节学习次数增加失败, 当前章节: {point['title']}")
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            f"章节学习次数增加连续失败 {consecutive_failures} 次, 终止任务"
                        )
                        return StudyResult.ERROR
                    continue

                consecutive_failures = 0

                # 第 1 步：从 HTML 中提取 setlog URL 并执行（真正的计次 API）
                self._extract_and_send_setlog(html_text)

                # 第 2 步：立即发送 monitor 心跳包（模拟 fn()）
                self._send_monitor_heartbeat(course, point)

                # 第 3 步：停留 30 秒（模拟前端 setInterval 间隔）
                time.sleep(30)

                # 第 4 步：再次发送 monitor 心跳包（模拟 setInterval 触发的第二次心跳）
                self._send_monitor_heartbeat(course, point)

                total += 1
                logger.info(f"章节学习次数进度: {total}/{target_count}")
        logger.info(f"章节学习次数增加完成, 共完成: {total} 次")
        return StudyResult.SUCCESS
