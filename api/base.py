# -*- coding: utf-8 -*-
"""
学习通API基础模块
包含账号登录、课程获取、任务点处理等基础功能
"""
import re
import time
import random
import requests
from hashlib import md5
from requests.adapters import HTTPAdapter
from typing import Dict, List, Optional, Union, Any

from api.cipher import AESCipher
from api.logger import logger
from api.cookies import save_cookies, use_cookies
from api.process import show_progress
from api.config import GlobalConst as gc
from api.decode import (
    decode_course_list,
    decode_course_point, 
    decode_course_card,
    decode_course_folder,
    decode_questions_info
)
from api.answer import *


def get_timestamp() -> str:
    """获取毫秒级时间戳"""
    return str(int(time.time() * 1000))


def get_random_seconds() -> int:
    """获取随机等待时间(30-90秒)"""
    return random.randint(30, 90)


def init_session(is_video: bool = False, is_audio: bool = False) -> requests.Session:
    """
    初始化requests会话
    
    Args:
        is_video: 是否为视频请求
        is_audio: 是否为音频请求
    
    Returns:
        配置好的requests.Session对象
    """
    session = requests.session()
    session.verify = False
    # 配置重试机制
    adapter = HTTPAdapter(max_retries=3)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    # 根据请求类型设置对应headers
    if is_video:
        session.headers = gc.VIDEO_HEADERS
    elif is_audio:
        session.headers = gc.AUDIO_HEADERS
    else:
        session.headers = gc.HEADERS
        
    session.cookies.update(use_cookies())
    return session


class Account:
    """账号信息类"""
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.last_login = None
        self.is_success = None


class Chaoxing:
    """超星学习通API封装类"""
    
    def __init__(self, account: Optional[Account] = None, tiku: Optional['Tiku'] = None):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku

    def login(self) -> Dict[str, Union[bool, str]]:
        """
        登录学习通
        
        Returns:
            登录结果字典 {"status": bool, "msg": str}
        """
        session = requests.session()
        session.verify = False
        url = "https://passport2.chaoxing.com/fanyalogin"
        
        data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(self.account.username),
            "password": self.cipher.encrypt(self.account.password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": True,
            "forbidotherlogin": 0,
            "validate": "",
            "doubleFactorLogin": 0,
            "independentId": 0
        }
        
        logger.trace("正在尝试登录...")
        resp = session.post(url, headers=gc.HEADERS, data=data)
        
        if resp and resp.json()["status"]:
            save_cookies(session)
            logger.info("登录成功...")
            return {"status": True, "msg": "登录成功"}
        return {"status": False, "msg": str(resp.json()["msg2"])}

    def get_fid(self) -> str:
        """获取fid"""
        return init_session().cookies.get("fid")

    def get_uid(self) -> str:
        """获取用户ID"""
        return init_session().cookies.get("_uid")

    def get_course_list(self) -> List[Dict]:
        """
        获取课程列表
        
        Returns:
            课程信息列表
        """
        session = init_session()
        url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
        
        # 基础请求数据
        data = {
            "courseType": 1,
            "courseFolderId": 0,
            "query": "",
            "superstarClass": 0
        }
        
        logger.trace("正在读取所有的课程列表...")
        
        # 设置专用headers
        headers = {
            "Host": "mooc2-ans.chaoxing.com",
            "sec-ch-ua-platform": "\"Windows\"",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
            "Accept": "text/html, */*; q=0.01",
            "sec-ch-ua": "\"Microsoft Edge\";v=\"129\", \"Not=A?Brand\";v=\"8\", \"Chromium\";v=\"129\"",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "sec-ch-ua-mobile": "?0",
            "Origin": "https://mooc2-ans.chaoxing.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5"
        }
        
        # 获取主课程列表
        resp = session.post(url, headers=headers, data=data)
        logger.info("课程列表读取完毕...")
        course_list = decode_course_list(resp.text)

        # 获取文件夹中的课程
        interaction_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
        interaction_resp = session.get(interaction_url)
        course_folder = decode_course_folder(interaction_resp.text)
        
        # 遍历文件夹获取课程
        for folder in course_folder:
            folder_data = data.copy()
            folder_data["courseFolderId"] = folder["id"]
            resp = session.post(url, data=folder_data)
            course_list.extend(decode_course_list(resp.text))
            
        return course_list

    def get_course_point(self, courseid: str, clazzid: str, cpi: str) -> List[Dict]:
        """
        获取课程章节信息
        
        Args:
            courseid: 课程ID
            clazzid: 班级ID  
            cpi: 课程参数
            
        Returns:
            章节信息列表
        """
        session = init_session()
        url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={courseid}&clazzid={clazzid}&cpi={cpi}&ut=s"
        
        logger.trace("开始读取课程所有章节...")
        resp = session.get(url)
        logger.info("课程章节读取成功...")
        
        return decode_course_point(resp.text)

    def get_job_list(self, clazzid: str, courseid: str, cpi: str, knowledgeid: str) -> tuple[List[Dict], Dict]:
        """
        获取章节任务点列表
        
        Args:
            clazzid: 班级ID
            courseid: 课程ID
            cpi: 课程参数
            knowledgeid: 知识点ID
            
        Returns:
            (任务点列表, 任务点信息)
        """
        session = init_session()
        job_list = []
        job_info = {}
        
        # 遍历可能的任务卡片数量
        for num in ["0", "1", "2"]:
            url = f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid={clazzid}&courseid={courseid}&knowledgeid={knowledgeid}&num={num}&ut=s&cpi={cpi}&v=20160407-3&mooc2=1"
            
            logger.trace("开始读取章节所有任务点...")
            resp = session.get(url)
            tasks, info = decode_course_card(resp.text)
            
            # 检查章节是否开放
            if info.get('notOpen', False):
                logger.info("该章节未开放")
                return [], info
                
            job_list.extend(tasks)
            job_info.update(info)
            
        logger.info("章节任务点读取成功...")
        return job_list, job_info

    def get_enc(self, clazz_id: str, jobid: str, object_id: str, playing_time: int, 
                duration: int, userid: str) -> str:
        """
        生成视频播放加密参数
        """
        raw = f"[{clazz_id}][{userid}][{jobid}][{object_id}][{playing_time * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]"
        return md5(raw.encode()).hexdigest()

    def video_progress_log(self, session: requests.Session, course: Dict, job: Dict,
                          job_info: Dict, dtoken: str, duration: int, playing_time: int,
                          type_: str = "Video") -> Union[Dict, bool]:
        """
        记录视频播放进度
        
        Args:
            session: 请求会话
            course: 课程信息
            job: 任务信息
            job_info: 任务详细信息
            dtoken: 播放token
            duration: 视频总时长
            playing_time: 当前播放时间
            type_: 媒体类型(Video/Audio)
            
        Returns:
            响应结果或False(失败)
        """
        # 构建otherInfo参数
        other_info = (f"otherInfo={job['otherinfo']}&courseId={course['courseId']}&" 
                     if "courseId" not in job['otherinfo'] 
                     else f"otherInfo={job['otherinfo']}&")
        
        success = False
        # 尝试不同的rt参数
        for rt in ["0.9", "1"]:
            url = (
                f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/{course['cpi']}/{dtoken}?"
                f"clazzId={course['clazzId']}&"
                f"playingTime={playing_time}&"
                f"duration={duration}&"
                f"clipTime=0_{duration}&"
                f"objectId={job['objectid']}&"
                f"{other_info}"
                f"jobid={job['jobid']}&"
                f"userid={self.get_uid()}&"
                f"isdrag=3&"
                f"view=pc&"
                f"enc={self.get_enc(course['clazzId'], job['jobid'], job['objectid'], playing_time, duration, self.get_uid())}&"
                f"rt={rt}&"
                f"dtype={type_}&"
                f"_t={get_timestamp()}"
            )
            
            resp = session.get(url)
            if resp.status_code == 200:
                success = True
                break
                
        if success:
            return resp.json()
            
        logger.warning("出现403报错，尝试修复无效，正在跳过当前任务点...")
        return False

    def study_video(self, course: Dict, job: Dict, job_info: Dict, 
                   speed: float = 1.0, type_: str = "Video") -> None:
        """
        学习视频/音频任务
        
        Args:
            course: 课程信息
            job: 任务信息
            job_info: 任务详细信息  
            speed: 播放速度
            type_: 媒体类型(Video/Audio)
        """
        # 初始化会话
        session = init_session(is_video=(type_=="Video"), is_audio=(type_=="Audio"))
        
        # 获取视频信息
        info_url = f"https://mooc1.chaoxing.com/ananas/status/{job['objectid']}?k={self.get_fid()}&flag=normal"
        video_info = session.get(info_url).json()
        
        if "status" not in video_info:
            logger.info("获取视频信息失败，跳过当前任务点...")
            return None
            
        if video_info["status"] == "success":
            dtoken = video_info["dtoken"]
            duration = video_info["duration"]
            
            is_passed = False
            is_finished = False
            playing_time = 0
            
            logger.info(f"开始任务: {job['name']}, 总时长: {duration}秒")
            
            # 循环提交播放进度
            while not is_finished:
                if is_finished:
                    playing_time = duration
                    
                is_passed = self.video_progress_log(
                    session, course, job, job_info, dtoken, 
                    duration, playing_time, type_
                )
                
                if not is_passed or (is_passed and is_passed["isPassed"]):
                    break
                    
                # 计算等待时间    
                wait_time = get_random_seconds()
                if playing_time + wait_time >= int(duration):
                    wait_time = int(duration) - playing_time
                    is_finished = True
                    
                # 显示进度
                show_progress(job['name'], playing_time, wait_time, duration, speed)
                playing_time += wait_time
                
            print("\r", end="", flush=True)
            logger.info(f"任务完成: {job['name']}")
            
    def study_document(self, course: Dict, job: Dict) -> None:
        """
        学习文档任务
        
        Args:
            course: 课程信息
            job: 任务信息
        """
        session = init_session()
        url = (f"https://mooc1.chaoxing.com/ananas/job/document?"
               f"jobid={job['jobid']}&"
               f"knowledgeid={re.findall(r'nodeId_(.*?)-', job['otherinfo'])[0]}&"
               f"courseid={course['courseId']}&"
               f"clazzid={course['clazzId']}&"
               f"jtoken={job['jtoken']}&"
               f"_dc={get_timestamp()}")
        session.get(url)

    def study_work(self, course: Dict, job: Dict, job_info: Dict) -> None:
        """
        完成作业任务
        
        Args:
            course: 课程信息
            job: 任务信息
            job_info: 任务详细信息
        """
        if not self.tiku:
            logger.info("未配置题库，跳过答题")
            return None
        
        if self.tiku.DISABLE or not self.tiku:
            return None
        
        def random_answer(options:str) -> str:
            answer = ''
            if not options:
                return answer
            
            if q['type'] == "multiple":
                _op_list = multi_cut(options)
                for i in range(random.choices([2,3,4],weights=[0.1,0.5,0.4],k=1)[0]):
                    _choice = random.choice(_op_list)
                    _op_list.remove(_choice)
                    answer+=_choice[:1] # 取首字为答案，例如A或B
                # 对答案进行排序，否则会提交失败
                answer = "".join(sorted(answer))
            elif q['type'] == "single":
                answer = random.choice(options.split('\n'))[:1] # 取首字为答案，例如A或B
            # 判断题处理
            elif q['type'] == "judgement":
                # answer = self.tiku.jugement_select(_answer)
                answer = "true" if random.choice([True,False]) else "false"
            logger.info(f'随机选择 -> {answer}')
            return answer
        
        def multi_cut(answer:str) -> list[str]:
            cut_char = [',','，','|','\n','\r','\t','#','*','-','_','+','@','~','/','\\','.','&',' ']    # 多选答案切割符
            res = []
            for char in cut_char:
                res = answer.split(char)
                if len(res)>1:
                    return res
            return list(res)


        # 学习通这里根据参数差异能重定向至两个不同接口，需要定向至https://mooc1.chaoxing.com/mooc-ans/workHandle/handle
        _session = init_session()
        headers={
            "Host": "mooc1.chaoxing.com",
            "sec-ch-ua": "\"Microsoft Edge\";v=\"129\", \"Not=A?Brand\";v=\"8\", \"Chromium\";v=\"129\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "iframe",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5"
        }
        cookies = _session.cookies.get_dict()


        _url = "https://mooc1.chaoxing.com/mooc-ans/api/work"   
        _resp = requests.get(
            _url,
            headers=headers,
            cookies=cookies,
            verify=False,
            params = {
                "api": "1",
                "workId": job['jobid'].replace("work-",""),
                "jobid": job['jobid'],
                "originJobId": job['jobid'],
                "needRedirect": "true",
                "skipHeader": "true",
                "knowledgeid": str(job_info['knowledgeid']),
                'ktoken': job_info['ktoken'], 
                "cpi": job_info['cpi'],
                "ut": "s",
                "clazzId": course['clazzId'],
                "type": "",
                "enc": job['enc'],
                "mooc2": "1",
                "courseid": course['courseId']
            }
        )
        questions = decode_questions_info(_resp.text)   # 加载题目信息

        # 搜题
        for q in questions['questions']:
            res = self.tiku.query(q)
            answer = ''
            if not res:
                # 随机答题
                answer = random_answer(q['options'])
            else:
                # 根据响应结果选择答案
                options_list = multi_cut(q['options'])
                if q['type'] == "multiple":
                    # 多选处理
                    for _a in multi_cut(res):
                        for o in options_list:
                            if _a.upper() in o:     # 题库返回的答案可能包含选项，如A，B，C，全部转成大写与学习通一致
                                answer += o[:1]
                    # 对答案进行排序，否则会提交失败
                    answer = "".join(sorted(answer))
                elif q['type'] == 'judgement':
                    answer = 'true' if self.tiku.jugement_select(res) else 'false'
                else:
                    for o in options_list:
                        if res in o:
                            answer = o[:1]
                            break
                # 如果未能匹配，依然随机答题
                answer = answer if answer else random_answer(q['options'])
            # 填充答案
            q['answerField'][f'answer{q["id"]}'] = answer
            logger.info(f'{q["title"]} 填写答案为 {answer}')
        
        # 提交模式  现在与题库绑定
        questions['pyFlag'] = self.tiku.get_submit_params()  

        # 组建提交表单
        for q in questions["questions"]:
            questions.update({
                f'answer{q["id"]}':q['answerField'][f'answer{q["id"]}'],
                f'answertype{q["id"]}':q['answerField'][f'answertype{q["id"]}']
            })


        del questions["questions"]

        res = _session.post(
            'https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew',
            data=questions,
            headers= {
                "Host": "mooc1.chaoxing.com",
                "sec-ch-ua-platform": "\"Windows\"",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "sec-ch-ua": "\"Microsoft Edge\";v=\"129\", \"Not=A?Brand\";v=\"8\", \"Chromium\";v=\"129\"",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "sec-ch-ua-mobile": "?0",
                "Origin": "https://mooc1.chaoxing.com",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                #"Referer": "https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?courseId=246831735&workAnswerId=52680423&workId=37778125&api=1&knowledgeid=913820156&classId=107515845&oldWorkId=07647c38d8de4c648a9277c5bed7075a&jobid=work-07647c38d8de4c648a9277c5bed7075a&type=&isphone=false&submit=false&enc=1d826aab06d44a1198fc983ed3d243b1&cpi=338350298&mooc2=1&skipHeader=true&originJobId=work-07647c38d8de4c648a9277c5bed7075a",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5"
            }
        )
        if res.status_code == 200:
            res_json = res.json()
            if res_json['status']:
                logger.info(f'提交答题成功 -> {res_json["msg"]}')
            else:
                logger.error(f'提交答题失败 -> {res_json["msg"]}')
        else:
            logger.error(f"提交答题失败 -> {res.text}")

    def strdy_read(self, course: Dict, job: Dict, job_info: Dict) -> None:
        """
        完成阅读任务(仅完成任务点,不增加时长)
        
        Args:
            course: 课程信息
            job: 任务信息
            job_info: 任务详细信息
        """
        session = init_session()
        resp = session.get(
            url="https://mooc1.chaoxing.com/ananas/job/readv2",
            params={
                'jobid': job['jobid'],
                'knowledgeid': job_info['knowledgeid'],
                'jtoken': job['jtoken'],
                'courseid': course['courseId'],
                'clazzid': course['clazzId']
            }
        )
        
        if resp.status_code != 200:
            logger.error(f"阅读任务学习失败 -> [{resp.status_code}]{resp.text}")
        else:
            resp_json = resp.json()
            logger.info(f"阅读任务学习 -> {resp_json['msg']}")
