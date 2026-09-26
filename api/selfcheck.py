# -*- coding: utf-8 -*-
"""只读自检.

使用配置好的账号登录，检查各个页面能否正常解析，但不完成、不提交任何任务。
用于在网站结构变动后快速定位失效的解析逻辑。

    python main.py --check
"""
import argparse
import sys
from typing import Optional

from api.base import Chaoxing, SessionManager
from api.config import GlobalConst as gc
from api.decode import decode_course_card
from api.logger import logger, setup_logging
from api.runner import Runner
from api.settings import load_settings


class Report:
    def __init__(self) -> None:
        """初始化检查结果收集器."""
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append((name, ok, detail))
        mark = "OK " if ok else "ERR"
        (logger.info if ok else logger.error)(f"[{mark}] {name} {('- ' + detail) if detail else ''}")

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.rows)

    def render(self) -> str:
        lines = ["# 学习通自检报告", ""]
        passed = sum(1 for _, ok, _ in self.rows if ok)
        lines.append(f"结果: {passed}/{len(self.rows)} 项通过")
        lines.append("")
        lines.append("| 检查项 | 结果 | 说明 |")
        lines.append("| --- | --- | --- |")
        for name, ok, detail in self.rows:
            lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail or ''} |")
        return "\n".join(lines)


def _check_cards(chaoxing: Chaoxing, course: dict, point: dict, report: Report) -> Optional[dict]:
    """检查某个章节的任务卡片能否解析（不完成任何任务）."""
    session = SessionManager.get_session()
    params = {
        "clazzid": course["clazzId"], "courseid": course["courseId"], "knowledgeid": point["id"],
        "ut": "s", "cpi": course["cpi"], "v": "2025-0424-1038-3", "mooc2": 1, "num": 0,
    }
    try:
        resp = session.get("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards", params=params)
    except Exception as e:
        report.add("章节任务卡片(knowledge/cards)", False, f"请求失败: {e}")
        return None
    jobs, info = decode_course_card(resp.text)
    if info.get("notOpen"):
        report.add("章节任务卡片(knowledge/cards)", True, "章节未开放（解析正常）")
        return info
    ok = bool(info) or bool(jobs)
    report.add("章节任务卡片(knowledge/cards)", ok,
               f"解析出 {len(jobs)} 个任务点, 字段: {', '.join(k for k in ('ktoken','cpi','reportUrl','knowledgeid') if info.get(k))}")
    return info


def run_selfcheck(settings, interactive: bool = True) -> int:
    """执行只读自检，返回进程退出码（0 表示全部通过）."""
    report = Report()
    runner = Runner(settings, interactive=interactive)
    common = settings.common

    logger.info("开始只读自检（不会完成或提交任何任务）...")
    try:
        result = runner.login(tiku_overrides={"provider": ""})
    except Exception as e:
        report.add("登录", False, f"{type(e).__name__}: {e}")
        _finish(report)
        return 1
    report.add("登录", result.get("status", False), result.get("msg", ""))
    if not result.get("status"):
        _finish(report)
        return 1

    name = ""
    try:
        name = runner.chaoxing.get_name()
    except Exception as e:
        logger.debug(f"获取用户名失败: {e}")
    report.add("读取账号信息(accountManage)", bool(name), f"当前用户: {name}" if name else "未能解析到用户名")

    try:
        courses = runner.list_courses()
        report.add("课程列表(courselistdata)", bool(courses), f"共 {len(courses)} 门课程")
    except Exception as e:
        report.add("课程列表(courselistdata)", False, f"{type(e).__name__}: {e}")
        _finish(report)
        return 1

    # 若指定了课程，则优先检查这些课程，否则检查前两门
    wanted = set(common.get("course_list") or [])
    if wanted:
        target_courses = [c for c in courses if c["courseId"] in wanted or c["clazzId"] in wanted] or courses[:2]
    else:
        target_courses = courses[:2]

    for course in target_courses:
        logger.info(f"检查课程: {course['title']}")
        try:
            point_list = runner.chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
        except Exception as e:
            report.add(f"课程章节 - {course['title']}", False, f"{type(e).__name__}: {e}")
            continue
        points = point_list.get("points", [])
        finished = sum(1 for p in points if p.get("has_finished"))
        report.add(f"课程章节 - {course['title']}", bool(points),
                   f"{len(points)} 章节, 已完成 {finished}, 需解锁: {'是' if point_list.get('hasLocked') else '否'}")
        # 找一个未完成的章节检查任务卡片解析
        target_point = next((p for p in points if not p.get("has_finished")), points[0] if points else None)
        if target_point:
            info = _check_cards(runner.chaoxing, course, target_point, report)
            _check_media(runner.chaoxing, course, target_point, info, report)

    _finish(report)
    return 0 if report.ok else 1


def _check_media(chaoxing: Chaoxing, course: dict, point: dict, info: Optional[dict], report: Report) -> None:
    """如果章节里有视频任务，检查视频信息接口是否可解析."""
    if not info or info.get("notOpen"):
        return
    try:
        jobs, job_info = chaoxing.get_job_list(course, point)
    except Exception as e:
        logger.debug(f"获取任务点列表失败: {e}")
        return
    video = next((j for j in jobs if j.get("type") == "video" and j.get("objectid")), None)
    if not video:
        return
    # 与学习时的请求一致：该接口校验播放器页面的 Referer，缺少时返回 403
    headers = gc.AUDIO_HEADERS if video.get("audio") else gc.VIDEO_HEADERS
    data = chaoxing._fetch_media_status(SessionManager.get_session(), video, headers)
    ok = isinstance(data, dict) and data.get("status") == "success" and bool(data.get("dtoken"))
    report.add("视频信息(ananas/status)", ok,
               f"时长 {data.get('duration')}s" if ok else f"返回: {str(data)[:80]}")


def _finish(report: Report) -> None:
    from api.config import data_path
    path = data_path("selfcheck_report.md")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(report.render() + "\n")
        logger.info(f"自检报告已保存: {path}")
    except OSError as e:
        logger.warning(f"保存自检报告失败: {e}")
    logger.info("\n" + report.render())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="学习通只读自检")
    parser.add_argument("-c", "--config", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)
    settings = load_settings(args.config)
    return run_selfcheck(settings, interactive=sys.stdin.isatty() if sys.stdin else False)


if __name__ == "__main__":
    sys.exit(main())
