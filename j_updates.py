import requests
import json
import time
def get_detail():
    url = 'https://api.github.com/repos/xz454867105/fxxk_chaoxing/releases/latest'
    resq = requests.get(url)
    return resq.json()['tag_name']


def check(current_v):
    print('正在检查更新，依据网络情况所用时间从1秒到10秒不等，请耐心等待')
    latest_v = str(get_detail())
    if latest_v == current_v:
        print('软件版本为最新，不需更新\n开始学习程序')
    else:
        print('您的当前版本为{}，服务器最新版本为{}\n请打开下载最新版本\nhttps://github.com/xz454867105/fxxk_chaoxing/releases\n不建议使用老版代码'.format(current_v,latest_v))
        a = input('是否继续使用当前版本\n1.是\n0.否\n请输入数字')
        if a == '1':
            print('3秒后开始学习程序')
            time.sleep(3)
        elif a == '0':
            print('3秒后自动退出程序')
            time.sleep(3)
            exit()
        else:
            print('您的输入有误，正在重试')
            check(current_v)