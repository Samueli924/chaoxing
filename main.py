# -*- coding: utf-8 -*-
import argparse
import configparser
import random
import time
import sys
import os
import traceback
from urllib3 import disable_warnings, exceptions

from api.logger import logger
from api.base import Chaoxing, Account
from api.exceptions import LoginError, InputFormatError, MaxRollBackExceeded
from api.answer import Tiku
from api.notification import Notification

# 关闭警告
disable_warnings(exceptions.InsecureRequestWarning)


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Samueli924/chaoxing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--use-cookies", action="store_true", help="使用cookies登录")

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

    # 在解析之前捕获 -h 的行为
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


def load_config_from_file(config_path):
    """从配置文件加载设置"""
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf8")
    
    common_config = {}
    tiku_config = {}
    notification_config = {}
    
    # 检查并读取common节
    if config.has_section("common"):
        common_config = dict(config.items("common"))
        # 处理course_list，将字符串转换为列表
        if "course_list" in common_config and common_config["course_list"]:
            common_config["course_list"] = [item.strip() for item in common_config["course_list"].split(",") if item.strip()]
        # 处理speed，将字符串转换为浮点数
        if "speed" in common_config:
            common_config["speed"] = float(common_config["speed"])
        # 处理notopen_action，设置默认值为retry
        if "notopen_action" not in common_config:
            common_config["notopen_action"] = "retry"
        if "use_cookies" in common_config:
            common_config["use_cookies"] = str_to_bool(common_config["use_cookies"])
        if "username" in common_config and common_config["username"] is not None:
            common_config["username"] = common_config["username"].strip()
        if "password" in common_config and common_config["password"] is not None:
            common_config["password"] = common_config["password"].strip()
    
    # 检查并读取tiku节
    if config.has_section("tiku"):
        tiku_config = dict(config.items("tiku"))
        # 处理数值类型转换
        for key in ["delay", "cover_rate"]:
            if key in tiku_config:
                tiku_config[key] = float(tiku_config[key])

    # 检查并读取notification节
    if config.has_section("notification"):
        notification_config = dict(config.items("notification"))
    
    return common_config, tiku_config, notification_config


def build_config_from_args(args):
    """从命令行参数构建配置"""
    common_config = {
        "use_cookies": args.use_cookies,
        "username": args.username,
        "password": args.password,
        "course_list": [item.strip() for item in args.list.split(",") if item.strip()] if args.list else None,
        "speed": args.speed if args.speed else 1.0,
        "notopen_action": args.notopen_action if args.notopen_action else "retry"
    }
    return common_config, {}, {}


def init_config():
    """初始化配置"""
    args = parse_args()
    
    if args.config:
        return load_config_from_file(args.config)
    else:
        return build_config_from_args(args)


class RollBackManager:
    """课程回滚管理器，避免无限回滚"""
    def __init__(self):
        self.rollback_times = 0
        self.rollback_id = ""

    def add_times(self, id: str):
        """增加回滚次数"""
        if id == self.rollback_id and self.rollback_times == 3:
            raise MaxRollBackExceeded("回滚次数已达3次, 请手动检查学习通任务点完成情况")
        else:
            self.rollback_times += 1

    def new_job(self, id: str):
        """设置新任务，重置回滚次数"""
        if id != self.rollback_id:
            self.rollback_id = id
            self.rollback_times = 0


def init_chaoxing(common_config, tiku_config):
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
    tiku = Tiku()
    tiku.config_set(tiku_config)  # 载入配置
    tiku = tiku.get_tiku_from_config()  # 载入题库
    tiku.init_tiku()  # 初始化题库
    
    # 获取查询延迟设置
    query_delay = tiku_config.get("delay", 0)
    
    # 实例化超星API
    chaoxing = Chaoxing(account=account, tiku=tiku, query_delay=query_delay)
    
    return chaoxing


def handle_not_open_chapter(notopen_action, point, tiku, RB, auto_skip_notopen=False):
    """处理未开放章节"""
    if notopen_action == "retry":
        # 默认处理方式：重试
        # 针对题库启用情况
        if not tiku or tiku.DISABLE or not tiku.SUBMIT:
            # 未启用题库或未开启题库提交, 章节检测未完成会导致无法开始下一章, 直接退出
            logger.error(
                "章节未开启, 可能由于上一章节的章节检测未完成, 也可能由于该章节因为时效已关闭，"
                "请手动检查完成并提交再重试。或者在配置中配置(自动跳过关闭章节/开启题库并启用提交)"
            )
            return -1  # 退出标记
        RB.add_times(point["id"])
        return 0  # 重试上一章节
        
    elif notopen_action == "ask":
        # 询问模式 - 判断是否需要询问
        if not auto_skip_notopen:
            user_choice = input(f"章节 {point['title']} 未开放，是否继续检查后续章节？(y/n): ")
            if user_choice.lower() != 'y':
                # 用户选择停止
                logger.info("根据用户选择停止检查后续章节")
                return -1  # 退出标记
            # 用户选择继续，设置自动跳过标志
            logger.info("用户选择继续检查后续章节，将自动跳过连续的未开放章节")
            return 1, True  # 继续下一章节, 设置自动跳过
        else:
            logger.info(f"章节 {point['title']} 未开放，自动跳过")
            return 1, auto_skip_notopen  # 继续下一章节, 保持自动跳过状态
            
    else:  # notopen_action == "continue"
        # 继续模式，直接跳过当前章节
        logger.info(f"章节 {point['title']} 未开放，根据配置跳过此章节")
        return 1  # 继续下一章节


def process_job(chaoxing, course, job, job_info, speed):
    """处理单个任务点"""
    # 视频任务
    if job["type"] == "video":
        logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        # 超星的接口没有返回当前任务是否为Audio音频任务
        video_result = chaoxing.study_video(
            course, job, job_info, _speed=speed, _type="Video"
        )
        if chaoxing.StudyResult.is_failure(video_result):
            logger.warning("当前任务非视频任务, 正在尝试音频任务解码")
            video_result = chaoxing.study_video(
                course, job, job_info, _speed=speed, _type="Audio")
        if chaoxing.StudyResult.is_failure(video_result):
            logger.warning(
                f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}, 已跳过"
            )
    # 文档任务
    elif job["type"] == "document":
        logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        chaoxing.study_document(course, job)
    # 测验任务
    elif job["type"] == "workid":
        logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
        chaoxing.study_work(course, job, job_info)
    # 阅读任务
    elif job["type"] == "read":
        logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
        chaoxing.strdy_read(course, job, job_info)


def process_chapter(chaoxing, course, point, RB, notopen_action, speed, auto_skip_notopen=False):
    """处理单个章节"""
    logger.info(f'当前章节: {point["title"]}')
    
    if point["has_finished"]:
        logger.info(f'章节：{point["title"]} 已完成所有任务点')
        return 1, auto_skip_notopen  # 继续下一章节
    
    # 随机等待，避免请求过快
    sleep_duration = random.uniform(1, 3)
    logger.debug(f"本次随机等待时间: {sleep_duration:.3f}s")
    time.sleep(sleep_duration)
    
    # 获取当前章节的所有任务点
    jobs = []
    job_info = None
    jobs, job_info = chaoxing.get_job_list(
        course["clazzId"], course["courseId"], course["cpi"], point["id"]
    )

    # 发现未开放章节, 根据配置处理
    try:
        if job_info.get("notOpen", False):
            result = handle_not_open_chapter(
                notopen_action, point, chaoxing.tiku, RB, auto_skip_notopen
            )
            
            if isinstance(result, tuple):
                return result  # 返回继续标志和更新后的auto_skip_notopen
            else:
                return result, auto_skip_notopen
        
        # 遇到开放的章节，重置自动跳过状态
        auto_skip_notopen = False
        RB.new_job(point["id"])

    except MaxRollBackExceeded:
        logger.error("回滚次数已达3次, 请手动检查学习通任务点完成情况")
        # 跳过该课程
        return -1, auto_skip_notopen  # 退出标记
    
    chaoxing.rollback_times = RB.rollback_times
    
    # 可能存在章节无任何内容的情况
    if not jobs:
        if RB.rollback_times > 0:
            logger.trace(f"回滚中 尝试空页面任务, 任务章节: {course['title']}")
            chaoxing.study_emptypage(course, point)
        return 1, auto_skip_notopen  # 继续下一章节
    
    # 遍历所有任务点
    for job in jobs:
        process_job(chaoxing, course, job, job_info, speed)
    
    return 1, auto_skip_notopen  # 继续下一章节


def process_course(chaoxing, course, notopen_action, speed):
    """处理单个课程"""
    logger.info(f"开始学习课程: {course['title']}")
    
    # 获取当前课程的所有章节
    point_list = chaoxing.get_course_point(
        course["courseId"], course["clazzId"], course["cpi"]
    )

    # 为了支持课程任务回滚, 采用下标方式遍历任务点
    __point_index = 0
    # 记录用户是否选择继续跳过连续的未开放任务点
    auto_skip_notopen = False
    # 初始化回滚管理器
    RB = RollBackManager()
    
    while __point_index < len(point_list["points"]):
        point = point_list["points"][__point_index]
        logger.debug(f"当前章节 __point_index: {__point_index}")
        
        result, auto_skip_notopen = process_chapter(
            chaoxing, course, point, RB, notopen_action, speed, auto_skip_notopen
        )
        
        if result == -1:  # 退出当前课程
            break
        elif result == 0:  # 重试前一章节
            __point_index -= 1  # 默认第一个任务总是开放的
        else:  # 继续下一章节
            __point_index += 1


def filter_courses(all_course, course_list):
    """过滤要学习的课程"""
    if not course_list:
        # 手动输入要学习的课程ID列表
        print("*" * 10 + "课程列表" + "*" * 10)
        for course in all_course:
            print(f"ID: {course['courseId']} 课程名: {course['title']}")
        print("*" * 28)
        try:
            course_list = input(
                "请输入想要学习的课程列表,以逗号分隔,例: 2151141,189191,198198\n"
            ).split(",")
        except Exception as e:
            raise InputFormatError("输入格式错误") from e

    # 筛选需要学习的课程
    course_task = []
    for course in all_course:
        if course["courseId"] in course_list:
            course_task.append(course)
    
    # 如果没有指定课程，则学习所有课程
    if not course_task:
        course_task = all_course
    
    return course_task


def main():
    """主程序入口"""
    try:
        # 初始化配置
        common_config, tiku_config, notification_config = init_config()
        
        # 强制播放按照配置文件调节
        speed = min(2.0, max(1.0, common_config.get("speed", 1.0)))
        notopen_action = common_config.get("notopen_action", "retry")
        
        # 初始化超星实例
        chaoxing = init_chaoxing(common_config, tiku_config)
        
        # 设置外部通知
        notification = Notification()
        notification.config_set(notification_config)
        notification = notification.get_notification_from_config()
        notification.init_notification()
        
        # 检查当前登录状态
        _login_state = chaoxing.login(login_with_cookies=common_config.get("use_cookies", False))
        if not _login_state["status"]:
            raise LoginError(_login_state["msg"])
        
        # 获取所有的课程列表
        all_course = chaoxing.get_course_list()
        
        # 过滤要学习的课程
        course_task = filter_courses(all_course, common_config.get("course_list"))
        
        # 开始学习
        logger.info(f"课程列表过滤完毕, 当前课程任务数量: {len(course_task)}")
        for course in course_task:
            process_course(chaoxing, course, notopen_action, speed)
        
        logger.info("所有课程学习任务已完成")
        notification.send("chaoxing : 所有课程学习任务已完成")
        
    except SystemExit as e:
        if e.code != 0:
            logger.error(f"错误: 程序异常退出, 返回码: {e.code}")
        sys.exit(e.code)
    except KeyboardInterrupt as e:
        logger.error(f"错误: 程序被用户手动中断, {e}")
    except BaseException as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        try:
            notification.send(f"chaoxing : 出现错误 {type(e).__name__}: {e}\n{traceback.format_exc()}")
        except Exception:
            pass  # 如果通知发送失败，忽略异常
        raise e


if __name__ == "__main__":
    main()
