"""Launch with the existing Python environment and a narrowly scoped dotenv file."""
import argparse
import os
from pathlib import Path
import re
import runpy
import sys

ROOT = Path(__file__).resolve().parent.parent


def load_env(path):
    """Read CHAOXING_* assignments literally; never execute shell commands."""
    values = {}
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(?:export\s+)?(CHAOXING_[A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description="从本机 env 读取超星配置，不执行其中的脚本")
    parser.add_argument("--env-file", default=str(Path.home()/".secrets.env"))
    args, remaining = parser.parse_known_args(argv)
    env_path = Path(args.env_file).expanduser()
    if env_path.is_file():
        for key, value in load_env(env_path).items():
            os.environ.setdefault(key, value)
    elif args.env_file != str(Path.home()/".secrets.env"):
        parser.error("指定的 env 文件不存在")
    os.environ.setdefault("CHAOXING_DATA_DIR", str(ROOT/"data"))
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.dont_write_bytecode = True
    Path(os.environ["CHAOXING_DATA_DIR"]).mkdir(parents=True, exist_ok=True, mode=0o700)
    sys.path.insert(0, str(ROOT))
    sys.argv = [str(ROOT/"main.py"), *(remaining or ["--web"])]
    runpy.run_path(str(ROOT/"main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
