import requests
import time
import hashlib
import re
import os
import random
from urllib.parse import unquote
import json
import small_tools
import get_user
import check_file
import j_updates

__version__ ='0.0.4'
__author__ = 'Samuel Chen'
mp4 = {}
"""
mp4[item] = [filename, dtoken, duration, crc, key], job = objectid
"""
ppt = {}
"""
ppt[item] = [crc, key, filename, pagenum, job[0=objectid,1=jobid]]
"""
course = {}
"""
course = courseid ,cpi ,clazzid ,enc
"""
user = {}
"""
user = userid ,fid
"""
jobs = {}
"""
jobs[0] = objectid , jobs[1] = jobid
"""
finished = ''

ppt_finished = ''


class Learn_XueXiTong():
    def __init__(self):
        # j_updates.check(__version__)
        self.session = requests.session()
        small_tools.check_path('saves')
        self.usernm,self.passwd = get_user.determine_user_file()
        self.login()
    def login(self):
        global user
        header = {'Accept-Language': 'zh_CN',
                  'Content-Type': 'multipart/form-data; boundary=vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6',
                  'Host': 'passport2.chaoxing.com',
                  'Connection': 'Keep-Alive',
                  'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_1969814533'
                  }
        datas = ''
        datas += '--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="uname"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
        datas += self.usernm + '\r\n'
        datas +='--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="code"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
        datas += self.passwd + '\r\n'
        datas +='--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="loginType"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
        datas +='1\r\n'
        datas += '--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6\r\nContent-Disposition: form-data; name="roleSelect"\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'
        datas +='true\r\n--vfV33Hae5dKmSaPrHidgXv4ZK-3gOyNn-jid8-6--\r\n'
        time_stamp = int(time.time() * 1000)
        m_token = '4faa8662c59590c6f43ae9fe5b002b42'
        m_encrypt_str = 'token=' + m_token + '&_time=' + str(time_stamp) + '&DESKey=Z(AfY@XS'
        md5 = hashlib.md5()
        md5.update(m_encrypt_str.encode('utf-8'))
        m_inf_enc = md5.hexdigest()
        post_url = 'http://passport2.chaoxing.com/xxt/loginregisternew?' + 'token=' + m_token + '&_time=' + str(time_stamp) + '&inf_enc=' + m_inf_enc
        req = self.session.post(post_url, data=datas, headers=header)
        result = req.json()
        if result['status']:
            print('登录成功')
            cookie = requests.utils.dict_from_cookiejar(self.session.cookies)
            user['fid'] = cookie['fid']
            user['userid'] = cookie['_uid']
        else:
            print('登录有误，请检查您的账号密码,按回车键退出')
            with open('saves//user_info.json', 'w') as file:
                print('已删除错误信息')
            input()
            exit()
    def prework(self):
        global jobs
        self.find_courses()
        cookie = requests.utils.dict_from_cookiejar(self.session.cookies)
        user['fid'] = cookie['fid']
        user['userid'] = cookie['_uid']
        try:
            f = open(os.path.join(str(self.usernm),str(course['courseid']),'job_list.json'),'r')
            f.close()
            if input('已检测到现有的课程任务点清单，是否加载(1/0)'):
                with open(os.path.join(str(self.usernm),str(course['courseid']),'job_list.json'),'r') as fd:
                    jobs = json.loads(fd.read())
            else:
                for item in self.chapterids:
                    self.find_objects(item,course['courseid'])
                with open(os.path.join(str(self.usernm),str(course['courseid']),'job_list.json'),'w') as file:
                    json.dump(jobs,file)
                print('完成添加{}任务点至json文件'.format(len(jobs)))
        except:
            print('未检测到现有的课程任务点')
            for item in self.chapterids:
                self.find_objects(item, course['courseid'])
            with open(os.path.join(str(self.usernm), str(course['courseid']), 'job_list.json'), 'w') as file:
                json.dump(jobs, file)
            print('完成添加{}任务点至json文件'.format(len(jobs)))
        try:
            with open(os.path.join(str(self.usernm), str(course['courseid']), 'mp4_log.json'), 'r') as m:
                mm = json.loads(m.read())
            with open(os.path.join(str(self.usernm), str(course['courseid']), 'ppt_log.json'), 'r') as p:
                pp = json.loads(p.read())
            if input('检测到已存在部分内容，是否继续(1/0)'):
                total = str(mm) + str(pp)
            else:
                total = ''
        except:
            total = ''
        for item in jobs:
            for i in jobs[item]:
                if i[0] in total:
                    print('{}已经存在'.format(i[0]))
                else:
                    self.determine_job_type(item,i,user['fid'])
        job_total = len(ppt) +len(mp4)
        with open(os.path.join(str(self.usernm),str(course['courseid']),'mp4_log.json'),'w') as m_dump:
            json.dump(mp4,m_dump)
        with open(os.path.join(str(self.usernm),str(course['courseid']),'ppt_log.json'),'w') as p_dump:
            json.dump(ppt,p_dump)
        print('共成功加载任务点{}个'.format(job_total))
    def find_courses(self):
        self.chapterids = []
        print("正在获取您的课程")
        header = {'Accept-Encoding': 'gzip',
                  'Accept-Language': 'zh_CN',
                  'Host': 'mooc1-api.chaoxing.com',
                  'Connection': 'Keep-Alive',
                  'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_1969814533'
                  }
        my_course = self.session.get("http://mooc1-api.chaoxing.com/mycourse?rss=1&mcode=", headers=header)
        result = my_course.json()
        channelList = result['channelList']
        for item in channelList:
            try:
                print(str(channelList.index(item)) + '、' + item['content']['course']['data'][0]['name'])
            except:
                print()
        num = int(input('请输入您要选择的课程的编号'))
        channelList_json = channelList[num]
        course['cpi'] = channelList_json['cpi']
        course['clazzid'] = channelList_json['content']['id']
        course['courseid'] = channelList_json['content']['course']['data'][0]['id']
        print('您要查看的课程为：')
        print("课程名称:" + channelList[num]['content']['course']['data'][0]['name'])
        print("讲师：" + channelList[num]['content']['course']['data'][0]['teacherfactor'])
        url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid=' + str(
            course['courseid']) + '&clazzid=' + str(course['clazzid']) + '&vc=1&cpi=' + str(course['cpi'])
        resq = self.session.get(url, headers=header)
        content = resq.content.decode('utf-8')
        for chapter in re.findall('\?chapterId=(.*?)&', content):
            self.chapterids.append(str(chapter))
        course['enc'] = re.findall("&clazzid=.*?&enc=(.*?)'", content)[0]
        if os.path.exists(os.path.join(str(self.usernm), str(course['courseid']))):
            print('当前课程文件夹已存在')
        else:
            os.mkdir(os.path.join(str(self.usernm), str(course['courseid'])))
            print('新建课程文件夹成功')
        file_path = os.path.join(os.path.join(str(self.usernm), str(course['courseid']), 'course_info.json'))
        with open(file_path, 'w') as coursejson:
            json.dump(course, coursejson)


    def find_objects(self,lesson_id,course_id):
        url = 'http://mooc1-api.chaoxing.com/gas/knowledge?id=' + str(lesson_id) + '&courseid=' + str(
            course_id) + '&fields=begintime,clickcount,createtime,description,indexorder,jobUnfinishedCount,jobcount,jobfinishcount,label,lastmodifytime,layer,listPosition,name,openlock,parentnodeid,status,id,card.fields(cardIndex,cardorder,description,knowledgeTitile,knowledgeid,theme,title,id).contentcard(all)&view=json'
        header = {
            'Accept-Language': 'zh_CN',
            'Host': 'mooc1-api.chaoxing.com',
            'Connection': 'Keep-Alive',
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_19698145335.21'
        }
        req = self.session.get(url, headers=header)
        content = str(json.loads(req.text)['data'][0]['card']['data']).replace('&quot;', '')
        result = re.findall('{objectid:(.*?),.*?,_jobid:(.*?),', content)
        jobs[lesson_id] = result
        print('在章节{}中找到{}个任务点'.format(lesson_id,len(result)))
        cookie = requests.utils.dict_from_cookiejar(self.session.cookies)
        user['fid'] = cookie['fid']
        user['userid'] = cookie['_uid']


    def determine_job_type(self,chapter,item,fid):
        url = 'https://mooc1-api.chaoxing.com/ananas/status/' + item[0]
        header = {
            'Host': 'mooc1-api.chaoxing.com',
            'Connection': 'keep-alive',
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 5.1.1; SM-G9350 Build/LMY48Z) com.chaoxing.mobile/ChaoXingStudy_3_5.21_android_phone_206_1 (SM-G9350; Android 5.1.1; zh_CN)_19698145335.21',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,en-US;q=0.8',
        }
        req = requests.get(url, headers=header)
        try:
            result = req.json()
            self.dj_type(chapter,item, result)
        except:
            print('问题url，{}'.format(url))


    def dj_type(self,chapter,item,content):
        i = 0
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
            mp4[item[0]] = object_mp4
            print('添加mp4任务' + content['filename'] + '成功')
        elif 'ppt' in filename:
            object_ppt = []
            object_ppt.append(content['crc'])
            object_ppt.append(content['key'])
            object_ppt.append(content['filename'])
            object_ppt.append(content['pagenum'])
            object_ppt.append(item)
            object_ppt.append(chapter)
            ppt[item[0]] = object_ppt
            print('添加ppt任务' + content['filename'] + '成功')
        else:
            print('未检测出任务类型，已跳过')


    def do_mp4(self):
        global finished
        finished_num = 0
        path = os.path.join(str(self.usernm),str(course['courseid']))
        try:
            with open(os.path.join(path, 'finished_list.json'),'r') as f:
                finished = f.read()
        except:
            f = open(os.path.join(path, 'finished_list.json'), 'w')
            f.close()
            finished = ''

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
        print('*'*30+'\n'+'*'*30)

        for item in mp4:
            if str(mp4[item][5][0]) in finished:
                print('视频任务{}已完成，跳过'.format(str(mp4[item][0])))
                finished_num += 1
            else:
                playingtime = 0
                retry_time = 0
                job_done = 0
                while True:
                    try:
                        t1 = time.time() * 1000
                        jsoncallback = 'jsonp0' + str(int(random.random() * 100000000000000000))
                        refer = 'http://i.mooc.chaoxing.com'
                        version = str('1605853642425')
                        url0 = 'https://passport2.chaoxing.com/api/monitor?version='+version+'&refer='+refer+'&jsoncallback='+jsoncallback+'&t='+str(t1)
                        rep = self.session.get(url0,headers=header)
                        if job_done >= 3:
                            url = 'https://mooc1-1.chaoxing.com/mycourse/studentstudy?chapterId=' + str(
                                mp4[item][6]) + '&courseId=' + str(course['courseid']) + '&clazzid=' + str(
                                course['clazzid']) + '&enc=' + str(course['enc'])
                            resq = self.session.get(url, headers=head).content.decode('utf-8')
                            url = 'https://fystat-ans.chaoxing.com/log/setlog?' + \
                                  re.findall('src="https://fystat-ans\.chaoxing\.com/log/setlog\?(.*?)">', resq)[0]
                            resq = self.session.get(url, headers=head).text
                            if 'success' in resq:
                                print('添加日志成功')
                                job_done = 0
                            else:
                                print('添加日志失败，请检查网络连接或联系管理员,按任意键退出')
                                input()
                                exit()
                            self.get_score()
                        t = str(int(t1))
                        if int(playingtime) > int(mp4[item][2]):
                            playingtime = int(mp4[item][2])
                        code = '[{}][{}][{}][{}][{}][{}][{}][{}]'.format(str(course['clazzid']),str(user['userid']),str(mp4[item][5][1]),str(mp4[item][5][0]),str(int(playingtime)*1000),"d_yHJ!$pdA~5",str(int(mp4[item][2])*1000),'0_'+str(mp4[item][2]))
                        coded = ''.join(code).encode()
                        enc = hashlib.md5(coded).hexdigest()
                        url = 'http://mooc1-1.chaoxing.com/multimedia/log/a/'+str(course['cpi'])+'/'+str(mp4[item][1])+'?clazzId='+str(course['clazzid'])+'&playingTime='+str(playingtime)+'&duration='+str(mp4[item][2])+'&clipTime=0_'+str(mp4[item][2])+'&objectId='+str(mp4[item][5][0])+'&otherInfo=nodeId_'+str(mp4[item][6])+'-cpi_'+str(course['cpi'])+'&jobid='+str(mp4[item][5][1])+'&userid='+str(user['userid'])+'&isdrag=0&view=pc&enc='+str(enc)+'&rt=0.9&dtype=Video&_t='+str(t)
                        resq = self.session.get(url,headers=header,verify=False)
                        mm = int(mp4[item][2] / 60)
                        ss = int(mp4[item][2]) % 60
                        percent = int(playingtime) / int(mp4[item][2])
                        if resq.json()['isPassed'] == True:
                            print('视频任务{}完成'.format(mp4[item][0]))
                            with open(os.path.join(path, 'finished_list.json'),'a') as f:
                                f.write(str(mp4[item][5][0])+'\n')
                            finished += str(mp4[item][5][0])
                            finished_num += 1
                            rt = random.randint(1, 3)
                            job_done += 1
                            break
                        print('视频任务“{}”总时长{}分钟{}秒，已看{}秒，完成度{:.2%},共完成视频任务{}/{}'.format(mp4[item][0],mm,ss,playingtime,percent,str(finished_num),str(len(mp4))))
                        time.sleep(60)
                        playingtime += 60
                        retry_time = 0
                    except:
                        if retry_time < 6:
                            rt = random.randint(1, 3)
                            print('等待{}秒后验证第{}/5次'.format(rt,retry_time))
                            retry_time += 1
                            time.sleep(rt)
                        else:
                            print('重试超时，请检查您的网络情况')
                            input('按回车键退出程序')
                            exit()
                print('等待{}秒后开始下一个任务'.format(rt))
                time.sleep(rt)

    def get_openc(self):
        url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid={}&clazzid={}&vc=1&cpi={}'.format(
            course['courseid'], course['clazzid'], course['cpi'])
        header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36',
        }
        resq = self.session.get(url,headers=header)
        course['openc'] = re.findall("openc : '(.*?)'",resq.text)[0]


        url = 'https://mooc1-1.chaoxing.com/visit/stucoursemiddle?courseid={}&clazzid={}&vc=1&cpi={}'.format(course['courseid'],course['clazzid'],course['cpi'])
        resq = self.session.get(url,headers=header)
        course['enc'] = re.findall('&enc=(.*?)&',str(resq.url))[0]

    def get_score(self):
        print('正在查询您的当前总分')
        url = 'https://mooc1-1.chaoxing.com/moocAnalysis/statistics-std?courseId={}&classId={}&ut=s&enc={}&cpi={}&openc={}'.format(course['courseid'],course['clazzid'],course['enc'],course['cpi'],course['openc'])
        header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36',
        }
        resq = self.session.get(url,headers=header)
        content = resq.text.replace('\r','').replace('\n','').replace(' ','')
        result = float(re.findall('<th>我的成绩（(.*?)）',content)[0])
        print('您的当前总分为：' + str(result))



    def main(self):
        global mp4,ppt,course,jobs
        j = check_file.check_course_file(self.usernm);
        if j:
            mp4 = j['mp4']
            ppt = j['ppt']
            course = j['course']
            jobs = j['job']
        else:
            self.prework()
        self.get_openc()
        self.do_mp4()


a = Learn_XueXiTong()
a.main()