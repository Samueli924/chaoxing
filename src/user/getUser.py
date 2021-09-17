import src.path.pathCheck as pathCheck
import time, hashlib, requests, json
import requests.utils
from os import listdir

from rich.console import Console
from rich.table import Table


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
    session = requests.session()
    tsp, enc = get_encoded_token()
    post_url = 'http://passport2.chaoxing.com/xxt/loginregisternew?' + 'token=4faa8662c59590c6f43ae9fe5b002b42' + '&_time=' + tsp + '&inf_enc=' + enc
    resp = session.post(post_url, data=get_data(usernm, passwd), headers=header)
    result = resp.json()
    if result['status']:
        print('登录成功')
        pathCheck.check_file('saves/{}/userinfo.json'.format(usernm))
        cookie = requests.utils.dict_from_cookiejar(resp.cookies)
        user['usernm'] = usernm
        user['passwd'] = passwd
        user['userid'] = cookie['_uid']
        user['fid'] = cookie['fid']
        with open('saves/{}/userinfo.json'.format(usernm), 'w') as f:
            json.dump(user, f)
    else:
        print('登录失败，请检查你的账号密码,按回车键退出')
        input()
        exit()
    return session


def get_user_from_input():
    """
    用户输入账号与密码
    :return:
    """
    usernm = input("请输入您的账号")
    passwd = input("请输入您的密码")
    return usernm, passwd


def get_user_from_disk():
    """
    获取本地记录的用户信息
    :return:
    """
    pathCheck.check_path('saves')
    folders = listdir('saves')
    return folders


def get_session():
    """
    获取session的总入口
    :return: 用户名(str),和 requests.session()对象
    """
    console = Console()
    folders = get_user_from_disk()
    if folders:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("序号", style="dim")
        table.add_column("用户名")
        for i in range(1, len(folders) + 1):
            table.add_row(str(i), folders[i - 1])
        console.print(table)
        num = str(input('请输入你要载入的账号记录序号，若要新建请输入0'))
        if num == '0':
            usernm, passwd = get_user_from_input()
            session = login(usernm, passwd)
            return usernm, session
        elif 1 <= int(num) <= len(folders):
            with open('saves/{}/userinfo.json'.format(folders[int(num) - 1]), 'r') as f:
                user = json.loads(f.read())
                session = login(user['usernm'], user['passwd'])
                return user['usernm'], session
        else:
            print('你的输入有误，请检查后重新输入,按回车键退出程序')
            input()
            exit()
    else:
        usernm, passwd = get_user_from_input()
        session = login(usernm, passwd)
        return usernm, session
