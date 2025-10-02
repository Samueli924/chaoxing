"""
Captcha API for Chaoxing

本模块用于通过CX验证码，提供包括验证码获取、识别、验证等接口。
使用了开源的验证码识别库[DdddOcr](https://github.com/sml2h3/ddddocr)

Author: skreon
Email: 1340554713@qq.com
Date: 2025-06-05
Version: 1.0.0
"""

__author__ = "skreon 1340554713@qq.com"
__version__ = "1.0.0"

from random import randint
from typing import Optional

from ddddocr import DdddOcr
from requests import session


def ocr_init() -> DdddOcr:
    """
    初始化OCR对象

    Returns: DdddOcr对象
    """
    return DdddOcr(show_ad=False)


class CxCaptcha:
    """
    CxCaptcha 类用于处理学习任务中出现的验证码

    该类提供了获取、识别和提交验证码的方法，使用 requests 库进行 HTTP 请求，
    并利用 DdddOcr 进行验证码识别。

    Attributes:
        host (str): 超星平台的主机地址。
        api (dict): 包含获取和提交验证码的 API 路径。
        user_agent (str): 用户代理字符串。
        cookies (str): 会话 cookies。
        s (requests.Session): 用于管理会话的请求对象。
    """

    host = 'https://mooc1.chaoxing.com'
    api = {
        'get': '/processVerifyPng.ac',
        'submit': '/html/processVerify.ac'
    }

    def __init__(self, user_agent: str, cookies: str, ocr: Optional[DdddOcr] = None):
        """
        初始化 CxCaptcha 实例。

        Args:
            user_agent (str): 用户代理字符串。
            cookies (str): 会话 cookies。
            ocr (DdddOcr, optional): 已初始化的 DdddOcr 对象。默认为 None。据DdddOcr官方说明，每次初始化和初始化后的首次识别速度都非常慢，所以推荐传入一个现成的DdddOcr对象实现复用。
        """

        self.user_agent = user_agent
        self.cookies = cookies
        self.s = session()
        self.s.headers.update({
            'User-Agent': self.user_agent,
            'Cookie': self.cookies,
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        })
        self.s.verify = False

        self.ocr = ocr if ocr else ocr_init()

    def getCaptcha(self) -> Optional[bytes]:
        """
        获取验证码图片。

        Returns:
            Optional[bytes]: 返回验证码图片的二进制数据，如果获取失败则返回 None。
        """
        api = self.host + self.api['get']
        random_t = randint(0, 2147483647)

        res = self.s.get(api, params={'t': random_t})
        if res.status_code == 200 and res.headers['Content-Type'] == 'image/png':
            return res.content
        else:
            # 提供的Cookies或UA存在问题，导致未能正常获取验证码内容
            return None

    def submitCaptcha(self, cap_token: str) -> bool:
        """
        提交验证码以完成验证。

        Args:
            cap_token (str): 验证码 token。

        Returns:
            bool: 如果提交成功并重定向，则返回 True；否则返回 False。
        """
        api = self.host + self.api['submit']
        params = {
            'ucode': cap_token,
            'app': 0
        }
        res = self.s.get(api, params=params)
        if res.status_code == 302:
            return True
        else:
            return False

    def recognition(self, img: bytes) -> str:
        """
        使用 DdddOcr 对验证码图片进行识别。

        Args:
            img (bytes): 验证码图片的二进制数据。

        Returns:
            str: 返回识别出的验证码字符串。
        """
        res = self.ocr.classification(img)
        return res

    def try_pass(self) -> bool:
        """
        尝试通过验证码验证流程。

        该方法会自动获取验证码、识别并提交。

        Returns:
            bool: 如果验证码成功通过验证，则返回 True；否则返回 False。
        """
        cap_img = self.getCaptcha()
        if not cap_img:
            return False
        cap_token = self.recognition(cap_img)
        return self.submitCaptcha(cap_token)
