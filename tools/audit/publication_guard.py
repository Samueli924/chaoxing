"""Reject private development material from public Git contributions."""

import argparse
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess  # nosec B404: invokes only Git with an argument list, never a shell
import sys


def audit_paths(root, paths):
    problems = []
    for name in paths:
        path = PurePosixPath(name)
        lower = name.lower()
        filename = path.name.lower()
        if (lower.startswith(("docs/handoff/", "docs/artifacts/", "private/", "accounts/"))
                or filename in {"agents.md", "claude.md", "tasks.yaml", "cookies.txt", "config.ini"}
                or filename.startswith(("session-log", "handoff", "audit-report"))
                or filename.endswith((".har", ".log"))
                or ("capture" in filename and filename.endswith(".txt"))
                or (filename.startswith(".env") and filename != ".env.example")):
            problems.append(name + ": private file type")
            continue
        source = Path(root) / name
        if not source.is_file() or source.is_symlink():
            continue
        if source.suffix.lower() == ".md" and name not in {"CONTRIBUTING.md", "SECURITY.md"}:
            text = source.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if re.search(r"docs/(?:handoff|artifacts)/|SESSION-LOG|TASKS\.yaml|本轮新增|上一轮 Agent|开发进度|/Users/[^/]+/", line):
                    problems.append(f"{name}:{number}: private development record")
        if source.suffix.lower() in {".py", ".ini", ".json", ".yaml", ".yml", ".md"}:
            text = source.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9]{20,}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b", line):
                    problems.append(f"{name}:{number}: credential-like value")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args(argv)
    executable = shutil.which("git")
    if executable is None:
        parser.error("Git is required to audit tracked files")
    root = str(Path(args.root).resolve())
    paths = subprocess.check_output([executable, "-C", root, "ls-files", "-z"]).decode().split("\0")  # nosec B603: fixed Git subcommand; root is a separate argument
    problems = audit_paths(args.root, [name for name in paths if name])
    for problem in problems:
        print(problem)
    if not problems:
        print("Publication guard passed")
    return int(bool(problems))


if __name__ == "__main__":
    sys.exit(main())
