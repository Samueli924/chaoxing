# -*- coding: utf-8 -*-
import argparse
import enum
import os
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Optional
from tqdm import tqdm
from api.answer import Tiku
from api.base import Chaoxing, Account, StudyResult
from api.exceptions import LoginError, InputFormatError
from api.configfile import read_config_file
from api.guard import check_before_run, hard_stop, UserAbort
from api import interrupt, scan
from api import paths
from api.display import ChapterProgress, course_plan_summary, safe_console
from api.logger import set_quiet as set_console_quiet
from api.logger import log_file_only, logger
from api.privacy import redact
from requests import RequestException
from api.notification import Notification
from api.live import Live
from api.live_process import LiveProcessor
from api.process import increase_learning_count_for_course
from api.task_center import (
    TaskCenter,
    PLAN_TYPE_CHAPTER,
    PLAN_TYPE_DOCUMENT,
    PLAN_TYPE_AI,
    PLAN_TYPE_VIDEO,
    PLAN_TYPE_HOMEWORK,
    PLAN_TYPE_DISCUSS,
    SUPPORTED_PLAN_TYPES,
    TaskOutcome,
    normalize_submit_mode,
    plan_type_name,
)

try:
    from queue import PriorityQueue, ShutDown
except ImportError:
    from queue import PriorityQueue


    class ShutDown(Exception):
        pass


class ChapterResult(enum.Enum):
    SUCCESS = 0,
    ERROR = 1,
    NOT_OPEN = 2,
    PENDING = 3


def log_error(func):
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except BaseException as e:
            logger.error(f"Error in thread {threading.current_thread().name}: {e}")
            logger.error(redact(traceback.format_exc()))
            raise

    return wrapper


class NetworkRetryFailed(Exception):
    """网络问题重试多次仍然失败（不是用户配置错误）"""


def with_network_retry(func, *args, what="请求", times=3, delay=2.0, **kwargs):
    """
    主流程的网络请求重试。

    登录 / 取课表 / 取章节这几步以前一次网络抖动就整轮崩掉（#124 #166 #192 #226 #228），
    这里对连接类异常重试几次；仍然失败就抛 NetworkRetryFailed，
    由 main() 统一给一句人话提示，而不是甩一堆 traceback。
    """
    last_error = None
    for attempt in range(1, times + 1):
        try:
            return func(*args, **kwargs)
        except RequestException as e:
            last_error = e
            if attempt < times:
                logger.warning(f"{what}失败（第 {attempt}/{times} 次）：{e}，{int(delay)} 秒后重试")
                time.sleep(delay)
    raise NetworkRetryFailed(f"{what}失败：{last_error}")


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_float(value, default, low=None, high=None):
    """
    安全地把配置值转成浮点数。
    配置里写错（"abc"）或超范围时用默认值，绝不让程序崩溃。
    """
    try:
        num = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if low is not None and num < low:
        return low
    if high is not None and num > high:
        return high
    return num


def safe_int(value, default, low=None, high=None):
    """安全地把配置值转成整数；写错或超范围时用默认值"""
    try:
        num = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    if low is not None and num < low:
        return low
    if high is not None and num > high:
        return high
    return num


NOTOPEN_ACTIONS = ("retry", "ask", "continue")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Samueli924/chaoxing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--use-cookies", action="store_true", help="使用cookies登录")

    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="跳过启动前的确认（用于已确认过的自动化/定时任务；默认必须人工确认）"
    )

    parser.add_argument(
        "-c", "--config", type=str, default=None, help="使用配置文件运行程序"
    )
    parser.add_argument("-u", "--username", type=str, default=None, help="手机号账号")
    parser.add_argument("-p", "--password", type=str, default=None, help="登录密码")
    parser.add_argument(
        "-l", "--list", type=str, default=None, help="要学习的课程ID列表, 以 , 分隔"
    )
    parser.add_argument(
        "-s", "--speed", type=float, default=1.0, help="视频播放倍速 (默认1, 最大2)"
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=4, help="同时进行的章节数 (默认4, 如果一个章节有多个任务点，不会限制同时处理任务点的数量)"
    )
    parser.add_argument(
        "-n", "--max-points", type=int, default=0,
        help="每门课最多刷几个任务点(章节), 0 或留空=全部刷完"
    )
    parser.add_argument(
        "--max-tasks", type=int, default=0,
        help="每门课最多刷几个教学任务(任务中心), 0 或留空=全部"
    )

    parser.add_argument(
        "-v",
        "--verbose",
        "--debug",
        action="store_true",
        help="启用调试模式, 输出DEBUG级别日志",
    )
    parser.add_argument(
        "-a", "--notopen-action", type=str, default="retry",
        choices=["retry", "ask", "continue"],
        help="遇到关闭任务点时的行为: retry-重试, ask-询问, continue-继续"
    )

    parser.add_argument(
        "--task-center", dest="task_center", action="store_true", default=None,
        help="刷任务中心的教学任务（默认跟随配置，配置里默认开启）"
    )
    parser.add_argument(
        "--no-task-center", dest="task_center", action="store_false", default=None,
        help="只刷章节，不刷任务中心的教学任务"
    )
    parser.add_argument(
        "--task-center-submit-mode", dest="task_center_submit_mode",
        choices=["confirm", "auto"], default=None,
        help="任务中心作业/讨论/AI实践提交模式；confirm 逐次确认，auto 自动提交"
    )
    parser.add_argument(
        "--chapters", dest="chapter_study", action="store_true", default=None,
        help="刷章节（目录）任务点（默认跟随配置，配置里默认开启）"
    )
    parser.add_argument(
        "--no-chapters", dest="chapter_study", action="store_false", default=None,
        help="只刷任务中心的教学任务，跳过章节（目录）"
    )
    parser.add_argument(
        "--retry-interval", type=float, default=1.0, help="重试等待时间, 单位秒 (默认1.0)"
    )
    parser.add_argument(
        "--only-discussion", action="store_true",
        help="只刷讨论（任务里的主题讨论），其它类型本次跳过",
    )
    parser.add_argument(
        "--course-id", type=str, default=None,
        help="指定课程 ID（cx discuss 浏览哪门课的讨论区）",
    )
    parser.add_argument(
        "--discuss", action="store_true",
        help="浏览课程讨论区，自己挑帖子回复（模式 2），不进刷课流程",
    )
    parser.add_argument(
        "--list-topics", action="store_true",
        help="只列出讨论区帖子（不交互、不回复），配合 --discuss 使用",
    )

    parser.add_argument(
        "-lc",
        "--add-learning-count",
        action="store_true",
        help="开启章节学习次数增加模式",
    )
    parser.add_argument(
        "-tc",
        "--target-count",
        type=int,
        default=100,
        help="章节学习次数目标总次数 (默认100)",
    )

    # 在解析之前捕获 -h 的行为
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


def load_config_from_file(config_path):
    """从配置文件加载设置"""
    config, broken = read_config_file(config_path)
    if broken:
        logger.warning(f"配置文件 {config_path} 内容有损坏，已跳过异常行并尽量沿用其余设置")

    common_config: dict[str, Any] = {}
    tiku_config: dict[str, Any] = {}
    notification_config: dict[str, Any] = {}

    # 检查并读取common节
    if config.has_section("common"):
        common_config = dict(config.items("common"))

        # 处理course_list，将字符串转换为列表
        if "course_list" in common_config and common_config["course_list"]:
            common_config["course_list"] = [item.strip() for item in common_config["course_list"].split(",") if
                                            item.strip()]

        # 下面这些数值都用 safe_* 解析：
        # 用户在配置里写错（比如 speed=abc）时用默认值兜底，而不是让程序崩溃。
        if "speed" in common_config:
            common_config["speed"] = safe_float(common_config["speed"], 1.0, low=1.0, high=2.0)
        if "jobs" in common_config:
            common_config["jobs"] = safe_int(common_config["jobs"], 4, low=1, high=8)
        if "retry_interval" in common_config:
            common_config["retry_interval"] = safe_float(common_config["retry_interval"], 1.0, low=0.0)
        else:
            common_config["retry_interval"] = 1.0
        if "work_max_retries" in common_config:
            common_config["work_max_retries"] = safe_int(common_config["work_max_retries"], 3, low=0, high=10)
        else:
            common_config["work_max_retries"] = 3
        if "work_redo_enabled" in common_config:
            common_config["work_redo_enabled"] = str_to_bool(common_config["work_redo_enabled"])
        if "use_cookies" in common_config:
            common_config["use_cookies"] = str_to_bool(common_config["use_cookies"])
        if "add_learning_count" in common_config:
            common_config["add_learning_count"] = str_to_bool(common_config["add_learning_count"])
        if "task_center" in common_config:
            common_config["task_center"] = str_to_bool(common_config["task_center"])
        if "chapter_study" in common_config:
            common_config["chapter_study"] = str_to_bool(common_config["chapter_study"])
        common_config["task_center_submit_mode"] = normalize_submit_mode(
            common_config.get("task_center_submit_mode", "auto")
        )
        common_config["ai_practice_min_score"] = safe_float(
            common_config.get("ai_practice_min_score", 85), 85.0, low=0.0, high=100.0
        )
        common_config["ai_practice_max_rounds"] = safe_int(
            common_config.get("ai_practice_max_rounds", 5), 5, low=1, high=20
        )
        if "target_count" in common_config:
            common_config["target_count"] = safe_int(common_config["target_count"], 100, low=1, high=9999)

        # notopen_action 只接受三个合法值，写错就用默认的 continue（最省事）
        action = str(common_config.get("notopen_action", "")).strip().lower()
        common_config["notopen_action"] = action if action in NOTOPEN_ACTIONS else "continue"
        # max_points_per_course 支持两种格式，必须保持字符串原样交给
        # _parse_max_points 解析：
        #   3                    全部课程都刷 3 个
        #   2151141:3,189191:0   按课程分别指定
        # 注意：不要在这里做 int() 转换，否则 "2151141:3" 会抛 ValueError
        # 被静默改成 0，导致"按课程指定"完全失效、退化成全部刷完。
        if "username" in common_config and common_config["username"] is not None:
            common_config["username"] = common_config["username"].strip()
        if "password" in common_config and common_config["password"] is not None:
            common_config["password"] = common_config["password"].strip()

    # 检查并读取tiku节
    if config.has_section("tiku"):
        tiku_config = dict(config.items("tiku"))
        # 处理数值类型转换（写错时用默认值兜底，不让程序崩溃）
        for key, default in (("delay", 1.0), ("cover_rate", 0.8)):
            if key in tiku_config:
                tiku_config[key] = safe_float(tiku_config[key], default, low=0.0)

    # 检查并读取notification节
    if config.has_section("notification"):
        notification_config = dict(config.items("notification"))

    return common_config, tiku_config, notification_config


def _load_default_tiku_and_notification():
    """
    命令行模式（不带 -c）下，题库和通知设置仍然从用户配置里读。

    运行时 Tiku 本来就会去读 ~/.chaoxing/config.ini 的 [tiku] 段，
    如果启动检查看不到它，就会出现"参数都填了却被拦下来问答题方式"的矛盾。
    只取题库和通知两段：账号 / 课程 / 刷课参数一律以命令行参数为准。
    """
    try:
        default_config = paths.config_path()
    except Exception:
        return {}, {}
    if not os.path.exists(default_config):
        return {}, {}
    try:
        _common, tiku_config, notification_config = load_config_from_file(default_config)
        return tiku_config, notification_config
    except Exception as e:
        logger.warning(f"读取配置文件失败，将忽略其中的答题/通知设置: {e}")
        return {}, {}


def build_config_from_args(args):
    """从命令行参数构建配置"""
    common_config = {
        "use_cookies": args.use_cookies,
        "username": args.username,
        "password": args.password,
        "course_list": [item.strip() for item in args.list.split(",") if item.strip()] if args.list else None,
        "speed": args.speed or 1.0,
        "jobs": args.jobs,
        "notopen_action": args.notopen_action or "retry",
        "retry_interval": args.retry_interval or 1.0,
        "add_learning_count": args.add_learning_count,
        "target_count": args.target_count,
        "max_points_per_course": getattr(args, "max_points", 0) or 0,
        "max_tasks_per_course": getattr(args, "max_tasks", 0) or 0,
        "task_center": getattr(args, "task_center", None),
        "task_center_submit_mode": getattr(args, "task_center_submit_mode", None),
        "chapter_study": getattr(args, "chapter_study", None),
        "ai_practice_min_score": 85.0,
        "ai_practice_max_rounds": 5,
    }
    tiku_config, notification_config = _load_default_tiku_and_notification()
    return common_config, tiku_config, notification_config


def init_config():
    """初始化配置"""
    args = parse_args()

    if args.config:
        common_config, tiku_config, notification_config = load_config_from_file(args.config)
    else:
        common_config, tiku_config, notification_config = build_config_from_args(args)
    # 明确提供的开关/提交模式始终覆盖配置文件；未提供时保留配置，避免 --yes
    # 或普通命令行启动意外改变提交门禁。
    if getattr(args, "chapter_study", None) is not None:
        common_config["chapter_study"] = bool(args.chapter_study)
    if getattr(args, "task_center", None) is not None:
        common_config["task_center"] = bool(args.task_center)
    if getattr(args, "task_center_submit_mode", None) is not None:
        common_config["task_center_submit_mode"] = normalize_submit_mode(
            args.task_center_submit_mode
        )
    # 仅供任务中心的写作器使用；不会写回配置文件，也不会改变章节答题配置。
    common_config["_tiku_config"] = tiku_config
    return common_config, tiku_config, notification_config, args.config, args


def init_chaoxing(common_config, tiku_config, config_path=None):
    """初始化超星实例"""
    username = common_config.get("username", "")
    password = common_config.get("password", "")
    use_cookies = common_config.get("use_cookies", False)

    # 如果没有提供用户名密码，从命令行获取
    if (not username or not password) and not use_cookies:
        username = input("请输入你的手机号, 按回车确认\n手机号:")
        password = input("请输入你的密码, 按回车确认\n密码:")

    account = Account(username, password)

    # 设置题库
    tiku = Tiku.get_tiku_from_config(tiku_config, config_path=config_path)  # 载入题库
    tiku.init_tiku()  # 初始化题库

    # 获取查询延迟设置

    # 检查大模型连接（如果使用的是大模型题库）
    # 根据配置文件中的 provider 判断是否为大模型题库
    provider = tiku_config.get('provider', '')
    provider_list = [name.strip() for name in provider.split(',') if name.strip()]
    if any(name in ['AI', 'SiliconFlow'] for name in provider_list):
        check_connection = tiku_config.get('check_llm_connection', 'true').lower() == 'true'
        if check_connection:
            logger.debug(f'正在验证大模型配置 (provider={provider})...')
            if not tiku.check_llm_connection():
                logger.error('大模型连接检查失败')

                # 没有终端可交互时，不能自己决定继续，直接停止
                if not sys.stdin.isatty():
                    raise RuntimeError(
                        'DeepSeek API Key 校验失败，且当前无法交互确认，已停止运行。\n'
                        '        请检查 config.ini 里的 key（或运行 cx setup 重新填写）。'
                    )

                print()
                print("  ✘ 答题用的 API Key 没通过验证，章节测验这次不能自动作答（运行 cx setup 可以改）")
                print("    可能原因：填错了、已失效、或账户余额不足。")
                print("    建议先运行 cx 重新填写；这里选停止更安全。")
                print()
                try:
                    choice = input("  仍然继续刷课吗？(y/n) > ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    choice = ""
                # 默认不继续（安全默认），必须明确输入 y
                if choice not in ("y", "yes", "是"):
                    raise RuntimeError("API Key 校验失败，用户选择停止")
                logger.warning("用户确认在 API Key 异常的情况下继续运行")

    query_delay = tiku_config.get("delay", 0)

    # 章节检测答错后允许的最大重做次数（答错时反馈给AI并重新提交，直到全部正确）
    work_max_retries = common_config.get("work_max_retries", 3)

    # 视频是否串行：默认并发（快）；遇到"刷完又变回没刷"可以打开
    serial_video = str_to_bool(common_config.get("serial_video", False))
    # 是否允许自动重做(默认false: 仅检查并记录成绩, 适用于只允许作答一次的课程)
    work_redo_enabled = common_config.get("work_redo_enabled", False)

    # 实例化超星API
    chaoxing = Chaoxing(
        account=account,
        tiku=tiku,
        query_delay=query_delay,
        work_max_retries=work_max_retries,
        serial_video=serial_video,
        work_redo_enabled=work_redo_enabled,
    )

    return chaoxing


def process_job(chaoxing: Chaoxing, course: dict, job: dict, job_info: dict, speed: float,
                engine_info: bool = False) -> StudyResult:
    """处理单个任务点

    engine_info=True 表示这次是任务引擎的"章节"任务点在刷 mooc 章节，
    打点/文档完成请求要带 courseEngineInfo，平台才会下发 stuJobInfo。
    """
    # 视频任务
    if job["type"] == "video":
        logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        # 超星的接口没有返回当前任务是否为Audio音频任务
        video_result = chaoxing.study_video(
            course, job, job_info, _speed=speed, _type="Video", engine_info=engine_info
        )
        if video_result == StudyResult.ERROR:
            # 只有"读不到视频信息"（多半其实是音频任务）才回退音频。
            # 403 风控时不能立刻再跑一遍音频 —— 那等于连续撞风控，
            # 而且会把剩余时长整段再"播放"一次，反而更容易被判定异常（#445 #473 #488）。
            logger.info("当前任务非视频任务, 正在尝试音频任务解码")
            video_result = chaoxing.study_video(
                course, job, job_info, _speed=speed, _type="Audio", engine_info=engine_info)
        if video_result.is_failure():
            logger.warning(
                f"任务点异常已跳过: {job.get('name', job['jobid'])}（详情见日志）"
            )
        return video_result
    # 文档任务
    elif job["type"] == "document":
        logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        return chaoxing.study_document(course, job, engine_info=engine_info)
    # 测验任务
    elif job["type"] == "workid":
        logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
        return chaoxing.study_work(course, job, job_info)
    # 阅读任务
    elif job["type"] == "read":
        logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
        return chaoxing.study_read(course, job, job_info)
    # 直播任务
    elif job["type"] == "live":
        logger.trace(f"识别到直播任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        try:
            # 准备直播所需参数
            defaults = {
                "userid": chaoxing.get_uid(),
                "clazzId": course.get("clazzId"),
                "knowledgeid": job_info.get("knowledgeid")
            }

            # 创建直播对象
            live = Live(
                attachment=job,
                defaults=defaults,
                course_id=course.get("courseId")
            )

            # 直播按真实时间跑（不看倍速），并尊重中断；拿不到成功结果就不算完成
            if not LiveProcessor.run_live(live, speed):
                logger.warning(f"直播任务未完成: {job.get('name', '?')}")
                return StudyResult.ERROR
            return StudyResult.SUCCESS
        except Exception as e:
            logger.error(f"处理直播任务时出错: {str(e)}")
            return StudyResult.ERROR

    logger.error(f"未知任务类型: {job['type']}")
    return StudyResult.ERROR


@dataclass
class ChapterTask:
    index: int
    point: dict[str, Any]
    course: dict[str, Any]
    result: ChapterResult = ChapterResult.PENDING
    tries: int = 0

    def __lt__(self, other):
        """比较两个任务的索引大小，用于优先级队列排序."""
        if not isinstance(other, ChapterTask):
            return NotImplemented
        return self.index < other.index


class JobProcessor:
    def __init__(self, chaoxing: Chaoxing, tasks: list[ChapterTask], config: dict[str, Any],
                 progress=None):
        """初始化任务处理器."""
        if "jobs" not in config or not config["jobs"]:
            config["jobs"] = 4

        self.chaoxing = chaoxing
        self.speed = config["speed"]
        self.max_tries = 5
        self.tasks = tasks
        self.failed_tasks: list[ChapterTask] = []
        self.task_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.retry_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.wait_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.threads: list[threading.Thread] = []
        self.worker_num = config["jobs"]
        self.config = config
        self.retry_interval = config.get("retry_interval", 1.0)
        self.progress = progress

    def run(self):
        for task in self.tasks:
            self.task_queue.put(task)

        for i in range(self.worker_num):
            thread = threading.Thread(target=self.worker_thread, daemon=True)
            self.threads.append(thread)
            thread.start()

        threading.Thread(target=self.retry_thread, daemon=True).start()

        # 等待所有任务完成。
        # 不用 task_queue.join()：如果工作线程意外全部退出，join() 会永久挂起
        # （表现为程序变成僵尸进程，既不报错也不退出）。这里加看门狗。
        while True:
            try:
                if self.task_queue.unfinished_tasks == 0:
                    break
            except AttributeError:
                break
            if interrupt.should_stop():
                logger.warning("收到终止指令，停止等待剩余任务")
                break
            alive = [t for t in self.threads if t.is_alive()]
            if not alive:
                remaining = getattr(self.task_queue, "unfinished_tasks", 0)
                logger.error(
                    "所有工作线程已退出，但仍有 {} 个任务未完成，停止等待", remaining
                )
                break
            time.sleep(0.3)

        time.sleep(0.5)
        if hasattr(self.task_queue, "shutdown"):
            self.task_queue.shutdown()

    @log_error
    def worker_thread(self):
        while True:
            # 用户按 q 要求终止 -> 立刻停止领取新任务
            if interrupt.should_stop():
                return
            try:
                task = self.task_queue.get()
            except ShutDown:
                logger.info("Queue shut down")
                return

            # 关键：单个章节的异常不能让线程退出，否则任务永远不会 task_done，
            # 主线程会永久等待。异常统一转成 ERROR，交给下面的重试逻辑处理。
            try:
                task.result = process_chapter(self.chaoxing, task.course, task.point, self.speed)
            except BaseException as e:
                logger.error(
                    "处理章节时发生异常: {} - {} -> {}: {}",
                    task.course.get("title", "?"), task.point.get("title", "?"),
                    type(e).__name__, e
                )
                logger.debug(traceback.format_exc())
                task.result = ChapterResult.ERROR

            match task.result:
                case ChapterResult.SUCCESS:
                    logger.debug("Task success: {} - {}", task.course["title"], task.point["title"])
                    if self.progress:
                        self.progress.chapter_done(task.point.get("title", ""))
                    self.task_queue.task_done()
                    logger.debug(f"unfinished task: {self.task_queue.unfinished_tasks}")

                case ChapterResult.NOT_OPEN:
                    if self.config["notopen_action"] == "continue":
                        # 进度行已用 ⤼ 标记，这里只写日志文件，不刷屏
                        logger.info("章节未开启，已跳过: {} - {}", task.course["title"], task.point["title"])
                        if self.progress:
                            self.progress.chapter_skipped(task.point.get("title", ""), "未开放")
                        self.task_queue.task_done()
                        continue

                    task.tries += 1
                    if task.tries >= self.max_tries:
                        logger.info(
                            "章节未开启(重试已达上限): {} - {} 可能由于上一章节的章节检测未完成, "
                            "或该章节因时效已关闭，请手动检查完成并提交再重试。"
                            , task.course["title"], task.point["title"])
                        if self.progress:
                            self.progress.chapter_skipped(task.point.get("title", ""), "(未开放)")
                        self.task_queue.task_done()
                        continue

                    # self.wait_queue.put(task)
                    self.retry_queue.put(task)

                case ChapterResult.ERROR:
                    task.tries += 1
                    # 重试过程写日志文件即可，控制台由进度行体现
                    logger.info("重试任务 {} - {} ({}/{} 次尝试)", task.course["title"], task.point["title"],
                                task.tries,
                                self.max_tries)
                    if task.tries >= self.max_tries:
                        # 进度行已用 ✗ 标记
                        logger.info("任务重试次数达到上限: {} - {}", task.course["title"], task.point["title"])
                        self.failed_tasks.append(task)
                        if self.progress:
                            self.progress.chapter_failed(task.point.get("title", ""))
                        self.task_queue.task_done()
                        continue
                    self.retry_queue.put(task)

                case _:
                    logger.error("任务 {} 的状态无效 {}", task.result, task.point["title"])
                    self.failed_tasks.append(task)
                    self.task_queue.task_done()

    @log_error
    def retry_thread(self):
        try:
            while True:
                task = self.retry_queue.get()
                self.task_queue.put(task)
                # task_done is not called when a task failed and needs to be retried so if is reinserted into the queue,
                # the task num will increase by one and become more than the real task number
                self.task_queue.task_done()
                time.sleep(self.retry_interval)
        except ShutDown:
            pass


def process_chapter(chaoxing: Chaoxing, course: dict[str, Any], point: dict[str, Any], speed: float,
                    engine_info: bool = False) -> ChapterResult:
    """处理单个章节

    engine_info=True：这次章节是任务引擎的"章节"任务点，打点要带引擎标记，
    完成后由调用方用平台下发的 stuJobInfo 做 autoPullChapterScore 同步。
    """
    # 用户已要求终止：不再开始新章节
    if interrupt.should_stop():
        return ChapterResult.ERROR
    logger.info(f'当前章节: {point["title"]}')
    if point["has_finished"]:
        logger.info(f'章节：{point["title"]} 已完成所有任务点')
        return ChapterResult.SUCCESS

    # 随机等待，避免请求过快
    chaoxing.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)

    # 获取当前章节的所有任务点
    job_info = None
    jobs, job_info = chaoxing.get_job_list(course, point)

    # jobs 为 None = 任务点没读到（登录失效 / 风控 / 页面结构变化）。
    # 这时绝不能返回 SUCCESS：那会让这一章在进度里被打勾，
    # 整门课都这样时还会报"全部完成"，其实一个任务点都没做（#223 / #357）。
    if jobs is None:
        logger.error("章节任务点读取失败，稍后重试: {}", point.get("title", ""))
        return ChapterResult.ERROR

    # 发现未开放章节, 根据配置处理
    if job_info.get("notOpen", False):
        return ChapterResult.NOT_OPEN

    # 已经默认处理空任务，此处不需要判断
    if not jobs:
        pass

    job_results: list[StudyResult] = []
    for job in jobs:
        result = process_job(chaoxing, course, job, job_info, speed, engine_info=engine_info)
        job_results.append(result)

    for result in job_results:
        if result.is_failure():
            return ChapterResult.ERROR

    return ChapterResult.SUCCESS


def process_course(chaoxing: Chaoxing, course: dict[str, Any], config: dict):
    """处理单个课程"""
    logger.info(f"开始学习课程: {course['title']}")

    # 获取当前课程的所有章节
    point_list = chaoxing.get_course_point(
        course["courseId"], course["clazzId"], course["cpi"]
    )

    # 为了支持课程任务回滚, 采用下标方式遍历任务点

    _old_format_sizeof = tqdm.format_sizeof
    tqdm.format_sizeof = format_time
    try:
        tasks = []
        for i, point in enumerate(point_list["points"]):
            task = ChapterTask(point=point, index=i, course=course)
            tasks.append(task)
        p = JobProcessor(chaoxing, tasks, config)
        p.run()
    finally:
        # 无论成功、失败还是被中断，都要把 tqdm 的全局格式恢复回去
        tqdm.format_sizeof = _old_format_sizeof


def _parse_max_points(raw):
    """
    解析 max_points_per_course 配置。

    支持：
      3                   -> ({}, 3, [])            全部课程都刷 3 个
      2151141:3,189191:0  -> ({'2151141':3, ...}, 0, [])
      0 或空              -> ({}, 0, [])            全部刷完
    返回 (每课程字典, 默认值, 无法识别的片段)

    第三个返回值很重要：如果用户填了东西却一个都认不出来，
    必须停下来提醒，绝不能默默当成"全部刷完"。
    """
    if raw is None:
        return {}, 0, []
    text = str(raw).strip()
    if not text:
        return {}, 0, []

    per_course = {}
    default = None
    bad = []

    for item in re.split(r"[，,、;；\s]+", text):
        item = item.strip()
        if not item:
            continue
        if ":" in item or "：" in item:
            # 课程ID:数量
            parts = re.split(r"[:：]", item, maxsplit=1)
            cid = parts[0].strip()
            try:
                num = int(parts[1].strip())
            except (ValueError, IndexError):
                bad.append(item)
                continue
            if not cid:
                bad.append(item)
                continue
            per_course[cid] = max(0, num)
        else:
            # 单个数字 = 全局默认
            try:
                default = max(0, int(item))
            except ValueError:
                bad.append(item)
                continue

    if default is None:
        default = 0
    return per_course, default, bad


def select_points_for_course(all_points, max_points=0):
    """
    把一门课的章节分成"已完成"和"待刷"两部分，并算出本次要刷哪些。

    已完成（has_finished）的章节直接跳过，不再排进任务队列 ——
    否则每节都会闪过一行"预计 1 秒"，看起来像是要把前面几章重刷一遍。

    返回 (已完成, 待刷, 本次要刷)
    """
    all_points = list(all_points or [])
    finished = [p for p in all_points if p.get("has_finished")]
    pending = [p for p in all_points if not p.get("has_finished")]
    if max_points and max_points > 0:
        selected = pending[:max_points]
    else:
        selected = pending
    return finished, pending, selected


def _format_course_table(all_course):
    """格式化课程列表，供用户选择或报错时展示"""
    lines = ["*" * 10 + "课程列表" + "*" * 10]
    for course in all_course:
        lines.append(f"ID: {course['courseId']} 班级ID: {course['clazzId']} 课程名: {course['title']}")
    lines.append("*" * 28)
    return "\n".join(lines)


def _parse_course_ids(raw):
    """
    解析用户输入的课程ID，兼容中文逗号 / 空格 / 换行 / 全角数字等常见误输入。
    返回去重后的 ID 列表。
    """
    if raw is None:
        return []
    # 已经是列表（例如配置里解析后的 course_list）则逐个处理，避免 str(list) 变成 "['111']"
    if isinstance(raw, (list, tuple, set)):
        candidates = [str(x) for x in raw]
    else:
        # 中文逗号、顿号、分号、空格、换行统一成英文逗号
        candidates = re.sub(r"[，、；;\s]+", ",", str(raw).strip()).split(",")
    parts = []
    for item in candidates:
        item = item.strip().strip('"').strip("'")
        # 全角数字转半角
        item = item.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if item:
            parts.append(item)
    return list(dict.fromkeys(parts))


def filter_courses(all_course, course_list):
    """
    过滤要学习的课程。

    规则（严格模式）：
      必须明确指定要刷的课程 ID。
        - 匹配成功   -> 只刷这些课程
        - 一个都没匹配上 -> 报错停止，绝不回退全刷
        - 没有指定(空)   -> 报错停止，绝不自动刷全部课程

    历史上这里有个"没指定就刷全部课程"的兜底逻辑，曾导致用户只想刷 1 门课
    却把 12 门课全部刷了。该兜底已移除。
    """
    if not all_course:
        raise InputFormatError("登录成功但没读到任何课程，请检查账号是否有课程")

    # 没有配置课程 ID：打印课程表并停止，由用户明确指定
    wanted = _parse_course_ids(course_list)
    if not wanted:
        raise InputFormatError(
            "没有指定要刷的课程 ID，为避免误刷全部课程已停止运行。\n"
            "请把你想要刷的课程 ID 填到 config.ini 的 course_list，或运行 cx setup。\n"
            + _format_course_table(all_course)
        )

    course_task = []
    seen_keys = set()
    matched_ids = set()
    for course in all_course:
        key = (course["courseId"], course["clazzId"])
        if str(course["courseId"]) in wanted and key not in seen_keys:
            course_task.append(course)
            seen_keys.add(key)
            matched_ids.add(str(course["courseId"]))

    if not course_task:
        raise InputFormatError(
            "配置的 course_list 没有匹配到任何课程，为避免误刷已停止运行。\n"
            f"你填写的: {', '.join(wanted)}\n"
            "请从下面的课程列表里复制正确的 ID 后重试:\n"
            + _format_course_table(all_course)
        )

    missing = [cid for cid in wanted if cid not in matched_ids]
    if missing:
        logger.warning(
            "以下课程ID未匹配到任何课程, 已忽略: {}", ", ".join(missing)
        )

    return course_task


def format_time(num, suffix='', divisor=''):
    total_time = round(num)
    sec = total_time % 60
    mins = (total_time % 3600) // 60
    hrs = total_time // 3600

    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{sec:02d}"

    return f"{mins:02d}:{sec:02d}"


# ---------------------------------------------------------------- 任务中心

# 一个教学任务最多交替推进几轮（每完成一组，下一组才会解锁）
TASK_CENTER_MAX_ROUNDS = 6


def _task_center_enabled(common_config: dict, args) -> bool:
    """任务中心开关：命令行 > 配置文件 > 默认开启"""
    cli = getattr(args, "task_center", None)
    if cli is not None:
        return bool(cli)
    value = common_config.get("task_center", True)
    if value is None:
        return True
    if isinstance(value, str):
        return str_to_bool(value)
    return bool(value)


def _chapter_study_enabled(common_config: dict, args) -> bool:
    """章节（目录）开关：命令行 > 配置文件 > 默认开启"""
    cli = getattr(args, "chapter_study", None)
    if cli is not None:
        return bool(cli)
    value = common_config.get("chapter_study", True)
    if value is None:
        return True
    if isinstance(value, str):
        return str_to_bool(value)
    return bool(value)


def _discussion_mode_for_run(common_config: dict, task_center_enabled: bool,
                             only_discussion: bool) -> str:
    """把讨论处理方式约束在本轮的任务中心范围内。

    向导每轮都会重写范围，但旧账号配置、手改配置或 CLI 覆盖仍可能留下 board。
    当本轮不跑任务中心时，把它降为 none，确保章节流程没有讨论区分派或提示。
    """
    if not (task_center_enabled or only_discussion):
        return "none"
    mode = str(common_config.get("discussion_mode", "") or "task").strip().lower()
    return mode if mode in ("task", "board") else "task"


def _teaching_task_finished(task: dict) -> bool:
    """教学任务在列表里的完成进度（1.0 = 全部刷完）"""
    try:
        return float(task.get("taskStudyProgress") or 0) >= 1.0
    except (TypeError, ValueError):
        return False


def _load_course_point_map(chaoxing: Chaoxing, course: dict) -> dict:
    """knowledgeId -> 章节点。教学任务里的"章节"类型任务点要靠它落回章节刷课逻辑"""
    try:
        point_list = chaoxing.get_course_point(
            course["courseId"], course["clazzId"], course["cpi"]
        )
    except Exception as e:
        logger.warning(
            "读取《{}》章节失败，教学任务里的章节类任务点这次先跳过: {}",
            course.get("title", "?"), e,
        )
        return {}
    points = (point_list or {}).get("points") or []
    return {str(point.get("id")): point for point in points}


def _complete_teaching_plan(tc: TaskCenter, chaoxing: Chaoxing, course: dict, plan: dict,
                            info: dict, config: dict, point_map: dict):
    """
    完成一个教学任务点。

    返回 True(已完成) / False(没完成) / None(类型不支持)。
    新任务中心客户端会额外写入 ``last_outcome``，旧的 FakeTC/调用方仍可只看 bool。
    """
    if hasattr(tc, "last_outcome"):
        tc.last_outcome = TaskOutcome.FAILED
    try:
        plan_type = int(plan.get("planType"))
    except (TypeError, ValueError):
        plan_type = -1
    name = plan.get("name", "?")
    type_name = plan_type_name(plan_type)

    if plan_type not in SUPPORTED_PLAN_TYPES:
        logger.info("教学任务点类型暂不支持，需要手动完成: [{}] {}", type_name, name)
        if hasattr(tc, "last_outcome"):
            tc.last_outcome = TaskOutcome.UNSUPPORTED
        return None

    if plan_type == PLAN_TYPE_CHAPTER:
        # 章节类型：任务点带 knowledgeId，直接复用章节刷课逻辑。
        # 与普通章节刷课的唯一区别是要带任务引擎标记，并在刷完后把平台
        # 下发的 stuJobInfo 交给 autoPullChapterScore（任务引擎才认账）。
        knowledge_id = str(plan.get("externalDataId") or "")
        point = point_map.get(knowledge_id)
        if point is None:
            logger.warning("教学任务里的章节在目录中找不到: {}（knowledgeId={}）", name, knowledge_id)
            return False
        if hasattr(chaoxing, "last_student_job_info"):
            chaoxing.last_student_job_info = None
        logger.info("任务中心章节任务点: {}（knowledgeId={}）", name, knowledge_id)
        result = process_chapter(chaoxing, course, point, config["speed"], engine_info=True)
        if result != ChapterResult.SUCCESS:
            logger.info("教学任务中的章节未完成: {} -> {}", name, result)
            return False
        job_info = getattr(chaoxing, "last_student_job_info", None)
        if isinstance(job_info, dict) and job_info:
            logger.info("教学任务章节刷完，正在同步给任务引擎: {}", name)
            if not tc.sync_chapter_plan(info["encryTaskUserId"], job_info):
                # 同步请求没被接受时不能继续等：引擎不认这一章的完成
                logger.warning("章节成绩同步未被接受，本次不计完成: {}", name)
                return False
        else:
            # 平台没下发同步数据（常见于章节本来就已经刷完）：不伪造 enc，
            # 交给下面的 wait_plan_finished 复查，完成与否只认引擎状态。
            logger.info("章节已完成但平台未下发同步数据（stuJobInfo），等待任务引擎更新: {}", name)
    else:
        # 视频 / 文档：走任务引擎自己的学习页
        study_url = tc.get_study_url(info["encryTaskUserId"], plan.get("encryptPlanId", ""))
        if not study_url:
            return False
        if plan_type == PLAN_TYPE_VIDEO:
            logger.info("任务中心视频任务点: {}", name)
            if not tc.study_video(study_url, plan):
                if hasattr(tc, "last_outcome"):
                    tc.last_outcome = TaskOutcome.FAILED
                logger.warning("任务中心视频任务未完成: {}", name)
                return False
        elif plan_type == PLAN_TYPE_DOCUMENT:
            logger.info("任务中心文档任务点: {}", name)
            if not tc.study_document(study_url, plan):
                if hasattr(tc, "last_outcome"):
                    tc.last_outcome = TaskOutcome.FAILED
                logger.warning("任务中心文档任务未完成: {}", name)
                return False
        elif plan_type == PLAN_TYPE_HOMEWORK:
            study_homework = getattr(tc, "study_homework", None)
            if not callable(study_homework):
                logger.info("教学任务点类型暂不支持，需要手动完成: [{}] {}", type_name, name)
                if hasattr(tc, "last_outcome"):
                    tc.last_outcome = TaskOutcome.UNSUPPORTED
                return None
            logger.info("任务中心作业任务点: {}", name)
            if not study_homework(study_url, plan, course):
                if hasattr(tc, "last_outcome"):
                    tc.last_outcome = TaskOutcome.FAILED
                logger.warning("任务中心作业任务未完成: {}", name)
                return False
        elif plan_type == PLAN_TYPE_DISCUSS:
            study_discussion = getattr(tc, "study_discussion", None)
            if not callable(study_discussion):
                logger.info("教学任务点类型暂不支持，需要手动完成: [{}] {}", type_name, name)
                if hasattr(tc, "last_outcome"):
                    tc.last_outcome = TaskOutcome.UNSUPPORTED
                return None
            logger.info("任务中心主题讨论任务点: {}", name)
            if not study_discussion(study_url, plan, course):
                if hasattr(tc, "last_outcome"):
                    tc.last_outcome = TaskOutcome.FAILED
                logger.warning("任务中心主题讨论任务未完成: {}", name)
                return False
        elif plan_type == PLAN_TYPE_AI:
            study_ai = getattr(tc, "study_ai_practice", None)
            if not callable(study_ai):
                logger.info("教学任务点类型暂不支持，需要手动完成: [{}] {}", type_name, name)
                if hasattr(tc, "last_outcome"):
                    tc.last_outcome = TaskOutcome.UNSUPPORTED
                return None
            logger.info("任务中心 AI 实践任务点: {}", name)
            if not study_ai(study_url, plan):
                return False

    if tc.wait_plan_finished(
        info["encryTaskUserId"], plan.get("encryptGroupId", ""), plan.get("planId")
    ):
        if hasattr(tc, "last_outcome"):
            tc.last_outcome = TaskOutcome.COMPLETED
        return True
    # 动作发出去了但任务中心还没显示完成：不算成功，下次运行会重试
    logger.info("任务点已执行，但任务中心暂未显示完成（可能还在同步）: {}", name)
    if hasattr(tc, "last_outcome"):
        tc.last_outcome = TaskOutcome.FAILED
    return False


def _process_teaching_task(tc: TaskCenter, chaoxing: Chaoxing, course: dict, task: dict,
                           config: dict, point_map: dict,
                           only_discussion: bool = False, stats: dict = None,
                           skip_discussion: bool = False) -> tuple:
    """
    按分组顺序推进一个教学任务。

    任务引擎是"通关式"的：只有 groupAllowStudy=True 的分组能学，
    上一组全部完成之后，下一组才会解锁，所以要反复重新读取分组状态。
    """
    logger.debug("教学任务：{} - {}", course.get("title", "?"), task.get("name", "?"))
    print(f"    ▸ 教学任务：{task.get('name', '?')}")
    unsupported = set()
    # 本次运行里已经失败过的任务点：不再重试。
    # 任务引擎的重试轮次是为"上一组刚完成、下一组还没解锁"准备的，
    # 拿它去重试一个真的失败的任务点只会白烧时间（AI实践重试一次就是好几分钟）。
    failed_plans = set()
    if hasattr(tc, "last_outcome"):
        tc.last_outcome = TaskOutcome.FAILED
    if hasattr(tc, "waiting_confirmation"):
        tc.waiting_confirmation = False

    skipped_other_ids = set()      # 只刷讨论时，同一计划多轮扫描只计一次
    for _ in range(TASK_CENTER_MAX_ROUNDS):
        if interrupt.should_stop():
            return False, unsupported
        info = tc.open_task(task)
        if not info:
            return False, unsupported
        groups = tc.get_groups(info["encryTaskUserId"])
        if not isinstance(groups, list) or not groups:
            return False, unsupported

        allowed_left = 0
        locked_left = 0
        skipped_failed = 0
        progressed = False
        saw_plan_data = False
        skipped_other = 0
        for group in groups:
            plans = tc.get_plans(info["encryTaskUserId"], group.get("encryptGroupId", ""))
            if getattr(tc, "last_plan_read_failed", False):
                logger.warning("教学任务点状态读取失败，本次不判定为完成")
                return False, unsupported
            if plans:
                saw_plan_data = True
            unfinished = [p for p in plans if not tc.plan_finished(p)]
            if not group.get("groupAllowStudy"):
                locked_left += len(unfinished)
                continue
            for plan in unfinished:
                if interrupt.should_stop():
                    return False, unsupported
                plan_key = str(plan.get("planId"))
                plan_type = int(plan.get("planType") or -1)
                skip_this = (only_discussion and plan_type != PLAN_TYPE_DISCUSS) or \
                    (skip_discussion and plan_type == PLAN_TYPE_DISCUSS)
                if skip_this:
                    if plan_key not in skipped_other_ids:
                        skipped_other_ids.add(plan_key)
                        if stats is not None:
                            stats["skipped_other"] = stats.get("skipped_other", 0) + 1
                    continue
                if plan_key in failed_plans:
                    skipped_failed += 1
                    continue
                allowed_left += 1
                result = _complete_teaching_plan(
                    tc, chaoxing, course, plan, info, config, point_map
                )
                if result is True:
                    progressed = True
                elif result is None:
                    unsupported.add(plan_type_name(plan.get("planType")))
                    # 同一轮内不再重复尝试不支持的类型（否则每轮都会重读一遍并重复写日志）
                    failed_plans.add(plan_key)
                elif getattr(tc, "last_outcome", None) == TaskOutcome.WAITING_CONFIRMATION:
                    # 用户明确取消或当前没有交互终端时，停止当前教学任务，避免继续触发别的提交。
                    return False, unsupported
                else:
                    failed_plans.add(plan_key)

        if allowed_left == 0 and locked_left == 0 and skipped_failed == 0 and saw_plan_data:
            # 所有任务点都已经完成：这是"完成"，不是"失败"。
            # 之前这里直接 return，last_outcome 还停在开头的 FAILED，
            # 调用方（或读日志的人）会把一次成功的跳过看成失败。
            if hasattr(tc, "last_outcome"):
                tc.last_outcome = TaskOutcome.COMPLETED
            return True, unsupported
        if not progressed:
            if allowed_left == 0 and locked_left:
                # 上一组刚完成，解锁要等任务引擎同步一下，再读一次分组
                tc.last_outcome = TaskOutcome.LOCKED
                time.sleep(3)
                continue
            break

    # 收尾复查：可能最后几个任务点刚同步完成
    info = tc.open_task(task)
    if info:
        remaining = 0
        locked_remaining = 0
        groups = tc.get_groups(info["encryTaskUserId"])
        if not isinstance(groups, list) or not groups:
            return False, unsupported
        saw_plan_data = False
        for group in groups:
            plans = tc.get_plans(
                info["encryTaskUserId"], group.get("encryptGroupId", "")
            )
            if getattr(tc, "last_plan_read_failed", False):
                return False, unsupported
            if plans:
                saw_plan_data = True
            if not group.get("groupAllowStudy"):
                locked_remaining += sum(1 for plan in plans if not tc.plan_finished(plan))
                continue
            for plan in plans:
                if tc.plan_finished(plan):
                    continue
                plan_type = int(plan.get("planType") or -1)
                if only_discussion and plan_type != PLAN_TYPE_DISCUSS:
                    continue
                if skip_discussion and plan_type == PLAN_TYPE_DISCUSS:
                    continue
                remaining += 1
        if remaining == 0 and locked_remaining == 0 and saw_plan_data:
            if hasattr(tc, "last_outcome"):
                tc.last_outcome = TaskOutcome.COMPLETED
            return True, unsupported
        if locked_remaining and hasattr(tc, "last_outcome"):
            tc.last_outcome = TaskOutcome.LOCKED
    return False, unsupported


def run_task_center_phase(chaoxing: Chaoxing, course_task: list, config: dict,
                           max_tasks=None, only_discussion: bool = False,
                           skip_discussion: bool = False) -> dict:
    """
    任务中心 -> 教学任务。

    和"章节"互相独立：章节全刷完的课程也可能还有教学任务，
    所以这一步在章节之后单独跑，失败只影响它自己。

    max_tasks: (每课程字典, 默认值)，来自 max_tasks_per_course；
    不传时从 config 里现解析（0 = 全部）。只限制要处理的教学任务个数，
    不会把"被限制没刷"当成失败。
    """
    if max_tasks is None:
        max_tasks_map, max_tasks_default, _bad = _parse_max_points(
            config.get("max_tasks_per_course")
        )
    else:
        max_tasks_map, max_tasks_default = max_tasks
    tc = TaskCenter(chaoxing, config)
    stats = {
        "courses": 0,
        "tasks": 0,
        "done": 0,
        "failed": 0,
        "unsupported": 0,
        "waiting_confirmation": 0,
        "locked": 0,
        "read_failed": 0,
        "limited": 0,
        "skipped_other": 0,     # 只刷讨论时被跳过的其它类型
        "only_discussion": bool(only_discussion),
        "empty": 0,             # 没有教学任务的课程数
    }

    for course in course_task:
        if interrupt.should_stop():
            break
        try:
            tasks = tc.get_course_tasks(course)
        except Exception as e:
            logger.warning("读取《{}》教学任务失败: {}", course.get("title", "?"), e)
            stats["read_failed"] += 1
            continue
        if getattr(tc, "last_read_failed", False):
            stats["read_failed"] += 1
            logger.warning("读取《{}》教学任务失败，本次不判定为完成", course.get("title", "?"))
            print(f"  ✗ {course.get('title', '?')}：任务中心状态读取失败，无法判断是否完成")
            continue
        if not tasks:
            stats["empty"] += 1
            print(f"  {course.get('title', '?')}：没有找到教学任务（可能还没发布）")
            continue

        stats["courses"] += 1
        pending_all = [t for t in tasks if not _teaching_task_finished(t)]
        limit = max_tasks_map.get(str(course.get("courseId")), max_tasks_default)
        pending = pending_all[:limit] if limit and limit > 0 else pending_all
        print()
        print(
            "  " + course.get("title", "?") + "：任务中心共 "
            + str(len(tasks)) + " 个教学任务"
            + (f"，待完成 {len(pending_all)} 个" if pending_all else "，已全部完成")
        )
        if limit and limit > 0 and len(pending_all) > len(pending):
            stats["limited"] += len(pending_all) - len(pending)
            print(f"      本次按设置只刷前 {limit} 个待完成教学任务，其余下次继续")
        logger.debug("任务中心《{}》：{} 个教学任务，待完成 {} 个，本次处理 {} 个",
                     course.get("title", "?"), len(tasks), len(pending_all), len(pending))
        if not pending:
            continue

        point_map = _load_course_point_map(chaoxing, course)
        for task in pending:
            if interrupt.should_stop():
                break
            stats["tasks"] += 1
            try:
                ok, unsupported = _process_teaching_task(
                    tc, chaoxing, course, task, config, point_map,
                    only_discussion=only_discussion, stats=stats,
                    skip_discussion=skip_discussion,
                )
            except Exception as e:
                logger.error("处理教学任务出错: {} - {}: {}", task.get("name", "?"),
                             type(e).__name__, e)
                logger.debug(traceback.format_exc())
                ok, unsupported = False, set()
            if ok:
                stats["done"] += 1
                print("      ✓ 完成")
            else:
                stats["failed"] += 1
                outcome = getattr(tc, "last_outcome", TaskOutcome.FAILED)
                if outcome == TaskOutcome.WAITING_CONFIRMATION:
                    stats["waiting_confirmation"] += 1
                    print("      ⏸ 等待确认（未提交，稍后可继续）")
                elif unsupported:
                    # 当前组有暂不支持的任务点时，即使后续组也处于锁定状态，
                    # 先报告真正阻塞解锁的原因，避免把“暂不支持”模糊成“未解锁”。
                    stats["unsupported"] += 1
                    print(
                        "      ⤼ 跳过（含暂不支持的任务点："
                        + "、".join(sorted(unsupported)) + "，需要手动完成）"
                    )
                elif outcome == TaskOutcome.LOCKED:
                    stats["locked"] += 1
                    print("      ⤼ 还没轮到（要先完成前面的任务）")
                else:
                    print("      ✗ 未完成（可能要先完成前面的任务）")
    return stats


def _board_result_text(result: Optional[dict]) -> str:
    """讨论区结果一句话（失败/一条没发时绝不写"已发送"）"""
    result = result or {}
    sent = int(result.get("sent") or 0)
    skipped = int(result.get("skipped") or 0)
    if sent:
        return f"讨论区：发送 {sent} 条 · 跳过 {skipped} 条"
    if skipped:
        return f"讨论区：本次没有发送任何回复（跳过 {skipped} 条）"
    reason = str(result.get("reason") or "没有可发送的内容")
    return f"讨论区：本次没有发送任何回复（{reason}）"


def _print_board_result(result: Optional[dict]) -> None:
    """控制台汇报：发送了就说发送，没发送就说没发送"""
    result = result or {}
    sent = int(result.get("sent") or 0)
    if sent:
        print("  ✔ " + _board_result_text(result))
    else:
        print("  ⚠ " + _board_result_text(result))


def _run_discussion_board(chaoxing: Chaoxing, config: dict, courses: list) -> dict:
    """讨论区模式（discussion_mode=board）：列帖子 → 自己挑 → 草稿 → 确认 → 逐条发送。

    返回 discuss_cli 的结果字典，调用方据此汇报——一条都没发时绝不能说"已发送"。
    """
    from api import discussion
    try:
        return discussion.discuss_cli(chaoxing, None, config, courses=courses)
    except Exception as e:
        logger.warning("讨论区模式出错: {}: {}", type(e).__name__, e)
        logger.debug(traceback.format_exc())
        print(f"  ⚠ 讨论区模式出错（不影响已完成的刷课）：{e}")
        return {"ok": False, "sent": 0, "skipped": 0, "reason": f"{type(e).__name__}: {e}"}


def _print_review_hint():
    """刷完后提示可以复核 AI 生成的文字（有留痕才提示，保持界面干净）"""
    try:
        from api import review
        count = review.count_today()
        if count:
            print(f"  AI 写的 {count} 条内容已经记下来 · 运行 ./cx review 可以查看和复核")
    except Exception:
        pass


def _start_interrupt(hint_shown: bool) -> bool:
    """启动 q 键监听；提示语整次运行只打一遍，避免每个阶段重复刷屏。"""
    if not hint_shown:
        interrupt.print_hint()
    interrupt.start_watcher()
    return True


def _run_task_center_quiet(chaoxing: Chaoxing, course_task: list, config: dict,
                           max_tasks=None, only_discussion: bool = False,
                           skip_discussion: bool = False) -> dict:
    """
    任务中心阶段包一层控制台静音。

    这一段的内部日志（任务点读取、逐页解析、题库明细）只写日志文件，
    控制台只保留用户能看懂的 print 结果行和 WARNING 以上。
    """
    set_console_quiet(True)
    try:
        return run_task_center_phase(chaoxing, course_task, config, max_tasks,
                                     only_discussion=only_discussion,
                                     skip_discussion=skip_discussion)
    finally:
        set_console_quiet(False)


def _print_task_center_summary(stats: dict):
    """任务中心处理结果：一条一条列，超过 76 列自动折行（别撑爆终端）"""
    if not stats or (not stats.get("courses") and not stats.get("read_failed")
                     and not stats.get("empty")):
        return
    if stats.get("empty") and not stats.get("done") and not stats.get("failed"):
        print("  任务中心：没有找到教学任务（这门课可能还没发布，或都在未解锁的分组里）")
        return
    parts = [f"教学任务完成 {stats.get('done', 0)} 个"]
    if stats.get("failed"):
        item = f"未完成 {stats['failed']} 个"
        if stats.get("unsupported"):
            item += f"（其中暂不支持 {stats['unsupported']} 个）"
        parts.append(item)
        if stats.get("waiting_confirmation"):
            parts.append(f"等待确认 {stats['waiting_confirmation']} 个")
        if stats.get("locked"):
            parts.append(f"未解锁 {stats['locked']} 个")
    if stats.get("read_failed"):
        parts.append(f"读取失败 {stats['read_failed']} 门课")
    if stats.get("limited"):
        parts.append(f"按设置跳过 {stats['limited']} 个（下次继续）")
    if stats.get("skipped_other"):
        if stats.get("only_discussion"):
            parts.append(f"只刷讨论：跳过其它类型 {stats['skipped_other']} 个")
        else:
            parts.append(f"讨论走讨论区模式：跳过主题讨论 {stats['skipped_other']} 个")
    text = "  任务中心：" + " · ".join(parts)
    import textwrap
    for line in textwrap.wrap(text, width=76, subsequent_indent="    ") or [text]:
        print(line)


def main():
    """主程序入口"""
    # cx discuss / cx topics 需要登录：没显式给 -c 时用最近使用的账号配置
    if ("--discuss" in sys.argv[1:] or "--list-topics" in sys.argv[1:]) \
            and not any(a in sys.argv[1:] for a in ("-c", "--config")):
        from api import accounts
        latest = accounts.latest_run_config()
        if latest:
            sys.argv.extend(["-c", latest])

    # cx review：翻阅 AI 生成过的文字，不进入刷课流程
    if "--review" in sys.argv[1:]:
        from api import review
        return review.review_cli([a for a in sys.argv[1:] if a != "--review"])

    _old_format_sizeof = None      # tqdm 全局格式补丁的恢复兜底（见 finally）
    hint_shown = False             # q 键提示整次运行只打一遍
    try:
        # 初始化配置
        common_config, tiku_config, notification_config, config_path, args = init_config()

        # 强制播放按照配置文件调节
        common_config["speed"] = min(2.0, max(1.0, common_config.get("speed", 1.0)))
        common_config["notopen_action"] = common_config.get("notopen_action", "retry")
        
        # 初始化增加章节学习次数配置
        add_learning_count = str_to_bool(common_config.get("add_learning_count", False))
        target_count = int(common_config.get("target_count", 100))

        # 刷课范围：章节（目录）和任务中心可以各自关闭，但不能两个都关
        chapters_enabled = _chapter_study_enabled(common_config, args)
        # 只刷讨论（任务中心里的主题讨论，planType=14）：默认关闭，可在向导里选第 4 项
        only_discussion = bool(getattr(args, "only_discussion", False)) or str(
            common_config.get("only_discussion", "") or ""
        ).strip().lower() in ("1", "true", "yes", "on")
        task_center_enabled = _task_center_enabled(common_config, args)
        if only_discussion:
            chapters_enabled = False
            # 只刷讨论走的是任务中心那条链路：这里强制打开，避免"两个都关"被启动检查拦下
            common_config["task_center"] = "true"
            task_center_enabled = True
        # 讨论的两种刷法只在任务中心范围内有效；纯章节轮必须是 none。
        discussion_mode = _discussion_mode_for_run(
            common_config, task_center_enabled, only_discussion
        )
        board_mode = discussion_mode == "board"
        # 讨论走讨论区模式时，任务中心里不再自动刷主题讨论（改由讨论区流程处理）
        skip_discussion = board_mode
        if only_discussion:
            print("  本次只刷讨论（" + ("讨论区挑帖" if board_mode else "任务里的主题讨论") + "）")
        if not chapters_enabled and not task_center_enabled:
            hard_stop(
                "章节和任务中心都被关掉了，没有可以刷的内容",
                "  当前配置：chapter_study = false、task_center = false",
                "  运行 cx 重新选择刷什么，或至少加一个开关：--chapters / --task-center",
            )

        # ===== 启动前人工确认门禁 =====
        # 配置缺失/将要降级运行时，必须人工确认；用户不确认就停止，绝不静默降级
        check_before_run(common_config, tiku_config, notification_config, config_path,
                         skip_confirm=getattr(args, "yes", False))

        # 每门课最多刷几个任务点（0 或空 = 全部）
        # 支持两种格式：
        #   max_points_per_course = 3                    全部课程都刷 3 个
        #   max_points_per_course = 2151141:3,189191:0   按课程分别指定（0=全部）
        # 一个都认不出来时必须停在原地提醒，绝不能默默退化成"全部刷完"。
        _raw_points = common_config.get("max_points_per_course")
        max_points_map, max_points_default, _bad_points = _parse_max_points(_raw_points)
        if _bad_points:
            hard_stop(
                "要刷的任务点数量填错了，无法识别",
                f"  当前填写：{_raw_points}\n"
                f"  认不出的部分：{'、'.join(_bad_points)}\n"
                "  正确写法：3                     → 每门课刷 3 个任务点\n"
                "            2151141:3,189191:0    → 指定课程刷 3 个，189191 刷完全部",
                "  运行 cx 重新选择要刷的任务点数量，或直接修改配置文件",
            )

        # 每门课最多刷几个教学任务（任务中心，0 = 全部）
        # 语法与 max_points_per_course 相同，同样不能把写错的当成"全部"。
        _raw_tasks = common_config.get("max_tasks_per_course")
        max_tasks_map, max_tasks_default, _bad_tasks = _parse_max_points(_raw_tasks)
        if _bad_tasks:
            hard_stop(
                "任务中心要刷的教学任务数量填错了，无法识别",
                f"  当前填写：{_raw_tasks}\n"
                f"  认不出的部分：{'、'.join(_bad_tasks)}\n"
                "  正确写法：3                     → 每门课刷 3 个教学任务\n"
                "            2151141:3,189191:0    → 指定课程刷 3 个，189191 刷完全部",
                "  运行 cx 重新选择要刷的教学任务数量，或直接修改配置文件",
            )

        # 初始化超星实例
        chaoxing = init_chaoxing(common_config, tiku_config, config_path=config_path)

        # 设置外部通知
        notification = Notification()
        notification.config_set(notification_config)
        notification = notification.get_notification_from_config()
        notification.init_notification()

        # 检查当前登录状态（网络抖动自动重试，不再一次就整轮崩）
        _login_state = with_network_retry(
            chaoxing.login,
            login_with_cookies=common_config.get("use_cookies", False),
            what="登录",
        )
        if not _login_state["status"]:
            raise LoginError(_login_state["msg"])

        # 获取所有的课程列表
        all_course = with_network_retry(chaoxing.get_course_list, what="读取课程列表")

        # 过滤要学习的课程
        course_task = filter_courses(all_course, common_config.get("course_list"))

        # cx discuss / cx topics：讨论区浏览 + 挑帖子回复（模式 2），不进刷课流程
        if getattr(args, "discuss", False) or getattr(args, "list_topics", False):
            from api import discussion
            result = discussion.discuss_cli(
                chaoxing, None, common_config,
                list_only=bool(getattr(args, "list_topics", False)),
                course_id=getattr(args, "course_id", None),
                courses=all_course or course_task,
            )
            return 0 if result.get("ok") else 1

        # 开始学习
        logger.trace(f"课程列表过滤完毕, 当前课程任务数量: {len(course_task)}")

        _old_format_sizeof = tqdm.format_sizeof
        tqdm.format_sizeof = format_time

        # 任务点数量已在启动检查时解析并校验（见上面的 max_points_map / max_points_default）
        tasks = []
        # 一个章节都没读到的课程：不能当成"已经刷完"，否则解析出问题时会误报"无需刷课"
        unreadable_courses = []
        scan_rows = []          # 开始前扫描：章节侧数据（复用这里已读到的章节）
        if not chapters_enabled:
            logger.info("chapter_study=false：跳过章节（目录）")
            if only_discussion:
                print("  只刷讨论：跳过章节（目录）")
            else:
                print("  已选择只刷任务中心：跳过章节（目录）")
            print()
        # 只刷任务中心时连章节列表都不用读，省掉一次请求，也不会误报"读不到章节"
        for course in (course_task if chapters_enabled else []):
            logger.trace(f"正在读取课程章节: {course['title']}")
            point_list = with_network_retry(
                chaoxing.get_course_point,
                course["courseId"], course["clazzId"], course["cpi"],
                what=f"读取《{course['title']}》的章节",
            )
            all_points = point_list.get("points") or []

            if not all_points:
                unreadable_courses.append(course["title"])
                scan_rows.append(scan.chapter_row(course, [], error="读不到章节"))
                logger.error("课程[{}] 没有读到任何章节", course["title"])
                print("  ⚠ " + course["title"] + "：没有读到任何章节（可能是页面结构变化或网络异常）")
                continue

            # 已经刷完的章节不再排进任务队列：整段跳过，只给一行汇总说明
            cid = str(course["courseId"])
            max_points = max_points_map.get(cid, max_points_default)
            finished, pending, selected = select_points_for_course(all_points, max_points)

            logger.debug(
                "课程[{}] 共 {} 节, 已完成 {} 节, 待刷 {} 节, 本次刷 {} 节",
                course["title"], len(all_points), len(finished), len(pending), len(selected)
            )
            print("  " + course["title"] + "：" + course_plan_summary(finished, pending, len(selected)))
            scan_rows.append(scan.chapter_row(course, all_points))

            for i, point in enumerate(selected):
                task = ChapterTask(point=point, index=i, course=course)
                tasks.append(task)

        # ---- 开始前扫描（默认开启、无需勾选）：把漏刷的东西一次说清楚 ----
        try:
            print()
            report = scan.run(
                chaoxing, course_task, common_config, scan_rows,
                chapters_enabled, _task_center_enabled(common_config, args),
                only_discussion=only_discussion, discussion_mode=discussion_mode,
            )
            if report:
                print(report)
                print()
        except Exception as e:
            logger.debug("开始前扫描失败（不影响刷课）: {}", e)

        # 所有课程都已经刷完：不用再走后面的刷课流程，也不用让用户白等
        if not tasks:
            tqdm.format_sizeof = _old_format_sizeof
            print()
            if unreadable_courses:
                # 读不到章节 ≠ 刷完了。宁可报错让人来看，也不能骗用户说"已全部完成"
                print("  ✘ 有课程没能读到章节，无法判断是否已刷完：" + "、".join(unreadable_courses))
                print("  可能是平台页面结构变化或网络异常，请稍后重试；如果一直这样请反馈。")
                print()
                try:
                    notification.send(
                        "超星刷课：读取失败\n以下课程没有读到章节：" + "、".join(unreadable_courses)
                    )
                except Exception:
                    pass
                sys.exit(4)
            # 章节刷完了不代表任务中心刷完了：教学任务是独立的一套学习入口
            tc_stats = {"courses": 0, "done": 0, "failed": 0, "unsupported": 0,
                        "waiting_confirmation": 0, "locked": 0, "read_failed": 0}
            board_result = None
            if _task_center_enabled(common_config, args) and not (only_discussion and board_mode):
                hint_shown = _start_interrupt(hint_shown)
                print()
                if chapters_enabled:
                    print("  章节已全部完成，继续检查任务中心的教学任务…")
                elif only_discussion and board_mode:
                    print("  下面进入讨论区（自己挑帖子回复）…")
                elif only_discussion:
                    print("  继续检查任务里的主题讨论…")
                else:
                    print("  继续检查任务中心的教学任务…")
                try:
                    tc_stats = _run_task_center_quiet(
                        chaoxing, course_task, common_config,
                        (max_tasks_map, max_tasks_default),
                        only_discussion=only_discussion,
                        skip_discussion=skip_discussion,
                    )
                    _print_task_center_summary(tc_stats)
                except Exception as e:
                    # 与主流程一致：任务中心整段软着陆，章节记录已经落库
                    logger.error("任务中心处理出错: {}: {}", type(e).__name__, e)
                    logger.debug(traceback.format_exc())
                    print(f"  ⚠ 任务中心处理出错（章节不受影响）：{type(e).__name__}: {e}")
                    tc_stats["read_failed"] = tc_stats.get("read_failed", 0) + 1
            if board_mode and not interrupt.should_stop():
                board_result = _run_discussion_board(chaoxing, common_config,
                                                     course_task or all_course)
            if interrupt.should_stop():
                # 在任务中心阶段被终止：绝不能走到下面的"全部完成"分支
                print()
                print("  已终止刷课。已完成的任务点会保留，下次运行会自动跳过。")
                try:
                    notification.send("超星刷课：已手动终止\n任务中心未全部完成，下次运行会接着刷")
                except Exception:
                    pass
                return
            _print_review_hint()
            if board_mode:
                _print_board_result(board_result)
            elif tc_stats["failed"] or tc_stats.get("read_failed"):
                if chapters_enabled:
                    print("  ✔ 章节任务点已完成；任务中心仍有未完成教学任务")
                else:
                    print("  ✔ 任务中心仍有未完成教学任务")
            elif tc_stats.get("empty") and not tc_stats.get("done"):
                print("  · 没有找到教学任务（这门课可能还没发布，或都在未解锁的分组里）")
            elif chapters_enabled:
                print("  ✔ 所有课程的任务点都已刷完，没有需要重刷的内容")
            else:
                print("  ✔ 任务中心的教学任务都已刷完")
            print()
            try:
                if tc_stats["failed"] or tc_stats.get("read_failed"):
                    notification.send(
                        "超星刷课：任务中心有未完成\n"
                        f"教学任务未完成：{tc_stats['failed']} 个，读取失败：{tc_stats.get('read_failed', 0)} 门课"
                        f"（含暂不支持类型 {tc_stats['unsupported']} 个）"
                    )
                elif chapters_enabled:
                    notification.send("超星刷课：无需刷课\n所有课程的任务点都已刷完")
                else:
                    notification.send("超星刷课：无需刷课\n任务中心的教学任务都已刷完")
            except Exception:
                pass
            return

        # 刷课开始：提示如何退出，并启动键盘监听（按 q 立即终止）
        hint_shown = _start_interrupt(hint_shown)

        # 记录开始时间 + 通知开始
        run_started_at = time.time()
        total_points = len(tasks)
        course_names = "、".join(c["title"] for c in course_task)
        log_file_only(f"开始刷课：{len(course_task)} 门课，共 {total_points} 个任务点", "INFO")
        notification.send(
            "超星刷课：已开始\n"
            f"课程（{len(course_task)} 门）：{course_names}\n"
            f"任务点：{total_points} 个"
        )

        # 打开控制台静音：刷课期间只显示 WARNING 及以上 + 进度行，
        # 避免 TRACE/DEBUG 刷屏（日志文件仍然记录全量）
        set_console_quiet(True)
        print()
        print(f"  开始刷课 · {len(course_task)} 门课 · 章节任务点 {total_points} 个")
        print("  ✓ 完成 · ⤼ 跳过 · ✗ 失败")
        print("  " + "─" * 46)
        print()

        progress = ChapterProgress(total_points)

        # 全局并发执行所有课程的任务点
        # 用 try/finally 保证无论成功、中断还是异常，控制台都会恢复非静音
        try:
            p = JobProcessor(chaoxing, tasks, common_config, progress=progress)
            p.run()
        finally:
            progress.summary()
            set_console_quiet(False)

        if interrupt.should_stop():
            logger.warning("刷课已被用户终止")
            print()
            print("  已终止刷课。已完成的任务点会保留，下次运行会自动跳过。")
            print()
            used = int(time.time() - run_started_at)
            try:
                notification.send(
                    "超星刷课：已手动终止\n"
                    f"课程（{len(course_task)} 门）：{course_names}\n"
                    f"任务点：{total_points} 个（未刷完）\n"
                    f"已运行：{used // 60} 分 {used % 60} 秒"
                )
            except Exception:
                pass
            return

        tqdm.format_sizeof = _old_format_sizeof

        # 任务中心：教学任务和章节是两套独立入口，章节跑完后再单独跑一遍
        tc_stats = {
            "courses": 0, "done": 0, "failed": 0, "unsupported": 0,
            "waiting_confirmation": 0, "locked": 0, "read_failed": 0,
        }
        if _task_center_enabled(common_config, args):
            logger.info("章节处理完毕，开始处理任务中心的教学任务...")
            try:
                tc_stats = _run_task_center_quiet(
                    chaoxing, course_task, common_config,
                    (max_tasks_map, max_tasks_default),
                    only_discussion=only_discussion,
                    skip_discussion=skip_discussion,
                )
                _print_task_center_summary(tc_stats)
            except Exception as e:
                # 任务中心整段软着陆：章节记录已经落库，不能因为这里的意外异常
                # 把后面的统计、学习次数都跳过（更不该让整次运行看起来崩了）。
                logger.error("任务中心处理出错: {}: {}", type(e).__name__, e)
                logger.debug(traceback.format_exc())
                print(f"  ⚠ 任务中心处理出错（章节不受影响）：{type(e).__name__}: {e}")
                tc_stats["read_failed"] = tc_stats.get("read_failed", 0) + 1

        if board_mode and not interrupt.should_stop():
            board_result = _run_discussion_board(chaoxing, common_config,
                                                 course_task or all_course)

        _print_review_hint()

        if interrupt.should_stop():
            # 终止发生在任务中心阶段：不能报"全部完成"（铁律 1）
            print()
            print("  已终止刷课。已完成的任务点会保留，下次运行会自动跳过。")
            try:
                notification.send("超星刷课：已手动终止\n已完成的任务点会保留，下次运行会自动跳过")
            except Exception:
                pass
            return

        used = int(time.time() - run_started_at)
        used_text = (f"{used // 60} 分 {used % 60} 秒" if used >= 60 else f"{used} 秒")

        # 有任务点没刷成功就不能说"全部完成"：否则用户以为已经刷完，
        # 实际上还差几节（#618）。这里按实际失败数量分开报。
        failed_points = getattr(progress, "failed", 0) or 0
        if failed_points or unreadable_courses or tc_stats["failed"] or tc_stats.get("read_failed"):
            # 一行汇总：细节在日志和通知里，控制台不刷屏
            parts = []
            if failed_points:
                parts.append(f"章节失败 {failed_points} 个")
            if unreadable_courses:
                parts.append(f"读不到章节 {len(unreadable_courses)} 门")
            if tc_stats["failed"]:
                detail = []
                if tc_stats["unsupported"]:
                    detail.append(f"暂不支持 {tc_stats['unsupported']}")
                if tc_stats.get("waiting_confirmation"):
                    detail.append(f"等待确认 {tc_stats['waiting_confirmation']}")
                if tc_stats.get("locked"):
                    detail.append(f"未解锁 {tc_stats['locked']}")
                parts.append(
                    "教学任务未完成 " + str(tc_stats["failed"])
                    + ("（" + "、".join(detail) + "）" if detail else "")
                )
            if tc_stats.get("read_failed"):
                parts.append(f"任务中心读取失败 {tc_stats['read_failed']} 门")
            summary_line = " · ".join(parts)
            logger.warning("本次未全部完成：" + summary_line)
            print()
            print("  ⚠ 本次没全部完成：" + summary_line + "（下次运行会自动继续）")
            print(flush=True)
            unreadable_text = ("\n读不到章节的课程：" + "、".join(unreadable_courses)) if unreadable_courses else ""
            tc_text = ""
            if tc_stats["failed"]:
                tc_text = f"\n任务中心：教学任务未完成 {tc_stats['failed']} 个"
                if tc_stats["unsupported"]:
                    tc_text += f"（含暂不支持类型 {tc_stats['unsupported']} 个）"
                if tc_stats.get("waiting_confirmation"):
                    tc_text += f"（等待确认 {tc_stats['waiting_confirmation']} 个）"
            if tc_stats.get("read_failed"):
                tc_text += f"\n任务中心：课程状态读取失败 {tc_stats['read_failed']} 门"
            notification.send(
                "超星刷课：部分完成（有失败）\n"
                f"课程（{len(course_task)} 门）：{course_names}\n"
                f"任务点：成功 {max(0, total_points - failed_points)} 个 · 失败 {failed_points} 个\n"
                f"耗时：{used_text}"
                f"{unreadable_text}"
                f"{tc_text}"
            )
        else:
            logger.info("所有课程学习任务已完成")
            tc_text = f"\n任务中心：教学任务完成 {tc_stats['done']} 个" if tc_stats["done"] else ""
            board_text = ("\n" + _board_result_text(board_result)) if board_mode else ""
            if board_mode:
                _print_board_result(board_result)
            notification.send(
                "超星刷课：全部完成\n"
                f"课程（{len(course_task)} 门）：{course_names}\n"
                f"任务点：{total_points} 个\n"
                f"耗时：{used_text}"
                f"{tc_text}"
                f"{board_text}"
            )

        # 刷课完成后，如果开启了增加章节学习次数，则执行
        # （只刷任务中心时跳过：这是章节功能，没有章节可刷）
        if add_learning_count and chapters_enabled:
            logger.info("刷课完成，开始增加章节学习次数...")
            common_config["target_count"] = target_count
            for course in course_task:
                increase_learning_count_for_course(chaoxing, course, common_config)
            logger.info("所有课程章节学习次数增加完成")
            notification.send("超星刷课：章节学习次数已刷完")
        
    except UserAbort as e:
        # 用户未确认/选择停止：不是程序错误，但用非 0 退出码，方便脚本判断"没跑成"
        logger.warning(f"已停止: {e}")
        sys.exit(3)
    except SystemExit as e:
        if e.code != 0:
            logger.error(f"错误: 程序异常退出, 返回码: {e.code}")
        sys.exit(e.code)
    except KeyboardInterrupt as e:
        logger.error(f"错误: 程序被用户手动中断, {e}")
    except (LoginError, InputFormatError, NetworkRetryFailed) as e:
        # 登录失败 / 网络不稳 / 输入格式错，都是用户自己处理一下就能解决的问题。
        # 只给一行清晰提示 + 处理办法，不打印一堆 traceback 吓人。
        log_file_only(str(e))
        print()
        print("  ✘ " + redact(e))
        if isinstance(e, NetworkRetryFailed):
            print("  网络不太稳定，请检查网络 / 代理后重试。")
        else:
            print("  请检查手机号 / 密码是否正确，或运行 cx setup 重新配置。")
        print(flush=True)
        try:
            notification.send(f"超星刷课：启动失败\n{e}")
        except Exception:
            pass
        sys.exit(2)
    except BaseException as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        try:
            notification.send(
                f"超星刷课：出现错误\n"
                f"{type(e).__name__}: {e}"
            )
        except Exception:
            pass  # 如果通知发送失败，忽略异常
        raise RuntimeError(redact(f"{type(e).__name__}: {e}")) from None
    finally:
        # 兜底恢复 tqdm 全局格式：中途 return / sys.exit / 异常都不能把它留在补丁状态
        if _old_format_sizeof is not None:
            tqdm.format_sizeof = _old_format_sizeof


if __name__ == "__main__":
    safe_console()
    main()
