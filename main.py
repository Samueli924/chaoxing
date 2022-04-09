import random
import time

import utils.functions as ft
from api.chaoxing import Chaoxing


def do_work(chaoxingAPI):
    # done = list(ft.load_finished(chaoxingAPI.usernm))
    logger.info("开始获取所有章节")
    chaoxingAPI.get_selected_course_data()  # 读取所有章节
    for mission in chaoxingAPI.missions:
        # logger.info("开始读取章节信息")
        knowledge_raw = chaoxingAPI.get_mission(mission['id'], chaoxingAPI.selected_course['key'])  # 读取章节信息
        if "data" not in knowledge_raw:
            print("课程信息中不存在data键\n请截图以下内容，在Github或Telegram中向作者提交反馈，谢谢")
            print(knowledge_raw)
            input("点击回车键退出")
            exit()
        tabs = len(knowledge_raw['data'][0]['card']['data'])
        for tab_index in range(tabs):
            # logger.info("开始读取标签信息")
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
                    # print(f"\n当前任务:{attachment['property']['name']}非视频任务")
                    continue
                # if attachment['jobid'] in done:
                #     print(f"\n当前视频:{attachment['property']['name']}存在历史记录")
                #     continue
                print(f"\n当前视频:{attachment['property']['name']}")
                if attachment.get('isPassed'):
                    ft.show_progress(attachment['property']['name'], 1, 1)
                    # done.append(attachment['jobid'])
                    # ft.save_finished(chaoxingAPI.usernm, done)
                    continue
                video_info = chaoxingAPI.get_d_token(
                    attachment['objectId'],
                    attachments['defaults']['fid']
                )
                chaoxingAPI.pass_video(
                    video_info['duration'],
                    attachments['defaults']['cpi'],
                    video_info['dtoken'],
                    attachments['attachments'][0]['otherInfo'],
                    chaoxingAPI.selected_course['key'],
                    attachments['attachments'][0]['jobid'],
                    video_info['objectid'],
                    chaoxingAPI.uid,
                    attachment['property']['name'],
                    chaoxingAPI.speed
                )
                # done.append(attachment['jobid'])
                # ft.save_finished(chaoxingAPI.usernm, done)
        time.sleep(random.randint(1, 3))


if __name__ == '__main__':
    ft.init_all_path(["saves", "logs"])  # 检查文件夹
    logger = ft.Logger("main")  # 初始化日志类
    ft.title_show()     # 显示头
    logger.info("正在获取用户数据...")
    usernm, passwd = ft.load_users()    # 获取账号密码
    chaoxing = Chaoxing(usernm, passwd)     # 实例化超星API
    chaoxing.init_explorer()    # 实例化浏览Explorer
    logger.info("开始登录")
    if chaoxing.login():    # 登录
        logger.info("开始读取所有课程")
        if chaoxing.get_all_courses():  # 读取所有的课程
            logger.info("开始选课")
            if chaoxing.select_course():    # 选择要学习的课程
                chaoxing.speed = int(input("当前倍速： 1 倍速 \n在不紧急的情况下建议使用 1 倍速，因使用不合理的多倍速造成的一切风险与作者无关\n请输入您想要的整数学习倍速:"))
                logger.info("开始学习")
                do_work(chaoxing)   # 开始学习
    input("任务已结束，请点击回车键退出程序")

