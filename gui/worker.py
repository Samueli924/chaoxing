# -*- coding: utf-8 -*-
"""
后台刷课进程：由 gui/server.py 启动，从标准输入读取一行 JSON 配置，
复用项目原有的 main.py / api 逻辑完成任务点，并把进度以事件行的形式写到标准输出。

运行方式（工作目录为项目根目录）: python -m gui.worker
"""
import itertools
import json
import sys
import threading
import time
import traceback

EV_PREFIX = "@@CX "
_out = sys.stdout
_out_lock = threading.Lock()
# 防止项目代码里的 print 混进事件流
sys.stdout = sys.stderr


def emit(t: str, **kw):
    kw["t"] = t
    line = EV_PREFIX + json.dumps(kw, ensure_ascii=False, default=str)
    with _out_lock:
        _out.write(line + "\n")
        _out.flush()


import main as cx  # noqa: E402  项目根目录下的 main.py
import api.base as cx_base  # noqa: E402
from api.answer import Tiku, DummyTiku  # noqa: E402
from api.base import Chaoxing, Account  # noqa: E402
from api.config import GlobalConst  # noqa: E402
from api.exceptions import LoginError  # noqa: E402
from api.logger import logger  # noqa: E402
from api.notification import Notification  # noqa: E402
from api.process import increase_learning_count_for_course  # noqa: E402
from gui.platform_utils import keep_awake_self  # noqa: E402


def _log_sink(message):
    r = message.record
    emit("log", level=r["level"].name, msg=r["message"], ts=r["time"].strftime("%H:%M:%S"))


logger.add(_log_sink, level="INFO", format="{message}")

_ctx = threading.local()
_jid = itertools.count(1)


def course_key(course: dict) -> str:
    return f"{course['courseId']}_{course['clazzId']}"


# ---- 把进度条换成事件上报 -------------------------------------------------
class GuiBar:
    def __init__(self, total=0, initial=0, desc="", **_kw):
        self.total = total or 0
        self.n = initial or 0
        self.leave = False
        self.jid = getattr(_ctx, "jid", None)
        self._last = 0.0
        self._emit(force=True)

    def _emit(self, force=False):
        now = time.time()
        if force or now - self._last >= 1:
            self._last = now
            emit("progress", jid=self.jid, n=int(self.n), total=int(self.total))

    def refresh(self):
        self._emit()

    def update(self, k=1):
        self.n += k
        self._emit()

    def close(self):
        self._emit(force=True)

    def clear(self, *a, **k):
        pass

    @staticmethod
    def write(s, file=None, **_kw):
        sys.stderr.write(str(s) + "\n")


cx_base.tqdm = GuiBar

# ---- 任务点开始/结束上报 ---------------------------------------------------
_KINDS = {
    "study_video": "视频",
    "study_document": "文档",
    "study_work": "章节检测",
    "study_read": "阅读",
}


def _wrap_job(method_name: str, kind: str):
    orig = getattr(Chaoxing, method_name)

    def wrapper(self, _course, _job, *args, **kwargs):
        jid = next(_jid)
        prev = getattr(_ctx, "jid", None)
        _ctx.jid = jid
        name = _job.get("name") or _job.get("title") or kind
        if method_name == "study_video" and kwargs.get("_type") == "Audio":
            k = "音频"
        else:
            k = kind
        emit("job_start", jid=jid, kind=k, name=name,
             course=getattr(_ctx, "course", None), chapter=getattr(_ctx, "chapter", None),
             speed=kwargs.get("_speed"))
        result = "ERROR"
        try:
            r = orig(self, _course, _job, *args, **kwargs)
            result = getattr(r, "name", str(r))
            return r
        finally:
            _ctx.jid = prev
            emit("job_end", jid=jid, result=result)

    setattr(Chaoxing, method_name, wrapper)


for _m, _k in _KINDS.items():
    _wrap_job(_m, _k)

# ---- 章节开始/结束上报 -----------------------------------------------------
_orig_process_chapter = cx.process_chapter


def _process_chapter(chaoxing, course, point, speed):
    key = course_key(course)
    _ctx.course = key
    _ctx.chapter = point["id"]
    emit("ch_start", course=key, id=point["id"])
    try:
        res = _orig_process_chapter(chaoxing, course, point, speed)
    except Exception as e:  # 原版遇到异常会让工作线程直接退出，这里改成按失败重试
        logger.error(f"章节 {point['title']} 处理出错: {type(e).__name__}: {e}")
        sys.stderr.write(traceback.format_exc())
        res = cx.ChapterResult.ERROR
    emit("ch_end", course=key, id=point["id"], result=res.name)
    return res


cx.process_chapter = _process_chapter


# ---- 主流程 ----------------------------------------------------------------
def build_tiku(tiku_conf: dict, config_path: str):
    provider = (tiku_conf.get("provider") or "").strip()
    if not provider:
        logger.info("未配置题库, 章节检测将被跳过")
        return DummyTiku(config_path=config_path)
    tiku = Tiku.get_tiku_from_config(tiku_conf, config_path=config_path)
    tiku.init_tiku()
    providers = [p.strip() for p in provider.split(",") if p.strip()]
    if any(p in ("AI", "SiliconFlow") for p in providers) and \
            str(tiku_conf.get("check_llm_connection", "true")).lower() == "true":
        logger.info("正在检查大模型连接...")
        if not tiku.check_llm_connection():
            logger.warning("大模型连接检查失败, 章节检测可能无法正确作答, 将继续运行")
    return tiku


def run(payload: dict):
    common = payload["common"]
    tiku_conf = payload.get("tiku") or {}
    notif_conf = payload.get("notification") or {}
    courses = payload["courses"]
    config_path = payload.get("config_path")

    emit("phase", msg="正在初始化题库…")
    tiku = build_tiku(tiku_conf, config_path)

    try:
        delay = float(tiku_conf.get("delay", 0) or 0)
    except ValueError:
        delay = 0
    chaoxing = Chaoxing(
        account=Account(payload.get("username", ""), payload.get("password", "")),
        tiku=tiku,
        query_delay=delay,
        work_max_retries=common.get("work_max_retries", 3),
        work_redo_enabled=common.get("work_redo_enabled", False),
    )

    notification = Notification()
    notification.config_set(notif_conf)
    notification = notification.get_notification_from_config()
    notification.init_notification()

    emit("phase", msg="正在登录…")
    state = chaoxing.login(login_with_cookies=True)
    if not state["status"]:
        raise LoginError(state["msg"])

    emit("phase", msg="正在读取课程章节…")
    tasks = []
    plan = []
    for course in courses:
        logger.info(f"正在读取课程章节: {course['title']}")
        point_list = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
        chapters = []
        for i, point in enumerate(point_list["points"]):
            tasks.append(cx.ChapterTask(point=point, index=i, course=course))
            chapters.append({"id": point["id"], "title": point["title"], "finished": point["has_finished"]})
        plan.append({"key": course_key(course), "title": course["title"],
                     "teacher": course.get("teacher", ""), "chapters": chapters})
    emit("plan", courses=plan)

    processor = cx.JobProcessor(chaoxing, tasks, common)
    processor.run()

    failed = {id(t) for t in processor.failed_tasks}
    emit("final", chapters=[
        {"course": course_key(t.course), "id": t.point["id"],
         "result": "ERROR" if id(t) in failed else t.result.name}
        for t in tasks
    ])
    logger.info("所有课程学习任务已完成")
    notification.send("chaoxing : 所有课程学习任务已完成")

    if common.get("add_learning_count"):
        emit("phase", msg="正在增加章节学习次数…")
        for course in courses:
            increase_learning_count_for_course(chaoxing, course, common)
        logger.info("所有课程章节学习次数增加完成")
        notification.send("chaoxing : 所有课程章节学习次数增加完成")

    emit("done")


def main():
    line = sys.stdin.readline()
    payload = json.loads(line or "{}")
    # 每个账号使用自己的 cookie 文件，多个账号同时运行时互不覆盖（必须在创建会话之前设置）
    if payload.get("cookies_path"):
        GlobalConst.COOKIES_PATH = payload["cookies_path"]
    keep_awake_self()
    try:
        run(payload)
    except BaseException as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        sys.stderr.write(traceback.format_exc())
        emit("error", msg=f"{e}" or type(e).__name__, kind=type(e).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
