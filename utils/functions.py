import json
import logging
import os
import time
import maskpass
from hashlib import md5
from os import mkdir
from os.path import exists
import random
from natsort import natsorted


def title_show(logo):
    if logo:
        print("-"*120 + "\n")
        print("""                                                                                 ,---.-,                         ,--, 
  .--.--.                         ____                           ,--,           '   ,'  '.       ,----,        ,--.'| 
 /  /    '.                     ,'  , `.                       ,--.'|     ,--, /   /      \    .'   .' \    ,--,  | : 
|  :  /`. /                  ,-+-,.' _ |        ,--,           |  | :   ,--.'|.   ;  ,/.  :  ,----,'    |,---.'|  : ' 
;  |  |--`                ,-+-. ;   , ||      ,'_ /|           :  : '   |  |, '   |  | :  ;  |    :  .  ;;   : |  | ; 
|  :  ;_      ,--.--.    ,--.'|'   |  || .--. |  | :    ,---.  |  ' |   `--'_ '   |  ./   :  ;    |.'  / |   | : _' | 
 \  \    `.  /       \  |   |  ,', |  |,'_ /| :  . |   /     \ '  | |   ,' ,'||   :       ,  `----'/  ;  :   : |.'  | 
  `----.   \.--.  .-. | |   | /  | |--'|  ' | |  . .  /    /  ||  | :   '  | | \   \      |    /  ;  /   |   ' '  ; : 
  __ \  \  | \__\/: . . |   : |  | ,   |  | ' |  | | .    ' / |'  : |__ |  | :  `---`---  ;   ;  /  /-,  \   \  .'. | 
 /  /`--'  / ," .--.; | |   : |  |/    :  | : ;  ; | '   ;   /||  | '.'|'  : |__   |   |  |  /  /  /.`|   `---`:  | ' 
'--'.     / /  /  ,.  | |   | |`-'     '  :  `--'   \'   |  / |;  :    ;|  | '.'|  '   :  ;./__;      :        '  ; | 
  `--'---' ;  :   .'   \|   ;/         :  ,      .-./|   :    ||  ,   / ;  :    ;  |   |  '|   :    .'         |  : ; 
           |  ,     .-./'---'           `--`----'     \   \  /  ---`-'  |  ,   /   ;   |.' ;   | .'            '  ,/  
            `--`---'                                   `----'            ---`-'    '---'   `---'               '--'   """)
        print("\n" + "-"*120)
    else:
        print("\n")
    print("欢迎使用Samueli924/chaoxing\n对代码有任何疑问或建议，请前往https://github.com/Samueli924/chaoxing进行反馈")
    print("如果喜欢这个项目，请给我的repo一个小小的Star，谢谢\n")


def check_path(path: str, file: bool = True):
    """
    检查路径是否存在
    :param path: 路径(str)
    :param file: 是否为文件(bool)
    :return: True
    """
    path_list = path.split("/")
    for i in range(len(path_list) - 1):     # 循环判断路径是否存在
        __temp = "/".join(path_list[:i + 1])
        if not exists(__temp):  # 不存在即新建路径
            mkdir(__temp)
    if file:
        with open(path, "w") as f:  # 新建文件
            f.write("")
    else:
        if not exists(path):
            mkdir(path)
    return True


def init_all_path(init_path):
    for path in init_path:
        check_path(path, file=False)
    return True


class Logger:
    def __init__(self, name, debug, show, save=True ):
        """
        日志记录系统
        :param name: 日志保存时使用的Name
        :param debug: 控制台输出等级传参    #有人懒得在外面传loghandler
        :param show: 是否在控制台显示日志
        :param save: 是否将日志保存至本地
        """
        log_path = f"logs/{name}.log"
        self.logger = logging.getLogger(name)
        # self.logger.handlers.clear()
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            if show:
                sh = logging.StreamHandler()
                if debug:
                    sh.setLevel(logging.DEBUG)
                else:
                    sh.setLevel(logging.INFO)
                sh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
                self.logger.addHandler(sh)
            if save:
                fh = logging.FileHandler(log_path)
                fh.setLevel(logging.DEBUG)
                fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
                self.logger.addHandler(fh)

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warn(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def critical(self, message):
        self.logger.critical(message)


def save_users(usernm, passwd):
    user_folder = f"saves/{usernm}"
    check_path(user_folder, file=False)
    with open(f"{user_folder}/user.json", "w") as f:
        json.dump({"usernm": usernm, "passwd": passwd}, f)
    return True


def load_users(hide):
    if os.listdir("saves"):
        users = os.listdir("saves")
        print("-" * 40)
        for index, user in enumerate(users):
            if hide:
                sec_user = "%s****%s"%(user[:3],user[7:])
            else:
                sec_user = user
            print(f"{index + 1}. {sec_user}")
        print("-" * 40)
        num = input("请输入要登录的用户序号，新建用户请直接点击回车键")
        if not num:
            usernm = input("请输入手机号")
            if hide:
                sec_user = "%s****%s"%(usernm[:3],usernm[7:])
                passwd = maskpass.askpass(prompt="请输入密码(已自动隐藏)", mask="#")
            else:
                sec_user = usernm
                passwd = input("请输入密码")
        else:
            with open(f"saves/{users[int(num) - 1]}/user.json", "r") as f:
                __temp = json.loads(f.read())
                usernm = __temp["usernm"]
                sec_user = "%s****%s" % (usernm[:3], usernm[7:])
                passwd = __temp["passwd"]
    else:
        usernm = input("请输入手机号")
        if hide:
            sec_user = "%s****%s"%(usernm[:3],usernm[7:])
            passwd = passwd = maskpass.askpass(prompt="请输入密码(已自动隐藏)", mask="#")
        else:
            sec_user = usernm
            passwd = input("请输入密码")
    return usernm, sec_user, passwd


def load_finished(usernm):
    path = f"saves/{usernm}/done.json"
    if exists(path):
        with open(path, "r") as f:
            done = json.loads(f.read())
    else:
        with open(path, "w") as f:
            json.dump([], f)
        done = list()
    return done


def save_finished(usernm, done):
    path = f"saves/{usernm}/done.json"
    with open(path, "w") as f:
        json.dump(done, f)


def pretty_print(courses_raw: list):
    titles = ["序号", "课程ID", "课程名称"]
    data = list()
    for course_index, course in enumerate(courses_raw):
        if "course" in course["content"]:
            data.append([str(course_index + 1), str(course["key"]), str(course['content']['course']['data'][0]['name'])])
    format_row = "{:>16}" * (len(titles) + 1)
    print("-"*100)
    print(format_row.format("", *titles))
    for row in data:
        print(format_row.format("", *row))
    print("-" * 100)


def sort_missions(missions):
    data = {}
    for mission in missions:
        data[mission['label']] = mission
    keys_sorted = natsorted(data.keys())
    return [data[k] for k in keys_sorted]


def get_enc_time():
    m_time = str(int(time.time() * 1000))
    m_token = '4faa8662c59590c6f43ae9fe5b002b42'
    m_encrypt_str = 'token=' + m_token + '&_time=' + m_time + '&DESKey=Z(AfY@XS'
    m_inf_enc = md5(m_encrypt_str.encode('utf-8')).hexdigest()
    return m_time, m_inf_enc


def sec2time(sec):
    ret = ""
    if sec // 3600 > 0:
        ret += f"{sec // 3600}h "
        sec = sec - sec // 3600 * 3600
    if sec // 60 > 0:
        ret += f"{sec // 60}min "
        sec = sec - sec // 60 * 60
    if sec:
        ret += f"{sec}s"
    if not ret:
        ret = "0s"
    return ret


def show_progress(name, current, total):
    percent = int(current / total * 100)
    length = int(percent * 40 // 100)
    progress = ("#" * length).ljust(40, " ")
    remain = (total - current)
    if current >= total and remain < 1:
        print("\r" + f"当前任务： {name} 已完成".ljust(100, " "))
    else:
        # print("\r" + f"当前任务： {name} 剩余时间：{sec2time(remain / speed)} |{progress}| {percent}%  {sec2time(current)}/{sec2time(total)}", end="", flush=True)
        print("\r" + f"当前任务： {name} |{progress}| {percent}%  {sec2time(current)}/{sec2time(total)}     ", end="", flush=True)


def pause(start: int, end: int):
    __temp = random.randint(start, end)
    print(f"等待{__temp}秒")
    time.sleep(__temp)
    return True
