# -*- coding: utf-8 -*-
"""
超星学习通数据解析模块

该模块负责解析超星学习通平台的课程、章节、任务点等各种数据，
并转换为程序内部使用的结构化数据格式。
"""
import json
import re
from typing import List, Dict, Tuple, Any, Optional

from bs4 import BeautifulSoup, NavigableString

from api.font_decoder import FontDecoder
from api.logger import logger


def decode_course_list(html_text: str) -> List[Dict[str, str]]:
    """
    解析课程列表页面，提取课程信息
    
    Args:
        html_text: 课程列表页面的HTML内容
        
    Returns:
        课程信息列表，每个课程包含id、title、teacher等信息
    """
    logger.trace("开始解码课程列表...")
    soup = BeautifulSoup(html_text, "lxml")
    raw_courses = soup.select("div.course")
    course_list = []

    for course in raw_courses:
        # 跳过未开放课程
        if course.select_one("a.not-open-tip") or course.select_one("div.not-open-tip"):
            continue

        course_detail = {
            "id": course.attrs["id"],
            "info": course.attrs["info"],
            "roleid": course.attrs["roleid"],
            "clazzId": course.select_one("input.clazzId").attrs["value"],
            "courseId": course.select_one("input.courseId").attrs["value"],
            "cpi": re.findall(r"cpi=(.*?)&", course.select_one("a").attrs["href"])[0],
            "title": course.select_one("span.course-name").attrs["title"],
            "desc": course.select_one("p.margint10").attrs["title"] if course.select_one("p.margint10") else "",
            "teacher": course.select_one("p.color3").attrs["title"]
        }
        course_list.append(course_detail)

    return course_list


def decode_course_folder(html_text: str) -> List[Dict[str, str]]:
    """
    解析二级课程列表页面，提取文件夹信息
    
    Args:
        html_text: 二级课程列表页面的HTML内容
        
    Returns:
        课程文件夹信息列表
    """
    logger.trace("开始解码二级课程列表...")
    soup = BeautifulSoup(html_text, "lxml")
    raw_courses = soup.select("ul.file-list>li")
    course_folder_list = []

    for course in raw_courses:
        if not course.attrs.get("fileid"):
            continue

        course_folder_detail = {
            "id": course.attrs["fileid"],
            "rename": course.select_one("input.rename-input").attrs["value"]
        }
        course_folder_list.append(course_folder_detail)

    return course_folder_list


def decode_course_point(html_text: str) -> Dict[str, Any]:
    """
    解析章节列表页面，提取章节点信息
    
    Args:
        html_text: 章节列表页面的HTML内容
        
    Returns:
        章节信息字典，包含是否锁定状态和章节点列表
    """
    logger.trace("开始解码章节列表...")
    soup = BeautifulSoup(html_text, "lxml")
    course_point = {
        "hasLocked": False,  # 用于判断该课程任务是否是需要解锁
        "points": [],
    }

    for chapter_unit in soup.find_all("div", class_="chapter_unit"):
        points = _extract_points_from_chapter(chapter_unit)
        # 检查是否有锁定内容
        for point in points:
            if point.get("need_unlock", False):
                course_point["hasLocked"] = True

        course_point["points"].extend(points)

    return course_point


def _extract_points_from_chapter(chapter_unit) -> List[Dict[str, Any]]:
    """
    从章节单元中提取章节点信息
    
    Args:
        chapter_unit: BeautifulSoup对象，表示一个章节单元
        
    Returns:
        章节点信息列表
    """
    point_list = []
    raw_points = chapter_unit.find_all("li")

    for raw_point in raw_points:
        point = raw_point.div
        if "id" not in point.attrs:
            continue

        point_id = re.findall(r"^cur(\d{1,20})$", point.attrs["id"])[0]
        point_title = point.select_one("a.clicktitle").text.replace("\n", "").strip()

        # 提取任务数量
        job_count = 1  # 默认为1
        need_unlock = False
        if point.select_one("input.knowledgeJobCount"):
            job_count = point.select_one("input.knowledgeJobCount").attrs["value"]
        elif point.select_one("span.bntHoverTips") and "解锁" in point.select_one("span.bntHoverTips").text:
            need_unlock = True

        # 判断是否已完成
        is_finished = False
        if point.select_one("span.bntHoverTips") and "已完成" in point.select_one("span.bntHoverTips").text:
            is_finished = True

        point_detail = {
            "id": point_id,
            "title": point_title,
            "jobCount": job_count,
            "has_finished": is_finished,
            "need_unlock": need_unlock
        }
        point_list.append(point_detail)

    return point_list


def decode_course_card(
    html_text: str, force_video_time: bool = False
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    解析任务点列表页面，提取任务点信息
    
    Args:
        html_text: 任务点列表页面的HTML内容
        
    Returns:
        任务点列表和任务信息的元组
    """
    logger.trace("开始解码任务点列表...")

    # 检查章节是否未开放
    if "章节未开放" in html_text:
        return [], {"notOpen": True}

    # 提取mArg参数
    temp = re.findall(r"mArg=\{(.*?)\};", html_text.replace(" ", ""))
    if not temp:
        return [], {}

    # 解析JSON数据
    cards_data = json.loads("{" + temp[0] + "}")

    if not cards_data:
        return [], {}

    # 提取任务信息
    job_info = _extract_job_info(cards_data)

    # 处理所有附件任务
    cards = cards_data.get("attachments", [])
    job_list = _process_attachment_cards(cards, force_video_time=force_video_time)

    return job_list, job_info


def _extract_job_info(cards_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    从卡片数据中提取任务基本信息
    
    Args:
        cards_data: 卡片数据字典
        
    Returns:
        任务基本信息字典
    """
    defaults = cards_data.get("defaults", {})
    if not defaults:
        return {}

    return {
        "ktoken": defaults.get("ktoken", ""),
        "mtEnc": defaults.get("mtEnc", ""),
        "reportTimeInterval": defaults.get("reportTimeInterval", 60),
        "defenc": defaults.get("defenc", ""),
        "cardid": defaults.get("cardid", ""),
        "cpi": defaults.get("cpi", ""),
        "qnenc": defaults.get("qnenc", ""),
        "knowledgeid": defaults.get("knowledgeid", "")
    }


def _is_video_or_audio_card(card: Dict[str, Any]) -> bool:
    """判断附件卡片是否为视频或音频类型."""
    card_type = card.get("type", "").lower()
    property_data = card.get("property", {}) or {}
    prop_type = property_data.get("type", "").lower()
    prop_module = property_data.get("module", "").lower()
    return (
        card_type in ("video", "audio")
        or prop_module in ("insertvideo", "insertaudio")
        or prop_type in (".mp4", ".mp3", "video", "audio")
    )


def _is_live_card(card: Dict[str, Any]) -> bool:
    """判断附件卡片是否为直播任务类型."""
    card_type = card.get("type", "").lower()
    property_data = card.get("property", {}) or {}
    prop_type = property_data.get("type", "").lower()
    resource_type = property_data.get("resourceType", "").lower()
    return (
        "live" in card_type
        or "live" in prop_type
        or "live" in resource_type
        or "livestream" in card_type
        or property_data.get("liveId") is not None
        or property_data.get("streamName") is not None
        or property_data.get("vdoid") is not None
    )


def _handle_null_job_card(
    card: Dict[str, Any], force_video_time: bool, is_video_or_audio: bool
) -> Optional[Dict[str, Any]]:
    """处理 job 字段为 None 的卡片（强制刷时长模式下的章节媒体或普通阅读任务）."""
    if force_video_time and is_video_or_audio:
        if "otherInfo" in card:
            card["otherInfo"] = card["otherInfo"].split("&")[0]
        return _process_video_task(card)
    return _process_read_task(card)


def _dispatch_card_by_type(
    card: Dict[str, Any], card_type: str, is_video_or_audio: bool
) -> Optional[Dict[str, Any]]:
    """根据卡片类型分发解析任务."""
    if _is_live_card(card):
        return _process_live_task(card)
    if card_type == "video" or is_video_or_audio:
        return _process_video_task(card)
    if card_type == "document":
        return _process_document_task(card)
    if card_type == "workid":
        return _process_work_task(card)
    logger.warning(f"Unknown card type: {card_type}")
    logger.warning(card)
    return None


def _process_attachment_cards(
    cards: List[Dict[str, Any]], force_video_time: bool = False
) -> List[Dict[str, Any]]:
    """
    处理所有附件任务卡片，强化直播任务识别逻辑
    
    Args:
        cards: 附件任务卡片列表
        force_video_time: 是否开启强制刷音视频时长模式
        
    Returns:
        处理后的任务列表
    """
    job_list = []

    for card in cards:
        card_type = card.get("type", "").lower()
        is_video_or_audio = _is_video_or_audio_card(card)

        # 跳过已通过的任务（若开启强制刷音视频时长，则不跳过音视频任务）
        if card.get("isPassed", False) and not (force_video_time and is_video_or_audio):
            continue

        # 处理无job字段的特殊任务
        if card.get("job") is None:
            special_job = _handle_null_job_card(card, force_video_time, is_video_or_audio)
            if special_job:
                job_list.append(special_job)
            continue

        # 清理otherInfo字段中的无效参数
        if "otherInfo" in card:
            logger.trace("Fixing other info...")
            card["otherInfo"] = card["otherInfo"].split("&")[0]
            logger.trace(f"New info: {card['otherInfo']}")

        parsed_job = _dispatch_card_by_type(card, card_type, is_video_or_audio)
        if parsed_job:
            job_list.append(parsed_job)

    return job_list


def _process_live_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理直播类型任务，提取所有必要参数"""
    try:
        property_data = card.get("property", {})
        return {
            "type": "live",
            "jobid": card.get("jobid", str(card.get("id", ""))),  # 兼容不同格式的任务ID
            "name": property_data.get("title", property_data.get("name", "未知直播")),
            "otherinfo": card.get("otherInfo", ""),
            "property": property_data,  # 保留完整属性用于后续处理
            "mid": card.get("mid", ""),
            "objectid": card.get("objectId", ""),
            "aid": card.get("aid", ""),
            # 补充直播特有标识
            "liveId": property_data.get("liveId"),
            "streamName": property_data.get("streamName")
        }
    except Exception as e:
        logger.error(f"解析直播任务失败: {str(e)}, 任务数据: {str(card)[:200]}")
        return None


def _process_read_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理阅读类型任务"""
    if not (card.get("type") == "read" and not card.get("property", {}).get("read", False)):
        return None

    return {
        "title": card.get("property", {}).get("title", ""),
        "type": "read",
        "id": card.get("property", {}).get("id", ""),
        "jobid": card.get("jobid", ""),
        "jtoken": card.get("jtoken", ""),
        "mid": card.get("mid", ""),
        "otherinfo": card.get("otherInfo", ""),
        "enc": card.get("enc", ""),
        "aid": card.get("aid", "")
    }


def _process_video_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理视频类型任务"""
    try:
        prop = card.get("property", {}) or {}
        mid = card.get("mid") or prop.get("mid")
        objectid = (
            card.get("objectId")
            or card.get("objectid")
            or prop.get("objectid")
            or prop.get("objectId", "")
        )
        if not mid or not objectid:
            logger.warning("出现转码失败视频，已跳过...")
            return None
        jobid = card.get("jobid") or prop.get("jobid") or prop.get("_jobid", "")
        return {
            "type": "video",
            "jobid": jobid,
            "name": prop.get("name", ""),
            "otherinfo": card.get("otherInfo", ""),
            "mid": mid,
            "objectid": objectid,
            "aid": card.get("aid", ""),
            "playTime": card.get("playTime", 0),
            "rt": prop.get("rt", ""),
            "attDuration": card.get("attDuration", ""),
            "attDurationEnc": card.get("attDurationEnc", ""),
            "videoFaceCaptureEnc": card.get("videoFaceCaptureEnc", ""),
        }
    except KeyError:
        logger.warning("出现转码失败视频，已跳过...")
        return None


def _process_document_task(card: Dict[str, Any]) -> Dict[str, Any]:
    """处理文档类型任务"""
    return {
        "type": "document",
        "jobid": card.get("jobid", ""),
        "otherinfo": card.get("otherInfo", ""),
        "jtoken": card.get("jtoken", ""),
        "mid": card.get("mid", ""),
        "enc": card.get("enc", ""),
        "aid": card.get("aid", ""),
        "objectid": card.get("property", {}).get("objectid", "")
    }


def _process_work_task(card: Dict[str, Any]) -> Dict[str, Any]:
    """处理作业类型任务"""
    return {
        "type": "workid",
        "jobid": card.get("jobid", ""),
        "otherinfo": card.get("otherInfo", ""),
        "mid": card.get("mid", ""),
        "enc": card.get("enc", ""),
        "aid": card.get("aid", "")
    }


def decode_questions_info(html_content: str) -> Dict[str, Any]:
    """
    解析题目信息，提取表单数据和问题列表
    
    Args:
        html_content: 题目页面HTML内容
        
    Returns:
        包含表单数据和问题列表的字典
    """
    soup = BeautifulSoup(html_content, "lxml")
    form_data = _extract_form_data(soup)

    # 检查是否存在字体加密
    has_font_encryption = bool(soup.find("style", id="cxSecretStyle"))
    font_decoder = None

    if has_font_encryption:
        font_decoder = FontDecoder(html_content)
    else:
        logger.warning("未找到字体文件，可能是未加密的题目不进行解密")

    # 处理所有问题
    questions = []
    for div_tag in soup.find("form").find_all("div", class_="singleQuesId"):
        question = _process_question(div_tag, font_decoder)
        if question:
            questions.append(question)

    # 更新表单数据
    form_data["questions"] = questions
    form_data["answerwqbid"] = ",".join([q["id"] for q in questions]) + ","

    return form_data


def _extract_form_data(soup: BeautifulSoup) -> Dict[str, Any]:
    """从BeautifulSoup对象中提取表单数据"""
    form_data = {}
    form_tag = soup.find("form")

    if not form_tag:
        return form_data

    # 提取所有非答案字段的input
    for input_tag in form_tag.find_all("input"):
        name_attr = input_tag.attrs.get("name")
        if name_attr is None:
            continue

        if isinstance(name_attr, list):
            name_str = str(name_attr[0]) if name_attr else ""
        else:
            name_str = str(name_attr)

        if not name_str or "answer" in name_str:
            continue

        val_attr = input_tag.attrs.get("value", "")
        if isinstance(val_attr, list):
            val_str = "".join(str(v) for v in val_attr)
        else:
            val_str = str(val_attr)

        form_data[name_str] = val_str

    return form_data


def _process_question(div_tag, font_decoder=None) -> Dict[str, Any]:
    """处理单个问题"""
    # 提取问题ID和题目类型
    question_id = div_tag.attrs.get("data", "")
    q_type_code = div_tag.find("div", class_="TiMu").attrs.get("data", "")
    q_type = _get_question_type(q_type_code)

    # 提取题目内容和选项
    title_div = div_tag.find("div", class_="Zy_TItle")
    options_list = div_tag.find("ul").find_all("li") if div_tag.find("ul") else []

    # 解析题目和选项
    q_title = _extract_title(title_div, font_decoder)
    q_options = []
    for li in options_list:
        q_options.append(_extract_choices(li, font_decoder))
    # 排序选项
    q_options.sort()
    q_options = '\n'.join(q_options)

    return {
        "id": question_id,
        "title": q_title,
        "options": q_options,
        "type": q_type,
        "answerField": {
            f"answer{question_id}": "",
            f"answertype{question_id}": q_type_code,
        },
    }


def _get_question_type(type_code: str) -> str:
    """根据题型代码返回题型名称"""
    type_map = {
        "0": "single",  # 单选题
        "1": "multiple",  # 多选题
        "2": "completion",  # 填空题
        "3": "judgement",  # 判断题
        "4": "shortanswer",  # 简答题
    }

    if type_code in type_map:
        return type_map[type_code]

    logger.info(f"未知题型代码 -> {type_code}")
    return "unknown"


def _extract_title(element, font_decoder=None) -> str:
    """提取标题内容，支持解码加密字体"""
    if not element:
        return ""

    # 收集元素中的所有文本和图片
    content = []
    for item in element.descendants:
        if isinstance(item, NavigableString):
            content.append(item.string or "")
        elif item.name == "img":
            img_url = item.get("src", "")
            content.append(f'<img src="{img_url}">')

    raw_content = "".join(content)
    cleaned_content = raw_content.replace("\r", "").replace("\t", "").replace("\n", "")

    # 如果有字体解码器，进行解码
    if font_decoder:
        return font_decoder.decode(cleaned_content)

    return cleaned_content


def _extract_choices(element, font_decoder=None) -> str:
    """提取选项内容，支持解码加密字体"""
    if not element:
        return ""

    # 提取aria-label属性值作为选项，解决#474
    choice = element.get("aria-label") or element.get_text()
    if not choice:
        return ""

    cleaned_content = re.sub(r"[\r\t\n]", "", choice)

    if font_decoder:
        cleaned_content = font_decoder.decode(cleaned_content)

    cleaned_content = cleaned_content.strip()
    if cleaned_content.endswith("选择"):
        cleaned_content = cleaned_content[:-2].rstrip()

    return cleaned_content
