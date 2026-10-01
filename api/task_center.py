# -*- coding: utf-8 -*-
"""任务中心「教学任务」支持（task.chaoxing.com 任务引擎）."""
#
# 【为什么需要单独一套逻辑】
# 新版泛雅课程首页的「任务中心」里，老师可以发布"教学任务"。它和「章节」是
# 两套互相独立的学习入口：
# * 章节   -> mooc1.chaoxing.com/mooc-ans/knowledge/cards（老接口）
# * 教学任务 -> task.chaoxing.com 的任务引擎，任务点按"分组"解锁，
# 完成上一组才允许学下一组
#
# 教学任务的每个任务点（plan）有自己的类型：
# 4  作业        8  章节        9  思考题      10 视频
# 11 文档        14 主题讨论    15 AI实践
# 本模块能自动完成其中的 视频 / 文档 / AI实践 / 作业；章节同步见 main.py 的编排：
# * 视频：任务引擎自带播放器，上报接口 /videoDataLog/dataLog/{总时长}/{当前秒}/{状态}
# 有"观看时长"要求（enableVideoWatchDuration + N 分钟）时按 1 倍速真实播放，
# 不够就回看；只要求"播完"时可用配置倍速。
# * 文档：阅读器每 30 秒向 data-xxt 上报一次 readPoint，服务端据此累计阅读时长，
# 凑够 documentWatchDuration 分钟后按需调 /documentStudy/readEnd。
# * 章节：任务点里带 knowledgeId，但通过平台返回的 stuJobInfo 同步完成状态。
# * 作业：任务引擎的学习页是 mooc2/work/dowork（新版结构），提交接口
# addStudentWorkNewWeb；选择题/判断题/填空题走题库，简答题走 ai_writer，
# 提交前走统一确认门禁（章节测验的 api/work 接口对课程级作业返回 403，不能复用）。
# * 主题讨论：groupweb 话题详情页 → 读已有回复做风格参考 → ai_writer 生成回复 →
# POST /pc/invitation/{topicUuid}/addReplys；文本有硬伤（编造经历等）直接不提交。
# 其余类型（思考题）目前不做，会明确写日志提示手动完成，绝不会假装成功。
#
# 接口全部是只读探测出来的，任何一步失败都只影响该任务点，不会影响章节刷课。

import hashlib
import json
import os
import re
import sys
import time
from enum import Enum
from typing import Any, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import uuid4

from api import interrupt, paths, review
from api.display import answer_line, answers_header, clip, emit, emit_block
from api.ai_writer import HumanLikeWriter
from api.base import (
    SessionManager,
    best_option_by_similarity,
    build_completion_fields,
    build_multiple_answer,
    clean_res,
    is_subsequence,
    multi_cut,
    random_answer,
)
from api.decode import decode_homework_page
from api.logger import logger

# 任务引擎 / 泛雅课程页
TASK_BASE = "https://task.chaoxing.com"
MOOC_BASE = "https://mooc2-ans.chaoxing.com"
# 主题讨论在 groupweb（话题详情页 + 回复列表/发回复接口）
DISCUSSION_BASE = "https://groupweb.chaoxing.com"
CHAPTER_SCORE_URL = f"{TASK_BASE}/userStudyPlan/autoPullChapterScore"

# 任务点类型
PLAN_TYPE_HOMEWORK = 4
PLAN_TYPE_CHAPTER = 8
PLAN_TYPE_QUESTION = 9
PLAN_TYPE_VIDEO = 10
PLAN_TYPE_DOCUMENT = 11
PLAN_TYPE_DISCUSS = 14
PLAN_TYPE_AI = 15

PLAN_TYPE_NAMES = {
    PLAN_TYPE_HOMEWORK: "作业",
    PLAN_TYPE_CHAPTER: "章节",
    PLAN_TYPE_QUESTION: "思考题",
    PLAN_TYPE_VIDEO: "视频",
    PLAN_TYPE_DOCUMENT: "文档",
    PLAN_TYPE_DISCUSS: "主题讨论",
    PLAN_TYPE_AI: "AI实践",
}

# 目前能自动完成且能由任务中心状态复查的类型。
# 章节类型现在能打通：刷 mooc 章节时带 courseEngineInfo，平台下发 stuJobInfo 后
# 调 autoPullChapterScore，最后用 isFinish 复查。
# 作业： 读取学习页与提交表单（mooc2/work/dowork +
# addStudentWorkNewWeb），按"接口业务成功 + 任务中心状态复查"接入。
# 思考题暂不支持，不能按完成处理。
SUPPORTED_PLAN_TYPES = {
    PLAN_TYPE_CHAPTER, PLAN_TYPE_VIDEO, PLAN_TYPE_DOCUMENT, PLAN_TYPE_AI,
    PLAN_TYPE_HOMEWORK, PLAN_TYPE_DISCUSS,
}

# 同一任务点提交后的本地去重窗口（秒）。
# 平台完成状态有延迟（作业实测 8 秒~1 分钟，其他类型更久），
# 重复运行不能因此把同一份作业/讨论再提交一遍。
SUBMISSION_LEDGER_TTL = 6 * 3600

# 文档任务点尝试记录窗口（秒）。实测 10 分钟文档连打 600 秒 + readEnd 后平台仍不计入，
# 24 小时内不重复消耗真实阅读时间；如果平台之后计入了，任务状态复查会直接通过。
DOCUMENT_ATTEMPT_TTL = 24 * 3600

# 视频打点的间隔（秒）。和任务引擎网页播放器保持一致：每 6 秒一个点。
VIDEO_DOT_INTERVAL = 6

# 文档阅读打点：阅读器每 30 秒向 data-xxt 上报一次阅读点，服务端按它累计阅读时长
READ_POINT_URL = "https://data-xxt.aichaoxing.com/analysis/ac_mark"
READ_POINT_INTERVAL = 30
# addPoint.js 的 ac_mark 签名盐（由已脱敏的浏览器样例复核）。
READ_POINT_ENC_SALT = "NrRzLDpWB2JkeodIVAn4"
# 浏览器从 pan-yz 跨域发起 XHR 时会带的最小请求头。data-xxt 对没有来源的
# 请求仍可能返回 HTTP 200，但不一定把它计入阅读时长，因此不能只依赖状态码。
READ_POINT_HEADERS = {
    "Accept": "*/*",
    "Referer": "https://pan-yz.chaoxing.com/",
}
# 任务中心前端 request.js 对章节成绩同步使用 JSON 请求体。
CHAPTER_SCORE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json; charset=UTF-8",
}

# AI 实践（思维阶梯）接口。入口页会 302 到带 aiEnc 的 SPA，后续接口必须使用
# SPA 地址里的 aiEnc；不能从课程或任务 ID 自行推导。
AI_INIT_URL = f"{MOOC_BASE}/mooc2-ans/ai-evaluate/v2/answer/init"
AI_LOAD_DATA_URL = f"{MOOC_BASE}/mooc2-ans/ai-evaluate/v2/answer/load-data"
AI_SUBMIT_URL = f"{MOOC_BASE}/mooc2-ans/ai-evaluate/v2/answer/submit"
AI_TALK_URL = f"{MOOC_BASE}/ai-ans/ai-evaluate/think/main-talk"
# 提交之后平台**不会自动评估**：成绩是学生点"学习质量评估报告"时由这个接口现算的。
# 实测提交后 10 分钟 answerRecords 里都没有分数，调一次 end-report 立刻出分。
AI_END_REPORT_URL = f"{MOOC_BASE}/ai-ans/ai-evaluate/think/end-report"
AI_FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
AI_STREAM_HEADERS = {
    "Accept": "text/event-stream",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

# SessionManager 有一个较短的默认超时；AI 对话首包和流式回答可能更久，
# 这里显式给任务中心请求设置上限，避免把正常的 SSE 等待误判成平台失败。
TASK_CENTER_TIMEOUT = 20
AI_STREAM_TIMEOUT = (10, 180)

SUBMIT_MODES = ("confirm", "auto")


class TaskOutcome(str, Enum):
    """任务中心任务点的明确状态，避免把跳过/等待显示成完成."""

    COMPLETED = "completed"
    WAITING_CONFIRMATION = "waiting_confirmation"
    LOCKED = "locked"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


def normalize_submit_mode(value: Any) -> str:
    """提交模式只允许 confirm/auto；默认 auto（后台自动提交），错误值也回到 auto."""
    #
    # auto = 作答完成后直接提交（适合挂后台刷课，用户要求默认值）；
    # confirm = 提交前显示预览并询问（需要人工盯着时显式配置）。
    mode = str(value or "auto").strip().lower()
    return mode if mode in SUBMIT_MODES else "auto"


def _api_success(value: Any) -> bool:
    """兼容泛雅接口常见的 true / 1 / "1" 成功表示，拒绝任意非空字符串."""
    if value is True or value == 1:
        return True
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"}


def _browser_timestamp(now: Optional[float] = None) -> str:
    """生成阅读器使用的本地时间戳：yyyyMMddHHmmssSSS."""
    if now is None:
        now = time.time()
    second_part = time.strftime("%Y%m%d%H%M%S", time.localtime(now))
    millis = int(now * 1000) % 1000
    return f"{second_part}{millis:03d}"


def _encode_uri_component(value: str) -> str:
    """等价于浏览器的 encodeURIComponent（包括其安全字符集合）."""
    return quote(value, safe="-_.!~*'()")


def _read_point_enc(params: dict) -> str:
    """按云盘阅读器 addPoint.js 的规则计算 ac_mark.enc."""
    #
    # 浏览器先对 d 做 encodeURIComponent，再按参数名排序拼接所有字符串参数，
    # 最后追加固定盐并取 MD5。requests 收到未编码的 d 后会在发送时编码一次，
    # 因而这里不能把已编码的 d 再放回 params，否则会在网络层双重编码。
    values = {
        key: (_encode_uri_component(value) if key == "d" else value)
        for key, value in params.items()
        if key != "enc" and isinstance(value, str)
    }
    material = "".join(values[key] for key in sorted(values))
    return hashlib.md5((material + READ_POINT_ENC_SALT).encode("utf-8"), usedforsecurity=False).hexdigest()


def _extract_json_object(text: str, marker: str) -> Optional[dict]:
    """从网页里抠出 "const xxx = {...}" 这种内嵌 JSON（页面里往往一整个对象都在）."""
    start = text.find(marker)
    if start < 0:
        return None
    brace = text.find("{", start)
    if brace < 0:
        return None
    try:

        obj, _ = json.JSONDecoder().raw_decode(text[brace:])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _extract_discussion_topic(page_html: str) -> dict:
    """从话题详情页里取 urlToken / 标题 / 正文."""
    #
    # window.obj.topic 是 JS 字面量（不是严格 JSON，带注释和未加引号的键），
    # 所以先定位 topic:{ 片段再用正则取字段，不做整段 JSON 解析。
    info = dict.fromkeys(("url_token", "title", "content", "user_puid"), str())
    matched = re.search(r"urlToken\s*:\s*['\"]([^'\"]+)['\"]", page_html or "")
    if matched:
        info["url_token"] = matched.group(1)
    matched = re.search(r"user:\{[^}]*?\"puid\"\s*:\s*\"?(\d+)\"?", page_html or "")
    if matched:
        info["user_puid"] = matched.group(1)
    index = (page_html or "").find("topic:{")
    blob = page_html[index:index + 4000] if index >= 0 else (page_html or "")
    for key in ("title", "content"):
        matched = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % key, blob)
        if not matched:
            continue
        try:
            info[key] = json.loads('"' + matched.group(1) + '"')
        except ValueError:
            info[key] = matched.group(1)
    return info


def _sse_events(lines, report=False):
    """Yield JSON events while accepting report events split across lines."""
    pending = ""
    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.strip()
        if not line or (not report and not line.startswith("data:")):
            continue
        payload = line[5:].strip() if line.startswith("data:") else line
        if payload == "[DONE]":
            if report:
                break
            continue
        payload = pending + payload if report else payload
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except (TypeError, ValueError):
            pending = payload if report else ""
            continue
        pending = ""
        if isinstance(event, dict):
            yield event


def _sse_content(event):
    """Normalize event content without dropping numeric or structured values."""
    content = event.get("content", "")
    if content is None:
        return ""
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


class TaskCenter:
    """任务中心客户端：读取教学任务 + 完成任务点."""

    #
    # ``study_video`` / ``study_document`` 保持历史 bool 返回值，供旧调用方继续使用。
    # 新增任务类型会同时更新 ``last_outcome``，编排层据此区分失败、锁定和等待确认。
    # ``writer`` 与 ``confirm_callback`` 可注入，既方便离线测试，也避免把提交确认和
    # 具体终端耦合在网络客户端里。

    def __init__(
        self,
        chaoxing: Any,
        config: Optional[dict] = None,
        writer: Optional[HumanLikeWriter] = None,
        confirm_callback=None,
    ):
        """Initialize configuration and runtime state."""
        self.chaoxing = chaoxing
        self.config = config or {}
        try:
            speed = float(self.config.get("speed", 1.0) or 1.0)
        except (TypeError, ValueError):
            speed = 1.0
        # 任务引擎的视频倍速不高于页面可选的 2 倍
        self.speed = max(1.0, min(2.0, speed))
        self.submit_mode = normalize_submit_mode(self.config.get("task_center_submit_mode"))
        try:
            self.ai_practice_min_score = float(
                self.config.get("ai_practice_min_score", 85) or 85
            )
        except (TypeError, ValueError):
            self.ai_practice_min_score = 85.0
        self.ai_practice_min_score = max(0.0, min(100.0, self.ai_practice_min_score))
        try:
            self.ai_practice_max_rounds = int(
                float(self.config.get("ai_practice_max_rounds", 5) or 5)
            )
        except (TypeError, ValueError):
            self.ai_practice_max_rounds = 5
        self.ai_practice_max_rounds = max(1, min(20, self.ai_practice_max_rounds))
        writer_config = self.config.get("tiku_config") or self.config.get("_tiku_config")
        self.writer = writer if writer is not None else HumanLikeWriter(writer_config)
        self.confirm_callback = (
            confirm_callback
            if confirm_callback is not None
            else self.config.get("task_center_confirm")
        )
        self.last_outcome = TaskOutcome.FAILED
        self.waiting_confirmation = False
        self.last_read_failed = False
        self.last_plan_read_failed = False
        self.session = SessionManager.get_session()

    def _set_outcome(self, outcome: TaskOutcome):
        self.last_outcome = outcome
        if outcome == TaskOutcome.WAITING_CONFIRMATION:
            self.waiting_confirmation = True

    def confirm_submission(self, kind: str, preview: str = "") -> bool:
        """提交前的统一门禁."""
        #
        # confirm 模式在无交互终端中直接安全停止；只有明确输入 y/yes 才会继续。
        # 该门禁只用于会改变课程记录的提交动作，视频/文档打点和状态读取不受影响。
        if self.submit_mode == "auto":
            return True

        preview = str(preview or "").strip()
        if len(preview) > 600:
            preview = preview[:600] + "…"

        if callable(self.confirm_callback):
            try:
                allowed = bool(self.confirm_callback(kind, preview))
            except Exception as e:
                logger.warning("{}提交确认回调失败，按取消处理: {}", kind, e)
                allowed = False
            if not allowed:
                self._set_outcome(TaskOutcome.WAITING_CONFIRMATION)
            return allowed

        is_tty = getattr(sys.stdin, "isatty", lambda: False)()
        if not is_tty:
            logger.warning(
                "{}需要人工确认，但当前不是交互终端；为安全起见不提交。",
                kind,
            )
            self._set_outcome(TaskOutcome.WAITING_CONFIRMATION)
            return False

        print("\n  ── 任务中心提交确认 ──")
        print(f"  类型：{kind}")
        if preview:
            print("  内容预览：" + preview.replace("\n", " "))
        try:
            # 键盘监听线程（api/interrupt.py）一直在读 stdin：不先让它让开，
            # input() 会收到被吃掉字符的碎片（实测 "yes" → "ye"/"ys" 被当取消），
            # 甚至永久挂住；而且终端还在 cbreak 模式，用户看不到自己敲了什么。
            with interrupt.stdin_for_prompt():
                answer = input("  确认提交？输入 y/yes 继续，其他输入取消：")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if str(answer).strip().lower() in {"y", "yes"}:
            return True
        logger.info("{}提交已取消，本次不记为完成。", kind)
        self._set_outcome(TaskOutcome.WAITING_CONFIRMATION)
        return False

    # ------------------------------------------------------------------ 读取

    def get_course_tasks(self, course: dict) -> list:
        """课程的教学任务列表（任务中心 -> 教学任务）."""
        self.last_read_failed = False
        params = {
            "courseId": course.get("courseId", ""),
            "clazzId": course.get("clazzId", ""),
            "cpi": course.get("cpi", ""),
        }
        try:
            resp = self.session.get(
                f"{MOOC_BASE}/mooc2-ans/fanya3/s/taskSignupList", params=params,
                timeout=TASK_CENTER_TIMEOUT,
            )
            if getattr(resp, "status_code", 0) != 200:
                logger.warning(
                    "《{}》教学任务列表读取失败: HTTP {}",
                    course.get("title", "?"), getattr(resp, "status_code", "?"),
                )
                self.last_read_failed = True
                return []
            data = resp.json()
        except Exception as e:
            logger.warning("教学任务列表读取失败: {} - {}", course.get("title", "?"), e)
            self.last_read_failed = True
            return []

        if not isinstance(data, dict) or not _api_success(data.get("status")):
            self.last_read_failed = True
            if not isinstance(data, dict):
                logger.warning("《{}》教学任务列表返回结构异常", course.get("title", "?"))
                return []
            msg = str(data.get("msg", ""))
            if "无权限" in msg:
                logger.info(
                    "《{}》没有教学任务或当前账号无权限（课程可能不属于该账号）",
                    course.get("title", "?"),
                )
            else:
                logger.warning("《{}》教学任务列表读取失败: {}", course.get("title", "?"), msg)
            return []
        items = data.get("data")
        if not isinstance(items, list):
            self.last_read_failed = True
            logger.warning("《{}》教学任务列表 data 不是列表，按失败处理", course.get("title", "?"))
            return []
        return items

    def open_task(self, task: dict) -> Optional[dict]:
        """进入教学任务，拿到 encryTaskUserId / encryTaskId（后续接口都要带）."""
        try:
            resp = self.session.get(
                f"{TASK_BASE}/api/v1/middlePageApi/jumpStudyPlanList",
                params={"taskId": task.get("id", "")},
                timeout=TASK_CENTER_TIMEOUT,
            )
        except Exception as e:
            logger.warning("教学任务打开失败: {} - {}", task.get("name", "?"), e)
            self._set_outcome(TaskOutcome.FAILED)
            return None
        if resp.status_code != 200:
            logger.warning("教学任务打开失败: {} HTTP {}", task.get("name", "?"), resp.status_code)
            self._set_outcome(TaskOutcome.FAILED)
            return None
        user_id = re.search(r'const eTaskUserId\s*=\s*"([^"]+)"', resp.text)
        if not user_id:
            logger.warning("教学任务页面结构变化，未取到 encryTaskUserId: {}", task.get("name", "?"))
            self._set_outcome(TaskOutcome.FAILED)
            return None
        task_id = re.search(r'const encryTaskId\s*=\s*"([^"]+)"', resp.text)
        return {
            "encryTaskUserId": user_id.group(1),
            "encryTaskId": task_id.group(1) if task_id else "",
        }

    def get_groups(self, encry_task_user_id: str) -> Optional[list]:
        """任务分组：只有 groupAllowStudy=True 的分组才允许学习（顺序解锁）."""
        try:
            resp = self.session.post(
                f"{TASK_BASE}/userStudyPlan/getGroupData",
                params={"encryTaskUserId": encry_task_user_id},
                timeout=TASK_CENTER_TIMEOUT,
            )
            if getattr(resp, "status_code", 0) != 200:
                logger.warning("教学任务分组读取失败: HTTP {}", getattr(resp, "status_code", "?"))
                self._set_outcome(TaskOutcome.FAILED)
                return None
            data = resp.json()
        except Exception as e:
            logger.warning("教学任务分组读取失败: {}", e)
            self._set_outcome(TaskOutcome.FAILED)
            return None
        if not isinstance(data, dict) or not _api_success(data.get("result")):
            if not isinstance(data, dict):
                logger.warning("教学任务分组返回结构异常")
                self._set_outcome(TaskOutcome.FAILED)
                return None
            logger.warning("教学任务分组读取失败: {}", data.get("message"))
            self._set_outcome(TaskOutcome.FAILED)
            return None
        items = data.get("data")
        if not isinstance(items, list):
            logger.warning("教学任务分组 data 不是列表，按失败处理")
            self._set_outcome(TaskOutcome.FAILED)
            return None
        return items

    def get_plans(self, encry_task_user_id: str, encry_group_id: str) -> list:
        """分组里的任务点."""
        self.last_plan_read_failed = False
        try:
            resp = self.session.post(
                f"{TASK_BASE}/userStudyPlan/getPlanDataByGroupId",
                params={
                    "encryTaskUserId": encry_task_user_id,
                    "encryGroupId": encry_group_id,
                },
                timeout=TASK_CENTER_TIMEOUT,
            )
            if getattr(resp, "status_code", 0) != 200:
                logger.warning("教学任务点读取失败: HTTP {}", getattr(resp, "status_code", "?"))
                self.last_plan_read_failed = True
                self._set_outcome(TaskOutcome.FAILED)
                return []
            data = resp.json()
        except Exception as e:
            logger.warning("教学任务点读取失败: {}", e)
            self.last_plan_read_failed = True
            self._set_outcome(TaskOutcome.FAILED)
            return []
        if not isinstance(data, dict) or not _api_success(data.get("result")):
            self.last_plan_read_failed = True
            if not isinstance(data, dict):
                logger.warning("教学任务点返回结构异常")
                self._set_outcome(TaskOutcome.FAILED)
                return []
            logger.warning("教学任务点读取失败: {}", data.get("message"))
            self._set_outcome(TaskOutcome.FAILED)
            return []
        items = data.get("data")
        if not isinstance(items, list):
            self.last_plan_read_failed = True
            logger.warning("教学任务点 data 不是列表，按失败处理")
            self._set_outcome(TaskOutcome.FAILED)
            return []
        return items

    def get_study_url(self, encry_task_user_id: str, encrypt_plan_id: str) -> Optional[str]:
        """任务点的学习地址；未解锁时接口会返回「任务点未解锁，不允许学习」."""
        try:
            resp = self.session.post(
                f"{TASK_BASE}/userStudyPlan/getToStudyUrl",
                params={
                    "encryptPlanId": encrypt_plan_id,
                    "encryTaskUserId": encry_task_user_id,
                    "studyJumpType": 0,
                    "isInterface": "false",
                },
                timeout=TASK_CENTER_TIMEOUT,
            )
            if getattr(resp, "status_code", 0) != 200:
                logger.warning("任务点学习地址获取失败: HTTP {}", getattr(resp, "status_code", "?"))
                self._set_outcome(TaskOutcome.FAILED)
                return None
            data = resp.json()
        except Exception as e:
            logger.warning("任务点学习地址获取失败: {}", e)
            self._set_outcome(TaskOutcome.FAILED)
            return None
        if not isinstance(data, dict) or not _api_success(data.get("result")):
            if not isinstance(data, dict):
                logger.warning("任务点学习地址返回结构异常")
                self._set_outcome(TaskOutcome.FAILED)
                return None
            message = str(data.get("message", ""))
            if "未解锁" in message or "不允许学习" in message:
                self._set_outcome(TaskOutcome.LOCKED)
            else:
                self._set_outcome(TaskOutcome.FAILED)
            logger.info("任务点暂不可学（多半是上一组还没完成）: {}", message)
            return None
        result = data.get("data")
        if not isinstance(result, dict):
            logger.warning("任务点学习地址 data 不是对象，按失败处理")
            self._set_outcome(TaskOutcome.FAILED)
            return None
        url = result.get("url")
        if not url:
            self._set_outcome(TaskOutcome.FAILED)
        return url

    @staticmethod
    def plan_finished(plan: dict) -> bool:
        """任务点是否已完成."""
        if not isinstance(plan, dict):
            return False
        if _api_success(plan.get("isFinish")):
            return True
        plan_user = plan.get("planUser")
        return isinstance(plan_user, dict) and _api_success(plan_user.get("finish"))

    def is_plan_finished(
        self, encry_task_user_id: str, encry_group_id: str, plan_id: Any
    ) -> bool:
        """重新拉一次任务点，确认是否真的完成了."""
        for plan in self.get_plans(encry_task_user_id, encry_group_id):
            if str(plan.get("planId")) == str(plan_id):
                return self.plan_finished(plan)
        return False

    @staticmethod
    def chapter_sync_payload(encry_task_user_id: str, chapter_data: dict) -> dict:
        """按任务中心网页格式组装章节成绩同步请求体."""
        #
        # 任务中心页面在查询参数里会使用编码后的变量，但
        # ``autoPullChapterScore`` 的 JSON 体实际使用原始 ``eTaskUserId``。
        # 这里必须保留 ``open_task`` 返回的原值；requests 会负责 HTTP 层编码。
        return {
            "encryTaskUserId": str(encry_task_user_id or ""),
            "uid": chapter_data.get("uid", ""),
            "finishCount": chapter_data.get("finishCount", 0),
            "clazzId": chapter_data.get("clazzId", ""),
            "enc": chapter_data.get("enc", ""),
            "time": chapter_data.get("time", 0),
            "jobCount": chapter_data.get("jobCount", 0),
            "knowledgeId": chapter_data.get("knowledgeId", ""),
        }

    def sync_chapter_plan(self, encry_task_user_id: str, chapter_data: dict) -> bool:
        """把已完成的章节成绩交给任务引擎."""
        #
        # HTTP 200 只代表请求到达服务器；只有 JSON 明确返回 ``result=true``
        # 才算同步请求被接受。任务点最终是否完成仍必须由调用方重新读取确认。
        payload = self.chapter_sync_payload(encry_task_user_id, chapter_data)
        try:
            resp = self.session.post(
                CHAPTER_SCORE_URL,
                json=payload,
                headers=CHAPTER_SCORE_HEADERS,
                timeout=TASK_CENTER_TIMEOUT,
            )
        except Exception as e:
            logger.warning("章节成绩同步失败: {}", e)
            return False
        if resp.status_code != 200:
            logger.warning("章节成绩同步失败: HTTP {}", resp.status_code)
            return False
        try:
            data = resp.json()
        except Exception as e:
            logger.warning("章节成绩同步返回非 JSON，按失败处理: {}", e)
            return False
        if not isinstance(data, dict) or data.get("result") is not True:
            logger.warning(
                "章节成绩同步未被接受: {}",
                data.get("message", "返回结果不明确") if isinstance(data, dict) else data,
            )
            return False
        return True

    def wait_plan_finished(
        self,
        encry_task_user_id: str,
        encry_group_id: str,
        plan_id: Any,
        tries: int = 6,
        interval: float = 5.0,
    ) -> bool:
        """完成动作之后服务端可能有一点延迟（阅读/观看时长要等它结算），等一下再确认."""
        for i in range(max(1, tries)):
            if self.is_plan_finished(encry_task_user_id, encry_group_id, plan_id):
                return True
            if i < tries - 1:
                time.sleep(interval)
        return False

    # ------------------------------------------------------------------ 完成

    def _video_dot(self, encry_id: str, duration: int, current_time: int, status: int) -> bool:
        """视频打点：status 0=开始 1=心跳 2=暂停/结束."""
        url = f"{TASK_BASE}/videoDataLog/dataLog/{int(duration)}/{int(current_time)}/{int(status)}"
        try:
            resp = self.session.get(
                url, params={"encryId": encry_id}, timeout=TASK_CENTER_TIMEOUT
            )
            if resp.status_code != 200:
                logger.warning("视频打点失败: HTTP {}", resp.status_code)
                return False
            data = resp.json()
        except Exception as e:
            logger.warning("视频打点失败: {}", e)
            return False
        if not isinstance(data, dict):
            logger.warning("视频打点返回结构异常，按失败处理")
            return False
        if "result" in data and not _api_success(data.get("result")):
            logger.warning("视频打点被拒绝: {}", data.get("message", ""))
            return False
        if "result" not in data:
            logger.warning("视频打点缺少业务成功标记，按失败处理")
            return False
        return True

    def _save_schedule(self, encry_id: str, current_time: int):
        """记录播放位置（网页播放器每 30 秒一次的进度保存）."""
        try:
            self.session.get(
                f"{TASK_BASE}/planUserSchedule/lastCurrentTime/{int(current_time)}",
                params={"encryId": encry_id},
                timeout=TASK_CENTER_TIMEOUT,
            )
        except Exception as exc:
            logger.debug("播放位置保存失败（{}）", type(exc).__name__)

    @staticmethod
    def need_seconds(plan: Optional[dict], enable_key: str, value_key: str) -> int:
        """任务点的"时长型"完成条件（读 planBreakthroughSet）."""
        #
        # 平台把它写成"开关 + 分钟数"，例如：
        # enableVideoWatchDuration=1 + videoWatchDuration=2.0      -> 要看够 2 分钟
        # enableDocumentWatchDuration=1 + documentWatchDuration=5.0 -> 要读够 5 分钟
        # 返回需要的秒数；没有该要求时返回 0。
        bt = (plan or {}).get("planBreakthroughSet") or {}
        try:
            enabled = int(bt.get(enable_key) or 0)
        except (TypeError, ValueError):
            enabled = 0
        if not enabled:
            return 0
        try:
            minutes = float(bt.get(value_key) or 0)
        except (TypeError, ValueError):
            minutes = 0.0
        return int(round(minutes * 60)) if minutes > 0 else 0

    def _task_page(self, study_url, label):
        """Load an engine task page and require a successful HTTP response."""
        try:
            resp = self.session.get(study_url, timeout=TASK_CENTER_TIMEOUT)
        except Exception as exc:
            logger.warning("{}任务页打开失败: {}", label, exc)
            return None
        if resp.status_code != 200:
            logger.warning("{}任务页打开失败: HTTP {}", label, resp.status_code)
            return None
        return resp

    def _video_task_metadata(self, study_url):
        """Validate video metadata before starting the paced playback loop."""
        try:
            resp = self.session.get(study_url, timeout=TASK_CENTER_TIMEOUT)
        except Exception as e:
            logger.warning("视频任务页打开失败: {}", e)
            return None
        if resp.status_code != 200:
            logger.warning("视频任务页打开失败: HTTP {}", resp.status_code)
            return None
        vo = _extract_json_object(resp.text, "videoLearnVo")
        if not vo:
            logger.warning("视频任务页结构变化，未取到 videoLearnVo")
            return None
        encry_id = vo.get("encryId")
        info = vo.get("videoInfo") or {}
        try:
            duration = int(info.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        if not encry_id or duration <= 0:
            logger.warning("视频任务信息不完整（encryId/duration 缺失），跳过")
            return None

        return vo, encry_id, info, duration

    def study_video(self, study_url: str, plan: Optional[dict] = None) -> bool:
        """按真实播放节奏完成任务引擎的视频任务点."""
        #
        # 完成条件有两种：
        # * enableVideoComplated=1              -> 播完就行
        # * enableVideoWatchDuration=1 + N 分钟 -> 要累计观看够 N 分钟
        #
        # 有"观看时长"要求时必须按 1 倍速真实播放：服务端按真实时间判定有效观看
        # 时长（实测 2 倍速打点只算一半、原地心跳不算），一遍不够就回看一遍。
        metadata = self._video_task_metadata(study_url)
        if metadata is None:
            return False
        vo, encry_id, info, duration = metadata

        required = self.need_seconds(plan, "enableVideoWatchDuration", "videoWatchDuration")
        # 有时长要求 -> 1 倍速，保证"有效观看时长"和真实时间一致
        speed = 1.0 if required else self.speed
        try:
            watched = int(vo.get("farthestTimeValue") or vo.get("currentTime") or 0)
        except (TypeError, ValueError):
            watched = 0
        current = max(0, min(watched, duration))

        logger.info(
            "任务中心视频：{}（时长 {} 秒，已看 {} 秒，{} 倍速{}）",
            info.get("videoName", ""), duration, current, speed,
            f"，需要观看 {required} 秒" if required else "",
        )
        # 长视频给一行用户可见提示（控制台刷课期间只显示 print 和 WARNING）
        if duration >= 180 or required >= 180:
            minutes = max(1, int((required or duration) // 60))
            print(f"      · 播放视频：{info.get('videoName', '')}（约 {minutes} 分钟）")

        effective = 0.0
        passes = 0
        max_passes = max(2, required // max(1, duration) + 2) if required else 1
        while True:
            passes += 1
            start = current if passes == 1 else 0
            if not self._video_dot(encry_id, duration, start, 0):
                return False
            current = start
            while current < duration:
                if interrupt.should_stop():
                    self._video_dot(encry_id, duration, current, 2)
                    return False
                # 按 6 秒视频时间打一个点；倍速只影响真实的等待时间
                time.sleep(VIDEO_DOT_INTERVAL / speed)
                current = min(duration, current + VIDEO_DOT_INTERVAL)
                effective += VIDEO_DOT_INTERVAL / speed
                if not self._video_dot(encry_id, duration, current, 1):
                    return False
                self._save_schedule(encry_id, current)

            if not self._video_dot(encry_id, duration, duration, 2):
                return False
            self._save_schedule(encry_id, duration)

            if not required or effective >= required or passes >= max_passes:
                break
            logger.info(
                "需要累计观看 {} 秒，当前有效 {:.0f} 秒，回看一遍（第 {} 遍）",
                required, effective, passes + 1,
            )
            time.sleep(2)
        logger.info("任务中心视频完成: {}（播放 {} 秒）", info.get("videoName", ""), duration)
        return True

    @staticmethod
    def _parse_reader_mark(html: str) -> Optional[dict]:
        """从云盘阅读器页面取出打点信息 markDataStr（资源ID、页数、ext 等）."""
        matched = re.search(r'id="markDataStr"[^>]*>(.*?)</div>', html, re.S)
        if not matched:
            return None
        try:
            data = json.loads(matched.group(1).strip())
        except (ValueError, TypeError):
            return None
        return data

    def _send_read_point(self, mark: dict, seq: int) -> bool:
        """上报一个阅读点（真实阅读器每 30 秒一次）."""
        #
        # 请求形态和签名与阅读器 addPoint.js 对齐：d 在 params 中保留原始 JSON，
        # 交给 requests 在网络层编码一次；enc 则使用 d 的 encodeURIComponent 形式计算。
        payload = {
            "r": mark.get("resourceID", ""),
            "t": mark.get("resourceType", "doc"),
            "l": mark.get("location", 1),
            "f": mark.get("from", 4),
            "p": mark.get("curPage", 1),
            # addPoint.js 使用 markDataStr.totalPage；页面里的 pagenum 是另一套展示变量。
            "tp": mark.get("totalPage") or 1,
            "wc": 0,
            "ic": 2,
            "v": 2,
            # addPoint.js 的首报状态为 1，后续阅读心跳固定为 2；seq 仅用于本地日志。
            "s": 1 if seq == 1 else 2,
            "h": 0,
            "ext": mark.get("ext", ""),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        params = {
            "f": "readPoint",
            "u": mark.get("passportUID", ""),
            "d": body,
            "t": _browser_timestamp(),
        }
        # addPoint.js 只把值为字符串的可选参数放进查询串；当前文档 mark 通常没有它们。
        for key in ("pid", "s"):
            value = mark.get(key)
            if isinstance(value, str):
                params[key] = value
        params["enc"] = _read_point_enc(params)
        try:
            resp = self.session.get(
                READ_POINT_URL,
                params=params,
                headers=READ_POINT_HEADERS,
                timeout=TASK_CENTER_TIMEOUT,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning("文档阅读打点失败: {}", e)
            return False

    def _read_document_points(self, mark: dict, required_seconds: int) -> bool:
        """按真实时间打点，凑够任务点要求的阅读时长."""
        started = time.time()
        seq = 0
        total_points = max(1, int(required_seconds / READ_POINT_INTERVAL))
        while True:
            seq += 1
            if not self._send_read_point(mark, seq):
                logger.warning("文档阅读打点未被接受，本次不计为完成")
                return False
            elapsed = time.time() - started
            logger.info(
                "文档阅读打点 {}/{}：已阅读 {:.0f}/{:.0f} 秒",
                seq, total_points, elapsed, required_seconds,
            )
            if elapsed >= required_seconds:
                return True
            if interrupt.should_stop():
                return False
            time.sleep(min(READ_POINT_INTERVAL, max(1.0, required_seconds - elapsed)))

    def study_document(self, study_url: str, plan: Optional[dict] = None) -> bool:
        """完成任务引擎的文档任务点."""
        #
        # 文档的完成条件是"阅读时长 >= N 分钟"（planBreakthroughSet.documentWatchDuration），
        # 阅读时长由云盘阅读器的 readPoint 打点累计，所以流程是：
        # 1. 打开任务引擎文档页，取出云盘阅读器地址
        # 2. 打开阅读器页，取出打点信息 markDataStr
        # 3. 每 30 秒打一个点，凑够要求的分钟数
        # 4. 页面明确要求"完成阅读"（enableCompleteRead）时再调 readEnd
        resp = self._task_page(study_url, "文档")
        if resp is None:
            return False
        page = resp.text
        matched = re.search(r'encryPlanUserId\s*=\s*"([^"]+)"', page)
        required = self.need_seconds(plan, "enableDocumentWatchDuration", "documentWatchDuration")

        mark = None
        reader_info = _extract_json_object(page, "docStudyUrlInfo") or {}
        reader_url = reader_info.get("yunPanUrl")
        if reader_url:
            try:
                reader_resp = self.session.get(reader_url, timeout=TASK_CENTER_TIMEOUT)
                if reader_resp.status_code == 200:
                    mark = self._parse_reader_mark(reader_resp.text)
            except Exception as e:
                logger.warning("文档阅读器打开失败: {}", e)

        if required:
            if self._recently_submitted(plan, kind="document", ttl=DOCUMENT_ATTEMPT_TTL):
                logger.info(
                    "文档任务 [{}] 24 小时内已尝试过且平台未计入，本次跳过（避免重复消耗真实阅读时间）",
                    (plan or {}).get("name") or "文档",
                )
                return True
            if not mark:
                # 拿不到打点信息就没法证明阅读时长，不能假装完成
                logger.warning("文档任务需要阅读 {} 秒，但没取到阅读器打点信息，本次跳过", required)
                return False
            label = (plan or {}).get("name") or reader_info.get("name") or "文档"
            logger.info("任务中心文档：{}（需要阅读约 {:.0f} 分钟）", label, required / 60)
            print(f"      · 阅读文档：{label}（约 {required / 60:.0f} 分钟，请勿关闭窗口）")
            if not self._read_document_points(mark, required):
                return False
            self._mark_submitted(plan, kind="document")

        if matched and self._breakthrough_enabled(plan, "enableCompleteRead"):
            try:
                end_resp = self.session.get(
                    f"{TASK_BASE}/documentStudy/readEnd",
                    params={"encryPlanUserId": matched.group(1)},
                    timeout=TASK_CENTER_TIMEOUT,
                )
                if end_resp.status_code != 200:
                    logger.warning("文档任务标记失败: HTTP {}", end_resp.status_code)
                    return False
                data = end_resp.json()
                if not isinstance(data, dict) or not _api_success(data.get("result")):
                    message = data.get("message", "") if isinstance(data, dict) else "返回结构异常"
                    logger.warning("文档任务标记失败: {}", message)
                    return False
            except Exception as e:
                logger.warning("文档任务标记失败: {}", e)
                return False
        return True

    @staticmethod
    def _breakthrough_enabled(plan: Optional[dict], key: str) -> bool:
        """读取 planBreakthroughSet 中的开关，拒绝把非空字符串当成功."""
        breakthrough = (plan or {}).get("planBreakthroughSet") or {}
        if not isinstance(breakthrough, dict):
            return False
        try:
            value = breakthrough.get(key)
            return int(value or 0) == 1
        except (TypeError, ValueError):
            return _api_success(breakthrough.get(key))

    # ------------------------------------------------------------ AI 实践

    @staticmethod
    def _ai_page_params(url: str, html: str = "") -> Optional[dict]:
        """从 AI 实践 302 后的 SPA 地址取出平台实际发给接口的参数."""
        parsed = urlparse(url or "")
        query = {
            key: values[-1]
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
            if values
        }
        lowered = {key.lower(): value for key, value in query.items()}

        def pick(*names):
            for name in names:
                value = query.get(name)
                if value is None:
                    value = lowered.get(name.lower())
                if value not in (None, ""):
                    return unquote(str(value))
            # 某些入口把参数写进内嵌脚本；这里只接受明确的键值，不猜算法或 ID。
            for name in names:
                pattern = (
                    r"(?:[?&]"
                    + re.escape(name)
                    + r"=|[\"']?"
                    + re.escape(name)
                    + r"[\"']?\s*[:=]\s*[\"'])([^&\"'\s<]+)"
                )
                matched = re.search(pattern, html or "", re.I)
                if matched:
                    return unquote(matched.group(1))
            return ""

        params = {
            "courseid": pick("courseid", "courseId"),
            "clazzid": pick("clazzid", "clazzId"),
            "cpi": pick("cpi"),
            "publishRelationUuid": pick("publishRelationUuid"),
            "aiEnc": pick("aiEnc", "ai_enc"),
            "isPreview": pick("isPreview") or "0",
        }
        required = ("courseid", "clazzid", "cpi", "publishRelationUuid", "aiEnc")
        if any(not params[key] for key in required):
            return None
        return params

    @staticmethod
    def _ai_query(params: dict, record_uuid: Optional[str] = None) -> dict:
        query = {
            key: params.get(key, "")
            for key in ("courseid", "clazzid", "cpi", "publishRelationUuid")
        }
        if record_uuid:
            query["recordUuid"] = str(record_uuid)
        return query

    @staticmethod
    def _ai_talk_query(params: dict, record_uuid: str) -> dict:
        return {
            "courseId": params.get("courseid", ""),
            "clazzId": params.get("clazzid", ""),
            "cpi": params.get("cpi", ""),
            "aiEnc": params.get("aiEnc", ""),
            "recordUuid": str(record_uuid or ""),
            "isPreview": params.get("isPreview", "0"),
            "newAnswerView": "true",
        }

    @staticmethod
    def _response_json(resp, label: str) -> Optional[dict]:
        if getattr(resp, "status_code", 0) != 200:
            logger.warning("{}失败: HTTP {}", label, getattr(resp, "status_code", "?"))
            return None
        try:
            data = resp.json()
        except Exception as e:
            logger.warning("{}返回非 JSON，按失败处理: {}", label, e)
            return None
        if not isinstance(data, dict):
            logger.warning("{}返回结构异常，按失败处理", label)
            return None
        return data

    def _ai_load_data(self, params: dict, record_uuid: Optional[str] = None) -> Optional[dict]:
        query = self._ai_query(params, record_uuid)
        try:
            resp = self.session.get(
                AI_LOAD_DATA_URL, params=query, timeout=TASK_CENTER_TIMEOUT
            )
        except Exception as e:
            logger.warning("AI实践状态读取失败: {}", e)
            return None
        data = self._response_json(resp, "AI实践状态读取")
        if data is None or not _api_success(data.get("status")):
            logger.warning("AI实践状态读取未被接受: {}", data.get("msg", "") if data else "")
            return None
        result = data.get("data")
        if not isinstance(result, dict):
            logger.warning("AI实践状态读取缺少 data，按失败处理")
            return None
        return result

    def _ai_init(self, params: dict) -> Optional[dict]:
        """初始化一次新的作答；已存在未完成记录时返回空字典，交给调用方续接."""
        #
        # 前端 helper 会把该 POST 序列化成 form-urlencoded，而不是 JSON。
        payload = {
            "type": 2,
            "courseid": params.get("courseid", ""),
            "clazzid": params.get("clazzid", ""),
            "cpi": params.get("cpi", ""),
            "publishRelationUuid": params.get("publishRelationUuid", ""),
        }
        try:
            resp = self.session.post(
                AI_INIT_URL,
                data=payload,
                headers=AI_FORM_HEADERS,
                timeout=TASK_CENTER_TIMEOUT,
            )
        except Exception as e:
            logger.warning("AI实践作答初始化失败: {}", e)
            return None
        data = self._response_json(resp, "AI实践作答初始化")
        if data is None:
            return None
        if not _api_success(data.get("status")):
            text = " ".join(
                str(data.get(key, ""))
                for key in ("msg", "message", "errorCode", "code")
            )
            if "4601" in text or "已存在未完成" in text:
                logger.info("AI实践已有未完成记录，改为续接，不重复初始化")
                return {}
            logger.warning("AI实践作答初始化未被接受: {}", text.strip())
            return None
        result = data.get("data")
        if not isinstance(result, dict):
            logger.warning("AI实践作答初始化缺少 data，按失败处理")
            return None
        if not result.get("recordUuid") or not result.get("answerUuid"):
            logger.warning("AI实践作答初始化缺少 recordUuid/answerUuid，按失败处理")
            return None
        return result

    @staticmethod
    def parse_ai_sse(lines) -> dict:
        """解析 main-talk 的 SSE 行，保留前端使用的题目字段和特殊标记."""
        result = {
            "content": "",
            "preAppendContent": "",
            "questionType": "",
            "questionTypeInt": "",
            "dimension": "",
            "knowledgePoint": "",
            "questionStem": "",
            "options": [],
            "special_marks": [],
            "had_data": False,
            "stream_closed": False,
            "error": "",
        }
        option_map = {}
        try:
            for event in _sse_events(lines):
                result["had_data"] = True
                if "status" in event and not _api_success(event.get("status")):
                    result["error"] = str(event.get("msg") or event.get("message") or "SSE业务失败")
                    continue
                content = _sse_content(event)
                if content:
                    result["content"] += content

                if any(marker in content for marker in (
                    "RightMark", "QuestionTip", "SummaryTopic", "TopicTest",
                    "SonQuestion", "showTipBtn",
                )):
                    result["special_marks"].append(content)

                event_type = str(event.get("type") or "")
                if event_type in {"preAppendContent", "questionType", "questionTypeInt",
                                  "dimension", "knowledgePoint", "questionStem"}:
                    result[event_type] += content
                elif event_type.startswith("option-"):
                    option = event_type.split("-", 1)[1].strip().upper()
                    if option:
                        option_map[option] = option_map.get(option, "") + content
        except Exception as e:
            result["error"] = str(e)
            return result

        result["options"] = [
            {"option": option, "optionContent": content}
            for option, content in option_map.items()
        ]
        result["stream_closed"] = True
        return result

    @staticmethod
    def parse_ai_report_sse(lines) -> dict:
        """解析"学习质量评估报告"的 SSE：成绩是 id=score 的那条事件."""
        #
        # 平台**不会**在提交后自动评估：实测提交后 10 分钟 answerRecords 里仍然没有分数，
        # 必须请求 end-report（页面上就是"学习质量评估报告"按钮）才会现算成绩。
        # 这个流会把同一条 JSON 拆到多行（中文 key 更长），所以按"拼接后能解析就算一条"处理。
        result = {
            "score": None,
            "sections": {},
            "had_data": False,
            "stream_closed": False,
            "error": "",
        }
        try:
            for event in _sse_events(lines, report=True):
                result["had_data"] = True
                content = _sse_content(event)
                key = str(event.get("id") or "").strip()
                if key:
                    result["sections"][key] = result["sections"].get(key, "") + content
        except Exception as e:
            result["error"] = str(e)
            return result

        result["stream_closed"] = True
        matched = re.search(r"\d+(?:\.\d+)?", result["sections"].get("score", ""))
        if matched:
            try:
                result["score"] = float(matched.group(0))
            except ValueError:
                result["score"] = None
        return result

    def _ai_end_report(self, params: dict, record_uuid: str) -> Optional[float]:
        """请求"学习质量评估报告"，让平台把这一局的成绩算出来."""
        query = {
            "courseId": params.get("courseid", ""),
            "clazzId": params.get("clazzid", ""),
            "cpi": params.get("cpi", ""),
            "aiEnc": params.get("aiEnc", ""),
            "recordUuid": str(record_uuid or ""),
        }
        if not query["recordUuid"] or not query["aiEnc"]:
            logger.warning("AI实践质量评估报告缺少 recordUuid/aiEnc，跳过")
            return None
        try:
            resp = self.session.post(
                AI_END_REPORT_URL,
                params=query,
                data={},
                headers=AI_STREAM_HEADERS,
                stream=True,
                timeout=AI_STREAM_TIMEOUT,
            )
        except Exception as e:
            logger.warning("AI实践质量评估报告请求失败: {}", e)
            return None
        try:
            result = self.parse_ai_report_sse(resp.iter_lines(decode_unicode=True))
        except Exception as e:
            logger.warning("AI实践质量评估报告读取失败: {}", e)
            return None
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()
        if result.get("error"):
            logger.warning("AI实践质量评估报告流异常: {}", result["error"])
        if not result.get("had_data") or not result.get("stream_closed"):
            logger.warning("AI实践质量评估报告没有完整数据，按失败处理")
            return None
        if result.get("score") is None:
            logger.warning("AI实践质量评估报告里没有成绩，按失败处理")
            return None
        logger.info("AI实践质量评估报告成绩：{:.1f}", result["score"])
        return float(result["score"])

    def _ai_stream(self, params: dict, record_uuid: str, user_message: str) -> Optional[dict]:
        query = self._ai_talk_query(params, record_uuid)
        payload = {"userMessage": str(user_message or "")}
        try:
            resp = self.session.post(
                AI_TALK_URL,
                params=query,
                data=payload,
                headers=AI_STREAM_HEADERS,
                stream=True,
                timeout=AI_STREAM_TIMEOUT,
            )
        except Exception as e:
            logger.warning("AI实践对话请求失败: {}", e)
            return None
        try:
            iterator = resp.iter_lines(decode_unicode=False)
            result = self.parse_ai_sse(iterator)
        except Exception as e:
            logger.warning("AI实践 SSE 读取失败: {}", e)
            return None
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()
        if not result.get("had_data") or not result.get("stream_closed"):
            logger.warning("AI实践 SSE 没有完整有效数据，按失败处理")
            return None
        if result.get("error"):
            logger.warning("AI实践 SSE 业务失败: {}", result["error"])
            return None
        return result

    def _ai_submit(self, params: dict, record_uuid: str, preview: str = "") -> bool:
        if not self.confirm_submission("AI实践", preview):
            return False
        try:
            resp = self.session.post(
                AI_SUBMIT_URL,
                params=self._ai_query(params, record_uuid),
                data={},
                headers=AI_FORM_HEADERS,
                timeout=TASK_CENTER_TIMEOUT,
            )
        except Exception as e:
            logger.warning("AI实践提交失败: {}", e)
            self._set_outcome(TaskOutcome.FAILED)
            return False
        data = self._response_json(resp, "AI实践提交")
        if data is None or not _api_success(data.get("status")) or not data.get("data"):
            logger.warning("AI实践提交未被接受: {}", data.get("msg", "") if data else "")
            self._set_outcome(TaskOutcome.FAILED)
            return False
        return True

    @staticmethod
    def _ai_message_payload(message: dict) -> Optional[dict]:
        if not isinstance(message, dict):
            return None
        payload = message.get("contentJson")
        if not isinstance(payload, dict):
            payload = message.get("content")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _ai_options(raw) -> list:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = []
        if isinstance(raw, dict):
            raw = [
                {"option": key, "optionContent": value}
                for key, value in raw.items()
            ]
        if not isinstance(raw, list):
            return []
        options = []
        for item in raw:
            if isinstance(item, dict):
                option = str(item.get("option") or item.get("key") or "").strip().upper()
                content = item.get("optionContent") or item.get("content") or ""
            else:
                option = ""
                content = item
            if option:
                options.append({"option": option, "optionContent": str(content)})
        return options

    @classmethod
    def _ai_turn_from_payload(cls, payload: Optional[dict]) -> Optional[dict]:
        if not isinstance(payload, dict):
            return None
        turn = {
            "content": str(payload.get("content") or ""),
            "preAppendContent": str(payload.get("preAppendContent") or ""),
            "questionType": str(payload.get("questionType") or ""),
            "questionTypeInt": str(payload.get("questionTypeInt") or ""),
            "dimension": str(payload.get("dimension") or ""),
            "knowledgePoint": str(payload.get("knowledgePoint") or ""),
            "questionStem": str(payload.get("questionStem") or ""),
            "options": cls._ai_options(
                payload.get("questionOptions") or payload.get("options")
            ),
            "special_marks": [],
        }
        return turn if cls._ai_turn_has_question(turn) else None

    @staticmethod
    def _ai_turn_has_question(turn: Optional[dict]) -> bool:
        if not isinstance(turn, dict):
            return False
        stem = str(turn.get("questionStem") or "").strip()
        options = turn.get("options") or []
        return bool(stem or options)

    # 平台结束一局时，最后一条是"知识点解析/小结"这类总结，而不是题目
    AI_SUMMARY_MARKS = ("知识点解析", "小结", "本局结束", "本轮结束", "练习结束", "继续加油")

    # 同一道题最多试几个答案：平台判分是它自己的大模型，偶尔会把标准答案
    # 判错并反复推回同一题（实测同一题被推回 15 次、整局拖到 112 题）。
    # 试满一轮选项还不够，就带着本轮已有作答直接提交，不再空转。
    AI_MAX_TRIES_PER_QUESTION = 4
    # 连续几次作答都没让平台的 messageList 变长，说明这一局其实已经结束、
    # 平台只是在把最后一道题推回来（实测"错/对"来回换了十几次仍在空转）。
    AI_STALL_LIMIT = 2

    @classmethod
    def _ai_pending_turn(cls, data: dict) -> Optional[dict]:
        """取当前还没作答的题."""
        #
        # 注意：从后往前扫时，一旦先遇到平台的结束总结，就必须返回 None。
        # 实测踩过坑：总结之后还留着上一条题目，旧实现会把那条**过期题目**当成 pending，
        # 于是对着它反复作答、平台根本不再收录，一路空转到轮数上限（23 分钟白跑）。
        messages = data.get("messageList") or []
        if not isinstance(messages, list):
            return None
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role != "2":
                continue
            payload = cls._ai_message_payload(message)
            if isinstance(payload, dict):
                plain = str(payload.get("content") or "")
                if not payload.get("questionStem") and any(
                        mark in plain for mark in cls.AI_SUMMARY_MARKS):
                    return None
            turn = cls._ai_turn_from_payload(payload)
            if turn:
                return turn
        return None

    @staticmethod
    def _ai_completion_state(data: dict) -> Optional[bool]:
        """返回 True=明确完成、False=明确未完成、None=平台未给出足够证据."""
        if not isinstance(data, dict):
            return None
        pending = data.get("unCompleteTopic")
        if isinstance(pending, (list, tuple, set)):
            return not bool(pending)
        if isinstance(pending, dict):
            if "isDone" in pending:
                return _api_success(pending.get("isDone"))
            return False
        if isinstance(pending, str):
            return pending.strip().lower() in {"", "0", "false", "[]", "{}", "null"}

        dimensions = data.get("dimensionList")
        if isinstance(dimensions, list) and dimensions:
            topics_found = False
            for dimension in dimensions:
                topics = dimension.get("topicList") if isinstance(dimension, dict) else None
                for topic in topics or []:
                    if isinstance(topic, dict) and not topic.get("diy"):
                        topics_found = True
                        if not _api_success(topic.get("isDone")):
                            return False
            if topics_found:
                return True
        return None

    def _ai_wait_for_score(self, params: dict, record_uuid: str,
                           tries: int = 20, interval: float = 30.0):
        """提交后等平台出评估结果."""
        #
        # 平台不是立刻出分：实测提交后要几分钟，`answerRecords` 里才会出现
        # statusMsg=已评估。这里轮询 load-data，等到就返回分数。
        data = None
        for attempt in range(max(1, tries)):
            if interrupt.should_stop():
                return None, data
            data = self._ai_load_data(params, record_uuid)
            if data is not None:
                for record in data.get("answerRecords") or []:
                    if not isinstance(record, dict):
                        continue
                    if str(record.get("recordUuid")) != str(record_uuid):
                        continue
                    # 平台只把评估过的记录放进 answerRecords；拿到本条记录才算真出分，
                    # 不能用顶层的 answerScore（那是上一次练习的旧分数）
                    score = self._ai_score(data, record_uuid)
                    if score is not None:
                        logger.info(
                            "AI实践第 {} 次轮询拿到评估成绩: {}（{}）",
                            attempt + 1, score, record.get("statusMsg") or "",
                        )
                        return score, data
            if attempt < tries - 1:
                time.sleep(interval)
        return None, data

    @staticmethod
    def _ai_score(data: dict, record_uuid: Optional[str] = None) -> Optional[float]:
        records = [r for r in (data or {}).get("answerRecords") or [] if isinstance(r, dict)]
        if record_uuid:
            # 问"这一条记录考了多少分"时，**只能**用这条记录自己的分数。
            # 旧实现会回落到顶层 answerScore（那是上一次练习的成绩），
            # 一旦本条还没评估，就会把上一次的分数当成本次的成绩。
            for record in records:
                if str(record.get("recordUuid")) == str(record_uuid):
                    try:
                        if record.get("score") not in (None, ""):
                            return float(record.get("score"))
                    except (TypeError, ValueError):
                        return None
                    return None
            return None
        candidates = [
            data.get("answerScore"),
            (data.get("reportData") or {}).get("score")
            if isinstance(data.get("reportData"), dict) else None,
        ]
        candidates.extend(record.get("score") for record in records)
        for candidate in candidates:
            try:
                if candidate not in (None, ""):
                    return float(candidate)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _ai_record_scores(data: dict) -> list:
        """平台已经评估过的每一次练习成绩（answerRecords）."""
        scores = []
        for record in (data or {}).get("answerRecords") or []:
            if not isinstance(record, dict):
                continue
            try:
                if record.get("score") not in (None, ""):
                    scores.append(float(record.get("score")))
            except (TypeError, ValueError):
                continue
        return scores

    @classmethod
    def _ai_average_score(cls, data: dict) -> Optional[float]:
        """练习平均分."""
        #
        # 页面上写的达标口径是"学生多次练习平均分达到 N 分"，所以历史低分记录会拖后腿；
        # 单次满分并不等于这项练习的最终成绩够看。
        scores = cls._ai_record_scores(data)
        return sum(scores) / len(scores) if scores else None

    @staticmethod
    def _ai_question_key(turn: dict) -> str:
        """同一道题（含追问）在平台里是同一段题干，用它来记住试过哪些答案."""
        stem = str((turn or {}).get("questionStem") or (turn or {}).get("content") or "")
        return re.sub(r"\s+", "", stem)[:100]

    @staticmethod
    def _ai_answer_core(answer: str) -> str:
        """从作答文本里取出"核心答案"（选项字母 / 对错），用于判断这题试过什么."""
        text = str(answer or "").strip()
        matched = re.match(r"选\s*([A-Ea-e]+)", text)
        if matched:
            return matched.group(1).upper()
        if text in {"对", "错"}:
            return text
        return text[:40]

    def _ai_answer(self, turn: dict, data: dict, exclude=None) -> str:
        stem = str(turn.get("questionStem") or turn.get("content") or "").strip()
        question_type = str(turn.get("questionTypeInt") if turn.get("questionTypeInt") is not None else "").strip()
        options = self._ai_options(turn.get("options"))
        if not question_type:
            question_label = str(turn.get("questionType") or "")
            if "多选" in question_label:
                question_type = "1"
            elif "单选" in question_label:
                question_type = "0"
            elif "判断" in question_label:
                question_type = "3"
        if question_type not in {"0", "1", "3"} and options:
            # 平台偶尔只给中文 questionType、或者给一个没见过的 questionTypeInt 编码，
            # 但题目带了选项。此时按最常见的单选处理：**绝不能**因为题型没认出来
            # 就把客观题当简答写一段小作文（实测被平台判"没有按题目要求作答"；
            # 独立审计也用 questionTypeInt="2" + A/B 选项复现过）。
            question_type = "0"
        requirement = str(data.get("requirement") or "").strip()
        # 客观题只需要"维度/知识点"这种题干上下文；平台反馈另算一份，
        # **只用于选择题/判断题的内部判据**。开放题的正文绝不能带平台判分话术，
        # 否则"回答正确/本题考核知识点"就会被写进交给老师的答案里。
        context = "；".join(
            value for value in (
                str(turn.get("dimension") or "").strip(),
                str(turn.get("knowledgePoint") or "").strip(),
            ) if value
        )
        choice_context = context
        if str(turn.get("preAppendContent") or "").strip():
            choice_context = (choice_context + "；" if choice_context else "") + \
                re.sub(r"\s+", " ", str(turn.get("preAppendContent")))[:200]
        feedback = getattr(self.writer, "_recent_feedback", None)
        if callable(feedback):
            try:
                hints = feedback(data)
            except Exception:
                hints = ""
            if hints:
                choice_context = (choice_context + "；平台判据：" + hints) if choice_context \
                    else ("平台判据：" + hints)

        if question_type in {"0", "1"} and options:
            chooser = getattr(self.writer, "choose_options", None)
            if not callable(chooser):
                raise RuntimeError("当前写作器不支持 AI 实践选择题")
            try:
                answer = chooser(stem, options, multiple=question_type == "1",
                                 context=choice_context, exclude=exclude)
            except TypeError:
                # 兼容旧写作器/测试替身：不接受 exclude 参数
                answer = chooser(stem, options, multiple=question_type == "1",
                                 context=choice_context)
            valid = {item["option"] for item in options}
            chosen = []
            for letter in re.findall(r"[A-E]", str(answer).upper()):
                if letter in valid and letter not in chosen:
                    chosen.append(letter)
            if not chosen:
                raise RuntimeError("AI 实践选择题没有得到有效选项")
            if question_type == "0":
                # 选择题就发选项字母本身（和真人在页面上点选项一样），
                # 不要拼"选 X，因为……"这种解释性长句：既不是平台的作答格式，
                # 也一眼就能看出是机器在答。
                return chosen[0]
            order = {letter: index for index, letter in enumerate("ABCDE")}
            return "".join(sorted(chosen, key=lambda letter: order.get(letter, 99)))

        if question_type == "3":
            judge = getattr(self.writer, "choose_judgement", None)
            if not callable(judge):
                raise RuntimeError("当前写作器不支持 AI 实践判断题")
            try:
                answer = judge(stem, context=choice_context, exclude=exclude)
            except TypeError:
                answer = judge(stem, context=choice_context)
            answer = str(answer).strip()
            if answer not in {"对", "错"}:
                raise RuntimeError("AI 实践判断题没有得到有效答案")
            return answer

        answerer = getattr(self.writer, "practice_answer", None)
        if callable(answerer):
            answer = answerer(stem, requirement=requirement, context=context)
        else:
            answer = self.writer.answer(stem, requirement=requirement, max_chars=500)
        answer = str(answer or "").strip()
        if not answer:
            raise RuntimeError("AI 实践简答没有生成内容")
        return answer[:2000]

    @staticmethod
    def _ai_turn_type(turn: dict) -> str:
        raw = (turn or {}).get("questionTypeInt")
        label = str((turn or {}).get("questionType") or "").strip()
        value = str(raw) if raw is not None else label
        if value in {"0", "1", "3"}:
            return {"0": "single", "1": "multiple", "3": "judgement"}[value]
        if "判断" in label:
            return "judgement"
        if "多选" in label:
            return "multiple"
        if "单选" in label or (turn or {}).get("options"):
            return "single"
        return "shortanswer"

    @staticmethod
    def _ai_turn_title(turn: dict) -> str:
        for key in ("questionStem", "stem", "question", "title", "content"):
            value = str((turn or {}).get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _ai_record_submitted(data: dict) -> bool:
        try:
            return int(data.get("recordStatus") or 0) in {1, 2}
        except (TypeError, ValueError):
            return str(data.get("recordStatus") or "") in {"1", "2"}

    # -------------------------------------------------------------- 主题讨论

    def _load_discussion_replies(self, bbsid: str, topic_uuid: str, user_puid: str = "",
                                 limit: int = 8) -> tuple:
        """读讨论已有回复."""
        #
        # 返回 (回复正文列表, 自己是否已经回复过)。
        # 正文供 ai_writer 模仿语气；"已回复过"用来避免重复运行同一任务时反复发帖。
        # 读取失败就当没有参考、也没回复过（上层仍会走正常的提交路径）。
        try:
            resp = self.session.get(
                f"{DISCUSSION_BASE}/pc/invitation/getReplyList",
                params={"bbsid": bbsid, "uuid": topic_uuid, "tag": "", "order": 2,
                        "lastValue": "", "lastAuxValue": ""},
                timeout=TASK_CENTER_TIMEOUT,
            )
            data = resp.json()
        except Exception as e:
            logger.debug("读取讨论已有回复失败（不参考风格继续）: {}", e)
            return [], False
        items = data.get("datas") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return [], False
        texts = []
        has_replied = False
        for item in items:
            if not isinstance(item, dict):
                continue
            if user_puid and str(item.get("createrPuid") or item.get("puid") or "") == str(user_puid):
                has_replied = True
            content = str(item.get("content") or "").strip()
            if content and len(texts) < limit:
                texts.append(content)
        return texts, has_replied

    def study_discussion(self, study_url: str, plan: Optional[dict] = None,
                         course: Optional[dict] = None) -> bool:
        """完成「任务中心 -> 主题讨论」任务点（planType=14）."""
        #
        # 真实接口（groupweb.chaoxing.com，）：
        # * 话题详情页：GET study_url（302 到 .../replysList?courseId=&classId=），
        # 页面里的 window.obj 带 urlToken / topic.title / topic.content；
        # * 已有回复：GET /pc/invitation/getReplyList?bbsid=&uuid=&order=2；
        # * 发回复：POST /pc/invitation/{topicUuid}/addReplys
        # （replyId=-1 一级回复、topic_content=encodeURIComponent(正文)、urlToken、bbsid）。
        #
        # 回复文本统一走 api/ai_writer.HumanLikeWriter.discussion（模仿已有回复、去 AI 味）；
        # 生成器判定有硬伤（编造个人经历/平台话术）时直接放弃，不提交。
        # 是否算完成仍由上层 wait_plan_finished 复查任务引擎状态裁定。
        name = (plan or {}).get("name") or "主题讨论"
        query = parse_qs(urlparse(study_url).query)
        bbsid = (query.get("bbsid") or [""])[0]
        topic_uuid = (query.get("uuid") or [""])[0]
        if not bbsid or not topic_uuid:
            logger.warning("主题讨论学习地址缺少 bbsid/uuid，本次不提交: {}", name)
            return False
        return self.reply_topic(bbsid, topic_uuid, course=course, name=name,
                                referer=study_url)

    def reply_topic(self, bbsid: str, topic_uuid: str, course: Optional[dict] = None,
                    name: str = "", referer: str = "") -> bool:
        """模式 1：任务里的主题讨论——生成草稿后按提交模式提交."""
        draft = self.draft_reply(bbsid, topic_uuid, course=course, name=name, referer=referer)
        if draft is None:
            return False
        if draft.get("has_replied"):
            return True
        name = name or "主题讨论"
        if not self.confirm_submission("主题讨论", draft["title"] + "\n" + draft["reply"]):
            return False
        return self.submit_reply(bbsid, topic_uuid, course=course, name=name,
                                 topic_info=draft["topic_info"], reply=draft["reply"],
                                 referer=draft["referer"])

    @staticmethod
    def _topic_detail_url(bbsid: str, topic_uuid: str, course: Optional[dict] = None) -> str:
        """帖子详情页地址（讨论区模式没有现成的 study_url 时用它）."""
        course = course or {}
        class_id = str(course.get("classId") or course.get("clazzId") or "")
        return (f"{DISCUSSION_BASE}/pc/topic/jumpToTopicDetail?bbsid={quote(str(bbsid))}"
                f"&uuid={quote(str(topic_uuid))}&classId={quote(class_id)}")

    def draft_reply(self, bbsid: str, topic_uuid: str, course: Optional[dict] = None,
                    name: str = "", referer: str = "", revision_hint: str = "",
                    previous_reply: str = "") -> Optional[dict]:
        """只生成回复草稿，**不提交**."""
        #
        # 讨论区模式（自己挑帖子）要先给用户看草稿、确认之后再发，所以拆出这一步。
        # 返回 {topic_info, title, reply, has_replied, referer}；失败返回 None。
        course = course or {}
        name = name or "主题讨论"
        study_url = referer or self._topic_detail_url(bbsid, topic_uuid, course)

        try:
            resp = self.session.get(
                study_url, timeout=TASK_CENTER_TIMEOUT, allow_redirects=True
            )
        except Exception as e:
            logger.warning("主题讨论页打开失败: {} - {}", name, e)
            return None
        if getattr(resp, "status_code", 0) != 200:
            logger.warning("主题讨论页打开失败: {} HTTP {}", name, getattr(resp, "status_code", "?"))
            return None

        topic_info = _extract_discussion_topic(resp.text or "")
        if not topic_info["url_token"]:
            logger.warning("主题讨论页没取到 urlToken（登录失效或页面改版），本次不提交: {}", name)
            return None

        writer = getattr(self, "writer", None)
        if writer is None or not getattr(writer, "available", False):
            logger.warning("主题讨论需要 AI 写作器，当前不可用，本次不提交: {}", name)
            return None

        existing, has_replied = self._load_discussion_replies(
            bbsid, topic_uuid, topic_info.get("user_puid", "")
        )
        if has_replied:
            # 已经回复过就不再发一条（重复运行不能刷屏讨论区）
            logger.info("主题讨论已经回复过，本次不重复发帖: {}", name)
            return {"topic_info": topic_info, "title": topic_info["title"], "reply": "",
                    "has_replied": True, "referer": study_url}

        topic = (topic_info["title"] + "\n" + topic_info["content"]).strip()
        try:
            # 保持普通主题讨论的原调用形态；只有用户明确要求重写时才传新上下文。
            # 这样第三方/旧版写作器仍能继续用于原有的自动讨论流程。
            if revision_hint or previous_reply:
                reply = writer.discussion(
                    topic, existing_posts=existing, max_chars=180,
                    revision_hint=str(revision_hint or "").strip()[:120],
                    previous_reply=str(previous_reply or "").strip()[:360],
                )
            else:
                reply = writer.discussion(topic, existing_posts=existing, max_chars=180)
        except Exception as e:
            logger.warning(
                "主题讨论生成回复失败（AI 味/编造内容反复出现），本次不提交: {} - {}", name, e
            )
            return None
        reply = str(reply or "").strip()
        if not reply:
            logger.warning("主题讨论没有生成内容，本次不提交: {}", name)
            return None
        logger.debug("主题讨论回复草稿（{} 字）：{}", len(reply), reply)
        return {"topic_info": topic_info, "title": topic_info["title"], "reply": reply,
                "has_replied": False, "referer": study_url}

    def submit_reply(self, bbsid: str, topic_uuid: str, course: Optional[dict] = None,
                     name: str = "", topic_info: Optional[dict] = None, reply: str = "",
                     referer: str = "", echo: bool = True) -> bool:
        """把已经确认的草稿提交给平台（含实时留痕与复核记录）."""
        course = course or {}
        name = name or "主题讨论"
        topic_info = topic_info or {}
        reply = str(reply or "").strip()
        if not reply:
            logger.warning("主题讨论没有可提交的正文: {}", name)
            return False
        study_url = referer or self._topic_detail_url(bbsid, topic_uuid, course)
        payload = {
            "courseId": str(course.get("courseId") or ""),
            "classId": str(course.get("classId") or course.get("clazzId") or ""),
            "replyId": -1,
            "uuid": uuid4().hex,
            # 网页端先 encodeURIComponent 一次，jQuery 再编码一次；这里保持一致
            "topic_content": quote(reply, safe="!'()*-._~"),
            "files_url": "",
            "files_attr": "",
            "anonymous": "",
            "urlToken": topic_info.get("url_token", ""),
            "bbsid": bbsid,
        }
        if echo:
            emit_block(f"讨论 · {clip(name, 24)}", reply)
        item = review.record(review.KIND_DISCUSSION, reply, course=course.get("title", ""),
                             task=name, status="待提交")
        if not item:
            logger.warning("讨论复核记录写入失败，本次不提交")
            return False
        status = "请求失败或平台未确认"
        try:
            post_url = f"{DISCUSSION_BASE}/pc/invitation/{quote(str(topic_uuid))}/addReplys"
            try:
                posted = self.session.post(
                    post_url,
                    data=payload,
                    timeout=TASK_CENTER_TIMEOUT,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Origin": DISCUSSION_BASE,
                        "Referer": study_url,
                    },
                )
            except Exception as e:
                logger.warning("主题讨论提交请求失败: {} - {}", name, e)
                return False
            if getattr(posted, "status_code", 0) != 200:
                logger.warning("主题讨论提交失败: {} HTTP {}", name, getattr(posted, "status_code", "?"))
                return False
            try:
                data = posted.json()
            except ValueError:
                logger.warning("主题讨论提交返回的不是 JSON，本次不判定成功: {}", name)
                return False
            if not isinstance(data, dict) or not data.get("status"):
                logger.warning("主题讨论提交被平台拒绝: {} -> {}", name, str(data)[:200])
                return False
            if not data.get("datas"):
                logger.info("主题讨论已提交，平台提示需要审核: {}", name)
            else:
                logger.info("主题讨论已回复（等待任务中心状态复查）: {}", name)
            status = "平台已接受，等待任务状态复查" if data.get("datas") else "平台已接受，待审核"
            return True

        finally:
            review.update(item, status)

    # ------------------------------------------------------------ 提交去重

    @staticmethod
    def _ledger_key(plan: Optional[dict], kind: str) -> str:
        plan_id = str((plan or {}).get("planId") or "")
        return f"{kind}:{plan_id}" if plan_id else ""

    def _recently_submitted(self, plan: Optional[dict], kind: str = "homework",
                            ttl: Optional[float] = None) -> bool:
        """本地台账里这个任务点最近提交/尝试过吗（避免状态延迟导致重复提交）."""
        key = self._ledger_key(plan, kind)
        if not key:
            return False
        try:
            with open(paths.submissions_path(), encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        try:
            submitted_at = float(data.get(key) or 0)
        except (TypeError, ValueError):
            return False
        window = SUBMISSION_LEDGER_TTL if ttl is None else ttl
        return submitted_at > 0 and (time.time() - submitted_at) < window

    def _mark_submitted(self, plan: Optional[dict], kind: str = "homework") -> None:
        """记下"这个任务点刚提交/尝试过"；写失败不影响本次提交."""
        key = self._ledger_key(plan, kind)
        if not key:
            return
        path = paths.submissions_path()
        try:
            try:
                with open(path, encoding="utf-8") as fp:
                    data = json.load(fp)
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data[key] = time.time()
            if len(data) > 200:
                for key in sorted(data, key=lambda k: data[k])[:len(data) - 200]:
                    data.pop(key, None)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(data, fp)
            os.replace(tmp, path)
        except Exception as e:
            logger.debug("提交记录写入失败（不影响本次提交）: {}", e)

    # ---------------------------------------------------------------- 作业

    def _fill_homework_answers(self, questions: list, course: Optional[dict] = None,
                               task_name: str = "") -> Optional[str]:
        """给作业题目填答案（选择题/判断题/填空题走题库，简答题走去 AI 味写作器）."""
        #
        # 返回 None 表示全部填好；返回字符串表示失败原因（此时绝不提交）。
        tiku = getattr(self.chaoxing, "tiku", None)
        if tiku is None or getattr(tiku, "DISABLE", False):
            return "没有可用题库，选择题/判断题无法作答"

        answers = tiku.query_all(questions, query_delay=0)
        if not isinstance(answers, list):
            answers = [None] * len(questions)
        elif len(answers) != len(questions):
            answers = list(answers) + [None] * (len(questions) - len(answers))
            answers = answers[:len(questions)]

        random_count = 0
        emit(answers_header(task_name or "作业", len(questions)))
        for _qi, (q, res) in enumerate(zip(questions, answers), 1):
            q_type = q.get("type")
            answer = ""
            if q_type == "shortanswer" or (q_type == "unknown" and not q.get("options")):
                # 简答题必须走去 AI 味写作器；拿不到正文就不提交（AGENTS 铁律 7/9）
                writer = getattr(self, "writer", None)
                if writer is None or not getattr(writer, "available", False):
                    return f"简答题需要 AI 写作器，当前不可用：{str(q.get('title'))[:40]}"
                try:
                    answer = writer.answer(str(q.get("title") or ""))
                except Exception as exc:
                    return "简答题未通过检查：" + str(exc)
                answer = str(answer or "").strip()
                if not answer:
                    return f"简答题没有生成内容：{str(q.get('title'))[:40]}"
                item = review.record(
                    review.KIND_HOMEWORK, answer,
                    course=(course or {}).get("title", ""),
                    task=task_name or "",
                    status="待确认",
                )
                if not item:
                    return "简答题复核记录写入失败"
                q["_review_item"] = item
                emit_block(f"简答 {_qi}", answer)
            elif not res:
                answer = random_answer(q.get("options", ""), q_type)
            elif q_type == "multiple":
                answer = build_multiple_answer(res, q.get("options", ""))
            elif q_type == "single":
                options_list = multi_cut(q.get("options", ""))
                if options_list:
                    t_res = clean_res(res)
                    for option in options_list:
                        if t_res and is_subsequence(t_res[0], option):
                            answer = option[:1]
                            break
                    if not answer and t_res:
                        answer = best_option_by_similarity(t_res[0], options_list, threshold=0.8)
            elif q_type == "judgement":
                answer = "true" if tiku.judgement_select(res) else "false"
            elif q_type == "completion":
                if isinstance(res, list):
                    answer = "#".join(str(x).strip() for x in res if str(x).strip())
                elif isinstance(res, str):
                    answer = res
            else:
                answer = res if isinstance(res, str) else ""

            if not answer and q_type not in ("shortanswer", "unknown"):
                answer = random_answer(q.get("options", ""), q_type)
                if answer:
                    random_count += 1
                    logger.debug("题库没匹配到答案，已随机作答: {}", str(q.get("title"))[:40])
            q.setdefault("answerField", {})[f"answer{q['id']}"] = answer
            emit(answer_line(_qi, q_type, answer, q.get("title")))
        if random_count:
            logger.info("作业有 {} 题没搜到答案，已随机作答", random_count)
        return None

    def study_homework(self, study_url: str, plan: Optional[dict] = None,
                       course: Optional[dict] = None) -> bool:
        """完成「任务中心 -> 作业」任务点（planType=4）."""
        #
        # 与章节测验的区别：学习页是新版 mooc2/work/dowork，提交接口是
        # addStudentWorkNewWeb（表单 action 自带 token / totalQuestionNum）；
        # 章节测验用的 mooc-ans/api/work 对课程级作业返回 403，不能复用。
        #
        # 这里只负责"作答并被接口接受"；是否算完成由上层 wait_plan_finished
        # 重新读任务引擎状态裁定，接口 200 / status=true 单独不算完成。
        name = (plan or {}).get("name") or "作业"

        if self._recently_submitted(plan):
            logger.info("作业 [{}] 最近已提交过，等平台同步，本次不重复提交", name)
            return True

        try:
            resp = self.session.get(
                study_url, timeout=TASK_CENTER_TIMEOUT, allow_redirects=True
            )
        except Exception as e:
            logger.warning("作业学习页打开失败: {} - {}", name, e)
            return False
        if getattr(resp, "status_code", 0) != 200:
            logger.warning("作业学习页打开失败: {} HTTP {}", name, getattr(resp, "status_code", "?"))
            return False

        page = decode_homework_page(resp.text or "")
        questions = page.get("questions") or []
        if not questions:
            logger.warning("作业页没有解析到题目（登录失效或页面改版），本次不提交: {}", name)
            return False
        logger.info("任务中心作业：{}，共 {} 题", name, len(questions))

        failure = self._fill_homework_answers(questions, course=course, task_name=name)
        if failure:
            for question in questions:
                review.update(question.get("_review_item"), "生成或复核失败，未提交")
            logger.warning("作业 [{}] 未提交：{}", name, failure)
            return False

        review_items = [q["_review_item"] for q in questions if q.get("_review_item")]
        review_status = "请求失败或平台未确认"
        try:
            if not self.confirm_submission("作业", f"{name}：共 {len(questions)} 题"):
                review_status = "用户取消，未提交"
                return False

            action = str(page.get("form_action") or "").strip()
            if not action:
                logger.warning("作业页没有提交地址，本次不提交: {}", name)
                return False
            if action.startswith("/"):
                action = "https://mooc1.chaoxing.com" + action

            payload = {
                key: value for key, value in page.items()
                if key not in ("questions", "form_action", "form_method")
            }
            payload["answerwqbid"] = page.get("answerwqbid", "")
            payload["pyFlag"] = ""
            for question in questions:
                answer_field = question.get("answerField") or {}
                payload[f"answer{question['id']}"] = answer_field.get(f"answer{question['id']}", "")
                payload[f"answertype{question['id']}"] = answer_field.get(
                    f"answertype{question['id']}", ""
                )
            # 填空题按空提交（answerEditor{id}{n} + tiankongsize{id}），与章节测验同一规则
            for question in questions:
                build_completion_fields(payload, question)

            sep = "&" if "?" in action else "?"
            submit_url = action + sep + "pyFlag=&ua=pc&formType=post&saveStatus=1&version=1"
            try:
                submitted = self.session.post(
                    submit_url,
                    data=payload,
                    timeout=TASK_CENTER_TIMEOUT,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Origin": "https://mooc1.chaoxing.com",
                        "Referer": study_url,
                    },
                )
            except Exception as e:
                logger.warning("作业提交请求失败: {} - {}", name, e)
                return False
            if getattr(submitted, "status_code", 0) != 200:
                logger.warning("作业提交失败: {} HTTP {}", name, getattr(submitted, "status_code", "?"))
                return False
            try:
                data = submitted.json()
            except ValueError:
                logger.warning("作业提交返回的不是 JSON，本次不判定成功: {}", name)
                return False
            if not isinstance(data, dict) or not data.get("status"):
                logger.warning("作业提交被平台拒绝: {} -> {}", name, str(data)[:200])
                return False

            review_status = "平台已接受，等待任务状态复查"
            self._mark_submitted(plan)
            logger.info("作业已提交（等待任务中心状态复查）: {}", name)
            return True

        finally:
            for item in review_items:
                review.update(item, review_status)

    def study_ai_practice(self, study_url: str, plan: Optional[dict] = None) -> bool:
        """续接/完成一次 AI 实践，并在达到最低分后才返回 True."""
        #
        # 对话请求本身不是最终提交；只有确认模式通过后调用 ``answer/submit``，
        # 并且提交后的 load-data 读回分数，才会进入完成状态。任务中心的 isFinish
        # 仍由上层 ``wait_plan_finished`` 再次确认。
        self._set_outcome(TaskOutcome.FAILED)
        try:
            page = self.session.get(
                study_url, allow_redirects=True, timeout=TASK_CENTER_TIMEOUT
            )
        except Exception as e:
            logger.warning("AI实践入口页打开失败: {}", e)
            return False
        if getattr(page, "status_code", 0) != 200:
            logger.warning("AI实践入口页打开失败: HTTP {}", getattr(page, "status_code", "?"))
            return False
        final_url = getattr(page, "url", None) or study_url
        params = self._ai_page_params(final_url, getattr(page, "text", ""))
        if not params:
            if "situationalDialogue" in final_url or "situationalDialogue" in (getattr(page, "text", "") or ""):
                # 新版"情景对话"是另一套接口（/mobile/situationalDialogue/*），与思维阶梯不通用
                logger.warning(
                    "该 AI 实践是新版「情景对话」(situationalDialogue)，暂未适配，本次跳过"
                )
                print("      · 该 AI 实践是新版「情景对话」，暂不支持，请到学习通 App 手动完成")
            else:
                logger.warning(
                    "AI实践入口页缺少 courseid/clazzid/cpi/publishRelationUuid/aiEnc（最终地址: {}）",
                    final_url,
                )
            return False

        data = self._ai_load_data(params)
        if data is None:
            return False

        for attempt in range(self.ai_practice_max_rounds):
            if interrupt.should_stop():
                return False

            # 第一次优先续接服务端已有的未完成记录；后续低分重答才初始化新记录。
            if attempt > 0 or self._ai_record_submitted(data) or not data.get("recordUuid"):
                init_data = self._ai_init(params)
                if init_data is None:
                    return False
                record_uuid = str(init_data.get("recordUuid") or data.get("recordUuid") or "")
                data = self._ai_load_data(params, record_uuid) or self._ai_load_data(params)
                if data is None:
                    return False
            record_uuid = str(data.get("recordUuid") or "")
            if not record_uuid:
                logger.warning("AI实践状态缺少 recordUuid，按失败处理")
                return False

            if self._ai_record_submitted(data):
                score = self._ai_score(data, record_uuid)
                if score is not None and score >= self.ai_practice_min_score:
                    average = self._ai_average_score(data)
                    if (average is not None and average < self.ai_practice_min_score
                            and attempt + 1 < self.ai_practice_max_rounds):
                        logger.info(
                            "AI实践已有 {:.1f} 分的记录，但练习平均分 {:.1f} 低于目标 {:.1f}，开新一轮补答",
                            score, average, self.ai_practice_min_score,
                        )
                        # 必须直接开新一轮：这一条记录已经提交过，落下去会把同一条
                        # 记录再 submit 一次（平台可能直接拒绝，白跑一轮还报失败）。
                        time.sleep(1.0)
                        continue
                    logger.info("AI实践已有有效成绩 {:.1f}，无需重复提交", score)
                    self._set_outcome(TaskOutcome.COMPLETED)
                    return True

            completion = self._ai_completion_state(data)
            turn = self._ai_pending_turn(data)
            last_answer = ""
            turn_count = 0
            summary_seen = False
            topic_count = sum(
                len(dimension.get("topicList") or [])
                for dimension in data.get("dimensionList") or []
                if isinstance(dimension, dict)
            )
            # 平台的判分是它自己的大模型，同一道题会反复追问；知识点多的时候
            # 一局可能要答几十题（实测 9 个知识点答过 55 题仍被追问），
            # 这里给足余量，但仍有上限避免死循环。
            max_turns = max(30, min(200, topic_count * 8 + 30))

            if turn is None and completion is not True:
                # 与前端 iniQuestion 一致：已有记录但没有 messageList 时发送空消息，
                # 让平台生成第一道题；这不是提交动作。
                turn = self._ai_stream(params, record_uuid, "")
                if turn is None:
                    return False

            # 平台已经给出总结、且快照里没有待答题目：这一局已经结束了。
            # 旧实现会再发一条空消息"让平台出第一题"，平台就继续生成新题，
            # 于是对着一个已经结束的局空转到轮数上限（实测白跑 23 分钟）。
            ready_to_submit = turn is None and completion is True
            if ready_to_submit:
                logger.info("AI实践这一局平台已经结束，直接提交本轮成绩")

            # 平台是拿自己的大模型判分的：同一道题同一个答案会被反复判错。
            # 记下每道题已经试过的答案，重试时换一个，才可能跳出死循环。
            tried_answers: dict = {}
            attempts: dict = {}
            stalled = 0
            while not ready_to_submit and turn_count < max_turns:
                if interrupt.should_stop():
                    return False
                if not self._ai_turn_has_question(turn):
                    summary_seen = any(
                        "SummaryTopic" in mark for mark in (turn or {}).get("special_marks", [])
                    )
                    # SSE 这一帧没带问题不代表练完了：平台的状态快照里可能还有 pending 题，
                    # 这时候提交会拿到一个"没答完"的低分（实测 60 分那轮就是提前提交）
                    pending_turn = self._ai_pending_turn(data)
                    if pending_turn is not None:
                        turn = pending_turn
                        continue
                    if completion is True or summary_seen:
                        break
                    logger.warning("AI实践 SSE 没有下一道可回答的问题，按失败处理")
                    return False

                question_key = self._ai_question_key(turn)
                used = tried_answers.setdefault(question_key, set())
                attempts[question_key] = attempts.get(question_key, 0) + 1
                try:
                    answer = self._ai_answer(turn, data, exclude=used)
                    item = None
                    if self._ai_turn_type(turn) == "shortanswer":
                        item = review.record(
                            review.KIND_PRACTICE, answer,
                            course="", task=(plan or {}).get("name") or "",
                            status="待发送给平台评分",
                        )
                        if not item:
                            logger.warning("AI实践复核记录写入失败，本次不发送")
                            return False
                except Exception as e:
                    logger.warning("AI实践生成答案失败: {}", e)
                    return False
                used.add(self._ai_answer_core(answer))
                last_answer = answer
                turn_count += 1
                emit(answer_line(turn_count, self._ai_turn_type(turn), answer,
                                 self._ai_turn_title(turn)))
                if self._ai_turn_type(turn) == "shortanswer":
                    emit_block(f"AI实践简答 {turn_count}", answer)
                if turn_count > 1:
                    time.sleep(1.0)
                before_msgs = len((data or {}).get("messageList") or [])
                try:
                    next_turn = self._ai_stream(params, record_uuid, answer)
                except Exception:
                    review.update(item, "请求失败或平台未确认")
                    raise
                review.update(item, "平台返回对话响应" if next_turn is not None else "请求失败或平台未确认")
                if next_turn is None:
                    return False

                refreshed = self._ai_load_data(params, record_uuid)
                if refreshed is None:
                    return False
                data = refreshed
                completion = self._ai_completion_state(data)
                if len((data or {}).get("messageList") or []) > before_msgs:
                    stalled = 0
                else:
                    stalled += 1
                # 知识点答完之后，平台还会把最后一道题推回来：它既不再收录我们的
                # 作答（messageList 不再增长），也不会主动结束这一局。实测会一直空转，
                # 甚至"错/对"来回换十几次。这时候收手提交才是对的。
                if completion is True and (
                    attempts.get(question_key, 0) >= self.AI_MAX_TRIES_PER_QUESTION
                    or stalled >= self.AI_STALL_LIMIT
                ):
                    logger.info(
                        "AI实践平台已判定答完（同一道题作答 {} 次、连续 {} 次无新消息），直接提交本轮",
                        attempts.get(question_key, 0), stalled,
                    )
                    break
                if self._ai_turn_has_question(next_turn):
                    turn = next_turn
                    continue
                summary_seen = any(
                    "SummaryTopic" in mark for mark in next_turn.get("special_marks", [])
                )
                pending_turn = self._ai_pending_turn(data)
                if pending_turn is not None:
                    turn = pending_turn
                    continue
                if completion is True or summary_seen:
                    break
                # 服务端偶尔先落库再返回下一题，尝试从状态快照续接一次；仍无题就失败。
                turn = self._ai_pending_turn(data)
                if turn is None:
                    logger.warning("AI实践未得到完成证据或下一道题，按失败处理")
                    return False
            else:
                # 只有"真的答满了轮数还没结束"才算失败；ready_to_submit 是跳过作答直接提交
                if not ready_to_submit:
                    logger.warning("AI实践对话超过安全轮数上限，按失败处理")
                    return False

            if completion is not True and not summary_seen:
                logger.warning("AI实践对话结束但没有明确完成证据，不提交")
                return False

            preview = (
                f"第 {attempt + 1} 轮，共回答 {turn_count} 个问题；"
                f"最后回答：{last_answer[:220]}"
            )
            if not self._ai_submit(params, record_uuid, preview):
                return False
            # 平台不会自己评估：必须请求一次质量评估报告，成绩才算出来并回填，
            # 否则 answerRecords 会一直停在"未评估"（实测等了 10 分钟都没有）。
            report_score = self._ai_end_report(params, record_uuid)
            if report_score is not None:
                # 报告已经给了成绩：读一次状态（remainAnswerCount 等）就走人，
                # 不再空等状态接口回填（旧实现固定轮询 19 次×30s≈10 分钟）。
                refreshed = self._ai_load_data(params, record_uuid)
                if refreshed is not None:
                    data = refreshed
                score = report_score
            else:
                # 报告没给成绩（平台偶发）：退回状态接口轮询
                score, data = self._ai_wait_for_score(params, record_uuid)
            if score is None or data is None:
                logger.warning("AI实践提交后平台还没出评估结果，本次不算完成")
                return False
            logger.info(
                "AI实践第 {}/{} 轮提交成绩：{:.1f}（目标 {:.1f}）",
                attempt + 1, self.ai_practice_max_rounds, score, self.ai_practice_min_score,
            )
            average = self._ai_average_score(data)
            logger.info(
                "AI实践练习记录：{} | 平均 {:.1f} | 本轮 {:.1f} | 目标 {:.1f}",
                "、".join(f"{value:.0f}" for value in self._ai_record_scores(data)) or "无",
                average if average is not None else score,
                score,
                self.ai_practice_min_score,
            )
            if score >= self.ai_practice_min_score and (
                average is None or average >= self.ai_practice_min_score
            ):
                self._set_outcome(TaskOutcome.COMPLETED)
                return True

            try:
                remain = int(float(data.get("remainAnswerCount")))
            except (TypeError, ValueError):
                remain = 1
            if attempt + 1 >= self.ai_practice_max_rounds or remain <= 0:
                if score >= self.ai_practice_min_score:
                    # 本轮已经达标，只是历史低分把平均分拖下来了；重答次数用尽就
                    # 如实汇报，不再空转（平台自己的成绩字段已含本轮的分）。
                    logger.warning(
                        "AI实践本轮 {:.1f} 已达标，但练习平均分 {:.1f} 未到目标 {:.1f}，重答次数已用尽",
                        score, average if average is not None else score,
                        self.ai_practice_min_score,
                    )
                    self._set_outcome(TaskOutcome.COMPLETED)
                    return True
                logger.warning("AI实践成绩 {:.1f} 未达到目标，重答次数已用尽", score)
                return False
            logger.info("AI实践成绩未达标，准备开始第 {} 轮重答", attempt + 2)
            time.sleep(1.0)

        return False


def plan_type_name(plan_type: Any) -> str:
    try:
        return PLAN_TYPE_NAMES.get(int(plan_type), f"未知类型{plan_type}")
    except (TypeError, ValueError):
        return f"未知类型{plan_type}"
