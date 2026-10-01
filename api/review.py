# -*- coding: utf-8 -*-
"""AI 生成内容复核（留痕 + 查阅）."""
#
# 刷课过程中由 AI 生成、最终提交给平台的"实质性文字"——章节测验简答、作业简答、
# 主题讨论回复、AI 实践作答——都会在这里留一份可读记录：
#
# ~/.chaoxing/reviews/YYYY-MM-DD.md   人读（Markdown，可直接打开看）
# ~/.chaoxing/reviews/index.jsonl     机读（cx review 用它做翻阅）
#
# 设计原则：
# * 只记录"会被平台看到的文字"；客观题的字母答案没有复核价值，不记；
# * 记录失败阻止本项提交，其他任务可以继续；
# * 不含账号、密码、cookie 等敏感信息，只有课程名 / 任务名 / 时间 / 正文 / 平台状态。

import json
import os
import textwrap
import time
import threading
from uuid import uuid4
from typing import List, Optional

from api import paths
from api.logger import logger
from api.privacy import redact

KIND_QUIZ = "测验简答"
KIND_HOMEWORK = "作业简答"
KIND_DISCUSSION = "讨论回复"
KIND_PRACTICE = "AI实践作答"

_INDEX_NAME = "index.jsonl"
_write_lock = threading.RLock()


def index_path() -> str:
    return os.path.join(paths.reviews_dir(), _INDEX_NAME)


def markdown_path(day: Optional[str] = None) -> str:
    return os.path.join(paths.reviews_dir(), (day or _today()) + ".md")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def record(kind: str, text: str, course: str = "", task: str = "",
           status: str = "待提交", extra: Optional[dict] = None) -> Optional[dict]:
    """留一条痕。返回记录；失败返回 None，调用方必须阻止本项提交."""
    body = redact(str(text or "").strip())
    if not body:
        return None
    item = {
        "ts": _now(),
        "day": _today(),
        "kind": str(kind or "AI 生成"),
        "course": redact(course or ""),
        "task": redact(task or ""),
        "status": str(status or ""),
        "chars": len(body),
        "text": body,
        "submission_id": str((extra or {}).get("submission_id") or uuid4().hex),
    }
    try:
        with _write_lock:
            os.makedirs(paths.reviews_dir(), exist_ok=True)
            os.chmod(paths.reviews_dir(), 0o700)
            for path, content in (
                (markdown_path(item["day"]), _markdown_block(item)),
                (index_path(), json.dumps(item, ensure_ascii=False) + "\n"),
            ):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as fp:
                    os.chmod(path, 0o600)
                    fp.write(content)
                    fp.flush()
                    os.fsync(fp.fileno())
    except Exception as e:  # 调用方必须在 None 时阻止提交
        logger.warning("复核记录写入失败，本项不得提交: {}", e)
        return None
    logger.debug("已留痕待复核: {} · {}", item["kind"], item["task"])
    return item


def update(item: Optional[dict], status: str) -> Optional[dict]:
    """Append an honest status event; never erase the pre-request record."""
    if not item:
        return None
    return record(item["kind"], item["text"], course=item["course"], task=item["task"],
                  status=status, extra={"submission_id": item["submission_id"]})


def _markdown_block(item: dict) -> str:
    lines = [
        "",
        "## " + item["ts"] + " · " + item["kind"],
        "",
        "- 课程：" + (item["course"] or "—"),
        "- 任务：" + (item["task"] or "—"),
        "- 状态：" + (item["status"] or "—") + "（" + str(item["chars"]) + " 字）",
        "",
    ]
    lines.append(textwrap.fill(item["text"], width=76))
    lines.append("")
    return "\n".join(lines)


def load(days: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
    """读取留痕（新的在前）。days=N 只看最近 N 天."""
    items: List[dict] = []
    path = index_path()
    if not os.path.exists(path):
        return items
    try:
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return items
    latest = {}
    for number, item in enumerate(items):
        latest[item.get("submission_id") or "legacy-" + str(number)] = item
    items = list(reversed(list(latest.values())))
    if days:
        edge = time.strftime("%Y-%m-%d", time.localtime(time.time() - (int(days) - 1) * 86400))
        items = [i for i in items if str(i.get("day") or "") >= edge]
    if limit:
        items = items[: int(limit)]
    return items


def count_today() -> int:
    return len([i for i in load() if i.get("day") == _today()])


def _wrap(text: str, width: int = 62, indent: str = "  ") -> str:
    return textwrap.fill(str(text or ""), width=width,
                         initial_indent=indent, subsequent_indent=indent)


def render_index(items: List[dict]) -> str:
    """列表视图：每条两行，一眼扫过."""
    if not items:
        return "\n  还没有可复核的内容。刷课过程中 AI 写的文字会自动记到这里。\n"
    out = [""]
    for idx, item in enumerate(items, 1):
        when = str(item.get("ts") or "")[11:16]
        kind = str(item.get("kind") or "")
        meta = " · ".join([x for x in (str(item.get("course") or ""),
                                       str(item.get("task") or "")) if x])
        chars = item.get("chars", 0)
        status = str(item.get("status") or "")
        out.append(f"  {idx:>2}. {kind}   {meta}")
        out.append(f"      {when} · {chars} 字 · {status}")
    out.append("")
    return "\n".join(out)

def render_item(item: dict, position: str = "") -> str:
    """单条视图：正文按 62 列折行，适合终端阅读."""
    lines = [
        "  " + "─" * 46,
        "  " + (position + " " if position else "") + str(item.get("kind", ""))
        + " · " + (str(item.get("course") or "") or "—"),
        "  任务  " + (str(item.get("task") or "") or "—"),
        "  时间  " + str(item.get("ts", "")),
        "  状态  " + str(item.get("status", "")) + "（" + str(item.get("chars", 0)) + " 字）",
        "  " + "─" * 46,
        _wrap(item.get("text", "")),
        "  " + "─" * 46,
    ]
    return "\n".join(lines)


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "q"


def review_cli(argv: Optional[List[str]] = None) -> int:
    """Cx review 的入口：翻阅 AI 生成过的文字."""
    argv = list(argv or [])
    days = None
    limit = None
    if "--all" in argv:
        days = None
    else:
        days = 1
    for i, arg in enumerate(argv):
        if arg in ("--days", "-d") and i + 1 < len(argv):
            try:
                days = int(argv[i + 1])
            except ValueError:
                days = 1
        if arg in ("--last", "-n") and i + 1 < len(argv):
            try:
                limit = int(argv[i + 1])
            except ValueError:
                limit = None

    items = load(days=days, limit=limit)
    scope = "今天" if days == 1 else (f"最近 {days} 天" if days else "全部")
    print()
    print("  复核 · AI 生成内容")
    print("  " + "─" * 46)
    print(f"  {scope} {len(items)} 条 · 记录文件 {markdown_path()}")
    print(render_index(items))
    if not items or "--list" in argv:
        return 0

    print("  输入序号看全文（n 下一条 · q 退出）")
    cursor = 0
    while True:
        raw = _ask("  ▶ ")
        if raw.lower() in ("q", "quit", "exit", ""):
            return 0
        if raw.lower() == "n":
            cursor = (cursor + 1) % len(items)
        elif raw.isdigit() and 1 <= int(raw) <= len(items):
            cursor = int(raw) - 1
        else:
            print("  ✘ 没有这个选项")
            continue
        print()
        print(render_item(items[cursor], f"[{cursor + 1}/{len(items)}]"))
        print()
        print("  n 下一条 · q 退出")
        print()
