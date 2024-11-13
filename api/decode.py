# -*- coding: utf-8 -*-
"""
学习通解码模块
用于解析和处理学习通页面中的数据
包含课程列表、文件夹、章节点、任务卡片、题目等内容的解析
"""

import re
import json
from bs4 import BeautifulSoup
from api.logger import logger
from api.font_decoder import FontDecoder


def decode_course_list(html_text: str) -> list:
    """解析课程列表页面,提取课程信息
    
    Args:
        html_text: 课程列表页面的HTML文本
        
    Returns:
        list: 包含所有课程信息的列表,每个课程为一个字典
    """
    logger.trace("开始解码课程列表...")
    soup = BeautifulSoup(html_text, "lxml")
    courses = []
    
    for course in soup.select("div.course"):
        # 跳过未开放的课程
        if course.select_one("a.not-open-tip") or course.select_one("div.not-open-tip"):
            continue
            
        course_info = {
            "id": course.attrs["id"],
            "info": course.attrs["info"], 
            "roleid": course.attrs["roleid"],
            "clazzId": course.select_one("input.clazzId").attrs["value"],
            "courseId": course.select_one("input.courseId").attrs["value"],
            "cpi": re.findall(r"cpi=(.*?)&", course.select_one("a").attrs["href"])[0],
            "title": course.select_one("span.course-name").attrs["title"],
            "desc": course.select_one("p.margint10").attrs["title"] if course.select_one("p.margint10") else '',
            "teacher": course.select_one("p.color3").attrs["title"]
        }
        courses.append(course_info)
        
    return courses


def decode_course_folder(html_text: str) -> list:
    """解析二级课程文件夹列表
    
    Args:
        html_text: 文件夹页面的HTML文本
        
    Returns:
        list: 包含所有文件夹信息的列表
    """
    logger.trace("开始解码二级课程列表...")
    soup = BeautifulSoup(html_text, "lxml")
    folders = []
    
    for course in soup.select("ul.file-list>li"):
        if course.attrs["fileid"]:
            folder = {
                "id": course.attrs["fileid"],
                "rename": course.select_one("input.rename-input").attrs["value"]
            }
            folders.append(folder)
            
    return folders


def decode_course_point(html_text: str) -> dict:
    """解析课程章节列表
    
    Args:
        html_text: 章节列表页面的HTML文本
        
    Returns:
        dict: 包含章节点信息的字典,格式为:
            {
                "hasLocked": bool,  # 是否有需要解锁的章节
                "points": list      # 章节点列表
            }
    """
    logger.trace("开始解码章节列表...")
    soup = BeautifulSoup(html_text, "lxml")
    course_point = {
        "hasLocked": False,
        "points": []
    }
    
    for chapter in soup.find_all("div", class_="chapter_unit"):
        points = []
        for point_li in chapter.find_all("li"):
            point_div = point_li.div
            if not "id" in point_div.attrs:
                continue
                
            point = {
                "id": re.findall(r"^cur(\d{1,20})$", point_div.attrs["id"])[0],
                "title": point_div.select_one("a.clicktitle").text.replace("\n",'').strip(),
                "jobCount": 1  # 默认任务点数为1
            }
            
            # 获取实际任务点数或检查是否需要解锁
            job_count_input = point_div.select_one("input.knowledgeJobCount") 
            if job_count_input:
                point["jobCount"] = job_count_input.attrs["value"]
            elif '解锁' in point_div.select_one("span.bntHoverTips").text:
                course_point["hasLocked"] = True
                
            points.append(point)
            
        course_point["points"].extend(points)
        
    return course_point


def decode_course_card(html_text: str) -> tuple:
    """解析课程任务卡片列表
    
    Args:
        html_text: 任务卡片页面的HTML文本
        
    Returns:
        tuple: (任务列表, 任务信息)
            任务列表包含所有未完成的任务
            任务信息包含ktoken等必要参数
    """
    logger.trace("开始解码任务点列表...")
    
    # 检查章节是否开放
    if '章节未开放' in html_text:
        return [], {'notOpen': True}
        
    # 提取任务卡片数据
    card_data = re.findall(r"mArg=\{(.*?)\};", html_text.replace(" ", ""))
    if not card_data:
        return [], {}
        
    cards = json.loads("{" + card_data[0] + "}")
    if not cards:
        return [], {}
        
    # 提取任务信息
    job_info = {
        key: cards["defaults"][key]
        for key in ["ktoken", "mtEnc", "reportTimeInterval", "defenc", 
                   "cardid", "cpi", "qnenc", "knowledgeid"]
    }
    
    # 解析任务列表
    job_list = []
    for card in cards["attachments"]:
        # 跳过已完成任务
        if card.get("isPassed"):
            continue
            
        # 处理非任务点内容
        if not card.get("job"):
            if _should_process_read_task(card):
                job_list.append(_parse_read_task(card))
            continue
            
        # 根据任务类型解析
        job_parser = {
            "video": _parse_video_task,
            "document": _parse_document_task,
            "workid": _parse_workid_task
        }.get(card["type"])
        
        if job_parser:
            job = job_parser(card)
            if job:
                job_list.append(job)
                
    return job_list, job_info


def decode_questions_info(html_content: str) -> dict:
    """解析试题信息
    
    Args:
        html_content: 试题页面的HTML内容
        
    Returns:
        dict: 包含试题信息的字典
    """
    def replace_rtn(text: str) -> str:
        """清理文本中的特殊字符"""
        return text.replace('\r', '').replace('\t', '').replace('\n', '')

    soup = BeautifulSoup(html_content, "lxml")
    form_tag = soup.find("form")
    fd = FontDecoder(html_content)  # 加载字体解码器
    
    # 提取表单基本信息
    form_data = {
        input_tag.attrs["name"]: input_tag.attrs.get("value",'')
        for input_tag in form_tag.find_all("input")
        if 'name' in input_tag.attrs and 'answer' not in input_tag.attrs["name"]
    }
    
    # 题型映射表
    QUESTION_TYPES = {
        '0': 'single',      # 单选题
        '1': 'multiple',    # 多选题
        '2': 'completion',  # 填空题
        '3': 'judgement'    # 判断题
    }
    
    # 解析试题
    form_data['questions'] = []
    for div_tag in form_tag.find_all("div", class_="singleQuesId"):
        # 提取题目和选项
        title = replace_rtn(fd.decode(div_tag.find("div", class_="Zy_TItle").text))
        options = '\n'.join(
            replace_rtn(fd.decode(li.text))
            for li in div_tag.find("ul").find_all("li")
        )
        
        # 获取题型
        type_code = div_tag.find('div', class_='TiMu').attrs['data']
        q_type = QUESTION_TYPES.get(type_code, 'unknown')
        if q_type == 'unknown':
            logger.info(f"未知题型代码 -> {type_code}")
            
        # 构建题目数据
        question = {
            'id': div_tag.attrs["data"],
            'title': title,
            'options': options,
            'type': q_type,
            'answerField': {
                f'answer{div_tag.attrs["data"]}': '',
                f'answertype{div_tag.attrs["data"]}': type_code
            }
        }
        form_data['questions'].append(question)
    
    # 添加答题ID列表
    form_data['answerwqbid'] = ','.join(q['id'] for q in form_data['questions']) + ','
    
    return form_data


# 辅助函数
def _should_process_read_task(card: dict) -> bool:
    """判断是否需要处理阅读任务"""
    return (card.get('type') == "read" and 
            not card.get('property', {}).get('read', False))

def _parse_read_task(card: dict) -> dict:
    """解析阅读任务"""
    return {
        'title': card['property']['title'],
        'type': 'read',
        'id': card['property']['id'],
        'jobid': card['jobid'],
        'jtoken': card['jtoken'],
        'mid': card['mid'],
        'otherinfo': card['otherInfo'],
        'enc': card['enc'],
        'aid': card['aid']
    }

def _parse_video_task(card: dict) -> dict:
    """解析视频任务"""
    try:
        return {
            'type': 'video',
            'jobid': card['jobid'],
            'name': card['property']['name'],
            'otherinfo': card['otherInfo'],
            'mid': card['mid'],
            'objectid': card['objectId'],
            'aid': card['aid']
        }
    except KeyError:
        logger.warning("出现转码失败视频，已跳过...")
        return None

def _parse_document_task(card: dict) -> dict:
    """解析文档任务"""
    return {
        'type': 'document',
        'jobid': card['jobid'],
        'otherinfo': card['otherInfo'],
        'jtoken': card['jtoken'],
        'mid': card['mid'],
        'enc': card['enc'],
        'aid': card['aid'],
        'objectid': card['property']['objectid']
    }

def _parse_workid_task(card: dict) -> dict:
    """解析章节测验任务"""
    return {
        'type': 'workid',
        'jobid': card['jobid'],
        'otherinfo': card['otherInfo'],
        'mid': card['mid'],
        'enc': card['enc'],
        'aid': card['aid']
    }
