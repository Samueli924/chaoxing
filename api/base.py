# -*- coding: utf-8 -*-
import itertools
import random
import re
import secrets
import threading
import time
from enum import Enum
from hashlib import md5
from html import unescape as html_unescape
from typing import Any, Literal, Optional
from urllib.parse import urljoin

import requests
from loguru import logger
from requests import RequestException
from api.transport import CompatibleHTTPAdapter
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from tqdm import tqdm
from urllib3.util.retry import Retry

from api.answer import CacheDAO, Tiku
from api.answer_check import (
    comparable_answer,
    cut,
    judgement_value,
    match_choice,
    option_body,
    option_letter,
    split_options,
)
from api.cipher import AESCipher
from api.config import GlobalConst as gc
from api.cookies import apply_cookies, get_cookie, save_cookies, use_cookies
from api.decode import (
    decode_course_card,
    decode_course_folder,
    decode_course_list,
    decode_course_point,
    decode_questions_info,
    decode_work_record_list,
    decode_work_result,
)
from api.exceptions import LoginError
from api.runtime import interactive_lock, runtime

CARDS_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"
STUDENT_COURSE_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
STUDENT_STUDY_AJAX_URL = "https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax"
MEDIA_STATUS_URL = "https://mooc1.chaoxing.com/ananas/status/{objectid}"
DEFAULT_REPORT_URL = "https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/{cpi}"
# 当前网页使用 /mooc-ans/job/... 完成文档与阅读任务点，旧的 /ananas/job/... 作为兜底
DOCUMENT_URLS = (
    "https://mooc1.chaoxing.com/mooc-ans/job/document",
    "https://mooc1.chaoxing.com/ananas/job/document",
)
READ_URLS = (
    "https://mooc1.chaoxing.com/mooc-ans/job/readv2",
    "https://mooc1.chaoxing.com/ananas/job/readv2",
)
WORK_URL = "https://mooc1.chaoxing.com/mooc-ans/api/work"
WORK_SUBMIT_URL = "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew"
WORK_RECORD_LIST_URL = "https://mooc1.chaoxing.com/mooc-ans/work/record-list"
WORK_RECORD_DETAIL_URL = "https://mooc1.chaoxing.com/mooc-ans/work/record-detail"
# 已批阅页面"重做"按钮调用的接口，返回 {"status": true, "url": 新的作答页面}
WORK_RETEST_URL = "https://mooc1.chaoxing.com/mooc-ans/work/retest"

# 视频播放到结尾后，服务器仍未判定完成时最多再上报的次数，避免无限循环
MAX_END_REPORTS = 10
# 一个章节最多尝试的任务卡片标签页数量
MAX_CARD_TABS = 7


def get_timestamp():
    return str(int(time.time() * 1000))


class ChaoxingRequestError(Exception):
    """请求学习通接口失败（状态码异常或返回内容无法解析）."""


class WorkAlreadySubmitted(Exception):
    """章节检测已经提交且当前不可作答."""


class WorkRedoUnavailable(Exception):
    """章节检测不允许重做（老师未开放重做或次数已用完）."""


class _TimeoutSession(requests.Session):
    """未显式指定超时时间的请求使用默认超时，防止请求无限挂起."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", gc.REQUEST_TIMEOUT)
        return super().request(method, url, **kwargs)


def _build_session() -> requests.Session:
    session = _TimeoutSession()
    retries = Retry(
        total=5,
        connect=5,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
        raise_on_status=False,
    )
    adapter = CompatibleHTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=32)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(gc.HEADERS)
    apply_cookies(session, use_cookies())
    return session


def _json_or_none(resp: requests.Response) -> Optional[Any]:
    try:
        return resp.json()
    except ValueError:
        return None


def _is_login_page(resp: requests.Response) -> bool:
    if resp.status_code in (301, 302, 303, 307, 308):
        return "passport2.chaoxing.com" in resp.headers.get("Location", "")
    return "passport2.chaoxing.com/login" in (resp.url or "") or (
        bool(resp.history) and "passport2.chaoxing.com" in (resp.url or "")
    )


class SessionManager:
    """全局共享的请求会话（线程间复用连接与 cookie）."""

    _session: Optional[requests.Session] = None
    _lock = threading.Lock()
    _login_lock = threading.Lock()

    @classmethod
    def get_session(cls) -> requests.Session:
        session = cls._session
        if session is None:
            with cls._lock:
                if cls._session is None:
                    cls._session = _build_session()
                session = cls._session
        return session

    @classmethod
    def reset(cls) -> None:
        """丢弃当前会话（切换账号时使用）."""
        with cls._lock:
            if cls._session is not None:
                cls._session.close()
            cls._session = None

    @classmethod
    def update_cookies(cls) -> None:
        """从 cookies 文件重新加载 cookie 到共享会话."""
        apply_cookies(cls.get_session(), use_cookies())

    @classmethod
    def relogin_if_needed(cls, chaoxing_instance) -> bool:
        with cls._login_lock:
            if chaoxing_instance._validate_cookie_session():
                return True

            logger.info("登录状态已失效，正在尝试重新登录...")
            account = chaoxing_instance.account
            if account and account.username and account.password:
                login_result = chaoxing_instance.login(login_with_cookies=False)
                if login_result.get("status"):
                    logger.info("重新登录成功")
                    return True
                logger.warning(f"重新登录失败: {login_result.get('msg')}")
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
    SKIPPED = 4  # 主动跳过（如未配置题库时的章节检测），不视为失败
    CANCELLED = 5  # 用户停止运行

    def is_success(self):
        return self in (StudyResult.SUCCESS, StudyResult.SKIPPED)

    def is_failure(self):
        return not self.is_success()


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
    return res


def random_answer(options: str, q_type: str) -> str:
    answer = ""
    if not options and q_type != "judgement":
        return answer

    if q_type == "multiple":
        _op_list = multi_cut(options)
        logger.debug(f"当前选项列表 -> {_op_list}")
        if not _op_list:
            logger.error("选项为空, 未能正确提取题目选项信息! 请反馈并提供以上信息")
            return answer

        available_options = len(_op_list)
        if available_options <= 1:
            select_count = available_options
        else:
            max_possible = min(4, available_options)
            min_possible = min(2, available_options)
            weights_map = {
                2: [1.0],
                3: [0.3, 0.7],
                4: [0.1, 0.5, 0.4],
            }
            possible_counts = list(range(min_possible, max_possible + 1))
            weights = weights_map.get(max_possible, [0.3, 0.4, 0.3])[:len(possible_counts)]
            select_count = random.choices(possible_counts, weights=weights, k=1)[0]

        selected_options = random.sample(_op_list, select_count) if select_count > 0 else []
        answer = "".join(sorted(option[:1] for option in selected_options))
    elif q_type == "single":
        choices = split_options(options)
        if choices:
            answer = random.choice(choices)[:1]  # 取首字为答案, 例如A或B
    elif q_type == "judgement":
        answer = "true" if random.choice([True, False]) else "false"
    logger.info(f"随机选择 -> {answer}")
    return answer


def evaluate_work_detail(detail: list[dict]) -> Optional[dict]:
    """根据作答详情判断对错.

    优先使用页面上每道题的对错标记（marking_dui 对 / marking_cuo 错 / marking_bandui 部分正确），
    没有标记时再与公布的正确答案比对。两者都没有时无法判断对错，返回 None，
    调用方不应据此重做（否则会白白消耗重做次数）。
    """
    wrong = []
    known = 0
    for q in detail:
        flag = q.get("correct")
        if flag is None:
            correct = comparable_answer(q.get("correct_answer"), q.get("type_label", ""))
            if not correct:
                continue
            flag = comparable_answer(q.get("my_answer"), q.get("type_label", "")) == correct
        known += 1
        if not flag:
            wrong.append(q)
    if known == 0:
        return None
    return {"all_correct": not wrong, "wrong": wrong}


class Chaoxing:
    def __init__(self, account: Account = None, tiku: Tiku = None, **kwargs):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku
        self.kwargs = kwargs
        self.rate_limiter = RateLimiter(0.5)  # 其他接口速率限制比较松
        self.video_log_limiter = RateLimiter(2)  # 上报进度极其容易卡验证码，限制2s一次
        self._ocr = None
        self._ocr_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    def login(self, login_with_cookies=False):
        if login_with_cookies:
            logger.info("正在使用 cookies 登录...")
            SessionManager.update_cookies()
            if self._validate_cookie_session():
                self._log_current_user()
                return {"status": True, "msg": "登录成功"}
            if self.account and self.account.username and self.account.password:
                logger.warning("cookies 已失效，改用账号密码登录")
                return self._login_with_password()
            return {"status": False, "msg": "cookies 已失效，请重新登录或提供账号密码"}
        return self._login_with_password()

    def _login_with_password(self) -> dict:
        if not (self.account and self.account.username and self.account.password):
            return {"status": False, "msg": "未提供手机号或密码"}

        session = SessionManager.get_session()
        session.cookies.clear()
        # 与网页端一致：先打开登录页获取初始 cookie（失败不影响后续登录）
        try:
            session.get(gc.LOGIN_PAGE, timeout=10)
        except RequestException as e:
            logger.debug(f"打开登录页失败: {e}")

        # 字段与 https://passport2.chaoxing.com/login 页面 login.js 中 loginByPhoneAndPwdSubmit 保持一致
        data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(self.account.username),
            "password": self.cipher.encrypt(self.account.password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": "true",
            "forbidotherlogin": "0",
            "validate": "",
            "doubleFactorLogin": "0",
            "independentId": "0",
            "independentNameId": "0",
        }
        headers = {
            "Origin": "https://passport2.chaoxing.com",
            "Referer": gc.LOGIN_PAGE,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        logger.trace("正在尝试登录...")
        try:
            resp = session.post(gc.LOGIN_URL, data=data, headers=headers, timeout=20)
        except RequestException as e:
            return {"status": False, "msg": f"无法连接学习通登录服务器: {e}"}

        result = _json_or_none(resp)
        if not isinstance(result, dict):
            return {
                "status": False,
                "msg": f"登录接口返回了非预期的内容 (HTTP {resp.status_code})，可能触发了风控，请稍后重试或改用 cookies 登录",
            }

        if result.get("status"):
            if result.get("containTwoFactorLogin") and not self._validate_cookie_session():
                return {
                    "status": False,
                    "msg": "该账号开启了双因子登录验证，无法直接用密码登录。请在浏览器登录后复制 cookies 到 cookies.txt 并使用 cookies 登录",
                }
            save_cookies(session)
            self._log_current_user()
            return {"status": True, "msg": "登录成功"}

        if result.get("weakpwd"):
            return {
                "status": False,
                "msg": "学习通要求先修改密码（密码过于简单或已过期），请在浏览器登录 passport2.chaoxing.com 修改密码后再试",
            }
        msg = result.get("msg2") or result.get("mes") or result.get("msg") or "登录失败"
        if msg in ("密码错误", "用户名或密码错误"):
            msg = "手机号或密码错误"
        return {"status": False, "msg": str(msg)}

    def _log_current_user(self) -> None:
        logger.info("登录成功...")
        try:
            realname = self.get_name()
            if realname:
                logger.info(f"当前登录用户: {realname}")
        except Exception as e:
            logger.debug(f"获取当前登录用户名失败: {e}")

    @staticmethod
    def get_name() -> str:
        session = SessionManager.get_session()
        try:
            resp = session.get("https://passport2.chaoxing.com/mooc/accountManage", timeout=10)
            if resp.status_code == 200:
                match = re.search(r'id="messageName"\s+value="([^"]*)"', resp.text)
                if match:
                    return match.group(1).strip()
        except Exception as e:
            logger.debug(f"获取用户名失败: {e}")
        return ""

    def _validate_cookie_session(self) -> bool:
        session = SessionManager.get_session()
        if not (get_cookie(session, "_uid") or get_cookie(session, "UID")):
            return False
        try:
            # 未登录时该接口返回 302 跳转到 passport2 登录页
            resp = session.post(
                gc.COURSE_LIST_URL,
                data={"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0},
                allow_redirects=False,
                timeout=10,
            )
        except RequestException as exc:
            logger.debug("Cookie validation request failed: {}", exc)
            return False
        return resp.status_code == 200 and not _is_login_page(resp)

    def get_fid(self):
        return get_cookie(SessionManager.get_session(), "fid", 1024)

    def get_uid(self):
        session = SessionManager.get_session()
        uid = get_cookie(session, "_uid") or get_cookie(session, "UID")
        if uid:
            return uid
        raise LoginError("无法获取用户ID，请重新登录")

    def _get_with_relogin(self, url: str, **kwargs) -> requests.Response:
        """GET 请求，若登录状态失效则自动重新登录后重试一次."""
        session = SessionManager.get_session()
        resp = session.get(url, **kwargs)
        if _is_login_page(resp) and SessionManager.relogin_if_needed(self):
            resp = SessionManager.get_session().get(url, **kwargs)
        return resp

    @staticmethod
    def _ensure_page_ok(resp: requests.Response, what: str) -> None:
        if _is_login_page(resp):
            raise LoginError(f"读取{what}时发现登录状态已失效，请重新登录")
        if resp.status_code != 200:
            raise ChaoxingRequestError(f"读取{what}失败: HTTP {resp.status_code}")

    # ------------------------------------------------------------------
    # 课程、章节、任务点
    # ------------------------------------------------------------------
    def get_course_list(self):
        session = SessionManager.get_session()
        data = {"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0}
        headers = {
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
        }
        logger.trace("正在读取所有的课程列表...")
        resp = session.post(gc.COURSE_LIST_URL, headers=headers, data=data)
        self._ensure_page_ok(resp, "课程列表")
        course_list = decode_course_list(resp.text)

        try:
            interaction_resp = session.get(gc.INTERACTION_URL)
            course_folder = decode_course_folder(interaction_resp.text) if interaction_resp.status_code == 200 else []
        except RequestException as e:
            logger.warning(f"读取课程文件夹失败: {e}")
            course_folder = []
        for folder in course_folder:
            folder_data = dict(data, courseFolderId=folder["id"])
            try:
                resp = session.post(gc.COURSE_LIST_URL, headers=headers, data=folder_data)
            except RequestException as e:
                logger.warning(f"读取课程文件夹 {folder.get('rename', folder['id'])} 失败: {e}")
                continue
            if resp.status_code == 200:
                course_list += decode_course_list(resp.text)

        unique_courses = {}
        for course in course_list:
            unique_courses.setdefault((course["courseId"], course["clazzId"]), course)
        logger.info(f"课程列表读取完毕, 共 {len(unique_courses)} 门课程")
        return list(unique_courses.values())

    def get_course_point(self, _courseid, _clazzid, _cpi):
        params = {"courseid": _courseid, "clazzid": _clazzid, "cpi": _cpi, "ut": "s"}
        logger.trace("开始读取课程所有章节...")
        resp = self._get_with_relogin(STUDENT_COURSE_URL, params=params)
        self._ensure_page_ok(resp, "课程章节")
        logger.trace(f"原始章节列表内容:\n{resp.text}")
        course_point = decode_course_point(resp.text)
        logger.info(f"课程章节读取成功, 共 {len(course_point['points'])} 个章节")
        return course_point

    def iter_card_pages(self, course: dict, point: dict):
        """依次请求章节的任务卡片标签页（num=0,1,2...），逐页返回 (num, 页面HTML)."""
        cards_params = {
            "clazzid": course["clazzId"],
            "courseid": course["courseId"],
            "knowledgeid": point["id"],
            "ut": "s",
            "cpi": course["cpi"],
            "v": "2025-0424-1038-3",
            "mooc2": 1,
        }
        for possible_num in range(MAX_CARD_TABS):
            cards_params["num"] = possible_num
            resp = self._get_with_relogin(CARDS_URL, params=cards_params)
            if resp.status_code != 200 or _is_login_page(resp):
                raise ChaoxingRequestError(f"读取章节任务点失败: HTTP {resp.status_code}")
            logger.trace(f"原始任务点列表内容(num={possible_num}):\n{resp.text}")
            yield possible_num, resp.text

    def get_job_list(self, course: dict, point: dict) -> tuple[list[dict], dict]:
        self.rate_limiter.limit_rate()
        job_list: list[dict] = []
        job_info: dict = {}
        seen_jobs = set()

        # 章节的标签页数量无法直接得知，依次请求 num=0,1,2...；标签页是连续的，
        # 请求到不存在的标签页（页面中 mArg 未被填充）即可停止，不会漏掉任务点
        for possible_num, html in self.iter_card_pages(course, point):
            cards, card_info = decode_course_card(html)
            if card_info.get("notOpen", False):
                # 直接返回, 节省请求
                logger.info(f"章节未开放: {point['title']}")
                return [], card_info
            if card_info.get("noCard", False):
                break

            for job in cards:
                key = (job.get("type"), job.get("jobid"), job.get("objectid"))
                if key in seen_jobs:
                    continue
                seen_jobs.add(key)
                job_list.append(job)
            for key, value in card_info.items():
                if value not in ("", None) and not job_info.get(key):
                    job_info[key] = value

        if not job_list:
            self.study_emptypage(course, point)

        logger.info(f"章节任务点读取成功: {point['title']} (待完成 {len(job_list)} 个)")
        return job_list, job_info

    # ------------------------------------------------------------------
    # 视频 / 音频
    # ------------------------------------------------------------------
    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        # 与视频播放器 videojs-ext.min.js 中的 '[{0}][{1}][{2}][{3}][{4}][{5}][{6}][{7}]' 模板一致
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{playingTime * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]"
            .encode()).hexdigest()

    def _get_ocr(self):
        with self._ocr_lock:
            if self._ocr is None:
                from api.captcha import ocr_init
                self._ocr = ocr_init() or False
            return self._ocr or None

    def _try_pass_captcha(self, session: requests.Session, headers: dict) -> bool:
        logger.warning("检测到验证码拦截，正在尝试自动通过验证码...")
        try:
            from api.captcha import CxCaptcha
            cookies_str = "; ".join(f"{c.name}={c.value}" for c in session.cookies)
            ua = headers.get("User-Agent", gc.USER_AGENT)
            captcha_solver = CxCaptcha(user_agent=ua, cookies=cookies_str, ocr=self._get_ocr())
            for attempt in range(3):
                logger.info(f"第 {attempt + 1} 次尝试通过验证码...")
                if captcha_solver.try_pass():
                    logger.success("验证码通过成功！")
                    session.cookies.update(captcha_solver.s.cookies)
                    return True
                logger.warning("验证码验证失败，正在重试...")
                time.sleep(2)
            logger.error("多次验证码验证失败，请在浏览器中打开学习通手动完成一次验证后再运行。")
        except Exception as e:
            logger.error(f"验证码处理异常: {e}")
        return False

    @staticmethod
    def _looks_like_captcha(res: requests.Response) -> bool:
        if "antispider" in (res.url or "").lower():
            return True
        text = res.text[:5000]
        return "processVerify" in text or ("验证码" in text and "isPassed" not in text)

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
            _isdrag: int = 0,
            headers: Optional[dict] = None,
    ) -> tuple[bool, int]:
        if headers is None:
            headers = gc.VIDEO_HEADERS

        self.video_log_limiter.limit_rate(random_time=True, random_max=2)

        if "courseId" in _job["otherinfo"]:
            logger.error(_job["otherinfo"])
            raise RuntimeError("this is not possible")

        uid = self.get_uid()
        enc = self.get_enc(_course["clazzId"], _job["jobid"], _job["objectid"], _playingTime, _duration, uid)
        report_url = ((_job_info or {}).get("reportUrl") or DEFAULT_REPORT_URL.format(cpi=_course["cpi"])).rstrip("/")
        _url = f"{report_url}/{_dtoken}"

        def build_params(rt_val) -> dict:
            # 参数顺序与网页播放器一致
            params = {
                "clazzId": _course["clazzId"],
                "playingTime": _playingTime,
                "duration": _duration,
                "clipTime": f"0_{_duration}",
                "objectId": _job["objectid"],
                "otherInfo": _job["otherinfo"],
                "courseId": _course["courseId"],
                "jobid": _job["jobid"],
                "userid": uid,
                "isdrag": _isdrag,
                "view": "pc",
                "enc": enc,
                "rt": rt_val,
            }
            if _job.get("videoFaceCaptureEnc"):
                params["videoFaceCaptureEnc"] = _job["videoFaceCaptureEnc"]
            params["dtype"] = _type
            params["_t"] = get_timestamp()
            if _job.get("attDuration"):
                params["attDuration"] = _job["attDuration"]
            if _job.get("attDurationEnc"):
                params["attDurationEnc"] = _job["attDurationEnc"]
            params["courseEngineInfo"] = "false"
            return params

        def perform_request(rt_val):
            res = _session.get(_url, params=build_params(rt_val), headers=headers)
            if self._looks_like_captcha(res) and self._try_pass_captcha(_session, headers):
                res = _session.get(_url, params=build_params(rt_val), headers=headers)
            return res

        def parse_passed(resp) -> Optional[bool]:
            data = _json_or_none(resp)
            if isinstance(data, dict) and "isPassed" in data:
                return bool(data["isPassed"])
            return None

        rt = _job.get('rt')
        if not rt:
            rt_search = re.search(r"-rt_([1d])", _job['otherinfo'])
            if rt_search:
                rt = "0.9" if rt_search.group(1) == "d" else "1"
                logger.trace(f"Got rt from otherinfo: {rt}")

        if rt:
            _job['rt'] = rt
            resp = perform_request(rt)
        else:
            logger.debug("未获取到 rt 参数, 依次尝试 0.9 与 1")
            resp = None
            for rt_candidate in ("0.9", "1"):
                resp = perform_request(rt_candidate)
                if resp.status_code == 200:
                    _job['rt'] = rt_candidate
                    break
                if resp.status_code != 403:
                    break
                logger.debug("rt={} 返回403, 尝试切换rt", rt_candidate)

        if resp.status_code == 200:
            logger.trace(resp.text)
            passed = parse_passed(resp)
            if passed is None:
                logger.warning(f"视频进度上报返回了非预期内容: {resp.text[:200]}")
                return False, -1
            return passed, 200

        if resp.status_code == 403:
            logger.debug("视频进度上报返回403, jobid={}, 摘要={}", _job.get("jobid"), resp.text[:200])
            return False, 403

        logger.error("视频进度上报失败: HTTP {} jobid={} url={}", resp.status_code, _job.get("jobid"), resp.url)
        return False, resp.status_code

    def _fetch_media_status(self, session: requests.Session, job: dict, headers: dict) -> Optional[dict]:
        info_url = MEDIA_STATUS_URL.format(objectid=job['objectid'])
        params = {"k": self.get_fid(), "flag": "normal", "ro": "0"}
        try:
            resp = session.get(info_url, params=params, headers=headers)
        except RequestException as exc:
            logger.warning("获取视频信息失败: {}", exc)
            return None
        if resp.status_code != 200:
            logger.warning("获取视频信息返回码异常: {}", resp.status_code)
            logger.debug(resp.text[:300])
            return None
        data = _json_or_none(resp)
        if not isinstance(data, dict):
            logger.warning("解析视频信息失败: {}", resp.text[:200])
            return None
        return data

    def _refresh_video_status(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]) \
            -> Optional[dict]:
        self.rate_limiter.limit_rate(random_time=True, random_max=0.2)
        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        data = self._fetch_media_status(session, job, headers)
        if data and data.get("status") == "success":
            return data
        return None

    def _recover_after_forbidden(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]):
        refreshed = self._refresh_video_status(session, job, _type)
        if refreshed:
            return refreshed

        if SessionManager.relogin_if_needed(self):
            return self._refresh_video_status(SessionManager.get_session(), job, _type)

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
        _session = SessionManager.get_session()
        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        job_name = _job.get("name") or _job.get("objectid", "")

        _video_info = self._fetch_media_status(_session, _job, headers)
        if not _video_info:
            return StudyResult.ERROR
        if _video_info.get("status") != "success":
            logger.error(f"获取媒体信息失败 ({job_name}): status={_video_info.get('status')}")
            return StudyResult.ERROR

        _dtoken = _video_info.get("dtoken")
        try:
            duration = int(float(_video_info.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0
        if not _dtoken or duration <= 0:
            logger.error(f"媒体信息缺少 dtoken 或时长 ({job_name})")
            return StudyResult.ERROR

        # 现实时间: last_iter, gc.THRESHOLD
        # 视频时间(随倍速缩放): duration, play_time, last_log_time, wait_time
        play_time = min(duration, int(_job.get("playTime") or 0) // 1000)
        # A last position at the end is not proof of the required watched duration.
        # The browser replays unfinished media; do not repeatedly claim its end.
        if play_time >= duration:
            play_time = 0
        last_log_time = play_time
        last_iter = time.monotonic()
        wait_time = 30

        logger.info(f"开始任务: {job_name}, 总时长: {duration}s, 已进行: {play_time}s")

        forbidden_retry = 0
        max_forbidden_retry = 2
        end_reports = 0
        progress_key = f"{_course.get('courseId')}-{_job.get('jobid')}"

        passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration, play_time,
                                                _type, headers=headers, _isdrag=3)
        if passed:
            logger.info("服务器确认任务已完成: {}", job_name)
            return StudyResult.SUCCESS
        if state != 200:
            return StudyResult.FORBIDDEN if state == 403 else StudyResult.ERROR

        pbar = None
        try:
            while not passed:
                if runtime.should_stop():
                    return StudyResult.CANCELLED

                # 播放到结尾后有时需要多次上报才会被判定完成
                if play_time - last_log_time >= wait_time or play_time >= duration:
                    if play_time >= duration:
                        end_reports += 1
                        if end_reports > MAX_END_REPORTS:
                            logger.error(f"视频已播放到结尾但服务器始终未判定完成, 稍后重试: {job_name}")
                            return StudyResult.ERROR

                    passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration,
                                                            int(play_time), _type, headers=headers,
                                                            _isdrag=4 if play_time >= duration else 0)

                    if state == 403:
                        if forbidden_retry >= max_forbidden_retry:
                            logger.warning("403重试失败, 跳过当前任务")
                            return StudyResult.FORBIDDEN
                        forbidden_retry += 1
                        logger.warning("出现403报错, 正在尝试刷新会话状态 (第{}次)", forbidden_retry)
                        runtime.sleep(random.uniform(2, 4))
                        _session = SessionManager.get_session()
                        refreshed_meta = self._recover_after_forbidden(_session, _job, _type)
                        if refreshed_meta and refreshed_meta.get("dtoken") and refreshed_meta.get("duration"):
                            _dtoken = refreshed_meta["dtoken"]
                            duration = int(float(refreshed_meta["duration"]))
                            logger.debug("刷新后的令牌: {}, 持续时间: {}, 播放时间: {}", _dtoken, duration, play_time)
                            pbar = self._close_pbar_safe(pbar)
                            continue
                        logger.error("会话恢复失败，刷新后的元数据缺少必要字段 (dtoken, duration)")
                        return StudyResult.ERROR

                    if not passed and state != 200:
                        return StudyResult.ERROR

                    wait_time = 30
                    last_log_time = play_time
                    logger.trace("Progress logged")

                # 上报进度需要时间, 假设视频在后台持续播放, 手动计算经过的时间
                now = time.monotonic()
                play_time = min(duration, play_time + (now - last_iter) * _speed)
                last_iter = now

                runtime.update_item(progress_key, job_name, play_time, duration, kind=_type.lower())
                if interactive_lock.locked():
                    pbar = self._close_pbar_safe(pbar)
                else:
                    if pbar is None:
                        pbar = tqdm(total=duration, initial=int(play_time), desc=job_name,
                                    unit_scale=True, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}', leave=False)
                    pbar.n = int(play_time)
                    pbar.refresh()

                runtime.sleep(gc.THRESHOLD)
        finally:
            runtime.remove_item(progress_key)
            self._close_pbar_safe(pbar)

        logger.info("任务完成: {}", job_name)
        return StudyResult.SUCCESS

    # ------------------------------------------------------------------
    # 文档 / 阅读
    # ------------------------------------------------------------------
    @staticmethod
    def _node_id(job: dict) -> str:
        match = re.search(r"nodeId_(\d+)", job.get("otherinfo", "") or "")
        return match.group(1) if match else ""

    def _finish_job_via(self, urls, params: dict, what: str) -> StudyResult:
        session = SessionManager.get_session()
        for url in urls:
            try:
                resp = session.get(url, params=params)
            except RequestException as e:
                logger.warning(f"{what}请求失败: {e}")
                continue
            data = _json_or_none(resp)
            if not isinstance(data, dict):
                logger.debug(f"{what}接口 {url} 返回非JSON内容 (HTTP {resp.status_code}), 尝试备用接口")
                continue
            if data.get("status"):
                logger.info(f"{what}完成 -> {data.get('msg', '')}")
                return StudyResult.SUCCESS
            logger.error(f"{what}失败 -> {data.get('msg', data)}")
            return StudyResult.ERROR
        return StudyResult.ERROR

    def study_document(self, _course, _job, _job_info=None) -> StudyResult:
        """完成文档任务点（与网页 documentJob.js 中的 finishJob 请求一致）."""
        job_info = _job_info or {}
        params = {
            "jobid": _job["jobid"],
            "knowledgeid": job_info.get("knowledgeid") or self._node_id(_job),
            "courseid": _course["courseId"],
            "clazzid": _course["clazzId"],
            "jtoken": _job.get("jtoken", ""),
        }
        if _job.get("microTopicId"):
            params["checkMicroTopic"] = "true"
            params["microTopicId"] = _job["microTopicId"]
        params["courseEngineInfo"] = "false"
        params["_dc"] = get_timestamp()
        return self._finish_job_via(DOCUMENT_URLS, params, "文档任务")

    def study_read(self, _course, _job, _job_info) -> StudyResult:
        """
        阅读任务学习, 仅完成任务点, 并不增长时长
        """
        params = {
            "jobid": _job["jobid"],
            "knowledgeid": (_job_info or {}).get("knowledgeid") or self._node_id(_job),
            "jtoken": _job.get("jtoken", ""),
            "courseid": _course["courseId"],
            "clazzid": _course["clazzId"],
        }
        return self._finish_job_via(READ_URLS, params, "阅读任务")

    # ------------------------------------------------------------------
    # 章节检测
    # ------------------------------------------------------------------
    def _work_max_retries(self) -> int:
        try:
            return max(0, int(self.kwargs.get("work_max_retries", 3)))
        except (TypeError, ValueError):
            return 3

    @staticmethod
    def _work_params(_course, _job, _job_info) -> dict:
        """构造章节检测页面参数（与网页 ananas/modules/work/index.html 一致）."""
        work_id = _job["jobid"].replace("work-", "")
        if _job.get("schoolid") and _job.get("workid"):
            work_id = f"{_job['schoolid']}-{_job['workid']}"
        params = {
            "api": "1",
            "workId": work_id,
            "jobid": _job["jobid"],
            "originJobId": _job["jobid"],
            "needRedirect": "true",
            "skipHeader": "true",
            "knowledgeid": str(_job_info.get("knowledgeid", "") or ""),
            "ktoken": _job_info.get("ktoken", "") or "",
            "cpi": _job_info.get("cpi", "") or _course.get("cpi", ""),
            "ut": "s",
            "clazzId": _course["clazzId"],
            "type": "b" if _job.get("worktype") == "workB" else "",
            "enc": _job.get("enc", ""),
        }
        if _job.get("workExtInfoEnc") and _job.get("oriNodeId"):
            params["workExtInfoEnc"] = _job["workExtInfoEnc"]
            params["oriNodeId"] = _job["oriNodeId"]
        params["mooc2"] = "1"
        params["courseid"] = _course["courseId"]
        return params

    @staticmethod
    def _looks_submitted(html: str) -> bool:
        return (("我的答案" in html and ("正确答案" in html or "marking_" in html))
                or "待批阅" in html or "本次成绩" in html)

    def _fetch_work(self, session, _course, _job, _job_info):
        params = self._work_params(_course, _job, _job_info)

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
            retry=retry_if_exception_type((ChaoxingRequestError, RequestException)),
            reraise=True,
        )
        def fetch():
            resp = session.get(WORK_URL, params=params)
            text = resp.text
            # 未创建完成该测验则不进行答题，目前遇到的情况是未创建完成等同于没题目
            if "教师未创建完成该测验" in text:
                raise PermissionError("教师未创建完成该测验")
            if resp.status_code != 200:
                raise ChaoxingRequestError(f"HTTP {resp.status_code}")
            questions = decode_questions_info(text)
            if questions.get("questions"):
                return resp, questions
            if self._looks_submitted(text):
                raise WorkAlreadySubmitted("章节检测已提交，当前不可作答（可能正在等待批阅）")
            raise ChaoxingRequestError("未能从页面中解析出题目")

        return fetch()

    def _open_redo(self, session, _course, _job, _job_info):
        """与网页"重做"按钮一致：先打开已批阅页面取参数，再调用 /work/retest，返回 (作答页面, 题目信息)."""
        graded = session.get(WORK_URL, params=self._work_params(_course, _job, _job_info))
        inputs = decode_work_result(graded.text)["inputs"]
        params = {
            "courseId": inputs.get("courseId") or _course["courseId"],
            "classId": inputs.get("classId") or _course["clazzId"],
            "workId": inputs.get("workId", ""),
            "workAnswerId": inputs.get("workAnswerId", ""),
            "knowledgeid": inputs.get("knowledgeid") or str(_job_info.get("knowledgeid", "") or ""),
            "jobid": inputs.get("jobid") or _job["jobid"],
            "originJobId": inputs.get("originJobId") or _job["jobid"],
            "enc": inputs.get("enc") or _job.get("enc", ""),
            "cpi": inputs.get("cpi") or _course.get("cpi", ""),
            "mooc2": 1,
            "wMicroNodeId": "0",
        }
        resp = session.get(WORK_RETEST_URL, params=params, headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": graded.url,
        })
        data = _json_or_none(resp)
        if not isinstance(data, dict) or not data.get("status"):
            reason = (data.get("msg") if isinstance(data, dict) else "") or f"HTTP {resp.status_code}"
            raise WorkRedoUnavailable(reason)
        if data.get("url"):
            page = session.get(urljoin(resp.url, str(data["url"])))
            questions = decode_questions_info(page.text)
            if questions.get("questions"):
                return page, questions
        # 没有返回地址或地址中解析不出题目时，重新打开题目页（此时应为可作答状态）
        return self._fetch_work(session, _course, _job, _job_info)

    @staticmethod
    def _bodies_for_letters(options: list[str], letters: str) -> list[str]:
        return [option_body(o) for o in options if option_letter(o) and option_letter(o) in letters]

    def _resolve_answer(self, q: dict, res) -> tuple[str, str, Any]:
        """把题库答案转换为表单值.

        Returns:
            (表单值, 来源 cover/random, 可在重做时复用的答案[选项正文列表/布尔值/文本])
        """
        q_type = q["type"]
        options = split_options(q.get("options"))
        if res:
            if q_type in ("single", "multiple"):
                letters = match_choice(res, options, multiple=(q_type == "multiple"))
                if letters:
                    return letters, "cover", self._bodies_for_letters(options, letters)
            elif q_type == "judgement":
                value = self.tiku.judgement_select(res)
                return ("true" if value else "false"), "cover", value
            else:
                text = "".join(res) if isinstance(res, list) else str(res)
                if text.strip():
                    return text, "cover", text
            logger.warning(f"找到答案但未能匹配选项 -> {res}\t随机选择答案")
            logger.debug(f"题目选项: {options}")
        answer = random_answer(q.get("options") or "", q_type)
        if q_type in ("single", "multiple"):
            resolved = self._bodies_for_letters(options, answer) if answer else None
        elif q_type == "judgement":
            resolved = (answer == "true") if answer else None
        else:
            resolved = answer or None
        return answer, "random", resolved

    @staticmethod
    def _render_known(q: dict, known) -> str:
        """把跨轮次保存的答案重新渲染为当前题目的表单值（选项顺序可能变化）."""
        q_type = q["type"]
        if q_type in ("single", "multiple") and isinstance(known, list):
            options = split_options(q.get("options"))
            letters = []
            for body in known:
                letter = match_choice(body, options, multiple=False)
                if letter and letter not in letters:
                    letters.append(letter)
            return "".join(sorted(letters)) if q_type == "multiple" else (letters[0] if letters else "")
        if q_type == "judgement" and isinstance(known, bool):
            return "true" if known else "false"
        return known if isinstance(known, str) else ""

    @staticmethod
    def _same_answer(a, b) -> bool:
        if isinstance(a, list) and isinstance(b, list):
            return frozenset(a) == frozenset(b)
        return a == b

    def _alternative_answer(self, q: dict, tried: list, superset_of: Optional[frozenset] = None) -> tuple[str, Any]:
        """答错且不知道正确答案时换一个还没试过的答案：判断题取反、单选逐个排除、多选依次尝试各组合.

        Args:
            q: 当前轮次的题目
            tried: 已判定为错误的答案（选项正文列表 / 布尔值）
            superset_of: 多选题上次"部分正确"时所选的选项，正确答案一定包含它们

        Returns:
            (表单值, 可复用的答案)；没有可尝试的答案时为 ("", None)
        """
        q_type = q["type"]
        if q_type == "judgement":
            for value in (True, False):
                if not any(self._same_answer(value, t) for t in tried):
                    return ("true" if value else "false"), value
            return "", None
        options = split_options(q.get("options"))
        bodies = [option_body(o) for o in options if option_letter(o)]
        if q_type == "single":
            for body in bodies:
                if not any(self._same_answer([body], t) for t in tried):
                    return self._render_known(q, [body]), [body]
            return "", None
        if q_type == "multiple":
            tried_sets = {frozenset(t) for t in tried if isinstance(t, list)}
            # 多选题正确答案至少两项，从选项多的组合开始尝试
            for size in range(len(bodies), 1, -1):
                for combo in itertools.combinations(bodies, size):
                    candidate = frozenset(combo)
                    if candidate in tried_sets or (superset_of and not superset_of < candidate):
                        continue
                    return self._render_known(q, list(combo)), list(combo)
        return "", None

    def _known_from_record(self, q: dict, correct_answer: str):
        """把作答记录中的正确答案（通常为选项字母）转换为可复用的答案."""
        q_type = q["type"]
        if q_type in ("single", "multiple"):
            options = split_options(q.get("options"))
            letters = match_choice(correct_answer, options, multiple=(q_type == "multiple"))
            return self._bodies_for_letters(options, letters) if letters else None
        if q_type == "judgement":
            return judgement_value(correct_answer, self.tiku.true_list, self.tiku.false_list)
        return correct_answer or None

    @staticmethod
    def _known_as_text(known) -> str:
        if isinstance(known, list):
            return "\n".join(known)
        if isinstance(known, bool):
            return "正确" if known else "错误"
        return str(known)

    def study_work(self, _course, _job, _job_info) -> StudyResult:
        if not self.tiku or self.tiku.DISABLE:
            logger.info("未配置可用的题库, 跳过章节检测")
            return StudyResult.SKIPPED
        try:
            return self._study_work(_course, _job, _job_info)
        finally:
            # 错误反馈只对本次章节检测有效，避免影响后续其它章节的答题与缓存
            self.tiku.set_work_feedback(None)

    def _study_work(self, _course, _job, _job_info) -> StudyResult:
        session = SessionManager.get_session()
        max_redo = self._work_max_retries()
        query_delay = self.kwargs.get("query_delay", 0) or 0
        work_name = _job.get("name") or _job.get("jobid", "")

        known: dict[str, Any] = {}  # 题目ID -> 已确认正确的答案（重做时直接使用）
        tried: dict[str, list] = {}  # 题目ID -> 已确认错误的答案（重做时换一个）
        superset_hint: dict[str, frozenset] = {}  # 多选题部分正确时所选的选项
        wrong_ids: set[str] = set()
        feedback: list[str] = []
        submitted = False
        next_page = None  # 重做时由 /work/retest 打开的作答页面

        for attempt in range(max_redo + 1):
            if attempt > 0:
                logger.warning(f"章节检测重做第 {attempt}/{max_redo} 轮: {work_name}")
                runtime.sleep(2)

            # 1. 获取题目
            try:
                if next_page is not None:
                    final_resp, questions = next_page
                    next_page = None
                else:
                    final_resp, questions = self._fetch_work(session, _course, _job, _job_info)
            except PermissionError as e:
                logger.warning(f"跳过章节检测: {e}")
                return StudyResult.SKIPPED
            except WorkAlreadySubmitted as e:
                if submitted:
                    logger.info("章节检测已提交且不允许再次作答，结束重做")
                    return StudyResult.SUCCESS
                logger.warning(f"跳过章节检测: {e}")
                return StudyResult.SKIPPED
            except Exception as e:
                logger.error(f"获取章节检测题目失败: {e}")
                return StudyResult.SUCCESS if submitted else StudyResult.ERROR

            q_list = questions["questions"]
            total_questions = len(q_list)

            # 2. 搜题：首轮查询全部题目；重做时只有能参考错误反馈的题库（大模型）才重新查询答错的题目，
            #    普通题库再查一次只会得到同样的答案，直接排除已答错的选项
            if attempt == 0:
                to_query = q_list
            elif getattr(self.tiku, "supports_feedback", False):
                to_query = [q for q in q_list if q["id"] in wrong_ids and q["id"] not in known]
                if feedback:
                    self.tiku.set_work_feedback(feedback)
            else:
                to_query = []

            raw_answers: dict[str, Any] = {}
            if to_query:
                results = self.tiku.query_all(to_query, query_delay=query_delay)
                if not isinstance(results, list):
                    logger.error("题库 query_all 返回的数据格式异常，期望列表。将采用随机答案答题")
                    results = []
                if len(results) != len(to_query):
                    logger.error(f"题库返回的答案数量（{len(results)}）与题目数量（{len(to_query)}）不匹配，已补齐或截断以防错位")
                    results = (list(results) + [None] * len(to_query))[:len(to_query)]
                raw_answers = {q["id"]: r for q, r in zip(to_query, results)}

            # 3. 生成答案
            found_answers = 0
            sources: dict[str, str] = {}
            resolved: dict[str, Any] = {}
            for q in q_list:
                qid = q["id"]
                logger.debug(f"当前题目信息 -> {q}")
                answer = ""
                if qid in known:
                    answer = self._render_known(q, known[qid])
                    if answer:
                        sources[qid], resolved[qid] = "cover", known[qid]
                if not answer:
                    answer, sources[qid], resolved[qid] = self._resolve_answer(q, raw_answers.get(qid))
                    # 重做时避免再次提交已判定为错误的答案
                    if qid in tried and any(self._same_answer(resolved[qid], t) for t in tried[qid]):
                        alt_answer, alt_resolved = self._alternative_answer(q, tried[qid], superset_hint.get(qid))
                        if alt_answer:
                            logger.info(f"排除已答错的选项后改为: {alt_answer}")
                            answer, sources[qid], resolved[qid] = alt_answer, "retry", alt_resolved
                if sources[qid] == "cover":
                    found_answers += 1
                    logger.info(f"成功获取到答案：{answer}")
                q["answerField"][f'answer{qid}'] = answer
                logger.info(f'{q["title"]} 填写答案为 {answer}')

            cover_rate = (found_answers / total_questions) * 100 if total_questions else 0
            logger.info(f"章节检测题库覆盖率： {cover_rate:.0f}%")

            # 4. 决定提交还是只保存（pyFlag 留空为提交, 1 为保存）
            is_manual_mode = getattr(self.tiku, '_is_manual_mode', False)
            if not self.tiku.SUBMIT:
                py_flag = "1"
            elif is_manual_mode or cover_rate >= self.tiku.COVER_RATE * 100 or attempt > 0:
                py_flag = ""
            elif _course.get("hasLocked"):
                logger.warning(
                    f"题库覆盖率 {cover_rate:.0f}% 低于 {self.tiku.COVER_RATE * 100:.0f}%，"
                    f"但该课程需要完成章节检测才能解锁后续章节，仍然提交")
                py_flag = ""
            else:
                py_flag = "1"
                logger.info(f"章节检测题库覆盖率低于{self.tiku.COVER_RATE * 100:.0f}%，不予提交"
                            f"（如需先提交再根据批改结果重做，可将题库配置 cover_rate 设为 0）")

            form = {k: v for k, v in questions.items() if k != "questions"}
            form["pyFlag"] = py_flag
            for q in q_list:
                qid = q["id"]
                value = q["answerField"][f'answer{qid}']
                if py_flag == "1" and sources.get(qid) != "cover":
                    value = ''  # 只保存搜到的答案，随机答案不保存
                form[f'answer{qid}'] = value
                form[f'answertype{qid}'] = q["answerField"][f'answertype{qid}']

            # 5. 提交/保存
            action = "提交" if py_flag == "" else "保存"
            try:
                res = session.post(
                    WORK_SUBMIT_URL,
                    data=form,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Origin": "https://mooc1.chaoxing.com",
                        "Referer": final_resp.url,
                        "Sec-Fetch-Site": "same-origin",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Dest": "empty",
                    },
                )
            except RequestException as e:
                logger.error(f"{action}答题失败 -> {e}")
                return StudyResult.SUCCESS if submitted else StudyResult.ERROR
            res_json = _json_or_none(res)
            if res.status_code != 200 or not isinstance(res_json, dict):
                logger.error(f'{action}答题失败 -> HTTP {res.status_code} {res.text[:200]}')
                return StudyResult.SUCCESS if submitted else StudyResult.ERROR
            if not res_json.get("status"):
                logger.error(f'{action}答题失败 -> {res_json.get("msg")}')
                return StudyResult.SUCCESS if submitted else StudyResult.ERROR
            logger.info(f'{action}答题成功 -> {res_json.get("msg", "")}')

            if py_flag == "1":
                return StudyResult.SUCCESS
            submitted = True

            # 6. 检查成绩：全对则结束；答错时仅在能改进答案且还有重做次数时重做
            result_info = self._check_work_result(session, _course, _job, _job_info, form)
            if result_info is None:
                return StudyResult.SUCCESS
            score = result_info.get("score")
            if result_info["all_correct"]:
                logger.info(f"章节检测全部正确（成绩 {score if score is not None else '?'} 分）: {work_name}")
                return StudyResult.SUCCESS

            questions_by_id = {q["id"]: q for q in q_list}
            wrong_ids = set()
            feedback = []
            cache = CacheDAO()
            for item in result_info["wrong"]:
                qid = item["id"]
                q = questions_by_id.get(qid)
                if not q:
                    continue
                wrong_ids.add(qid)
                cache_key = Tiku.clean_title(q["title"])
                correct = self._known_from_record(q, item.get("correct_answer", "")) if item.get("correct_answer") else None
                if correct not in (None, "", []):
                    known[qid] = correct
                    cache.add_cache(cache_key, self._known_as_text(correct))
                else:
                    known.pop(qid, None)
                    cache.remove_cache(cache_key)  # 不再使用已知错误的缓存答案
                    if resolved.get(qid) not in (None, "", []):
                        tried.setdefault(qid, []).append(resolved[qid])
                        if item.get("partial") and isinstance(resolved[qid], list):
                            superset_hint[qid] = frozenset(resolved[qid])
                my_text = self._known_as_text(resolved.get(qid)) if resolved.get(qid) is not None else item.get("my_answer", "")
                feedback.append(
                    f"- 题目：{item.get('title') or q['title']}\n"
                    f"  题型：{item.get('type_label', '')}\n"
                    f"  你的上次答案：{my_text or '(空)'}\n"
                    f"  正确答案：{self._known_as_text(correct) if correct not in (None, '', []) else '(未公布)'}"
                )
            # 答对的题目下一轮沿用本轮答案
            for qid, value in resolved.items():
                if qid not in wrong_ids and value is not None:
                    known.setdefault(qid, value)

            improvable = [
                qid for qid in wrong_ids
                if qid in known or getattr(self.tiku, "supports_feedback", False)
                or questions_by_id[qid]["type"] in ("single", "multiple", "judgement")
            ]
            if attempt >= max_redo or not improvable:
                reason = "已达到重做次数上限" if attempt >= max_redo else "当前题库无法改进答案"
                logger.warning(f"章节检测有 {len(wrong_ids)}/{total_questions} 题回答错误"
                               f"（成绩 {score if score is not None else '?'} 分），{reason}，不再重做: {work_name}")
                return StudyResult.SUCCESS
            logger.warning(f"章节检测有 {len(wrong_ids)}/{total_questions} 题回答错误"
                           f"（成绩 {score if score is not None else '?'} 分），准备重新作答")
            try:
                next_page = self._open_redo(session, _course, _job, _job_info)
            except WorkRedoUnavailable as e:
                logger.warning(f"章节检测无法重做（{e}），保留当前成绩: {work_name}")
                return StudyResult.SUCCESS
            except Exception as e:
                logger.warning(f"打开重做页面失败（{type(e).__name__}: {e}），保留当前成绩: {work_name}")
                return StudyResult.SUCCESS

        return StudyResult.SUCCESS

    def _work_record_params(self, _course, questions) -> dict:
        return {
            "courseId": str(_course.get("courseId", "")),
            "classId": str(_course.get("clazzId", "")),
            "workId": str(questions.get("workId", "") or questions.get("workRelationId", "")),
            "workAnswerId": str(questions.get("workAnswerId", "") or ""),
            "cpi": str(_course.get("cpi", "") or questions.get("cpi", "")),
        }

    def _check_work_result(self, _session, _course, _job, _job_info, questions) -> Optional[dict]:
        """
        章节检测提交后，查询最新一次作答的成绩与每道题的对错，供判断是否需要重做。

        Returns:
            {"all_correct": bool, "wrong": list[dict], "score": float|None, "times": str, "detail": list[dict]}
            无法判断对错（接口异常或页面没有对错信息）时返回 None
        """
        base = self._work_record_params(_course, questions)
        if not base["workId"]:
            base["workId"] = _job["jobid"].replace("work-", "")

        # 1. 获取作答记录列表（提交后服务端异步生成记录，需稍作等待并多次重试）
        records = []
        for attempt in range(5):
            try:
                resp = _session.get(WORK_RECORD_LIST_URL, params=dict(base, api="1", mooc2="1", ut="s"), timeout=20)
                records = decode_work_record_list(resp.text)
                if records:
                    break
            except Exception as e:
                logger.warning(f"获取章节检测作答记录失败 (第{attempt + 1}次): {e}")
            if attempt < 4:
                time.sleep(1.5)

        result = None
        if records:
            # 2. 获取最新一次作答详情（times 从 0 开始，"第1次" 对应 times=0）
            latest_times, latest_score = max(records, key=lambda r: int(r[0]) if r[0].isdigit() else -1)
            try:
                resp = _session.get(WORK_RECORD_DETAIL_URL, params=dict(
                    base, times=latest_times, ut="s", isdisplaytable="0", firstHeader="2", isWork="false",
                    workSystem="0", api="1", archive="false", mooc2="1"), timeout=20)
                result = decode_work_result(resp.text)
                result.setdefault("times", latest_times)
                if result.get("score") is None:
                    result["score"] = latest_score
            except Exception as e:
                logger.warning(f"获取章节检测作答详情失败: {e}")

        if not result or not result.get("questions"):
            # 兜底：重新打开题目页，提交后显示的已批阅页面中同样包含每道题的对错
            logger.debug("无法获取章节检测作答详情，尝试通过题目页判断")
            try:
                resp = _session.get(WORK_URL, params=self._work_params(_course, _job, _job_info), timeout=20)
                result = decode_work_result(resp.text)
            except Exception as e:
                logger.warning(f"兜底判断章节检测状态失败: {e}")
                return None

        detail = result.get("questions") or []
        evaluation = evaluate_work_detail(detail) if detail else None
        if evaluation is None:
            logger.info("页面中没有每道题的对错信息（老师可能设置了不公布），无法判断是否需要重做")
            return None
        evaluation.update(score=result.get("score"), times=result.get("times", ""), detail=detail)
        logger.debug(f"章节检测成绩: {evaluation['score']} 分, 全部正确: {evaluation['all_correct']}, "
                     f"错题数: {len(evaluation['wrong'])}")
        return evaluation

    # ------------------------------------------------------------------
    # 空页面 / 章节学习次数
    # ------------------------------------------------------------------
    def _send_monitor_heartbeat(self, course, point):
        """
        发送章节监控心跳包到 detect.chaoxing.com，与网页端打开章节页面时的请求一致。

        Args:
            course: 课程信息字典
            point: 当前章节信息字典
        """
        callback = f"jsonp{secrets.randbelow(10 ** 21 - 10 ** 20) + 10 ** 20}"
        params = {
            "version": get_timestamp(),
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
            resp = SessionManager.get_session().get(
                "https://detect.chaoxing.com/api/monitor",
                params=params,
                headers={"Referer": referer_url},
                timeout=5,
            )
            logger.trace(f"Monitor heartbeat sent -> {resp.status_code}")
        except Exception as e:
            logger.trace(f"Monitor heartbeat failed (non-critical): {e}")

    def _visit_chapter(self, _course, point) -> Optional[requests.Response]:
        try:
            resp = SessionManager.get_session().get(
                url=STUDENT_STUDY_AJAX_URL,
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
                timeout=10,
            )
        except RequestException as e:
            logger.warning(f"访问章节失败 -> {point['title']}: {e}")
            return None
        if resp.status_code != 200:
            logger.error(f"访问章节失败 -> [{resp.status_code}]{point['title']}")
            return None
        return resp

    def study_emptypage(self, _course, point):
        if self._visit_chapter(_course, point) is None:
            return StudyResult.ERROR
        logger.info(f"空页面任务完成 -> {point['title']}")
        return StudyResult.SUCCESS

    def _access_chapter_for_count(self, _course, point):
        resp = self._visit_chapter(_course, point)
        if resp is None:
            return None
        logger.info(f"章节访问成功 -> {point['title']}")
        return resp.text

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

        setlog_url = html_unescape(match.group(1))
        try:
            resp = SessionManager.get_session().get(setlog_url, timeout=5)
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
        progress_key = f"count-{course.get('courseId')}-{course.get('clazzId')}"
        try:
            while total < target_count:
                for point in points:
                    if total >= target_count:
                        break
                    if runtime.should_stop():
                        return StudyResult.CANCELLED
                    self.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)
                    html_text = self._access_chapter_for_count(course, point)
                    if not html_text:
                        logger.error(f"章节学习次数增加失败, 当前章节: {point['title']}")
                        consecutive_failures += 1
                        if consecutive_failures >= max_consecutive_failures:
                            logger.error(f"章节学习次数增加连续失败 {consecutive_failures} 次, 终止任务")
                            return StudyResult.ERROR
                        continue

                    consecutive_failures = 0
                    self._extract_and_send_setlog(html_text)
                    self._send_monitor_heartbeat(course, point)
                    if runtime.sleep(30):
                        return StudyResult.CANCELLED
                    self._send_monitor_heartbeat(course, point)

                    total += 1
                    runtime.update_item(progress_key, f"学习次数 · {course.get('title', '')}", total, target_count,
                                        kind="count")
                    logger.info(f"章节学习次数进度: {total}/{target_count}")
        finally:
            runtime.remove_item(progress_key)
        logger.info(f"章节学习次数增加完成, 共完成: {total} 次")
        return StudyResult.SUCCESS
