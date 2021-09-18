import src.user.getUser as getUser
import src.course.foreWork as foreWork
import src.course.doWork as doWork
import src.show.mdshow as mdshow

if __name__ == '__main__':
    # 展示md信息文件
    mdshow.print_md()
    # 从本地或在线获取用户信息
    usernm, session = getUser.get_session()
    # 从本地或在线获取课程信息以及各类任务点信息
    jobs, course, mp4, ppt = foreWork.get_forework_done(usernm, session)
    # 开始完成MP4任务点
    doWork.do_mp4(usernm, course, session, mp4)
    # 开始完成PPT任务点
    doWork.do_ppt(session, mp4, ppt, usernm, course)
