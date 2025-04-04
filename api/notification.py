
import configparser
import requests
from api.logger import logger

#仿制answer.py写的外部通知

class Notification:

    CONFIG_PATH = "config.ini"
    DISABLE = False

    def __init__(self):
        self._name = None
        self._conf = None

    def config_set(self, config):
        self._conf = config

    def _init_notification(self):
        # 仅用于外部通知初始化, 例如配置token, 则交由具体外部通知完成
        pass

    def _get_conf(self):
        """
            从默认配置文件查询配置, 如果未能查到, 停用外部通知功能
        """
        try:
            config = configparser.ConfigParser()
            config.read(self.CONFIG_PATH, encoding="utf8")
            return config['notification']
        except (KeyError, FileNotFoundError):
            logger.info("未找到notification配置, 已忽略外部通知功能")
            self.DISABLE = True
            return None

    def get_notification_from_config(self):
        if not self._conf:
            # 尝试从默认配置文件加载
            self.config_set(self._get_conf())
        if self.DISABLE:
            return self
        try:
            cls_name = self._conf['provider']
            if not cls_name:
                raise KeyError
        except KeyError:
            self.DISABLE = True
            logger.info("未找到外部通知配置, 已忽略外部通知功能")
            return self
        new_cls = globals()[cls_name]()
        new_cls.config_set(self._conf)
        return new_cls
    def init_notification(self):
        if not self._conf:
            self.config_set(self._get_conf())
        if not self.DISABLE:
            # 调用自定义外部通知初始化
            self._init_notification()
    def _send(self,*args, **kwargs):
        pass
    def send(self, *args, **kwargs):
        if not self.DISABLE:
            self._send(*args, **kwargs)
        return None


class ServerChan(Notification):
    def __init__(self):
        super().__init__()
        self.name = 'ServerChan'
        self.url = ''

    def _send(self, text):
        params = {
            # serverChan有两个版本，一版本参数是text，一个是desp，干脆直接这么写，不区分
            'text': text,
            'desp': text,
        }
        headers = {
            'Content-Type': 'application/json;charset=utf-8'
        }
        response = requests.post(self.url, json=params, headers=headers)
        result = response.json()
        if response.status_code != 200:
            logger.error(f"Server酱发送通知失败{result}")
        else:
            logger.info("Server酱发送通知成功")
        return None

    def _init_notification(self):
        self.url = self._conf['url']

class Qmsg(Notification):
    def __init__(self):
        super().__init__()
        self.name = 'Qmsg'
        self.url = ''

    def _send(self, msg):
        params = {
            'msg': msg,
        }
        headers = {
            'Content-Type': 'application/json;charset=utf-8'
        }
        response = requests.post(self.url, params=params, headers=headers)
        result = response.json()
        if response.status_code != 200:
            logger.error(f"Qmsg酱发送通知失败{result}")
        else:
            logger.info("Qmsg酱发送通知成功")
        return None

    def _init_notification(self):
        self.url = self._conf['url']