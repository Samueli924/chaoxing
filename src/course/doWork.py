import json
from os.path import exists
import time, random, re, hashlib
from rich.console import Console
from rich.table import Table



console = Console()
def do_mp4(usernm, course, session, mp4):
    """
    完成所有的MP4任务点
    :param usernm: 用户名
    :param course: 课程信息
    :param session: 网络session
    :param mp4: mp4任务点信息
    :return:
    """
    speed = 1
    finished_num = 0
    course_path = 'saves/{}/{}'.format(usernm, course['courseid'])
    if exists('{}/finishedinfo.json'.format(course_path)):
        with open('{}/finishedinfo.json'.format(course_path), 'r') as f:
            finished = f.read()
    else:
        with open('{}/finishedinfo.json'.format(course_path), 'w') as f:
            pass
        finished = ''
    with open('saves/{}/userinfo.json'.format(usernm), 'r') as f:
        user = json.loads(f.read())
    header = {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'keep-alive',
        'Content-Type': 'application/json',
        'Host': 'mooc1-1.chaoxing.com',
        'Referer': 'https://mooc1-1.chaoxing.com/ananas/modules/video/index.html?v=2020-1105-2010',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36',
    }
    head = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36',
    }
    # print('*' *30 +'\n ' +'*' *30)
    job_done = 0
    for item in mp4:
        if str(mp4[item][5][0]) in finished:
            print('跳过视频任务{}'.format(str(mp4[item][0])))
            finished_num += 1
        else:
            playingtime = 0
            retry_time = 0
            print('开始任务{}'.format(str(mp4[item][0])))
            while True:
                try:
                    t1 = time.time() * 1000
                    jsoncallback = 'jsonp0' + str(int(random.random() * 100000000000000000))
                    refer = 'http://i.mooc.chaoxing.com'
                    version = str('1605853642425')
                    url0 = 'https://passport2.chaoxing.com/api/monitor?version=' + version + '&refer=' + refer + '&jsoncallback=' + jsoncallback + '&t=' + str \
                        (t1)
                    rep = session.get(url0, headers=header)
                    if job_done >= 3:
                        url = 'https://mooc1-1.chaoxing.com/mycourse/studentstudy?chapterId=' + str(
                            mp4[item][6]) + '&courseId=' + str(course['courseid']) + '&clazzid=' + str(
                            course['clazzid']) + '&enc=' + str(course['enc'])
                        resq = session.get(url, headers=head).content.decode('utf-8')
                        url = 'https://fystat-ans.chaoxing.com/log/setlog?' + \
                              re.findall('src="https://fystat-ans\.chaoxing\.com/log/setlog\?(.*?)">', resq)[0]
                        resq = session.get(url, headers=head).text
                        if 'success' in resq:
                            print('添加日志成功')
                            job_done = 0
                        else:
                            print('添加日志失败，请检查网络连接或联系管理员,按任意键退出')
                            input()
                            exit()
                        # self.get_score()
                    t = str(int(t1))
                    if int(playingtime) > int(mp4[item][2]):
                        playingtime = int(mp4[item][2])
                    code = '[{}][{}][{}][{}][{}][{}][{}][{}]'.format(str(course['clazzid']), str(user['userid'])
                                                                     , str(mp4[item][5][1]), str(mp4[item][5][0])
                                                                     , str(int(playingtime) * 1000), "d_yHJ!$pdA~5"
                                                                     , str(int(mp4[item][2]) * 1000)
                                                                     , '0_' + str(mp4[item][2]))
                    coded = ''.join(code).encode()
                    enc = hashlib.md5(coded).hexdigest()
                    url = 'http://mooc1-1.chaoxing.com/multimedia/log/a/' + str(course['cpi']) + '/' + str \
                        (mp4[item][1]) + '?clazzId=' + str(course['clazzid']) + '&playingTime=' + str \
                              (playingtime) + '&duration=' + str(mp4[item][2]) + '&clipTime=0_' + str \
                              (mp4[item][2]) + '&objectId=' + str(mp4[item][5][0]) + '&otherInfo=nodeId_' + str \
                              (mp4[item][6]) + '-cpi_' + str(course['cpi']) + '&jobid=' + str \
                              (mp4[item][5][1]) + '&userid=' + str(user['userid']) + '&isdrag=0&view=pc&enc=' + str \
                              (enc) + '&rt=0.9&dtype=Video&_t=' + str(t)
                    resq = session.get(url, headers=header, verify=False)
                    # print(resq.text)
                    mm = int(mp4[item][2] / 60)
                    ss = int(mp4[item][2]) % 60
                    percent = int(playingtime) / int(mp4[item][2])
                    # print(resq.text)
                    if resq.json()['isPassed'] == True:
                        print('视频任务{}   进度100%      完成观看        '.format(mp4[item][0]))
                        with open('{}/finishedinfo.json'.format(course_path), 'a') as f:
                            f.write(str(mp4[item][5][0]) + '\n')
                        finished += str(mp4[item][5][0])
                        finished_num += 1
                        rt = random.randint(1, 3)
                        job_done += 1
                        break

                    # self.show_status(speed ,mp4[item][0] ,mm ,ss ,playingtime ,str(finished_num) ,str(len(mp4)))

                    print(
                        '视频任务“{}”总时长{}分钟{}秒，已看{}秒，完成度{:.2%},共完成视频任务{}/{}'.format(mp4[item][0], mm, ss, playingtime,
                                                                                 percent, str(finished_num),
                                                                                 str(len(mp4))), end="\r",
                        flush=True)
                    time.sleep(int(float(60) * float(1 / speed)))
                    playingtime += 60
                    retry_time = 0
                except:
                    if retry_time < 6:
                        rt = random.randint(1, 3)
                        print('等待{}秒后验证第{}/5次'.format(rt, retry_time))
                        retry_time += 1
                        time.sleep(rt)
                    else:
                        print('重试超时，请检查您的网络情况或检查此课程是否已经结课')
                        input('按回车键退出程序')
                        exit()
            print('等待{}秒后开始下一个任务'.format(rt))
            time.sleep(rt)
    print('MP4任务全部完成')


def do_ppt(session,mp4,ppt,usernm, course):
    """
    完成所有的ppt任务点
    :param session: 网络session
    :param mp4: 所有MP4任务点信息
    :param ppt: 所有PPT任务点信息
    :param usernm: 用户名
    :param course: 课程信息
    :return:
    """
    ppt_detail_path = 'saves/{}/{}/pptdetail.json'.format(usernm, course['courseid'])
    ppt_done_path = 'saves/{}/{}/pptdone.json'.format(usernm, course['courseid'])
    chapter_done_path = 'saves/{}/{}/chapterdone.json'.format(usernm, course['courseid'])
    with open(ppt_detail_path, 'w') as f:
        pass

    if exists(ppt_done_path):
        with open(ppt_done_path, 'r') as f:
            ppt_done = f.read()
    else:
        with open(ppt_done_path, 'w') as f:
            pass
        ppt_done = ''

    if exists(chapter_done_path):
        with open(chapter_done_path, 'r') as f:
            chapter_done = f.read()
    else:
        with open(chapter_done_path, 'w') as f:
            pass
        chapter_done = ''

    chapters = []
    for item in mp4:
        if mp4[item][6] in chapters:
            pass
        else:
            chapters.append(mp4[item][6])
    for item in ppt:
        if ppt[item][5] in chapters:
            pass
        else:
            chapters.append(ppt[item][5])


    load_ppt(session,course,ppt_done,chapter_done,chapters,usernm,ppt)
    input('ppt学习结束，按回车键退出')


def learn_ppt(objectid, jtoken,ppt_done,usernm,course,ppt,session):
    ppt_done_path = 'saves/{}/{}/pptdone.json'.format(usernm, course['courseid'])
    rt = random.randint(2, 6)
    header = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36',
    }
    print('开始任务' + str(objectid))
    url = 'https://mooc1-1.chaoxing.com/ananas/job/document?jobid=' + str(ppt[objectid][4][1]) + '&knowledgeid=' + str(
        ppt[objectid][5]) + '&courseid=' + str(course['courseid']) + '&clazzid=' + str(
        course['clazzid']) + '&jtoken=' + str(jtoken) + '&_dc=' + str(int((time.time() - 10) * 1000))
    resq = session.get(url, headers=header)
    result = resq.json()['msg']
    if result == '考核点已经完成' or result == '添加考核点成功':
        print('PPT任务{}完成,{}秒后开始下一项'.format(str(objectid), rt))
        with open(ppt_done_path, 'a') as f:
            f.write(objectid + '\n')
        ppt_done += str(objectid + '\n')
        time.sleep(rt)
        return 1
    else:
        print(result)
        print('任务失败，重试中')
        return 0


def load_ppt(session,course,ppt_done,chapter_done,chapters,usernm,ppt):
    ppt_detail_path = 'saves/{}/{}/pptdetail.json'.format(usernm, course['courseid'])

    chapter_done_path = 'saves/{}/{}/chapterdone.json'.format(usernm, course['courseid'])
    header = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36',
    }
    total = 0
    for item in sorted(chapters):
        if item in chapter_done:
            print('章节{}已完成，跳过'.format(item))
        else:
            i = 0
            while True:
                url = 'https://mooc1-1.chaoxing.com/knowledge/cards?clazzid=' + str(
                    course['clazzid']) + '&courseid=' + str(course['courseid']) + '&knowledgeid=' + str(
                    item) + '&num=' + str(i) + '&ut=s&cpi=' + str(course['cpi']) + '&v=20160407-1'
                resq = session.get(url, headers=header).text
                result = re.findall('mArg = (.*?);', resq)[1]
                if result != '$mArg':
                    print('{}章{}页读取完毕，查看下一页'.format(item, i))
                    with open(ppt_detail_path, 'a') as f:
                        f.write(result + '\n\n')
                    i += 1
                else:
                    print('{}章读取完毕，开始读取下一章'.format(item))
                    chapter_done += item + '\n'
                    with open(chapter_done_path, 'a') as f:
                        f.write(item + '\n')
                    total += 1
                    break
            time.sleep(1)
            if total == 5:
                with open(ppt_detail_path, 'r') as f:
                    tmp_ppt = f.read()
                result = re.findall('{"jobid":".*?,"jtoken":"(.*?)".*?,"objectid":"(.*?)",.*?},', tmp_ppt)
                retry = 0
                for item in result:
                    if item[1] in ppt_done:
                        print('任务{}已完成，跳过'.format(item[1]))
                    else:
                        if learn_ppt(item[1], item[0],ppt_done,usernm,course,ppt,session):
                            pass
                        else:
                            retry += 1
                        if retry > 1:
                            input('重试失败，请检查网络情况,按回车键退出')
                            exit()
                f = open(ppt_detail_path, 'w')
                f.close()
                total = 0
                print('开始读取后续章节')
