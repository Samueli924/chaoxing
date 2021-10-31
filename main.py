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
    try:
        options, _ = getopt.getopt(sys.argv[1:], "c", ["config"])
        for option, value in options:
            if option in ("-c", "--config"):
                config.read(filenames='config.ini', encoding="utf-8")
    except getopt.GetoptError:
        pass



    # 展示md信息文件 默认为显示
    try:
        isallow = config.get("notify","use_tg")
    except configparser.NoOptionError:
        isallow = True
    mdshow.print_md(isallow)


    # 从本地或在线获取用户信息
    try:
        usernm = config.get("user","usernm")
        passwd = config.get("user", "passwd")
    except configparser.NoOptionError:
        usernm = ''
        passwd = ''
    usernm, session = getUser.get_session(usernm,passwd)





    # 从本地或在线获取课程信息以及各类任务点信息
    jobs, course, mp4, ppt = foreWork.get_forework_done(usernm, session)
    # 开始完成MP4任务点
    doWork.do_mp4(usernm, course, session, mp4)
    # 开始完成PPT任务点
    doWork.do_ppt(session, mp4, ppt, usernm, course)
