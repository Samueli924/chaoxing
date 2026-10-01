# -*- coding: utf-8 -*-
"""讨论区浏览 + 挑帖子回复（模式 2）."""
#
# 模式 1 是"任务里的主题讨论"：任务中心里 planType=14 的任务点，按分组顺序自动刷。
# 模式 2 就是这里：先只读统计讨论区有多少帖子 → 用户挑要回复哪几条 → 逐条给草稿、
# 确认后再发送。
#
# 接口（，groupweb.chaoxing.com）：
# * 帖子列表 GET /pc/topic/topiclist/{bbsid}/getTopicList
# ?folder_uuid=&page=1&pageSize=20&kw=&last_reply_time=&searchType=&authMappId=&isSetTop=1
# * 帖子详情与发回复复用 TaskCenter.draft_reply / submit_reply（与模式 1 同一条链路）。

import re
import textwrap
import time
from typing import List, Optional, Tuple

from api.logger import logger

TOPIC_LIST_PATH = "/pc/topic/topiclist/{bbsid}/getTopicList"
DEFAULT_PAGE_SIZE = 20
MAX_PAGES = 10
SEND_INTERVAL_SECONDS = 1.5
MAX_REVISION_HINT_LENGTH = 120


def clip_text(text, limit: int = 20) -> str:
    """按显示宽度截断（中文算 2 列），用于列表/预览行不撑爆终端."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    width = 0
    out = []
    for ch in value:
        w = 2 if ord(ch) > 127 else 1
        if width + w > limit:
            return "".join(out) + "…"
        out.append(ch)
        width += w
    return value


def normalize_topic(item: dict) -> dict:
    """把接口返回的一条帖子整理成界面要用的字段."""
    item = item or {}
    title = str(item.get("title") or "").strip()
    content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
    last = item.get("lastReply") or {}
    return {
        "uuid": str(item.get("uuid") or ""),
        "id": item.get("id"),
        "title": title or content,
        "content": content,
        "author": str(item.get("createrName") or "").strip(),
        "reply_count": int(item.get("reply_count") or 0),
        "time": str(item.get("ftime") or "").strip(),
        "last_reply_name": str(last.get("name") or "").strip(),
        "last_reply_time": str(last.get("formattime") or "").strip(),
        "tags": str(item.get("tags") or "").strip(),
        "top": bool(item.get("top")),
    }


def fetch_topics(session, bbsid: str, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                 keyword: str = "", base: str = "") -> List[dict]:
    """只读拉一页帖子；失败返回空列表（不抛异常）."""
    from api.task_center import DISCUSSION_BASE
    url = (base or DISCUSSION_BASE) + TOPIC_LIST_PATH.format(bbsid=bbsid)
    params = {
        "folder_uuid": "",
        "page": max(1, int(page or 1)),
        "pageSize": max(1, int(page_size or DEFAULT_PAGE_SIZE)),
        "kw": keyword or "",
        "last_reply_time": "",
        "searchType": "",
        "authMappId": "",
        "isSetTop": "1",
    }
    try:
        resp = session.get(url, params=params, timeout=20)
    except Exception as e:
        logger.warning("讨论区帖子列表请求失败: {}", e)
        return []
    if getattr(resp, "status_code", 0) != 200:
        logger.warning("讨论区帖子列表读取失败: HTTP {}", getattr(resp, "status_code", "?"))
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.warning("讨论区帖子列表返回的不是 JSON（可能登录失效或页面改版）")
        return []
    if not isinstance(data, dict) or not data.get("status"):
        logger.warning("讨论区帖子列表被平台拒绝: {}", str(data)[:150])
        return []
    items = data.get("datas")
    if not isinstance(items, list):
        return []
    return [normalize_topic(it) for it in items if isinstance(it, dict) and it.get("uuid")]


def fetch_all_topics(session, bbsid: str, max_pages: int = MAX_PAGES) -> Tuple[List[dict], bool]:
    """把讨论区的帖子读出来（只读，最多 max_pages 页）."""
    #
    # 返回 (帖子列表, 是否因为页数上限被截断)——截断时界面上要说"至少 N 条"，
    # 不能假装这就是全部。
    topics: List[dict] = []
    capped = False
    for page in range(1, max(1, int(max_pages)) + 1):
        batch = fetch_topics(session, bbsid, page=page)
        if not batch:
            break
        topics.extend(batch)
        if len(batch) < DEFAULT_PAGE_SIZE:
            return topics, False
        if page == max(1, int(max_pages)):
            capped = True
    return topics, capped


def resolve_bbsid(tc, course: dict) -> str:
    """拿到课程的讨论区板块 id：优先问任务中心里的主题讨论任务点."""
    direct = str((course or {}).get("bbsid") or "").strip()
    if direct:
        return direct
    try:
        from api.task_center import PLAN_TYPE_DISCUSS
        for task in tc.get_course_tasks(course) or []:
            info = tc.open_task(task)
            if not info:
                continue
            groups = tc.get_groups(info.get("encryTaskUserId", "")) or []
            for group in groups:
                plans = tc.get_plans(info.get("encryTaskUserId", ""),
                                     group.get("encryptGroupId", "")) or []
                for plan in plans:
                    if int(plan.get("planType") or -1) != PLAN_TYPE_DISCUSS:
                        continue
                    url = tc.get_study_url(info.get("encryTaskUserId", ""),
                                           plan.get("encryptPlanId"))
                    matched = re.search(r"bbsid=([0-9a-fA-F]+)", url or "")
                    if matched:
                        return matched.group(1)
    except Exception as e:
        logger.debug("从任务中心解析讨论区板块失败: {}", e)
    return ""


def render_topics(topics: List[dict], page: int = 1, offset: int = 0,
                  page_size: int = DEFAULT_PAGE_SIZE) -> str:
    """列表视图：全局编号 + 回复数 + 作者 + 时间 + 正文."""
    if not topics:
        return "\n  这一页没有帖子（可能已经翻到底，或该课程还没开放讨论区）。\n"
    lines = ["", f"  第 {page} 页 · 第 {offset + 1}–{offset + len(topics)} 条", ""]
    for idx, topic in enumerate(topics, 1):
        number = offset + idx
        who = topic.get("author") or "同学"
        when = topic.get("time") or topic.get("last_reply_time") or ""
        head = f"  {number:>3}. [{topic.get('reply_count', 0)} 回复] {who}"
        if when:
            head += f" · {when}"
        lines.append(head)
        body = textwrap.fill(topic.get("title") or topic.get("content") or "",
                             width=62, initial_indent="       ", subsequent_indent="       ")
        lines.append(body)
    lines.append("")
    return "\n".join(lines)


def parse_selection(raw: str, total: int) -> Optional[List[int]]:
    """把 "1,3,5" / "1-3" / "all" 解析成 1 基序号列表；解析不了返回 None."""
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text in ("all", "全部", "*"):
        return list(range(1, total + 1))
    picked: List[int] = []
    for part in re.split(r"[，,、\s]+", text):
        if not part:
            continue
        if "-" in part:
            left, _, right = part.partition("-")
            if not (left.strip().isdigit() and right.strip().isdigit()):
                return None
            start, end = int(left), int(right)
            if start > end:
                start, end = end, start
            picked.extend(range(start, end + 1))
        elif part.isdigit():
            picked.append(int(part))
        else:
            return None
    picked = [n for n in dict.fromkeys(picked) if 1 <= n <= total]
    return picked or None


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "q"


def _revision_hint() -> str:
    """读取一条简短重写方向；空白也允许，表示换一种写法."""
    hint = _ask("      说说怎么改（如“更短一点、少讲案例”；回车＝换一种写法） ")
    if hint.lower() in ("q", "quit", "exit"):
        return "q"
    hint = hint.strip()
    if len(hint) > MAX_REVISION_HINT_LENGTH:
        print(f"      · 优化方向过长，只取前 {MAX_REVISION_HINT_LENGTH} 个字")
        hint = hint[:MAX_REVISION_HINT_LENGTH]
    return hint or "换一种更自然、直接的说法，不要沿用上一版的句式。"


def _pick_course(courses: list, list_only: bool) -> Optional[dict]:
    if len(courses) == 1 or list_only:
        return courses[0]
    print()
    print("  选择课程")
    print("  " + "─" * 46)
    for i, c in enumerate(courses, 1):
        print(f"   {i:>2}. {c.get('title', '')}")
    print()
    raw = _ask("  ▶ 输入序号 [回车=1 · q 退出] ")
    if raw.lower() in ("q", "quit", "exit"):
        return None
    if raw == "":
        return courses[0]
    if raw.isdigit() and 1 <= int(raw) <= len(courses):
        return courses[int(raw) - 1]
    print("  ✘ 没有这个选项")
    return None


def _board_course(tc, courses: list) -> Tuple[Optional[dict], str]:
    """按顺序找第一门有讨论区的课程."""
    for course in courses:
        bbsid = resolve_bbsid(tc, course)
        if bbsid:
            return course, bbsid
    return None, ""


def _pick_reply_topics(topics, list_only):
    """Browse pages and select topic indices, preserving safe exit behavior."""
    page_size = DEFAULT_PAGE_SIZE
    page = 1
    total_pages = max(1, (len(topics) + page_size - 1) // page_size)
    picked: List[int] = []
    while True:
        offset = (page - 1) * page_size
        chunk = topics[offset:offset + page_size]
        print(render_topics(chunk, page=page, offset=offset, page_size=page_size))
        if list_only:
            return {"ok": True, "sent": 0, "skipped": 0, "reason": "只列不回复"}
        hint = "n 下一页" if page < total_pages else ""
        back = "p 上一页" if page > 1 else ""
        keys = " · ".join([k for k in (back, hint, "q 退出") if k])
        raw = _ask(f"  ▶ 选要回复的帖子（如 1,3,5 / 1-3 / all；{keys}） ")
        low = raw.lower()
        if low in ("q", "quit", "exit", ""):
            return {"ok": True, "sent": 0, "skipped": 0, "reason": "用户退出"}
        if low == "n":
            page = min(total_pages, page + 1)
            continue
        if low == "p":
            page = max(1, page - 1)
            continue
        picked = parse_selection(raw, len(topics)) or []
        if not picked:
            print("  ✘ 没看懂，可以填 1,3,5 / 1-3 / all")
            continue
        break

    return picked


def _reply_selected_topics(tc, bbsid, course, chosen):
    """Preview, rewrite and individually confirm each selected reply."""
    sent = 0
    skipped = 0
    for index, topic in enumerate(chosen, 1):
        name = topic.get("title") or "讨论区帖子"
        print(f"  [{index}/{len(chosen)}] {clip_text(name, 34)}")
        draft = tc.draft_reply(bbsid, topic["uuid"], course=course, name=name)
        if draft is None:
            print("      ✘ 这条没生成出草稿，跳过")
            skipped += 1
            print()
            continue
        if draft.get("has_replied"):
            print("      · 你之前已经回复过这条，跳过（不重复发）")
            skipped += 1
            print()
            continue
        while True:
            print("      " + "─" * 44)
            for line in textwrap.wrap(draft["reply"], width=60):
                print("      " + line)
            print("      " + "─" * 44)
            # 安全默认：回车 = 跳过；r 只重写草稿，绝不提交任何版本。
            answer = _ask("      怎么处理？[y 发送 · r 按提示重写 · 回车跳过 · q 退出] ")
            if answer.lower() in ("q", "quit", "exit"):
                print()
                print(f"  已停止：发送 {sent} 条 · 跳过 {skipped} 条")
                return {"ok": True, "sent": sent, "skipped": skipped, "reason": "用户中途退出"}
            if answer.lower() in ("r", "rewrite", "改", "重写"):
                hint = _revision_hint()
                if hint == "q":
                    print()
                    print(f"  已停止：发送 {sent} 条 · 跳过 {skipped} 条")
                    return {"ok": True, "sent": sent, "skipped": skipped, "reason": "用户中途退出"}
                revised = tc.draft_reply(
                    bbsid, topic["uuid"], course=course, name=name,
                    revision_hint=hint, previous_reply=draft["reply"],
                )
                if revised is None:
                    print("      ✘ 没能重写草稿，保留这一版供你决定")
                    continue
                if revised.get("has_replied"):
                    print("      · 你之前已经回复过这条，跳过（不重复发）")
                    skipped += 1
                    print()
                    break
                draft = revised
                print("      · 已按你的方向重写，请再看一眼")
                continue
            if answer.lower() not in ("y", "yes", "是", "1"):
                print("      · 已跳过这条")
                skipped += 1
                print()
                break
            ok = tc.submit_reply(bbsid, topic["uuid"], course=course, name=name,
                                 topic_info=draft["topic_info"], reply=draft["reply"],
                                 referer=draft["referer"], echo=False)
            if ok:
                print("      ✓ 已发送")
                sent += 1
            else:
                print("      ✘ 发送失败（详见运行日志）")
                skipped += 1
            print()
            break
        if index < len(chosen):
            time.sleep(SEND_INTERVAL_SECONDS)

    return {"ok": True, "sent": sent, "skipped": skipped, "reason": ""}


def _select_discussion_course(tc, courses, list_only):
    """Select a board course and confirm any fallback to a different course."""
    course = _pick_course(courses, list_only)
    if course is None:
        return {"ok": False, "sent": 0, "skipped": 0, "reason": "没有选择课程"}

    bbsid = resolve_bbsid(tc, course)
    if not bbsid:
        # 用户选的那门课没有讨论区：问一句再换，绝不静默改课
        others = [c for c in courses if c is not course]
        picked_course, picked_bbsid = _board_course(tc, others)
        if picked_course is None:
            print(f"  ✘ 《{course.get('title', '')}》没有讨论区板块，其它课程也没有")
            return {"ok": False, "sent": 0, "skipped": 0, "reason": "没有找到讨论区板块"}
        if list_only:
            course, bbsid = picked_course, picked_bbsid
        else:
            answer = _ask(f"  《{course.get('title', '')}》没有讨论区，改去"
                          f"《{picked_course.get('title', '')}》吗？[y/n · 回车＝否] ")
            if answer.lower() not in ("y", "yes", "是", "1"):
                return {"ok": False, "sent": 0, "skipped": 0, "reason": "用户取消了换课"}
            course, bbsid = picked_course, picked_bbsid

    return course, bbsid


def discuss_cli(chaoxing, tc, config: dict, list_only: bool = False,
                course_id: Optional[str] = None, courses: Optional[list] = None,
                auto_yes: bool = False) -> dict:
    """讨论区模式的入口：统计 → 挑帖子 → 草稿 → 确认 → 逐条发送."""
    #
    # 返回 {ok, sent, skipped, reason}：调用方据此汇报，失败时绝不能说"已发送"。
    # auto_yes 只跳过"开始刷课"的确认；把 AI 写的回复发到公开讨论区必须逐条确认，
    # 所以这里不因为 --yes 就静默群发（非交互输入会停在确认处并安全退出）。
    from api.task_center import TaskCenter
    if tc is None:
        tc = TaskCenter(chaoxing, config)
    if courses is None:
        try:
            courses = chaoxing.get_course_list() or []
        except Exception as e:
            print(f"  ✘ 读取课程列表失败：{e}")
            return {"ok": False, "sent": 0, "skipped": 0, "reason": "读取课程列表失败"}
    courses = list(courses)
    wanted = str(course_id or "").strip()
    if wanted:
        courses = [c for c in courses if str(c.get("courseId")) == wanted]
    if not courses:
        print("  ✘ 没有可用的课程")
        return {"ok": False, "sent": 0, "skipped": 0, "reason": "没有可用的课程"}

    selection = _select_discussion_course(tc, courses, list_only)
    if isinstance(selection, dict):
        return selection
    course, bbsid = selection

    title = str(course.get("title") or "")
    print()
    print(f"  讨论区 · {title}")
    print("  " + "─" * 46)
    print("  正在读取帖子…")
    topics, capped = fetch_all_topics(tc.session, bbsid)
    if not topics:
        print("  ✘ 没读到帖子（可能登录失效、页面改版，或这个讨论区还是空的）")
        return {"ok": False, "sent": 0, "skipped": 0, "reason": "没读到帖子"}
    if capped:
        print(f"  至少 {len(topics)} 条帖子（只读了前 {MAX_PAGES} 页）· 已经回复过的会自动跳过")
    else:
        print(f"  共 {len(topics)} 条帖子 · 已经回复过的会自动跳过")

    picked = _pick_reply_topics(topics, list_only)
    if isinstance(picked, dict):
        return picked

    chosen = [topics[n - 1] for n in picked]
    print()
    preview = " ｜ ".join(f"{n}. {clip_text(topics[n - 1].get('title') or '', 8)}" for n in picked[:4])
    more = f" 等 {len(chosen)} 条" if len(chosen) > 4 else ""
    print(f"  将回复 {len(chosen)} 条：{preview}{more}")
    print()

    result = _reply_selected_topics(tc, bbsid, course, chosen)
    if result["reason"]:
        return result
    sent, skipped = result["sent"], result["skipped"]

    print(f"  完成：发送 {sent} 条 · 跳过 {skipped} 条")
    if sent:
        print("  （平台约 3 分钟后才显示完成，可在 ./cx review 里复核正文）")
    again = _ask("  还要继续挑别的帖子吗？[y/n · 回车＝退出] ")
    if again.lower() not in ("y", "yes", "是", "1"):
        return {"ok": True, "sent": sent, "skipped": skipped, "reason": ""}
    return discuss_cli(chaoxing, tc, config, list_only=False, course_id=course_id,
                       courses=courses, auto_yes=auto_yes)
