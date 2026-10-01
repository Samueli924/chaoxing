# -*- coding: utf-8 -*-
"""超星刷课 · 统一多用户入口."""
#
# 启动流程：
# 1. 检查/配置 DeepSeek API Key（实时验证有效性）
# 2. 显示用户列表：选一个直接开始，或加入新账号，或管理账号
# 3. 登录（用保存的账密，不用重输）
# 4. 选刷什么：章节（目录）/ 任务中心·教学任务（两套独立入口）
# 5. 选课（每次都手动选，不沿用上次）
# 6. 逐门课程设置本次范围：章节前几个 / 教学任务前几个（不刷的那类不问）
# 7. 开始刷课
#
# 安全设计：
# 任何时候输入 q / quit / exit 都能立即退出，防止刷错课。
# Ctrl+C 同样安全退出。
#
# 每个用户的账号、cookie 都互相隔离，不会串号。

import configparser
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from api import accounts, interrupt, paths
from api.configfile import read_config_file
from api.cxsecret_font import resource_path
from api.display import safe_console

# 模板在项目目录；用户配置在数据目录（~/.chaoxing/config.ini），
# 这样升级代码不会影响用户的配置。
TEMPLATE = resource_path("config_template.ini")
paths.init()          # 确保数据目录存在，并完成一次旧数据迁移
CONFIG = paths.config_path()

DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-flash"

# 视觉规范：
#   title() 用一条细横线做小标题，只在关键节点使用
#   正文缩进 2 空格；说明文字尽量一行说完，不堆叠空行
#   输入提示保持在单行，避免每次都占两行
RULE = "─" * 46

# 输入这些字符 = 立即退出
QUIT_WORDS = {"q", "quit", "exit", "退出", "取消"}


class UserQuit(Exception):
    """用户主动一键退出."""


def quit_now(reason="用户主动退出"):
    """统一的安全退出：清理后终止进程."""
    raise UserQuit(reason)


def _pad(text, width):
    """按终端显示宽度右侧补空格（中文占 2 列）."""
    try:
        import unicodedata
        cur = 0
        for ch in str(text):
            cur += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    except Exception:
        cur = len(str(text))
    gap = width - cur
    return str(text) + (" " * gap if gap > 0 else "")


def title(text):
    """小标题：空行 + 标题 + 细横线."""
    print()
    print("  " + text)
    print("  " + RULE)


def ask_choice(prompt, valid, default="", max_tries=5):
    """反复问，直到拿到合法选项."""
    #
    # 非交互输入（管道/重定向）反复给不出合法值时按默认继续，绝不卡死——
    # 向导里任何一个选择题都不该让整个流程停在那里。
    options = " / ".join(sorted(valid))
    for _ in range(max_tries):
        raw = ask(prompt, default=default or None)
        if raw in valid:
            return raw
        print("  ✘ 只能填 " + options + "。")
    fallback = default or sorted(valid)[0]
    print("  · 没收到有效选择，按默认 " + fallback + " 继续")
    return fallback


def _read_line(prompt, tip):
    """读一行输入（提示和输入在同一行，省掉多余的空行）."""
    # q/exit 立即退出，Ctrl+C 安全退出。
    try:
        return input("▶ " + prompt + tip + " > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("  已退出。")
        raise UserQuit("cancelled")


def ask(prompt, default=None, allow_empty=False):
    """读取必填项。留空会一直追问."""
    # 输入 q / quit / exit 立即退出。
    for _ in range(5):
        if default is not None:
            tip = "  [回车=" + str(default) + "，q 退出]"
        elif allow_empty:
            tip = "  [回车跳过，q 退出]"
        else:
            tip = "  （q 退出）"
        val = _read_line(prompt, tip)

        if val.lower() in QUIT_WORDS:
            print()
            print("  已退出，不会执行任何刷课操作。")
            raise UserQuit("user quit")

        if val:
            return val
        if default is not None:
            return str(default)
        if allow_empty:
            return ""
        print("  ✘ 这一项不能为空。")
    print()
    print("  · 连续多次没有收到有效输入，已退出向导（重新运行 cx 即可）。")
    sys.exit(1)


def ask_yes_no(prompt, default_no=True):
    # 把默认值写进提示：回车 = 默认（危险动作默认不继续）
    tip = "  [y/n · 回车＝" + ("否" if default_no else "是") + " · q 退出]"
    ans = _read_line(prompt, tip).lower()

    if ans in QUIT_WORDS:
        print()
        print("  已退出，不会执行任何刷课操作。")
        raise UserQuit("user quit")

    if not ans:
        return not default_no
    return ans in ("y", "yes", "是", "1")


def replace_value(content, section, key, value):
    """在 ini 文本里替换 key=value，保留注释."""
    out = []
    cur = None
    done = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            cur = stripped[1:-1]
        if cur == section and not done:
            core = stripped.split(";")[0].strip()
            if "=" in core and core.split("=")[0].strip() == key:
                out.append(key + " = " + value)
                done = True
                continue
        out.append(line)
    if done:
        return chr(10).join(out)
    res = []
    inserted = False
    cur = None
    for line in out:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if cur == section and not inserted:
                res.append(key + " = " + value)
                inserted = True
            cur = stripped[1:-1]
        res.append(line)
    if cur == section and not inserted:
        res.append(key + " = " + value)
        inserted = True

    # 整个文件里都没有这个节 -> 直接追加一个新节
    if not inserted:
        res.append("")
        res.append("[" + section + "]")
        res.append(key + " = " + value)
    return chr(10).join(res)


# ==================== DeepSeek API Key ====================

def short_err(err, limit=60):
    """把冗长的 API 报错压缩成一句人话."""
    # 例如：Error code: 401 - {'error': {'message': 'Authentication Fails...'}}
    # ->  认证失败：API Key 无效
    text = str(err)
    try:
        import re as _re
        # 兼容单引号和双引号的 message 字段
        m = _re.search(r"['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]", text)
        if m:
            text = m.group(1)
    except (TypeError, ValueError):
        text = str(err)

    # 用【原始】报错判断类型（精简后的文本可能已经不含 401 等关键字）
    low = str(err).lower()
    if "401" in low or "authentication" in low or "invalid" in low or "unauthorized" in low:
        return "API Key 无效或已失效"
    if "402" in low or "insufficient" in low or "balance" in low or "quota" in low:
        return "账户余额不足"
    if "429" in low or "rate limit" in low:
        return "请求过于频繁，请稍后再试"
    if "timeout" in low or "timed out" in low:
        return "连接超时，请检查网络"
    if "connection" in low or "unreachable" in low:
        return "网络连接失败"

    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def verify_deepseek_key(api_key):
    """联网验证 Key 是否真的可用."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url=DEEPSEEK_ENDPOINT, api_key=api_key)
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": "回复：ok"}],
            max_tokens=10,
            extra_body={"thinking": {"type": "disabled"}},
        )
        if resp.choices:
            return True, ""
        return False, "没有收到有效响应"
    except Exception as e:
        return False, str(e)[:200]


def read_config():
    """读取 config.ini（不存在则返回空；内容损坏时尽量沿用其余设置）."""
    if not os.path.exists(CONFIG):
        return configparser.ConfigParser()
    cfg, broken = read_config_file(CONFIG)
    if broken:
        print(f"  ⚠ 配置文件内容有损坏，已跳过异常行并尽量沿用其余设置：{CONFIG}")
    return cfg


def _read_config_text():
    """读取 config.ini 原文（还没配置过就用模板），保留注释和排版."""
    path = CONFIG if os.path.exists(CONFIG) else TEMPLATE
    if not os.path.exists(path):
        raise UserQuit(f"找不到配置文件模板：{path}")
    with open(path, encoding="utf8", errors="replace") as f:
        return f.read()


def update_config(mapping):
    """更新 config.ini 的若干项，保留注释."""
    # mapping: {(section, key): value}
    #
    # 写入前会自动备份，误覆盖也能恢复（见 ~/.chaoxing/backups/）。
    paths.backup_config()

    text = _read_config_text()

    for (section, key), value in mapping.items():
        text = replace_value(text, section, key, str(value))

    with open(CONFIG, "w", encoding="utf8") as f:
        f.write(text)
    return CONFIG





# 通知服务说明
NOTIFY_SERVICES = {
    "1": ("Bark", "https://api.day.app/你的key/", "iPhone 推送到 Bark App，最简单"),
    "2": ("ServerChan", "https://sctapi.ftqq.com/你的key.send", "Server酱，微信推送"),
    "3": ("Telegram", "https://api.telegram.org/bot<token>/sendMessage", "需要额外填 chat_id"),
    "4": ("Qmsg", "https://qmsg.zendee.cn/send/你的key", "QQ 推送"),
}


def setup_notification(existing=None):
    """配置完成通知（可跳过）；返回 (provider, url, tg_chat_id)."""
    if existing is None:
        existing = read_config()

    cur_provider = ""
    cur_url = ""
    cur_tg = ""
    if existing.has_section("notification"):
        cur_provider = (existing.get("notification", "provider", fallback="") or "").strip()
        cur_url = (existing.get("notification", "url", fallback="") or "").strip()
        cur_tg = (existing.get("notification", "tg_chat_id", fallback="") or "").strip()

    title("完成通知（可选）")
    print("  刷课开始 / 完成 / 被中断 / 出错时，推送到手机。")
    if cur_provider and cur_url:
        print("  当前已配置：" + cur_provider)
    print()
    print("   1. Bark        iPhone，最简单")
    print("   2. Server酱    微信")
    print("   3. Telegram    需额外填 chat_id")
    print("   4. Qmsg酱      QQ")
    print("   0. 不用通知")
    print()

    choice = ask("请选择", allow_empty=True)
    if not choice or choice == "0":
        return cur_provider, cur_url, cur_tg

    if choice not in NOTIFY_SERVICES:
        print("  ✘ 没有这个选项，本次跳过。")
        return cur_provider, cur_url, cur_tg

    provider, example, _desc = NOTIFY_SERVICES[choice]
    print("  格式参考：" + example)
    url = ask("推送地址")
    tg_chat_id = ""
    if provider == "Telegram":
        tg_chat_id = ask("chat_id")

    print("  发送测试通知...")
    ok, err = test_notification(provider, url, tg_chat_id)
    if ok:
        print("  ✔ 已发送，请检查手机是否收到")
    else:
        print("  ✘ 发送失败：" + err + "（可能是地址填错）")
        if not ask_yes_no("  仍然保存吗？", default_no=True):
            return cur_provider, cur_url, cur_tg

    return provider, url, tg_chat_id


def test_notification(provider, url, tg_chat_id=""):
    """发一条测试通知，返回 (是否成功, 错误信息)."""
    try:
        import requests
        msg = "超星刷课：这是一条测试通知，收到说明配置成功。"
        if provider == "Bark":
            r = requests.post(url.rstrip("/") + "/" + requests.utils.quote(msg), timeout=10)
        elif provider == "ServerChan":
            r = requests.post(url, data={"title": "超星刷课", "desp": msg}, timeout=10)
        elif provider == "Qmsg":
            r = requests.post(url, data={"msg": msg}, timeout=10)
        elif provider == "Telegram":
            r = requests.post(url, data={"chat_id": tg_chat_id, "text": msg}, timeout=10)
        else:
            return False, "未知的通知服务"
        if r.status_code == 200:
            return True, ""
        return False, "HTTP " + str(r.status_code) + " " + r.text[:120]
    except Exception as e:
        return False, str(e)[:150]


def ask_deepseek_key(existing_key=""):
    """让用户填一个可用的 DeepSeek Key（会联网验证）."""
    print("  地址与模型已预设（" + DEEPSEEK_MODEL + "），只需粘贴 Key。")
    print("  获取：https://platform.deepseek.com/ → API Keys")
    print()

    while True:
        key = ask("DeepSeek API Key")
        print("  验证中...")
        ok, err = verify_deepseek_key(key)
        if ok:
            print("  ✔ 验证通过")
            return key

        # 验证失败：当场给出两条路，不必退出重走 setup
        print("  ✘ " + short_err(err))
        print()
        print("   1. 重新粘贴 Key")
        print("   2. 不做测验，只刷视频 / 文档等部分")
        print()
        choice = ask("请选择")
        if choice == "2":
            return ""      # 空字符串 = 用户放弃答题，转为降级模式
        # 选 1 或其它 -> 继续循环重新粘贴


# 每种答题方式在 config 里必须存在的字段
ANSWER_MODE_REQUIREMENTS = {
    "AI": "key",
    "SiliconFlow": "siliconflow_key",
    "TikuYanxi": "tokens",
    "TikuAdapter": "url",
}

# 答题方式选项（顺序即展示顺序）
ANSWER_MODES = [
    ("1", "AI", "DeepSeek AI", "推荐 · 什么题都能答，无需额外购买", True),
    ("2", "TikuYanxi", "言溪题库", "答案准 · 需 token（tk.enncy.cn）", False),
    ("3", "TikuGo", "GO 题", "答案准 · 可选 authorization", False),
    ("4", "TikuYanxi,AI", "言溪 + AI 兜底", "更准 · 需言溪 token", True),
    ("5", "TikuGo,AI", "GO题 + AI 兜底", "更准 · 可选 authorization", True),
    ("6", "TikuManual", "手动答题", "每题手动输入，最慢", False),
    ("0", "", "不答题", "跳过测验 · 解锁章节会卡住", False),
]


def is_answer_mode_configured(cfg):
    """答题方式是否已经配置过（且必要字段齐全）."""
    #
    # 两种判定，任一成立即视为已配置：
    # 1. 有 [cx] answer_mode_done = yes 标记（新配置走这条路）
    # 2. 没有标记，但 [tiku] 里的字段是齐全的（兼容旧配置）
    #
    # 这样升级后不会让用户重新填一遍。
    if not cfg.has_section("tiku"):
        return False

    provider = (cfg.get("tiku", "provider", fallback="") or "").strip()
    providers = [p.strip() for p in provider.split(",") if p.strip()]

    if providers:
        # 检查每种答题方式需要的字段是否都有值
        for name in providers:
            need = ANSWER_MODE_REQUIREMENTS.get(name)
            if need and not (cfg.get("tiku", need, fallback="") or "").strip():
                return False
        return True

    # provider 为空 = "不答题"，这种需要显式标记才算配置过
    if not cfg.has_section("cx"):
        return False
    return (cfg.get("cx", "answer_mode_done", fallback="") or "").strip() == "yes"


def _configured_answer_mode(cfg):
    """Return the existing provider configuration without prompting for secrets."""
    provider = (cfg.get("tiku", "provider", fallback="") or "").strip()
    existing = {"provider": provider, "_ran": False}
    cur_degraded = (cfg.get("cx", "quiz_degraded", fallback="") or "").strip()             if cfg.has_section("cx") else ""
    existing["_degraded"] = (cur_degraded == "yes")
    for name in [p.strip() for p in provider.split(",") if p.strip()]:
        need = ANSWER_MODE_REQUIREMENTS.get(name)
        if need:
            existing[need] = (cfg.get("tiku", need, fallback="") or "").strip()
    label = "、".join(
        m[2] for m in ANSWER_MODES
        if m[1] == provider
    ) or (provider or "不答题")
    print(f"  答题方式：{label}（已配置，如需修改请运行 cx setup）")
    return provider, existing


def setup_answer_mode(force=False):
    """选择答题方式。返回 (provider字符串, 需要的配置字典)."""
    #
    # 已经配置过且字段齐全时，直接沿用，不再打扰用户。
    # 需要重新配置请用 cx setup（force=True）。
    cfg = read_config()

    # 已配置 -> 直接沿用（_ran=False 表示没有重新配置，不要覆盖已有标记）
    if not force and is_answer_mode_configured(cfg):
        return _configured_answer_mode(cfg)

    cur_key = cfg.get("tiku", "key", fallback="") if cfg.has_section("tiku") else ""

    title("选择答题方式")
    print("  章节测验要答对才能继续往下刷，选一种答题方式：")
    print()
    for num, _p, label, desc, _need_ai in ANSWER_MODES:
        print("   " + num + ". " + _pad(label, 16) + desc)
    print()

    while True:
        choice = ask("请填序号")
        hit = [m for m in ANSWER_MODES if m[0] == choice]
        if hit:
            break
        print("  ✘ 没有这个序号，请重新填。")

    # 表结构是 (序号, provider, 名称, 说明, 是否需要 AI)；顺序错会让题库模式也被追问 Key
    _num, provider, label, _desc, need_ai = hit[0]

    result = {"provider": provider}

    # 不需要任何东西
    if not provider:
        print()
        print("  已选择：不答题（章节测验会被跳过）")
        return provider, result

    # 手动模式
    if provider == "TikuManual":
        print()
        print("  已选择：手动答题（每条题目都会停下来让你输入答案）")
        return provider, result

    # 需要 token 的题库
    if "TikuYanxi" in provider:
        print()
        print("  言溪题库（别人整理好的答案库）需要 token，登录 https://tk.enncy.cn/ 获取")
        print("  有多个 token 可以用英文逗号分隔。")
        print()
        tokens = ask("言溪 token")
        result["tokens"] = tokens

    if "TikuGo" in provider:
        print()
        print("  GO 题可不填 authorization 直接使用（可能限流）。")
        print("  如需解除限流，可在公众号「一之哥哥」申请后填入。")
        print()
        go_auth = ask("GO题 authorization（可留空）", allow_empty=True)
        result["go_authorization"] = go_auth

    # 需要 AI 兜底
    if need_ai:
        if cur_key:
            print("  检测到已保存的 Key，正在验证...")
            ok, err = verify_deepseek_key(cur_key)
            if ok:
                print("  ✔ 已保存的 Key 有效，无需重新填写")
                result["key"] = cur_key
            else:
                print("  ✘ 已保存的 Key 失效了：" + short_err(err))
                result["key"] = ask_deepseek_key()
        else:
            result["key"] = ask_deepseek_key()

        # 用户在填 Key 时选择了"不做测验"
        if not result.get("key"):
            tokens = result.get("tokens") or ""
            go_auth = result.get("go_authorization") or ""
            if tokens or go_auth:
                # 已经填好题库了：只去掉 AI 兜底，不要把用户刚填的 token 丢掉
                plain = "TikuYanxi" if "TikuYanxi" in provider else "TikuGo"
                print("  已切换为「只用题库、不加 AI 兜底」：" + plain)
                return plain, {"provider": plain, "tokens": tokens,
                               "go_authorization": go_auth}
            print("  已切换为「不做测验」模式。")
            return "", {"provider": "", "degraded": True, "_ran": True}

    result["_ran"] = True
    return provider, result


def _provider_needs_ai(provider):
    """这个答题方式是否需要 DeepSeek."""
    names = [p.strip() for p in (provider or "").split(",") if p.strip()]
    return any(n in ("AI", "SiliconFlow") for n in names)


def resolve_invalid_api_key(provider, current_key):
    """API Key 失效时的处理：当场让用户重填，而不是把他踢出去重走 setup."""
    #
    # 返回 (处理结果, 新key)：
    # ("fixed",   新key)   -> 用户重新填了有效的 Key
    # ("degraded", "")     -> 用户确认：不做测验，只刷视频/文档
    # ("abort",    "")     -> 用户放弃
    while True:
        title("DeepSeek API Key 无法使用")
        print("  可能原因：填错了、已失效、或账户余额不足。")
        print("  没有可用的 Key，章节测验就无法作答。")
        print()
        print("   1. 重新填写 API Key")
        print("   2. 不做测验，只刷视频 / 文档等部分")
        print()

        choice = ask("请选择")

        if choice == "1":
            new_key = ask_deepseek_key()
            if new_key:
                return "fixed", new_key
            # 用户在重填过程中选择了"不做测验"
            return "degraded", ""

        if choice == "2":
            print("  确认：只刷「视频 / 文档 / 阅读」等部分，所有测验都会跳过。")
            print("  需要答题才能解锁的章节会卡住，刷不下去。")
            if ask_yes_no("  确认这样做吗？", default_no=True):
                return "degraded", ""
            continue

        return "abort", ""


def ensure_api_key(force=False):
    """确保答题方式已配置好，并验证 Key 是否真的可用."""
    #
    # 已配置时不再重复询问；但会验证 Key —— 失效时当场让用户重填，
    # 或确认降级为"只刷非测验部分"，不需要重走整个 setup。
    provider, conf = setup_answer_mode(force=force)

    degraded = False

    # ---- 验证 AI Key ----
    if conf.get("degraded"):
        # setup_answer_mode 里已经确认过不做测验，不要再问
        degraded = True
        provider = ""
        conf = {"provider": ""}
    elif _provider_needs_ai(provider):
        key = (conf.get("key") or "").strip()

        if key:
            # 已有保存的 Key -> 验证；失效时当场处理，不必重走 setup
            print()
            print("  正在验证 API Key...")
            while True:
                ok, err = verify_deepseek_key(key)
                if ok:
                    print("  ✔ 有效")
                    break

                print("  ✘ " + short_err(err))
                action, new_key = resolve_invalid_api_key(provider, key)
                if action == "fixed":
                    key = new_key
                    continue
                if action == "degraded":
                    degraded = True
                    provider = ""
                    conf = {"provider": ""}
                    print("  已切换为「不做测验」模式。")
                    break
                raise UserQuit("API Key 不可用，用户选择退出")

            # 【关键】把最终生效的 Key 写回 conf。
            # 之前漏了这一步：重填的新 Key 只存在局部变量里，
            # 保存时用的还是 conf["key"]（旧值），导致"校验通过但保存的是旧 Key"。
            if not degraded:
                conf["key"] = key
        else:
            # 没有 Key -> 让用户填（ask_deepseek_key 内部已验证，不用重复验证）
            key = ask_deepseek_key()
            if not key:
                degraded = True
                provider = ""
                conf = {"provider": ""}
                print("  已切换为「不做测验」模式。")
            else:
                conf["key"] = key

    mapping = {
        ("tiku", "provider"): provider,
        ("tiku", "endpoint"): DEEPSEEK_ENDPOINT,
        ("tiku", "model"): DEEPSEEK_MODEL,
        ("tiku", "submit"): "true",
        ("tiku", "cover_rate"): "0.9",
    }
    if "key" in conf:
        mapping[("tiku", "key")] = conf["key"]
    if "tokens" in conf:
        mapping[("tiku", "tokens")] = conf["tokens"]
    if "go_authorization" in conf:
        mapping[("tiku", "go_authorization")] = conf["go_authorization"]

    # 记下"答题方式已配置过"，下次直接沿用
    mapping[("cx", "answer_mode_done")] = "yes"

    # 是否"已确认不做测验"：只在真正走过配置流程时才更新，
    # 否则普通启动会把上次的 yes 覆盖成 no（导致每次都被重新询问）。
    if conf.get("_ran", True):
        mapping[("cx", "quiz_degraded")] = "yes" if degraded else "no"

    update_config(mapping)
    return conf.get("key", "")


# ==================== 全局偏好 ====================

# 推荐刷课配置：不再逐项询问用户，直接用最稳的一套。
# 有观看时长要求的视频在代码里会自动 1 倍速，所以这里的 2x 只影响"播完即可"的视频。
RECOMMENDED_PREFS = {
    "speed": "2",
    "jobs": "2",
    "notopen_action": "continue",
    "work_max_retries": "3",
    "add_learning_count": "false",
    "target_count": "100",
    "task_center_submit_mode": "auto",
}


def prefs_summary() -> str:
    """一行显示本次生效的推荐配置（只在启动时显示一遍，不询问）."""
    return (
        "  推荐配置：" + RECOMMENDED_PREFS["speed"] + " 倍速 · 同时刷 "
        + RECOMMENDED_PREFS["jobs"] + " 个 · 未开放跳过 · 答错重做 "
        + RECOMMENDED_PREFS["work_max_retries"] + " 次 · 自动提交"
    )


def ensure_global_prefs(force=False):
    """全局设置：直接用推荐默认，不再逐项询问."""
    #
    # 首次运行写入推荐配置；之后每次启动只显示一遍当前配置。
    # force=True（cx setup）同样不问刷课参数，只保留可选的通知配置。
    cfg = read_config()
    done = cfg.get("cx", "prefs_done", fallback="") if cfg.has_section("cx") else ""

    if done == "yes" and not force:
        # 一次性迁移（v2）：并发从 4 降到 2——4 个任务并行更容易触发验证码/403
        version = cfg.get("cx", "prefs_version", fallback="1") if cfg.has_section("cx") else "1"
        if version != "2":
            if (cfg.get("common", "jobs", fallback="") or "").strip() == "4":
                update_config({("common", "jobs"): RECOMMENDED_PREFS["jobs"]})
                print("  · 同时刷的任务数已从 4 调整为 2（更稳，能明显减少验证码）")
            update_config({("cx", "prefs_version"): "2"})
        print(prefs_summary())
        return

    provider, url, tg = "", "", ""
    if force or done != "yes":
        # "完成通知"是可选项：第一次运行也问一次（直接回车＝不用），之后不再打扰
        provider, url, tg = setup_notification(cfg)

    update_config({
        ("tiku", "check_llm_connection"): "true",
        ("common", "speed"): RECOMMENDED_PREFS["speed"],
        ("common", "jobs"): RECOMMENDED_PREFS["jobs"],
        ("common", "notopen_action"): RECOMMENDED_PREFS["notopen_action"],
        ("common", "work_max_retries"): RECOMMENDED_PREFS["work_max_retries"],
        ("common", "add_learning_count"): RECOMMENDED_PREFS["add_learning_count"],
        ("common", "target_count"): RECOMMENDED_PREFS["target_count"],
        ("common", "task_center_submit_mode"): RECOMMENDED_PREFS["task_center_submit_mode"],
        ("cx", "prefs_done"): "yes",
        ("cx", "prefs_version"): "2",
        ("notification", "provider"): provider or "",
        ("notification", "url"): url or "",
        ("notification", "tg_chat_id"): tg or "XXXXXX",
    })

    title("全局设置已保存（推荐配置）")
    print(prefs_summary())
    print()


# ==================== 登录 ====================

def do_login(username, password):
    """登录；返回 (chaoxing实例, 昵称) 或 (None, 错误信息)."""
    print()
    print("  正在登录 " + username + "...")
    try:
        from api.base import Chaoxing, Account
        from api import cookies
        cookies.set_current_account(username)
        account = Account(username, password)
        cx = Chaoxing(account=account)
        result = cx.login(login_with_cookies=False)
    except Exception as e:
        return None, str(e)[:150]

    if not result.get("status"):
        return None, str(result.get("msg", "未知原因"))

    name = ""
    try:
        name = cx.get_name()
    except Exception as exc:
        from api.logger import logger
        logger.debug("账号昵称读取失败（{}）", type(exc).__name__)
    return cx, name


def add_new_account():
    """加入新账号：登录成功后保存."""
    title("加入新账号")
    print("  输入手机号和密码，登录成功后自动保存，下次可直接选用。")
    print()

    while True:
        username = ask("手机号")
        password = ask("密码")
        cx, name = do_login(username, password)
        if cx:
            print("  ✔ 登录成功" + ("，欢迎 " + name if name else ""))
            accounts.save_account(username, password, name)
            print("  ✔ 已保存，下次可直接选用")
            return username, password, cx, name
        print("  ✘ 登录失败：" + name)
        print()
        if not ask_yes_no("  重新输入吗？", default_no=False):
            sys.exit(1)


def use_existing(acc):
    """用已保存的账号登录（不重输密码，除非失败）."""
    label = acc.get("name") or acc["username"]
    title("登录 " + label)
    print("  账号：" + acc["username"] + "（已保存密码，无需重输）")

    username = acc["username"]
    password = acc["password"]

    while True:
        cx, name = do_login(username, password)
        if cx:
            print("  ✔ 登录成功" + ("，欢迎 " + name if name else ""))
            accounts.save_account(username, password, name or acc.get("name", ""))
            return username, password, cx, name
        print("  ✘ 登录失败：" + name)
        print("    可能是密码改了，或账号被冻结。")
        print()
        if not ask_yes_no("  重新输入密码吗？", default_no=False):
            sys.exit(1)
        password = ask("密码")


# ==================== 账号管理 ====================

def manage_accounts():
    """删除账号等管理操作."""
    while True:
        saved = accounts.list_accounts()
        title("管理账号")
        if not saved:
            print("  没有已保存的账号")
            return
        for i, a in enumerate(saved, 1):
            print("    [" + str(i) + "] " + (a.get("name") or "(昵称未知)") + "   " + a["username"])
        print()
        print("    [0] 返回")
        print()
        raw = ask_choice("要删除哪个账号的序号",
                         {"0"} | {str(i) for i in range(1, len(saved) + 1)}, default="0")
        if raw == "0":
            return
        target = saved[int(raw) - 1]
        print()
        if not ask_yes_no("  确定删除 " + (target.get("name") or target["username"]) + " 吗？", default_no=True):
            continue
        accounts.delete_account(target["username"])
        from api import cookies
        cookies.clear_cookies(target["username"])
        print("  ✔ 已删除该账号（连同它的登录状态）")


# ==================== 刷课范围 / 选课 ====================

# 选项 -> (刷章节, 刷任务中心)
STUDY_SCOPES = {
    "1": (True, True, False),
    "2": (True, False, False),
    "3": (False, True, False),
    "4": (False, False, True),    # 只刷讨论（模式在下一步单独问）
}

DISCUSSION_MODES = {
    "1": "task",     # 任务里的主题讨论：自动，按课程要求的顺序
    "2": "board",    # 讨论区帖子：先列出来，自己挑
}


def choose_study_scope():
    """选择这次刷什么."""
    #
    # 学习通里「章节（目录）」和「任务中心 · 教学任务」是两套互相独立的学习入口，
    # 记录不互通，所以这里必须明确选一次，不能让配置文件里的默认值替用户决定。
    #
    # 返回 (chapters_enabled, task_center_enabled)。
    title("刷什么内容")
    print("  章节（目录）和任务中心的教学任务是两套独立记录，要分开刷。")
    print("  一个「任务点」就是课程里的一个视频 / 文档 / 测验 / 讨论。")
    print()
    print("   1. 章节 + 任务中心   ✓推荐")
    print("   2. 只刷章节（目录）")
    print("   3. 只刷任务中心（教学任务）")
    print("   4. 只刷讨论（讨论区）")
    print()

    raw = ask_choice("请选择", set(STUDY_SCOPES), default="1")

    chapters, task_center, only_discussion = STUDY_SCOPES[raw]
    if only_discussion:
        print("  → 只刷讨论")
    elif chapters and task_center:
        print("  → 章节 + 任务中心")
    elif chapters:
        print("  → 只刷章节")
    else:
        print("  → 只刷任务中心")

    # 讨论怎么刷：任务里的主题讨论（自动）还是讨论区（自己挑帖子）
    discussion_mode = ""
    if only_discussion or task_center:
        discussion_mode = choose_discussion_mode(required=only_discussion)
    return chapters, task_center, only_discussion, discussion_mode


def choose_discussion_mode(required=False):
    """讨论的两种刷法：自动跟任务，或进讨论区自己挑帖子."""
    title("讨论怎么刷")
    if not required:
        print("  教学任务里本来就包含主题讨论，这里选它怎么刷。")
        print()
    print("   1. 任务里的主题讨论（自动，按课程要求的顺序做）   ✓推荐")
    print("   2. 讨论区（自己挑帖子回复）")
    print()
    raw = ask_choice("请选择", set(DISCUSSION_MODES), default="1")
    mode = DISCUSSION_MODES[raw]
    if mode == "task":
        print("  → 任务里的主题讨论（自动）")
    else:
        print("  → 讨论区（自己挑帖子，逐条给草稿、确认后发送）")
    return mode


def _ask_count(prompt):
    """读一个"刷几个"的数量."""
    #
    # 数字 = 只刷前几个未完成的；all / 全部 / 0（或直接回车）= 全部。
    # 返回 0 表示全部。
    for _ in range(5):
        raw = ask(prompt, default="all")
        low = raw.strip().lower()
        if low in ("all", "全部", "0"):
            return 0
        try:
            n = int(low)
            if n < 0:
                raise ValueError
            return n
        except ValueError:
            print("  ✘ 请填数字（如 3），或填 all 表示全部。")
    print("  · 没收到有效数字，按「全部」继续")
    return 0


def _choose_course_entries(courses):
    """Read valid course indices/IDs with a bounded number of invalid inputs."""
    chosen = None
    tries = 0
    while chosen is None:
        tries += 1
        raw = ask("要刷哪几门？填序号，如 1,3")
        parts = [p.strip() for p in raw.replace("，", ",").replace("、", ",").split(",") if p.strip()]
        picked, bad = [], []
        for p in parts:
            if p.isdigit() and 1 <= int(p) <= len(courses):
                picked.append(courses[int(p) - 1])
            else:
                hit = [c for c in courses if str(c["courseId"]) == p]
                if hit:
                    picked.append(hit[0])
                else:
                    bad.append(p)
        if bad:
            print("  ✘ 没认出来：" + ", ".join(bad))
            if tries >= 5:
                # 非交互输入（管道/重定向）反复给不出有效序号时干净退出，绝不卡死
                print("  · 连续多次没认出课程，已退出向导（重新运行 cx 即可）。")
                sys.exit(1)
            continue
        uniq, seen2 = [], set()
        for c in picked:
            if c["courseId"] not in seen2:
                seen2.add(c["courseId"])
                uniq.append(c)
        chosen = uniq

    return chosen


def choose_courses(cx, ask_points=True, ask_tasks=True, only_discussion=False,
                   discussion_mode=""):
    title("选择课程")
    print("  正在读取课程列表...")

    try:
        all_course = cx.get_course_list()
    except Exception as e:
        print("  ✘ 读取失败：" + short_err(e))
        sys.exit(1)

    if not all_course:
        print("  ✘ 这个账号下没有课程")
        sys.exit(1)

    seen, courses = set(), []
    for c in all_course:
        key = (str(c["courseId"]), str(c["clazzId"]))
        if key not in seen:
            seen.add(key)
            courses.append(c)

    print()
    for i, c in enumerate(courses, 1):
        print("   " + str(i).rjust(2) + ". " + c["title"])
    print()

    chosen = _choose_course_entries(courses)

    print("  已选：" + "、".join(c["title"] for c in chosen))

    # 只刷讨论：不设数量，直接说明这次会怎么刷（模式在上一步已经问过）
    if only_discussion:
        title("这次怎么刷讨论")
        if discussion_mode == "board":
            print("  进入讨论区后先列出帖子，你自己挑要回复哪几条；逐条给草稿、确认后发送。")
        else:
            print("  自动刷任务里的主题讨论：按课程要求的顺序，每条读已有回复后写一条普通回复。")
        print("  讨论不按数量限制（有任务/帖子就会处理）。")
        return [(c, 0, 0) for c in chosen]

    # 两类都不刷的课程不存在；只刷一类时另一类就别问了
    if not ask_points and not ask_tasks:
        return [(c, 0, 0) for c in chosen]

    title("每门课刷多少")
    print("  数字 = 本次刷多少个「还没完成」的，已完成的自动跳过、不会重刷。")
    print("  例：共 300 节、前 150 节已完成，填 150 = 把后面 150 节刷完。")
    print("  all 或直接回车 = 没完成的全部刷完。")
    if ask_points and ask_tasks:
        print("  章节和教学任务各算各的，互不影响。")
    print()

    plan = []
    for c in chosen:
        print("  " + c["title"])
        chapter_n = 0
        task_n = 0
        if ask_points:
            chapter_n = _ask_count("章节：本次刷多少个（只算没完成的）")
            print("    → " + ("没完成的章节全部刷完" if chapter_n == 0
                               else ("从第一节未完成开始，往后刷 " + str(chapter_n)
                                     + " 个（已完成的自动跳过）")))
        if ask_tasks:
            task_n = _ask_count("教学任务：本次刷多少个（只算没完成的）")
            print("    → " + ("没完成的教学任务全部刷完" if task_n == 0
                               else ("从第一个未完成的教学任务开始，往后刷 "
                                     + str(task_n) + " 个（已完成的自动跳过）")))
        plan.append((c, chapter_n, task_n))

    return plan


# ==================== 主流程 ====================

def build_config(username, password, plan, chapters_enabled=True, task_center_enabled=True,
                 only_discussion=False, discussion_mode="task"):
    """写出本次要用的配置（用账号专属文件，不污染全局配置）."""
    paths.backup_config()
    text = _read_config_text()

    course_ids = ",".join(str(c["courseId"]) for c, *_ in plan)
    mp = ",".join(str(c["courseId"]) + ":" + str(chapter_n) for c, chapter_n, _ in plan)
    mt = ",".join(str(c["courseId"]) + ":" + str(task_n) for c, _, task_n in plan)

    text = replace_value(text, "common", "username", username)
    text = replace_value(text, "common", "password", password)
    text = replace_value(text, "common", "course_list", course_ids)
    text = replace_value(text, "common", "notopen_action", "continue")
    # 刷课参数用推荐值：向导不再逐项询问（用户要求"直接按默认最优"）
    text = replace_value(text, "common", "speed", RECOMMENDED_PREFS["speed"])
    text = replace_value(text, "common", "jobs", RECOMMENDED_PREFS["jobs"])
    text = replace_value(text, "common", "work_max_retries", RECOMMENDED_PREFS["work_max_retries"])
    text = replace_value(text, "common", "task_center_submit_mode",
                         RECOMMENDED_PREFS["task_center_submit_mode"])
    # 刷课范围：向导里选了什么就写什么，不再吃全局配置的默认值
    # 只刷讨论也走任务中心链路：必须写成 true，否则启动检查会以为"两个入口都关了"
    text = replace_value(text, "common", "task_center",
                         "true" if (task_center_enabled or only_discussion) else "false")
    text = replace_value(text, "common", "chapter_study", "true" if chapters_enabled else "false")
    text = replace_value(text, "common", "only_discussion",
                         "true" if only_discussion else "false")
    # 没有任务中心的本轮不存在讨论处理方式。显式写 none，避免上一轮的讨论区选择
    # 在下一轮「只刷章节」时被误读成仍要进讨论区。
    mode = discussion_mode if (task_center_enabled or only_discussion) else "none"
    text = replace_value(text, "common", "discussion_mode", mode or "task")
    text = replace_value(text, "common", "max_points_per_course", mp)
    text = replace_value(text, "common", "max_tasks_per_course", mt)
    text = replace_value(text, "common", "use_cookies", "false")
    # 保留 check_llm_connection=true：main.py 启动时会再验证一次 Key。
    # 本流程虽然刚验证过，但保持这道兜底更安全 —— 万一是旧配置/Key 中途失效，
    # 也能在"开始刷课之前"就拦住，而不是刷到测验时才发现（那样会一堆报错）。
    text = replace_value(text, "tiku", "check_llm_connection", "true")
    # 注意：通知配置必须原样保留，不能清空（之前这里会覆盖掉用户配好的通知）

    # 每个用户一份独立配置，避免多用户互相覆盖
    os.makedirs(accounts.ACCOUNTS_DIR, exist_ok=True)
    user_config = os.path.join(accounts.ACCOUNTS_DIR, "run_" + accounts._safe_name(username) + ".ini")
    with open(user_config, "w", encoding="utf8") as f:
        f.write(text)
    try:
        os.chmod(user_config, 0o600)
    except OSError:
        if os.name != "nt":
            raise
    return user_config


def pick_user():
    """选择用户：返回 (username, password, cx, name)."""
    # 没有账号时会引导加入新账号。
    saved = accounts.list_accounts()

    if not saved:
        print("  还没有保存过用户，先加入一个账号。")
        return add_new_account()

    title("选择用户")
    for i, a in enumerate(saved, 1):
        label = a.get("name") or "(昵称未知)"
        when = (a.get("last_used") or "")[5:16]   # 只留 月-日 时:分
        print("   " + str(i) + ". " + _pad(label, 12) + _pad(a["username"], 13) + when)
    print()
    print("   " + str(len(saved) + 1) + ". 加入新账号")
    print("   " + str(len(saved) + 2) + ". 管理账号（删除）")
    print()

    idx_add = len(saved) + 1
    idx_mgr = len(saved) + 2

    raw = ask_choice("请选择", {str(i) for i in range(1, idx_mgr + 1)}, default="1")
    idx = int(raw)
    if idx == idx_mgr:
        manage_accounts()
        return pick_user()
    if idx == idx_add:
        return add_new_account()
    return use_existing(saved[idx - 1])


def ask_after_run(label, cancelled=False):
    """一轮结束后问用户下一步做什么."""
    # 返回 "again"（同账号继续）/ "switch"（换账号）/ "exit"（退出）
    #
    # cancelled=True 表示用户在上一步取消了刷课（此时不能说"刷课结束"）。
    title("接下来做什么")
    if cancelled:
        print("  本次没有刷课（你在确认时取消了）。")
    else:
        print("  刚刷完的账号：" + label)
    print()
    print("   1. 继续刷这个账号的其他课程")
    print("   2. 换个账号刷")
    print("   3. 退出程序")
    print()

    choice = ask_choice("请选择", {"1", "2", "3"}, default="3")
    return {"1": "again", "2": "switch", "3": "exit"}[choice]


def _show_run_confirmation(label, username, plan, chapters_enabled,
                           task_center_enabled, only_discussion, discussion_mode):
    """Display the exact account, courses and scope selected for this run."""
    if only_discussion:
        scope_text = "只刷讨论"
    elif chapters_enabled and task_center_enabled:
        scope_text = "章节 + 任务中心"
    elif chapters_enabled:
        scope_text = "只刷章节"
    else:
        scope_text = "只刷任务中心"
    title("请确认")
    account_text = label or username or "已保存的账号"
    if username and username != account_text:
        account_text = account_text + "（" + username + "）"
    print("  账号  " + account_text)
    print("  范围  " + scope_text)
    if discussion_mode:
        print("  讨论  " + ("讨论区（自己挑帖子，逐条确认后发送）"
                            if discussion_mode == "board"
                            else "任务里的主题讨论（自动）"))
    print("  课程")
    for c, chapter_n, task_n in plan:
        cp = "章节全部" if chapter_n == 0 else ("章节 " + str(chapter_n) + " 个未完成")
        tp = "教学任务全部" if task_n == 0 else ("教学任务 " + str(task_n) + " 个未完成")
        if only_discussion:
            detail = ""     # 上面"讨论"那一行已经说清楚了，这里不再重复
        elif chapters_enabled and task_center_enabled:
            detail = cp + " · " + tp
        elif chapters_enabled:
            detail = cp
        else:
            detail = tp
        print(("        " + _pad(c["title"], 24) + detail).rstrip())
    print()


def _main_inner(force_setup=False):
    title("超星刷课")
    print()
    print("  提示：程序会一步步问你（刷什么、刷哪门、刷多少），有默认值的直接回车就行。")
    print("        在本向导里输入 q 再回车可随时退出，不会刷任何课。")

    # cx --yes：跳过向导最后的人工确认，并把 --yes 传给 main.py 的启动检查
    auto_yes = any(a in ("--yes", "-y") for a in sys.argv[1:])

    # 1. 答题方式：已配置则静默沿用，只有 cx setup 才会重新询问
    ensure_api_key(force=force_setup)

    # 1.5 首次使用或还没配过通知/偏好时，问一次全局设置（存到 config.ini，以后不再问）
    ensure_global_prefs(force=force_setup)

    # 2. 选用户 -> 选课 -> 刷课；刷完再问下一步
    from main import main as run_main

    current = None          # 当前登录的 (username, password, cx, name)
    round_no = 0            # 第几轮

    while True:
        # ---- 选用户（换了账号或第一轮时） ----
        if current is None:
            current = pick_user()
        username, password, cx, name = current
        label = name or username

        # 同一账号继续刷时，明确告诉用户当前是谁
        if round_no > 0:
            title("继续刷课")
            print("  当前账号：" + label + "（" + username + "）")

        # ---- 选刷课范围：章节（目录）/ 任务中心·教学任务 ----
        chapters_enabled, task_center_enabled, only_discussion, discussion_mode = \
            choose_study_scope()

        # ---- 选课 + 逐门设置本次范围（不刷的那一类不问） ----
        plan = choose_courses(cx, ask_points=chapters_enabled, ask_tasks=task_center_enabled,
                              only_discussion=only_discussion,
                              discussion_mode=discussion_mode)

        # ---- 写该用户专属配置 ----
        user_config = build_config(username, password, plan,
                                   chapters_enabled, task_center_enabled, only_discussion,
                                   discussion_mode)

        # ---- 最终确认 ----
        _show_run_confirmation(label, username, plan, chapters_enabled,
                               task_center_enabled, only_discussion, discussion_mode)
        if auto_yes:
            print("  （--yes：跳过确认，直接开始）")
        elif not ask_yes_no("开始刷课吗？", default_no=True):
            print("  已取消，本次不会刷任何课。")
            # 取消了不直接退出，问用户下一步
            action = ask_after_run(label, cancelled=True)
            if action == "again":
                round_no += 1
                continue
            if action == "switch":
                current = None
                round_no += 1
                continue
            break

        # ---- 开刷 ----
        # 关键：清掉上一轮可能残留的终止标志，否则新一轮会立刻停止
        interrupt.reset()
        sys.argv = ["main.py", "-c", user_config] + (["--yes"] if auto_yes else [])
        run_main()

        # ---- 刷完问下一步 ----
        round_no += 1
        action = ask_after_run(label)
        if action == "again":
            continue
        if action == "switch":
            current = None
            continue
        break

    return 0


def main(force_setup=False):
    """统一入口：把一键退出/中断处理成干净退出."""
    try:
        return _main_inner(force_setup=force_setup)
    except UserQuit:
        print()
        print("  已安全退出。")
        print()
        return 0
    except KeyboardInterrupt:
        print()
        print()
        print("  已安全退出（Ctrl+C）。")
        print()
        return 0


if __name__ == "__main__":
    safe_console()
    # cx setup -> 重新配置；cx -> 已配置则直接开始
    _force = "--setup" in sys.argv or "setup" in sys.argv
    sys.exit(main(force_setup=_force))
