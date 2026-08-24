import time
import random
from api.logger import logger


class SignIn:
    def __init__(self, session, uid, fid):
        self.session = session
        self.uid = uid
        self.fid = fid

    def get_active_list(self, course_id, class_id):
        url = f"https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist"
        params = {"fid": "0", "courseId": course_id, "classId": class_id, "_": int(time.time() * 1000)}
        resp = self.session.get(url, params=params)
        if resp.status_code != 200:
            return None
        return resp.json()

    def get_active_info(self, active_id):
        url = f"https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo"
        params = {"activeId": active_id}
        resp = self.session.get(url, params=params)
        if resp.status_code != 200:
            return None
        return resp.json().get("data")

    def pre_sign(self, active_id, course_id, class_id):
        url = "https://mobilelearn.chaoxing.com/newsign/preSign"
        params = {
            "courseId": course_id, "classId": class_id, "activePrimaryId": active_id,
            "general": "1", "sys": "1", "ls": "1", "appType": "15", "uid": self.uid, "ut": "s"
        }
        self.session.get(url, params=params)
        time.sleep(0.5)

    def general_sign(self, active_id, name):
        url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax"
        params = {
            "activeId": active_id, "uid": self.uid, "clientip": "",
            "latitude": "-1", "longitude": "-1", "appType": "15",
            "fid": self.fid, "name": name
        }
        resp = self.session.get(url, params=params)
        return resp.text

    def location_sign(self, active_id, name, lat, lon, address):
        url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax"
        params = {
            "activeId": active_id, "uid": self.uid, "clientip": "",
            "latitude": lat, "longitude": lon, "appType": "15",
            "fid": self.fid, "name": name, "address": address, "ifTiJiao": "1"
        }
        resp = self.session.get(url, params=params)
        return resp.text

    def photo_sign(self, active_id, name, object_id):
        url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax"
        params = {
            "activeId": active_id, "uid": self.uid, "clientip": "",
            "latitude": "-1", "longitude": "-1", "appType": "15",
            "fid": self.fid, "objectId": object_id, "name": name
        }
        resp = self.session.get(url, params=params)
        return resp.text

    def scan_courses(self, courses, sign_config):
        logger.info("正在查询有效签到活动...")
        for course in courses:
            try:
                data = self.get_active_list(course["courseId"], course["clazzId"])
                if not data or not data.get("data"):
                    continue
                active_list = data["data"].get("activeList", [])
                if not active_list:
                    continue
                act = active_list[0]
                other_id = int(act.get("otherId", -1))
                if other_id < 0 or other_id > 5 or act.get("status") != 1:
                    continue
                start_time = act.get("startTime", 0)
                if (time.time() * 1000 - start_time) / 1000 > 7200:
                    continue
                name = act.get("nameOne", "签到")
                active_id = str(act["id"])
                logger.info(f"检测到签到: {name} ({course['title']})")
                return self._handle_sign(active_id, name, other_id, course, sign_config)
            except Exception as e:
                logger.debug(f"查询课程 {course.get('title')} 签到失败: {e}")
        return None

    def _handle_sign(self, active_id, name, sign_type, course, config):
        info = self.get_active_info(active_id)
        if not info:
            logger.error(f"获取签到信息失败")
            return None

        self.pre_sign(active_id, course["courseId"], course["clazzId"])

        if sign_type == 0:
            if info.get("ifphoto") == 1:
                return self._do_photo(active_id, name, info, config)
            return self._do_general(active_id, name)
        elif sign_type == 2:
            logger.warning("二维码签到需手动扫码，跳过")
            return None
        elif sign_type == 3:
            return self._do_gesture(active_id, name, info)
        elif sign_type == 4:
            return self._do_location(active_id, name, info, config)
        elif sign_type == 5:
            return self._do_code(active_id, name, info)
        return None

    def _do_general(self, active_id, name):
        result = self.general_sign(active_id, name)
        msg = "签到成功" if result == "success" else f"签到失败: {result}"
        logger.info(f"[普通] {msg}")
        return msg

    def _do_gesture(self, active_id, name):
        result = self.general_sign(active_id, name)
        msg = "签到成功" if result == "success" else f"签到失败: {result}"
        logger.info(f"[手势] {msg}")
        return msg

    def _do_location(self, active_id, name, info, config):
        lat = config.get("latitude", "30.1234")
        lon = config.get("longitude", "120.5678")
        address = config.get("address", "学校")
        result = self.location_sign(active_id, name, lat, lon, address)
        msg = "签到成功" if result == "success" else f"签到失败: {result}"
        logger.info(f"[位置] {msg}")
        return msg

    def _do_photo(self, active_id, name, info, config):
        object_id = config.get("photo_object_id", "")
        if not object_id:
            logger.warning("拍照签到需要准备照片，请上传到超星云盘命名为 0.jpg")
            return None
        result = self.photo_sign(active_id, name, object_id)
        msg = "签到成功" if result == "success" else f"签到失败: {result}"
        logger.info(f"[拍照] {msg}")
        return msg

    def _do_code(self, active_id, name, info):
        code = input("请输入签到码: ").strip()
        if not code:
            return None
        result = self.general_sign(active_id, name + f"&code={code}")
        msg = "签到成功" if result == "success" else f"签到失败: {result}"
        logger.info(f"[签到码] {msg}")
        return msg

    def monitor(self, courses, sign_config, interval=30):
        logger.info(f"签到监控已启动，每 {interval} 秒检查一次...")
        try:
            while True:
                result = self.scan_courses(courses, sign_config)
                if result:
                    logger.info(f"签到结果: {result}")
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("签到监控已停止")