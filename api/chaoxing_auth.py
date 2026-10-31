import base64
import re
import time

import requests

from api.cipher import AESCipher
from api.config import GlobalConst as gc


class ChaoXingQRManager:
    """超星扫码认证与账号密码登录管理服务."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self.cipher = AESCipher()

    def create_session(self) -> dict:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        login_url = "https://passport2.chaoxing.com/login"
        try:
            resp = session.get(login_url, timeout=10)
            if resp.status_code != 200:
                return {"status": False, "msg": f"拉取登录页失败: HTTP {resp.status_code}"}

            u_match = re.search(r'value="([^"]+)"\s+id="uuid"|id="uuid"\s+value="([^"]+)"', resp.text)
            e_match = re.search(r'value="([^"]+)"\s+id="enc"|id="enc"\s+value="([^"]+)"', resp.text)
            if not u_match or not e_match:
                return {"status": False, "msg": "解析二维码参数失败"}

            uuid = u_match.group(1) or u_match.group(2)
            enc = e_match.group(1) or e_match.group(2)

            qr_img_url = f"https://passport2.chaoxing.com/createqr?uuid={uuid}&fid=-1"
            img_resp = session.get(qr_img_url, timeout=10)
            if img_resp.status_code != 200 or not img_resp.content:
                return {"status": False, "msg": "获取二维码图片失败"}

            base64_data = base64.b64encode(img_resp.content).decode("utf-8")
            data_uri = f"data:image/png;base64,{base64_data}"

            self._sessions[uuid] = {
                "uuid": uuid,
                "enc": enc,
                "session": session,
                "created_at": time.time(),
            }
            return {
                "status": True,
                "session_id": uuid,
                "qr_url": data_uri,
            }
        except Exception as e:
            return {"status": False, "msg": str(e)}

    def check_status(self, session_id: str) -> dict:
        sess_data = self._sessions.get(session_id)
        if not sess_data:
            return {"status": "EXPIRED"}

        if time.time() - sess_data["created_at"] > 300:
            self._sessions.pop(session_id, None)
            return {"status": "EXPIRED"}

        session = sess_data["session"]
        url = "https://passport2.chaoxing.com/getauthstatus/v2"
        payload = {
            "enc": sess_data["enc"],
            "uuid": sess_data["uuid"],
            "doubleFactorLogin": 0,
            "forbidotherlogin": 0,
        }
        try:
            resp = session.post(url, data=payload, timeout=8)
            data = resp.json()
            if data.get("status") is True:
                cookies_dict = {}
                for k, v in session.cookies.items():
                    cookies_dict[k] = v
                for k, v in resp.cookies.items():
                    cookies_dict[k] = v
                cookie_str = "; ".join(f"{k}={v}" for k, v in cookies_dict.items())
                uid = cookies_dict.get("_uid") or cookies_dict.get("UID") or session_id
                self._sessions.pop(session_id, None)
                return {
                    "status": "SUCCESS",
                    "cookies": cookie_str,
                    "uid": str(uid),
                }

            status_type = str(data.get("type", ""))
            if status_type == "4":
                return {"status": "CONFIRMED"}
            elif status_type == "2":
                self._sessions.pop(session_id, None)
                return {"status": "EXPIRED"}
            elif status_type == "6":
                self._sessions.pop(session_id, None)
                return {"status": "CANCELLED"}
            else:
                return {"status": "PENDING"}
        except Exception as e:
            return {"status": "ERROR", "msg": str(e)}

    def login_with_password(self, username: str, password: str) -> dict:
        session = requests.Session()
        session.headers.update(gc.HEADERS)
        url = "https://passport2.chaoxing.com/fanyalogin"
        data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(username),
            "password": self.cipher.encrypt(password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": True,
            "forbidotherlogin": 0,
            "validate": "",
            "doubleFactorLogin": 0,
            "independentId": 0,
        }
        try:
            resp = session.post(url, headers=gc.HEADERS, data=data, timeout=5)
            res_json = resp.json()
            if res_json.get("status") is True:
                cookie_str = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
                uid = session.cookies.get("_uid") or session.cookies.get("UID") or username
                return {
                    "status": "SUCCESS",
                    "cookies": cookie_str,
                    "uid": str(uid),
                }
            return {
                "status": "FAILED",
                "msg": str(res_json.get("msg2", "认证失败")),
            }
        except Exception as e:
            return {"status": "FAILED", "msg": str(e)}
