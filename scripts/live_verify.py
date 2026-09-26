# -*- coding: utf-8 -*-
"""真实账号端到端实测 + 抓包记录。

默认只读：登录 → 读取课程 → 逐章节读取任务卡片，核对本工具解析出的"待完成任务点"与
章节页顶部"已完成任务点: 完成数/总数"（学习通服务端自己的统计）是否一致。

加 --run：只读核对之后，用本工具实际完成所选课程（与 main.py 相同的 Runner 流程），
完成后再次核对服务端计数，并逐个读取章节检测的成绩。

输出（均已脱敏，不含手机号、密码、姓名、用户ID、学校ID 等）：
  docs/LIVE_TEST_RESULTS.md       报告
  <数据目录>/live_trace.jsonl     每个 HTTP 请求的记录（方法、地址、参数、状态码、耗时、响应摘要）
  <数据目录>/live_result.json     报告所用的原始统计

用法：
  python scripts/live_verify.py                    只读核对全部课程
  python scripts/live_verify.py --run              核对后完成全部课程（视频按真实时长播放，耗时较长）
  python scripts/live_verify.py --run -l 课程ID     只完成指定课程
  python scripts/live_verify.py --scores           只读核对并读取各章节检测成绩
  python scripts/live_verify.py --report-only      用上次保存的统计与抓包重新生成报告

账号与题库配置与 main.py 相同（config.ini 或 CHAOXING_* 环境变量）。
注意：--run 会在账号上产生真实的学习记录并提交章节检测，请只在你有权使用的账号上运行。
"""
import argparse
import json
import os
import platform
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from urllib.parse import parse_qsl, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests  # noqa: E402

from api.base import WORK_URL, SessionManager  # noqa: E402
from api.config import data_path  # noqa: E402
from api.decode import _extract_marg, decode_course_card, decode_work_result  # noqa: E402
from api.logger import logger, setup_logging  # noqa: E402
from api.runner import Runner, format_summary  # noqa: E402
from api.runtime import runtime  # noqa: E402
from api.settings import load_settings, split_course_list  # noqa: E402

REPORT_PATH = os.path.join(ROOT, "docs", "LIVE_TEST_RESULTS.md")
TRACE_PATH = data_path("live_trace.jsonl")
RESULT_PATH = data_path("live_result.json")

# 需要脱敏的参数名（不区分大小写）
SENSITIVE_KEYS = {
    "uname", "password", "pwd", "token", "enc", "jtoken", "ktoken", "userid", "uid", "_uid", "fid", "k",
    "cpi", "clazzid", "classid", "enc_work", "worktimesenc", "dtoken", "key", "mtenc", "defenc", "qnenc",
    "workanswerid", "videofacecaptureenc", "attdurationenc", "otherinfo", "userId".lower(),
}
HEX32_RE = re.compile(r"\b[0-9a-f]{32}\b")


def mask(value) -> str:
    text = "" if value is None else str(value)
    if len(text) <= 4:
        return "***"
    return text[:2] + "***" + text[-2:]


class Scrubber:
    """把已知的敏感值（手机号、用户ID、学校ID、班级ID 等）以及 32 位十六进制令牌替换为掩码."""

    def __init__(self):
        self.values: set[str] = set()

    def add(self, *values) -> None:
        for value in values:
            text = str(value or "").strip()
            if len(text) >= 3:
                self.values.add(text)

    def __call__(self, text) -> str:
        text = "" if text is None else str(text)
        for value in sorted(self.values, key=len, reverse=True):
            text = text.replace(value, mask(value))
        return HEX32_RE.sub(lambda m: mask(m.group(0)), text)


class Tracer:
    """在应用层记录每个 HTTP 请求/响应，逐条写入 JSONL（HTTPS 传输层抓包只能看到密文）."""

    def __init__(self, path: str):
        self.path = path
        self._orig = None
        self._lock = threading.Lock()
        self.count = 0

    def start(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._orig = requests.sessions.Session.request
        tracer = self

        def wrapper(session, method, url, **kwargs):
            start = time.time()
            params = kwargs.get("params")
            entry = {
                "time": round(start, 3), "method": method, "url": url,
                "params": {str(k): str(v) for k, v in params.items()} if isinstance(params, dict) else params,
                "body": bool(kwargs.get("data") or kwargs.get("json")),
            }
            try:
                resp = tracer._orig(session, method, url, **kwargs)
            except Exception as e:
                entry.update(status="EXC", elapsed=round(time.time() - start, 3), error=str(e)[:200])
                tracer._write(entry)
                raise
            ctype = resp.headers.get("Content-Type", "").split(";")[0]
            entry.update(status=resp.status_code, elapsed=round(time.time() - start, 3), ctype=ctype,
                         length=len(resp.content or b""))
            if resp.url and resp.url.split("?")[0] != url.split("?")[0]:
                entry["final"] = resp.url.split("?")[0]
            text = resp.text if resp.content and len(resp.content) < 200000 else ""
            if "json" in ctype or text[:1] in ("{", "["):
                entry["resp"] = text[:400]
            else:
                marks = [m for m in ("章节未开放", "mArg = $mArg", "本次成绩", "我的答案", "doHomeWorkNew",
                                     "selectWorkQuestionYiPiYue", "已完成任务点") if m in text]
                if marks:
                    entry["marks"] = marks
            tracer._write(entry)
            return resp

        requests.sessions.Session.request = wrapper

    def _write(self, entry: dict) -> None:
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.count += 1

    def stop(self) -> None:
        if self._orig:
            requests.sessions.Session.request = self._orig


def audit_course(chaoxing, course: dict) -> dict:
    """只读核对一门课程：解析结果与服务端"已完成任务点"计数是否一致."""
    pl = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
    progress = pl.get("jobProgress") or {}
    chapters = []
    works = []
    for point in pl["points"]:
        pending_truth, parsed_pending, tabs, not_open = 0, 0, 0, False
        for num, html in chaoxing.iter_card_pages(course, point):
            jobs, info = decode_course_card(html)
            if info.get("notOpen"):
                not_open = True
                break
            if info.get("noCard"):
                break
            tabs += 1
            parsed_pending += len(jobs)
            marg = _extract_marg(html) or {}
            for att in marg.get("attachments") or []:
                if att.get("job") is True and not att.get("isPassed"):
                    pending_truth += 1
                if str(att.get("type", "")).lower() == "workid":
                    works.append({"chapter": point["title"], "attachment": att, "info": info})
            time.sleep(0.2)
        chapters.append({
            "id": point["id"], "title": point["title"], "has_finished": point["has_finished"],
            "pending_truth": pending_truth, "parsed_pending": parsed_pending, "tabs": tabs, "not_open": not_open,
        })
    pending = sum(c["pending_truth"] for c in chapters)
    return {
        "title": course["title"], "courseId": course["courseId"], "clazzId": course["clazzId"],
        "site_done": progress.get("done"), "site_total": progress.get("total"),
        "chapters": chapters, "pending": pending, "works": works,
    }


def work_scores(chaoxing, course: dict, works: list[dict]) -> list[dict]:
    """逐个打开章节检测（只读），读取已提交的成绩；尚未提交的记为 None."""
    session = SessionManager.get_session()
    scores = []
    for item in works:
        att = item["attachment"]
        jobs, info = decode_course_card("mArg = " + json.dumps({"attachments": [dict(att, job=True)],
                                                                   "defaults": {}}) + ";")
        if not jobs:
            continue
        job_info = dict(item["info"])
        try:
            resp = session.get(WORK_URL, params=chaoxing._work_params(course, jobs[0], job_info))
            result = decode_work_result(resp.text)
        except Exception as e:
            logger.warning(f"读取章节检测成绩失败 {item['chapter']}: {e}")
            continue
        graded = bool(result["questions"]) and result["score"] is not None
        scores.append({
            "chapter": item["chapter"], "name": jobs[0].get("name", ""),
            "score": result["score"] if graded else None,
            "questions": len(result["questions"]),
            "wrong": sum(1 for q in result["questions"] if q.get("correct") is False),
        })
        time.sleep(0.3)
    return scores


def summarize_trace(path: str, scrub: Scrubber) -> dict:
    """按接口统计抓包记录，并为每个接口挑一条示例."""
    stats: Counter = Counter()
    status: dict[str, Counter] = {}
    samples: dict[str, str] = {}
    video_reports = Counter()
    if not os.path.exists(path):
        return {"total": 0}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            u = urlparse(e["url"])
            path_key = re.sub(r"/\d{6,}(/[0-9a-f]{32})?$", "/{cpi}/{dtoken}", u.path)
            path_key = re.sub(r"/status/[0-9a-f]{32}$", "/status/{objectid}", path_key)
            key = f"{e['method']} {u.netloc}{path_key}"
            stats[key] += 1
            status.setdefault(key, Counter())[str(e.get("status"))] += 1
            if "/multimedia/log/" in u.path and e.get("resp"):
                m = re.search(r'"isPassed"\s*:\s*(true|false)', e["resp"])
                video_reports[m.group(1) if m else "other"] += 1
            if key not in samples:
                params = e.get("params") or {}
                pairs = params.items() if isinstance(params, dict) else parse_qsl(str(params))
                shown = "&".join(f"{k}={mask(v) if k.lower() in SENSITIVE_KEYS else v}" for k, v in pairs)
                line_text = f"{e['method']} {u.netloc}{u.path}{'?' + shown if shown else ''}"
                if e.get("body"):
                    line_text += " [+表单]"
                line_text += f"  -> {e.get('status')} {e.get('ctype', '')} {e.get('length', '')}B"
                if e.get("final"):
                    line_text += f"  (跳转到 {urlparse(e['final']).path})"
                if e.get("resp"):
                    line_text += "  " + e["resp"][:160].replace("\n", " ")
                elif e.get("marks"):
                    line_text += "  含: " + ",".join(e["marks"])
                samples[key] = scrub(line_text)
    return {"total": sum(stats.values()), "stats": stats.most_common(), "status": {k: dict(v) for k, v in status.items()},
            "samples": samples, "video_reports": dict(video_reports)}


def render_report(data: dict, scrub: Scrubber) -> str:
    lines = ["# 真实账号实测报告", ""]
    lines.append(f"- 测试时间：{data['started']} → {data.get('finished', '-')}")
    lines.append(f"- 运行环境：Python {data['python']}，{data['platform']}")
    lines.append("- 测试对象：学习通网页端（登录 passport2.chaoxing.com，课程 mooc1 / mooc2-ans）")
    lines.append(f"- 模式：{'只读核对 + 实际完成课程' if data.get('run') else '只读核对'}")
    lines.append(f"- 登录：{'成功' if data.get('login') else '失败'}（{data.get('login_msg', '')}）")
    if data.get("tiku"):
        lines.append(f"- 章节检测答题来源：{data['tiku']}")
    lines.append("")

    lines.append("## 1. 任务点解析是否准确（与服务端计数对比）")
    lines.append("")
    lines.append("章节页顶部的\"已完成任务点: 完成数/总数\"由学习通服务端统计。逐章节读取任务卡片后，"
                 "本工具判定为\"待完成\"的任务点数应当等于 总数 − 完成数。")
    lines.append("")
    lines.append("| 课程 | 时点 | 服务端 完成/总数 | 服务端待完成 | 工具解析待完成 | 一致 | 章节已完成标记与卡片一致 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for phase in ("before", "after"):
        for c in data.get(phase, []):
            site_pending = (c["site_total"] - c["site_done"]) if c.get("site_total") is not None else None
            parsed = sum(ch["parsed_pending"] for ch in c["chapters"])
            flag_mismatch = [ch for ch in c["chapters"]
                             if ch["tabs"] and ch["pending_truth"] > 0 and ch["has_finished"]]
            lines.append(f"| {c['title']} | {'运行前' if phase == 'before' else '运行后'} | "
                         f"{c.get('site_done')}/{c.get('site_total')} | {site_pending} | {parsed} | "
                         f"{'✅' if site_pending == parsed else '❌'} | {'✅' if not flag_mismatch else '❌ ' + str(len(flag_mismatch))} |")
    lines.append("")

    if data.get("run"):
        lines.append("## 2. 实际完成课程")
        lines.append("")
        lines.append("```")
        lines.append(scrub(data.get("summary_text", "")))
        lines.append("```")
        lines.append("")
    if data.get("scores"):
        scores = data.get("scores", {})
        if scores:
            lines.append("### 章节检测成绩（运行后逐个打开已批阅页面读取）")
            lines.append("")
            lines.append("| 课程 | 章节检测数 | 已提交 | 满分(100) | 最低分 | 未提交 |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for title, items in scores.items():
                got = [s["score"] for s in items if s["score"] is not None]
                full = sum(1 for s in got if s >= 100)
                lines.append(f"| {title} | {len(items)} | {len(got)} | {full} | {min(got) if got else '-'} | "
                             f"{len(items) - len(got)} |")
            lines.append("")
            low = [(t, s) for t, items in scores.items() for s in items if s["score"] is not None and s["score"] < 100]
            if low:
                lines.append("未满分的章节检测：")
                lines.append("")
                for title, s in low:
                    lines.append(f"- {title} / {s['chapter']}：{s['score']} 分（错 {s['wrong']} 题）")
                lines.append("")

    trace = data.get("trace", {})
    lines.append(f"## {'3' if data.get('run') or data.get('scores') else '2'}. 抓包记录（应用层，已脱敏）")
    lines.append("")
    lines.append(f"共记录 {trace.get('total', 0)} 个 HTTP 请求。完整记录保存在本机数据目录 `live_trace.jsonl`，不提交到仓库。")
    if trace.get("video_reports"):
        vr = trace["video_reports"]
        lines.append("")
        lines.append(f"视频进度上报共 {sum(vr.values())} 次，其中服务端返回 isPassed=true {vr.get('true', 0)} 次、"
                     f"false {vr.get('false', 0)} 次、其它 {vr.get('other', 0)} 次。")
    lines.append("")
    lines.append("| 接口 | 次数 | 状态码 |")
    lines.append("| --- | --- | --- |")
    for key, count in trace.get("stats", []):
        st = ", ".join(f"{k}×{v}" for k, v in sorted(trace["status"].get(key, {}).items()))
        lines.append(f"| `{scrub(key)}` | {count} | {st} |")
    lines.append("")
    lines.append("每个接口的一条示例：")
    lines.append("")
    lines.append("```")
    for key, _ in trace.get("stats", []):
        lines.append(trace["samples"].get(key, ""))
    lines.append("```")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="真实账号端到端实测 + 抓包记录")
    parser.add_argument("-c", "--config", default=None)
    parser.add_argument("-l", "--list", dest="course_list", default=None, help="只测试这些课程（课程ID或班级ID，逗号分隔）")
    parser.add_argument("--run", action="store_true", help="只读核对后实际完成所选课程")
    parser.add_argument("--scores", action="store_true", help="只读模式下也逐个读取章节检测成绩")
    parser.add_argument("--report-only", action="store_true", help="用上次保存的统计与抓包重新生成报告")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)

    if args.report_only:
        with open(RESULT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        scrub = Scrubber()
        scrub.add(*data.get("_scrub", []))
        data["trace"] = summarize_trace(TRACE_PATH, scrub)
        _write_report(data, scrub)
        return 0

    settings = load_settings(args.config)
    common = settings.common
    if not (common.get("username") and common.get("password")):
        logger.error("未检测到账号密码，请设置 CHAOXING_USERNAME / CHAOXING_PASSWORD 或使用 config.ini")
        return 2

    scrub = Scrubber()
    scrub.add(common["username"])
    data = {"started": datetime.now().strftime("%Y-%m-%d %H:%M"), "python": platform.python_version(),
            "platform": platform.system(), "run": args.run}
    if os.path.exists(TRACE_PATH):
        os.replace(TRACE_PATH, TRACE_PATH + ".prev")
    tracer = Tracer(TRACE_PATH)
    tracer.start()
    runner = Runner(settings, interactive=False)
    try:
        login = runner.login() if args.run else runner.login(tiku_overrides={"provider": ""})
        data.update(login=bool(login.get("status")), login_msg=login.get("msg", ""))
        if not login.get("status"):
            logger.error(f"登录失败: {login.get('msg')}")
            return 1
        cx = runner.chaoxing
        name = cx.get_name()
        scrub.add(name, cx.get_uid(), cx.get_fid())
        if runner.tiku and not runner.tiku.DISABLE:
            data["tiku"] = f"{runner.tiku.name}（{'提交' if runner.tiku.SUBMIT else '只保存'}，" \
                           f"覆盖率阈值 {runner.tiku.COVER_RATE:.0%}，最多重做 {common.get('work_max_retries')} 次）"

        courses = runner.list_courses()
        wanted = set(split_course_list(args.course_list)) if args.course_list else set()
        if wanted:
            courses = [c for c in courses if c["courseId"] in wanted or c["clazzId"] in wanted]
        for c in courses:
            scrub.add(c["cpi"], c["clazzId"])
        logger.info(f"待测试课程: {', '.join(c['title'] for c in courses)}")

        data["before"] = [audit_course(cx, c) for c in courses]
        _save(data, scrub)
        if args.scores and not args.run:
            data["scores"] = {c["title"]: work_scores(cx, c, audit["works"])
                              for c, audit in zip(courses, data["before"])}

        if args.run:
            summary = runner.run(courses)
            data["summary"] = summary
            data["summary_text"] = format_summary(summary)
            logger.info("\n" + data["summary_text"])
            _save(data, scrub)
            # 运行结束后停止信号可能已置位，核对前清除，避免影响后续只读请求
            runtime.reset()
            try:
                data["after"] = [audit_course(cx, c) for c in courses]
                _save(data, scrub)
                data["scores"] = {c["title"]: work_scores(cx, c, audit["works"])
                                  for c, audit in zip(courses, data["after"])}
            except Exception as e:
                logger.error(f"运行后核对失败: {type(e).__name__}: {e}")
        data["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _save(data, scrub)
    finally:
        tracer.stop()
        runtime.request_stop()

    data["trace"] = summarize_trace(TRACE_PATH, scrub)
    _write_report(data, scrub)
    return 0


def _save(data: dict, scrub: Scrubber) -> None:
    payload = dict(data, _scrub=sorted(scrub.values))
    os.makedirs(os.path.dirname(os.path.abspath(RESULT_PATH)), exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=str)


def _write_report(data: dict, scrub: Scrubber) -> None:
    text = scrub(render_report(data, scrub))
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"报告已写入 {REPORT_PATH}")
    logger.info(f"抓包记录: {TRACE_PATH}")


if __name__ == "__main__":
    sys.exit(main())
