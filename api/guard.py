# -*- coding: utf-8 -*-
"""
启动检查（人工确认门禁）

设计目标：零技术基础也能安全使用。
规则：
  1. 账号密码是必填项，没有就停止，不存在"跳过"。
  2. 课程 ID 是必填项，没填就停止，绝不会自动刷全部课程。
  3. 没配 API Key 时，章节测验不会真的作答 —— 必须人工确认后才继续。
"""

import os
import sys

from api import paths
from api.configfile import read_config_file

LINE = "=" * 62


class UserAbort(Exception):
    """用户主动取消 / 未确认"""


def _can_prompt():
    """是否能与用户交互（有终端）"""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _ask_yes(prompt):
    """询问 y/n，默认 n（安全默认）"""
    if not _can_prompt():
        return False
    try:
        ans = input(prompt + " [y/n]\n> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("y", "yes", "是", "1", "true")


def _stop(title, details, how_to_fix):
    """必填项缺失：直接停止，不给继续选项"""
    print()
    print(LINE)
    print("  ✘  " + title)
    print(LINE)
    print(details)
    print()
    print("  怎么解决：")
    print(how_to_fix)
    print()
    print("  程序已停止，不会执行任何刷课操作。")
    print()
    raise UserAbort(title)


def hard_stop(title, details, how_to_fix):
    """必填项/配置错误：直接停止（供其它模块在启动检查之外调用）"""
    _stop(title, details, how_to_fix)


def _confirm(title, details, how_to_fix):
    """可继续项：必须人工确认，默认 N"""
    print()
    print(LINE)
    print("  ⚠️  " + title)
    print(LINE)
    print(details)
    print()
    print("  怎么解决：")
    print(how_to_fix)
    print()
    if _ask_yes("  你已了解以上情况，仍要继续运行吗？"):
        print("  → 已确认，继续运行。")
        print()
        return
    raise UserAbort("用户未确认: " + title)


# 各答题方式需要的配置项：(provider, 需要的键, 缺失时怎么说明)
_PROVIDER_REQUIREMENTS = {
    "AI": ("key", "DeepSeek API Key", "https://platform.deepseek.com/ 创建"),
    "SiliconFlow": ("siliconflow_key", "硅基流动 API Key", "https://cloud.siliconflow.cn/account/ak 获取"),
    "TikuYanxi": ("tokens", "言溪题库 token", "https://tk.enncy.cn/ 购买"),
    "TikuAdapter": ("url", "TikuAdapter 服务地址", "自行部署 tikuAdapter 后填写地址"),
}

# 不需要额外配置的答题方式
_PROVIDER_NO_CONFIG = {"TikuGo", "TikuManual"}


def _quiz_degraded_confirmed():
    """用户是否已经确认过"不做测验，只刷非测验部分" """
    try:
        cfg, _broken = read_config_file(paths.config_path())
        if not cfg.has_section("cx"):
            return False
        return (cfg.get("cx", "quiz_degraded", fallback="") or "").strip() == "yes"
    except Exception:
        return False


def _check_answer_provider(tiku_config):
    """按实际选择的答题方式检查配置，返回需要人工确认的问题列表"""
    provider_str = (tiku_config.get("provider") or "").strip()

    # 没选答题方式：用户明确选了"不答题"，或配置缺失
    if not provider_str:
        # 用户在引导里已经确认过"不做测验，只刷非测验部分" -> 不再重复询问
        if _quiz_degraded_confirmed():
            return []
        return [{
            "title": "没有配置答题方式（章节测验会被跳过）",
            "details": "  所有章节测验都不会真的作答，这些任务点会显示未完成。\n"
                       "  需要答题解锁的章节会卡住刷不下去。",
            "fix": "  运行 cx setup 选择答题方式（推荐第 1 项 DeepSeek AI）",
        }]

    providers = [p.strip() for p in provider_str.split(",") if p.strip()]
    problems = []
    missing = []

    for name in providers:
        # 手动答题 / GO题：不需要额外配置
        if name in _PROVIDER_NO_CONFIG:
            continue

        if name not in _PROVIDER_REQUIREMENTS:
            missing.append(f"{name}（未知的答题方式）")
            continue

        key_name, label, how = _PROVIDER_REQUIREMENTS[name]
        if not (tiku_config.get(key_name) or "").strip():
            missing.append(f"{label}（{how}）")

    if missing:
        detail_lines = "\n".join("    · " + m for m in missing)
        problems.append({
            "title": "答题方式缺少必要的配置",
            "details": "  当前答题方式：" + provider_str + "\n"
                       "  缺少以下配置：\n" + detail_lines + "\n"
                       "  缺少时相关章节测验无法作答，需要解锁的章节会卡住。",
            "fix": "  运行 cx setup 重新配置答题方式",
        })

    return problems


def check_before_run(common_config, tiku_config, notification_config, config_path,
                     skip_confirm=False):
    """
    启动前检查。
    skip_confirm=True（--yes）只对"可继续项"生效；必填项缺失永远停止。
    """
    hard = []      # 必填项缺失 -> 一律停止
    soft = []      # 需要人工确认

    # ---- 1. 账号（必填，无"跳过"） ----
    username = (common_config.get("username") or "").strip()
    password = (common_config.get("password") or "").strip()
    use_cookies = common_config.get("use_cookies", False)
    if not use_cookies and (not username or not password):
        hard.append({
            "title": "没有填写登录账号（手机号 / 密码是必填项）",
            "details": "  程序需要账号才能登录学习通，这一项不能跳过。",
            "fix": "  运行 cx setup 填写",
        })

    # ---- 2. 课程 ID（必填，不自动全刷） ----
    course_list = common_config.get("course_list")
    if not course_list:
        hard.append({
            "title": "没有填写要刷的课程 ID",
            "details": "  为避免误刷你账号下的全部课程，必须明确指定要刷哪些课。",
            "fix": "  运行 cx setup 填写",
        })

    # ---- 3. 配置文件不存在 ----
    # 只有"明确指定了 -c 配置文件但文件不在"才算致命。
    # 纯命令行模式（python main.py -u 手机号 -p 密码 -l 课程ID）本来就不需要配置文件，
    # 不能因为没传 -c 就拦死（#567）。
    if config_path and not os.path.exists(config_path):
        hard.append({
            "title": "没有找到配置文件 " + str(config_path),
            "details": "  你指定了 -c 参数，但这个文件不存在，账号/课程设置读不到。",
            "fix": "  运行 cx setup 生成，或去掉 -c 用命令行参数运行",
        })

    # ---- 4. 答题方式检查（可继续，但需确认） ----
    soft.extend(_check_answer_provider(tiku_config or {}))

    # 必填项缺失：无条件停止（--yes 也不能绕过）
    for p in hard:
        _stop(p["title"], p["details"], p["fix"])

    if not soft:
        print("  ✔ 启动检查通过")
        return

    if skip_confirm:
        print()
        print(LINE)
        print("  ⚠️  以下情况因 --yes 被视为已确认：")
        for p in soft:
            print("    · " + p["title"])
        print(LINE)
        print()
        return

    for p in soft:
        _confirm(p["title"], p["details"], p["fix"])
