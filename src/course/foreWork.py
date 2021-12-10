# -*- coding:utf-8 -*-
import json
import re
import requests
from os.path import exists
import time
import requests.utils
from rich.console import Console
from rich.table import Table
import random
import src.path.pathCheck as pathCheck

console = Console()


def find_courses(usernm, session, courseid):
    """
    获取用户的所有课程列表
    :param usernm: 用户名
    :param session: requests.session()对象
    :return:
    """
    console.log("开始获取用户的所有[yellow]课程信息[/yellow]")
    course = {}
    chapterids = []
    session.headers['Accept-Encoding'] = 'gzip'
    session.headers['Accept-Language'] = 'zh_CN'
    session.headers['Host'] = 'mooc1-api.chaoxing.com'
    session.headers['Connection'] = 'Keep-Alive'
    url = 'http://mooc1-api.chaoxing.com/mycourse?rss=1&mcode='
    my_course = session.get(url)
    try:
        result = my_course.json()
    except json.decoder.JSONDecodeError as e:
        print("-------------------------")
        print("访问的url为: {}".format(url))
        print("-------------------------")
        print(my_course.text)
        print("-------------------------")
        print("JSON解码错误,请截图或复制上传Issue，方便作者修复BUG")
        print("https://github.com/Samueli924/chaoxing")
        input("点击回车键退出程序")
        exit()
    channelList = result['channelList']
    if not courseid:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("序号", style="dim")
        table.add_column("课程名")
        table.add_column("课程状态")
        table.add_column("记录")
        for item in channelList:
            if "state" in item["content"]:
                if item["content"]["state"] == 0:
                    state = "开课"
                else:
                    state = "结课"
                if exists('saves/{}/{}'.format(usernm, str(item['content']['course']['data'][0]['id']))):
                    table.add_row(str(channelList.index(item) + 1), item['content']['course']['data'][0]['name'], state, "存在")
                else:
                    table.add_row(str(channelList.index(item) + 1), item['content']['course']['data'][0]['name'], state, "无")
        console.rule("所有课程信息", align="center")
        console.print(table)
        num = int(console.input("请输入你要选择的[red]课程序号[/red]\n")) - 1
        channelList_json = channelList[num]
    else:
        found = False
        for item in channelList:
            if "state" in item["content"]:
                if str(item['content']['course']['data'][0]['id']) == str(courseid):
                    channelList_json = item
                    found = True
                    break
        if not found:
            console.log("不存在课程{}，请检查配置文件".format(courseid))
            console.input("点击回车键退出程序")
            exit()
    course['cpi'] = channelList_json['cpi']
    course['clazzid'] = channelList_json['content']['id']
    course['courseid'] = channelList_json['content']['course']['data'][0]['id']
    console.log("[yellow]课程名称[/yellow]:" + channelList_json['content']['course']['data'][0]['name'])
    console.log("[yellow]讲师[/yellow]：" + channelList_json['content']['course']['data'][0]['teacherfactor'])
    # print(exists('saves/{}/{}'.format(usernm,course['courseid'])))
    # print('saves/{}/{}'.format(usernm,course['courseid']))
    # input()
    if exists('saves/{}/{}'.format(usernm, course['courseid'])):
        # num = str(console.input('存在本地保存的课程记录，是否读取本地记录?(1.[red]读取记录[/red],2.[red]不读取[/red])'))
        console.log("读取本地课程记录，如果在后续代码中出现错误，请删除程序目录下的saves文件夹重新运行")
        # if num == '1':
        # console.log("正在读取[red]本地[/red]课程记录")
        course_path = 'saves/{}/{}'.format(usernm, course['courseid'])
        with open('{}/courseinfo.json'.format(course_path), 'r') as f:
            course = json.loads(f.read())
        with open('{}/chapterid.json'.format(course_path), 'r') as f:
            chapterids = json.loads(f.read())
        console.log("[red]本地[/red]课程记录读取成功")
        return session, chapterids, course, True
        # elif num == '2':
        #     console.log("正在尝试[red]在线[/red]读取课程记录")
        #     url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid=' + str(
        #         course['courseid']) + '&clazzid=' + str(course['clazzid']) + '&vc=1&cpi=' + str(course['cpi'])
        #     resp = session.get(url, headers=header)
        #     content = resp.text
        #     for chapter in re.findall('\?chapterId=(.*?)&', content):
        #         chapterids.append(str(chapter))
        #     course['enc'] = re.findall("&clazzid=.*?&enc=(.*?)'", content)[0]
        #     course_path = 'saves/{}/{}'.format(usernm, course['courseid'])
        #     pathCheck.check_path(course_path)
        #     with open('{}/courseinfo.json'.format(course_path), 'w') as f:
        #         json.dump(course, f)
        #     with open('{}/chapterid.json'.format(course_path), 'w') as f:
        #         json.dump(chapterids, f)
        #     console.log("[red]在线[/red]课程记录读取成功")
        #     return chapterids, course, False
    else:
        console.log("正在尝试[red]在线[/red]读取课程记录")
        url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid=' + str(
            course['courseid']) + '&clazzid=' + str(course['clazzid']) + '&vc=1&cpi=' + str(course['cpi'])
        resp = session.get(url)
        content = resp.text
        for chapter in re.findall('\?chapterId=(.*?)&', content):
            chapterids.append(str(chapter))
        course['enc'] = re.findall("&clazzid=.*?&enc=(.*?)'", content)[0]
        course_path = 'saves/{}/{}'.format(usernm, course['courseid'])
        pathCheck.check_path(course_path)
        with open('{}/courseinfo.json'.format(course_path), 'w') as f:
            json.dump(course, f)
        with open('{}/chapterid.json'.format(course_path), 'w') as f:
            json.dump(chapterids, f)
        console.log("[red]在线[/red]课程记录读取成功")
        return session, chapterids, course, False


def find_objectives(usernm, chapterids, course_id, session):
    """
    在用户选择的课程中获取所有的任务点
    :param usernm: 用户名
    :param chapterids: 章节编号
    :param course_id: 课程编号
    :param session: requests.session()
    :return:
    """
    jobs = {}
    num = 0
    last_wait = 0
    while num < len(chapterids):
        if num >= last_wait + 40:
            wait = random.randint(1,6)
            console.log("已加载{}个任务点，等待{}秒".format(num, wait))
            time.sleep(wait)
            last_wait = num
        lesson_id = chapterids[num]
        url = 'http://mooc1-api.chaoxing.com/gas/knowledge?id=' + str(lesson_id) + '&courseid=' + str(
            course_id) + '&fields=begintime,clickcount,createtime,description,indexorder,jobUnfinishedCount,jobcount,' \
                         'jobfinishcount,label,lastmodifytime,layer,listPosition,name,openlock,parentnodeid,status,' \
                         'id,card.fields(cardIndex,cardorder,description,knowledgeTitile,knowledgeid,theme,title,' \
                         'id).contentcard(all)&view=json '
        resp = session.get(url)
        try:
            content = str(json.loads(resp.text)['data'][0]['card']['data']).replace('&quot;', '')
            result = re.findall('[{,]objectid:(.*?)[},].*?[{,]_jobid:(.*?)[},]', content)
            jobs[lesson_id] = result
            console.log('在章节{}中找到[yellow bold]{}[/yellow bold]个任务点'.format(lesson_id, len(result)))
        except Exception as e:
            console.log('错误类型:{}'.format(e.__class__.__name__))
            console.log('错误明细:{}'.format(e))
        num += 1
    course_path = 'saves/{}/{}'.format(usernm, course_id)
    console.log("正在向[red]本地[/red]保存任务点记录")
    with open('{}/jobsinfo.json'.format(course_path), 'w') as f:
        json.dump(jobs, f)
    console.log("[red]本地[/red]保存记录成功")
    return session, jobs


def detect_job_type(jobs, usernm, course_id):
    """
    识别任务点的类型(mp4/ppt)
    :param jobs: 任务点信息
    :param usernm: 用户名
    :param course_id: 课程编号
    :return:
    """
    console.log("正在尝试识别[yellow]任务点类型[/yellow]")
    mp4 = {}
    ppt = {}
    for chapter in jobs:
        for item in jobs[chapter]:
            url = 'https://mooc1-api.chaoxing.com/ananas/status/' + item[0]
            header = {
                'Host': 'mooc1-api.chaoxing.com',
                'Connection': 'keep-alive',
                'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) '
                              'com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; '
                              'zh_CN)_19698145335.21',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate',
                'Accept-Language': 'zh-CN,en-US;q=0.8',
            }
            resp = requests.get(url, headers=header)
            result = resp.json()
            rtn = job_type(chapter, item, result)
            if rtn['type'] == 'mp4':
                mp4[item[0]] = rtn['detail']
            elif rtn['type'] == 'ppt':
                ppt[item[0]] = rtn['detail']
            else:
                pass
    console.log('共加载任务点[yellow]{}[/yellow]个'.format(len(mp4) + len(ppt)))
    course_path = 'saves/{}/{}'.format(usernm, course_id)
    with open('{}/mp4info.json'.format(course_path), 'w') as f:
        json.dump(mp4, f)
    with open('{}/pptinfo.json'.format(course_path), 'w') as f:
        json.dump(ppt, f)
    return mp4, ppt


def job_type(chapter, item, content):
    """
    获取任务点信息
    :param chapter: 章节编号
    :param item: 任务点名
    :param content: 任务点信息
    :return:
    """
    try:
        filename = content['filename']
        if 'mp4' in filename:
            object_mp4 = []
            object_mp4.append(content['filename'])
            object_mp4.append(content['dtoken'])
            object_mp4.append(content['duration'])
            object_mp4.append(content['crc'])
            object_mp4.append(content['key'])
            object_mp4.append(item)
            object_mp4.append(chapter)
            # mp4[item[0]] = object_mp4
            console.log('添加mp4任务[yellow]{}[/yellow]成功'.format(content['filename']))
            return {'type': 'mp4', 'detail': object_mp4}
        elif 'ppt' in filename:
            object_ppt = []
            object_ppt.append(content['crc'])
            object_ppt.append(content['key'])
            object_ppt.append(content['filename'])
            object_ppt.append(content['pagenum'])
            object_ppt.append(item)
            object_ppt.append(chapter)
            # ppt[item[0]] = object_ppt
            console.log('添加ppt任务[yellow]{}[/yellow]成功'.format(content['filename']))
            return {'type': 'ppt', 'detail': object_ppt}
        else:
            console.log('[red]未检测出任务类型[/red]')
            return {'type': 'none'}
    except Exception as e:
        console.log('[red]任务点识别失败[/red]:{}'.format(e))
        return {'type': 'none'}


def get_openc(usernm, course, session):
    """
    获取超星的openc加密密文
    :param usernm: 用户名
    :param course: 课程信息
    :param session: requests.session()
    :return:
    """
    url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid={}&clazzid={}&vc=1&cpi={}'.format(
        course['courseid'], course['clazzid'], course['cpi'])
    resp = session.get(url)
    openc = re.findall("openc : '(.*?)'", resp.text)
    if len(openc) == 0:
        openc = re.findall('&openc=(.*?)"', resp.text)
        if len(openc) == 0:
            print(resp.text)
            console.log("获取课程openc过程中出现错误\n已输出请求返回的结果\n请在Github Issue中提交截图方便我修复")
            console.log(resp.url)
            console.input("点击回车键退出代码")
            exit()
        else:
            course['openc'] = openc[0]
    else:
        course['openc'] = openc[0]
    console.log('成功获取[yellow]openc参数[/yellow]:{}'.format(course['openc']))
    course_path = 'saves/{}/{}'.format(usernm, course['courseid'])
    with open('{}/courseinfo.json'.format(course_path), 'w') as f:
        json.dump(course, f)
    return session, course


def get_forework_done(usernm, session,courseid):
    """
    整合上述所有函数的内容
    :param usernm: 用户名
    :param session: requests.session()
    :return:
    """
    session, chapterids, course, isLocal = find_courses(usernm, session,courseid)
    if not isLocal:
        console.log("开始[red]在线[/red]获取课程所有信息")
        session, jobs = find_objectives(usernm, chapterids, course['courseid'], session)
        mp4, ppt = detect_job_type(jobs, usernm, course['courseid'])
        session, course = get_openc(usernm, course, session)
        return session, jobs, course, mp4, ppt
    else:
        console.log('开始读取[red]本地[/red]记录文件')
        course_path = 'saves/{}/{}'.format(usernm, course['courseid'])
        with open('{}/jobsinfo.json'.format(course_path), 'r') as f:
            jobs = json.loads(f.read())
        with open('{}/mp4info.json'.format(course_path), 'r') as f:
            mp4 = json.loads(f.read())
        with open('{}/pptinfo.json'.format(course_path), 'r') as f:
            ppt = json.loads(f.read())
        return session, jobs, course, mp4, ppt
