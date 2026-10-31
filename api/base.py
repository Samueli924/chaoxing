# -*- coding: utf-8 -*-
import functools
import os
import random
import secrets
import re
import threading
import time
import uuid
from difflib import SequenceMatcher
from enum import Enum, IntEnum
from hashlib import md5
from typing import Optional, Literal
from typing_extensions import Self

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
from api.cookies import parse_cookie_string, save_cookies, use_cookies
from api.decode import (
    decode_course_list,
    decode_course_point,
    decode_course_card,
    decode_course_folder,
    decode_questions_info,
)
from api.task_runner import TaskStateHub


def get_timestamp():
    return str(int(time.time() * 1000))


def create_session(cookies: Optional[dict] = None) -> requests.Session:
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=10))
    session.mount("http://", HTTPAdapter(max_retries=10))
    session.request = functools.partial(session.request, timeout=5)
    # For debug purposes
    # session.verify=False
    session.headers.clear()
    session.headers.update(gc.HEADERS)
    if cookies is not None:
        session.cookies.update(cookies)
    else:
        session.cookies.update(use_cookies())
    return session


class SessionManager:
    _instance = None
    _login_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_session"):
            self._session = create_session({} if TaskStateHub().is_web_mode() else None)

    @classmethod
    def get_instance(cls) -> Self:
        return cls()

    @classmethod
    def get_session(cls) -> requests.Session:
        instance = cls.get_instance()
        return instance._session

    @classmethod
    def update_cookies(cls):
        if not TaskStateHub().is_web_mode():
            cls.get_instance()._session.cookies.update(use_cookies())

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
        # 仅在字符串长度大于1时才尝试去除开头的字母编号，防止误删单个字母答案
        cleaned = re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*|[.,!?;:，。！？；：]', '', c) if len(c) > 1 else c
        cleaned_res.append(cleaned.strip())
    return cleaned_res


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
    logger.info(f"随机选择 -> {answer}")
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
    def __init__(self, account: Account = None, tiku: Tiku = None, session: Optional[requests.Session] = None, **kwargs):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku
        self.kwargs = kwargs
        self.rollback_times = 0
        self.rate_limiter = RateLimiter(0.5)  # 其他接口速率限制比较松
        self.video_log_limiter = RateLimiter(2)  # 上报进度极其容易卡验证码，限制2s一次

        if session is not None:
            self._session = session
        else:
            raw_cookies = kwargs.get("cookies")
            cookie_dict = None
            if isinstance(raw_cookies, dict):
                cookie_dict = raw_cookies
            elif isinstance(raw_cookies, str):
                cookie_dict = parse_cookie_string(raw_cookies)

            sm_session = SessionManager.get_session()
            if hasattr(sm_session, "_mock_return_value") or type(sm_session).__name__ in ("MagicMock", "Mock"):
                self._session = sm_session
            else:
                self._session = create_session(cookie_dict)

    def get_session(self) -> requests.Session:
        return self._session

    def login(self, login_with_cookies=False):
        if login_with_cookies:
            logger.info("Logging in with cookies")
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

        temp_session = requests.Session()
        temp_session.headers.update(gc.HEADERS)
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
        resp = temp_session.post(_url, headers=gc.HEADERS, data=_data, timeout=10)
        if resp and resp.json().get("status") == True:
            _session = self._session
            _session.cookies.clear()
            _session.cookies.update(temp_session.cookies)
            if TaskStateHub().is_web_mode():
                SessionManager.get_session().cookies.clear()
                SessionManager.get_session().cookies.update(_session.cookies)
                cfg_path = self.kwargs.get("config_path")
                if cfg_path and os.path.exists(cfg_path):
                    try:
                        from api.account_manager import AccountManager
                        new_cookies = "; ".join(f"{k}={v}" for k, v in _session.cookies.items())
                        uid = _session.cookies.get("_uid") or _session.cookies.get("UID") or self.account.username
                        acc_dir = os.path.dirname(os.path.abspath(cfg_path))
                        AccountManager(accounts_dir=acc_dir, auto_import_legacy=False).save_account(str(uid), {
                            "username": self.account.username,
                            "password": self.account.password,
                            "cookies": new_cookies,
                            "use_cookies": "true",
                        })
                    except Exception as e:
                        logger.debug(f"同步保存WebUI重登Cookie失败: {e}")
            else:
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
        else:
            return {"status": False, "msg": str(resp.json().get("msg2"))}

    def get_name(self, session: Optional[requests.Session] = None) -> str:
        _session = session or self._session
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
        session = self._session
        if not (session.cookies.get("_uid") or session.cookies.get("UID")):
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
        return self._session.cookies.get("fid", 1024)

    def get_uid(self):
        s = self._session
        if "_uid" in s.cookies:
            return s.cookies["_uid"]
        if "UID" in s.cookies:
            return s.cookies["UID"]
        raise ValueError("Cannot get uid !")

    def get_course_list(self):
        _session = self._session
        logger.trace("正在读取所有的课程列表...")

        # 官方接口直接包含服务端权威的 coursestate 结课状态
        try:
            _api_url = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata"
            _api_resp = _session.get(_api_url, timeout=8)
            if _api_resp.status_code == 200:
                api_data = _api_resp.json()
                if api_data.get("result") == 1:
                    api_courses = []
                    for ch in api_data.get("channelList", []):
                        content = ch.get("content", {})
                        c_list = content.get("course", {}).get("data", [])
                        c_data = c_list[0] if c_list else {}
                        course_id = str(c_data.get("id") or "")
                        clazz_id = str(content.get("id") or "")
                        cpi = str(content.get("cpi") or ch.get("cpi") or "")
                        title = c_data.get("name") or content.get("name") or ""
                        if not course_id or not clazz_id:
                            continue
                        is_ended = (content.get("isFiled") == 1 or c_data.get("coursestate") == 1)
                        api_courses.append({
                            "id": f"c_{course_id}",
                            "info": f"{clazz_id}_{cpi}",
                            "roleid": f"stu_{clazz_id}",
                            "clazzId": clazz_id,
                            "courseId": course_id,
                            "cpi": cpi,
                            "title": title,
                            "desc": c_data.get("schools") or "",
                            "teacher": c_data.get("teacherfactor") or "",
                            "status": "已结课" if is_ended else "进行中",
                            "is_ended": is_ended,
                        })
                    if api_courses:
                        try:
                            from api.decode import decode_archived_courses
                            _archive_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/archivecourse/student"
                            _archive_resp = _session.get(_archive_url, timeout=8)
                            _archive_resp.encoding = "utf-8"
                            if _archive_resp.status_code == 200:
                                api_courses += decode_archived_courses(_archive_resp.text)
                        except Exception:
                            pass
                        logger.debug("课程列表读取完毕...")
                        return api_courses
        except Exception as e:
            logger.debug(f"尝试读取官方课程API异常，降级为HTML解析: {e}")

        _url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
        _data = {"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0}

        # 接口突然抽风, 增加headers
        # 有可能只是referer的问题
        _headers = {
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
        }
        _resp = _session.post(_url, headers=_headers, data=_data)
        _resp.encoding = "utf-8"
        # logger.trace(f"原始课程列表内容:\n{_resp.text}")
        logger.debug("课程列表读取完毕...")
        course_list = decode_course_list(_resp.text)

        _interaction_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
        _interaction_resp = _session.get(_interaction_url)
        _interaction_resp.encoding = "utf-8"
        course_folder = decode_course_folder(_interaction_resp.text)
        for folder in course_folder:
            _data = {
                "courseType": 1,
                "courseFolderId": folder["id"],
                "query": "",
                "superstarClass": 0,
            }
            _resp = _session.post(_url, data=_data)
            _resp.encoding = "utf-8"
            course_list += decode_course_list(_resp.text)

        try:
            from api.decode import decode_archived_courses
            _archive_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/archivecourse/student"
            _archive_resp = _session.get(_archive_url, timeout=8)
            _archive_resp.encoding = "utf-8"
            if _archive_resp.status_code == 200:
                course_list += decode_archived_courses(_archive_resp.text)
        except Exception as e:
            logger.debug(f"读取归档已结课课程异常: {e}")

        return course_list

    def get_activity_list(self, course: dict) -> list[dict]:
        s = self._session
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
        s = self._session
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
        s = self._session
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
        _session = self._session
        _url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={_courseid}&clazzid={_clazzid}&cpi={_cpi}&ut=s"
        logger.trace("URL: " + _url)
        logger.trace("开始读取课程所有章节...")
        _resp = _session.get(_url)

        logger.trace(f"原始章节列表内容:\n{_resp.text}")
        logger.info("课程章节读取成功...")
        return decode_course_point(_resp.text)

    def get_job_list(self, course: dict, point: dict) -> tuple[list[dict], dict]:
        _session = self._session
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
        for _possible_num in "0123456":

            logger.trace("开始读取章节所有任务点...")

            cards_params.update({"num": _possible_num})
            _resp = _session.get("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards", params=cards_params)
            if _resp.status_code != 200:
                logger.error(f"未知错误: {_resp.status_code} 正在跳过")
                logger.error(_resp.text)
                return [], {}

            _job_list, _job_info = decode_course_card(_resp.text)
            if _job_info.get("notOpen", False):
                # 直接返回, 节省一次请求
                logger.info("该章节未开放")
                return [], _job_info

            job_list += _job_list
            job_info.update(_job_info)

        if not job_list:
            self.study_emptypage(course, point)

        logger.trace(f"原始任务点列表内容:\n{_resp.text}")
        logger.info("章节任务点读取成功...")

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
            is_9011_forbidden = res.status_code == 403 and ("9011" in res.text or "没有权限" in res.text)
            has_captcha_indicator = ("验证码" in res.text or "captcha" in res.text.lower() or "validate" in res.text.lower()) and not is_9011_forbidden
            if has_captcha_indicator:
                logger.warning("检测到验证码拦截，正在尝试自动通过验证码...")
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
                        logger.info(f"第 {attempt + 1} 次尝试通关验证码...")
                        if captcha_solver.try_pass():
                            logger.success("验证码通关成功！")
                            solved = True
                            break
                        else:
                            logger.warning("验证码验证失败，正在重试...")
                            time.sleep(2)
                    if solved:
                        _session.cookies.update(captcha_solver.s.cookies)
                        res = _session.get(_url, params=params, headers=headers)
                    else:
                        logger.error("多次验证码通关失败，可能需要手动干预。")
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
            if resp.status_code == 403 and "9011" not in resp.text:
                alt_rt = "1" if str(rt) in ["0.9", "d"] else "0.9"
                logger.warning(f"当前 rt={rt} 返回403，尝试切换为备选 rt={alt_rt}")
                alt_resp = perform_request(alt_rt)
                if alt_resp.status_code == 200:
                    _job['rt'] = alt_rt
                    resp = alt_resp
        else:
            logger.warning("Failed to get rt")
            for rt in [0.9, 1]:
                resp = perform_request(rt)
                if resp.status_code == 200:
                    logger.trace(resp.text)
                    return resp.json()["isPassed"], 200
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
            return resp.json()["isPassed"], 200

        elif resp.status_code == 403:
            logger.debug(
                "视频进度上报返回403, jobid={}, 摘要={}",
                _job.get("jobid"),
                resp.text[:200],
            )

            # 若出现两个rt参数都返回403的情况, 则跳过当前任务
            logger.error("出现403报错, 尝试修复无效, 正在跳过当前任务点...")
            logger.error("请求url: {}", resp.url)
            logger.error("请求头: {}", dict(_session.headers) | headers)
            return False, 403

        logger.error(f"未知错误: {resp.status_code}")
        logger.error("请求url:", resp.url)
        logger.error("请求头：", dict(_session.headers) | headers)
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

    def study_video(self, _course, _job, _job_info, _speed: float = 1.0,
                    _type: Literal["Video", "Audio"] = "Video") -> StudyResult:
        _session = self._session

        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        _info_url = f"https://mooc1.chaoxing.com/ananas/status/{_job['objectid']}?k={self.get_fid()}&flag=normal"
        _video_info = _session.get(_info_url, headers=headers).json()

        if _video_info["status"] != "success":
            logger.error(f"Unknown status: {_video_info['status']}")
            return StudyResult.ERROR

        _dtoken = _video_info["dtoken"]

        _crc = _video_info["crc"]
        _key = _video_info["key"]

        # Time in the real world: last_iter, gc.THRESHOLD
        # Time in the video (can be scaled with the speed factor): duration, play_time, last_log_time, wait_time

        duration = int(_video_info["duration"])
        play_time = int(_job["playTime"]) // 1000
        last_log_time = 0
        last_iter = time.time()
        wait_time = int(random.uniform(30, 90))

        limit_minutes = int(self.kwargs.get("daily_watch_limit_minutes", 0) or 0)
        username = str(self.kwargs.get("username") or getattr(getattr(self, "account", None), "username", "") or "default")
        from api.account_manager import AccountManager
        acct_mgr = AccountManager(auto_import_legacy=False)
        watched_today = 0.0
        if limit_minutes > 0:
            watched_today = acct_mgr.get_daily_watched_seconds(username)
            if watched_today >= limit_minutes * 60:
                logger.warning(
                    f"当前账号今日视频观看时长已达上限 ({int(watched_today // 60)}/{limit_minutes}分钟)，自动跳过视频: {_job['name']}"
                )
                return StudyResult.SUCCESS

        logger.info(f"开始任务: {_job['name']}, 总时长: {duration}s, 已进行: {play_time}s")

        forbidden_retry = 0
        max_forbidden_retry = 2

        passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration, duration,
                                                _type, headers=headers, _isdrag=4)
        if passed:
            logger.info("任务瞬间完成: {}", _job['name'])
            return StudyResult.SUCCESS

        pbar = None
        hub = TaskStateHub()
        try:
            while not passed:
                if hub.is_web_mode() and not hub.is_task_running():
                    logger.warning(f"检测到任务终止指令，中断视频播放: {_job['name']}")
                    return StudyResult.ERROR

                # Sometimes the last request needs to be sent several times to complete the task
                if play_time - last_log_time >= wait_time or play_time == duration:

                    passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration,
                                                            int(play_time), _type, headers=headers)

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

                            logger.debug("刷新后的令牌: {}, 持续时间: {}, 播放时间: {}", _dtoken, duration, play_time)
                            pbar = self._close_pbar_safe(pbar)
                            continue
                        else:
                            logger.error("会话恢复失败，刷新后的元数据缺少必要字段 (dtoken, duration)")
                            return StudyResult.ERROR

                    elif not passed and state != 200:
                        return StudyResult.ERROR

                    wait_time = int(random.uniform(30, 90))
                    last_log_time = play_time

                    logger.trace("Progress logged")

                current_speed = _speed
                if hub.is_web_mode():
                    t_name = threading.current_thread().name
                    current_speed = hub.get_effective_speed(t_name)
                    hub.update_worker_state(t_name, {
                        "chapter": f"{_course['title']} - {_job.get('name', '')}",
                        "position": int(play_time),
                        "duration": int(duration),
                        "speed": current_speed,
                        "status": "PLAYING",
                        "type": "video",
                    })

                dt = (time.time() - last_iter) * current_speed
                last_iter = time.time()
                play_time = min(duration, play_time + dt)

                if limit_minutes > 0:
                    acct_mgr.add_daily_watched_seconds(username, dt)
                    watched_today += dt
                    if watched_today >= limit_minutes * 60:
                        logger.warning(
                            f"当前账号今日视频观看时长达到设定上限 ({limit_minutes}分钟)，停止继续播放: {_job['name']}"
                        )
                        return StudyResult.SUCCESS

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
                        pbar = tqdm(total=duration, initial=int(play_time), desc=_job["name"],
                                    unit_scale=True, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}', leave=False)
                    pbar.n = int(play_time)
                    pbar.refresh()

                time.sleep(gc.THRESHOLD)
        finally:
            pbar = self._close_pbar_safe(pbar)
            hub = TaskStateHub()
            if hub.is_web_mode():
                hub.remove_worker(threading.current_thread().name)

        logger.info("任务完成: {}", _job['name'])
        return StudyResult.SUCCESS

    def study_document(self, _course, _job) -> StudyResult:
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

        Returns:
            requests.Response: Response object from the GET request

        Note:
            This method requires the following helper functions:
            - init_session(): To initialize a new session
            - get_timestamp(): To get current timestamp
            - re module for regular expression matching
        """
        _session = self._session
        _url = f"https://mooc1.chaoxing.com/ananas/job/document?jobid={_job['jobid']}&knowledgeid={re.findall(r'nodeId_(.*?)-', _job['otherinfo'])[0]}&courseid={_course['courseId']}&clazzid={_course['clazzId']}&jtoken={_job['jtoken']}&_dc={get_timestamp()}"
        _resp = _session.get(_url)
        if _resp.status_code != 200:
            return StudyResult.ERROR
        else:
            return StudyResult.SUCCESS

    def study_work(self, _course, _job, _job_info) -> StudyResult:
        if self.tiku.DISABLE or not self.tiku:
            return StudyResult.SUCCESS

        _session = self._session
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
            if TaskStateHub().is_web_mode() and not TaskStateHub().is_task_running():
                logger.warning("检测到任务终止指令，取消提交章节检测")
                return StudyResult.ERROR

            if not isinstance(answers, list):
                logger.error("题库 query_all 返回的数据格式异常，期望列表。将采用随机答案答题")
                answers = [None] * total_questions
            elif len(answers) != total_questions:
                logger.error(
                    f"题库返回的答案数量（{len(answers)}）与题目数量（{total_questions}）不匹配，正在补齐或截断以防错位！")
                answers = list(answers) + [None] * (total_questions - len(answers))
                answers = answers[:total_questions]

            for q, res in zip(questions["questions"], answers):
                logger.debug(f"当前题目信息 -> {q}")
                answer = ""
                if not res:
                    # 随机答题
                    answer = random_answer(q["options"], q["type"])
                    q[f'answerSource{q["id"]}'] = "random"
                else:
                    # 根据响应结果选择答案
                    if q["type"] == "multiple":
                        # 多选处理
                        options_list = multi_cut(q["options"], _ORIGIN_HTML_CONTENT)
                        res_list = multi_cut(res, _ORIGIN_HTML_CONTENT)
                        if res_list is not None and options_list is not None:
                            for _a in clean_res(res_list):
                                matched = False
                                for o in options_list:
                                    if (
                                            is_subsequence(_a, o)  # 去掉各种符号和前面ABCD的答案应当是选项的子序列
                                    ):
                                        answer += o[:1]
                                        matched = True
                                        break  # 找到匹配项后立即停止，防止重复添加
                                if not matched:
                                    best_letter = best_option_by_similarity(_a, options_list, threshold=0.8)
                                    if best_letter:
                                        answer += best_letter
                            # 对答案进行排序, 否则会提交失败
                            answer = "".join(sorted(set(answer)))
                        # else 如果分割失败那么就直接到下面去随机选
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
                            answer = "".join(res)
                        elif isinstance(res, str):
                            answer = res
                    else:
                        # 其他类型直接使用答案 （目前仅知有简答题，待补充处理）
                        answer = res

                    if not answer:  # 检查 answer 是否为空
                        logger.warning(f"找到答案但答案未能匹配 -> {res}\t随机选择答案")
                        answer = random_answer(q["options"], q["type"])  # 如果为空，则随机选择答案
                        q[f'answerSource{q["id"]}'] = "random"
                    else:
                        logger.info(f"成功获取到答案：{answer}")
                        q[f'answerSource{q["id"]}'] = "cover"
                        found_answers += 1
                # 填充答案
                q["answerField"][f'answer{q["id"]}'] = answer
                logger.info(f'{q["title"]} 填写答案为 {answer}')
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

            del questions["questions"]

            # 4. 提交
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
                    logger.info(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题成功 -> {res_json["msg"]}')
                else:
                    logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {res_json["msg"]}')
                    return StudyResult.ERROR
            else:
                logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {res.text}')
                return StudyResult.ERROR

            # 5. 若只是保存未提交，无法判断成绩，保持原有行为
            if questions["pyFlag"] == "1":
                return StudyResult.SUCCESS

            result_info = self._check_work_result(_session, _course, _job, _job_info, questions)
            if result_info is None:
                return StudyResult.SUCCESS

            score = float(result_info.get("score", 0.0) or 0.0)
            unknown = int(result_info.get("unknown", 0) or 0)
            if result_info.get("all_correct", False):
                logger.info(f"章节检测全部正确（成绩 {score} 分），通过！")
                TaskStateHub().increment_passed_tests()
                return StudyResult.SUCCESS
            if score >= 99.95:
                # 逐题比对存在格式差异或解析失配, 但满分成绩说明实际全对, 以分数为准
                if unknown > 0:
                    logger.warning(f"成绩 {score} 分达到满分, 以分数为准通过"
                                   f"（{unknown} 题答案字段未能解析, 建议人工复核）")
                else:
                    logger.info(f"逐题比对存在格式差异, 但成绩 {score} 分达到满分, 以分数为准, 通过！")
                TaskStateHub().increment_passed_tests()
                return StudyResult.SUCCESS
            if unknown > 0:
                # 解析失配且未达满分: 判定不可信, 不触发重做, 保留已提交成绩
                logger.warning(f"{unknown} 题答案字段解析失败且成绩 {score} 分未达满分, 跳过重做判定")
                return StudyResult.SUCCESS

            feedback_history = result_info.get("feedback", [])
            wrong_count = len(feedback_history)
            if attempt >= max_retries:
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
                        feedback = []
                        all_correct = True
                        unknown = 0
                        for q in detail:
                            if not q.get("parse_ok", True):
                                unknown += 1
                                all_correct = False
                                continue
                            my_ans = (q.get("my_answer") or "").strip()
                            correct_ans = (q.get("correct_answer") or "").strip()
                            if normalize_answer_text(my_ans) != normalize_answer_text(correct_ans):
                                all_correct = False
                                feedback.append(
                                    f"- 题目：{q.get('title', '')}\n"
                                    f"  题型：{q.get('type_label', '')}\n"
                                    f"  你的上次答案：{my_ans or '(空)'}\n"
                                    f"  正确答案：{correct_ans or '(空)'}"
                                )
                        m = re.search(r'本次成绩<i>([\d.]+)</i>分', html)
                        score = float(m.group(1)) if m else 0.0
                        return {
                            "all_correct": all_correct,
                            "feedback": feedback,
                            "score": score,
                            "times": 0,
                            "unknown": unknown,
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

        # 3. 逐题判断对错，收集错误反馈（解析失配的题跳过并计数, 避免误判全错）
        feedback = []
        all_correct = True
        unknown = 0
        for q in detail:
            if not q.get("parse_ok", True):
                unknown += 1
                all_correct = False
                continue
            my_ans = (q.get("my_answer") or "").strip()
            correct_ans = (q.get("correct_answer") or "").strip()
            if normalize_answer_text(my_ans) != normalize_answer_text(correct_ans):
                all_correct = False
                feedback.append(
                    f"- 题目：{q.get('title', '')}\n"
                    f"  题型：{q.get('type_label', '')}\n"
                    f"  你的上次答案：{my_ans or '(空)'}\n"
                    f"  正确答案：{correct_ans or '(空)'}"
                )

        logger.debug(f"章节检测成绩: {latest_score} 分, 全部正确: {all_correct}, 错题数: {len(feedback)}, 未解析题数: {unknown}")
        return {
            "all_correct": all_correct,
            "feedback": feedback,
            "score": latest_score,
            "times": latest_times,
            "unknown": unknown,
        }

    def study_read(self, _course, _job, _job_info) -> StudyResult:
        """
        阅读任务学习, 仅完成任务点, 并不增长时长
        """
        _session = self._session
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
        else:
            _resp_json = _resp.json()
            logger.info(f"阅读任务学习 -> {_resp_json['msg']}")
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
            session = self._session
            resp = session.get(
                "https://detect.chaoxing.com/api/monitor",
                params=params,
                headers={"Referer": referer_url},
                timeout=5,
            )
            logger.trace(f"Monitor heartbeat sent -> {resp.status_code}")
        except Exception as e:
            logger.trace(f"Monitor heartbeat failed (non-critical): {e}")

    def study_topic(self, _course: dict, _job: dict, _job_info: dict) -> StudyResult:
        """执行话题回复讨论任务点."""
        auto_reply = self.kwargs.get("topic_auto_reply", True)
        if str(auto_reply).strip().lower() in ("false", "0", "no", "off"):
            logger.info(f"已关闭话题自动回复，跳过话题讨论 -> {_job.get('title') or '话题讨论'}")
            return StudyResult.SUCCESS

        course_id = str(_course.get("courseId", ""))
        class_id = str(_course.get("clazzId", ""))
        cpi = str(_course.get("cpi", ""))
        topic_uuid = str(_job.get("topic_uuid") or _job.get("property", {}).get("uuid", "")).strip()
        bbsid = str(_job.get("bbsid") or _job.get("property", {}).get("bbsid", "")).strip()
        title = _job.get("title") or "话题讨论"
        job_id = str(_job.get("jobid", ""))
        mid = str(_job.get("mid") or _job.get("property", {}).get("mid", "")).strip()
        knowledge_id = str(_job_info.get("knowledgeid") or "")
        if not knowledge_id:
            m = re.findall(r"nodeId_(\d+)", str(_job.get("otherinfo", "")))
            if m:
                knowledge_id = m[0]

        session = self._session
        self.rate_limiter.limit_rate()

        reply_list_url = ""
        # 兼容 insertbbs 模块：卡片未直出 uuid 与 bbsid 时从讨论卡片页面动态解析真实标识
        if not topic_uuid or not bbsid:
            chapter_url = "https://mooc1.chaoxing.com/mooc-ans/bbscircle/chapter"
            chapter_params = {
                "mtopicid": mid,
                "jobid": job_id,
                "isPortal": "false",
                "knowledgeid": knowledge_id,
                "ut": "s",
                "clazzId": class_id,
                "courseid": course_id,
                "isJob": "false",
            }
            try:
                chapter_resp = session.get(chapter_url, params=chapter_params, timeout=10)
                if chapter_resp.status_code == 200:
                    if 'id="isFinished" value="true"' in chapter_resp.text:
                        logger.info(f"话题已回复完成 -> {title}")
                        return StudyResult.SUCCESS
                    data_match = re.search(
                        r'data=["\'](https://groupweb\.chaoxing\.com/course/topic/v3/bbs/([^/]+)/([^/]+)/replysList[^\"]*)["\']',
                        chapter_resp.text,
                    )
                    if data_match:
                        reply_list_url = data_match.group(1)
                        bbsid = data_match.group(2)
                        topic_uuid = data_match.group(3)
            except Exception as e:
                logger.debug(f"动态解析话题详情地址异常: {e}")

        if not reply_list_url and bbsid and topic_uuid:
            reply_list_url = f"https://groupweb.chaoxing.com/course/topic/v3/bbs/{bbsid}/{topic_uuid}/replysList"

        if not topic_uuid or not bbsid or not reply_list_url:
            logger.error(f"话题讨论参数解析失败，跳过 -> {title}")
            return StudyResult.ERROR

        params = {
            "courseId": course_id,
            "classId": class_id,
            "cpi": cpi,
            "isLearnSilver": 0,
            "ut": "s",
        }
        url_token = ""
        try:
            resp = session.get(reply_list_url, params=params, timeout=8)
            resp.encoding = "utf-8"
            if resp.status_code == 200:
                uid = str(session.cookies.get("UID") or session.cookies.get("_uid") or "")
                if uid and (f'creater_id="{uid}"' in resp.text or f'createrPuid":{uid}' in resp.text or f'createrPuid": "{uid}"' in resp.text):
                    logger.info(f"话题已回复过，直接标记完成 -> {title}")
                    return StudyResult.SUCCESS

                token_match = re.search(r'urlToken\s*[:=]\s*["\']([^"\']+)["\']', resp.text)
                if token_match:
                    url_token = token_match.group(1)
        except Exception as e:
            logger.debug(f"检查话题历史回复异常: {e}")

        reply_content = str(self.kwargs.get("topic_reply_content") or "").strip()
        if not reply_content:
            if self.tiku and hasattr(self.tiku, "generate_topic_reply"):
                try:
                    ans = self.tiku.generate_topic_reply(title, str(_job.get("content") or ""))
                    if ans and len(str(ans).strip()) >= 5:
                        reply_content = str(ans).strip()
                except Exception as e:
                    logger.debug(f"题库生成话题回复异常: {e}")

            if not reply_content:
                default_replies = [
                    "本章节内容观点明确，理论结合实际，对理解核心知识很有启发。",
                    "认真研读了本议题，分析透彻，逻辑清晰，加深了专业知识的掌握。",
                    "结合案例阐述到位，层次分明，对后续学习和实践具有指导意义。",
                    "通过本小节的学习与思考，进一步理清了知识脉络，收获很大。"
                ]
                reply_content = random.choice(default_replies)

        logger.info(f"正在发表话题回复 -> [{title}]: {reply_content}")

        submit_url = f"https://groupweb.chaoxing.com/pc/invitation/{topic_uuid}/addReplys"
        payload = {
            "courseId": course_id,
            "classId": class_id,
            "replyId": "-1",
            "uuid": str(uuid.uuid4()),
            "topic_content": reply_content,
            "files_url": "",
            "files_attr": "",
            "anonymous": "",
            "urlToken": url_token,
            "bbsid": bbsid,
        }
        headers = {
            "Referer": reply_list_url,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            post_resp = session.post(submit_url, data=payload, headers=headers, timeout=10)
            if post_resp.status_code == 405:
                logger.warning(f"话题已截止或关闭回复，标记完成 -> {title}")
                return StudyResult.SUCCESS
            if not post_resp.text or not post_resp.text.strip():
                logger.info(f"话题回复已提交 HTTP {post_resp.status_code} -> {title}")
                return StudyResult.SUCCESS if post_resp.status_code == 200 else StudyResult.ERROR
            try:
                res_data = post_resp.json()
            except Exception:
                if post_resp.status_code == 200 and ("成功" in post_resp.text or "success" in post_resp.text.lower()):
                    logger.info(f"话题回复成功 -> {title}")
                    return StudyResult.SUCCESS
                logger.error(f"话题回复响应解析异常: [{post_resp.status_code}] {post_resp.text[:100]}")
                return StudyResult.ERROR

            if res_data.get("status") is True or res_data.get("result") == 1:
                logger.info(f"话题回复成功 -> {title}")
                return StudyResult.SUCCESS
            msg = str(res_data.get("msg", "回复提交未通过"))
            if "最多回复" in msg or "已达到" in msg or "重复回复" in msg:
                logger.info(f"已达到该话题回复上限，视作完成 -> {title}")
                return StudyResult.SUCCESS
            logger.error(f"话题回复失败 -> [{msg}] {title}")
            return StudyResult.ERROR
        except Exception as e:
            logger.error(f"话题回复网络请求异常 -> {e}")
            return StudyResult.ERROR

    def study_vote(self, _course: dict, _job: dict, _job_info: dict) -> StudyResult:
        """执行随堂问答投票任务点."""
        course_id = str(_course.get("courseId", ""))
        class_id = str(_course.get("clazzId", ""))
        active_id = str(_job.get("active_id") or _job.get("property", {}).get("id", ""))
        job_id = str(_job.get("jobid", ""))
        jtoken = str(_job.get("jtoken", ""))
        knowledge_id = str(_job_info.get("knowledgeid") or "")
        if not knowledge_id:
            m = re.findall(r"nodeId_(\d+)", str(_job.get("otherinfo", "")))
            if m:
                knowledge_id = m[0]
        title = _job.get("title") or "随堂问答"

        session = self._session
        self.rate_limiter.limit_rate()

        submit_view_url = "https://mobilelearn.chaoxing.com/widget/chaptervote/goChapterSubmit"
        params = {
            "activeId": active_id,
            "quessequence": "1",
            "courseId": course_id,
            "isjob": "true",
            "ut": "s",
        }
        try:
            resp = session.get(submit_view_url, params=params, timeout=10)
            if resp.status_code != 200:
                logger.error(f"获取随堂问答页面失败 ({resp.status_code}) -> {title}")
                return StudyResult.ERROR

            match = re.search(
                r'var\s+questionlist\s*=\s*(\[\s*\{.*?\}\s*\]);\s*\n\s*var\s+questionhtml',
                resp.text,
                re.DOTALL,
            )
            if not match:
                logger.warning(f"随堂问答未解析到题目列表，可能已完成或无需答题 -> {title}")
                self._finish_vote_job(job_id, knowledge_id, course_id, class_id, jtoken)
                return StudyResult.SUCCESS

            js_code = match.group(1)
            q_list = eval(js_code, {"null": None, "true": True, "false": False, "__builtins__": None})
            if not q_list:
                logger.warning(f"随堂问答题目为空 -> {title}")
                self._finish_vote_job(job_id, knowledge_id, course_id, class_id, jtoken)
                return StudyResult.SUCCESS

            all_answered = all(bool(q.get("haveAnswer")) for q in q_list)
            if all_answered:
                logger.info(f"随堂问答之前已作答，直接完成 -> {title}")
                self._finish_vote_job(job_id, knowledge_id, course_id, class_id, jtoken)
                return StudyResult.SUCCESS

            uid = str(session.cookies.get("UID") or session.cookies.get("_uid") or "")
            payload = {
                "courseId": course_id,
                "classId": class_id,
                "activeId": active_id,
                "uid": uid,
                "fid": "",
            }
            for q in q_list:
                qid = str(q.get("id"))
                qtype = str(q.get("type", 0))
                payload["questionId"] = qid
                payload["questionType"] = qtype
                ans_options = q.get("answer") or []
                selected_ans = "A"
                if self.tiku and hasattr(self.tiku, "query"):
                    try:
                        tiku_ans = self.tiku.query(q.get("content", ""))
                        if tiku_ans:
                            for opt in ans_options:
                                if opt.get("content") and opt["content"] in tiku_ans:
                                    selected_ans = opt.get("name", "A")
                                    break
                    except Exception:
                        pass
                payload[f"answer{qid}"] = selected_ans

            submit_url = "https://mobilelearn.chaoxing.com/widget/pcvote/doQuestion"
            headers = {
                "Referer": resp.url,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            post_res = session.post(submit_url, data=payload, headers=headers, timeout=10)
            if post_res.status_code == 200:
                try:
                    res_json = post_res.json()
                except Exception:
                    res_json = {}
                if res_json.get("isresult") in (0, 1):
                    logger.info(f"随堂问答作答提交成功 -> {title}")
                    self._finish_vote_job(job_id, knowledge_id, course_id, class_id, jtoken)
                    return StudyResult.SUCCESS
                msg = str(res_json.get("msg", ""))
                if "重复" in msg or "已答" in msg or "已完成" in msg:
                    logger.info(f"随堂问答已作答过，标记完成 -> {title}")
                    self._finish_vote_job(job_id, knowledge_id, course_id, class_id, jtoken)
                    return StudyResult.SUCCESS

            logger.error(f"随堂问答提交未通过: {post_res.text[:100]} -> {title}")
            return StudyResult.ERROR
        except Exception as e:
            logger.error(f"随堂问答处理异常: {e}")
            return StudyResult.ERROR

    def _finish_vote_job(self, job_id: str, knowledge_id: str, course_id: str, class_id: str, jtoken: str) -> None:
        if not job_id:
            return
        try:
            url = f"https://mooc1.chaoxing.com/mooc-ans/job/vote?jobid={job_id}&knowledgeid={knowledge_id}&courseid={course_id}&clazzid={class_id}&jtoken={jtoken}"
            self._session.get(url, timeout=8)
        except Exception as e:
            logger.trace(f"投票完成标记通知异常: {e}")

    def study_emptypage(self, _course, point):
        _session = self._session
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
        _session = self._session
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
            session = self._session
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
        hub = TaskStateHub()
        while total < target_count:
            for point in points:
                if total >= target_count:
                    break
                if hub.is_web_mode() and not hub.is_task_running():
                    logger.warning("检测到任务终止指令，中断章节学习次数增加")
                    return StudyResult.ERROR
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
                self._extract_and_send_setlog(html_text)
                self._send_monitor_heartbeat(course, point)

                for _ in range(30):
                    if hub.is_web_mode() and not hub.is_task_running():
                        logger.warning("检测到任务终止指令，中断章节学习次数增加")
                        return StudyResult.ERROR
                    time.sleep(1)

                self._send_monitor_heartbeat(course, point)
                total += 1
                logger.info(f"章节学习次数进度: {total}/{target_count}")
        logger.info(f"章节学习次数增加完成, 共完成: {total} 次")
        return StudyResult.SUCCESS
