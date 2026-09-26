# -*- coding: utf-8 -*-
"""
超星学习通数据解析模块

该模块负责解析超星学习通平台的课程、章节、任务点等各种数据，
并转换为程序内部使用的结构化数据格式。

网页结构随时可能调整，因此解析时尽量使用多种特征兜底：
单个课程/章节/题目解析失败只会跳过该条目，不会导致整个流程崩溃。
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, NavigableString
from bs4.exceptions import FeatureNotFound

from api.font_decoder import FontDecoder
from api.logger import logger


def _make_soup(html_text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html_text, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html_text, "html.parser")


def _attr(tag, name: str, default: str = "") -> str:
    if tag is None:
        return default
    value = tag.attrs.get(name, default)
    if isinstance(value, list):
        value = " ".join(value)
    return value if value is not None else default


def _text(tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip() if tag is not None else ""


def decode_course_list(html_text: str) -> List[Dict[str, str]]:
    """
    解析课程列表页面，提取课程信息

    Args:
        html_text: 课程列表页面的HTML内容

    Returns:
        课程信息列表，每个课程包含id、title、teacher等信息
    """
    logger.trace("开始解码课程列表...")
    soup = _make_soup(html_text)
    course_list = []

    for course in soup.select(".course"):
        # 跳过未开放课程
        if course.select_one(".not-open-tip"):
            continue

        course_id = _attr(course.select_one("input.courseId"), "value") or _attr(course, "courseid")
        clazz_id = _attr(course.select_one("input.clazzId"), "value") or _attr(course, "clazzid")
        if not course_id or not clazz_id:
            continue

        link = course.select_one("a[href*='cpi=']") or course.select_one("a")
        cpi_match = re.search(r"[?&]cpi=(\d+)", _attr(link, "href"))
        cpi = cpi_match.group(1) if cpi_match else _attr(course, "personid")
        if not cpi:
            logger.warning(f"课程 {course_id} 缺少 cpi 参数, 已跳过")
            continue

        name_tag = course.select_one("span.course-name")
        teacher_tag = course.select_one("p.color3")
        course_list.append({
            "id": _attr(course, "id"),
            "info": _attr(course, "info"),
            "roleid": _attr(course, "roleid"),
            "clazzId": clazz_id,
            "courseId": course_id,
            "cpi": cpi,
            "title": _attr(name_tag, "title") or _text(name_tag) or f"课程{course_id}",
            "desc": _attr(course.select_one("p.margint10"), "title"),
            "teacher": _attr(teacher_tag, "title") or _text(teacher_tag),
        })

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
    soup = _make_soup(html_text)
    course_folder_list = []

    for folder in soup.select("ul.file-list>li"):
        folder_id = _attr(folder, "fileid")
        if not folder_id:
            continue
        course_folder_list.append({
            "id": folder_id,
            "rename": _attr(folder.select_one("input.rename-input"), "value"),
        })

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
    soup = _make_soup(html_text)
    course_point = {
        "hasLocked": False,  # 用于判断该课程任务是否是需要解锁
        "points": [],
    }

    seen = set()
    chapter_units = soup.find_all("div", class_="chapter_unit") or [soup]
    for chapter_unit in chapter_units:
        for point in _extract_points_from_chapter(chapter_unit):
            if point["id"] in seen:
                continue
            seen.add(point["id"])
            if point.get("need_unlock", False):
                course_point["hasLocked"] = True
            course_point["points"].append(point)

    return course_point


_POINT_ID_RE = re.compile(r"^cur(\d{1,20})$")


def _extract_points_from_chapter(chapter_unit) -> List[Dict[str, Any]]:
    """
    从章节单元中提取章节点信息

    Args:
        chapter_unit: BeautifulSoup对象，表示一个章节单元

    Returns:
        章节点信息列表
    """
    point_list = []

    for point in chapter_unit.find_all(id=_POINT_ID_RE):
        point_id = _POINT_ID_RE.match(point.attrs["id"]).group(1)
        title_tag = point.select_one("a.clicktitle")
        point_title = _text(title_tag) or _attr(point, "title") or f"章节{point_id}"

        tips_text = _text(point.select_one("span.bntHoverTips"))
        job_count_input = point.select_one("input.knowledgeJobCount")
        job_count_value = _attr(job_count_input, "value")
        job_count = int(job_count_value) if job_count_value.isdigit() else 1
        need_unlock = job_count_input is None and "解锁" in tips_text

        point_list.append({
            "id": point_id,
            "title": point_title,
            "jobCount": job_count,
            "has_finished": "已完成" in tips_text,
            "need_unlock": need_unlock,
        })

    return point_list


_MARG_RE = re.compile(r"mArg\s*=\s*\{")


def _extract_marg(html_text: str) -> Optional[Dict[str, Any]]:
    """提取任务点页面中的 mArg 对象（raw_decode 可正确处理字符串中的空格、换行和 "};"）."""
    decoder = json.JSONDecoder()
    for match in _MARG_RE.finditer(html_text):
        try:
            data, _ = decoder.raw_decode(html_text, match.end() - 1)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    # 兼容旧格式
    temp = re.findall(r"mArg=\{(.*?)\};", html_text.replace(" ", ""))
    if temp:
        try:
            return json.loads("{" + temp[0] + "}")
        except json.JSONDecodeError as e:
            logger.warning(f"任务点数据解析失败: {e}")
    return None


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

    cards_data = _extract_marg(html_text)
    if not cards_data:
        return [], {}

    job_info = _extract_job_info(cards_data)
    job_list = _process_attachment_cards(cards_data.get("attachments") or [])
    return job_list, job_info


def _extract_job_info(cards_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    从卡片数据中提取任务基本信息

    Args:
        cards_data: 卡片数据字典

    Returns:
        任务基本信息字典
    """
    defaults = cards_data.get("defaults") or {}
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
        "knowledgeid": defaults.get("knowledgeid", ""),
        # 视频播放器使用 defaults.reportUrl + "/" + dtoken 上报进度
        "reportUrl": defaults.get("reportUrl", ""),
        "clazzId": defaults.get("clazzId", ""),
        "courseid": defaults.get("courseid", ""),
    }


def _process_attachment_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    处理所有附件任务卡片

    Args:
        cards: 附件任务卡片列表

    Returns:
        处理后的任务列表
    """
    job_list = []

    for card in cards:
        if not isinstance(card, dict):
            continue
        # 跳过已通过的任务
        if card.get("isPassed", False):
            continue
        # job 为 false 的附件不是任务点，网页端会直接视为已完成（阅读任务的 job 为 null，需另外处理）
        if card.get("job") is False:
            continue

        card_type = str(card.get("type", "")).lower()

        # 阅读任务：job 字段为 null，通过 type=="read" 识别
        if card_type == "read":
            read_job = _process_read_task(card)
            if read_job:
                job_list.append(read_job)
            continue

        # 一开始就把超星api的屎山处理掉，不要用一个屎山行为掩盖另一个屎山 (指根据otherInfo中是否有courseId决定url拼接方式😂)
        if "otherInfo" in card:
            card["otherInfo"] = str(card["otherInfo"]).split("&")[0]

        property_data = card.get("property") or {}
        prop_type = str(property_data.get("type", "")).lower()
        resource_type = str(property_data.get("resourceType", "")).lower()

        # 直播任务特征：包含liveId、streamName等字段，或类型标识包含live
        is_live = (
                "live" in card_type
                or "live" in prop_type
                or "live" in resource_type
                or property_data.get("liveId") is not None
                or property_data.get("streamName") is not None
                or property_data.get("vdoid") is not None
        )

        try:
            if is_live:
                job = _process_live_task(card)
            elif card_type == "video":
                job = _process_video_task(card)
            elif card_type == "document":
                job = _process_document_task(card)
            elif card_type == "workid":
                job = _process_work_task(card)
            else:
                logger.warning(f"暂不支持的任务点类型: {card_type}")
                logger.debug(card)
                job = None
        except Exception as e:
            logger.error(f"解析任务点失败: {e}, 任务数据: {str(card)[:200]}")
            job = None
        if job:
            job_list.append(job)

    return job_list


def _process_live_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理直播类型任务，提取所有必要参数"""
    property_data = card.get("property") or {}
    return {
        "type": "live",
        "jobid": card.get("jobid", str(card.get("id", ""))),  # 兼容不同格式的任务ID
        "name": property_data.get("title", property_data.get("name", "未知直播")),
        "otherinfo": card.get("otherInfo", ""),
        "property": property_data,  # 保留完整属性用于后续处理
        "mid": card.get("mid", ""),
        "objectid": card.get("objectId", ""),
        "aid": card.get("aid", ""),
        "liveId": property_data.get("liveId"),
        "streamName": property_data.get("streamName"),
    }


def _process_read_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理阅读类型任务"""
    property_data = card.get("property") or {}
    if not (card.get("type") == "read" and not property_data.get("read", False)):
        return None

    return {
        "title": property_data.get("title", ""),
        "name": property_data.get("title", ""),
        "type": "read",
        "id": property_data.get("id", ""),
        "jobid": card.get("jobid", ""),
        "jtoken": card.get("jtoken", ""),
        "mid": card.get("mid", ""),
        "otherinfo": card.get("otherInfo", ""),
        "enc": card.get("enc", ""),
        "aid": card.get("aid", ""),
    }


def _process_video_task(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理视频/音频类型任务"""
    property_data = card.get("property") or {}
    if "mid" not in card:
        logger.warning("出现转码失败视频，已跳过...")
        return None
    module = str(property_data.get("module", "")).lower()
    return {
        "type": "video",
        # 音频任务点同样以 video 类型返回，通过插件模块名区分
        "audio": "audio" in module,
        "jobid": card.get("jobid", ""),
        "name": property_data.get("name", "") or property_data.get("title", ""),
        "otherinfo": card.get("otherInfo", ""),
        "mid": card["mid"],
        "objectid": card.get("objectId", "") or property_data.get("objectid", ""),
        "aid": card.get("aid", ""),
        "playTime": card.get("playTime", 0),
        "rt": property_data.get("rt", ""),
        "attDuration": card.get("attDuration", ""),
        "attDurationEnc": card.get("attDurationEnc", ""),
        "videoFaceCaptureEnc": card.get("videoFaceCaptureEnc", ""),
    }


def _process_document_task(card: Dict[str, Any]) -> Dict[str, Any]:
    """处理文档类型任务"""
    property_data = card.get("property") or {}
    return {
        "type": "document",
        "name": property_data.get("name", "") or property_data.get("title", ""),
        "jobid": card.get("jobid", ""),
        "otherinfo": card.get("otherInfo", ""),
        "jtoken": card.get("jtoken", ""),
        "mid": card.get("mid", ""),
        "enc": card.get("enc", ""),
        "aid": card.get("aid", ""),
        "objectid": property_data.get("objectid", ""),
        "microTopicId": card.get("microTopicId", ""),
    }


def _process_work_task(card: Dict[str, Any]) -> Dict[str, Any]:
    """处理章节检测类型任务"""
    property_data = card.get("property") or {}
    return {
        "type": "workid",
        "name": property_data.get("title", "") or property_data.get("name", ""),
        "jobid": card.get("jobid", ""),
        "otherinfo": card.get("otherInfo", ""),
        "mid": card.get("mid", ""),
        "enc": card.get("enc", ""),
        "aid": card.get("aid", ""),
        # 以下字段与网页端 ananas/modules/work/index.html 构造题目地址时使用的字段一致
        "workid": property_data.get("workid", ""),
        "schoolid": property_data.get("schoolid", ""),
        "worktype": property_data.get("worktype", ""),
        "workExtInfoEnc": card.get("workExtInfoEnc", ""),
        "oriNodeId": card.get("oriNodeId", ""),
    }


def decode_questions_info(html_content: str) -> Dict[str, Any]:
    """
    解析题目信息，提取表单数据和问题列表

    Args:
        html_content: 题目页面HTML内容

    Returns:
        包含表单数据和问题列表的字典；页面中没有答题表单时 questions 为空列表
    """
    soup = _make_soup(html_content)
    form_tag = soup.find("form")
    form_data = _extract_form_data(form_tag)

    # 检查是否存在字体加密
    font_decoder = None
    if soup.find("style", id="cxSecretStyle"):
        font_decoder = FontDecoder(html_content)
        if not font_decoder.available:
            font_decoder = None
    else:
        logger.debug("未找到加密字体，题目未加密")

    questions = []
    if form_tag is not None:
        for div_tag in form_tag.find_all("div", class_="singleQuesId"):
            try:
                question = _process_question(div_tag, font_decoder)
            except Exception as e:
                logger.warning(f"解析题目失败, 已跳过: {e}")
                continue
            if question:
                questions.append(question)

    form_data["questions"] = questions
    form_data["answerwqbid"] = ",".join([q["id"] for q in questions]) + ","

    return form_data


def _extract_form_data(form_tag) -> Dict[str, Any]:
    """从表单中提取所有非答案字段"""
    form_data: Dict[str, Any] = {}
    if form_tag is None:
        return form_data

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


def _process_question(div_tag, font_decoder=None) -> Optional[Dict[str, Any]]:
    """处理单个问题"""
    question_id = _attr(div_tag, "data")
    if not question_id:
        return None
    type_tag = div_tag.find("div", class_="TiMu")
    q_type_code = _attr(type_tag, "data") if type_tag is not None else ""
    if not q_type_code:
        # 新版页面题型代码可能直接写在题目容器上
        q_type_code = _attr(div_tag, "typename") or _attr(div_tag, "data-type")
    q_type = _get_question_type(q_type_code)

    # 提取题目内容和选项
    title_div = div_tag.find("div", class_="Zy_TItle")
    options_list = div_tag.find("ul").find_all("li") if div_tag.find("ul") else []

    q_title = _extract_title(title_div, font_decoder)
    q_options = [choice for choice in (_extract_choices(li, font_decoder) for li in options_list) if choice]
    q_options.sort()

    return {
        "id": question_id,
        "title": q_title,
        "options": '\n'.join(q_options),
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
