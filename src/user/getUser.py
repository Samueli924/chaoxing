# -*- coding:utf-8 -*-
import base64
import hashlib
import json
import requests
import time
from os import listdir
from base64 import b64encode
import requests.utils
from rich.console import Console
from rich.table import Table

import src.path.pathCheck as pathCheck

console = Console()


def get_encoded_token():
    """
    通过逆向得到的超星学习通登录加密算法，根据当前时间戳计算得出加密结果并返回
    :return: 当前时间戳(str),加密结果(str)
    """
    tsp = int(time.time() * 1000)
    m_token = '4faa8662c59590c6f43ae9fe5b002b42'
    m_encrypt_str = 'token=' + m_token + '&_time=' + str(tsp) + '&DESKey=Z(AfY@XS'
    md5 = hashlib.md5()
    md5.update(m_encrypt_str.encode('utf-8'))
    enc = md5.hexdigest()
    return str(tsp), enc


def get_data(usernm, passwd):
    """
    获取发送登录POST请求时需要用到的data内容
    :param usernm: 用户名
    :param passwd: 密码
    :return: 发送登录POST请求的data参数
    """
    data = ''
    data += '--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="uname"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
    data += usernm + '\r\n'
    data += '--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="code"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
    data += passwd + '\r\n'
    data += '--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="loginType"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
    data += '1\r\n'
    data += '--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="roleSelect"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
    data += 'true\r\n--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6--\r\n'
    return data


def login(usernm, passwd):
    """
    尝试登录，获取登录用户的学校fid号码以及学生的uid号码，保存至本地
    :param usernm: 用户名
    :param passwd: 密码
    :return: requests.session()对象
    """
    user = {}
    header = {'Accept-Language': 'zh_CN',
              'Content-Type': 'multipart/form-data; boundary=vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6',
              'Host': 'passport2.chaoxing.com',
              'Connection': 'Keep-Alive',
              'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_1969814533'
              }
    console.log("正在开始尝试[yellow]登录账号[/yellow]")
    session = requests.session()
    tsp, enc = get_encoded_token()
    post_url = 'http://passport2.chaoxing.com/xxt/loginregisternew?' + 'token=4faa8662c59590c6f43ae9fe5b002b42' + '&_time=' + tsp + '&inf_enc=' + enc
    resp = session.post(post_url, data=get_data(usernm, passwd), headers=header)
    result = resp.json()
    if result['status']:
        console.log("[yellow]登录成功[/yellow]")
        pathCheck.check_file('saves/{}/userinfo.json'.format(usernm))
        cookie = requests.utils.dict_from_cookiejar(resp.cookies)
        user['usernm'] = usernm
        user['passwd'] = passwd
        user['userid'] = cookie['_uid']
        user['fid'] = cookie['fid']
        console.log("正在[red]本地[/red]保存账户信息")
        with open('saves/{}/userinfo.json'.format(usernm), 'w') as f:
            json.dump(user, f)
        console.log("[yellow]账户信息[/yellow]保存成功")
    else:
        console.input("[red]登录失败[/red],请检查你的[red]账号密码[/red]是否正确,按回车键退出")
        # print('登录失败，请检查你的账号密码,按回车键退出')
        exit()
    return session


def newLogin(usernm,passwd):
    user = {}
    url = 'https://passport2-api.chaoxing.com/fanyalogin'
    console.log("正在开始尝试[yellow]登录账号[/yellow]")
    session = requests.session()
    session.headers['User-Agent'] = 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_19698145335.21'
    session.headers['X-Requested-With'] = 'XMLHttpRequest'
    data = {
        'fid': '-1',
        'uname': str(usernm),
        'password': b64encode(passwd.encode('utf8')),
        'refer': 'http%3A%2F%2Fi.mooc.chaoxing.com',
        't': 'true',
        'forbidotherlogin': '0',
    }
    resp = session.post(url,data=data)
    if resp.status_code == 200:
        if resp.json()['status']:
            console.log("[yellow]登录成功[/yellow]")
            pathCheck.check_file('saves/{}/userinfo.json'.format(usernm))
            cookie = requests.utils.dict_from_cookiejar(resp.cookies)
            user['usernm'] = usernm
            user['passwd'] = passwd
            user['userid'] = cookie['_uid']
            user['fid'] = cookie['fid']
            console.log("正在[red]本地[/red]保存账户信息")
            with open('saves/{}/userinfo.json'.format(usernm), 'w') as f:
                json.dump(user, f)
            console.log("[yellow]账户信息[/yellow]保存成功")
        else:
            console.input("[red]登录失败[/red],请检查你的[red]账号密码[/red]是否正确,按回车键退出")
            # print('登录失败，请检查你的账号密码,按回车键退出')
            exit()
    else:
        console.log("登录失败，登录返回状态码[red]{}[/red]".format(resp.status_code))
        console.log("返回内容：\n")
        console.log(resp.text)
        console.input("请在仓库Issue页面提出反馈，按回车键退出")
        exit()
    return session

def get_user_from_input():
    """
    用户输入账号与密码
    :return:
    """
    # usernm = input("请输入您的账号")
    # passwd = input("请输入您的密码")
    usernm = console.input("请输入你的[yellow]账号[/yellow]\n")
    passwd = console.input("请输入你的[yellow]密码[/yellow]\n")
    return usernm, passwd


def get_user_from_disk():
    """
    获取本地记录的用户信息
    :return:
    """
    console.log("正在尝试从[bold red]本地[/bold red]获取用户信息")
    pathCheck.check_path('saves')
    folders = listdir('saves')
    return folders


def get_session(usernm,passwd):
    """
    获取session的总入口
    :return: 用户名(str),和 requests.session()对象
    """
    if not usernm and not passwd:
        folders = get_user_from_disk()
        if folders:
            console.log("[bold red]本地[/bold red]存在用户信息")
            console.rule("[bold red]本地[/bold red]用户信息")
            table = Table(show_header=True, header_style="bold magenta", caption_justify='center')
            table.add_column("序号", style="dim")
            table.add_column("用户名")
            for i in range(1, len(folders) + 1):
                table.add_row(str(i), folders[i - 1])
            console.print(table)
            num = str(console.input(
                "请输入你要读取的[yellow bold]账号序号[/yellow bold],若要[bold italic]新建[/bold italic]请输入[yellow]0[/yellow]\n"))
            if num == '0':
                usernm, passwd = get_user_from_input()
                session = newLogin(usernm, passwd)
                return usernm, session
            elif 1 <= int(num) <= len(folders):
                with open('saves/{}/userinfo.json'.format(folders[int(num) - 1]), 'r') as f:
                    user = json.loads(f.read())
                    session = newLogin(user['usernm'], user['passwd'])
                    return user['usernm'], session
            else:
                console.input('你的输入有误，请检查后重新输入,按[red]回车键[/red]退出程序')
                exit()
        else:
            console.log("[red]本地[/red]不存在用户数据，请新建用户")
            usernm, passwd = get_user_from_input()


    session = newLogin(usernm, passwd)
    return usernm, session
