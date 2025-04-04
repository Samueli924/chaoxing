import configparser
import requests
from pathlib import Path
import json
from api.logger import logger
import random
from urllib3 import disable_warnings,exceptions
from openai import OpenAI
import httpx
from re import sub
import time
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
    DISABLE = False     # 停用标志
    SUBMIT = False      # 提交标志
    COVER_RATE = 0.8    # 覆盖率

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
    def token(self,value):
        self._token = value

    def init_tiku(self):
        # 仅用于题库初始化, 应该在题库载入后作初始化调用, 随后才可以使用题库
        # 尝试根据配置文件设置提交模式
        if not self._conf:
            self.config_set(self._get_conf())
        if not self.DISABLE:
            # 设置提交模式
            self.SUBMIT = True if self._conf['submit'] == 'true' else False
            self.COVER_RATE = self._conf['cover_rate']
            # 调用自定义题库初始化
            self._init_tiku()
        
    def _init_tiku(self):
        # 仅用于题库初始化, 例如配置token, 交由自定义题库完成
        pass

    def config_set(self,config):
        self._conf = config

    def _get_conf(self):
        """
        从默认配置文件查询配置, 如果未能查到, 停用题库
        """
        try:
            config = configparser.ConfigParser()
            config.read(self.CONFIG_PATH, encoding="utf8")
            return config['tiku']
        except (KeyError, FileNotFoundError):
            logger.info("未找到tiku配置, 已忽略题库功能")
            self.DISABLE = True
            return None

    def query(self,q_info:dict):
        if self.DISABLE:
            return None

        # 预处理, 去除【单选题】这样与标题无关的字段
        # 此处需要改进！！！
        logger.debug(f"原始标题：{q_info['title']}")
        q_info['title'] = sub(r'^\d+', '', q_info['title'])
        q_info['title'] = sub(r'^(?:【.*?】)+', '', q_info['title'])
        q_info['title'] = sub(r'（\d+\.\d+分）$', '', q_info['title'])
        logger.debug(f"处理后标题：{q_info['title']}")

        # 先过缓存
        cache_dao = CacheDAO()
        answer = cache_dao.getCache(q_info['title'])
        if answer:
            logger.info(f"从缓存中获取答案：{q_info['title']} -> {answer}")
            return answer.strip()
        else:
            answer = self._query(q_info)
            if answer:
                answer = answer.strip()
                cache_dao.addCache(q_info['title'], answer)
                logger.info(f"从{self.name}获取答案：{q_info['title']} -> {answer}")
                return answer
            logger.error(f"从{self.name}获取答案失败：{q_info['title']}")
        return None
    
    def _query(self,q_info:dict):
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
            cls_name = self._conf['provider']
            if not cls_name:
                raise KeyError
        except KeyError:
            self.DISABLE = True
            logger.error("未找到题库配置, 已忽略题库功能")
            return self
        new_cls = globals()[cls_name]()
        new_cls.config_set(self._conf)
        return new_cls
    
    def jugement_select(self,answer:str) -> bool:
        """
        这是一个专用的方法, 要求配置维护两个选项列表, 一份用于正确选项, 一份用于错误选项, 以应对题库对判断题答案响应的各种可能的情况
        它的作用是将获取到的答案answer与可能的选项列对比并返回对应的布尔值
        """
        if self.DISABLE:
            return False
        true_list = self._conf['true_list'].split(',')
        false_list = self._conf['false_list'].split(',')
        # 对响应的答案作处理
        answer = answer.strip()
        if answer in true_list:
            return True
        elif answer in false_list:
            return False
        else:
            # 无法判断, 随机选择
            logger.error(f'无法判断答案 -> {answer} 对应的是正确还是错误, 请自行判断并加入配置文件重启脚本, 本次将会随机选择选项')
            return random.choice([True,False])
    
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
        self.name = '言溪题库'
        self.api = 'https://tk.enncy.cn/query'
        self._token = None
        self._token_index = 0   # token队列计数器
        self._times = 100   # 查询次数剩余, 初始化为100, 查询后校对修正

    def _query(self,q_info:dict):
        res = requests.get(
            self.api,
            params={
                'question':q_info['title'],
                'token':self._token
            },
            verify=False
        )
        if res.status_code == 200:
            res_json = res.json()
            if not res_json['code']:
                # 如果是因为TOKEN次数到期, 则更换token
                if self._times == 0 or '次数不足' in res_json['data']['answer']:
                    logger.info(f'TOKEN查询次数不足, 将会更换并重新搜题')
                    self._token_index += 1
                    self.load_token()
                    # 重新查询
                    return self._query(q_info)
                logger.error(f'{self.name}查询失败:\n\t剩余查询数{res_json["data"].get("times",f"{self._times}(仅参考)")}:\n\t消息:{res_json["message"]}')
                return None
            self._times = res_json["data"].get("times",self._times)
            return res_json['data']['answer'].strip()
        else:
            logger.error(f'{self.name}查询失败:\n{res.text}')
        return None
    
    def load_token(self): 
        token_list = self._conf['tokens'].split(',')
        if self._token_index == len(token_list):
            # TOKEN 用完
            logger.error('TOKEN用完, 请自行更换再重启脚本')
            raise Exception(f'{self.name} TOKEN 已用完, 请更换')
        self._token = token_list[self._token_index]

    def _init_tiku(self):
        self.load_token()

class TikuLike(Tiku):
    # Like知识库实现
    def __init__(self) -> None:
        super().__init__()
        self.name = 'Like知识库'
        self.ver = '1.0.8' #对应官网API版本
        self.query_api = 'https://api.datam.site/search'
        self.balance_api = 'https://api.datam.site/balance'
        self.homepage = 'https://www.datam.site'
        self._model = None
        self._token = None
        self._times = -1
        self._search = False
        self._count = 0

    def _query(self,q_info:dict):
        q_info_map = {"single":"【单选题】","multiple":"【多选题】","completion":"【填空题】","judgement":"【判断题】"}
        api_params_map = {0:"others",1:"choose",2:"fills",3:"judge"}
        q_info_prefix = q_info_map.get(q_info['type'],"【其他类型题目】")
        options = ', '.join(q_info['options']) if isinstance(q_info['options'], list) else q_info['options']
        question = "{}{}\n{}".format(q_info_prefix,q_info['title'],options)
        ret = ""
        ans = ""
        res = requests.post(
            self.query_api,
            json={
                'query': question,
                'token': self._token,
                'model': self._model if self._model else '',
                'search': self._search
            },
            verify=False
        )

        if res.status_code == 200:
            res_json = res.json()
            q_type = res_json['data'].get('type',0)
            params = api_params_map.get(q_type,"")
            ans = res_json['data'].get(params,"")
            if q_type == 3:
                ans = "正确" if ans ==1 else "错误"
        else:
            logger.error(f'{self.name}查询失败:\n{res.text}')
            return None

        ret += str(ans)

        self._times -= 1

        #10次查询后更新实际次数
        self._count = (self._count+1) % 10

        if self._count == 0:
            self.update_times()
        
        return ret
    
    def update_times(self):
        res = requests.post(
            self.balance_api,
            json={
                'token': self._token,
            },
            verify=False
        )
        if res.status_code == 200:
            res_json = res.json()
            self._times = res_json["data"].get("balance",self._times)
            logger.info("当前LIKE知识库Token剩余查询次数为: {}".format(str(self._times)))
        else:
            logger.error('TOKEN出现错误，请检查后再试')

    def load_token(self): 
        token = self._conf['tokens'].split(',')[-1] if ',' in self._conf['tokens'] else self._conf['tokens']
        self._token = token

    def load_config(self):
        var_params = {"likeapi_search":self._search,"likeapi_model":self._model}
        config_params = {"likeapi_search":False, "likeapi_model":None}

        for k,v in config_params.items():
            if k in self._conf:
                var_params[k] = self._conf[k]
            else:
                var_params[k] = v

    def _init_tiku(self):
        self.load_token()
        self.load_config()
        self.update_times()

class TikuAdapter(Tiku):
    # TikuAdapter题库实现 https://github.com/DokiDoki1103/tikuAdapter
    def __init__(self) -> None:
        super().__init__()
        self.name = 'TikuAdapter题库'
        self.api = ''

    def _query(self, q_info: dict):
        # 判断题目类型
        if q_info['type'] == "single":
            type = 0
        elif q_info['type'] == 'multiple':
            type = 1
        elif q_info['type'] == 'completion':
            type = 2
        elif q_info['type'] == 'judgement':
            type = 3
        else:
            type = 4

        options = q_info['options']
        res = requests.post(
            self.api,
            json={
                'question': q_info['title'],
                'options': [sub(r'^[A-Za-z]\.?、?\s?', '', option) for option in options.split('\n')],
                'type': type
            },
            verify=False
        )
        if res.status_code == 200:
            res_json = res.json()
            # if bool(res_json['plat']):
            # plat无论搜没搜到答案都返回0
            # 这个参数是tikuadapter用来设定自定义的平台类型
            if not len(res_json['answer']['bestAnswer']):
                logger.error("查询失败, 返回：" + res.text)
                return None
            sep = "\n"
            return sep.join(res_json['answer']['bestAnswer']).strip()
        # else:
        #   logger.error(f'{self.name}查询失败:\n{res.text}')
        return None

    def _init_tiku(self):
        # self.load_token()
        self.api = self._conf['url']

class AI(Tiku):
    # AI大模型答题实现
    def __init__(self) -> None:
        super().__init__()
        self.name = 'AI大模型答题'
        self.last_request_time = None

    def _query(self, q_info: dict):
        if self.http_proxy:
            proxy = self.http_proxy
            httpx_client = httpx.Client(proxy=proxy)
            client = OpenAI(http_client=httpx_client, base_url = self.endpoint,api_key = self.key)
        else:
            client = OpenAI(base_url = self.endpoint,api_key = self.key)
        # 判断题目类型
        if q_info['type'] == "single":
            completion = client.chat.completions.create(
                model = self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "本题为单选题，你只能选择一个选项，请根据题目和选项回答问题，以json格式输出正确的选项内容，特别注意回答的内容需要去除选项内容前的字母，示例回答：{\"Answer\": [\"答案\"]}。除此之外不要输出任何多余的内容。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料"
                    },
                    {
                        "role": "user",
                        "content": f"题目：{q_info['title']}\n选项：{q_info['options']}"
                    }
                ]
            )
        elif q_info['type'] == 'multiple':
            completion = client.chat.completions.create(
                model = self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "本题为多选题，你必须选择两个或以上选项，请根据题目和选项回答问题，以json格式输出正确的选项内容，特别注意回答的内容需要去除选项内容前的字母，示例回答：{\"Answer\": [\"答案1\",\n\"答案2\",\n\"答案3\"]}。除此之外不要输出任何多余的内容。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料"
                    },
                    {
                        "role": "user",
                        "content": f"题目：{q_info['title']}\n选项：{q_info['options']}"
                    }
                ]
            )
        elif q_info['type'] == 'completion':
            completion = client.chat.completions.create(
                model = self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "本题为填空题，你必须根据语境和相关知识填入合适的内容，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"答案\"]}。除此之外不要输出任何多余的内容。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料"
                    },
                    {
                        "role": "user",
                        "content": f"题目：{q_info['title']}"
                    }
                ]
            )
        elif q_info['type'] == 'judgement':
            completion = client.chat.completions.create(
                model = self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "本题为判断题，你只能回答正确或者错误，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"正确\"]}。除此之外不要输出任何多余的内容。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料"
                    },
                    {
                        "role": "user",
                        "content": f"题目：{q_info['title']}"
                    }
                ]
            )
        else:
            completion = client.chat.completions.create(
                model = self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "本题为简答题，你必须根据语境和相关知识填入合适的内容，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"这是我的答案\"]}。除此之外不要输出任何多余的内容。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料"
                    },
                    {
                        "role": "user",
                        "content": f"题目：{q_info['title']}"
                    }
                ]
            )

        try:
            if self.last_request_time:
                interval_time = time.time() - self.last_request_time
                if interval_time < self.min_interval_seconds:
                    sleep_time = self.min_interval_seconds - interval_time
                    logger.debug(f"API请求间隔过短, 等待 {sleep_time} 秒")
                    time.sleep(sleep_time)
            self.last_request_time = time.time()
            response = json.loads(completion.choices[0].message.content)
            sep = "\n"
            return sep.join(response['Answer']).strip()
        except:
            logger.error("无法解析大模型输出内容")
            return None

    def _init_tiku(self):
        self.endpoint = self._conf['endpoint']
        self.key = self._conf['key']
        self.model = self._conf['model']
        self.http_proxy = self._conf['http_proxy']
        self.min_interval_seconds = int(self._conf['min_interval_seconds'])
