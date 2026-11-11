# -*- coding: utf-8 -*-
"""读写 config.ini：只替换指定键的值，保留原有注释和顺序，方便命令行版继续使用同一份配置."""
import configparser
import os
import re
import shutil
import threading

_lock = threading.Lock()


def ensure_config(path: str, template: str) -> None:
    if not os.path.exists(path) and os.path.exists(template):
        shutil.copyfile(template, path)


def read_config(path: str) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # 保持键名大小写
    with _lock:
        parser.read(path, encoding="utf8")
    return {section: dict(parser.items(section)) for section in parser.sections()}


_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def update_config(path: str, updates: dict[str, dict[str, object]]) -> None:
    """把 updates 中的 {section: {key: value}} 写回文件，不存在的键追加到对应小节末尾."""
    with _lock:
        lines: list[str] = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf8") as f:
                lines = f.read().splitlines()

        pending = {sec: {k: _fmt(v) for k, v in kv.items()} for sec, kv in updates.items()}
        section = None
        section_end: dict[str, int] = {}  # 小节最后一个非空行的下标

        for i, line in enumerate(lines):
            m = _SECTION_RE.match(line)
            if m:
                section = m.group(1).strip()
                section_end[section] = i
                continue
            if section is None:
                continue
            if line.strip():
                section_end[section] = i
            stripped = line.lstrip()
            if stripped.startswith((";", "#")) or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if section in pending and key in pending[section]:
                lines[i] = f"{key} = {pending[section].pop(key)}"

        # 追加缺失的键（从后往前插，避免下标错位）
        inserts = []
        for sec, kv in pending.items():
            if not kv:
                continue
            new_lines = [f"{k} = {v}" for k, v in kv.items()]
            if sec in section_end:
                inserts.append((section_end[sec] + 1, new_lines))
            else:
                lines.extend(["", f"[{sec}]", *new_lines])
        for idx, new_lines in sorted(inserts, key=lambda x: x[0], reverse=True):
            lines[idx:idx] = new_lines

        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)


def _fmt(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()
