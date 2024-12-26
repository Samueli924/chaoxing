# -*- coding: utf-8 -*-
from calendar import LocaleHTMLCalendar
import re
import time
import random
import requests
from hashlib import md5
from requests.adapters import HTTPAdapter

from api.cipher import AESCipher
from api.logger import logger
from api.cookies import save_cookies, use_cookies
from api.process import show_progress
from api.config import GlobalConst as gc
from api.decode import (
    decode_course_list,
    decode_course_point,
    decode_course_card,
    decode_course_folder,
    decode_questions_info,
)
from api.answer import *


def get_timestamp():
    return str(int(time.time() * 1000))


def get_random_seconds():
    return random.randint(30, 90)


def init_session(isVideo: bool = False, isAudio: bool = False):
    _session = requests.session()
    _session.verify = False
    _session.mount("http://", HTTPAdapter(max_retries=3))
    _session.mount("https://", HTTPAdapter(max_retries=3))
    if isVideo:
        _session.headers = gc.VIDEO_HEADERS
    elif isAudio:
        _session.headers = gc.AUDIO_HEADERS
    else:
        _session.headers = gc.HEADERS
    _session.cookies.update(use_cookies())
    return _session


class Account:
    username = None
    password = None
    last_login = None
    isSuccess = None

    def __init__(self, _username, _password):
        self.username = _username
        self.password = _password


class Chaoxing:
    def __init__(self, account: Account = None, tiku: Tiku = None):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku

    def login(self):
        _session = requests.session()
        _session.verify = False
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
        resp = _session.post(_url, headers=gc.HEADERS, data=_data)
        if resp and resp.json()["status"] == True:
            save_cookies(_session)
            logger.info("登录成功...")
            return {"status": True, "msg": "登录成功"}
        else:
            return {"status": False, "msg": str(resp.json()["msg2"])}

    def get_fid(self):
        _session = init_session()
        return _session.cookies.get("fid")

    def get_uid(self):
        _session = init_session()
        return _session.cookies.get("_uid")

    def get_course_list(self):
        _session = init_session()
        _url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
        _data = {"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0}
        logger.trace("正在读取所有的课程列表...")
        # 接口突然抽风, 增加headers
        _headers = {
            "Host": "mooc2-ans.chaoxing.com",
            "sec-ch-ua-platform": '"Windows"',
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
            "Accept": "text/html, */*; q=0.01",
            "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "sec-ch-ua-mobile": "?0",
            "Origin": "https://mooc2-ans.chaoxing.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
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
            _resp = _session.post(_url, data=_data)
            course_list += decode_course_list(_resp.text)
        return course_list

    def get_course_point(self, _courseid, _clazzid, _cpi):
        _session = init_session()
        _url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={_courseid}&clazzid={_clazzid}&cpi={_cpi}&ut=s"
        logger.trace("开始读取课程所有章节...")
        _resp = _session.get(_url)
        # logger.trace(f"原始章节列表内容:\n{_resp.text}")
        logger.info("课程章节读取成功...")
        return decode_course_point(_resp.text)

    def get_job_list(self, _clazzid, _courseid, _cpi, _knowledgeid):
        _session = init_session()
        job_list = []
        job_info = {}
        for _possible_num in [
            "0",
            "1",
            "2",
        ]:  # 学习界面任务卡片数, 很少有3个的, 但是对于章节解锁任务点少一个都不行, 可以从API /mooc-ans/mycourse/studentstudyAjax获取值, 或者干脆直接加, 但二者都会造成额外的请求
            _url = f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid={_clazzid}&courseid={_courseid}&knowledgeid={_knowledgeid}&num={_possible_num}&ut=s&cpi={_cpi}&v=20160407-3&mooc2=1"
            logger.trace("开始读取章节所有任务点...")
            _resp = _session.get(_url)
            _job_list, _job_info = decode_course_card(_resp.text)
            if _job_info.get("notOpen", False):
                # 直接返回, 节省一次请求
                logger.info("该章节未开放")
                return [], _job_info
            job_list += _job_list
            job_info.update(_job_info)
            # if _job_list and len(_job_list) != 0:
            #     break
        # logger.trace(f"原始任务点列表内容:\n{_resp.text}")
        logger.info("章节任务点读取成功...")
        return job_list, job_info

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{playingTime * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]".encode()
        ).hexdigest()

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
    ):
        if "courseId" in _job["otherinfo"]:
            _mid_text = f"otherInfo={_job['otherinfo']}&"
        else:
            _mid_text = f"otherInfo={_job['otherinfo']}&courseId={_course['courseId']}&"
        _success = False
        for _possible_rt in ["0.9", "1"]:
            _url = (
                f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/"
                f"{_course['cpi']}/"
                f"{_dtoken}?"
                f"clazzId={_course['clazzId']}&"
                f"playingTime={_playingTime}&"
                f"duration={_duration}&"
                f"clipTime=0_{_duration}&"
                f"objectId={_job['objectid']}&"
                f"{_mid_text}"
                f"jobid={_job['jobid']}&"
                f"userid={self.get_uid()}&"
                f"isdrag=3&"
                f"view=pc&"
                f"enc={self.get_enc(_course['clazzId'], _job['jobid'], _job['objectid'], _playingTime, _duration, self.get_uid())}&"
                f"rt={_possible_rt}&"
                f"dtype={_type}&"
                f"_t={get_timestamp()}"
            )
            resp = _session.get(_url)
            if resp.status_code == 200:
                _success = True
                break  # 如果返回为200正常, 则跳出循环
            elif resp.status_code == 403:
                continue  # 如果出现403无权限报错, 则继续尝试不同的rt参数
        if _success:
            return resp.json()
        else:
            # 若出现两个rt参数都返回403的情况, 则跳过当前任务
            logger.warning("出现403报错, 尝试修复无效, 正在跳过当前任务点...")
            return False

    def study_video(
        self, _course, _job, _job_info, _speed: float = 1.0, _type: str = "Video"
    ):
        if _type == "Video":
            _session = init_session(isVideo=True)
        else:
            _session = init_session(isAudio=True)
        _session.headers.update()
        _info_url = f"https://mooc1.chaoxing.com/ananas/status/{_job['objectid']}?k={self.get_fid()}&flag=normal"
        _video_info = _session.get(_info_url).json()
        if _video_info["status"] == "success":
            _dtoken = _video_info["dtoken"]
            _duration = _video_info["duration"]
            _crc = _video_info["crc"]
            _key = _video_info["key"]
            _isPassed = False
            _isFinished = False
            _playingTime = 0
            logger.info(f"开始任务: {_job['name']}, 总时长: {_duration}秒")
            while not _isFinished:
                if _isFinished:
                    _playingTime = _duration
                _isPassed = self.video_progress_log(
                    _session,
                    _course,
                    _job,
                    _job_info,
                    _dtoken,
                    _duration,
                    _playingTime,
                    _type,
                )
                if not _isPassed or (_isPassed and _isPassed["isPassed"]):
                    break
                _wait_time = get_random_seconds()
                if _playingTime + _wait_time >= int(_duration):
                    _wait_time = int(_duration) - _playingTime
                    _isFinished = True
                # 播放进度条
                show_progress(_job["name"], _playingTime, _wait_time, _duration, _speed)
                _playingTime += _wait_time
            print("\r", end="", flush=True)
            logger.info(f"任务完成: {_job['name']}")

    def study_document(self, _course, _job):
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
        _session = init_session()
        _url = f"https://mooc1.chaoxing.com/ananas/job/document?jobid={_job['jobid']}&knowledgeid={re.findall(r'nodeId_(.*?)-', _job['otherinfo'])[0]}&courseid={_course['courseId']}&clazzid={_course['clazzId']}&jtoken={_job['jtoken']}&_dc={get_timestamp()}"
        _resp = _session.get(_url)

    def study_work(self, _course, _job, _job_info) -> None:
        if self.tiku.DISABLE or not self.tiku:
            return None

        def match_answer_with_options(answer: str, options_list: list[str], q_type: str) -> str:
            # pretreatment
            # del ';' '；' ',' '，' ' ' '、'
            # Prevents incorrect answers due to poor matches with the question bank.
            # It would be better to maintain the return in terms of correctness, starting with this.
            def delete_option_separator(options: str) -> str:
                return re.sub(r"[;,，、\s]", "", options)
            """统一的答案匹配处理函数"""
            matched_answer = ""
            if q_type == "multiple":
                for ans in multi_cut(answer):
                    ans = delete_option_separator(ans)
                    ans = ans.strip().upper()
                    for opt in options_list:
                        opt = delete_option_separator(opt)
                        if ans == opt[:1].upper() or ans in opt.upper():
                            matched_answer += opt[:1]
                matched_answer = "".join(sorted(set(matched_answer)))  # 去重并排序
            elif q_type == "judgement":
                matched_answer = "true" if self.tiku.jugement_select(answer) else "false"
            else:  # single
                for opt in options_list:
                    if answer.upper() in opt.upper():
                        matched_answer = opt[:1]
                        break
            return matched_answer

        def random_answer(options: str, q_type: str) -> str:
            """改进的随机答案生成"""
            if not options:
                return ""

            options_list = multi_cut(options)
            if not options_list:
                logger.error("选项为空，未能正确提取题目选项信息!")
                return ""

            if q_type == "multiple":
                # 权重调整：2选项(10%), 3选项(50%), 4选项(40%)
                num_choices = random.choices([2, 3, 4], weights=[0.1, 0.5, 0.4], k=1)[0]
                num_choices = min(num_choices, len(options_list))  # 确保不超过可用选项数
                selected = random.sample(options_list, num_choices)
                return "".join(sorted(opt[:1] for opt in selected))
            elif q_type == "single":
                return random.choice(options_list)[:1]
            elif q_type == "judgement":
                return "true" if random.choice([True, False]) else "false"
            return ""

        def multi_cut(answer: str) -> list[str]:
            """
            将多选题答案字符串按特定字符进行切割, 并返回切割后的答案列表.

            参数:
            answer (str): 多选题答案字符串.

            返回:
            list[str]: 切割后的答案列表, 如果无法切割, 则返回默认的选项列表 ['A', 'B', 'C', 'D'].

            注意:
            如果无法从网页中提取题目信息, 将记录警告日志并返回默认选项列表.
            """
            # cut_char = [',','，','|','\n','\r','\t','#','*','-','_','+','@','~','/','\\','.','&',' ']    # 多选答案切割符
            # ',' 在常规被正确划分的, 选项中出现, 导致 multi_cut 无法正确划分选项 #391
            # IndexError: Cannot choose from an empty sequence #391
            # 同时为了避免没有考虑到的 case, 应该先按照 '\n' 匹配, 匹配不到再按照其他字符匹配
            cut_char = [
                "\n",
                "；",
                ",",
                "，",
                "|",
                "\r",
                "\t",
                "#",
                "*",
                "-",
                "_",
                "+",
                "@",
                "~",
                "/",
                "\\",
                ".",
                "&",
                " ",
                "、",
            ]  # 多选答案切割符
            res = []
            for char in cut_char:
                # logger.debug(f"尝试使用字符 '{char}' 进行切割") # 输出的时候不要渲染
                res = [
                    opt for opt in answer.split(char) if opt.strip()
                ]  # Filter empty strings
                if len(res) > 1:
                    logger.debug(f"使用字符 '{char}' 切割成功")
                    logger.debug(f"切割后的选项列表为: {res}")
                    return res
            logger.warning(
                f"未能从网页中提取题目信息, 以下为相关信息：\n\t{answer}\n\n{_ORIGIN_HTML_CONTENT}\n"
            )  # 尝试输出网页内容和选项信息
            logger.warning("未能正确提取题目选项信息! 请反馈并提供以上信息")
            return ["A", "B", "C", "D"]  # 默认多选题为4个选项

        # 获取题目信息
        _session = init_session()
        headers = {
            "Host": "mooc1.chaoxing.com",
            "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "iframe",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
        }
        cookies = _session.cookies.get_dict()

        _url = "https://mooc1.chaoxing.com/mooc-ans/api/work"
        _resp = requests.get(
            _url,
            headers=headers,
            cookies=cookies,
            verify=False,
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
            },
        )
        _ORIGIN_HTML_CONTENT = _resp.text  # 用于配合输出网页源码, 帮助修复#391错误
        questions = decode_questions_info(_resp.text)  # 加载题目信息

        # 处理每个题目
        for q in questions["questions"]:
            logger.debug(f"当前题目信息 -> {q}")
            options_list = multi_cut(q["options"])
            res = self.tiku.query(q)
            
            if not res:
                answer = random_answer(q["options"], q["type"])
                logger.info(f"未找到答案，随机选择 -> {answer}")
            else:
                answer = match_answer_with_options(res, options_list, q["type"])
                if not answer:
                    answer = random_answer(q["options"], q["type"])
                    logger.info(f"答案匹配失败，随机选择 -> {answer}")
                else:
                    logger.info(f"找到匹配答案 -> {answer}")
            
            q["answerField"][f'answer{q["id"]}'] = answer
            logger.info(f'{q["title"]} 填写答案为 {answer}')

        # 提交模式  现在与题库绑定
        questions["pyFlag"] = self.tiku.get_submit_params()

        # 组建提交表单
        for q in questions["questions"]:
            questions.update(
                {
                    f'answer{q["id"]}': q["answerField"][f'answer{q["id"]}'],
                    f'answertype{q["id"]}': q["answerField"][f'answertype{q["id"]}'],
                }
            )

        del questions["questions"]

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
                # "Referer": "https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?courseId=246831735&workAnswerId=52680423&workId=37778125&api=1&knowledgeid=913820156&classId=107515845&oldWorkId=07647c38d8de4c648a9277c5bed7075a&jobid=work-07647c38d8de4c648a9277c5bed7075a&type=&isphone=false&submit=false&enc=1d826aab06d44a1198fc983ed3d243b1&cpi=338350298&mooc2=1&skipHeader=true&originJobId=work-07647c38d8de4c648a9277c5bed7075a",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
            },
        )
        # TODO 提交答案后查询分数和正确率
        if res.status_code == 200:
            res_json = res.json()
            if res_json["status"]:
                logger.info(f'提交答题成功 -> {res_json["msg"]}')
            else:
                logger.error(f'提交答题失败 -> {res_json["msg"]}')
        else:
            logger.error(f"提交答题失败 -> {res.text}")

    def strdy_read(self, _course, _job, _job_info) -> None:
        """
        阅读任务学习, 仅完成任务点, 并不增长时长
        """
        _session = init_session()
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
        else:
            _resp_json = _resp.json()
            logger.info(f"阅读任务学习 -> {_resp_json['msg']}")
