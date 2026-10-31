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
        tip = course.select_one("a.not-open-tip, div.not-open-tip")
        tip_text = tip.get_text(strip=True) if tip else ""
        is_ended = bool(tip) and ("结束" in tip_text or "已结" in tip_text or "已结课" in tip_text)
        if tip and not is_ended and "未开放" in tip_text:
            continue

        link = course.select_one("a")
        href = link.attrs.get("href", "") if link else ""
        cpi_match = re.findall(r"(?:^|[?&])cpi=([^&]*)", href)
        cpi = cpi_match[0] if cpi_match else ""
        title_el = course.select_one("span.course-name")
        title = title_el.attrs.get("title") or title_el.get_text(strip=True) if title_el else ""

        course_detail = {
            "id": course.attrs["id"],
            "info": course.attrs["info"],
            "roleid": course.attrs["roleid"],
            "clazzId": course.select_one("input.clazzId").attrs["value"],
            "courseId": course.select_one("input.courseId").attrs["value"],
            "cpi": cpi,
            "title": title,
            "desc": course.select_one("p.margint10").attrs["title"] if course.select_one("p.margint10") else "",
            "teacher": course.select_one("p.color3").attrs["title"] if course.select_one("p.color3") else "",
            "status": "已结课" if is_ended else "进行中",
            "is_ended": is_ended,
        }
        course_list.append(course_detail)

    return course_list


def decode_archived_courses(html_text: str) -> List[Dict[str, Any]]:
    """解析归档已结课课程列表页面."""
    soup = BeautifulSoup(html_text, "lxml")
    raw_courses = soup.select(".course")
    archived_list = []

    for course in raw_courses:
        name_el = course.select_one("span.course-name, .course-name")
        clazz_input = course.select_one("input.clazzId, .clazzId")
        course_input = course.select_one("input.courseId, .courseId")
        if not name_el or not clazz_input or not course_input:
            continue

        title = name_el.attrs.get("title", name_el.get_text(strip=True))
        clazz_id = clazz_input.attrs.get("value", "")
        course_id = course_input.attrs.get("value", "")
        link = course.select_one("a")
        href = link.attrs.get("href", "") if link else ""
        cpi_match = re.findall(r"(?:^|[?&])cpi=([^&]*)", href)
        cpi = cpi_match[0] if cpi_match else ""

        teacher_el = course.select_one("p.color3")
        desc_el = course.select_one("p.margint10")

        archived_list.append({
            "id": course.attrs.get("id", f"c_{course_id}"),
            "info": course.attrs.get("info", ""),
            "roleid": course.attrs.get("roleid", ""),
            "clazzId": clazz_id,
            "courseId": course_id,
            "cpi": cpi,
            "title": f"{title}(已归档)" if not title.endswith("(已归档)") else title,
            "desc": desc_el.attrs.get("title") or (desc_el.get_text(strip=True) if desc_el else ""),
            "teacher": teacher_el.attrs.get("title") or (teacher_el.get_text(strip=True) if teacher_el else ""),
            "status": "已结课",
            "is_ended": True,
        })
    return archived_list


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


_PROGRESS_BAR_REGEX = re.compile(
    r'class="catalog_ressbar_width"[^>]*style="[^"]*width:\s*(\d+)%|style="[^"]*width:\s*(\d+)%"[^>]*class="catalog_ressbar_width"'
)


_TASK_STAT_REGEX = re.compile(r'完成任务点[^\d]*<span[^>]*>(\d+)</span>\s*/\s*(\d+)')


def parse_course_progress(html_text: str, soup: Optional[BeautifulSoup] = None) -> Tuple[int, int, int]:
    """解析章节页任务点统计、章节完成状态与进度百分比."""
    if soup is None:
        soup = BeautifulSoup(html_text, "lxml")

    has_locked = any("解锁" in tip.get_text() for tip in soup.select("span.bntHoverTips"))
    max_pct = 99 if has_locked else 100

    m = _TASK_STAT_REGEX.search(html_text)
    if m:
        fin = int(m.group(1))
        tot = int(m.group(2))
        if tot == 0:
            return 0, 0, max_pct
        if fin >= tot:
            return fin, tot, max_pct
        return fin, tot, min(99, round(fin / tot * 100))

    bar_m = _PROGRESS_BAR_REGEX.search(html_text)
    bar_pct = int(bar_m.group(1) or bar_m.group(2)) if bar_m else None

    lis = [li for li in soup.select("div.chapter_unit li") if li.find("ul") is None]
    if lis:
        has_any_job = any(
            li.select_one("input.knowledgeJobCount") or li.select_one("span.bntHoverTips")
            for li in lis
        )
        if not has_any_job:
            return 0, 0, max_pct
        tot = len(lis)
        fin = sum(
            1 for li in lis
            if "已完成" in li.get_text() or li.select_one(".icon_yiwanc, .icon-finish, .icon-chuangguan-ok")
        )
        if fin >= tot or bar_pct == 100:
            return fin, tot, max_pct
        return fin, tot, min(99, round(fin / tot * 100))

    if bar_pct is not None:
        return 0, 0, min(max_pct, bar_pct)

    return 0, 0, max_pct


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

    _, tot, pct = parse_course_progress(html_text, soup=soup)
    stat_m = _TASK_STAT_REGEX.search(html_text)
    course_point["page_finished"] = int(stat_m.group(1)) if stat_m else 0
    course_point["page_total"] = int(stat_m.group(2)) if stat_m else 0
    has_progress_indicator = bool(
        tot > 0
        or _PROGRESS_BAR_REGEX.search(html_text)
        or course_point["points"]
        or "完成任务点" in html_text
        or soup.select("div.chapter_unit li")
    )
    if not has_progress_indicator:
        course_point["progress"] = 0
        course_point["is_finished"] = False
    else:
        course_point["progress"] = pct
        course_point["is_finished"] = pct >= 100 and not course_point["hasLocked"]
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
        # 父级任务节点只是折叠容器，本身没有任务点，计入学任务会虚增章节总数
        if raw_point.find("ul") is not None:
            continue

        point = raw_point.div
        if not point or "id" not in point.attrs:
            continue

        id_match = re.findall(r"^cur(\d{1,20})$", str(point.attrs["id"]))
        if not id_match:
            continue
        point_id = id_match[0]
        title_el = point.select_one("a.clicktitle")
        point_title = title_el.text.replace("\n", "").strip() if title_el else ""

        # 提取任务数量
        job_count = 1  # 默认为1
        need_unlock = False
        if point.select_one("input.knowledgeJobCount"):
            job_count = point.select_one("input.knowledgeJobCount").attrs["value"]
        elif point.select_one("span.bntHoverTips") and "解锁" in point.select_one("span.bntHoverTips").text:
            need_unlock = True

        # 判断是否已完成
        is_finished = False
        if (
            (point.select_one("span.bntHoverTips") and "已完成" in point.select_one("span.bntHoverTips").text)
            or point.select_one(".icon_yiwanc, .icon-finish, .icon-chuangguan-ok")
        ):
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


def decode_course_card(html_text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
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
    job_list = _process_attachment_cards(cards)

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


def _process_attachment_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    处理所有附件任务卡片，强化直播任务识别逻辑
    
    Args:
        cards: 附件任务卡片列表
        
    Returns:
        处理后的任务列表
    """
    job_list = []

    for index, card in enumerate(cards):
        # 跳过已通过的任务
        if card.get("isPassed", False):
            continue

        # 处理无job字段的特殊任务
        if card.get("job") is None:
            # 尝试识别阅读任务
            read_job = _process_read_task(card)
            if read_job:
                job_list.append(read_job)
            continue

        # 一开始就把超星api的屎山处理掉，不要用一个屎山行为掩盖另一个屎山 (指根据otherInfo中是否有courseId决定url拼接方式😂)
        # 清理otherInfo字段中的无效参数，这里优化了一下(保留了作者原来的注释TAT）
        if "otherInfo" in card:
            logger.trace("Fixing other info...")
            card["otherInfo"] = card["otherInfo"].split("&")[0]
            logger.trace(f"New info: {card['otherInfo']}")

        # 多维度判断是否为直播任务
        card_type = card.get("type", "").lower()
        property_data = card.get("property", {})
        prop_type = property_data.get("type", "").lower()
        resource_type = property_data.get("resourceType", "").lower()

        # 直播任务特征：包含liveId、streamName等字段，
        # 或类型标识包含live（因为live和video有点类似，怕超星又搞出什么幺蛾子就加了一些关键字识别）
        is_live = (
                "live" in card_type
                or "live" in prop_type
                or "live" in resource_type
                or "livestream" in card_type
                or property_data.get("liveId") is not None
                or property_data.get("streamName") is not None
                or property_data.get("vdoid") is not None
        )

        is_topic = (
            card_type in ("topic", "bbs", "discuss")
            or prop_type in ("topic", "bbs", "discuss")
            or resource_type in ("topic", "bbs", "discuss")
            or "bbs" in property_data.get("module", "").lower()
            or "topic" in property_data.get("module", "").lower()
            or property_data.get("module") in ("topic", "bbs", "discuss", "insertbbs")
            or property_data.get("topicId") is not None
        )

        is_vote = (
            card_type in ("vote", "insertvote")
            or prop_type in ("vote", "insertvote")
            or resource_type in ("vote", "insertvote")
            or property_data.get("module") in ("vote", "insertvote")
        )

        # 根据任务类型处理
        if is_live:
            live_job = _process_live_task(card)
            if live_job:
                job_list.append(live_job)
        elif is_topic:
            topic_job = _process_topic_task(card)
            if topic_job:
                job_list.append(topic_job)
        elif is_vote:
            vote_job = _process_vote_task(card)
            if vote_job:
                job_list.append(vote_job)
        elif card_type == "video":
            video_job = _process_video_task(card)
            if video_job:
                job_list.append(video_job)
        elif card_type == "document":
            doc_job = _process_document_task(card)
            if doc_job:
                job_list.append(doc_job)
        elif card_type == "workid":
            work_job = _process_work_task(card)
            if work_job:
                job_list.append(work_job)
        else:
            logger.warning(f"Unknown card type: {card_type}")
            logger.warning(card)

    return job_list


def _process_topic_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """提取话题回复讨论任务所需参数."""
    try:
        property_data = card.get("property", {})
        topic_id = property_data.get("id") or property_data.get("topicId") or card.get("topicId", "")
        topic_uuid = property_data.get("uuid") or card.get("uuid", "")
        bbsid = property_data.get("bbsid") or property_data.get("bbsId") or card.get("bbsid", "")
        title = property_data.get("title") or property_data.get("name") or card.get("title", "话题讨论")

        return {
            "type": "topic",
            "jobid": card.get("jobid", str(card.get("id", ""))),
            "title": title,
            "topic_id": str(topic_id),
            "topic_uuid": str(topic_uuid),
            "bbsid": str(bbsid),
            "content": property_data.get("content", ""),
            "otherinfo": card.get("otherInfo", ""),
            "property": property_data,
            "mid": str(card.get("mid") or property_data.get("mid", "")),
            "aid": card.get("aid", ""),
        }
    except Exception as e:
        logger.error(f"解析话题任务失败: {e}")
        return None


def _process_vote_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """提取随堂问答投票任务所需参数."""
    try:
        property_data = card.get("property", {})
        active_id = str(property_data.get("id") or property_data.get("activeId") or card.get("id", ""))
        title = property_data.get("title") or card.get("title", "随堂问答")

        return {
            "type": "vote",
            "jobid": card.get("jobid", str(card.get("id", ""))),
            "title": title,
            "active_id": active_id,
            "jtoken": card.get("jtoken", ""),
            "mid": str(card.get("mid") or property_data.get("mid", "")),
            "enc": card.get("enc", ""),
            "otherinfo": card.get("otherInfo", ""),
            "property": property_data,
            "aid": card.get("aid", ""),
        }
    except Exception as e:
        logger.error(f"解析投票任务失败: {e}")
        return None


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
        return {
            "type": "video",
            "jobid": card.get("jobid", ""),
            "name": card.get("property", {}).get("name", ""),
            "otherinfo": card.get("otherInfo", ""),
            "mid": card["mid"],  # 必须字段，如果不存在会抛出异常
            "objectid": card.get("objectId", ""),
            "aid": card.get("aid", ""),
            "playTime": card.get("playTime", 0),
            "rt": card.get("property", {}).get("rt", ""),
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
