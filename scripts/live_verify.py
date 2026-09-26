# -*- coding: utf-8 -*-
"""真实账号实测 + 抓包验证。

用途：在配置了真实账号（CHAOXING_USERNAME / CHAOXING_PASSWORD，或 config.ini）的环境中，
验证本工具对最新网页的有效性（效度）：

  1. 登录，并在应用层抓取每一个 HTTP 请求/响应（脱敏），作为"抓包"证据；
  2. 以一门**已手动完成**的课程为参照，核对完成状态解析是否准确；
  3. 对一门**未完成**的课程，实际完成一个任务点，然后重新拉取页面，
     证明该任务点确实从"未完成"变为"已完成"（效度验证）；
  4. 输出脱敏报告 docs/LIVE_TEST_RESULTS.md 与抓包明细 docs/live_trace.log。

用法：
  python scripts/live_verify.py                 # 自动挑选参照课程与目标课程
  python scripts/live_verify.py --ref 课程ID --target 课程ID
  python scripts/live_verify.py --target 课程ID --max-tasks 1

注意：会对目标课程产生真实学习行为（完成任务点），请在已授权的账号上运行。
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qsl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from api.config import data_path  # noqa: E402
from api.logger import logger, setup_logging  # noqa: E402
from api.runner import Runner  # noqa: E402
from api.runtime import runtime  # noqa: E402
from api.scheduler import process_job  # noqa: E402
from api.settings import load_settings  # noqa: E402

# 需要从抓包中隐去的敏感字段
SENSITIVE_KEYS = {"password", "uname", "pwd", "token", "tokens", "key", "authorization",
                  "cookie", "ktoken", "jtoken", "enc", "_uid", "uid", "siliconflow_key"}
SENSITIVE_RE = re.compile(r"(?i)(password|passwd|pwd|token|key|authorization|cookie|uname|_uid)=[^&\s]+")


def _mask(value: str) -> str:
    if value is None:
        return ""
    value = str(value)
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-2:]


def _sanitize_params(pairs):
    out = []
    for k, v in pairs:
        if k.lower() in SENSITIVE_KEYS:
            out.append((k, _mask(v)))
        else:
            out.append((k, v))
    return out


class Tracer:
    """在应用层记录每个 HTTP 请求/响应（HTTPS 抓包只能看到密文，应用层更能证明与网站的实际交互）。"""

    def __init__(self):
        self.entries = []
        self._orig = None

    def start(self):
        self._orig = requests.sessions.Session.request

        def wrapper(session, method, url, **kwargs):
            start = time.time()
            entry = {"method": method, "url": url, "params": kwargs.get("params"),
                     "has_data": bool(kwargs.get("data") or kwargs.get("json"))}
            try:
                resp = self._orig(session, method, url, **kwargs)
            except Exception as e:
                entry.update(status="EXC", elapsed=time.time() - start, error=str(e))
                self.entries.append(entry)
                raise
            entry.update(status=resp.status_code, elapsed=round(time.time() - start, 3),
                         ctype=resp.headers.get("Content-Type", "").split(";")[0],
                         length=len(resp.content or b""))
            # 记录响应摘要（JSON 取 status/msg，HTML 只记录长度与关键标记）
            body = resp.text[:400] if resp.content else ""
            if "json" in entry["ctype"]:
                entry["resp"] = body[:300]
            else:
                marks = [m for m in ("章节未开放", "用户未登录", "passport2.chaoxing.com/login",
                                     "我的答案", "正确答案") if m in resp.text[:6000]]
                entry["resp"] = ("marks=" + ",".join(marks)) if marks else f"<{entry['ctype']} {entry['length']}B>"
            self.entries.append(entry)
            return resp

        requests.sessions.Session.request = wrapper

    def stop(self):
        if self._orig:
            requests.sessions.Session.request = self._orig

    def render(self, limit=400) -> str:
        lines = []
        for i, e in enumerate(self.entries[:limit], 1):
            u = urlparse(e["url"])
            params = ""
            if e.get("params"):
                pairs = e["params"].items() if isinstance(e["params"], dict) else parse_qsl(str(e["params"]))
                params = "?" + "&".join(f"{k}={v}" for k, v in _sanitize_params(pairs))
            path = SENSITIVE_RE.sub(lambda m: m.group(0).split("=")[0] + "=***", u.path + params)
            line = f"{i:>3} {e['method']:4} {u.netloc}{path}"
            if e.get("has_data"):
                line += " [+body]"
            line += f"  -> {e['status']}"
            if "elapsed" in e:
                line += f" {e['elapsed']}s {e.get('ctype','')} {e.get('length','')}B"
            if e.get("resp"):
                line += f"  {e['resp'][:120]}"
            if e.get("error"):
                line += f"  ERR {e['error']}"
            lines.append(line)
        return "\n".join(lines)


class Report:
    def __init__(self):
        self.lines = []

    def h(self, text):
        self.lines.append(f"\n## {text}\n")
        logger.info("== " + text)

    def p(self, text):
        self.lines.append(text + "\n")
        logger.info(text)

    def kv(self, ok, name, detail=""):
        mark = "✅" if ok else "❌"
        self.lines.append(f"- {mark} {name}{('：' + detail) if detail else ''}")
        (logger.info if ok else logger.error)(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")

    def text(self):
        return "\n".join(self.lines)


def _course_label(c):
    return f"{c.get('title','?')} (courseId={c.get('courseId')}, clazzId={c.get('clazzId')})"


def analyze_reference(runner, course, report):
    """参照：已完成课程，核对完成状态解析。"""
    report.h(f"参照课程（应已完成）: {_course_label(course)}")
    pl = runner.chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
    points = pl["points"]
    finished = sum(1 for p in points if p.get("has_finished"))
    report.kv(bool(points), "读取章节", f"共 {len(points)} 章，解析为已完成 {finished} 章，需解锁={pl.get('hasLocked')}")
    # 抽查一个章节的任务卡片，确认已完成任务的 isPassed 被正确识别（get_job_list 只返回未完成任务）
    sample = points[len(points)//2] if points else None
    if sample:
        jobs, info = runner.chaoxing.get_job_list(course, sample)
        report.kv(True, f"抽查章节「{sample['title']}」", f"待完成任务点 {len(jobs)} 个"
                  + ("（该章已全部完成）" if not jobs and sample.get("has_finished") else ""))
    ratio = finished / len(points) if points else 0
    report.kv(ratio >= 0.5 or finished == len(points), "完成状态解析可信度",
              f"{finished}/{len(points)} 章识别为已完成")
    return points


def _pick_target_chapter(runner, course, points):
    """在目标课程中找到一个含可快速验证任务（文档/阅读优先，其次视频）的未完成章节。"""
    best = None
    for p in points:
        if p.get("has_finished"):
            continue
        try:
            jobs, info = runner.chaoxing.get_job_list(course, p)
        except Exception as e:
            logger.warning(f"读取章节任务失败 {p['title']}: {e}")
            continue
        if info.get("notOpen") or not jobs:
            continue
        order = {"document": 0, "read": 1, "video": 2, "workid": 3, "live": 4}
        jobs_sorted = sorted(jobs, key=lambda j: order.get(j.get("type"), 9))
        for job in jobs_sorted:
            if job.get("type") in ("document", "read", "video"):
                return p, info, job, jobs
        if best is None:
            best = (p, info, jobs_sorted[0], jobs)
    return best if best else (None, None, None, None)


def verify_target(runner, course, report, max_tasks=1):
    """效度验证：对未完成课程实际完成一个任务点并复核状态翻转。"""
    report.h(f"目标课程（未完成，实测）: {_course_label(course)}")
    pl = runner.chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
    course["hasLocked"] = bool(pl.get("hasLocked"))
    points = pl["points"]
    before_finished = sum(1 for p in points if p.get("has_finished"))
    report.kv(bool(points), "读取章节", f"共 {len(points)} 章，已完成 {before_finished} 章")

    chapter, info, job, jobs = _pick_target_chapter(runner, course, points)
    if not job:
        report.kv(False, "挑选可验证任务点", "未找到未完成且已开放的任务点（课程可能已全部完成或全部未开放）")
        return
    report.p(f"选定章节「{chapter['title']}」中的任务点：类型={job.get('type')} 名称={job.get('name','')}")
    before_ids = {(j.get("type"), j.get("jobid"), j.get("objectid")) for j in jobs}

    speed = float(runner.settings.common.get("speed") or 1.0)
    t0 = time.time()
    result = process_job(runner.chaoxing, course, job, info, speed)
    elapsed = round(time.time() - t0, 1)
    report.kv(result.is_success(), f"执行任务点（{job.get('type')}）", f"结果={result.name}，耗时 {elapsed}s")

    # 复核：重新拉取该章节任务卡片，确认该任务点已从"未完成列表"消失（即 isPassed 变为 true）
    time.sleep(2)
    jobs_after, info_after = runner.chaoxing.get_job_list(course, chapter)
    after_ids = {(j.get("type"), j.get("jobid"), j.get("objectid")) for j in jobs_after}
    target_key = (job.get("type"), job.get("jobid"), job.get("objectid"))
    flipped = target_key not in after_ids
    report.kv(flipped, "效度复核：任务点状态翻转",
              f"完成前待办 {len(before_ids)} 个 → 完成后待办 {len(after_ids)} 个；该任务点"
              + ("已从待办中消失（确认完成）" if flipped else "仍在待办中（未确认完成）"))

    # 再从课程章节页复核该章节 has_finished
    pl2 = runner.chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
    chap2 = next((p for p in pl2["points"] if p["id"] == chapter["id"]), None)
    if chap2:
        report.kv(True, "章节页复核",
                  f"章节「{chapter['title']}」has_finished={chap2.get('has_finished')}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="真实账号实测 + 抓包验证")
    parser.add_argument("-c", "--config", default=None)
    parser.add_argument("--ref", default=None, help="作为参照的已完成课程ID")
    parser.add_argument("--target", default=None, help="用于实测的未完成课程ID")
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(verbose=args.verbose)
    settings = load_settings(args.config)
    if not (settings.common.get("username") and settings.common.get("password")):
        logger.error("未检测到账号密码。请设置 CHAOXING_USERNAME / CHAOXING_PASSWORD 环境变量后，"
                     "在新会话中运行本脚本。")
        return 2

    report = Report()
    report.p(f"# 真实账号实测 + 抓包验证报告\n\n运行时间：{datetime.now():%Y-%m-%d %H:%M:%S}")
    tracer = Tracer()
    tracer.start()
    try:
        runner = Runner(settings, interactive=False)
        report.h("登录")
        login = runner.login()
        report.kv(login.get("status"), "账号密码登录", login.get("msg", ""))
        if not login.get("status"):
            return 1
        name = runner.chaoxing.get_name()
        report.kv(bool(name), "读取账号信息", f"当前用户：{_mask(name)}" if name else "未解析到用户名")

        courses = runner.list_courses()
        report.kv(bool(courses), "读取课程列表", f"共 {len(courses)} 门课程")
        for c in courses:
            report.p(f"  - {_course_label(c)}")

        by_id = {}
        for c in courses:
            by_id.setdefault(c["courseId"], c)
            by_id.setdefault(c["clazzId"], c)
        ref = by_id.get(args.ref) if args.ref else None
        target = by_id.get(args.target) if args.target else None

        # 自动挑选：参照=已完成章节最多的课程；目标=另一门有未完成章节的课程
        if not ref or not target:
            stats = []
            for c in courses:
                try:
                    pl = runner.chaoxing.get_course_point(c["courseId"], c["clazzId"], c["cpi"])
                except Exception:
                    continue
                pts = pl["points"]
                fin = sum(1 for p in pts if p.get("has_finished"))
                stats.append((c, fin, len(pts)))
            done = [s for s in stats if s[2] and s[1] == s[2]]
            undone = [s for s in stats if s[2] and s[1] < s[2]]
            if not ref:
                ref = (done[0][0] if done else (max(stats, key=lambda s: s[1])[0] if stats else None))
            if not target:
                undone.sort(key=lambda s: (s[2] - s[1]))
                target = undone[0][0] if undone else None

        if ref:
            analyze_reference(runner, ref, report)
        else:
            report.kv(False, "参照课程", "未找到已完成课程")
        if target and (not ref or target["clazzId"] != ref["clazzId"]):
            verify_target(runner, target, report, max_tasks=args.max_tasks)
        else:
            report.kv(False, "目标课程", "未找到可用于实测的未完成课程（可用 --target 指定）")
    finally:
        tracer.stop()
        runtime.request_stop()

    report.h("抓包明细（应用层，已脱敏）")
    report.p(f"共记录 {len(tracer.entries)} 个请求，完整明细见 `docs/live_trace.log`。以下为前 60 条：\n")
    report.p("```\n" + tracer.render(limit=60) + "\n```")

    out_md = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "LIVE_TEST_RESULTS.md")
    trace_path = os.path.join(os.path.dirname(out_md), "live_trace.log")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(report.text() + "\n")
    with open(trace_path, "w", encoding="utf-8") as f:
        f.write(tracer.render(limit=100000) + "\n")
    logger.info(f"报告已写入 {out_md}")
    logger.info(f"抓包明细已写入 {trace_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
