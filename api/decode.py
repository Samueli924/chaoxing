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


# 平台上常见的"特殊空白"字符。&nbsp;( ) 在 GBK 控制台里无法编码，
# print 时会直接抛 UnicodeEncodeError 把程序打崩（#602），统一换成普通空格。
_EXOTIC_CHARS = {
    " ": " ",   # &nbsp; 不间断空格
    " ": " ",   # 图形空格
    " ": " ",   # 窄不换行空格
    "　": " ",   # 全角空格
    "​": "",    # 零宽空格
    "‌": "",
    "‍": "",
    "﻿": "",    # BOM
}


def _sel_text(node, selector, default="") -> str:
    """安全取选择器命中的文本：页面结构变了也只是取到空，不会抛 NoneType.text"""
    try:
        found = node.select_one(selector)
    except Exception:
        return default
    if not found:
        return default
    try:
        return found.text
    except Exception:
        return default


def _sel_attr(node, selector, attr, default="") -> str:
    """安全取选择器命中的属性值（同上，不会抛 NoneType.attrs）"""
    try:
        found = node.select_one(selector)
    except Exception:
        return default
    if not found:
        return default
    try:
        value = found.attrs.get(attr, default)
    except Exception:
        return default
    if isinstance(value, list):
        value = value[0] if value else default
    return default if value is None else value


def clean_text(text) -> str:
    """清理平台返回文本里的特殊空白字符，并把连续空格压成一个"""
    if text is None:
        return ""
    text = str(text)
    for src, dst in _EXOTIC_CHARS.items():
        if src in text:
            text = text.replace(src, dst)
    return re.sub(r"[ \t\u00a0]{2,}", " ", text).strip()


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

        # 平台改版时字段可能缺失，缺了就当这条有问题跳过并记一条日志，
        # 不能让整个课程列表直接崩掉（#58 / #392 这类 KeyError / AttributeError）
        clazz_id = _sel_attr(course, "input.clazzId", "value")
        course_id = _sel_attr(course, "input.courseId", "value")
        cpi_match = re.findall(r"cpi=(.*?)&", _sel_attr(course, "a", "href"))
        title = clean_text(_sel_attr(course, "span.course-name", "title")) or clean_text(
            _sel_text(course, "span.course-name"))
        if not (clazz_id and course_id and cpi_match and title):
            logger.warning("课程条目缺少必要字段，已跳过: {}", str(course.attrs)[:200])
            continue

        course_detail = {
            "id": course.attrs.get("id", ""),
            "info": course.attrs.get("info", ""),
            "roleid": course.attrs.get("roleid", ""),
            "clazzId": clazz_id,
            "courseId": course_id,
            "cpi": cpi_match[0],
            "title": title,
            "desc": clean_text(_sel_attr(course, "p.margint10", "title")),
            "teacher": clean_text(_sel_attr(course, "p.color3", "title"))
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
        folder_id = course.attrs.get("fileid")
        if not folder_id:
            continue

        # 目录条目缺 rename-input 时跳过这一条并告警，
        # 不能让一个目录把整个课程列表读取打断
        folder_name = _sel_attr(course, "input.rename-input", "value")
        if not folder_name:
            logger.warning("课程目录条目缺少名称，已跳过: {}", str(course.attrs)[:150])
            continue

        course_folder_list.append({
            "id": folder_id,
            "rename": clean_text(folder_name),
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
        if point is None or "id" not in point.attrs:
            continue

        # id 解析不出来就跳过这一条，别用 [0] 直接 IndexError（#22 / #374）
        id_match = re.findall(r"^cur(\d{1,20})$", str(point.attrs.get("id", "")))
        if not id_match:
            logger.warning("章节点 id 异常，已跳过: {}", str(point.attrs)[:120])
            continue
        point_id = id_match[0]

        point_title = clean_text(_sel_text(point, "a.clicktitle").replace("\n", "")) or "未命名章节"

        # 提取任务数量
        job_count = 1  # 默认为1
        need_unlock = False
        hover_tips = _sel_text(point, "span.bntHoverTips")
        job_count_attr = _sel_attr(point, "input.knowledgeJobCount", "value")
        if job_count_attr:
            job_count = job_count_attr
        elif "解锁" in hover_tips:
            need_unlock = True

        # 判断是否已完成
        is_finished = "已完成" in hover_tips

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
        # 正常的学习页面一定带 mArg；取不到说明拿到的是登录页/验证码页/
        # 改版页面。标记 parseError，让上层按"读取失败"重试，
        # 绝不能当成"这个章节没有任务点"直接打勾（#223 / #357）。
        # 逐页的"找不到 mArg"不再单独记日志：新版只有第 0 页带 mArg，
        # 由 api/base.py 的 get_job_list 汇总成一条。
        return [], {"parseError": True}

    # 解析JSON数据。mArg 片段可能因为平台改版/截断而不是合法 JSON，
    # 这里必须兜住：抛出去会让整个章节失败，兜住后按"读取失败"重试更靠谱
    try:
        cards_data = json.loads("{" + temp[0] + "}")
    except (ValueError, TypeError) as e:
        logger.warning("任务点数据解析失败（mArg 不是合法 JSON）: {}", e)
        return [], {"parseError": True}

    if not cards_data:
        return [], {}

    # 提取任务信息
    job_info = _extract_job_info(cards_data)

    # 处理所有附件任务
    cards = cards_data.get("attachments", [])
    job_list, unknown_types = _process_attachment_cards(cards)
    if unknown_types:
        job_info["unknownCardTypes"] = unknown_types

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


def _process_attachment_cards(cards: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    处理所有附件任务卡片，强化直播任务识别逻辑

    Args:
        cards: 附件任务卡片列表

    Returns:
        (处理后的任务列表, 无法识别的卡片类型列表)

    平台新增任务点类型时必须让上层知道：整章卡片都不认识 → 任务列表为空，
    以前会走"空章节"分支把章节记成完成（假完成）。现在把未知类型带上去，
    由 get_job_list 按"读取失败"处理。
    """
    job_list = []
    unknown_types: List[str] = []

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

        # 根据任务类型处理
        if is_live:
            live_job = _process_live_task(card)
            if live_job:
                job_list.append(live_job)
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
            # 未知类型不能静默丢弃：整章都是未知卡片时会被误判成"空章节已完成"
            logger.error(f"Unknown card type: {card_type}")
            logger.debug(card)
            if card_type not in unknown_types:
                unknown_types.append(card_type)

    return job_list, unknown_types


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
    form_tag = soup.find("form")
    if form_tag is None:
        # 页面结构异常（最常见的是接口返回了登录页），交给上层按"无效响应"重试，
        # 不要在这里抛 NoneType.find_all 把任务打挂（#593）
        logger.warning("题目页面没有找到 form 表单，可能是登录页或页面结构变化")
        form_data["questions"] = []
        form_data["answerwqbid"] = ""
        return form_data

    for div_tag in form_tag.find_all("div", class_="singleQuesId"):
        question = _process_question(div_tag, font_decoder)
        if question:
            questions.append(question)

    # 更新表单数据
    form_data["questions"] = questions
    form_data["answerwqbid"] = ",".join([q["id"] for q in questions]) + ","

    return form_data


def _extract_form_data(soup: BeautifulSoup) -> Dict[str, Any]:
    """从BeautifulSoup对象中提取表单数据"""
    return _extract_form_fields(soup.find("form"))


def _extract_form_fields(form_tag) -> Dict[str, Any]:
    """从 form 标签里提取所有非答案字段的 input"""
    form_data = {}
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


# 任务中心作业页（mooc2/work/dowork）的题型名 -> 题型代码（与 _get_question_type 对应）
_HOMEWORK_TYPE_CODES = {
    "单选题": "0",
    "多选题": "1",
    "填空题": "2",
    "判断题": "3",
    "简答题": "4",
}


def decode_homework_page(html_content: str) -> Dict[str, Any]:
    """
    解析「任务中心 -> 作业」的作答页（mooc2/work/dowork）。

    和章节测验页（knowledge/cards 里的 TiMu/Zy_TItle）结构不同：
      * 题型在隐藏 input answertype<题目id> 的 value 里（旧页在 div.TiMu 的 data 上）
      * 题干在 h3.mark_name，选项在 div.stem_answer 的 div.answerBg（带 aria-label）
      * 提交地址在 form#submitForm 的 action 上（带 token / totalQuestionNum），
        提交接口是 addStudentWorkNewWeb，不是章节测验的 addStudentWorkNew

    返回结构和 decode_questions_info 对齐（form 隐藏字段 + questions + answerwqbid），
    额外带 form_action / form_method，供提交时原样复用。
    """
    soup = BeautifulSoup(html_content, "lxml")
    form_tag = soup.find("form", id="submitForm") or soup.find("form")
    if form_tag is None:
        logger.warning("作业页面没有找到 form 表单，可能是登录页或页面结构变化")
        return {"questions": [], "answerwqbid": ""}

    form_data = _extract_form_fields(form_tag)
    form_data["form_action"] = str(form_tag.attrs.get("action") or "")
    form_data["form_method"] = str(form_tag.attrs.get("method") or "post").lower()

    font_decoder = None
    if soup.find("style", id="cxSecretStyle"):
        font_decoder = FontDecoder(html_content)
        logger.info("作业页面有字体加密，已启用字体解密")

    questions = []
    for div_tag in form_tag.find_all("div", class_="singleQuesId"):
        question = _process_homework_question(div_tag, form_tag, font_decoder)
        if question:
            questions.append(question)

    form_data["questions"] = questions
    form_data["answerwqbid"] = (
        ",".join(q["id"] for q in questions) + "," if questions else ""
    )
    return form_data


def _extract_homework_title(div_tag, font_decoder=None) -> str:
    """
    提取作业题干。

    作业页的题干是 "<h3>1.<span>(多选题)</span><p>题干…</p></h3>"，但 <p> 嵌在
    <h3> 里属于非法 HTML，lxml 会把 <h3> 提前闭合，题干段落变成 h3 的兄弟节点。
    只取 h3 会丢题干（实测第 1 题、填空题全部丢），所以这里按 DOM 顺序拼到
    "选项区（div.stem_answer）"之前的所有文本。
    """
    parts = []
    for child in div_tag.children:
        name = getattr(child, "name", None)
        if name == "div" and "stem_answer" in (child.get("class") or []):
            break
        if name == "input":
            continue
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif name in ("h3", "p", "span", "div"):
            parts.append(_extract_title(child, font_decoder))
    return clean_text("".join(parts))


def _process_homework_question(div_tag, form_tag, font_decoder=None) -> Optional[Dict[str, Any]]:
    """解析作业页里的单道题目（新版结构）"""
    question_id = str(div_tag.attrs.get("data") or "").strip()
    if not question_id:
        return None

    type_code = ""
    type_input = form_tag.find("input", attrs={"name": f"answertype{question_id}"})
    if type_input is not None:
        type_code = str(type_input.attrs.get("value", "")).strip()
    if not type_code:
        type_name = str(div_tag.attrs.get("typeName") or "").strip()
        type_code = _HOMEWORK_TYPE_CODES.get(type_name, "")
    q_type = _get_question_type(type_code)

    q_title = _extract_homework_title(div_tag, font_decoder)

    options = []
    stem = div_tag.find("div", class_="stem_answer")
    if stem is not None:
        for option_tag in stem.find_all("div", class_="answerBg"):
            text = _extract_choices(option_tag, font_decoder)
            if text:
                options.append(text)
        if not options:
            for li in stem.find_all("li"):
                text = _extract_choices(li, font_decoder)
                if text:
                    options.append(text)
    options.sort()

    return {
        "id": question_id,
        "title": q_title,
        "options": "\n".join(options),
        "type": q_type,
        "answerField": {
            f"answer{question_id}": "",
            f"answertype{question_id}": type_code,
        },
    }


def _process_question(div_tag, font_decoder=None) -> Dict[str, Any]:
    """处理单个问题"""
    # 提取问题ID和题目类型
    question_id = div_tag.attrs.get("data", "")
    timu_tag = div_tag.find("div", class_="TiMu")
    q_type_code = timu_tag.attrs.get("data", "") if timu_tag is not None else ""
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
        "10": "completion",  # 新版填空题
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
        return clean_text(font_decoder.decode(cleaned_content))

    return clean_text(cleaned_content)


def _extract_choices(element, font_decoder=None) -> str:
    """提取选项内容，支持解码加密字体"""
    if not element:
        return ""

    # 提取aria-label属性值作为选项，解决#474
    choice = element.get("aria-label") or element.get_text() or ""

    cleaned_content = re.sub(r"[\r\t\n]", "", choice)

    if font_decoder and cleaned_content:
        cleaned_content = font_decoder.decode(cleaned_content)

    cleaned_content = clean_text(cleaned_content)
    if cleaned_content.endswith("选择"):
        cleaned_content = cleaned_content[:-2].rstrip()

    # 选项本身可能就是一张图片（电路图 / 公式图 / 结构图）：
    # 这时 aria-label 往往只有选项字母，真正的题目内容在 <img> 里。
    # 不把图片地址带上，传给题库的选项就退化成一串字母，图片题只能随机作答（#457）。
    # 只有"除了选项字母没有别的文字"时才追加，避免给普通文字选项加噪音。
    img_urls = [img.get("src", "") for img in element.find_all("img") if img.get("src")]
    if img_urls:
        bare = re.sub(r"^[A-Za-z]\s*[.、:：]?\s*", "", cleaned_content).strip()
        if not bare:
            images = " ".join(f'<img src="{url}">' for url in img_urls)
            cleaned_content = (cleaned_content + " " + images).strip()

    return cleaned_content
