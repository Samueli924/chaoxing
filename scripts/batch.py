"""Serial, process-isolated account profiles. Read-only checks are the default."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def prepare_profiles(path, run=False):
    path = Path(path).resolve()
    profiles = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 20:
        raise ValueError("配置须为 1–20 个账号的 JSON 数组")
    seen = set()
    result = []
    for item in profiles:
        if not isinstance(item, dict):
            raise ValueError("账号配置必须为对象")
        name = str(item.get("name", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name) or name in seen:
            raise ValueError("账号别名须唯一，且只含字母、数字、短横线或下划线")
        seen.add(name)
        env_file = (path.parent/str(item.get("env_file", ""))).resolve()
        if not env_file.is_file():
            raise ValueError("每个账号须指定存在的 env_file")
        courses = item.get("courses", [])
        if not isinstance(courses, list) or not all(isinstance(x, str) and x.isdigit() for x in courses):
            raise ValueError("courses 须为课程 ID 字符串数组")
        limit = int(item.get("max_duration", 3600))
        if not 1 <= limit <= 86400 or (run and not courses):
            raise ValueError("运行须明确指定课程，时限须为 1–86400 秒")
        result.append(dict(name=name, env_file=env_file, courses=courses, max_duration=limit))
    return result


def profile_environment(data_dir):
    env = {k:v for k,v in os.environ.items() if not k.startswith("CHAOXING_")}
    env.update(CHAOXING_DATA_DIR=str(data_dir), CHAOXING_NOTIFICATION_PROVIDER="", PYTHONDONTWRITEBYTECODE="1")
    return env


def main(argv=None):
    parser=argparse.ArgumentParser(description="按账号逐一运行，独立进程和数据目录；默认只读检查")
    parser.add_argument("profiles")
    parser.add_argument("--run", action="store_true", help="实际运行任务，可能保存或提交答题")
    parser.add_argument("--data-dir", default=str(ROOT/"data/profiles"))
    args=parser.parse_args(argv)
    try:
        profiles=prepare_profiles(args.profiles,args.run)
    except (ValueError,OSError) as exc:
        parser.error(str(exc))
    failed=False
    for profile in profiles:
        data_dir=Path(args.data_dir).expanduser().resolve()/profile["name"]
        data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        cmd=[sys.executable,"-B",str(ROOT/"scripts/local.py"),"--env-file",str(profile["env_file"])]
        if args.run:
            cmd.extend(["--max-duration",str(profile["max_duration"])])
        else:
            cmd.append("--check")
        if profile["courses"]:
            cmd.extend(["-l",",".join(profile["courses"])])
        log_path=data_dir/"batch.log"
        fd=os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:
            with os.fdopen(fd,"a") as log:
                result=subprocess.run(cmd,cwd=ROOT,env=profile_environment(data_dir),stdin=subprocess.DEVNULL,stdout=log,stderr=log,timeout=profile["max_duration"]+120)
            code=result.returncode
        except subprocess.TimeoutExpired:
            code=124
        failed=failed or code!=0
        print(f"{profile['name']}: exit={code}")
    return int(failed)

if __name__=="__main__":
    raise SystemExit(main())
