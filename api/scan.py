# -*- coding: utf-8 -*-
"""
开始刷课前的自动扫描（默认开启，无需用户勾选）。

每次开始刷课前跑一遍，把"漏刷"的东西一次说清楚：
  * 章节：共多少节 · 已完成 · 待刷（从哪一节接着刷）；
  * 教学任务：已完成 / 可学待完成 / 未解锁 / 暂不支持；
  * 需要人管的：作业等批改、时长类文档平台不计入、新版情景对话未适配。

设计原则：
  * 全程只读，不提交任何东西；
  * 失败软着陆：扫描出错只记日志，绝不挡住刷课；
  * 输出控制在几行以内（结论先行，细节看运行日志）。
"""

from typing import List, Optional

from api.logger import logger


def chapter_row(course: dict, all_points: Optional[list], error: str = "") -> dict:
    """一门课的章节扫描结果（纯计算，不发请求）"""
    points = list(all_points or [])
    finished = [p for p in points if p.get("has_finished")]
    pending = [p for p in points if not p.get("has_finished")]
    return {
        "title": str(course.get("title") or ""),
        "total": len(points),
        "finished": len(finished),
        "pending": len(pending),
        "first": str((pending[0].get("title") if pending else "") or "")[:20],
        "error": error,
    }


def scan_task_center(chaoxing, courses: list, config: dict) -> List[dict]:
    """只读扫描任务中心：每门课的分组 / 任务点状态分类"""
    from api.task_center import (TaskCenter, SUPPORTED_PLAN_TYPES,
                                 PLAN_TYPE_DISCUSS, plan_type_name)
    rows = []
    try:
        tc = TaskCenter(chaoxing, config)
    except Exception as e:
        logger.debug("任务中心扫描初始化失败: {}", e)
        return rows
    for course in courses:
        row = {"title": str(course.get("title") or ""), "tasks": 0, "plans": 0, "done": 0,
               "todo": 0, "locked": 0, "unsupported": [], "by_type": {},
               "locked_by_type": {}, "error": ""}
        try:
            tasks = tc.get_course_tasks(course) or []
            row["tasks"] = len(tasks)
            for task in tasks:
                info = tc.open_task(task)
                if not info:
                    continue
                groups = tc.get_groups(info.get("encryTaskUserId", "")) or []
                for group in groups:
                    plans = tc.get_plans(info.get("encryTaskUserId", ""),
                                         group.get("encryptGroupId", "")) or []
                    unlocked = bool(group.get("groupAllowStudy"))
                    for plan in plans:
                        row["plans"] += 1
                        if tc.plan_finished(plan):
                            row["done"] += 1
                            continue
                        ptype = int(plan.get("planType") or -1)
                        name = plan_type_name(ptype)
                        if ptype not in SUPPORTED_PLAN_TYPES:
                            if name not in row["unsupported"]:
                                row["unsupported"].append(name)
                            continue
                        if unlocked:
                            row["todo"] += 1
                            row["by_type"][name] = row["by_type"].get(name, 0) + 1
                        else:
                            row["locked"] += 1
                            row["locked_by_type"][name] = row["locked_by_type"].get(name, 0) + 1
        except Exception as e:
            row["error"] = str(e)[:80]
            logger.debug("任务中心扫描失败: {}", e)
        rows.append(row)
    return rows


def _type_text(by_type: dict) -> str:
    order = ["作业", "主题讨论", "视频", "文档", "AI实践", "章节"]
    parts = []
    for name in order:
        if by_type.get(name):
            parts.append(f"{name} {by_type[name]}")
    for name, count in by_type.items():
        if name not in order:
            parts.append(f"{name} {count}")
    return " · ".join(parts)


def render(chapter_rows: list, tc_rows: list, chapters_enabled: bool,
           task_center_enabled: bool, only_discussion: bool = False,
           discussion_mode: str = "task") -> str:
    """扫描报告：结论先行，几行说完"""
    lines = ["  开始前扫描", "  " + "─" * 46]
    for row in chapter_rows or []:
        title = str(row.get("title") or "")
        if row.get("error"):
            lines.append("  " + title + "：章节读取失败，稍后会自动重试")
            continue
        tail = ("，从「" + str(row.get("first")) + "」接着刷") if row.get("first") else ""
        lines.append("  " + title)
        lines.append("    章节      " + str(row.get("total")) + " 节 · 已完成 "
                     + str(row.get("finished")) + " · 待刷 " + str(row.get("pending")) + tail)
    for row in tc_rows or []:
        title = str(row.get("title") or "")
        if row.get("error"):
            lines.append("  " + title + "：教学任务读取失败，稍后会自动重试")
            continue
        if not row.get("tasks"):
            continue
        lines.append("  " + title)
        head = ("    教学任务  " + str(row.get("tasks")) + " 个 · 任务点 "
                + str(row.get("plans")) + " 个（已完成 " + str(row.get("done"))
                + " · 待完成 " + str(row.get("todo")))
        if row.get("locked"):
            head += " · 未解锁 " + str(row.get("locked"))
        head += "）"
        lines.append(head)
        detail = _type_text(row.get("by_type") or {})
        if detail:
            lines.append("    待完成    " + detail)
        if only_discussion:
            if discussion_mode == "board":
                lines.append("    本次只刷  讨论区（自己挑帖子，逐条确认后发送）")
            else:
                lines.append("    本次只刷  任务里的主题讨论（自动，其它类型跳过）")
        elif discussion_mode == "board":
            lines.append("    讨论      走讨论区模式（任务里的主题讨论本次跳过）")
        for name in row.get("unsupported") or []:
            lines.append("    提醒      · " + str(name) + " 暂不支持，需要手动完成")
        todo_types = row.get("by_type") or {}
        if todo_types.get("作业"):
            if only_discussion:
                lines.append("    提醒      · " + str(todo_types["作业"])
                             + " 个作业没做（本次只刷讨论，作业要另外选「任务中心」才刷）")
            else:
                lines.append("    提醒      · " + str(todo_types["作业"])
                             + " 个作业没做，本次会自动完成（简答题要等老师批改）")
        if todo_types.get("主题讨论"):
            if discussion_mode == "board":
                lines.append("    提醒      · " + str(todo_types["主题讨论"])
                             + " 个任务里的主题讨论未做（本次改在讨论区里自己挑）")
            elif only_discussion:
                lines.append("    提醒      · " + str(todo_types["主题讨论"])
                             + " 个讨论还没回复，本次会自动回复")
            else:
                lines.append("    提醒      · " + str(todo_types["主题讨论"])
                             + " 个讨论还没回复，本次会一起回复")
        if row.get("locked_by_type") and not only_discussion:
            lines.append("    提醒      · 还有 " + _type_text(row["locked_by_type"])
                         + " 被前面的分组锁着，完成前面的任务后会自动解锁")
    lines.append("  " + "─" * 46)
    return "\n".join(lines)

def run(chaoxing, courses: list, config: dict, chapter_rows: list,
        chapters_enabled: bool, task_center_enabled: bool,
        only_discussion: bool = False, discussion_mode: str = "task") -> str:
    """执行扫描并返回可直接 print 的报告文本（永不抛异常）"""
    tc_rows = []
    if task_center_enabled:
        try:
            tc_rows = scan_task_center(chaoxing, courses, config)
        except Exception as e:
            logger.debug("任务中心扫描整体失败: {}", e)
    try:
        return render(chapter_rows, tc_rows, chapters_enabled,
                      task_center_enabled, only_discussion, discussion_mode)
    except Exception as e:
        logger.debug("扫描报告渲染失败: {}", e)
        return ""
