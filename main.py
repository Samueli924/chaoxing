# -*- coding: utf-8 -*-
"""超星学习通自动完成任务点.

最简单的用法：
    python main.py            # 按提示输入手机号和密码
    python main.py --web      # 打开网页控制台，在浏览器里操作
"""
import argparse
import getpass
import sys
import traceback
from typing import Any, Optional

from api.exceptions import InputFormatError, LoginError
from api.logger import logger, setup_logging
from api.runtime import runtime
from api.settings import Settings, load_settings, split_course_list

# 以下名称保持从 main 导出，兼容已有的调用方式与测试
from api.runner import Runner, format_summary, format_time, has_saved_cookies  # noqa: F401
from api.scheduler import ChapterResult, ChapterTask, JobProcessor, process_chapter, process_job  # noqa: F401

EPILOG = """示例:
  python main.py                              按提示输入手机号、密码并选择课程
  python main.py -u 手机号 -p 密码             直接登录并选择课程
  python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2
  python main.py -c config.ini                使用配置文件（不指定时自动查找 config.ini）
  python main.py --web                        打开网页控制台
  python main.py --check                      只读自检：检查登录与各页面解析是否正常

也可以使用环境变量 CHAOXING_USERNAME / CHAOXING_PASSWORD / CHAOXING_COURSE_LIST 等提供配置。
"""


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """解析命令行参数（未填写的参数不会覆盖配置文件中的值）"""
    parser = argparse.ArgumentParser(
        description="超星学习通自动完成任务点 (Samueli924/chaoxing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument("-c", "--config", type=str, default=None,
                        help="配置文件路径 (默认自动查找当前目录或程序目录下的 config.ini)")
    parser.add_argument("-u", "--username", type=str, default=None, help="手机号账号")
    parser.add_argument("-p", "--password", type=str, default=None, help="登录密码")
    parser.add_argument("-l", "--list", dest="course_list", type=str, default=None,
                        help="要学习的课程ID列表, 以 , 分隔 (默认运行后选择)")
    parser.add_argument("-s", "--speed", type=float, default=None, help="视频播放倍速 (默认1, 最大2)")
    parser.add_argument("-j", "--jobs", type=int, default=None, help="同时进行的章节数 (默认4)")
    parser.add_argument("-a", "--notopen-action", type=str, default=None, choices=["retry", "ask", "continue"],
                        help="遇到未开放章节时的行为: retry-重试(默认), ask-询问, continue-跳过")
    parser.add_argument("--retry-interval", type=float, default=None, help="重试等待时间, 单位秒 (默认1.0)")
    parser.add_argument("--use-cookies", action="store_true", default=None, help="使用 cookies.txt 登录")
    parser.add_argument("-lc", "--add-learning-count", action="store_true", default=None,
                        help="完成任务点后增加章节学习次数")
    parser.add_argument("-tc", "--target-count", type=int, default=None, help="章节学习次数目标总次数 (默认100)")
    parser.add_argument("-v", "--verbose", "--debug", action="store_true", help="输出调试日志")

    parser.add_argument("--web", action="store_true", help="启动网页控制台, 在浏览器中登录并选择要完成的任务")
    parser.add_argument("--host", type=str, default=None, help="网页控制台监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="网页控制台端口 (默认 8765)")
    parser.add_argument("--no-browser", action="store_true", help="启动网页控制台时不自动打开浏览器")
    parser.add_argument("--check", action="store_true",
                        help="只读自检: 登录后检查课程/章节/任务点/题目页面能否正常解析, 不学习也不提交任何内容")
    # 旧版本遗留参数，从未实现，保留以免旧脚本报错
    parser.add_argument("--auto-sign", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "username": args.username,
        "password": args.password,
        "course_list": args.course_list,
        "speed": args.speed,
        "jobs": args.jobs,
        "notopen_action": args.notopen_action,
        "retry_interval": args.retry_interval,
        "use_cookies": args.use_cookies,
        "add_learning_count": args.add_learning_count,
        "target_count": args.target_count,
    }


def stdin_is_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def prompt_credentials(settings: Settings) -> None:
    common = settings.common
    if not common.get("username"):
        common["username"] = input("请输入你的手机号, 按回车确认\n手机号: ").strip()
    if not common.get("password"):
        common["password"] = getpass.getpass("密码(输入时不会显示): ")


def select_courses(all_course: list[dict], course_list: list[str], interactive: bool) -> list[dict]:
    """根据课程ID/班级ID筛选课程；未指定时在终端中选择，非交互环境下学习全部课程"""
    if course_list:
        wanted = set(course_list)
        selected = [c for c in all_course if c["courseId"] in wanted or c["clazzId"] in wanted]
        matched = {c["courseId"] for c in selected} | {c["clazzId"] for c in selected}
        missing = wanted - matched
        if missing:
            logger.warning(f"以下课程ID不在你的课程列表中: {', '.join(sorted(missing))}")
        if not selected:
            raise InputFormatError("配置的课程ID都不在课程列表中，请检查 course_list（运行时不指定课程即可查看全部课程ID）")
        return selected

    if not interactive:
        logger.info("未指定课程，将学习全部课程")
        return all_course

    print("*" * 10 + "课程列表" + "*" * 10)
    for index, course in enumerate(all_course, start=1):
        print(f"[{index}] ID: {course['courseId']} 班级ID: {course['clazzId']} 课程名: {course['title']}")
    print("*" * 28)
    print("提示: 同一 courseId 下若存在多个班级, 将分别完成。")
    while True:
        raw = input("请输入要学习的课程序号或课程ID, 多个用逗号分隔, 直接回车学习全部课程:\n").strip()
        if not raw:
            return all_course
        selected, unknown = [], []
        for token in split_course_list(raw):
            matches = [c for c in all_course if token in (c["courseId"], c["clazzId"])]
            if not matches and token.isdigit() and 1 <= int(token) <= len(all_course):
                matches = [all_course[int(token) - 1]]
            if not matches:
                unknown.append(token)
            for course in matches:
                if course not in selected:
                    selected.append(course)
        if unknown:
            print(f"无法识别: {', '.join(unknown)}，请重新输入")
            continue
        if selected:
            return selected


def run_cli(settings: Settings) -> int:
    interactive = stdin_is_interactive()
    runner = None
    try:
        runner = Runner(settings, interactive=interactive)
        common = settings.common
        need_password = not (common.get("username") and common.get("password"))
        if need_password and not common.get("use_cookies") and not has_saved_cookies():
            if not interactive:
                raise LoginError("未提供手机号和密码。请通过 -u/-p 参数、config.ini 或环境变量 "
                                 "CHAOXING_USERNAME/CHAOXING_PASSWORD 提供")
            prompt_credentials(settings)

        result = runner.login()
        if not result["status"] and need_password and interactive and not common.get("password"):
            # 上次保存的登录状态已失效，改为输入账号密码
            logger.warning(result["msg"])
            prompt_credentials(settings)
            result = runner.login()
        if not result["status"]:
            raise LoginError(result["msg"])

        all_course = runner.list_courses()
        if not all_course:
            logger.warning("没有找到任何课程")
            return 0
        courses = select_courses(all_course, common.get("course_list") or [], interactive)
        summary = runner.run(courses)
        report = format_summary(summary)
        logger.info("\n" + report)
        runner.notify(f"chaoxing : 任务结束\n{report}")
        return 1 if summary.get("failed") else 0
    except KeyboardInterrupt:
        runtime.request_stop()
        logger.warning("程序已被用户手动中断")
        return 130
    except (LoginError, InputFormatError) as e:
        logger.error(f"错误: {e}")
        if runner:
            runner.notify(f"chaoxing : 出现错误 {e}")
        return 1
    except Exception as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.debug(traceback.format_exc())
        if runner:
            runner.notify(f"chaoxing : 出现错误 {type(e).__name__}: {e}")
        return 1


def should_start_web(args: argparse.Namespace, argv: list[str]) -> bool:
    """双击打包好的 exe（没有任何参数）时默认打开网页控制台，方便不熟悉命令行的用户."""
    return args.web or (bool(getattr(sys, "frozen", False)) and not argv)


def main(argv: Optional[list[str]] = None) -> int:
    """主程序入口"""
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    setup_logging(verbose=args.verbose)
    if args.auto_sign:
        logger.warning("--auto-sign 参数从未实现, 已忽略")

    try:
        settings = load_settings(args.config, cli_overrides(args))
    except (OSError, ValueError) as e:
        logger.error(f"读取配置失败: {e}")
        return 2

    if should_start_web(args, argv):
        from api.web import serve
        return serve(settings, host=args.host, port=args.port, open_browser=not args.no_browser)
    if args.check:
        from api.selfcheck import run_selfcheck
        return run_selfcheck(settings, interactive=stdin_is_interactive())
    return run_cli(settings)


if __name__ == "__main__":
    sys.exit(main())
