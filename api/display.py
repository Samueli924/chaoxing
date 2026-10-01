# -*- coding: utf-8 -*-
"""
刷课进度显示

目标：刷课时不再刷屏，每完成一个章节只输出一行，清晰可读。

显示形式：
  ██████░░░░░░░░░░░░░░░░░░░░   23/111  21%   剩 88 节 · 预计 12 分 30 秒   ✓ 1.2 什么是马克思主义
  ██████████░░░░░░░░░░░░░░░░   24/111  22%   剩 87 节 · 预计 12 分 10 秒   ⤼ 3.1 社会形态（未开放）
  ████████████░░░░░░░░░░░░░░   25/111  23%   剩 86 节 · 预计 11 分 50 秒   ✗ 4.2.6 社会形态

  ✓ 完成   ⤼ 跳过   ✗ 失败

通过 tqdm.write 输出，与视频进度条共存不会互相破坏。
"""

import re
import sys
import threading
import time
import unicodedata

from tqdm import tqdm


def safe_console():
    """
    让控制台输出永远不会因为编码问题崩溃。

    Windows 中文版控制台默认是 GBK 编码，课程名 / 题干里只要出现一个
    &nbsp;(\xa0) 之类的字符，print 就会抛 UnicodeEncodeError 直接结束程序（#602）。
    这里只放宽错误处理（errors="replace"），不改编码 ——
    改编码会让中文在旧控制台上变成乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            # 被重定向 / 打包成窗口程序时没有 reconfigure，忽略即可
            pass


def _disp_width(text) -> int:
    """
    字符串在终端里的显示宽度。
    中文/全角字符占 2 列，ASCII 占 1 列 —— 直接用 len() 会导致中文对不齐。
    """
    width = 0
    for ch in str(text):
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def _pad_right(text, width) -> str:
    """按显示宽度右侧补空格"""
    text = str(text)
    gap = width - _disp_width(text)
    return text + (" " * gap if gap > 0 else "")


def _truncate(text, max_width) -> str:
    """按显示宽度截断，超出部分用省略号"""
    text = str(text)
    if _disp_width(text) <= max_width:
        return text
    out = ""
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > max_width - 1:
            break
        out += ch
        used += w
    return out + "…"


def _fmt_duration(seconds, ceil_min=False):
    """秒 -> 可读时长；ceil_min=True 时不足 1 秒也显示 1 秒"""
    try:
        seconds = float(seconds)
    except Exception:
        return "--"
    if seconds < 0:
        return "--"
    if ceil_min:
        import math
        seconds = max(1, math.ceil(seconds))
    seconds = int(seconds)
    if seconds < 60:
        return str(seconds) + " 秒"
    if seconds < 3600:
        return str(seconds // 60) + " 分 " + str(seconds % 60) + " 秒"
    return str(seconds // 3600) + " 小时 " + str((seconds % 3600) // 60) + " 分"


def _fmt_bar(done, total, width=20):
    """文本进度条（用方块字符，比 # 更清晰）"""
    if total <= 0:
        return "░" * width
    filled = int(width * done / total)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


# 章节标题开头的编号，例如 "1.2 什么是马克思主义" -> "1.2"
_LABEL_RE = re.compile(r"^\s*(\d+(?:[.\-]\d+)*)")


# ---------------------------------------------------------------- 作答留痕

QUESTION_TYPE_LABELS = {
    'single': '选择',
    'multiple': '多选',
    'judgement': '判断',
    'completion': '填空',
    'shortanswer': '简答',
    'unknown': '问答',
}


def clip(text, limit: int = 36) -> str:
    '''单行显示用的截断（按显示宽度，中文算 2 列）'''
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not value:
        return ''
    if _disp_width(value) <= limit:
        return value
    out = []
    width = 0
    for ch in value:
        w = _disp_width(ch)
        if width + w > limit - 1:
            break
        out.append(ch)
        width += w
    return ''.join(out) + '…'


def answer_line(index, q_type, answer, title: str = "") -> str:
    '''一题的作答留痕：序号 + 题型 + 题干提示 + 答案'''
    label = QUESTION_TYPE_LABELS.get(str(q_type or '').lower(), '作答')
    hint = clip(title, 20)
    prefix = f'    {index:>2}. {label:<4}'
    if hint:
        prefix += hint + '  '
    body = str(answer or '').strip()
    if _disp_width(body) > 36:
        body = clip(body, 36) + f'（{len(body)} 字）'
    return prefix + body


def answers_header(title, count) -> str:
    '''一次作答的开头：题目数量一眼可见'''
    return f'  作答 · {clip(title, 24)}（{count} 题）'


def emit(text):
    '''把一行留痕同时写到控制台和运行日志（普通运行日志即可回溯）'''
    from api.privacy import redact
    line = redact(str(text or ''))
    if not line.strip():
        return
    try:
        print(line)
    except Exception:
        pass
    try:
        from api.logger import log_file_only
        log_file_only(line.strip(), 'INFO')
    except Exception:
        pass


def emit_block(title: str, text: str, width: int = 60) -> None:
    '''多行正文（讨论回复等）留痕：标题一行 + 折行正文'''
    import textwrap
    if title:
        emit('  ' + title)
    body = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not body:
        return
    wrapped = textwrap.wrap(body, width=width) or []
    # 中文标点不落行首（读起来更顺）
    no_lead = '，。、；：！？）》”’…'
    fixed = []
    for line in wrapped:
        if fixed and line and line[0] in no_lead:
            fixed[-1] = fixed[-1] + line[0]
            line = line[1:]
        if line:
            fixed.append(line)
    for line in fixed:
        emit('    ' + line)

def chapter_label(point, max_width=20) -> str:
    """
    章节简称：优先用编号（1.2 / 1.2.3），没有编号就退回标题本身。
    point 可以是章节字典，也可以直接是标题字符串。
    """
    if isinstance(point, dict):
        title = str(point.get("title") or "").strip()
    else:
        title = str(point or "").strip()
    if not title:
        return "未命名章节"
    matched = _LABEL_RE.match(title)
    if matched:
        return matched.group(1)
    return _truncate(title, max_width)


def compress_labels(labels, max_groups=3) -> str:
    """
    把连续的编号压成区间：
      ['1.1', '1.2', '1.3', '2.1'] -> '1.1~1.3、2.1'
    传入顺序必须和章节顺序一致。
    """
    labels = [str(x) for x in labels]
    if not labels:
        return ""

    groups = []
    first = last = 0
    for i in range(1, len(labels)):
        if i == last + 1:
            last = i
        else:
            groups.append((first, last))
            first = last = i
    groups.append((first, last))

    parts = []
    for start, end in groups:
        parts.append(labels[start] if start == end else labels[start] + "~" + labels[end])

    if len(parts) > max_groups:
        return "、".join(parts[:max_groups]) + " 等 " + str(len(parts)) + " 段"
    return "、".join(parts)


def course_plan_summary(finished_points, pending_points, planned_count=None) -> str:
    """
    一门课开刷前的一句话说明，让用户一眼看清"哪些已经刷过、从哪儿接着刷"：

      共 30 节待刷
      共 12 节已完成（1.1 ~ 3.4），从 4.1 开始
      共 12 节已完成（1.1 ~ 3.4），从 4.1 开始，本次刷 3 节
      共 30 节全部已完成
    """
    finished_points = list(finished_points or [])
    pending_points = list(pending_points or [])
    done = len(finished_points)
    total = done + len(pending_points)

    if total == 0:
        return "没有读到章节"
    if done == 0:
        return "共 " + str(total) + " 节待刷"

    ranges = compress_labels([chapter_label(p) for p in finished_points])
    if not pending_points:
        return "共 " + str(done) + " 节全部已完成"

    text = ("共 " + str(done) + " 节已完成（" + ranges + "），从 "
            + chapter_label(pending_points[0]) + " 开始")
    if planned_count is not None and planned_count < len(pending_points):
        text += "，本次刷 " + str(planned_count) + " 节"
    return text


class ChapterProgress:
    """章节级进度：每完成一个章节输出一行整体进度"""

    def __init__(self, total, enabled=True, title_width=30):
        self.total = int(total or 0)
        self.done = 0
        self.failed = 0
        self.skipped = 0
        self.start_time = time.time()
        self.title_width = title_width
        self._lock = threading.Lock()
        self._enabled = bool(enabled) and self.total > 0

    # ---------- 内部 ----------
    def _elapsed(self):
        return max(0.0, time.time() - self.start_time)

    def _eta(self):
        """基于平均每章节耗时估算剩余时间"""
        processed = self.done + self.failed + self.skipped
        if processed <= 0:
            return None
        avg = self._elapsed() / processed
        remain = self.total - processed
        if remain <= 0:
            return 0
        return avg * remain

    def _render(self, mark, title, extra=""):
        processed = self.done + self.failed + self.skipped
        total = self.total
        bar = _fmt_bar(processed, total)
        remain = max(0, total - processed)

        # 只要还有未完成的章节就显示 ETA；全部完成时改为显示耗时
        if remain > 0:
            eta = self._eta()
            when_text = "预计 " + (_fmt_duration(eta, ceil_min=True) if eta is not None else "--")
        else:
            when_text = "耗时 " + _fmt_duration(self._elapsed())

        name = _truncate(str(title).strip(), self.title_width)

        # 固定列宽（按显示宽度计算），保证多行对齐；整行控制在 80 列左右。
        # 百分比不单独列一栏：进度条本身已经直观表达了比例。
        counter = _pad_right(str(processed) + "/" + str(total), 7)
        info = _pad_right("剩 " + str(remain) + " · " + when_text, 18)

        return "  " + bar + " " + counter + info + " " + mark + " " + name + extra

    def _emit(self, line):
        if not self._enabled:
            return
        try:
            tqdm.write(line, file=sys.stderr)
            sys.stderr.flush()
        except Exception:
            try:
                print(line, file=sys.stderr, flush=True)
            except Exception:
                pass

    def _bump(self, kind, title, extra=""):
        with self._lock:
            if kind == "done":
                self.done += 1
                mark = "✓"
            elif kind == "skip":
                self.skipped += 1
                mark = "⤼"
            else:
                self.failed += 1
                mark = "✗"
            self._emit(self._render(mark, title, extra))

    # ---------- 对外 ----------
    def chapter_done(self, title):
        self._bump("done", title)

    def chapter_skipped(self, title, reason=""):
        self._bump("skip", title, ("（" + reason + "）") if reason else "")

    def chapter_failed(self, title):
        self._bump("fail", title)

    def summary(self):
        """刷课结束时的总结"""
        if not self._enabled:
            return
        elapsed = self._elapsed()
        parts = []
        if self.done:
            parts.append("完成 " + str(self.done))
        if self.skipped:
            parts.append("跳过 " + str(self.skipped))
        if self.failed:
            parts.append("失败 " + str(self.failed))
        self._emit("  " + "─" * 46)
        self._emit("  刷课结束：共 " + str(self.total) + " 节 · "
                   + " · ".join(parts) + " · 耗时 " + _fmt_duration(elapsed))
