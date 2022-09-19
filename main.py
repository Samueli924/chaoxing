import random
import time
import argparse

import utils.functions as ft
from api.chaoxing import Chaoxing


def do_work(chaoxingAPI):
    #print(chaoxingAPI.selected_course)
    re_login_try = 0
    # done = list(ft.load_finished(chaoxingAPI.usernm))
    logger.info("已选课程："+str(chaoxingAPI.selected_course['content']['course']['data'][0]['name']))
    logger.info("开始获取所有章节")
    chaoxingAPI.get_selected_course_data()  # 读取所有章节
    mission_num = len(chaoxingAPI.missions)
    mission_index = 0
    while mission_index < mission_num:
        mission = chaoxingAPI.missions[mission_index]
        mission_index += 1
        logger.debug("开始读取章节信息")
        knowledge_raw = chaoxingAPI.get_mission(mission['id'], chaoxingAPI.selected_course['key'])  # 读取章节信息
        if "data" not in knowledge_raw and "error" in knowledge_raw:
            logger.debug("---knowledge_raw info begin---")
            logger.debug(knowledge_raw)
            logger.debug("---knowledge_raw info end---")
            if re_login_try < 2:
                logger.warn("章节数据错误,可能是课程存在验证码,正在尝试重新登录")
                chaoxingAPI.re_init_login()
                mission_index -= 1
                re_login_try += 1
                continue
            else:
                logger.error("章节数据错误,可能是课程存在验证码,重新登录尝试无效")
                input("请截图并携带日志提交Issue反馈")
        re_login_try = 0
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
            print(f'\n当前章节：{mission["label"]}:{mission["name"]}')
            for attachment in attachments['attachments']:
                if attachment.get('type') != 'video': # 非视频任务跳过
                    #print(attachment)
                    if attachment.get('type') != 'document':
                        print("跳过非视频任务 and document")
                        continue
                    if not chaoxingAPI.filebeta:
                        continue
                    # document (.pptx...)支持
                    jobid = None
                    if "jobid" in attachments:
                        jobid = attachments["jobid"]
                    else: 
                        if "jobid" in attachment:
                            jobid = attachment["jobid"]
                        else:
                            if "jobid" in attachment['property']:
                                jobid = attachment['property']['jobid']
                            else:
                                if "'_jobid'" in attachment['property']:
                                    jobid = attachment['property']['_jobid']
                    if not jobid:
                        print("未找到jobid，已跳过当前任务点")
                        continue
                    video_info = chaoxingAPI.get_d_token(
                        attachment['property']['objectid'],
                        attachments['defaults']['fid']
                    )
                    #print(video_info)
                    print(f"\n当前文件：{attachment['property']['name']}")
                    #print(mission)
                    #print(attachment)
                    #if mission['id'] == 390379027:
                    chaoxingAPI.document(
                        chaoxingAPI.uid,
                        chaoxingAPI.selected_course['key'],
                        attachment['jtoken'],
                        chaoxingAPI.selected_course['content']['course']['data'][0]['id'],
                        mission["id"],
                        jobid
                    )
                    continue
                print(f"\n当前视频：{attachment['property']['name']}")
                if attachment.get('isPassed'):
                    print("当前视频任务已完成")
                    ft.show_progress(attachment['property']['name'], 1, 1)
                    time.sleep(1)
                    continue
                try:
                    video_info = chaoxingAPI.get_d_token(
                        attachment['objectid'],
                        attachments['defaults']['fid']
                    )
                except:
                    print(attachment)
                    logger.warn("出现了一个问题")
                    video_info = chaoxingAPI.get_d_token(
                        attachment['property']['objectid'],
                        attachments['defaults']['fid']
                    )
                if not video_info:
                    continue
                jobid = None
                if "jobid" in attachments:
                    jobid = attachments["jobid"]
                else: 
                    if "jobid" in attachment:
                        jobid = attachment["jobid"]
                    else:
                        if "jobid" in attachment['property']:
                            jobid = attachment['property']['jobid']
                        else:
                            if "'_jobid'" in attachment['property']:
                                jobid = attachment['property']['_jobid']
                if not jobid:
                    print("未找到jobid，已跳过当前任务点")
                    continue
                # if adopt:
                #     logger.debug("已启用自适应速率")
                #     if "doublespeed" in attachment['property']:
                #         if attachment['property']['doublespeed']:
                #             print("当前视频支持倍速播放,已切换速率")
                #             chaoxing.speed = 2
                #     else:
                #         print("当前视频不支持倍速播放,跳过")
                #         chaoxing.speed = set_speed
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
                    chaoxingAPI.speed,
                    chaoxingAPI.get_current_ms
                )
                ft.pause(10, 13)
                # chaoxing.speed = set_speed  # 预防ERR


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='chaoxing-xuexitong')  # 命令行传参
    parser.add_argument('-debug','--debug', action='store_true', help='Enable debug output in console')
    # parser.add_argument('-default','--default-speed', action='store_true', help='Choose Default Speed,Enable adaptive speed(Disable by --no-adopt)')
    # parser.add_argument('--use-adopt', action='store_true', help='Use adaptive speed')
    # parser.add_argument('--no-adopt',  action='store_true', help='Disable adaptive speed')
    parser.add_argument('--no-log', action='store_false', help='Disable Console log')
    parser.add_argument('--no-logo', action='store_false', help='Disable Boot logo')
    parser.add_argument('--no-sec', action='store_false', help='Disable all security feature')

    args = parser.parse_args()  # 定义专用参数变量
    debug = args.debug  # debug输出  Default:False
    # disable_adopt = args.no_adopt # 禁用自适应速率 Default:False
    show = args.no_log # 显示控制台log Default:True
    logo = args.no_logo # 展示启动LOGO Default:True
    hideinfo = args.no_sec  # 启用隐私保护 Default:True
    # use_adopt = args.use_adopt # 使用自适应速率 Default:False
    # se_default = args.default_speed # 启用默认速度 Default:False
    try:
        #if 1:
        ft.init_all_path(["saves", "logs"])  # 检查文件夹
        logger = ft.Logger("main",debug,show)  # 初始化日志类
        if debug:
            logger.debug("已启用debug输出")
        if not show:
            logger.debug("已关闭控制台日志")
        ft.title_show(logo)     # 显示头
        if not logo:
            logger.debug("已关闭启动LOGO")
#         if use_default:
#             logger.debug("已选择默认速率")
#         if disable_adopt:
#             logger.debug("已关闭自适应速率")
#         else:
#             if use_adopt:
#                 logger.debug("已使用自适应速率")
        logger.info("正在读取本地用户数据...")
        usernm, secname, passwd = ft.load_users(hideinfo)    # 获取账号密码
        chaoxing = Chaoxing(usernm, passwd, debug, show)     # 实例化超星API
        chaoxing.init_explorer()    # 实例化浏览Explorer
        logger.info("登陆中")
        if chaoxing.login():    # 登录
            logger.info("已登录账户：" +secname)
            logger.info("正在读取所有课程")
            if chaoxing.get_all_courses():  # 读取所有的课程
                logger.info("进行选课")
                if chaoxing.select_course():    # 选择要学习的课程
#                     if not use_default: 
#                         set_speed = input("默认倍速： 1 倍速 \n在不紧急的情况下建议使用 1 倍速，因使用不合理的多倍速造成的一切风险与作者无关\n请输入您想要的学习倍速(倍数需为整数,0或直接回车将使用默认1倍速)：")
#                     else:
#                         set_speed = 0
#                     if not set_speed or set_speed == 0:
#                         chaoxing.speed = 1
#                         set_speed = 1
#                         logger.info("已使用默认速率")
#                     else:
#                         chaoxing.speed = int(set_speed)
#                         set_speed = int(set_speed)
                    if chaoxing.filebeta:
                        logger.warn("您已打开 Beta 版本功能（具体查看README.md）")
                    speed_input = input("默认倍速： 1 倍速 \n——因使用不合理的多倍速造成的一切风险与开发者无关——\n请输入学习倍速(倍数为整数,默认1倍速)：")
                    if speed_input:
                        chaoxing.speed = int(speed_input)
                    else:
                        chaoxing.speed = 1
                    logger.debug("当前设置速率："+str(chaoxing.speed)+"倍速")
#                     if not disable_adopt and set_speed == 1: # Only God and I knew how it worked.
#                         if not use_default and not use_adopt: 
#                             set_adopt = input("是否启用自适应速率(当播放速率为1且视频支持倍速播放时,自动切换为两倍速)\n！注意 该功能可能存在风险！输入(Y/y/Yes/yes)启用").lower()
#                         if use_default or use_adopt or set_adopt.startswith('y'):
#                             adopt = True
#                         else:
#                             adopt = False
#                     else:
#                         adopt = False
#                     if adopt:
#                         logger.info("已启用自适应速率")
#                     else:
#                         logger.info("已禁用自适应速率")
                    logger.info("开始学习")
                    do_work(chaoxing)   # 开始学习
        input("任务已结束，请点击回车键退出程序")
    except Exception as e:
        print(f"出现报错{e.__class__}")
        print(f"错误文件名：{e.__traceback__.tb_frame.f_globals['__file__']}")
        print(f"错误行数：{e.__traceback__.tb_lineno}")
        print(f"错误原因:{e}")
        input("请截图提交至Github或QQ供作者修改代码\n点击回车键退出程序")
