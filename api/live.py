# -*- coding: utf-8 -*-
import json
import time
from urllib import parse

from api.logger import logger

from api.base import SessionManager
from api.config import GlobalConst as gc


class Live:
    def __init__(self, attachment: dict, defaults: dict, course_id: str):
        self.attachment = attachment
        self.defaults = defaults  # 包含用户ID、课程ID等信息
        self.course_id = course_id  # 课程ID
        self.name = self.attachment.get("property", {}).get("title", "未知直播")  # 直播名称
        self.headers = gc.HEADERS.copy()
        self.headers.update({
            "Referer": "https://mooc1.chaoxing.com/ananas/modules/live/index.html?v=2022-1214-1139"
        })

    def do_finish(self):
        """提交直播观看时长（核心方法）"""
        # 从直播信息中提取关键参数
        stream_name = self.attachment.get("property", {}).get("streamName")
        vdoid = self.attachment.get("property", {}).get("vdoid")
        user_id = self.defaults.get("userid")
        
        if not all([stream_name, vdoid, user_id]):
            logger.error("缺少直播必要参数，无法提交时长")
            return False
        
        # 构造时长记录请求URL（超星直播时长记录接口）
        url = f"https://zhibo.chaoxing.com/saveTimePc?streamName={stream_name}&vdoid={vdoid}&userId={user_id}&isStart=0&t={int(time.time()*1000)}&courseId={self.course_id}"
        
        # 发送请求记录时长
        session = SessionManager.get_session()
        try:
            response = session.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            logger.debug(f"直播时长提交响应: {response.text}")
            return response.text.strip() == "@success"  # 响应为@success表示提交成功
        except Exception as e:
            logger.error(f"提交直播时长失败: {str(e)}")
            return False

    def get_status(self) -> dict|None:
        """获取直播状态（总时长等信息）"""
        live_id = self.attachment.get("property", {}).get("liveId")
        user_id = self.defaults.get("userid")
        clazz_id = self.defaults.get("clazzId")
        knowledge_id = self.defaults.get("knowledgeid")
        
        if not all([live_id, user_id, clazz_id, knowledge_id]):
            logger.error("缺少直播状态查询必要参数")
            return None
        
        # 构造直播状态请求URL
        status_url = f"https://mooc1.chaoxing.com/ananas/live/liveinfo?liveid={live_id}&userid={user_id}&clazzid={clazz_id}&knowledgeid={knowledge_id}&courseid={self.course_id}&jobid={self.attachment.get('property', {}).get('_jobid', '')}&ut=s"
        
        # 发送请求并解析状态（包含总时长）
        session = SessionManager.get_session()
        try:
            response = session.get(status_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return json.loads(response.text)  # 返回包含总时长的状态字典
        except Exception as e:
            logger.error(f"获取直播状态失败: {str(e)}")
            return None
