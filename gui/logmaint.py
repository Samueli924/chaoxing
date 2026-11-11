# -*- coding: utf-8 -*-
"""
日志清理：只保留最近的日志，过期的自动删除，所有日志加起来不超过上限。

- 超过保留天数没有更新过的日志文件直接删除
- 总量超过上限时，先删最旧的、当前没有在写的日志；还超出就把最大的日志裁掉前面一半（保留最新的内容）
- 正在写入的日志（后台、搜索服务、正在刷课的账号）只裁剪不删除；它们都以追加方式打开，原地裁剪是安全的
"""
import os
import time
from pathlib import Path
from typing import Iterable

MB = 1024 * 1024


def trim_keep_tail(path: Path, keep_bytes: int) -> None:
    """原地只保留文件末尾约 keep_bytes 字节（从下一个换行处开始，避免半行）."""
    try:
        size = path.stat().st_size
        if size <= keep_bytes:
            return
        with open(path, "r+b") as f:
            f.seek(size - keep_bytes)
            tail = f.read()
            newline = tail.find(b"\n")
            if 0 <= newline < len(tail) - 1:
                tail = tail[newline + 1:]
            f.seek(0)
            f.write(tail)
            f.truncate()
    except OSError:
        pass


def enforce(files: Iterable[Path], max_bytes: int = 10 * MB, keep_days: float = 7,
            active: Iterable[Path] = (), now: float | None = None, prefer_delete: Iterable[Path] = ()) -> dict:
    """对给定的日志文件执行保留策略，返回 {"deleted": [...], "trimmed": [...], "total": 字节数}.

    prefer_delete：超出上限时优先删除的文件（如已不再写入的旧日志），删完它们再按时间从旧到新删除其他日志。
    """
    now = time.time() if now is None else now
    active = {Path(p).resolve() for p in active}
    prefer = {Path(p).resolve() for p in prefer_delete}
    files = [Path(p) for p in files if Path(p).is_file()]
    deleted, trimmed = [], []

    def is_active(p: Path) -> bool:
        return p.resolve() in active

    # 1. 过期删除
    for p in list(files):
        try:
            if not is_active(p) and now - p.stat().st_mtime > keep_days * 86400:
                p.unlink()
                deleted.append(p)
                files.remove(p)
        except OSError:
            pass

    def total() -> int:
        return sum(p.stat().st_size for p in files if p.exists())

    # 2. 超出上限：先删最旧的非活跃日志
    if total() > max_bytes:
        candidates = (p for p in files if not is_active(p))
        for p in sorted(candidates, key=lambda p: (p.resolve() not in prefer, p.stat().st_mtime)):
            if total() <= max_bytes:
                break
            try:
                p.unlink()
                deleted.append(p)
                files.remove(p)
            except OSError:
                pass

    # 3. 仍超出：反复把最大的文件裁掉一半
    for _ in range(20):
        size = total()
        if size <= max_bytes or not files:
            break
        biggest = max(files, key=lambda p: p.stat().st_size)
        before = biggest.stat().st_size
        trim_keep_tail(biggest, max(before // 2, 1))
        if biggest.stat().st_size >= before:
            break
        trimmed.append(biggest)

    return {"deleted": deleted, "trimmed": trimmed, "total": total()}
