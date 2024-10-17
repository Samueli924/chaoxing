import configparser
import requests
from pathlib import Path
from typing import Optional
import json
from api.logger import logger

class CacheDAO:
    """
    @Author: SocialSisterYi
    @Reference: https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy
    """
    def __init__(self, file: str = "cache.json"):
        self.cacheFile = Path(file)
        if not self.cacheFile.is_file():
            self.cacheFile.open("w").write("{}")
        self.fp = self.cacheFile.open("r+", encoding="utf8")

    def getCache(self, question: str) -> Optional[str]:
        self.fp.seek(0)
        data = json.load(self.fp)
        if isinstance(data, dict):
            return data.get(question)

    def addCache(self, question: str, answer: str):
        self.fp.seek(0)
        data: dict = json.load(self.fp)
        data[question] = answer
        self.fp.seek(0)
        json.dump(data, self.fp, ensure_ascii=False, indent=4)


class Tiku:
    CONFIG_PATH = "config.ini"

    def __init__(self) -> None:
        self._name = None
        self._api = None
        self._conf = None
        self._token = None
    @property
    def name(self):
        return self._name
    
    @name.setter
    def name(self, value):
        self._name = value

    @property
    def api(self):
        return self._api
    
    @api.setter
    def api(self, value):
        self._api = value

    @property
    def token(self):
        return self._token

    @token.setter
    def token(self,value):
        self._token = value

    def load_token(self): 
        self.token=self._conf['token']

    def config_set(self,config:configparser.ConfigParser):
        self._conf = config


    def __get_conf(self):
        config = configparser.ConfigParser()
        config.read(self.CONFIG_PATH, encoding="utf8")
        return config['tiku']
    
    def query(self,q_info:dict) -> str|None:
        # 预处理，去除【单选题】这样与标题无关的字段
        q_info['title'] = q_info['title'][6:]   # 暂时直接用裁切解决

        # 先过缓存
        cache_dao = CacheDAO()
        answer = cache_dao.getCache(q_info['title'])
        if answer:
            logger.info(f"从缓存中获取答案：{q_info['title']} -> {answer}")
            return answer
        else:
            answer = self._query(q_info)
            if answer:
                cache_dao.addCache(q_info['title'], answer)
                logger.info(f"从{self.name}获取答案：{q_info['title']} -> {answer}")
                return answer
            logger.error(f"从{self.name}获取答案失败：{q_info['title']}")
        return None
    def _query(self,q_info:dict):
        pass

    def get_tiku_from_config(self):
        if not self._conf:
            self.config_set(self.__get_conf())
        cls_name = self._conf['provider']
        new_cls = globals()[cls_name]()
        new_cls.config_set(self._conf)
        return new_cls

# 按照以下模板实现更多题库

class TikuYanxi(Tiku):
    # 言溪题库实现
    def __init__(self) -> None:
        super().__init__()
        self.name = '言溪题库'
        self.api = 'https://tk.enncy.cn/query'
        self._token = None

    def _query(self,q_info:dict):
        res = requests.get(
            self.api,
            params={
                'question':q_info['title'],
                'token':self.token
            },
            verify=False
        )
        if res.status_code == 200:
            res_json = res.json()
            if not res_json['code']:
                logger.error(f'{self.name}查询失败:\n剩余查询数{res_json["data"].get("times","未知")}:\n消息:{res_json["message"]}')
                return None
            return res_json['data']['answer']
        else:
            logger.error(f'{self.name}查询失败:\n{res.text}')
        return None

    

