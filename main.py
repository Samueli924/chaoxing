# -*- coding:utf-8 -*-
import src.user.getUser as getUser
import src.course.foreWork as foreWork
import src.course.doWork as doWork
# import src.show.mdshow as mdshow
import src.config.config as config


if __name__ == '__main__':

    isallow,usernm,passwd,courseid,speed = config.get_params()

    # 展示md信息文件 默认为不显示
    # mdshow.print_md(isallow)

    # 从本地或在线获取用户信息 默认为空
    usernm, session = getUser.get_session(usernm,passwd)

    # 从本地或在线获取课程信息以及各类任务点信息
    session, jobs, course, mp4, ppt = foreWork.get_forework_done(usernm, session,courseid)

    # 开始完成MP4任务点 速度默认为一倍速
    doWork.do_mp4(usernm, course, session, mp4, int(speed))

    # 开始完成PPT任务点
    # doWork.do_ppt(session, mp4, ppt, usernm, course)
    
    # 提示任务全部结束
    input("所有可识别的任务已经完成，请点击回车键退出程序")
