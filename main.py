# -*- coding: utf-8 -*-
import argparse
import configparser
from api.logger import logger
from api.base import Chaoxing, Account
from api.exceptions import LoginError, FormatError, JSONDecodeError,MaxRollBackError
from api.answer import Tiku
from urllib3 import disable_warnings,exceptions
import os

# # 定义全局变量，用于存储配置文件路径
# textPath = './resource/BookID.txt'

# # 获取文本 -> 用于查看学习过的课程ID
# def getText():
#     try: 
#         if not os.path.exists(textPath):
#             with open(textPath, 'x') as file: pass 
#             return []
#         with open(textPath, 'r', encoding='utf-8') as file: content = file.read().split(',')
#         content = {int(item.strip()) for item in content if item.strip()}
#         return list(content)
#     except Exception as e: logger.error(f"获取文本失败: {e}"); return []

# # 追加文本 -> 用于记录学习过的课程ID
# def appendText(text):
#     if not os.path.exists(textPath): return
#     with open(textPath, 'a', encoding='utf-8') as file: file.write(f'{text}, ') 
    

# 关闭警告
disable_warnings(exceptions.InsecureRequestWarning)

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

class RollBackManager:
    def __init__(self) -> None:
        self.rollback_times = 0
        self.rollback_id = ""

    def add_times(self,id:str) -> None:
        if id == self.rollback_id and self.rollback_times == 3:
            raise MaxRollBackError("回滚次数已达3次，请手动检查学习通任务点完成情况")
        elif id != self.rollback_id:
            # 新job
            self.rollback_id = id
            self.rollback_times = 1
        else:  
            self.rollback_times += 1


if __name__ == '__main__':
    try:
        # 避免异常的无限回滚
        RB = RollBackManager()
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
        tiku.config_set(tiku_config)    # 载入配置
        tiku = tiku.get_tiku_from_config()  # 载入题库
        tiku.init_tiku()    # 初始化题库
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
            logger.info(f"开始学习课程: {course['title']}")
            # 获取当前课程的所有章节
            point_list = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])

            # 为了支持课程任务回滚，采用下标方式遍历任务点
            __point_index = 0
            while __point_index < len(point_list["points"]):
                point = point_list["points"][__point_index]
                logger.info(f'当前章节: {point["title"]}')
                # 获取当前章节的所有任务点
                jobs = []
                job_info = None
                jobs, job_info = chaoxing.get_job_list(course["clazzId"], course["courseId"], course["cpi"], point["id"])
                
                # bookID = job_info["knowledgeid"] # 获取视频ID
                
                # 发现未开放章节，尝试回滚上一个任务重新完成一次
                try:
                    if job_info.get('notOpen',False):
                        __point_index -= 1  # 默认第一个任务总是开放的
                        # 针对题库启用情况
                        if not tiku or tiku.DISABLE or not tiku.SUBMIT:
                            # 未启用题库或未开启题库提交，章节检测未完成会导致无法开始下一章，直接退出
                            logger.error(f"章节未开启，可能由于上一章节的章节检测未完成，请手动完成并提交再重试，或者开启题库并启用提交")
                            break
                        RB.add_times(point["id"])
                        continue
                except MaxRollBackError as e:
                    logger.error("回滚次数已达3次，请手动检查学习通任务点完成情况")
                    # 跳过该课程，继续下一课程
                    break


                # 可能存在章节无任何内容的情况
                if not jobs:
                    __point_index += 1
                    continue
                # 遍历所有任务点
                for job in jobs:
                    # 视频任务
                    if job["type"] == "video":
                        # TODO: 目前这个记录功能还不够完善，中途退出的课程ID也会被记录
                        # TextBookID = getText() # 获取学习过的课程ID
                        # if TextBookID.count(bookID) > 0: 
                        #     logger.info(f"课程: {course['title']} 章节: {point['title']} 任务: {job['title']} 已学习过或在学习中，跳过") # 如果已经学习过该课程，则跳过
                        #     break # 如果已经学习过该课程，则跳过
                        # appendText(bookID) # 记录正在学习的课程ID

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
                        logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
                        chaoxing.study_work(course, job,job_info)
                    # 阅读任务
                    elif job["type"] == "read":
                        logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
                        chaoxing.strdy_read(course, job,job_info)
                __point_index += 1
        logger.info("所有课程学习任务已完成")
    except BaseException as e:
        import traceback
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        raise e