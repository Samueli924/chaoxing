import random
import time
import argparse

import utils.functions as ft
from api.chaoxing import Chaoxing


def do_work(chaoxingAPI):
    # done = list(ft.load_finished(chaoxingAPI.usernm))
    logger.info("开始获取所有章节")
    chaoxingAPI.get_selected_course_data()  # 读取所有章节
    for mission in chaoxingAPI.missions:
        logger.debug("开始读取章节信息")
        knowledge_raw = chaoxingAPI.get_mission(mission['id'], chaoxingAPI.selected_course['key'])  # 读取章节信息
        if "data" not in knowledge_raw and "error" in knowledge_raw:
            input("当前课程需要认证，请在学习通客户端中验证码认证后再运行本课程\n点击回车键退出程序")
            exit()
        tabs = len(knowledge_raw['data'][0]['card']['data'])
        for tab_index in range(tabs):
            print("开始读取标签信息")
            knowledge_card_text = chaoxingAPI.get_knowledge(
                chaoxingAPI.selected_course['key'],
                chaoxingAPI.selected_course['content']['course']['data'][0]['id'],
                mission["id"],
                tab_index
            )
            attachments: dict = chaoxingAPI.get_attachments(knowledge_card_text)
            if not attachments:
                continue
            if not attachments.get('attachments'):
                continue
            print(f'\n当前章节:{mission["label"]}:{mission["name"]}')
            for attachment in attachments['attachments']:   # 非视频任务跳过
                if attachment.get('type') != 'video':
                    print("跳过非视频任务")
                    continue
                print(f"\n当前视频:{attachment['property']['name']}")
                if attachment.get('isPassed'):
                    print("当前视频任务已完成")
                    ft.show_progress(attachment['property']['name'], 1, 1)
                    continue
                video_info = chaoxingAPI.get_d_token(
                    attachment['objectId'],
                    attachments['defaults']['fid']
                )
                if "duration" not in video_info or "jobid" not in attachment:
                    continue

                chaoxingAPI.pass_video(
                    video_info['duration'],
                    attachments['defaults']['cpi'],
                    video_info['dtoken'],
                    attachment['otherInfo'],
                    chaoxingAPI.selected_course['key'],
                    attachment['jobid'],
                    video_info['objectid'],
                    chaoxingAPI.uid,
                    attachment['property']['name'],
                    chaoxingAPI.speed
                )
                ft.pause(1, 3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='chaoxing-xuexitong')  # 命令行传参
    parser.add_argument('-debug','--debug', action='store_true', help='Enable debug output in console')
    parser.add_argument('--no-logo', action='store_false', help='Disable Boot logo')
    parser.add_argument('--no-sec', action='store_false', help='Disable all security feature')

    args = parser.parse_args()  # 定义专用参数变量
    debug = args.debug  # debug输出  Default:False
    logo = args.no_logo # 展示启动LOGO Default:True
    hideinfo = args.no_sec  # 启用隐私保护 Default:True

    try:
        ft.init_all_path(["saves", "logs"])  # 检查文件夹
        logger = ft.Logger("main",debug)  # 初始化日志类
        if debug:
            logger.debug("已启用debug输出")
        ft.title_show(logo)     # 显示头
        if not logo:
            logger.debug("已关闭启动LOGO")
        logger.info("正在读取本地用户数据...")
        usernm, secname, passwd = ft.load_users(hideinfo)    # 获取账号密码
        chaoxing = Chaoxing(usernm, passwd, debug)     # 实例化超星API
        chaoxing.init_explorer()    # 实例化浏览Explorer
        logger.info("登陆中")
        if chaoxing.login():    # 登录
            logger.info("已登录账户：" +secname)
            logger.info("正在读取所有课程")
            if chaoxing.get_all_courses():  # 读取所有的课程
                logger.info("进行选课")
                if chaoxing.select_course():    # 选择要学习的课程
                    chaoxing.speed = int(input("默认倍速： 1 倍速 \n在不紧急的情况下建议使用 1 倍速，因使用不合理的多倍速造成的一切风险与作者无关\n请输入您想要的整数学习倍速:"))
                    logger.info("开始学习")
                    do_work(chaoxing)   # 开始学习
        input("任务已结束，请点击回车键退出程序")
    except Exception as e:
        print(f"出现报错{e.__class__}")
        print(f"错误文件名：{e.__traceback__.tb_frame.f_globals['__file__']}")
        print(f"错误行数：{e.__traceback__.tb_lineno}")
        print(f"错误原因:{e}")
        input("请截图提交至Github或Telegram供作者修改代码\n点击回车键退出程序")
