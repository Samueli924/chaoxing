# -*- coding: utf-8 -*-
"""
本地大模型的自动加载 / 卸载。

题库使用 AI 大模型、并且接口地址指向本机的 LM Studio 时：
- 开始学习前自动加载配置的模型；
- 所有账号学完或停止后（空闲一小段时间），自动卸载这次刷课用过的模型，释放内存。
使用 LM Studio 的 REST 接口（/api/v1/models、/api/v1/models/load、/api/v1/models/unload）。
"""
import json
import time
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import urlparse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


class LocalLLMError(Exception):
    pass


def _request(method: str, url: str, body: Optional[dict] = None, timeout: float = 10) -> dict:
    data = json.dumps(body).encode("utf8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf8")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf8")).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise LocalLLMError(msg or f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise LocalLLMError(f"无法连接 {url}: {e}") from e
    return json.loads(text or "{}")


class LMStudio:
    name = "LM Studio"

    def __init__(self, root: str):
        self.root = root.rstrip("/")

    def _models(self) -> list[dict]:
        return _request("GET", f"{self.root}/api/v1/models", timeout=5).get("models", [])

    def probe(self) -> bool:
        try:
            return isinstance(_request("GET", f"{self.root}/api/v1/models", timeout=3).get("models"), list)
        except Exception:
            return False

    def instances(self, model: str) -> list[str]:
        ids = []
        for m in self._models():
            for inst in m.get("loaded_instances") or []:
                if m.get("key") == model or inst.get("id") == model:
                    ids.append(inst["id"])
        return ids

    def ensure_loaded(self, model: str) -> bool:
        """模型未加载时加载它。返回 True 表示这次新加载了。"""
        if self.instances(model):
            return False
        _request("POST", f"{self.root}/api/v1/models/load", {"model": model}, timeout=600)
        return True

    def unload(self, model: str) -> int:
        """卸载该模型的所有实例，返回卸载的数量。"""
        ids = self.instances(model)
        for inst in ids:
            _request("POST", f"{self.root}/api/v1/models/unload", {"instance_id": inst}, timeout=120)
        return len(ids)


def local_target(tiku_conf: dict) -> Optional[tuple[str, str]]:
    """题库配置指向本机大模型时返回 (服务根地址, 模型名)，否则返回 None。"""
    providers = [p.strip() for p in str(tiku_conf.get("provider", "")).split(",") if p.strip()]
    if "AI" not in providers:
        return None
    model = str(tiku_conf.get("model", "")).strip()
    url = urlparse(str(tiku_conf.get("endpoint", "")).strip())
    if not model or url.hostname not in LOCAL_HOSTS:
        return None
    return f"{url.scheme or 'http'}://{url.netloc}", model


class AutoUnloader:
    """记录刷课用过的本地模型；所有账号空闲 grace 秒后返回需要卸载的模型。"""

    def __init__(self, grace: float = 15, clock: Callable[[], float] = time.time):
        self.grace = grace
        self._clock = clock
        self.pending: dict[tuple[str, str], LMStudio] = {}
        self.idle_since: Optional[float] = None

    def used(self, backend: LMStudio, model: str):
        self.pending[(backend.root, model)] = backend
        self.idle_since = None

    def tick(self, busy: bool) -> list[tuple[LMStudio, str]]:
        if busy or not self.pending:
            self.idle_since = None
            return []
        now = self._clock()
        if self.idle_since is None:
            self.idle_since = now
            return []
        if now - self.idle_since < self.grace:
            return []
        due = [(backend, model) for (_root, model), backend in self.pending.items()]
        self.pending.clear()
        self.idle_since = None
        return due

    def take_all(self) -> list[tuple[LMStudio, str]]:
        due = [(backend, model) for (_root, model), backend in self.pending.items()]
        self.pending.clear()
        return due
