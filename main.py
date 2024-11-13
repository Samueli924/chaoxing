#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
超星学习通自动化学习脚本
功能:
- 自动完成视频/音频任务
- 自动完成文档任务
- 自动完成测验任务(需配置题库)
- 自动完成阅读任务
"""

import argparse
import configparser
import os
import traceback
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any, Union

from urllib3 import disable_warnings, exceptions

from api.logger import logger
from api.base import Chaoxing, Account
from api.answer import Tiku
from api.exceptions import LoginError, FormatError, JSONDecodeError, MaxRollBackError

# 关闭 SSL 警告
disable_warnings(exceptions.InsecureRequestWarning)

@dataclass
class Config:
    """配置数据类"""
    username: str
    password: str 
    course_list: Optional[List[str]]
    speed: float
    tiku_config: Optional[Dict[str, Any]]

class CourseManager:
    """课程管理类"""
    
    def __init__(self, chaoxing: Chaoxing):
        self.chaoxing = chaoxing
        self.all_courses: List[Dict] = []
        self.selected_courses: List[Dict] = []

    def load_courses(self) -> None:
        """加载所有课程"""
        self.all_courses = self.chaoxing.get_course_list()
        
    def select_courses(self, course_list: Optional[List[str]] = None) -> None:
        """
        选择要学习的课程
        
        Args:
            course_list: 课程ID列表,为None时通过交互方式选择
        """
        if not course_list:
            self._interactive_select()
        else:
            self._filter_courses(course_list)
            
        if not self.selected_courses:
            self.selected_courses = self.all_courses
            
        logger.info(f"课程列表过滤完毕，当前课程任务数量: {len(self.selected_courses)}")

    def _interactive_select(self) -> None:
        """交互式选择课程"""
        print("*" * 10 + "课程列表" + "*" * 10)
        for course in self.all_courses:
            print(f"ID: {course['courseId']} 课程名: {course['title']}")
        print("*" * 28)
        
        try:
            course_input = input("请输入想要学习的课程列表,以逗号分隔,例: 2151141,189191,198198\n").strip()
            if course_input:
                course_list = [c.strip() for c in course_input.split(",")]
                self._filter_courses(course_list)
        except Exception as e:
            raise FormatError("输入格式错误") from e

    def _filter_courses(self, course_list: List[str]) -> None:
        """根据课程ID列表筛选课程"""
        self.selected_courses = [
            course for course in self.all_courses 
            if course["courseId"] in course_list
        ]

class RollBackManager:
    """任务回滚管理类"""
    
    MAX_ROLLBACK = 3
    
    def __init__(self) -> None:
        self.rollback_times: int = 0
        self.rollback_id: str = ""

    def add_times(self, id: str) -> None:
        """
        增加回滚次数
        
        Args:
            id: 任务点ID
            
        Raises:
            MaxRollBackError: 超过最大回滚次数
        """
        if id == self.rollback_id:
            if self.rollback_times >= self.MAX_ROLLBACK:
                raise MaxRollBackError("回滚次数已达3次，请手动检查学习通任务点完成情况")
            self.rollback_times += 1
        else:
            self.rollback_id = id
            self.rollback_times = 1

def init_config() -> Config:
    """
    初始化配置
    
    Returns:
        Config: 配置对象
    """
    parser = argparse.ArgumentParser(description='超星学习通自动化学习工具')
    parser.add_argument("-c", "--config", type=str, help="使用配置文件运行程序")
    parser.add_argument("-u", "--username", type=str, help="手机号账号")
    parser.add_argument("-p", "--password", type=str, help="登录密码") 
    parser.add_argument("-l", "--list", type=str, help="要学习的课程ID列表")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="视频播放倍速(默认1)")
    
    args = parser.parse_args()
    
    if args.config:
        return _load_config_file(args.config)
    
    return Config(
        username=args.username,
        password=args.password,
        course_list=args.list.split(",") if args.list else None,
        speed=max(1.0, args.speed),
        tiku_config=None
    )

def _load_config_file(config_path: str) -> Config:
    """
    从配置文件加载配置
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        Config: 配置对象
    """
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf8")
    
    return Config(
        username=config.get("common", "username"),
        password=config.get("common", "password"),
        course_list=config.get("common", "course_list", fallback="").split(",") if config.get("common", "course_list") else None,
        speed=float(config.get("common", "speed")),
        tiku_config=dict(config["tiku"]) if "tiku" in config and config.get("tiku", "tokens", fallback="").strip() else None
    )

def process_course_tasks(chaoxing: Chaoxing, course: Dict, speed: float, tiku: Tiku) -> None:
    """
    处理单个课程的所有任务
    
    Args:
        chaoxing: Chaoxing实例
        course: 课程信息
        speed: 视频播放速度
        tiku: 题库实例
    """
    logger.info(f"开始学习课程: {course['title']}")
    
    # 获取课程章节
    point_list = chaoxing.get_course_point(
        course["courseId"], 
        course["clazzId"], 
        course["cpi"]
    )
    
    rb_manager = RollBackManager()
    point_index = 0
    
    # 遍历章节
    while point_index < len(point_list["points"]):
        point = point_list["points"][point_index]
        logger.info(f'当前章节: {point["title"]}')
        
        try:
            process_chapter(chaoxing, course, point, point_index, speed, tiku, rb_manager)
            point_index += 1
        except MaxRollBackError as e:
            logger.error(str(e))
            break

def process_chapter(
    chaoxing: Chaoxing,
    course: Dict,
    point: Dict,
    point_index: int,
    speed: float,
    tiku: Tiku,
    rb_manager: RollBackManager
) -> None:
    """
    处理单个章节的任务
    
    Args:
        chaoxing: Chaoxing实例
        course: 课程信息
        point: 章节信息
        point_index: 章节索引
        speed: 视频播放速度
        tiku: 题库实例
        rb_manager: 回滚管理器
    """
    jobs, job_info = chaoxing.get_job_list(
        course["clazzId"],
        course["courseId"], 
        course["cpi"],
        point["id"]
    )

    # 处理未开放章节
    if job_info.get('notOpen', False):
        handle_locked_chapter(point, tiku, rb_manager)
        return

    # 处理章节任务
    if jobs:
        for job in jobs:
            process_job(chaoxing, course, point, job, job_info, speed)

def handle_locked_chapter(point: Dict, tiku: Optional[Tiku], rb_manager: RollBackManager) -> None:
    """
    处理未开放的章节
    
    Args:
        point: 章节信息
        tiku: 题库实例
        rb_manager: 回滚管理器
        
    Raises:
        MaxRollBackError: 章节未开放且无法处理
    """
    if not tiku or tiku.DISABLE or not tiku.SUBMIT:
        logger.error("章节未开启，可能由于上一章节的章节检测未完成，请手动完成并提交再重试，或者开启题库并启用提交")
        raise MaxRollBackError("章节未开放")
    rb_manager.add_times(point["id"])

def process_job(
    chaoxing: Chaoxing,
    course: Dict,
    point: Dict,
    job: Dict,
    job_info: Dict,
    speed: float
) -> None:
    """
    处理单个任务点
    
    Args:
        chaoxing: Chaoxing实例
        course: 课程信息
        point: 章节信息
        job: 任务信息
        job_info: 任务详细信息
        speed: 视频播放速度
    """
    job_type_handlers = {
        "video": handle_video_job,
        "document": handle_document_job,
        "workid": handle_work_job,
        "read": handle_read_job
    }
    
    handler = job_type_handlers.get(job["type"])
    if handler:
        handler(chaoxing, course, point, job, job_info, speed)

def handle_video_job(
    chaoxing: Chaoxing,
    course: Dict,
    point: Dict,
    job: Dict,
    job_info: Dict,
    speed: float
) -> None:
    """处理视频任务"""
    logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
    try:
        chaoxing.study_video(course, job, job_info, speed=speed, type_="Video")
    except JSONDecodeError:
        logger.warning("当前任务非视频任务，正在尝试音频任务解码")
        try:
            chaoxing.study_video(course, job, job_info, speed=speed, type_="Audio")
        except JSONDecodeError:
            logger.warning(f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}, 已跳过")

def handle_document_job(
    chaoxing: Chaoxing,
    course: Dict,
    point: Dict,
    job: Dict,
    job_info: Dict,
    speed: float
) -> None:
    """处理文档任务"""
    logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
    chaoxing.study_document(course, job)

def handle_work_job(
    chaoxing: Chaoxing,
    course: Dict,
    point: Dict,
    job: Dict,
    job_info: Dict,
    speed: float
) -> None:
    """处理测验任务"""
    logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
    chaoxing.study_work(course, job, job_info)

def handle_read_job(
    chaoxing: Chaoxing,
    course: Dict,
    point: Dict,
    job: Dict,
    job_info: Dict,
    speed: float
) -> None:
    """处理阅读任务"""
    logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
    chaoxing.study_read(course, job, job_info)

def main() -> None:
    """主函数"""
    try:
        # 初始化配置
        config = init_config()
        
        # 获取登录信息
        if not config.username or not config.password:
            config.username = input("请输入你的手机号，按回车确认\n手机号:").strip()
            config.password = input("请输入你的密码，按回车确认\n密码:").strip()
            
        # 初始化账号
        account = Account(config.username, config.password)
        
        # 初始化题库
        tiku = None
        if config.tiku_config:
            tiku = Tiku()
            tiku.config_set(config.tiku_config)
            tiku = tiku.get_tiku_from_config()
            tiku.init_tiku()
            
        # 初始化超星API
        chaoxing = Chaoxing(account=account, tiku=tiku)
        
        # 登录检查
        login_state = chaoxing.login()
        if not login_state["status"]:
            raise LoginError(login_state["msg"])
            
        # 课程管理
        course_manager = CourseManager(chaoxing)
        course_manager.load_courses()
        course_manager.select_courses(config.course_list)
        
        # 处理所有课程
        for course in course_manager.selected_courses:
            process_course_tasks(chaoxing, course, config.speed, tiku)
            
        logger.info("所有课程学习任务已完成")
        
    except Exception as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        raise

if __name__ == '__main__':
    main()