# -*- coding: utf-8 -*-
"""大模型调用的统一策略层（thinking 模式自适应）."""
#
# 不同模型可能返回正文、推理正文或空响应，需要按实际响应降级。
#
# 策略（thinking = auto/on/off，默认 auto）：
# auto: 按模型默认行为调用；正文为空但有 reasoning 时用 reasoning 兜底；
# 两者都空 → 再试一次 thinking=disabled。
# on  : 显式开启；若接口不支持该参数 → 去掉参数重试。
# off : 显式关闭；正文仍为空 → 去掉参数重试。

import re
from typing import Any, Optional

THINKING_MODES = ("auto", "on", "off")


def normalize_thinking(value: Any) -> str:
    """只接受 auto/on/off，其它值一律回到 auto."""
    mode = str(value or "auto").strip().lower()
    return mode if mode in THINKING_MODES else "auto"


def thinking_payload(mode: str) -> dict:
    """该模式要附加到请求体里的 thinking 字段（auto 不加）."""
    if mode == "on":
        return {"thinking": {"type": "enabled"}}
    if mode == "off":
        return {"thinking": {"type": "disabled"}}
    return {}


def thinking_steps(mode: str) -> list:
    """按顺序尝试的模式列表：主模式失败后回退到更保守的一档."""
    mode = normalize_thinking(mode)
    if mode == "on":
        return ["on", "auto"]
    if mode == "off":
        return ["off", "auto"]
    return ["auto", "off"]


def extract_text(message: Any) -> tuple:
    """从响应 message 里取 (content, reasoning_content)，兼容 SDK 对象与 dict."""
    if isinstance(message, dict):
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
    else:
        content = getattr(message, "content", "") or ""
        reasoning = getattr(message, "reasoning_content", "") or ""
    return str(content).strip(), str(reasoning).strip()


def is_thinking_param_error(exc: BaseException) -> bool:
    """接口不认 thinking 参数时（400/422 + 关键字）返回 True."""
    text = str(exc).lower()
    if "thinking" not in text:
        return False
    return any(key in text for key in (
        "unsupported", "unknown", "invalid", "not support", "unrecognized",
        "extra_forbidden", "unexpected keyword", "400", "422",
    ))


def strip_code_fence(text: str) -> str:
    """去掉三反引号（可带 json 标注）包裹的代码块."""
    matched = re.match(r"^\s*\`\`\`(?:json)?\s*(.*?)\s*\`\`\`\s*$", str(text or ""), re.DOTALL)
    return matched.group(1).strip() if matched else str(text or "").strip()


def create_completion(client, *, model: str, messages: list, thinking: str = "auto",
                      allow_reasoning_fallback: bool = False, **kwargs) -> str:
    """调一次 chat.completions，按 thinking 策略自动降级."""
    #
    # allow_reasoning_fallback=True 时（答题链路），正文为空则用 reasoning_content 兜底
    # （推理内容里通常也包含最终答案）；写作链路必须为 False，避免把思维链当正文交出去。
    steps = thinking_steps(thinking)
    last_error: Optional[BaseException] = None
    for index, step in enumerate(steps):
        extra = thinking_payload(step)
        call_kwargs = dict(kwargs)
        if extra:
            call_kwargs["extra_body"] = extra
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, **call_kwargs
            )
        except BaseException as exc:  # noqa: BLE001 - 需要区分参数不支持与其它错误
            last_error = exc
            if extra and is_thinking_param_error(exc) and index + 1 < len(steps):
                continue
            raise
        content, reasoning = extract_text(response.choices[0].message)
        if content:
            return content
        if reasoning and allow_reasoning_fallback:
            return reasoning
    if last_error is not None:
        raise last_error
    return ""
