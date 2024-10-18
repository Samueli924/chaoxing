# -*- coding: utf-8 -*-
import argparse
import configparser
from api.logger import logger
from api.base import Chaoxing, Account
from api.exceptions import LoginError, FormatError, JSONDecodeError
from api.answer import Tiku

def init_config():
    parser = argparse.ArgumentParser(description='Samueli924/chaoxing')  # 命令行传参
    parser.add_argument("-c", "--config", type=str, default=None, help="使用配置文件运行程序")
    parser.add_argument("-u", "--username", type=str, default=None, help="手机号账号")
    parser.add_argument("-p", "--password", type=str, default=None, help="登录密码")
    parser.add_argument("-l", "--list", type=str, default=None, help="要学习的课程ID列表")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="视频播放倍速(默认1，最大2)")
    args = parser.parse_args()
    if args.config:
        config = configparser.ConfigParser()
        config.read(args.config, encoding="utf8")
        return (config.get("common", "username"),
                config.get("common", "password"),
                str(config.get("common", "course_list")).split(",") if config.get("common", "course_list") else None,
                int(config.get("common", "speed")),
                config['tiku']
                )
    else:
        return (args.username, args.password, args.list.split(",") if args.list else None, int(args.speed) if args.speed else 1,None)


if __name__ == '__main__':
    try:
        # 初始化登录信息
        username, password, course_list, speed,tiku_config= init_config()
        # 规范化播放速度的输入值
        speed = min(2.0, max(1.0, speed))
        if (not username) or (not password):
            username = input("请输入你的手机号，按回车确认\n手机号:")
            password = input("请输入你的密码，按回车确认\n密码:")
        account = Account(username, password)
        # 设置题库
        tiku = Tiku()
        if not tiku_config: 
            # 尝试使用默认的config路径
            config = configparser.ConfigParser()
            config.read('config.ini', encoding="utf8")
            tiku_config = config['tiku']
        tiku.config_set(tiku_config)
        tiku = tiku.get_tiku_from_config()
        tiku.load_token()
        # 实例化超星API
        chaoxing = Chaoxing(account=account,tiku=tiku)
        # 检查当前登录状态，并检查账号密码
        _login_state = chaoxing.login()
        if not _login_state["status"]:
            raise LoginError(_login_state["msg"])
        # 获取所有的课程列表
        all_course = chaoxing.get_course_list()
        course_task = []
        # 手动输入要学习的课程ID列表
        if not course_list:
            print("*" * 10 + "课程列表" + "*" * 10)
            for course in all_course:
                print(f"ID: {course['courseId']} 课程名: {course['title']}")
            print("*" * 28)
            try:
                course_list = input("请输入想要学习的课程列表,以逗号分隔,例: 2151141,189191,198198\n").split(",")
            except Exception as e:
                raise FormatError("输入格式错误") from e
        # 筛选需要学习的课程
        for course in all_course:
            if course["courseId"] in course_list:
                course_task.append(course)
        if not course_task:
            course_task = all_course
        # 开始遍历要学习的课程列表
        logger.info(f"课程列表过滤完毕，当前课程任务数量: {len(course_task)}")
        for course in course_task:
            # 获取当前课程的所有章节
            point_list = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
            for point in point_list["points"]:
                # 获取当前章节的所有任务点
                jobs = []
                job_info = None
                jobs, job_info = chaoxing.get_job_list(course["clazzId"], course["courseId"], course["cpi"], point["id"])
                # 可能存在章节无任何内容的情况
                if not jobs:
                    continue
                # 遍历所有任务点
                for job in jobs:
                    # 视频任务
                    if job["type"] == "video":
                        logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
                        # 超星的接口没有返回当前任务是否为Audio音频任务
                        isAudio = False
                        try:
                            chaoxing.study_video(course, job, job_info, _speed=speed, _type="Video")
                        except JSONDecodeError as e:
                            logger.warning("当前任务非视频任务，正在尝试音频任务解码")
                            isAudio = True
                        if isAudio:
                            try:
                                chaoxing.study_video(course, job, job_info, _speed=speed, _type="Audio")
                            except JSONDecodeError as e:
                                logger.warning(f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}, 已跳过")
                    # 文档任务
                    elif job["type"] == "document":
                        logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
                        chaoxing.study_document(course, job)
                    # 测验任务
                    elif job["type"] == "workid":
                        logger.trace(f"识别到测验任务, 任务章节: {course['title']}")
                        chaoxing.study_work(course, job,job_info)
        logger.info("所有课程学习任务已完成")
    except BaseException as e:
        import traceback
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        raise e