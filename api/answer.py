import configparser
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from re import sub
from typing import Any, Optional

import httpx
import requests

from api.answer_check import TRUE_WORDS, FALSE_WORDS, check_answer
from api.config import data_path
from api.logger import logger
from api.runtime import interactive_lock

__all__ = ["CacheDAO", "Tiku", "TikuFallback", "TikuYanxi", "TikuGo", "TikuLike", "TikuAdapter", "AI", "SiliconFlow",
           "TikuManual", "TikuCustom", "DummyTiku", "PROVIDER_REGISTRY", "resolve_provider_name"]

DEFAULT_TRUE_LIST = "正确,对,√,是"
DEFAULT_FALSE_LIST = "错误,错,×,否,不对,不正确"


def _to_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on"}


def _to_float(value, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_int(value, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


class _CacheStore:
    """单个缓存文件的内存副本，所有 CacheDAO 实例共享，读写均加锁."""

    def __init__(self, path: Path) -> None:
        """加载缓存文件."""
        self.path = path
        self.lock = threading.RLock()
        self.data = self._load()

    def _recover(self, reason: str) -> dict:
        logger.error(f"缓存文件读取失败: {reason}, 尝试恢复...")
        try:
            text = self.path.read_bytes().decode("utf-8", errors="ignore")
            start, end = text.find('{'), text.rfind('}')
            if start != -1 and end > start:
                return json.loads(text[start:end + 1])
        except Exception:
            pass
        try:
            bak_path = self.path.with_name(f"{self.path.name}.bak.{int(time.time())}")
            shutil.copy2(self.path, bak_path)
            logger.error(f"缓存文件已损坏，已备份为: {bak_path}，将使用空缓存继续运行")
        except Exception as ex:
            logger.error(f"备份损坏缓存失败: {ex}")
        return {}

    def _load(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            with self.path.open("r", encoding="utf8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return self._recover(str(e))
        except OSError as e:
            logger.error(f"读取缓存异常: {e}")
            return {}

    def _write(self) -> None:
        # 写入临时文件后原子替换，避免写入过程中断导致文件损坏
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=self.path.name, dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf8") as fp:
                    json.dump(self.data, fp, ensure_ascii=False, indent=4)
                os.replace(tmp_path, str(self.path))
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
        except Exception as e:
            logger.error(f"写入缓存失败: {e}")

    def get(self, key: str) -> Optional[str]:
        with self.lock:
            return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        with self.lock:
            self.data[key] = value
            self._write()

    def delete(self, key: str) -> None:
        with self.lock:
            if self.data.pop(key, None) is not None:
                self._write()


class CacheDAO:
    """
    @Author: SocialSisterYi
    @Reference: https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy
    """
    DEFAULT_CACHE_FILE = "cache.json"
    _stores: dict[str, _CacheStore] = {}
    _stores_lock = threading.Lock()

    def __init__(self, file: Optional[str] = None):
        """打开（或复用已加载的）缓存文件."""
        self.cache_file = Path(file or data_path(self.DEFAULT_CACHE_FILE)).resolve()
        key = str(self.cache_file)
        with CacheDAO._stores_lock:
            store = CacheDAO._stores.get(key)
            if store is None:
                store = _CacheStore(self.cache_file)
                CacheDAO._stores[key] = store
        self._store = store

    def get_cache(self, question: str) -> Optional[str]:
        return self._store.get(question)

    def add_cache(self, question: str, answer: str) -> None:
        self._store.set(question, answer)

    def remove_cache(self, question: str) -> None:
        self._store.delete(question)


class Tiku(ABC):
    CONFIG_PATH = os.path.join(os.getcwd(), "config.ini")
    DISABLE = False  # 停用标志
    SUBMIT = False  # 提交标志
    COVER_RATE = 0.9  # 覆盖率
    true_list = None
    false_list = None
    # 是否会参考章节检测的错误反馈重新作答（大模型题库）
    supports_feedback = False

    def __init__(self, config_path: Optional[str] = None) -> None:
        """
        初始化题库基类。

        Args:
            config_path: 配置文件路径，若为 None 则使用默认的 CONFIG_PATH。
        """
        self._name = None
        self._api = None
        self._conf = None
        self._token = None
        self._config_path = config_path or self.CONFIG_PATH
        self._local = threading.local()
        self.true_list = []
        self.false_list = []

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

    def _conf_get(self, key: str, default: Any = None) -> Any:
        """读取配置项，空字符串视为未填写."""
        if not self._conf:
            return default
        try:
            value = self._conf.get(key, None)
        except Exception:
            value = None
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
        return value

    def init_tiku(self):
        # 仅用于题库初始化, 应该在题库载入后作初始化调用, 随后才可以使用题库
        if not self._conf:
            self.config_set(self._get_conf())
        if not self.DISABLE:
            # 设置提交模式，未填写的配置项使用默认值
            self.SUBMIT = _to_bool(self._conf_get('submit'), False)
            self.COVER_RATE = min(1.0, max(0.0, _to_float(self._conf_get('cover_rate'), 0.9)))
            self.true_list = [x.strip() for x in str(self._conf_get('true_list', DEFAULT_TRUE_LIST)).split(',') if x.strip()]
            self.false_list = [x.strip() for x in str(self._conf_get('false_list', DEFAULT_FALSE_LIST)).split(',') if x.strip()]
            # 调用自定义题库初始化
            self._init_tiku()

    def _init_tiku(self):
        # 仅用于题库初始化, 例如配置token, 交由自定义题库完成
        pass

    def _disable(self, reason: str) -> None:
        logger.error(f"{self.name}不可用: {reason}")
        self.DISABLE = True

    def config_set(self, config):
        self._conf = config

    def _get_conf(self):
        """
        从默认配置文件查询配置, 如果未能查到, 停用题库
        """
        try:
            config = configparser.ConfigParser()
            config.read(self._config_path, encoding="utf8")
            return config['tiku']
        except (KeyError, FileNotFoundError):
            logger.info("未找到tiku配置, 已忽略题库功能")
            self.DISABLE = True
            return None

    @property
    def _is_manual_mode(self) -> bool:
        return (
                getattr(self, 'is_manual', False) or
                self.__class__.__name__ == 'TikuManual' or
                (self.__class__.__name__ == 'TikuFallback' and any(
                    getattr(p, 'is_manual', False) or p.__class__.__name__ == 'TikuManual' for p in
                    getattr(self, 'providers', [])))
        )

    @staticmethod
    def clean_title(title: str) -> str:
        """去掉题号与分值等与题目无关的内容，作为缓存与搜题使用的标题."""
        title = sub(r'^\d+', '', title or '')
        title = sub(r'[（(]\s*\d+(\.\d+)?\s*分\s*[）)]\s*$', '', title)
        return title.strip()

    @property
    def work_feedback(self):
        """当前线程正在作答的章节检测的错误反馈（重做时使用）."""
        return getattr(self._local, "feedback", None)

    def set_work_feedback(self, feedback) -> None:
        """
        设置上一轮章节检测的错误反馈，仅对当前线程生效，供大模型题库在重新作答时参考。

        Args:
            feedback: 错误反馈，可以是 str 或 list[str]（描述哪些题目答错、正确答案是什么）
        """
        self._local.feedback = feedback or None

    def query(self, q_info: dict) -> Optional[str]:
        return self.query_all([q_info])[0]

    def query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        if self.DISABLE:
            return [None] * len(q_list)

        results: list[Optional[str]] = [None] * len(q_list)
        pending_indices = []

        cache_dao = CacheDAO()
        # 重做模式：不走缓存，让题库参考错误反馈重新作答
        skip_cache = bool(self.work_feedback)
        for idx, q in enumerate(q_list):
            if not self._is_manual_mode:
                logger.debug(f"原始标题：{q['title']}")
            q['title'] = self.clean_title(q['title'])
            if not self._is_manual_mode:
                logger.debug(f"处理后标题：{q['title']}")

            if skip_cache:
                pending_indices.append(idx)
                continue

            answer = cache_dao.get_cache(q['title'])
            if answer:
                logger.info(f"从缓存中获取答案：{q['title']} -> {answer}")
                results[idx] = answer.strip()
            else:
                pending_indices.append(idx)

        if not pending_indices:
            return results

        sub_q_list = [q_list[idx] for idx in pending_indices]
        sub_results = self._query_all(sub_q_list, query_delay=query_delay)

        if not isinstance(sub_results, list):
            logger.error(f"{self.name} _query_all 返回结果格式异常，期望列表")
            sub_results = [None] * len(pending_indices)
        elif len(sub_results) != len(pending_indices):
            logger.error(
                f"{self.name} _query_all 返回结果长度不匹配，期望 {len(pending_indices)}，实际 {len(sub_results)}")
            # 补齐或截断 sub_results 防止错位
            sub_results = (list(sub_results) + [None] * len(pending_indices))[:len(pending_indices)]

        for idx, ans in zip(pending_indices, sub_results):
            q_info = q_list[idx]
            if ans:
                ans = str(ans).strip()
                logger.info(f"从{self.name}获取答案：{q_info['title']} -> {ans}")
                if check_answer(ans, q_info['type'], self):
                    cache_dao.add_cache(q_info['title'], ans)
                    results[idx] = ans
                else:
                    logger.info(f"从{self.name}获取到的答案类型与题目类型不符，已舍弃")
            else:
                logger.warning(f"从{self.name}获取答案失败：{q_info['title']}")

        return results

    @abstractmethod
    def _query(self, q_info: dict) -> Optional[str]:
        """
        查询接口, 交由自定义题库实现
        """

    def _query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        """
        批量查询的实现接口，默认循环调用单个查询 _query。
        子类若有批量查询或交互需求（如手动模式），可重写此方法。
        """
        results = []
        for q in q_list:
            if query_delay > 0:
                time.sleep(query_delay)
            try:
                results.append(self._query(q))
            except Exception as e:
                logger.error(f"{self.name} 查询单个题目发生异常: {e}")
                results.append(None)
        return results

    @staticmethod
    def get_tiku_from_config(config: Optional[dict] = None, config_path: Optional[str] = None):
        """
        从配置文件加载题库, 这个配置可以是用户提供, 可以是默认配置文件
        """
        conf = config
        path = config_path or Tiku.CONFIG_PATH
        if not conf:
            # 尝试从默认配置文件加载
            try:
                config_parser = configparser.ConfigParser()
                config_parser.read(path, encoding="utf8")
                conf = config_parser['tiku']
            except (KeyError, FileNotFoundError):
                logger.info("未配置题库, 章节检测将被跳过")
                return DummyTiku(config_path=path)

        provider_value = (conf.get('provider') or '').strip() if hasattr(conf, 'get') else ''
        if not provider_value:
            logger.info("未配置题库, 章节检测将被跳过")
            return DummyTiku(config_path=path)

        providers = []
        for raw_name in provider_value.split(','):
            if not raw_name.strip():
                continue
            name = resolve_provider_name(raw_name)
            if not name:
                logger.error(f"题库provider配置无效: {raw_name.strip()}，可选值: {', '.join(PROVIDER_REGISTRY)}")
                return DummyTiku(config_path=path)
            providers.append(name)
        if not providers:
            logger.info("未配置题库, 章节检测将被跳过")
            return DummyTiku(config_path=path)

        if len(providers) == 1:
            new_cls = PROVIDER_REGISTRY[providers[0]](config_path=path)
            new_cls.config_set(conf)
            return new_cls

        chain_providers = []
        for provider_name in providers:
            provider = PROVIDER_REGISTRY[provider_name](config_path=path)
            provider.config_set(conf)
            chain_providers.append(provider)
        fallback = TikuFallback(chain_providers, config_path=path)
        fallback.config_set(conf)
        return fallback

    def judgement_select(self, answer: str) -> bool:
        """
        这是一个专用的方法, 要求配置维护两个选项列表, 一份用于正确选项, 一份用于错误选项, 以应对题库对判断题答案响应的各种可能的情况
        它的作用是将获取到的答案answer与可能的选项列对比并返回对应的布尔值
        """
        if self.DISABLE:
            return False
        # 对响应的答案作处理
        answer = str(answer).strip().lower()

        # 内置的高频通用判断词规整
        if answer in TRUE_WORDS:
            return True
        if answer in FALSE_WORDS:
            return False

        # 兼容自定义配置列表
        if answer in [x.lower() for x in self.true_list]:
            return True
        elif answer in [x.lower() for x in self.false_list]:
            return False
        else:
            # 无法判断, 随机选择
            logger.error(
                f'无法判断答案 -> {answer} 对应的是正确还是错误, 请自行判断并加入配置文件重启脚本, 本次将会随机选择选项')
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

    def check_llm_connection(self) -> bool:
        """
        检查大模型连接是否可用
        默认返回 True（非大模型题库不需要检查）
        """
        return True


class TikuFallback(Tiku):
    # 多题库回退实现，按 provider 中配置顺序依次查询。
    def __init__(self, providers=None, config_path: Optional[str] = None):
        """初始化多题库回退."""
        super().__init__(config_path)
        self.name = '多题库回退'
        self.providers = providers or []
        self.skip_answer_validation = True

    @property
    def supports_feedback(self) -> bool:
        return any(getattr(p, "supports_feedback", False) for p in self.providers)

    def _init_tiku(self):
        active = []
        for provider in self.providers:
            try:
                provider.init_tiku()
                if not provider.DISABLE:
                    active.append(provider)
            except Exception as e:
                logger.error(f'初始化题库 {provider.name} 失败: {e}')
        self.providers = active
        if not self.providers:
            logger.error('多题库回退初始化失败: 没有可用题库')
            self.DISABLE = True
        else:
            logger.info(f"多题库回退已启用，查询顺序: {', '.join([p.__class__.__name__ for p in self.providers])}")

    def _query(self, q_info: dict) -> Optional[str]:
        for provider in self.providers:
            try:
                answer = provider._query(q_info)
            except Exception as e:
                provider_id = f'{provider.name}({provider.__class__.__name__})'
                logger.exception(f'{self.name} 查询时 {provider_id} 异常: {e}')
                continue
            if not answer:
                logger.info(f'{provider.name} 未命中，回退到下一个题库')
                continue

            # 若当前题库返回答案但类型不符，则继续回退。
            if check_answer(answer, q_info['type'], provider):
                logger.info(f'{provider.name} 命中答案')
                return answer

            logger.info(f'{provider.name} 返回答案类型不符，回退到下一个题库')
        return None

    def _query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        results = [None] * len(q_list)
        pending_indices = list(range(len(q_list)))

        for provider in self.providers:
            if not pending_indices:
                break
            if provider.DISABLE:
                continue

            sub_q_list = [q_list[idx] for idx in pending_indices]
            try:
                sub_results = provider.query_all(sub_q_list, query_delay=query_delay)
            except Exception as e:
                provider_id = f'{provider.name}({provider.__class__.__name__})'
                logger.exception(f'{self.name} 批量查询时 {provider_id} 异常: {e}')
                continue

            if not isinstance(sub_results, list):
                logger.error(f"{provider.name} 批量查询返回数据格式异常（非列表），跳过该题库")
                continue

            if len(sub_results) != len(pending_indices):
                logger.error(
                    f"{provider.name} 批量查询返回结果长度（{len(sub_results)}）与请求题目数（{len(pending_indices)}）不匹配，跳过该题库以防答案错位")
                continue

            next_pending_indices = []
            for orig_idx, ans in zip(pending_indices, sub_results):
                if ans:
                    logger.info(f'{provider.name} 命中答案: {q_list[orig_idx]["title"]} -> {ans}')
                    results[orig_idx] = ans
                else:
                    logger.info(f'{provider.name} 未命中或返回答案无效，将回退')
                    next_pending_indices.append(orig_idx)
            pending_indices = next_pending_indices

        return results

    def set_work_feedback(self, feedback) -> None:
        """将章节检测错误反馈转发给子题库."""
        super().set_work_feedback(feedback)
        for provider in self.providers:
            try:
                provider.set_work_feedback(feedback)
            except Exception as e:
                logger.warning(f"向子题库 {provider.name} 设置错误反馈失败: {e}")

    def check_llm_connection(self) -> bool:
        for provider in self.providers:
            if not provider.check_llm_connection():
                logger.error(f'{provider.name} 连接检查失败')
                return False
        return True


# 按照以下模板实现更多题库

class TikuYanxi(Tiku):
    # 言溪题库实现
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化言溪题库实例."""
        super().__init__(config_path)
        self.name = '言溪题库'
        self.api = 'https://tk.enncy.cn/query'
        self._tokens: list[str] = []
        self._token_index = 0  # token队列计数器
        self._token_lock = threading.Lock()

    def _query(self, q_info: dict):
        while True:
            with self._token_lock:
                if self._token_index >= len(self._tokens):
                    logger.error(f'{self.name} TOKEN 已全部用完, 请更换后重启')
                    return None
                token = self._tokens[self._token_index]
            try:
                res = requests.get(
                    self.api,
                    params={'question': q_info['title'], 'token': token},
                    timeout=20,
                )
            except requests.RequestException as e:
                logger.error(f'{self.name}查询失败: {e}')
                return None
            if res.status_code != 200:
                logger.error(f'{self.name}查询失败: HTTP {res.status_code} {res.text[:200]}')
                return None
            try:
                res_json = res.json()
            except ValueError:
                logger.error(f'{self.name}查询失败: 返回内容不是有效JSON')
                return None
            data = res_json.get('data') or {}
            answer = str(data.get('answer') or '').strip()
            if res_json.get('code'):
                return answer or None
            # 查询次数用完则换下一个 token 重试
            if '次数不足' in answer or '次数已用完' in answer:
                logger.info(f'{self.name} 当前 TOKEN 查询次数不足, 将更换 TOKEN 并重新搜题')
                with self._token_lock:
                    if self._tokens[self._token_index] == token:
                        self._token_index += 1
                continue
            logger.warning(
                f'{self.name}未查到答案: {res_json.get("message", "")} {answer} (剩余次数: {data.get("times", "未知")})')
            return None

    def _init_tiku(self):
        self._tokens = [t.strip() for t in str(self._conf_get('tokens', '')).split(',') if t.strip()]
        if not self._tokens:
            self._disable("未填写 tokens（可在 https://tk.enncy.cn/ 获取）")


class TikuGo(Tiku):
    # GO题（网课小工具题库）实现，无需 token 即可使用（有频率限制）
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化GO题实例."""
        super().__init__(config_path)
        self.name = 'GO题（网课小工具题库）'
        self.api = 'https://q.icodef.com/wyn-nb?v=4'
        self._headers = {
            'Authorization': '',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        self._request_lock = threading.Lock()
        self._last_request_time = 0.0
        self._min_interval = 1.0
        self._retry_times = 3
        self._retry_backoff = 1.2

    def _sleep_for_next_request(self) -> None:
        with self._request_lock:
            now = time.time()
            wait_time = max(0.0, self._last_request_time + self._min_interval - now)
            self._last_request_time = now + wait_time
        if wait_time > 0:
            time.sleep(wait_time)

    def _mark_request_finished(self) -> None:
        with self._request_lock:
            self._last_request_time = time.time()

    def _request_question(self, question: str, attempt: int) -> Optional[requests.Response]:
        try:
            self._sleep_for_next_request()
            res = requests.post(
                self.api,
                data={'question': question},
                headers=self._headers,
                timeout=15
            )
            self._mark_request_finished()
            return res
        except requests.exceptions.RequestException as e:
            logger.error(f'{self.name}查询异常 ({attempt}/{self._retry_times}): {e}')
            self._mark_request_finished()
            return None

    def _parse_response(self, res: requests.Response) -> Optional[dict]:
        if res.status_code != 200:
            logger.error(f'{self.name}查询失败: 状态码 {res.status_code}, 响应: {res.text[:200]}')
            return None

        try:
            res_json = res.json()
        except ValueError:
            logger.error(f'{self.name}查询失败: 返回内容不是有效JSON, 响应: {res.text[:200]}')
            return None

        try:
            code = int(str(res_json.get('code', '')).strip())
        except ValueError:
            code = 0

        answer = str(res_json.get('data', '')).strip()
        msg = str(res_json.get('msg', '')).strip()
        raw_text = f'{answer} {msg}'
        is_throttled = any(key in raw_text for key in ['流控限制', '速度太快', '并发限制', '忙不过来'])
        return {
            'code': code,
            'answer': answer,
            'msg': msg,
            'is_throttled': is_throttled,
        }

    def _sleep_retry(self, attempt: int, reason: str, include_min_interval: bool = False) -> None:
        if include_min_interval:
            sleep_seconds = max(self._min_interval, self._retry_backoff * attempt)
        else:
            sleep_seconds = self._retry_backoff * attempt
        logger.warning(f'{self.name}{reason}，{sleep_seconds:.1f}s 后重试 ({attempt}/{self._retry_times})')
        time.sleep(sleep_seconds)

    @staticmethod
    def _is_placeholder_answer(answer: str, msg: str) -> bool:
        return '李恒雅' in answer or '李恒雅' in msg

    def _query(self, q_info: dict):
        title = q_info.get('title', '')
        candidates = [
            title,
            re.sub(r'^【[^】]+】\s*', '', title).strip(),
            re.sub(r'^\[[^\]]+\]\s*', '', title).strip(),
        ]
        seen = set()
        normalized_titles = []
        for item in candidates:
            if item and item not in seen:
                seen.add(item)
                normalized_titles.append(item)

        for query_title in normalized_titles:
            answer = self._query_once(query_title)
            if answer:
                return answer
        return None

    def _query_once(self, question: str) -> Optional[str]:
        for attempt in range(1, self._retry_times + 1):
            res = self._request_question(question, attempt)
            if res is None:
                if attempt < self._retry_times:
                    self._sleep_retry(attempt, '查询异常', include_min_interval=True)
                    continue
                break

            parsed = self._parse_response(res)
            if not parsed:
                return None

            code = parsed['code']
            answer = parsed['answer']
            msg = parsed['msg']
            is_throttled = parsed['is_throttled']

            if code != 1:
                if is_throttled and attempt < self._retry_times:
                    self._sleep_retry(attempt, '触发流控')
                    continue
                logger.info(f"{self.name}未命中或失败: {msg or '未知错误'}")
                return None

            if not answer:
                return None

            # GO题库在未搜到时可能在 data/msg 中返回“李恒雅正在努力撰写中...”。
            if self._is_placeholder_answer(answer, msg):
                if is_throttled and attempt < self._retry_times:
                    self._sleep_retry(attempt, '命中流控提示')
                    continue
                return None

            return answer

        return None

    def _init_tiku(self):
        self._headers['Authorization'] = str(self._conf_get('go_authorization', ''))
        min_interval = _to_float(self._conf_get('go_min_interval'), self._min_interval)
        if min_interval >= 0:
            self._min_interval = min_interval
        else:
            logger.warning(f'{self.name}配置 go_min_interval 无效，使用默认值 {self._min_interval}')

        retry_times = _to_int(self._conf_get('go_retry_times'), self._retry_times)
        if retry_times >= 1:
            self._retry_times = retry_times
        else:
            logger.warning(f'{self.name}配置 go_retry_times 无效，使用默认值 {self._retry_times}')

        retry_backoff = _to_float(self._conf_get('go_retry_backoff'), self._retry_backoff)
        if retry_backoff >= 0:
            self._retry_backoff = retry_backoff
        else:
            logger.warning(f'{self.name}配置 go_retry_backoff 无效，使用默认值 {self._retry_backoff}')


class TikuLike(Tiku):
    # LIKE知识库实现 参考 https://www.datam.site/
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化LIKE知识库实例."""
        super().__init__(config_path)
        self.name = 'LIKE知识库'
        self.ver = '2.0.0'  # 对应官网API版本
        self.query_api = 'https://app.datam.site/api/v1/query'
        self.models_api = 'https://app.datam.site/api/v1/query/models'
        self.balance_api = 'https://app.datam.site/api/v1/balance'
        self.homepage = 'https://www.datam.site'
        self._model = None
        self._timeout = 300
        self._retry = True
        self._retry_times = 3
        self._tokens = []
        self._balance = {}
        self._search = False
        self._vision = True
        self._count = 0
        self._count_lock = threading.Lock()
        self._headers = {"Content-Type": "application/json"}

    def _query(self, q_info: dict = None):
        if not q_info:
            logger.error("当前无题目信息，请检查")
            return None

        q_info_map = {"single": "【单选题】", "multiple": "【多选题】", "completion": "【填空题】", "judgement": "【判断题】"}
        q_info_prefix = q_info_map.get(q_info['type'], "【其他类型题目】")
        options = ', '.join(q_info['options']) if isinstance(q_info['options'], list) else q_info['options']
        question = f"{q_info_prefix}{q_info['title']}\n"

        if q_info['type'] in ['single', 'multiple']:
            question += f"选项为: {options}\n"

        # 优先选择有余额的token
        available_tokens = [t for t in self._tokens if self._balance.get(t, 0) > 0]
        if not available_tokens:
            logger.error(f'{self.name}所有Token查询次数都不足')
            return None
        token = random.choice(available_tokens)

        ans = None
        max_attempts = self._retry_times if self._retry else 1
        for try_times in range(1, max_attempts + 1):
            ans = self._query_single(token, question)
            if ans:
                self._balance[token] = self._balance.get(token, 1) - 1
                logger.info(f'使用Token ...{token[-5:]} 查询成功，剩余次数: {self._balance[token]}')
                break
            if try_times < max_attempts:
                logger.warning(f'使用Token ...{token[-5:]} 查询失败，进行第 {try_times + 1} 次重试...')

        # 10次查询后更新余额
        with self._count_lock:
            self._count = (self._count + 1) % 10
            need_update = self._count == 0
        if need_update:
            self.update_times()

        return ans

    def _query_single(self, token: str = "", query: str = "") -> Optional[str]:
        """
        查询单个问题的答案

        Args:
            token: API访问令牌
            query: 查询的问题内容

        Returns:
            查询到的答案，如果失败则返回None
        """
        if not token:
            logger.error(f'{self.name}查询失败: 未提供有效的token')
            return None

        if not query:
            logger.error(f'{self.name}查询失败: 查询内容为空')
            return None

        temp_headers = self._headers.copy()
        temp_headers['Authorization'] = f'Bearer {token}'

        request_data = {
            'query': query,
            'model': self._model if self._model else '',
            'search': self._search,
            'vision': self._vision
        }

        try:
            res = requests.post(
                self.query_api,
                json=request_data,
                headers=temp_headers,
                timeout=self._timeout
            )
        except requests.exceptions.Timeout:
            logger.error(f'{self.name}查询超时: 请求超过{self._timeout}秒')
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f'{self.name}网络连接错误: 无法连接到API服务器')
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f'{self.name}查询异常: \n{e}')
            return None

        if res.status_code == 200:
            return self._parse_response(res)
        elif res.status_code == 401:
            logger.error(f'{self.name}认证失败: 请检查Token是否正确或已过期')
        elif res.status_code == 429:
            logger.error(f'{self.name}请求过于频繁: 已达到API速率限制')
        elif res.status_code == 500:
            logger.error(f'{self.name}服务器内部错误: API服务暂时不可用')
        elif res.status_code == 400:
            logger.error(f'{self.name}请求参数错误: 请检查查询内容格式')
        elif res.status_code == 403:
            logger.error(f'{self.name}访问被拒绝: 可能是Token权限不足')
        else:
            logger.error(f'{self.name}查询失败: 状态码 {res.status_code}, 响应内容: \n{res.text[:300]}')

        return None

    def _parse_response(self, response):
        """
        解析API响应

        Args:
            response: HTTP响应对象

        Returns:
            解析后的答案，如果解析失败则返回None
        """
        try:
            res_json = response.json()
        except ValueError:
            logger.error(f'{self.name}响应解析失败: 响应不是有效的JSON格式')
            return None

        msg = res_json.get('message', '')
        if msg:
            logger.info(f'{self.name}响应消息: {msg}')

        results = res_json.get('results', {})
        if not results or not isinstance(results, dict):
            logger.error(f'{self.name}查询结果格式错误: API返回结果中results字段格式不正确')
            return None

        output = results.get('output', None)
        if output is None or not isinstance(output, dict):
            logger.error(f'{self.name}查询结果中output字段格式错误或不存在')
            return None

        q_type = output.get('questionType', None)
        if q_type is None:
            logger.error(f'{self.name}查询结果中questionType字段不存在')
            return None

        answer = output.get('answer', None)
        if answer is None:
            logger.error(f'{self.name}查询结果中answer字段不存在')
            return None

        return self._extract_answer_by_type(q_type, answer)

    def _extract_answer_by_type(self, q_type: str, answer: dict) -> Optional[str]:
        """
        根据题目类型提取答案

        Args:
            q_type: 题目类型
            answer: 答案字典

        Returns:
            提取的答案文本
        """
        if not isinstance(answer, dict):
            logger.error(f'{self.name}答案格式错误: 不是有效的字典格式')
            return None

        if q_type == "CHOICE":
            selected_options = answer.get('selectedOptions', None)
            if isinstance(selected_options, list):
                valid_options = [opt for opt in selected_options if opt is not None and str(opt).strip()]
                if valid_options:
                    return '\n'.join(str(opt) for opt in valid_options)
            logger.error(f'{self.name}CHOICE类型题目没有有效的选项内容')
        elif q_type == "FILL_IN_BLANK":
            blanks = answer.get('blanks', None)
            if isinstance(blanks, list):
                valid_blanks = [blank for blank in blanks if blank is not None and str(blank).strip()]
                if valid_blanks:
                    return "\n".join(str(blank) for blank in valid_blanks)
            logger.error(f'{self.name}FILL_IN_BLANK类型题目没有有效的填空内容')
        elif q_type == "JUDGMENT":
            is_correct = answer.get('isCorrect', None)
            if is_correct is not None:
                return "正确" if is_correct else "错误"
            logger.error(f'{self.name}JUDGMENT类型题目缺少isCorrect字段')
        else:
            other_text = answer.get('otherText', None)
            if other_text is not None:
                return str(other_text)
            logger.error(f'{self.name}未知题目类型{q_type}且缺少otherText字段')

        return None

    def get_api_balance(self, token: str = ""):
        if not token:
            logger.error(f'{self.name}获取余额失败: 未提供有效的token')
            return 0

        temp_headers = self._headers.copy()
        temp_headers['Authorization'] = f'Bearer {token}'
        try:
            res = requests.get(
                self.balance_api,
                headers=temp_headers,
                timeout=30
            )
            if res.status_code == 200:
                return int(res.json().get("balance", 0))
            logger.error(f'{self.name}请求余额接口失败，状态码: {res.status_code}')
            return 0
        except requests.exceptions.Timeout:
            logger.error(f'{self.name}获取余额超时: 请求超过30秒')
            return 0
        except requests.exceptions.ConnectionError:
            logger.error(f'{self.name}网络连接错误: 无法连接到余额查询API服务器')
            return 0
        except ValueError:  # json解析错误或int转换错误
            logger.error(f'{self.name}余额响应解析失败: 响应格式不正确')
            return 0
        except Exception as e:
            logger.error(f'{self.name}Token余额查询过程中出现错误: {e}')
            return 0

    def update_times(self) -> None:
        if not self._tokens:
            logger.warning(f'{self.name}未加载任何Token, 无法更新余额')
            return
        for token in self._tokens:
            balance = self.get_api_balance(token)
            self._balance[token] = balance
            logger.info(
                f"当前LIKE知识库Token: ...{token[-5:]} 的剩余查询次数为: {balance} (仅供参考, 实际次数以查询结果为准)")

    def load_tokens(self) -> None:
        tokens_str = str(self._conf_get('tokens', ''))
        self._tokens = [token.strip() for token in tokens_str.split(',') if token.strip()]

    def load_config(self) -> None:
        # 配置文件中的值均为字符串，需要显式转换布尔值（否则 "false" 会被当成 True）
        self._search = _to_bool(self._conf_get('likeapi_search'), False)
        self._model = self._conf_get('likeapi_model', None)
        self._vision = _to_bool(self._conf_get('likeapi_vision'), True)
        self._retry = _to_bool(self._conf_get("likeapi_retry"), True)
        self._retry_times = max(1, _to_int(self._conf_get("likeapi_retry_times"), 3))

    def _init_tiku(self) -> None:
        self.load_config()
        self.load_tokens()
        if self._tokens:
            self.update_times()
        else:
            self._disable("未填写 tokens（可在 https://www.datam.site/ 获取）")


class TikuAdapter(Tiku):
    # TikuAdapter题库实现 https://github.com/DokiDoki1103/tikuAdapter
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化TikuAdapter题库实例."""
        super().__init__(config_path)
        self.name = 'TikuAdapter题库'
        self.api = ''

    def _query(self, q_info: dict):
        type_map = {'single': 0, 'multiple': 1, 'completion': 2, 'judgement': 3}
        options = q_info.get('options') or ''
        try:
            res = requests.post(
                self.api,
                json={
                    'question': q_info['title'],
                    'options': [sub(r'^[A-Za-z]\.?、?\s?', '', option) for option in options.split('\n')],
                    'type': type_map.get(q_info['type'], 4)
                },
                timeout=20,
            )
        except requests.RequestException as e:
            logger.error(f'{self.name}查询失败: {e}')
            return None
        if res.status_code == 200:
            try:
                best = res.json()['answer']['bestAnswer']
            except (ValueError, KeyError, TypeError):
                logger.error(f"{self.name}返回格式异常: {res.text[:200]}")
                return None
            if not best:
                logger.warning(f"{self.name}未查到答案")
                return None
            return "\n".join(best).strip()
        logger.error(f'{self.name}查询失败: HTTP {res.status_code}')
        return None

    def _init_tiku(self):
        self.api = str(self._conf_get('url', ''))
        if not self.api:
            self._disable("未填写 url")



class TikuCustom(Tiku):
    """自建题库服务器.

    接口约定与 chaoxing-toolkit 的题库服务器、以及常见油猴脚本的"自定义题库"一致：
    POST {custom_url}，JSON 请求体 {"question": 题目, "type": "0"~"7", "options": [选项正文], "key": 密钥}；
    成功时返回 {"code": 1 或 -1, "data": {"answer": 答案}} 或 {"code": 1, "answer": 答案}。
    多选答案用 "#" 分隔（例如 "A#B#C"），填空题多个空用 "|" 分隔。
    """
    TYPE_CODES = {"single": "0", "multiple": "1", "completion": "2", "judgement": "3", "shortanswer": "4"}

    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化自建题库服务器实例."""
        super().__init__(config_path)
        self.name = '自建题库服务器'
        self.api = ''
        self.key = ''

    def _init_tiku(self):
        self.api = str(self._conf_get('custom_url', ''))
        self.key = str(self._conf_get('custom_key', ''))
        if not self.api:
            self._disable("未填写 custom_url")

    def _query(self, q_info: dict):
        options = [re.sub(r"^[A-Z]\s*[.、:：)）]?\s*", "", o).strip()
                   for o in str(q_info.get('options') or '').split('\n') if o.strip()]
        payload = {
            "question": re.sub(r'^【[^】]+】\s*', '', q_info.get('title', '')).strip(),
            "type": self.TYPE_CODES.get(q_info.get('type'), "4"),
            "options": options,
        }
        if self.key:
            payload["key"] = self.key
        try:
            res = requests.post(self.api, json=payload, timeout=15)
        except requests.RequestException as e:
            logger.error(f'{self.name}查询失败: {e}')
            return None
        try:
            data = res.json()
        except ValueError:
            logger.error(f'{self.name}返回内容不是有效JSON: HTTP {res.status_code} {res.text[:200]}')
            return None
        if not isinstance(data, dict) or str(data.get('code')) not in ('1', '-1'):
            logger.info(f"{self.name}未命中: {data.get('msg', '') if isinstance(data, dict) else data}")
            return None
        body = data.get('data') if isinstance(data.get('data'), dict) else {}
        answer = body.get('answer') or data.get('answer')
        if isinstance(answer, list):
            answer = "\n".join(str(a) for a in answer if str(a).strip())
        answer = str(answer or '').strip()
        return answer or None

def _extract_llm_answer(content: Optional[str]) -> Optional[str]:
    """从大模型输出中提取 {"Answer": [...]} 结构，兼容思考过程与 Markdown 代码块."""
    if not content:
        return None
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    match = re.search(r'^\s*```(?:json)?\s*(.*?)\s*```\s*$', text, re.S)
    if match:
        text = match.group(1).strip()
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        obj = re.search(r"\{.*\}", text, re.S)
        if obj:
            try:
                data = json.loads(obj.group(0))
            except json.JSONDecodeError:
                data = None
    if isinstance(data, dict):
        answer = data.get("Answer", data.get("answer"))
    elif isinstance(data, list):
        answer = data
    else:
        return None
    if isinstance(answer, str):
        answer = [answer]
    if not isinstance(answer, list):
        return None
    parts = [str(a).strip() for a in answer if str(a).strip()]
    return "\n".join(parts) if parts else None


class AI(Tiku):
    # AI大模型答题实现（任意兼容 OpenAI 接口的服务）
    supports_feedback = True

    PROMPTS = {
        "single": "本题为单选题，你只能选择一个选项，请根据题目和选项回答问题，以json格式输出正确的选项内容，示例回答：{\"Answer\": [\"答案\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
        "multiple": "本题为多选题，你必须选择两个或以上选项，请根据题目和选项回答问题，以json格式输出正确的选项内容，示例回答：{\"Answer\": [\"答案1\",\n\"答案2\",\n\"答案3\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
        "completion": "本题为填空题，你必须根据语境和相关知识填入合适的内容，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"答案\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
        "judgement": "本题为判断题，你只能回答正确或者错误，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"正确\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
        "other": "本题为简答题，你必须根据语境和相关知识填入合适的内容，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"这是我的答案\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
    }

    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化AI大模型答题实现."""
        super().__init__(config_path)
        self.name = 'AI大模型答题'
        self.last_request_time = None
        self._lock = threading.Lock()
        self._client = None
        self.endpoint = ''
        self.key = ''
        self.model = ''
        self.http_proxy = ''
        self.min_interval_seconds = 3.0

    def _build_work_feedback_text(self) -> str:
        """将 work_feedback 转为提示词文本."""
        fb = self.work_feedback
        if not fb:
            return ""
        if isinstance(fb, str):
            return fb
        lines = [
            "你上一次作答的章节检测中有以下题目回答错误，"
            "请根据题目与正确答案仔细思考错因，纠正你的判断，本次作答务必保证每道题都正确："
        ]
        lines.extend(str(item) for item in fb)
        return "\n".join(lines)

    def _is_deepseek_v4(self) -> bool:
        return (
                'api.deepseek.com' in (self.endpoint or '').lower()
                and (self.model or '').lower().startswith('deepseek-v4')
        )

    def _completion_kwargs(self, **kwargs):
        if self._is_deepseek_v4():
            # DeepSeek V4 defaults to thinking mode, which can leave message.content empty.
            kwargs['extra_body'] = {'thinking': {'type': 'disabled'}}
        return kwargs

    def _wait_for_interval(self):
        if self.last_request_time:
            interval_time = time.time() - self.last_request_time
            if interval_time < self.min_interval_seconds:
                sleep_time = self.min_interval_seconds - interval_time
                logger.debug(f"API请求间隔过短, 等待 {sleep_time:.1f} 秒")
                time.sleep(sleep_time)

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            http_client = None
            if self.http_proxy:
                try:
                    from openai import DefaultHttpxClient
                    http_client = DefaultHttpxClient(proxy=self.http_proxy)
                except (ImportError, TypeError):
                    http_client = httpx.Client(proxy=self.http_proxy)
            self._client = OpenAI(base_url=self.endpoint, api_key=self.key, http_client=http_client,
                                  timeout=120, max_retries=2)
        return self._client

    def _query(self, q_info: dict):
        with self._lock:
            return self._query_locked(q_info)

    def _query_locked(self, q_info: dict):
        client = self._get_client()
        # 去除选项字母，防止大模型直接输出字母而非内容
        options = "\n".join(re.sub(r"^[A-Z]\s*[.、:：)）]?\s*", "", o) for o in str(q_info.get('options') or '').split('\n'))

        feedback_text = self._build_work_feedback_text()
        q_type = q_info['type'] if q_info['type'] in self.PROMPTS else 'other'
        if q_type in ('single', 'multiple'):
            user_content = f"题目：{q_info['title']}\n选项：{options}"
        else:
            user_content = f"题目：{q_info['title']}"
        messages = [{"role": "system", "content": self.PROMPTS[q_type]}]
        if feedback_text:
            messages.append({"role": "system", "content": feedback_text})
        messages.append({"role": "user", "content": user_content})

        self._wait_for_interval()
        self.last_request_time = time.time()
        try:
            completion = client.chat.completions.create(**self._completion_kwargs(model=self.model, messages=messages))
        except Exception as e:
            logger.error(f"{self.name}请求失败: {e}")
            return None

        content = completion.choices[0].message.content if completion.choices else None
        answer = _extract_llm_answer(content)
        if answer is None:
            logger.error(f"无法解析大模型输出内容: {str(content)[:200]}")
        return answer

    def _load_llm_config(self) -> tuple[str, str, str]:
        return (str(self._conf_get('endpoint', '')), str(self._conf_get('key', '')),
                str(self._conf_get('model', '')))

    def _init_tiku(self):
        self.endpoint, self.key, self.model = self._load_llm_config()
        self.http_proxy = str(self._conf_get('http_proxy', ''))
        self.min_interval_seconds = max(0.0, _to_float(self._conf_get('min_interval_seconds'), 3.0))
        missing = [name for name, value in (("endpoint", self.endpoint), ("key", self.key), ("model", self.model))
                   if not value]
        if missing:
            self._disable(f"未填写 {', '.join(missing)}")

    def check_llm_connection(self) -> bool:
        """
        检查大模型连接是否可用
        发送一个简单的测试请求来验证 API 配置
        """
        with self._lock:
            logger.info(f'正在检查 {self.name} 连接...')
            try:
                client = self._get_client()
                self._wait_for_interval()
                self.last_request_time = time.time()
                completion = client.chat.completions.create(**self._completion_kwargs(
                    model=self.model,
                    messages=[{'role': 'user', 'content': '你好，请回答：1+1 等于几？只回答数字。'}],
                    max_tokens=200  # 增大以支持可能返回的 reasoning_content
                ))
                if completion.choices:
                    msg = completion.choices[0].message
                    if msg.content or getattr(msg, 'reasoning_content', None):
                        logger.info(f'{self.name} 连接检查成功')
                        return True
                logger.error(f'{self.name} 连接检查失败：未收到响应')
                return False
            except Exception as e:
                logger.error(f'{self.name} 连接检查失败：{e}')
                return False


class SiliconFlow(AI):
    # 硅基流动（OpenAI 兼容接口），复用 AI 的实现，仅配置项不同
    DEFAULT_ENDPOINT = 'https://api.siliconflow.cn/v1'
    DEFAULT_MODEL = 'deepseek-ai/DeepSeek-V3'

    def __init__(self, config_path: Optional[str] = None):
        """初始化硅基流动大模型题库."""
        super().__init__(config_path)
        self.name = '硅基流动大模型'

    def _load_llm_config(self) -> tuple[str, str, str]:
        endpoint = str(self._conf_get('siliconflow_endpoint', self.DEFAULT_ENDPOINT))
        # 兼容旧配置中填写的完整地址 https://api.siliconflow.cn/v1/chat/completions
        endpoint = re.sub(r'/chat/completions/?$', '', endpoint.rstrip('/'))
        return (endpoint, str(self._conf_get('siliconflow_key', '')),
                str(self._conf_get('siliconflow_model', self.DEFAULT_MODEL)))


class TikuManual(Tiku):
    # 与日志、进度条共用同一把交互锁：输入期间后台日志暂存、进度条隐藏
    _manual_lock = interactive_lock
    is_manual = True

    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化手动题库实例."""
        super().__init__(config_path)
        self.name = '手动输入题库'
        self.default_mode = 'batch'
        self.skip_answer_validation = True

    @staticmethod
    def _extract_option_letters(ans: str) -> list[str]:
        cleaned = re.sub(r'[\s,，;；、]+', '', ans)
        if not cleaned or not re.fullmatch(r'[A-Za-z]+', cleaned):
            return []
        return [c.upper() for c in cleaned]

    @staticmethod
    def _stdin_interactive() -> bool:
        try:
            return sys.stdin is not None and sys.stdin.isatty()
        except (AttributeError, ValueError):
            return False

    def _init_tiku(self):
        self.default_mode = str(self._conf_get('manual_mode_default', 'batch')).lower()
        if self.default_mode not in ['batch', 'single']:
            self.default_mode = 'batch'

        self.separator = str(self._conf_get('manual_mode_separator', ';'))
        if self.separator.lower() in ['\\n', 'newline', '换行']:
            self.separator = '\n'
        elif self.separator.lower() in ['space', '空格']:
            self.separator = ' '
        elif self.separator.lower() in ['tab', '制表符']:
            self.separator = '\t'

    @staticmethod
    def _safe_close_tqdm_bars():
        """安全地清除并关闭所有活动的 tqdm 进度条，防止私有属性变更引发异常."""
        try:
            from tqdm import tqdm
            if hasattr(tqdm, '_instances') and hasattr(tqdm._instances, '__iter__'):
                # 复制一份以防遍历时容器大小发生变化 (WeakSet/list)
                instances = list(tqdm._instances)
                for instance in instances:
                    try:
                        if hasattr(instance, 'leave'):
                            instance.leave = False
                        if hasattr(instance, 'clear'):
                            instance.clear()
                        if hasattr(instance, 'close'):
                            instance.close()
                    except Exception as ie:
                        logger.debug(f"清理单个 tqdm 实例失败: {ie}")
        except Exception as e:
            logger.debug(f"获取/清理 tqdm 实例列表失败: {e}")

    def _query(self, q_info: dict) -> Optional[str]:
        if not self._stdin_interactive():
            logger.warning("手动输入题库需要在终端中交互运行，当前环境无法输入，已跳过该题")
            return None
        # 强行关闭清除所有当前活动的 tqdm 进度条
        self._safe_close_tqdm_bars()

        with self._manual_lock:
            ans = self._single_query(q_info)
        logger.debug("手动答题结束，冲刷缓存日志")
        return ans

    def _query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        if not self._stdin_interactive():
            logger.warning("手动输入题库需要在终端中交互运行，当前环境无法输入，已跳过本次章节检测的手动作答")
            return [None] * len(q_list)
        # 强行关闭清除所有当前活动的 tqdm 进度条
        self._safe_close_tqdm_bars()

        with self._manual_lock:
            print(f"\n{'=' * 20} 手动输入题库 (共 {len(q_list)} 题) {'=' * 20}")
            if self.default_mode == 'batch':
                ans_list = self._batch_query_flow(q_list)
            else:
                ans_list = [self._single_query(q) for q in q_list]
        logger.debug("手动答题结束，冲刷缓存日志")
        return ans_list

    @staticmethod
    def _get_type_display(type_str: str) -> str:
        type_map = {
            'single': '单选题',
            'multiple': '多选题',
            'completion': '填空题',
            'judgement': '判断题'
        }
        return type_map.get(type_str, '其他类型')

    def _single_query(self, q: dict) -> Optional[str]:
        type_str = self._get_type_display(q['type'])
        if q['type'] in ['single', 'multiple'] and q.get('options'):
            options = q['options']
            parts = []
            if isinstance(options, str):
                parts = [o.strip() for o in options.split('\n') if o.strip()]
                if len(parts) <= 1:
                    from api.answer_check import cut
                    cut_parts = cut(options)
                    if cut_parts:
                        parts = cut_parts
            elif isinstance(options, list):
                parts = [str(o).strip() for o in options if str(o).strip()]

            options_text = "  ".join(parts)
            print(f"\n【{type_str}】 {q['title']} 选项: {options_text}")
        elif q['type'] == 'judgement':
            print(f"\n【{type_str}】 {q['title']} 选项: 正确 / 错误")
        else:
            print(f"\n【{type_str}】 {q['title']}")

        while True:
            ans = input("请输入答案 (直接回车表示跳过/无答案): ").strip()
            if not ans:
                print(f"  [已记录] 题目: {q['title']} ---> 答案: [跳过/随机]")
                return None

            # 即时校验
            ok, err_msg = self._validate_user_input(ans, q)
            if not ok:
                print(f"  \033[31m[输入错误] {err_msg}\033[0m")
                continue

            normalized_ans = self._normalize_user_input(ans, q)
            print(f"  [已记录] 题目: {q['title']} ---> 答案: {normalized_ans}")
            return normalized_ans

    def _validate_user_input(self, ans: str, q: dict) -> tuple[bool, str]:
        """
        验证用户手动输入的答案是否合规.
        """
        if not ans:
            return True, ""

        ans = ans.strip()
        if not ans:
            return True, ""

        q_type = q.get('type')
        if q_type == 'judgement':
            return self._validate_judgement_input(ans)
        elif q_type in ['single', 'multiple']:
            return self._validate_choice_input(ans, q)
        return True, ""

    def _validate_judgement_input(self, ans: str) -> tuple[bool, str]:
        """验证判断题手动输入是否合规."""
        val = ans.lower()
        valid_judgements = [
            'true', 't', '1', '对', '正确', '√', '是', 'yes', 'y',
            'false', 'f', '0', '错', '错误', '×', '否', 'no', 'n', '不对', '不正确'
        ]
        if val not in valid_judgements:
            return False, f"无法识别的判断词 '{ans}'，请输入：对/错、正确/错误、T/F、1/0"
        return True, ""

    def _validate_choice_input(self, ans: str, q: dict) -> tuple[bool, str]:
        """
        验证选择题手动输入是否合规.
        """
        options = q.get('options', '')
        parts = self._parse_options(options)
        valid_keys = self._extract_valid_keys(parts)

        if not valid_keys:
            return True, ""

        letters = self._extract_option_letters(ans)
        if not letters:
            return self._validate_text_match(ans, parts)

        invalid_letters = [letter for letter in letters if letter not in valid_keys]
        if invalid_letters:
            return False, f"输入包含无效的选项字母 {invalid_letters}，当前题目的可用选项为: {', '.join(valid_keys)}"

        if q.get('type') == 'single' and len(letters) > 1:
            return False, "当前是单选题，但输入了多个选项字母！"

        return True, ""

    def _parse_options(self, options) -> list[str]:
        """
        解析选项.
        """
        parts = []
        if isinstance(options, str):
            parts = [o.strip() for o in options.split('\n') if o.strip()]
            if len(parts) <= 1:
                from api.answer_check import cut
                cut_parts = cut(options)
                if cut_parts:
                    parts = cut_parts
        elif isinstance(options, list):
            parts = [str(o).strip() for o in options if str(o).strip()]
        return parts

    def _extract_valid_keys(self, parts: list[str]) -> list[str]:
        """
        提取合法的选项字母.
        """
        valid_keys = []
        for p in parts:
            first_char = p[:1].upper()
            if first_char.isalpha():
                valid_keys.append(first_char)
        return valid_keys

    def _validate_text_match(self, ans: str, parts: list[str]) -> tuple[bool, str]:
        """
        验证用户输入的文本是否和选项文本匹配.
        """
        from api.answer_check import cut
        split_ans = cut(ans)
        if split_ans:
            for item in split_ans:
                matched = False
                for p in parts:
                    p_norm = re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*', '', p).strip().lower()
                    if item.strip().lower() in p_norm or p_norm in item.strip().lower():
                        matched = True
                        break
                if not matched:
                    return False, f"输入的文本 '{item}' 在所有选项中均无法匹配，请输入合法的选项文本或字母"
        return True, ""

    def _normalize_user_input(self, ans: str, q: dict) -> Optional[str]:
        """
        规整化用户的手动输入答案.
        """
        if not ans:
            return None

        ans = ans.strip()
        if not ans:
            return None

        q_type = q.get('type')
        if q_type == 'judgement':
            return self._normalize_judgement_input(ans)
        elif q_type in ['single', 'multiple']:
            return self._normalize_choice_input(ans, q)
        return ans

    def _normalize_judgement_input(self, ans: str) -> str:
        """
        规整化判断题的手动输入.
        """
        val = ans.lower()
        if val in ['true', 't', '1', '对', '正确', '√', '是', 'yes', 'y']:
            return "正确"
        elif val in ['false', 'f', '0', '错', '错误', '×', '否', 'no', 'n', '不对', '不正确']:
            return "错误"
        return ans

    def _normalize_choice_input(self, ans: str, q: dict) -> str:
        """
        规整化选择题的手动输入.
        """
        options = q.get('options', '')
        parts = self._parse_options(options)
        valid_keys = self._extract_valid_keys(parts)

        letters = self._extract_option_letters(ans)
        if letters and all(letter in valid_keys for letter in letters):
            unique_ordered_letters = []
            for letter in letters:
                if letter not in unique_ordered_letters:
                    unique_ordered_letters.append(letter)
            return "\n".join(unique_ordered_letters)

        from api.answer_check import cut
        split_ans = cut(ans)
        if split_ans:
            return "\n".join(split_ans)
        return ans

    def _batch_query_flow(self, q_list: list[dict]) -> list[Optional[str]]:
        """
        执行批量手动搜题交互.
        """
        self._print_batch_questions(q_list)

        sep_desc = self.separator
        if self.separator == '\n':
            sep_desc = '换行 (每题一行)'
        elif self.separator == ' ':
            sep_desc = '空格'
        elif self.separator == '\t':
            sep_desc = 'Tab制表符'

        self._print_batch_instructions(sep_desc)

        while True:
            answers = []
            if self.separator == '\n':
                print(f"请直接粘贴或依次输入各题答案（每行一个，共 {len(q_list)} 行）：")
                for i in range(len(q_list)):
                    try:
                        ans = input(f"  第 {i + 1} 题答案: ").strip()
                    except EOFError:
                        ans = ""
                    answers.append(ans)
            else:
                raw_input = input(f"\n请一次性输入所有题目的答案 (使用 '{sep_desc}' 分割): ").strip()
                answers = self._split_batch_answers(raw_input, len(q_list))

            has_error, temp_answers = self._parse_and_validate_batch(q_list, answers)

            if has_error:
                print("\033[31m检测到存在不合规的答案，已拒绝确认，请重新输入！\033[0m")
                continue

            confirm = input("确认使用上述答案？[Y/n]: ").strip().lower()
            if confirm in ['', 'y', 'yes']:
                return temp_answers
            elif confirm == 'switch':
                return [self._single_query(q) for q in q_list]
            else:
                print("已取消，请重新输入，或输入 'switch' 切换为单题输入模式。")

    def _print_batch_questions(self, q_list: list[dict]) -> None:
        """批量打印题目内容及选项."""
        for idx, q in enumerate(q_list):
            type_str = self._get_type_display(q['type'])
            if q['type'] in ['single', 'multiple'] and q.get('options'):
                options = q['options']
                parts = []
                if isinstance(options, str):
                    parts = [o.strip() for o in options.split('\n') if o.strip()]
                    if len(parts) <= 1:
                        from api.answer_check import cut
                        cut_parts = cut(options)
                        if cut_parts:
                            parts = cut_parts
                elif isinstance(options, list):
                    parts = [str(o).strip() for o in options if str(o).strip()]

                options_text = "  ".join(parts)
                print(f"\n[{idx + 1}] 【{type_str}】 {q['title']} 选项: {options_text}")
            elif q['type'] == 'judgement':
                print(f"\n[{idx + 1}] 【{type_str}】 {q['title']} 选项: 正确 / 错误")
            else:
                print(f"\n[{idx + 1}] 【{type_str}】 {q['title']}")

    def _print_batch_instructions(self, sep_desc: str) -> None:
        """打印批量输入的使用引导说明."""
        print("\n" + "=" * 50)
        print("请依次输入每道题的答案。")
        print(f"格式要求：当前配置要求使用【{sep_desc}】分割各题的答案。")
        print("如果是多选题，答案中的多个选项直接连着写即可（例如：AB 或 AC）。")
        print("直接按回车或输入空格跳过的题，对应的答案将为空（会触发随机答题）。")
        if self.separator == '\n':
            print("粘贴多行时，每行会被解析为对应一题的答案。")
        else:
            print(f"示例输入: A{self.separator} B{self.separator} 正确{self.separator} 答案1, 答案2{self.separator} 错")
        print("=" * 50)

    def _split_batch_answers(self, raw_input: str, expected_len: int) -> list[str]:
        """根据配置的分割符将批量的答案进行分拆和补齐."""
        if not raw_input:
            return [''] * expected_len

        if self.separator in [';', '；']:
            raw_input = raw_input.replace('；', ';')
            answers = [ans.strip() for ans in raw_input.split(';')]
        elif self.separator in [',', '，']:
            raw_input = raw_input.replace('，', ',')
            answers = [ans.strip() for ans in raw_input.split(',')]
        else:
            answers = [ans.strip() for ans in raw_input.split(self.separator)]

        if len(answers) < expected_len:
            answers.extend([''] * (expected_len - len(answers)))
        elif len(answers) > expected_len:
            answers = answers[:expected_len]
        return answers

    def _parse_and_validate_batch(self, q_list: list[dict], answers: list[str]) -> tuple[bool, list[Optional[str]]]:
        """批量解析用户输入并进行合法性校验."""
        print("\n--- 解析答案结果 ---")
        has_error = False
        temp_answers = []
        for idx, (q, ans) in enumerate(zip(q_list, answers)):
            ok, err_msg = self._validate_user_input(ans, q)
            if not ok:
                has_error = True
                print(f"第 {idx + 1} 题: {q['title']} ---> \033[31m[错误: {err_msg}]\033[0m")
                temp_answers.append(None)
            else:
                normalized_ans = self._normalize_user_input(ans, q)
                temp_answers.append(normalized_ans)
                print(f"第 {idx + 1} 题: {q['title']} ---> 答案: {normalized_ans if normalized_ans else '[跳过/随机]'}")
        print("-------------------")
        return has_error, temp_answers


class DummyTiku(Tiku):
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化空题库."""
        super().__init__(config_path)
        self.name = '空/禁用题库'
        self.DISABLE = True

    def _query(self, q_info: dict) -> Optional[str]:
        return None


PROVIDER_REGISTRY = {
    'TikuYanxi': TikuYanxi,
    'TikuGo': TikuGo,
    'TikuLike': TikuLike,
    'TikuAdapter': TikuAdapter,
    'TikuCustom': TikuCustom,
    'AI': AI,
    'SiliconFlow': SiliconFlow,
    'TikuManual': TikuManual,
}

# 常用简写，填写 provider 时不区分大小写
PROVIDER_ALIASES = {
    'yanxi': 'TikuYanxi',
    '言溪': 'TikuYanxi',
    'go': 'TikuGo',
    'go题': 'TikuGo',
    'icodef': 'TikuGo',
    'like': 'TikuLike',
    'adapter': 'TikuAdapter',
    'custom': 'TikuCustom',
    '自建': 'TikuCustom',
    'openai': 'AI',
    'llm': 'AI',
    'manual': 'TikuManual',
    '手动': 'TikuManual',
}


def resolve_provider_name(name) -> Optional[str]:
    """把用户填写的题库名称解析为已注册的题库类名，无法识别时返回 None."""
    key = str(name or '').strip()
    if not key:
        return None
    if key in PROVIDER_REGISTRY:
        return key
    lower = key.lower()
    for registered in PROVIDER_REGISTRY:
        if registered.lower() == lower:
            return registered
    return PROVIDER_ALIASES.get(lower)
