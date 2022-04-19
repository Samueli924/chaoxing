import json
import random
import re
import time
from base64 import b64encode
from hashlib import md5

import requests
from requests.utils import dict_from_cookiejar

from utils.functions import Logger
from utils.functions import pretty_print, sort_missions, get_enc_time, show_progress, save_users


class Chaoxing:
    def __init__(self, usernm, passwd, debug, show):
        self.usernm = usernm
        self.passwd = passwd
        self.logger = Logger("ChaoxingAPI", debug, show)
        self.session = None
        self.uid = None
        self.cookies = None
        self.courses = None
        self.selected_course = None
        self.missions = None
        self.speed = None

    def init_explorer(self):
        self.session = requests.session()
        self.session.headers = {
            'User-Agent': f'Dalvik/2.1.0 (Linux; U; Android {random.randint(9, 12)}; MI{random.randint(10, 12)} Build/SKQ1.210216.001) (device:MI{random.randint(10, 12)}) Language/zh_CN com.chaoxing.mobile/ChaoXingStudy_3_5.1.4_android_phone_614_74(@Kalimdor)_6845669cc7294fdc8549000714291300',
            'X-Requested-With': 'com.chaoxing.mobile'
        }

    def login(self):
        """
        登录
        :return:
        """
        url = "https://passport2.chaoxing.com/fanyalogin"
        data = {"fid": "-1",
                "uname": self.usernm,
                "password": b64encode(self.passwd.encode("utf8")),
                "t": "true",
                "forbidotherlogin": "0",
                "validate": ""}
        self.logger.debug("发送登录数据")
        resp = self.session.post(url, data=data)
        self.logger.debug("收到返回数据")
        if resp.json()["status"]:
            self.uid = resp.cookies['_uid']
            self.cookies = dict_from_cookiejar(resp.cookies)
            save_users(usernm=self.usernm, passwd=self.passwd)
            return True
        else:
            self.logger.error("登录失败：" + str(resp.json()))
            return False

    def status(self):
        """
        检测Cookies是否有效
        :return:
        """
        if not re.findall("<title>用户登录</title>", self.session.get("https://i.chaoxing.com/base").text):
            self.logger.debug("用户Cookies有效")
            return True
        else:
            return False

    def get_all_courses(self):
        url = 'https://mooc1-api.chaoxing.com/mycourse/backclazzdata?view=json&mcode='
        courses = self.session.get(url).json()
        if courses["result"] == 1:  # 假如返回值为1
            __temp = courses["channelList"]
            for course in __temp:   # 删除所有的自建课程
                if "course" not in course['content']:
                    __temp.remove(course)
            self.courses = __temp
            return True
        else:
            self.logger.error("无法获取相关课程数据")
            return False

    def select_course(self):
        pretty_print(self.courses)
        index = int(input("请输入您要学习的课程序号"))
        self.selected_course = self.courses[index - 1]
        return True

    def get_selected_course_data(self):
        url = 'https://mooc1-api.chaoxing.com/gas/clazz'
        params = {
            'id': self.selected_course["key"],
            'fields': 'id,bbsid,classscore,isstart,allowdownload,chatid,name,state,isthirdaq,isfiled,information,discuss,visiblescore,begindate,coursesetting.fields(id,courseid,hiddencoursecover,hiddenwrongset,coursefacecheck),course.fields(id,name,infocontent,objectid,app,bulletformat,mappingcourseid,imageurl,teacherfactor,knowledge.fields(id,name,indexOrder,parentnodeid,status,layer,label,begintime,endtime,attachment.fields(id,type,objectid,extension).type(video)))',
            'view': 'json'
        }
        self.missions = sort_missions(self.session.get(url, params=params).json()["data"][0]["course"]["data"][0]["knowledge"]["data"])
        return True

    def get_mission(self, mission_id, course_id):
        url = 'https://mooc1-api.chaoxing.com/gas/knowledge'
        enc = get_enc_time()
        params = {
            'id': mission_id,
            'courseid': course_id,
            'fields': 'id,parentnodeid,indexorder,label,layer,name,begintime,createtime,lastmodifytime,status,jobUnfinishedCount,clickcount,openlock,card.fields(id,knowledgeid,title,knowledgeTitile,description,cardorder).contentcard(all)',
            'view': 'json',
            'token': "4faa8662c59590c6f43ae9fe5b002b42",
            '_time': enc[0],
            'inf_enc': enc[1]
        }
        return self.session.get(url, params=params).json()

    def get_knowledge(self, clazzid, courseid, knowledgeid, num):
        url = 'https://mooc1-api.chaoxing.com/knowledge/cards'
        params = {
            'clazzid': clazzid,
            'courseid': courseid,
            'knowledgeid': knowledgeid,
            'num': num,
            'isPhone': 1,
            'control': True,
        }
        return self.session.get(url, params=params).text

    def get_attachments(self, text):
        if res := re.search(r'window\.AttachmentSetting =({\"attachments\":.*})', text):
            attachments = json.loads(res[1])
            self.logger.debug("---attachments info begin---")
            self.logger.debug(attachments)
            self.logger.debug("---attachments info end---")
            return attachments

    def get_d_token(self, objectid, fid):
        url = 'https://mooc1-api.chaoxing.com/ananas/status/{}'.format(objectid)
        params = {
            'k': fid,
            'flag': 'normal',
            '_dc': int(round(time.time() * 1000))
        }
        self.logger.debug("获取视频信息")
        d_token = self.session.get(url, params=params).json()
        self.logger.debug("视频信息已获取")
        self.logger.debug("---d_token info begin---")
        self.logger.debug(d_token)
        self.logger.debug("---d_token info end---")
        return d_token

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        # https://github.com/ZhyMC/chaoxing-xuexitong-autoflush/blob/445c8d8a8cc63472dd90cdf2a6ab28542c56d93b/logger.js
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{playingTime * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]".encode()).hexdigest()

    def add_log(self, personid, courseid, classid, encode):
        log_url = f"https://fystat-ans.chaoxing.com/log/setlog?personid={personid}&courseId={courseid}&classId={classid}&encode={encode}"
        self.logger.debug("录入学习记录")
        resp = self.session.get(url=log_url)
        self.logger.debug("收到录入结果")
        if "success" in resp.text:
            print("学习记录录入成功")
            return True
        else:
            print("学习记录录入失败")
            self.logger.debug("---resp.text info begin---")
            self.logger.debug(resp.text)
            self.logger.debug("---resp.text info end---")

    def main_pass_video(self, personid, dtoken, otherInfo, playingTime, clazzId, duration, jobid, objectId, userid):
        url = 'https://mooc1-api.chaoxing.com/multimedia/log/a/{}/{}'.format(personid, dtoken)
        # print(url)
        params = {
            'otherInfo': otherInfo,
            'playingTime': playingTime,
            'duration': duration,
            # 'akid': None,
            'jobid': jobid,
            'clipTime': '0_{}'.format(duration),
            'clazzId': clazzId,
            'objectId': objectId,
            'userid': userid,
            'isdrag': 0,
            'enc': self.get_enc(clazzId, jobid, objectId, playingTime, duration, userid),
            'rt': '1',  # 'rt': '0.9',  ??
            'dtype': 'Video',
            'view': 'json'
        }
        # print:(url+params)
        return self.session.get(url, params=params).json()

    def pass_video(self, video_duration, cpi, dtoken, otherInfo, clazzid, jobid, objectid, userid, name, speed):
        sec = 58
        playingTime = 0
        print("当前播放速率："+str(speed)+"倍速")
        while True:
            if sec >= 58:
                sec = 0
                res = self.main_pass_video(
                    cpi,
                    dtoken,
                    otherInfo,
                    playingTime,
                    clazzid,
                    video_duration,
                    jobid,
                    objectid,
                    userid
                )
                # print(res)
                if res.get('isPassed'):
                    show_progress(name, video_duration, video_duration, speed)
                    break
                elif res.get('error'):
                    self.logger.debug("---result info begin---")
                    self.logger.debug(res.get)
                    self.logger.debug("---result info end---")
                    raise Exception('出现错误')
                continue
            show_progress(name, playingTime, video_duration, speed)
            playingTime += 1 * self.speed
            sec += 1 * self.speed
            time.sleep(1)
