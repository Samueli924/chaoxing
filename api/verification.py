"""Read-only, fail-closed reconciliation of course task completion."""
from collections import Counter

from api.decode import _extract_marg, _is_true, _NO_CARD_RE
from api.runtime import runtime


def _progress(value):
    if not isinstance(value, dict):
        return None
    done, total = value.get("done"), value.get("total")
    if type(done) is not int or type(total) is not int or not 0 <= done <= total:
        return None
    return {"done": done, "total": total}


def verify_course(chaoxing, course):
    """Never call get_job_list: that method can mark empty pages as studied.

    Aggregate progress and raw pending attachments must agree. An unsupported
    task, unreadable card, locked chapter or missing aggregate cannot pass.
    This verifies task completion, not answer correctness or reading quality.
    """
    report = {"course": course.get("title", ""), "complete": False,
              "chapters": 0, "chapters_checked": 0, "progress": None,
              "pending": {}, "attachments": {}, "errors": []}
    pending, attachments = Counter(), Counter()
    try:
        if runtime.should_stop():
            report["errors"].append("校验已停止")
            return report
        before = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
        points = before.get("points") or []
        report["chapters"] = len(points)
        if not points:
            report["errors"].append("未读取到章节")
        baseline = _progress(before.get("jobProgress"))
        if baseline is None:
            report["errors"].append("缺少有效的课程总进度")
        for index, point in enumerate(points, 1):
            if runtime.should_stop():
                report["errors"].append("校验已停止")
                break
            ended, valid = False, True
            seen = set()
            for tab, html in chaoxing.iter_card_pages(course, point):
                if runtime.should_stop():
                    report["errors"].append("校验已停止")
                    valid = False
                    break
                if "章节未开放" in html:
                    report["errors"].append(f"第{index}章未开放")
                    valid = False
                    break
                data = _extract_marg(html)
                if not isinstance(data, dict):
                    if _NO_CARD_RE.search(html):
                        ended = True
                    else:
                        report["errors"].append(f"第{index}章页面无法识别")
                        valid = False
                    break
                cards = data.get("attachments")
                if cards is None:
                    cards = []
                if not isinstance(cards, list) or any(not isinstance(a, dict) for a in cards):
                    report["errors"].append(f"第{index}章附件格式异常")
                    valid = False
                    break
                for position, card in enumerate(cards):
                    kind = str(card.get("type") or "unknown").lower()
                    key = (kind, str(card.get("jobid") or card.get("objectId") or (tab, position)))
                    if key in seen:
                        continue
                    seen.add(key)
                    attachments[kind] += 1
                    is_task = _is_true(card.get("job")) or (kind in ("read", "video") and bool(card.get("jobid")))
                    if is_task and not _is_true(card.get("isPassed")):
                        pending[kind] += 1
            if valid and not ended and not runtime.should_stop():
                report["errors"].append(f"第{index}章未确认最后一个标签页")
            if valid and ended:
                report["chapters_checked"] += 1
        if not runtime.should_stop():
            after = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
            report["progress"] = _progress(after.get("jobProgress"))
            if report["progress"] is None:
                report["errors"].append("回读总进度失败")
            elif baseline != report["progress"]:
                report["errors"].append("校验期间总进度发生变化，需重新校验")
            if [p.get("id") for p in points] != [p.get("id") for p in after.get("points", [])]:
                report["errors"].append("校验期间章节清单发生变化")
    except Exception as exc:
        # Exception strings and HTTP URLs may contain credentials or account IDs.
        report["errors"].append("读取失败: " + type(exc).__name__)
    report["pending"] = dict(pending)
    report["attachments"] = dict(attachments)
    progress = report["progress"]
    report["complete"] = bool(progress is not None and progress["done"] == progress["total"]
                              and not pending and not report["errors"]
                              and report["chapters_checked"] == report["chapters"])
    return report


def confirm_video(chaoxing, course, point, job):
    """Require a fresh positive server card for this exact media task."""
    try:
        for _, html in chaoxing.iter_card_pages(course, point):
            if runtime.should_stop():
                return False
            marg = _extract_marg(html)
            if not isinstance(marg, dict):
                continue
            for card in marg.get("attachments", []):
                if not isinstance(card, dict):
                    return False
                matches = (bool(job.get("jobid")) and str(card.get("jobid")) == str(job["jobid"])) or (
                    bool(job.get("objectid")) and card.get("objectId") == job["objectid"])
                if matches:
                    return _is_true(card.get("isPassed"))
    except Exception:
        return False
    return False
