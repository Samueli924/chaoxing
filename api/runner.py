# -*- coding: utf-8 -*-
"""命令行与网页控制台共用的运行流程：登录 → 读取课程 → 完成任务点 → 章节学习次数."""
import os
from contextlib import contextmanager
from typing import Any, Callable, Optional

from tqdm import tqdm

from api.answer import AI, SiliconFlow, Tiku, TikuFallback
from api.base import Account, Chaoxing, SessionManager
from api.config import GlobalConst as gc
from api.logger import logger
from api.notification import Notification
from api.process import increase_learning_count_for_course
from api.runtime import interactive_lock, runtime
from api.scheduler import ChapterTask, JobProcessor
from api.settings import Settings, to_bool
from api.verification import verify_course


def format_time(num, suffix='', divisor=''):
    total_time = round(num)
    sec = total_time % 60
    mins = (total_time % 3600) // 60
    hrs = total_time // 3600

    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{sec:02d}"

    return f"{mins:02d}:{sec:02d}"


@contextmanager
def tqdm_time_format():
    """让视频进度条以 分:秒 显示."""
    old_format_sizeof = tqdm.format_sizeof
    tqdm.format_sizeof = format_time
    try:
        yield
    finally:
        tqdm.format_sizeof = old_format_sizeof


def has_saved_cookies() -> bool:
    return os.path.isfile(gc.COOKIES_PATH) and os.path.getsize(gc.COOKIES_PATH) > 0


def _uses_llm(tiku: Tiku) -> bool:
    providers = tiku.providers if isinstance(tiku, TikuFallback) else [tiku]
    return any(isinstance(p, (AI, SiliconFlow)) for p in providers)


class Runner:
    def __init__(self, settings: Settings, interactive: bool = True):
        """初始化运行流程."""
        self.settings = settings
        self.interactive = interactive
        self.chaoxing: Optional[Chaoxing] = None
        self.tiku: Optional[Tiku] = None
        self.processor: Optional[JobProcessor] = None
        self.notification = self._init_notification()

    # ------------------------------------------------------------------
    def _init_notification(self):
        notification = Notification()
        # 传入非空配置，避免在未配置时再去读取无关的 config.ini
        notification.config_set(self.settings.notification or {"provider": ""})
        notification = notification.get_notification_from_config()
        notification.init_notification()
        return notification

    def notify(self, message: str) -> None:
        try:
            self.notification.send(message)
        except Exception as e:
            logger.debug(f"发送通知失败: {e}")

    def build_tiku(self, overrides: Optional[dict[str, Any]] = None) -> Tiku:
        conf = {**self.settings.tiku, **{k: v for k, v in (overrides or {}).items() if v is not None}}
        tiku = Tiku.get_tiku_from_config(conf or {"provider": ""}, config_path=self.settings.config_path)
        tiku.init_tiku()
        if tiku.DISABLE:
            if conf.get("provider"):
                logger.warning("题库不可用（请检查上方提示的配置项），章节检测将被跳过")
            return tiku
        logger.info(f"已启用题库: {tiku.name}（{'答完直接提交' if tiku.SUBMIT else '只保存答案不提交'}）")

        if _uses_llm(tiku) and to_bool(conf.get("check_llm_connection"), True):
            logger.info("正在验证大模型配置...")
            if not tiku.check_llm_connection():
                logger.error("大模型连接检查失败")
                if self.interactive:
                    with interactive_lock:
                        choice = input('大模型连接检查失败，无法准确答题，是否继续运行？(Y/n): ').strip().lower()
                    if choice not in ('', 'y', 'yes'):
                        raise RuntimeError('用户取消运行')
                else:
                    logger.warning("大模型连接检查失败，将继续运行，章节检测可能无法获取答案")
        return tiku

    # ------------------------------------------------------------------
    def login(self, username: Optional[str] = None, password: Optional[str] = None,
              use_cookies: Optional[bool] = None, tiku_overrides: Optional[dict[str, Any]] = None) -> dict:
        common = self.settings.common
        username = (username if username is not None else common.get("username", "")).strip()
        password = password if password is not None else common.get("password", "")
        if use_cookies is None:
            use_cookies = bool(common.get("use_cookies"))
            # 没有提供账号密码时，自动使用上次登录保存的 cookies
            if not (username and password) and has_saved_cookies():
                use_cookies = True
        if not use_cookies and not (username and password):
            return {"status": False, "msg": "请提供手机号和密码"}

        try:
            query_delay = max(0.0, float(self.settings.tiku.get("delay") or 0))
        except ValueError:
            query_delay = 0.0
        SessionManager.reset()
        self.tiku = self.build_tiku(tiku_overrides)
        self.chaoxing = Chaoxing(
            account=Account(username, password),
            tiku=self.tiku,
            query_delay=query_delay,
            work_max_retries=common.get("work_max_retries", 3),
        )
        return self.chaoxing.login(login_with_cookies=use_cookies)

    def list_courses(self) -> list[dict]:
        if not self.chaoxing:
            raise RuntimeError("请先登录")
        return self.chaoxing.get_course_list()

    def build_tasks(self, courses: list[dict]) -> list[ChapterTask]:
        tasks = []
        for course in courses:
            if runtime.should_stop():
                break
            runtime.set_stage(f"正在读取课程章节: {course['title']}")
            logger.info(f"正在读取课程章节: {course['title']}")
            point_list = self.chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
            # 闯关模式的课程需要提交章节检测才能解锁后续章节
            course["hasLocked"] = bool(point_list.get("hasLocked"))
            for index, point in enumerate(point_list["points"]):
                tasks.append(ChapterTask(point=point, index=index, course=course))
        return tasks

    def verify_courses(self, courses: list[dict]) -> dict[str, Any]:
        """Read every selected course without executing tasks or querying a bank."""
        if not self.chaoxing:
            raise RuntimeError("请先登录")
        runtime.set_stage("正在校验服务端任务进度")
        reports = []
        for course in courses:
            if runtime.should_stop():
                break
            reports.append(verify_course(self.chaoxing, course))
        return {"complete": bool(courses) and len(reports) == len(courses)
                and all(row["complete"] for row in reports) and not runtime.should_stop(),
                "courses": reports}

    def run(self, courses: list[dict], *, study: bool = True, add_learning_count: Optional[bool] = None,
            target_count: Optional[int] = None, options: Optional[dict[str, Any]] = None,
            ask_callback: Optional[Callable[[ChapterTask], str]] = None) -> dict[str, Any]:
        """完成所选课程的任务点，并按需增加章节学习次数，返回运行结果汇总."""
        if not self.chaoxing:
            raise RuntimeError("请先登录")
        common = dict(self.settings.common, **(options or {}))
        runtime.set_time_limit(float(common.get("max_duration") or 0))
        if add_learning_count is None:
            add_learning_count = bool(common.get("add_learning_count"))
        target_count = int(target_count or common.get("target_count") or 100)

        summary: dict[str, Any] = {"courses": len(courses), "total": 0, "done": 0, "failed": [], "skipped": [],
                                   "cancelled": 0, "skipped_works": 0, "stopped": False}
        logger.info(f"课程列表过滤完毕, 当前课程任务数量: {len(courses)}")

        if study:
            tasks = self.build_tasks(courses)
            runtime.set_stage("正在完成任务点")
            config = dict(common, interactive=self.interactive)
            self.processor = JobProcessor(self.chaoxing, tasks, config, ask_callback=ask_callback)
            with tqdm_time_format():
                self.processor.run()
            summary.update(self.processor.summary())

        if add_learning_count and not runtime.should_stop():
            runtime.set_stage("正在增加章节学习次数")
            logger.info("开始增加章节学习次数...")
            for course in courses:
                if runtime.should_stop():
                    break
                increase_learning_count_for_course(self.chaoxing, course, {"target_count": target_count})

        summary["complete"] = None
        if study:
            verification = self.verify_courses(courses)
            summary["verification"] = verification
            summary["complete"] = bool(verification["complete"] and not summary["failed"]
                                       and not summary["skipped"] and not summary["cancelled"]
                                       and not summary["skipped_works"] and not runtime.should_stop())

        summary["stopped"] = runtime.should_stop()
        summary["stop_reason"] = runtime.stop_reason
        if summary["stopped"]:
            runtime.set_stage("已停止")
        elif not study:
            runtime.set_stage("运行结束")
        elif summary["complete"]:
            runtime.set_stage("已完成并校验")
        else:
            runtime.set_stage("未完成或未通过校验")
        return summary


def format_summary(summary: dict[str, Any]) -> str:
    lines = [
        "========== 运行结果 ==========",
        f"课程数: {summary.get('courses', 0)}  章节数: {summary.get('total', 0)}  "
        f"完成: {summary.get('done', 0)}  失败: {len(summary.get('failed', []))}  "
        f"未开放跳过: {len(summary.get('skipped', []))}",
    ]
    if summary.get("verification_only"):
        lines = ["========== 只读任务校验 ==========", f"课程数: {summary.get('courses', 0)}"]
    if summary.get("complete") is not None:
        lines.append("服务端任务校验：" + ("通过" if summary["complete"] else "未通过"))
    for row in summary.get("verification", {}).get("courses", []):
        progress = row.get("progress")
        value = f'{progress["done"]}/{progress["total"]}' if progress else "未知"
        lines.append(f'{row["course"]}: 任务点 {value}，待完成 {sum(row["pending"].values())}')
        lines.extend("  " + error for error in row["errors"])
    if summary.get("skipped_works"):
        lines.append(f"因未配置可用题库而跳过的章节检测: {summary['skipped_works']} 个")
    if summary.get("failed"):
        lines.append("失败的章节: " + "；".join(summary["failed"][:20]))
    if summary.get("skipped"):
        lines.append("未开放而跳过的章节: " + "；".join(summary["skipped"][:20]))
    if summary.get("stopped"):
        lines.append("已达到运行时限" if summary.get("stop_reason") == "time_limit" else "运行已被手动停止")
    return "\n".join(lines)
