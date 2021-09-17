import json
import os
def determine_user_file():
    i = 0
    try:
        f = open('saves/user_info.json', 'r')
        content = json.load(f)
        usernm = content[0]
        passwd = content[1]
        i = 1
    except:
        i = 0
    if i == 1:
        num = int(input('检测到已存在用户{}，是否使用当前用户\n1.是\n2.否'.format(usernm)))
        if num == 1:
            return usernm,passwd
        elif num == 2:
            usernm = input('请输入您的账号')
            passwd = input('请输入您的密码')
            content = [usernm, passwd]
            with open('saves//user_info.json', 'w') as file:
                json.dump(content, file)
            if os.path.exists(usernm):
                print('用户文件夹已存在')
            else:
                os.mkdir(usernm)
                print('创建用户文件夹成功')
            return usernm, passwd
    else:
        usernm = input('请输入您的账号')
        passwd = input('请输入您的密码')
        content = [usernm, passwd]
        with open('saves//user_info.json', 'w') as file:
            json.dump(content, file)
        if os.path.exists(usernm):
            print('用户文件夹已存在')
        else:
            os.mkdir(usernm)
            print('创建用户文件夹成功')
        return usernm, passwd