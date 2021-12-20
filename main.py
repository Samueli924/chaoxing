import requests
import requests.utils
import json
import time
import logging
from random import randint
import re
from base64 import b64encode
from os import mkdir
from os.path import exists
import hashlib


GENERAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.93 Safari/537.36"}


def check_path(path):
    """
    遍历检查各个子路径是否存在，不存在即mkdir新建路径
    :param path: 路径
    :return:
    """
    _path = path.split('/')
    if len(_path) == 1:
        # 路径只有一级
        if not exists(path):
            mkdir(path)
    else:
        # 路径有多级
        for i in range(1, len(_path) + 1):
            path_tmp = '/'.join(_path[:i])
            if not exists(path_tmp):
                mkdir(path_tmp)


def ret_msg(status, data):
    return {"status":status,"data":data}


def formulate_cookies_from_dict(cookies_raw: dict):
    cookies = ""
    for key in cookies_raw:
        cookies += f"{key}={cookies_raw.get(key)}; "
    return cookies[:-2]


class Logger:
    def __init__(self, path, stream=True, output=True, slevel=logging.INFO, olevel=logging.DEBUG):
        check_path("Logs")
        self.logger = logging.getLogger(path)
        self.logger.handlers.clear()
        self.logger.setLevel(logging.DEBUG)
        if stream:
            # 设置CMD日志
            sh = logging.StreamHandler()
            sh.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S'))
            sh.setLevel(slevel)
            self.logger.addHandler(sh)
        if output:
            # 设置文件日志
            fh = logging.FileHandler(path)
            fh.setFormatter(logging.Formatter(
                '[%(asctime)s] [%(levelname)s] [file: %(filename)s] [func: %(funcName)s] [line: %(lineno)d] %(message)s',
                '%Y-%m-%d %H:%M:%S'))
            fh.setLevel(olevel)
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


class User:
    def __init__(self, usernm: str, passwd=""):
        self.logger = Logger("Logs/ClassUser.log")
        check_path(f"Saves/{usernm}")
        self.fid = ""
        self.userid = ""
        if usernm and not passwd:
            self.logger.info("仅用户名模式(User)")
            if exists(f"Saves/{usernm}/secret.cx"):
                with open(f"Saves/{usernm}/secret.cx", "r") as f:
                    self.usernm = usernm
                    self.passwd = json.loads(f.read()).get("passwd")
                    self.logger.info("用户信息设置完毕(User)")
        elif usernm and passwd:
            self.logger.info("用户名且密码模式(User)")
            self.usernm = usernm
            self.passwd = passwd
            self.logger.info("用户信息设置完毕(User)")
        else:
            self.logger.debug("未知模式(User)")

    def login(self, session, need_cookies=False):
        """
        登录请求，并保存Cookies内容至本地文件Saves/{usernm}/cookies.cx
        :return: msg{格式化后的Cookies字符串}
        """
        self.logger.info("开始尝试登录")
        login_url = 'https://passport2.chaoxing.com/fanyalogin'
        data = {
            "fid": "-1",
            "uname": self.usernm,
            "password": b64encode(self.passwd.encode("utf-8")).decode("utf-8"),
            "refer": "http%3A%2F%2Fi.mooc.chaoxing.com",
            "t": "true",
            "validate": "",
        }
        # 发送登录请求
        resp = session.post(login_url, data=data)
        self.logger.debug("请求发送完毕")
        # 判断请求返回正常
        if resp.status_code == 200 and resp.content:
            self.logger.debug("Response接收正常")
            # 判断请求返回是否为JSON格式
            try:
                resp.json()
            except json.decoder.JSONDecodeError:
                self.logger.error("Response内容异常，出现JSONDecodeError错误，请检查您的网络情况。若无法解决，请在GitHub页面提交截图Issue")
                self.logger.error("相关日志:")
                self.logger.error("url=https://passport2.chaoxing.com/fanyalogin")
                self.logger.error(f"data={data}")
                self.logger.error(f"resp={resp.content.decode('utf8')}")
                # 返回错误信息
                return ret_msg("fail","Response出现JSONDecodeError错误，请检查日志")
            result = resp.json()
            self.logger.debug("JSON格式读取正常")
            # 判断返回JSON信息内容
            if not result.get("status") and (("或密码错误" in result.get("msg2")) or ('password is wrong' in result.get("msg2"))):
                self.logger.warn("您的用户名或密码错误")
                self.logger.warn("错误三次将被冻结15分钟")
                return ret_msg("fail","您的用户名或密码错误,错误三次将被冻结15分钟")
            elif not result.get("status") and "已冻结" in result.get("msg2"):
                self.logger.warn("账号因多次输入密码错误，已冻结15分钟")
                return ret_msg("fail","账号因多次输入密码错误，已冻结15分钟")
            elif result.get("status") and "i.mooc.chaoxing.com" in result.get("url"):
                expires = 0
                self.logger.info("登录成功")
                self.logger.debug("正在读取Cookies")
                cookies = resp.cookies
                # 获取用户基本信息(id&fid)
                self.userid = requests.utils.dict_from_cookiejar(cookies)['_uid']
                self.fid = requests.utils.dict_from_cookiejar(cookies)['fid']
                # 将dict(info)用户账号密码保存至本地文件Saves/{self.usernm}/secret.cx
                with open(f"Saves/{self.usernm}/secret.cx", 'w') as f:
                    json.dump({"usernm": self.usernm, "passwd": self.passwd}, f)
                if need_cookies:
                    raw = {
                        "cookies": requests.utils.dict_from_cookiejar(cookies),
                        "expires": expires,
                    }
                    # 将dict(Cookies)保存至本地文件Saves/{self.usernm}/cookies.cx
                    with open(f"Saves/{self.usernm}/cookies.cx", 'w') as f:
                        json.dump(raw, f)
                    # 返回格式化后的Cookies数据
                    return ret_msg("success",formulate_cookies_from_dict(requests.utils.dict_from_cookiejar(cookies)))
                else:
                    return ret_msg("success","登录成功")
            else:
                # 出现未知的返回码，未来出现BUG后再更新
                self.logger.error("出现未知返回码，正在输出日志")
                self.logger.error(resp.text)
                self.logger.error("若无法解决，请在GitHub页面提交截图Issue")
                return ret_msg("fail","出现未知返回码，请检查日志")

        else:
            self.logger.error("网络连接超时，请检查您的网络连接状况")
            return ret_msg("fail","网络连接超时，请检查您的网络连接状况")


    def get_courses(self, session, old, raw):
        """
        读取用户的所有课程信息
        :param old: 是否读取本地文件
        :param raw: 是否返回原始数据
        :return: 返回课程信息数据(原始raw|精简not raw)
        """
        courses = []
        # 是否读取本地文件(old=True|False)
        if old:
            self.logger.info("old读取模式(Courses)")
            if exists(f"Saves/{self.usernm}/courses.cx"):
                # 本地是否存在courses.cx课程文件
                with open(f"Saves/{self.usernm}/courses.cx", "r") as f:
                    self.logger.info("Courses文件存在且可用，正在读取")
                    courses_raw = json.loads(f.read())
                    # 是否返回原始数据(raw=True|False)
                    if raw:
                        # 返回原始数据
                        return ret_msg("success", courses_raw)
                    else:
                        # 读取原始数据里的每一个课程字典
                        for item in courses_raw:
                            # 判断课程是否为学习课程(异常课程字典中不存在state键)
                            if "state" in item["content"]:
                                dic = {}
                                dic['id'] = item['content']['course']['data'][0]['id']
                                dic['name'] = item['content']['course']['data'][0]['name']
                                if item["content"]["state"] == 0:
                                    dic['state'] = "开课"
                                else:
                                    dic['state'] = "结课"
                                if exists(f"Saves/{self.usernm}/{item['content']['course']['data'][0]['id']}"):
                                    dic['exists'] = "存在"
                                else:
                                    dic['exists'] = "不存在"
                                courses.append(dic)
                                self.logger.debug(f"课程识别正常:{dic}")
                                # 返回精简数据
                                return ret_msg("success", courses)
            else:
                self.logger.info("Courses文件不存在，正在在线读取")
        else:
            self.logger.info(f"非old读取模式(Courses)")
            self.logger.info("开始在线读取Courses")
        self.logger.info("开始读取用户的所有课程")
        resp = session.get("http://mooc1-api.chaoxing.com/mycourse?rss=1&mcode=")
        self.logger.debug("Response接收正常")
        # 判断返回值是否为JSON格式
        try:
            resp.json()
        except json.decoder.JSONDecodeError:
            self.logger.error("Response内容异常，出现JSONDecodeError错误，请检查您的网络情况。若无法解决，请在GitHub页面提交截图Issue")
            self.logger.error("相关日志:")
            self.logger.error("url=http://mooc1-api.chaoxing.com/mycourse?rss=1&mcode=")
            self.logger.error(f"resp={resp.content.decode('utf8')}")
            # 返回错误信息
            return ret_msg("fail", "Response出现JSONDecodeError错误，请检查日志")
        self.logger.debug("JSON读取正常")
        channelList = resp.json().get('channelList')
        # 写入本地课程Courses文件
        with open(f"Saves/{self.usernm}/courses.cx", 'w') as f:
            json.dump(channelList, f)
            self.logger.debug(f"写入文件正常:Saves/{self.usernm}/courses.cx")
        # 是否返回原始数据(raw=True|False)
        if raw:
            self.logger.info("在线Courses课程读取完毕")
            return ret_msg("success", channelList)
        else:
            # 读取原始数据里的每一个课程字典
            for item in channelList:
                # 判断课程是否为学习课程(异常课程字典中不存在state键)
                if "state" in item["content"]:
                    dic = {}
                    dic['id'] = item['content']['course']['data'][0]['id']
                    dic['name'] = item['content']['course']['data'][0]['name']
                    if item["content"]["state"] == 0:
                        dic['state'] = "开课"
                    else:
                        dic['state'] = "结课"
                    if exists(f"Saves/{self.usernm}/{item['content']['course']['data'][0]['id']}"):
                        dic['exists'] = "存在"
                    else:
                        dic['exists'] = "不存在"
                    courses.append(dic)
                    self.logger.debug(f"课程识别正常:{dic}")
            self.logger.info("在线Courses课程读取完毕")
            return ret_msg("success", courses)

    def find_course(self, courseid, course_detail):
        """
        根据提供的courses原始数据搜索courseid得到对应的课程原始信息
        :param courseid: 课程id
        :param course_detail: 所有课程的原始数据
        :return:
        """
        for course in course_detail:
            if "state" in course["content"]:
                if str(course['content']['course']['data'][0]['id']) == str(courseid):
                    self.logger.error("已找到课程")
                    return ret_msg("success", course)
        self.logger.error("未找到相关的课程id，请仔细检查后重试")
        return ret_msg("fail", "未找到相关的课程id，请仔细检查后重试")


class Course:
    def __init__(self, user, courseid, course_detail):
        # 初始化日志文件
        self.logger = Logger("Logs/ClassCourse.log")
        self.logger.info("正在初始化Course对象")
        # 初始化Course(courseid:课程id, user:用户User, userid:用户id, course_detail:课程信息)
        self.courseid = courseid
        self.user = user
        self.userid = self.user.userid
        self.course_detail = course_detail
        self.clazzid = course_detail['content']['id']
        self.cpi = course_detail['cpi']
        self.logger.info("初始化完毕")

    def load_chapter_id(self, session, old=True):
        """
        获取所有的章节的ID
        :param session:
        :param old:
        :return:
        """
        course_path = 'Saves/{}/{}'.format(self.user.usernm, self.courseid)
        check_path(course_path)
        if not old:
            self.logger.info("非old读取模式")
            self.logger.info("正在在线请求读取课程章节信息")
            url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid=' + str(
                self.courseid) + '&clazzid=' + str(self.clazzid) + '&vc=1&cpi=' + str(self.cpi)
            resp = session.get(url)
            content = resp.text
            self.chapterids = []
            for chapter in re.findall('\?chapterId=(.*?)&', content):
                self.chapterids.append(str(chapter))
            with open(f"{course_path}/chapterid.cx", "w") as f:
                json.dump(self.chapterids,f)
            self.enc = re.findall("&clazzid=.*?&enc=(.*?)'", content)[0]
            self.course_detail['enc'] = self.enc

            self.logger.info("正在读取openc参数")
            openc_url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid={}&clazzid={}&vc=1&cpi={}'.format(
                self.courseid, self.clazzid, self.cpi)
            resp = session.get(openc_url)
            self.openc = re.findall('&openc=(.*?)"', resp.text)[0]
            self.logger.info(f'成功获取openc参数: {self.openc}')
            self.course_detail['openc'] = self.openc

            with open(f"{course_path}/course.cx", "w") as f:
                json.dump(self.course_detail,f)
        else:
            self.logger.info("old读取模式")
            if exists(f"{course_path}/course.cx") and exists(f"{course_path}/chapterid.cx"):
                self.logger.info("本地存在存储文件，正在读取")
                with open(f"{course_path}/course.cx", "r") as f:
                    self.course_detail = json.loads(f.read())
                with open(f"{course_path}/chapterid.cx", "r") as f:
                    self.chapterids = json.loads(f.read())
                self.enc = self.course_detail['enc']
                self.openc = self.course_detail['openc']
            else:
                self.logger.info("本地不存在存储文件，无法使用old读取模式")
                self.chapterids = self.load_chapter_id(session, old=False)
        return self.chapterids

    def load_jobs(self, session, old):
        session.headers["User-Agent"] = "Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_19698145335.21"
        course_path = 'Saves/{}/{}'.format(self.user.usernm, self.courseid)
        if not old:
            self.logger.info("非old读取模式")
            self.jobs = {}
            num = 0
            last_wait = 0
            while num < len(self.chapterids):
                if num >= last_wait + 40:
                    wait = randint(1, 6)
                    self.logger.info(f"已加载{num}个任务点，等待{wait}秒")
                    time.sleep(wait)
                    last_wait = num
                lesson_id = self.chapterids[num]
                url = 'http://mooc1-api.chaoxing.com/gas/knowledge?id=' + str(lesson_id) + '&courseid=' + str(
                    self.courseid) + '&fields=begintime,clickcount,createtime,description,indexorder,jobUnfinishedCount,jobcount,' \
                                 'jobfinishcount,label,lastmodifytime,layer,listPosition,name,openlock,parentnodeid,status,' \
                                 'id,card.fields(cardIndex,cardorder,description,knowledgeTitile,knowledgeid,theme,title,' \
                                 'id).contentcard(all)&view=json'
                resp = session.get(url)
                try:
                    content = str(resp.json()['data'][0]['card']['data']).replace('&quot;', '')
                    result = re.findall('[{,]objectid:(.*?)[},].*?[{,]_jobid:(.*?)[},]', content)
                    self.jobs[lesson_id] = result
                    self.logger.info(f'在章节{lesson_id}中找到{len(result)}个任务点')
                except Exception as e:
                    self.logger.error("出现错误，请查看日志")
                    self.logger.debug("--------------------")
                    self.logger.debug(resp.text)
                    self.logger.debug("--------------------")
                num += 1
            self.logger.info("正在向本地保存任务点记录")
            with open(f'{course_path}/jobsinfo.cx', 'w') as f:
                json.dump(self.jobs, f)
            self.logger.info("本地保存记录成功")
        else:
            self.logger.info("old读取模式")
            if exists(f"{course_path}/jobsinfo.cx"):
                with open(f'{course_path}/jobsinfo.cx', 'r') as f:
                    self.jobs = json.loads(f.read())
            else:
                self.logger.info("不存在本地存储，无法使用old模式")
                self.jobs = self.load_jobs(session, old=False)
        return self.jobs

    def detect_job_type(self, session, old = False):
        course_path = f'Saves/{self.user.usernm}/{self.courseid}'
        self.mp4 = {}
        if not old:
            self.logger.info("非old读取模式")
            self.logger.info("正在尝试识别任务点类型")
            for chapter in self.jobs:
                for item in self.jobs[chapter]:
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
                    ret = {"type": "none"}
                    try:
                        filename = result['filename']
                        if 'mp4' in filename:
                            object_mp4 = []
                            object_mp4.append(result['filename'])
                            object_mp4.append(result['dtoken'])
                            object_mp4.append(result['duration'])
                            object_mp4.append(result['crc'])
                            object_mp4.append(result['key'])
                            object_mp4.append(item)
                            object_mp4.append(chapter)
                            # mp4[item[0]] = object_mp4
                            self.logger.info(f"添加mp4任务{result['filename']}成功")
                            ret = {'type': 'mp4', 'detail': object_mp4}
                    except:
                        self.logger.error('任务点识别失败')
                    if ret.get("type") == "mp4":
                        self.mp4[item[0]] = ret['detail']
            self.logger.info(f'共加载任务点{len(self.mp4)}个')
            with open(f'{course_path}/mp4info.cx', 'w') as f:
                json.dump(self.mp4, f)
        else:
            self.logger.info("old读取模式")
            if exists(f"{course_path}/mp4info.cx"):
                with open(f'{course_path}/mp4info.cx', 'r') as f:
                    self.mp4 = json.loads(f.read())
            else:
                self.logger.info("不存在本地存储，无法使用old模式")
                self.mp4 = self.detect_job_type(session, old = False)
        return self.mp4

    def do_mp4(self, session, speed):
        """
        完成所有的MP4任务点
        :return:
        """
        finished_num = 0
        finished = []
        # 显示倍速信息
        self.logger.info(f"当前倍速 {speed} 倍速")
        self.logger.info("推荐使用 1 倍速，使用多倍速存在风险")
        # 初始化课程本地文件夹
        course_path = 'Saves/{}/{}'.format(self.user.usernm, self.courseid)
        # 读取本地保存的已完成任务列表
        if exists('{}/finishedinfo.cx'.format(course_path)):
            with open('{}/finishedinfo.cx'.format(course_path), 'r') as f:
                finished = list(f.read())
        # 初始化Trigger
        with open(f"{course_path}/trigger.cx" , "w") as f:
            f.write("True")
        # 开始遍历MP4任务
        for item in self.mp4:

            # 本地完成列表存在MP4的id
            if str(self.mp4[item][5][0]) in finished:
                self.logger.info(f"本地存储显示视频任务 {self.mp4[item][5][0]} 已完成，跳过")
                finished_num += 1
            else:
                mm = int(self.mp4[item][2] / 60)
                ss = int(self.mp4[item][2]) % 60
                total_dated = f"{str(mm).rjust(2,'0')}:{str(ss).rjust(2,'0')}"
                playingtime = 0
                self.logger.info("开始任务 {} ".format(str(self.mp4[item][0])))
                while True:
                    # 加载chaoxing的播放器（保险起见）
                    session.get('https://passport2.chaoxing.com/api/monitor?version=1638893948678&refer=http://i.mooc.chaoxing.com')
                    # 获取当前时间timestamp
                    t = str(int(time.time() * 1000))
                    # 判断任务已完成时间是否大于总时间
                    if int(playingtime) > int(self.mp4[item][2]):
                        playingtime = int(self.mp4[item][2])
                    # 生成加密后的密文参数
                    code = '[{}][{}][{}][{}][{}][{}][{}][{}]'.format(str(self.clazzid), str(self.userid)
                                                                     , str(self.mp4[item][5][1]), str(self.mp4[item][5][0])
                                                                     , str(int(playingtime) * 1000), "d_yHJ!$pdA~5"
                                                                     , str(int(self.mp4[item][2]) * 1000)
                                                                     , '0_' + str(self.mp4[item][2]))
                    coded = ''.join(code).encode()
                    # md5加密
                    enc = hashlib.md5(coded).hexdigest()
                    url = 'https://mooc1.chaoxing.com/multimedia/log/a/' + str(self.cpi) + '/' + str \
                        (self.mp4[item][1]) + '?clazzId=' + str(self.clazzid) + '&playingTime=' + str \
                              (playingtime) + '&duration=' + str(self.mp4[item][2]) + '&clipTime=0_' + str \
                              (self.mp4[item][2]) + '&objectId=' + str(self.mp4[item][5][0]) + '&otherInfo=nodeId_' + str \
                              (self.mp4[item][6]) + '-cpi_' + str(self.cpi) + '&jobid=' + str \
                              (self.mp4[item][5][1]) + '&userid=' + str(self.userid) + '&isdrag=0&view=pc&enc=' + str \
                              (enc) + '&rt=0.9&dtype=Video&_t=' + str(t)
                    # 发送课程记录请求
                    resp = session.get(url)
                    try:
                        resp.json()
                    except json.decoder.JSONDecodeError as e:
                        self.logger.error("出现错误，错误类型:json.decoder.JSONDecodeError")
                        raise Exception("视频任务失败")
                    # 判断任务是否完成
                    if resp.json()['isPassed'] == True:
                        self.logger.info(f'视频任务{self.mp4[item][0]}完成观看')
                        finished.append(self.mp4[item][5][0])
                        with open('{}/finishedinfo.json'.format(course_path), 'w') as f:
                            f.write(str(finished))
                        finished_num += 1
                        data = {
                            "jobId": "完成",
                            "playingTime": total_dated,
                            "totalTime": total_dated,
                            "jobsDone": finished_num,
                            "totalJobs": len(self.mp4),
                            "currentSpeed": speed,
                        }
                        with open(f"{course_path}/currentData", "w") as f:
                            json.dump(data, f)
                        break

                    count = 0
                    # 倍速播放
                    while count < 60:
                        mmm = int(playingtime / 60)
                        sss = int(playingtime) % 60
                        playing_dated = f"{str(mmm).rjust(2, '0')}:{str(sss).rjust(2, '0')}"
                        data = {
                            "jobId": str(self.mp4[item][5][0]),
                            "playingTime": playing_dated,
                            "totalTime": total_dated,
                            "jobsDone": finished_num,
                            "totalJobs": len(self.mp4),
                            "currentSpeed": speed,
                        }
                        self.logger.debug(data)
                        with open(f"{course_path}/currentData", "w") as f:
                            json.dump(data, f)
                        time.sleep(1)
                        playingtime += int(speed)
                        count += int(speed)
                # 单个任务完成
                with open(f"{course_path}/trigger.cx", "r") as f:
                    status = f.read()
                if status == "False":
                    break
                rt = randint(1, 3)
                self.logger.info(
                    '当前任务完成，已完成{}/{}项任务,等待{}秒后开始[blue]下一任务[/blue]'.format(str(finished_num),
                                                                                           str(len(self.mp4)),
                                                                                           rt))

                time.sleep(rt)


def regulate(max_len: int, text: str):
    return text.ljust(2*max_len-len(text), " ")


def show_course(courses):
    max_len = 0
    for course in courses:
        if len(course['name']) > max_len:
            max_len = len(course['name'])
    print(f"| 序号 |    id     |{regulate(max_len, 'name')}| 结课 | 存在 |")
    for course in courses:
        print(f"|{regulate(5, str(courses.index(course) + 1))}|{regulate(10, str(course['id']))}|{regulate(max_len, str(course['name']))}| {course['state']} |{course['exists']}|")
    num = int(input("请输入课程前的序号")) - 1
    return courses[num]['id']


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-usernm", type=str, default="", help="用户名(如:13444449090)")
    parser.add_argument("-passwd", type=str, default="", help="密码(如:123456)")
    parser.add_argument("-courseid", type=str, default="", help="课程id(如:124125621)")
    parser.add_argument("-circle", type=str, default="SINGLE", help="循环模式(SINGLE/ROUND)")
    args = parser.parse_args()
    usernm = args.usernm
    passwd = args.passwd
    courseid = args.courseid
    circle = args.circle
    if not usernm:
        usernm = input("请输入您的账号/手机号")
    if not passwd:
        passwd = input("请输入您的密码")

    logger = Logger("Logs/Main.log")
    session = requests.session()
    session.headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,fr-FR;q=0.8,fr;q=0.7,en;q=0.6,en-GB;q=0.5",
        "Connection": "keep-alive",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
    }
    user = User(usernm, passwd)
    resp = user.login(session, need_cookies=False)
    if resp.get("status") == "success":
        if not courseid:
            courses = user.get_courses(session, old=False, raw=False)
            if courses.get("status") == "success":
                courseid = show_course(courses.get("data"))
        courses = user.get_courses(session, old=False, raw=True)
        if courses.get("status") == "success":
            course_detail = user.find_course(courseid, courses.get("data"))
            if course_detail.get("status") == "success":
                previous_jobs = 0
                speed = str(input("请输入您需要的倍速(建议1-2倍速，请勿设置的太高)"))
                course = Course(user, courseid, course_detail.get("data"))
                while True:
                    course.load_chapter_id(session)
                    jobs = course.load_jobs(session, old=False)
                    if len(jobs) == previous_jobs:
                        logger.info("判断不存在新的任务点")
                        break
                    previous_jobs = len(jobs)
                    course.detect_job_type(session)
                    course.do_mp4(session, speed)
                    logger.info("本轮任务点已完成")
                    if circle == "SINGLE":
                        break
                logger.info("所有任务点已经完成")
