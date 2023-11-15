# -*- coding: utf-8 -*-
import re
import requests
import time
import random
from hashlib import md5

from api import formatted_output
from api.cipher import AESCipher
from api.logger import logger
from api.cookies import save_cookies, use_cookies
from api.process import show_progress
from api.config import GlobalConst as gc
from api.decode import (decode_course_list,
                        decode_course_point,
                        decode_course_card)


def get_timestamp():
    return str(int(time.time() * 1000))


def get_random_seconds():
    return random.randint(30, 90)


def init_session(isVideo: bool = False):
    _session = requests.session()
    if isVideo:
        _session.headers = gc.VIDEO_HEADERS
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
    def __init__(self, account: Account = None):
        self.account = account
        self.cipher = AESCipher()

    def login(self):
        _session = requests.session()
        _url = "https://passport2.chaoxing.com/fanyalogin"
        _data = {"fid": "-1",
                    "uname": self.cipher.encrypt(self.account.username),
                    "password": self.cipher.encrypt(self.account.password),
                    "refer": "https%3A%2F%2Fi.chaoxing.com",
                    "t": True,
                    "forbidotherlogin": 0,
                    "validate": "",
                    "doubleFactorLogin": 0,
                    "independentId": 0
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
        _data = {
            "courseType": 1,
            "courseFolderId": 0,
            "query": "",
            "superstarClass": 0
        }
        logger.trace("正在读取所有的课程列表...")
        _resp = _session.post(_url, data=_data)
        # logger.trace(f"原始课程列表内容:\n{_resp.text}")
        logger.info("课程列表读取完毕...")
        return decode_course_list(_resp.text)

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
        _url = f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid={_clazzid}&courseid={_courseid}&knowledgeid={_knowledgeid}&num=0&ut=s&cpi={_cpi}&v=20160407-3&mooc2=1"
        logger.trace("开始读取章节所有任务点...")
        _resp = _session.get(_url)
        _job_list, _job_info = decode_course_card(_resp.text)
        # logger.trace(f"原始任务点列表内容:\n{_resp.text}")
        logger.info("章节任务点读取成功...")
        return _job_list, _job_info

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{playingTime * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]"
            .encode()).hexdigest()

    def video_progress_log(self, _session, _course, _job, _job_info, _dtoken, _duration, _playingTime):
        _url = (f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/"
                f"{_course['cpi']}/"
                f"{_dtoken}?"
                f"clazzId={_course['clazzId']}&"
                f"playingTime=0&"
                f"duration={_duration}&"
                f"clipTime=0_{_duration}&"
                f"objectId={_job['objectid']}&"
                f"otherInfo={_job['otherinfo']}&"
                f"courseId={_course['courseId']}&"
                f"jobid={_job['jobid']}&"
                f"userid={self.get_uid()}&"
                f"isdrag=3&"
                f"view=pc&"
                f"enc={self.get_enc(_course['clazzId'], _job['jobid'], _job['objectid'], _playingTime, _duration, self.get_uid())}&"
                f"rt=0.9&"
                f"dtype=Video&"
                f"_t={get_timestamp()}")
        resp = _session.get(_url)
        return resp.json()["isPassed"]

    def study_video(self, _course, _job, _job_info, _speed: float = 1):
        _session = init_session(isVideo=True)
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
            logger.info(f"开始任务:{_job['name']}, 总时长: {_duration}秒")
            while not _isPassed:
                if _isFinished:
                    _playingTime = _duration
                _isPassed = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, _duration, 0)
                if _isPassed:
                    break
                _wait_time = get_random_seconds()
                if _playingTime + _wait_time >= int(_duration):
                    _wait_time = int(_duration) - _playingTime
                    _isFinished = True
                # 播放进度条
                show_progress(_job['name'], _playingTime, _wait_time, _duration, _speed)
                _playingTime += _wait_time
            logger.info(f"\n任务完成:{_job['name']}")

    def study_document(self, _course, _job):
        _session = init_session()
        _url = f"https://mooc1.chaoxing.com/ananas/job/document?jobid={_job['jobid']}&knowledgeid={re.findall('nodeId_(.*?)-', _job['otherinfo'])[0]}&courseid={_course['courseId']}&clazzid={_course['clazzId']}&jtoken={_job['jtoken']}&_dc={get_timestamp()}"
        _resp = _session.get(_url)
