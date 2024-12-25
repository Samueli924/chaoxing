import configparser
import requests
from pathlib import Path
import json
from api.logger import logger
import random
from urllib3 import disable_warnings, exceptions

# 关闭警告
disable_warnings(exceptions.InsecureRequestWarning)


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

    def getCache(self, question: str):
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
    CONFIG_PATH = "config.ini"  # 默认配置文件路径
    DISABLE = False  # 停用标志
    SUBMIT = False  # 提交标志

    def __init__(self) -> None:
        self._name = None
        self._api = None
        self._conf = None

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
    def token(self, value):
        self._token = value

    def init_tiku(self):
        # 仅用于题库初始化, 应该在题库载入后作初始化调用, 随后才可以使用题库
        # 尝试根据配置文件设置提交模式
        if not self._conf:
            self.config_set(self._get_conf())
        if not self.DISABLE:
            # 设置提交模式
            self.SUBMIT = True if self._conf["submit"] == "true" else False
            # 调用自定义题库初始化
            self._init_tiku()

    def _init_tiku(self):
        # 仅用于题库初始化, 例如配置token, 交由自定义题库完成
        pass

    def config_set(self, config):
        self._conf = config

    def _get_conf(self):
        """
        从默认配置文件查询配置, 如果未能查到, 停用题库
        """
        try:
            config = configparser.ConfigParser()
            config.read(self.CONFIG_PATH, encoding="utf8")
            return config["tiku"]
        except KeyError or FileNotFoundError:
            logger.info("未找到tiku配置, 已忽略题库功能")
            self.DISABLE = True
            return None

    def query(self, q_info: dict):
        if self.DISABLE:
            return None

        # 预处理, 去除【单选题】这样与标题无关的字段
        # 此处需要改进！！！
        logger.debug(f"原始标题: {q_info['title']}")
        q_info["title"] = q_info["title"][6:]  # 暂时直接用裁切解决
        logger.debug(f"处理后标题: {q_info['title']}")

        # 先过缓存
        cache_dao = CacheDAO()
        answer = cache_dao.getCache(q_info["title"])
        if answer:
            logger.info(f"从缓存中获取答案: {q_info['title']} -> {answer}")
            return answer.strip()
        else:
            answer = self._query(q_info)
            if answer:
                answer = answer.strip()
                cache_dao.addCache(q_info["title"], answer)
                logger.info(f"从{self.name}获取答案: {q_info['title']} -> {answer}")
                return answer
            logger.error(f"从{self.name}获取答案失败: {q_info['title']}")
        return None

    def _query(self, q_info: dict):
        """
        查询接口, 交由自定义题库实现
        """
        pass

    def get_tiku_from_config(self):
        """
        从配置文件加载题库, 这个配置可以是用户提供, 可以是默认配置文件
        """
        if not self._conf:
            # 尝试从默认配置文件加载
            self.config_set(self._get_conf())
        if self.DISABLE:
            return self
        try:
            cls_name = self._conf["provider"]
            if not cls_name:
                raise KeyError
        except KeyError:
            logger.error("未找到题库配置, 已忽略题库功能")
            return self
        new_cls = globals()[cls_name]()
        new_cls.config_set(self._conf)
        return new_cls

    def jugement_select(self, answer: str) -> bool:
        """
        这是一个专用的方法, 要求配置维护两个选项列表, 一份用于正确选项, 一份用于错误选项, 以应对题库对判断题答案响应的各种可能的情况
        它的作用是将获取到的答案answer与可能的选项列对比并返回对应的布尔值
        """
        if self.DISABLE:
            return False
        true_list = self._conf["true_list"].split(",")
        false_list = self._conf["false_list"].split(",")
        # 对响应的答案作处理
        answer = answer.strip()
        if answer in true_list:
            return True
        elif answer in false_list:
            return False
        else:
            # 无法判断, 随机选择
            logger.error(
                f"无法判断答案 -> {answer} 对应的是正确还是错误, 请自行判断并加入配置文件重启脚本, 本次将会随机选择选项"
            )
            return random.choice([True, False])

    def get_submit_params(self):
        """
        这是一个专用方法, 用于根据当前设置的提交模式, 响应对应的答题提交API中的pyFlag值
        """
        # 留空直接提交, 1保存但不提交
        if self.SUBMIT:
            return ""
        else:
            return "1"


# 按照以下模板实现更多题库


class TikuYanxi(Tiku):
    # 言溪题库实现
    def __init__(self) -> None:
        super().__init__()
        self.name = "言溪题库"
        self.api = "https://tk.enncy.cn/query"
        self._token = None
        self._token_index = 0  # token队列计数器
        self._times = 100  # 查询次数剩余, 初始化为100, 查询后校对修正

    def _query(self, q_info: dict):
        res = requests.get(
            self.api,
            params={"question": q_info["title"], "token": self._token},
            verify=False,
        )
        if res.status_code == 200:
            res_json = res.json()
            if not res_json["code"]:
                # 如果是因为TOKEN次数到期, 则更换token
                if self._times == 0 or "次数不足" in res_json["data"]["answer"]:
                    logger.info("TOKEN查询次数不足, 将会更换并重新搜题")
                    self._token_index += 1
                    self.load_token()
                    # 重新查询
                    return self._query(q_info)
                logger.error(
                    f'{self.name}查询失败:\n\t剩余查询数{res_json["data"].get("times",f"{self._times}(仅参考)")}:\n\t消息:{res_json["message"]}'
                )
                return None
            self._times = res_json["data"].get("times", self._times)
            return res_json["data"]["answer"].strip()
        else:
            logger.error(f"{self.name}查询失败:\n{res.text}")
        return None

    def load_token(self):
        token_list = self._conf["tokens"].split(",")
        if self._token_index == len(token_list):
            # TOKEN 用完
            logger.error("TOKEN用完, 请自行更换再重启脚本")
            raise Exception(f"{self.name} TOKEN 已用完, 请更换")
        self._token = token_list[self._token_index]

    def _init_tiku(self):
        self.load_token()


class TikuAdapter(Tiku):
    # TikuAdapter题库实现 https://github.com/DokiDoki1103/tikuAdapter
    def __init__(self) -> None:
        super().__init__()
        self.name = "TikuAdapter题库"
        self.api = ""

    def _query(self, q_info: dict):
        # 判断题目类型
        if q_info["type"] == "single":
            type = 0
        elif q_info["type"] == "multiple":
            type = 1
        elif q_info["type"] == "completion":
            type = 2
        elif q_info["type"] == "judgement":
            type = 3
        else:
            type = 4

        options = q_info["options"]
        res = requests.post(
            self.api,
            json={
                "question": q_info["title"],
                "options": options.split("\n"),
                "type": type,
            },
            verify=False,
        )
        if res.status_code == 200:
            res_json = res.json()
            if bool(res_json["plat"]):
                logger.error("查询失败, 返回: " + res.text)
                return None
            sep = "\n"
            return sep.join(res_json["answer"]["allAnswer"][0]).strip()
            # else: # https://github.com/Samueli924/chaoxing/blame/3369cae6e55a44d6d284e17bccefb56d1606f5bb/api/answer.py#L269
            # logger.error(f"{self.name}查询失败:\n{res.text}") # Unreachable code
        return None

    def _init_tiku(self):
        # self.load_token()
        self.api = self._conf["url"]
