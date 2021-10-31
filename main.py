# -*- coding:utf-8 -*-
import src.user.getUser as getUser
import src.course.foreWork as foreWork
import src.course.doWork as doWork
import src.show.mdshow as mdshow

import configparser
import getopt
import sys

config = configparser.ConfigParser()

if __name__ == '__main__':
    isconfig = False
    try:
        options, _ = getopt.getopt(sys.argv[1:], "c", ["config"])
        for option, value in options:
            if option in ("-c", "--config"):
                config.read(filenames='config.ini', encoding="utf-8")
                isconfig = True
    except getopt.GetoptError:
        pass


    # 展示md信息文件 默认为显示
    if isconfig:
        try:
            isallow = config.getboolean("play","showmd")
        except configparser.NoOptionError:
            isallow = True
    else:
        isallow = True
    mdshow.print_md(isallow)


    # 从本地或在线获取用户信息 默认为空
    if isconfig:
        try:
            usernm = config.get("user","usernm")
            passwd = config.get("user", "passwd")
        except configparser.NoOptionError:
            usernm = ''
            passwd = ''
    else:
        usernm = ''
        passwd = ''
    usernm, session = getUser.get_session(usernm,passwd)


    # 从本地或在线获取课程信息以及各类任务点信息
    if isconfig:
        try:
            courseid = str(config.get("user", "courseid"))
        except configparser.NoOptionError:
            courseid = ''
    else:
        courseid = ''

    jobs, course, mp4, ppt = foreWork.get_forework_done(usernm, session,courseid)


    # 开始完成MP4任务点 速度默认为一倍速
    if isconfig:
        try:
            speed = config.get("play", "speed")
            # daily = config.get("play", 'daily')
        except configparser.NoOptionError:
            speed = 1
            # daily = 0
    else:
        speed = 1
        # daily = 0
    doWork.do_mp4(usernm, course, session, mp4, speed)


    # 开始完成PPT任务点
    doWork.do_ppt(session, mp4, ppt, usernm, course)
