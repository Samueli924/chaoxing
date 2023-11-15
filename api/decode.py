# -*- coding: utf-8 -*-
import json
from bs4 import BeautifulSoup
import re
from api.logger import logger


def decode_course_list(_text):
    logger.trace("开始解码课程列表...")
    _soup = BeautifulSoup(_text, "lxml")
    _raw_courses = _soup.select("li.course")
    _course_list = list()
    for course in _raw_courses:
        if not course.select_one("a.not-open-tip"):
            _course_detail = {}
            _course_detail["id"] = course.attrs["id"]
            _course_detail["info"] = course.attrs["info"]
            _course_detail["roleid"] = course.attrs["roleid"]
            _course_detail["clazzId"] = course.select_one("input.clazzId").attrs["value"]
            _course_detail["courseId"] = course.select_one("input.courseId").attrs["value"]
            _course_detail["cpi"] = re.findall("cpi=(.*?)&", course.select_one("a").attrs["href"])[0]
            _course_detail["title"] = course.select_one("span.course-name").attrs["title"]
            _course_detail["desc"] = course.select_one("p.margint10").attrs["title"]
            _course_detail["teacher"] = course.select_one("p.color3").attrs["title"]
            _course_list.append(_course_detail)
    return _course_list


def decode_course_point(_text):
    logger.trace("开始解码章节列表...")
    _soup = BeautifulSoup(_text, "lxml")
    _course_point = {}
    _point_list = []
    _raw_points = _soup.select("div.chapter_item")
    for _point in _raw_points:
        if (not "id" in _point.attrs) or (not "title" in _point.attrs):
            continue
        _point_detail = {}
        _point_detail["id"] = re.findall("^cur(\d{1,20})$", _point.attrs["id"])[0]
        _point_detail["title"] = str(_point.select_one("span.catalog_sbar").text) + " " + str(_point.attrs["title"])
        _point_detail["jobCount"] = 0
        if _point.select_one("input.knowledgeJobCount"):
            _point_detail["jobCount"] = _point.select_one("input.knowledgeJobCount").attrs["value"]
        _point_list.append(_point_detail)
    _course_point["points"] = _point_list
    return _course_point


def decode_course_card(_text: str):
    logger.trace("开始解码任务点列表...")
    _temp = re.findall("mArg=\{(.*?)};", _text.replace(" ", ""))
    if _temp:
        _temp = _temp[0]
    else:
        return None
    _cards = json.loads("{" + _temp + "}")
    _job_info = {}
    _job_list = []
    if _cards:
        _job_info = {}
        _job_info["ktoken"] = _cards["defaults"]["ktoken"]
        _job_info["mtEnc"] = _cards["defaults"]["mtEnc"]
        _job_info["reportTimeInterval"] = _cards["defaults"]["reportTimeInterval"]   # 60
        _job_info["defenc"] = _cards["defaults"]["defenc"]
        _job_info["cardid"] = _cards["defaults"]["cardid"]
        _job_info["cpi"] = _cards["defaults"]["cpi"]
        _job_info["qnenc"] = _cards["defaults"]["qnenc"]
        _cards = _cards["attachments"]
        _job_list = []
        for _card in _cards:
            # 已经通过的任务
            if "isPassed" in _card and _card["isPassed"] == True:
                continue
            # 不属于任务点的任务
            if "job" not in _card or _card["job"] == False:
                continue
            # 视频任务
            if _card["type"] == "video":
                _job = {}
                _job["type"] = "video"
                _job["jobid"] = _card["jobid"]
                _job["name"] = _card["property"]["name"]
                _job["otherinfo"] = _card["otherInfo"]
                _job["mid"] = _card["mid"]
                _job["objectid"] = _card["objectId"]
                _job["aid"] = _card["aid"]
                # _job["doublespeed"] = _card["property"]["doublespeed"]
                _job_list.append(_job)
                continue
            if _card["type"] == "document":
                _job = {}
                _job["type"] = "document"
                _job["jobid"] = _card["jobid"]
                _job["otherinfo"] = _card["otherInfo"]
                _job["jtoken"] = _card["jtoken"]
                _job["mid"] = _card["mid"]
                _job["enc"] = _card["enc"]
                _job["aid"] = _card["aid"]
                _job["objectid"] = _card["property"]["objectid"]
                _job_list.append(_job)
                continue
            if _card["type"] == "workid":
                continue
        return _job_list, _job_info
