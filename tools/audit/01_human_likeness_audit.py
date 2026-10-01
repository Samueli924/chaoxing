# -*- coding: utf-8 -*-
"""真人化审计：检查"发给老师/同学看"的文本与作答行为是否像真人."""
#
# 协议约束：
# 为了"提高判分通过率"，AI实践的选择题被拼成了
# "选 D。D：……。依据：回答正确！你的回答正确。本题考核知识点为业务层战略……"
# —— 选择题本该只回选项字母，而且把平台的反馈原文当"依据"回显，
# 既是自曝 AI，也确实不像人在答题。这个审计器就是防止同类问题再出现。
#
# 用法：
# python tools/audit/01_human_likeness_audit.py                    # 审计内置样例文件
# python tools/audit/01_human_likeness_audit.py --samples x.json    # 审计指定样例
# python tools/audit/01_human_likeness_audit.py --selftest          # 只跑规则自检
#
# 样例 JSON：[{"kind": "思考题|作业简答|主题讨论|AI实践开放题|AI实践客观题", "prompt": "...", "text": "..."}]
import argparse
import json
import os
import re
import statistics
import sys

# ---------------------------------------------------------------- 规则

# 1) 模板腔 / AI 腔
AI_PHRASES = [
    "首先", "其次", "再次", "最后", "总之", "总而言之", "综上所述", "总的来说",
    "值得注意的是", "不难看出", "由此可见", "希望对你有所帮助", "作为一名学生",
    "让我们一起来看看", "在当今社会", "随着社会的发展", "具有重要意义",
]
# 2) 把平台反馈/判分回显进作答（最严重：直接暴露在对话里）
LEAK_PHRASES = [
    "回答正确", "回答错误", "真遗憾", "本题考核知识点", "平台判据", "依据：",
    "已评估", "答案解析", "参考答案",
]
# 3) markdown / 排版痕迹
TEMPLATE_PATTERNS = [
    (r"^\s*[-*•]\s", "列表符号"),
    (r"^\s*\d+[.、]\s", "编号列表"),
    (r"\*\*", "markdown 加粗"),
    (r"```", "代码块"),
    (r"^\s*#+\s", "markdown 标题"),
    (r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "emoji"),
]
# 4) 口语/个人痕迹（长文本至少要有几个，否则像说明文）
COLLOQUIAL = ["我觉得", "感觉", "其实", "反正", "可能", "大概", "挺", "有点", "吧", "呢", "哦"]
# 5) 具体性（要有例子，不能只讲概念）
SPECIFIC = ["比如", "例如", "像", "课", "身边", "上次", "之前", "小组", "案例",
            "平台", "品牌", "公司", "门店", "客户", "宿舍", "同学", "老师", "群", "楼"]
# 6) 结尾金句收束：每篇都交一句"可被引用的结论"是最强的机器指纹（第二遍独立审计提出）
CLOSING_CLICHE = [
    (r"不是[^。！？]{0,24}而是", "「不是……而是……」式对照收尾"),
    (r"并非[^。！？]{0,24}而是", "「并非……而是……」式收尾"),
    (r"真正(难|重要|关键)的是", "「真正难的是……」式金句"),
    (r"说到底", "「说到底」式总结"),
    (r"这才是", "「这才是」式收尾"),
    (r"归根到底", "「归根到底」式总结"),
]
# 7) 无来源的"假具体"：既模糊又当事实用，老师一问就穿（第二遍独立审计提出）
UNSOURCED_SPECIFIC = [
    (r"某(个|家|一)?(公司|企业|品牌|区域|城市|行业|领域|产线)", "「某公司/某领域」式虚构"),
    (r"多少(小时|天|单|人)", "「多少小时/多少单」式虚构"),
    (r"几十(单|万|个)", "「几十单」式圆整数据"),
    (r"近(三|两)年(的)?(数据|指标)", "「近三年数据」式无来源数字"),
    (r"(一些|不少|部分)(做|的)?[^，。；]{0,10}(品牌|企业|公司|商家|机构)", "「一些/不少+主体」无来源断言"),
    (r"之前(看过|了解过|刷到过)[^，。；]{0,12}(案例|例子|新闻)", "「之前看过一个案例」无出处"),
    (r"(往往|通常|多半|一般都会)[^。！？]{0,24}(总部|客户|一线|市场|财务|生意|老板|公司)",
     "「往往……」式无来源断言"),
]
# 7.5) 有标记的口癖（"吧/呢/哦"这类语气词不算，它们本来就是口语）
MARKED_HABIT = ["我觉得", "其实", "反正", "可能", "感觉", "挺", "有点"]
# 7.6) 三层递进/对偶收尾：同一账号多篇用同一套结构，是最容易被看出的破绽
STRUCTURE_CLICHE = [
    (r"从[^，。；]{0,14}到[^，。；]{0,14}再到", "「从……到……再到……」排比"),
    (r"[^，。；]{0,12}管的是[^，。；]{0,14}，[^，。；]{0,12}(管|是)的是", "「A 管……B 管……」三段式"),
    (r"[^，。；]{0,10}管[^，。；]{0,8}，[^，。；]{0,10}管[^，。；]{0,8}，[^，。；]{0,10}管", "「A 管X，B 管Y，C 管Z」三段式"),
    (r"先[^，。；]{0,10}再[^，。；]{0,10}(最后|才能|然后)", "「先……再……」递进"),
    (r"不是[^，。；]{0,14}，(而)?是[^，。；]{0,16}", "「不是……而是……」对偶（含段中）"),
]
# 7.7) 编造的第一人称琐事
FAKE_PERSONAL = [
    (r"我(上个月|上上个月|前几天|上周|最近|上次|昨天)(注册|下载|买了|报名|参加|去|跟|面)",
     "编造的个人琐事"),
    (r"我(一个|有个)(朋友|同学|亲戚)(跟|在|做|说)", "编造的朋友/同学经历"),
    # 编造履历：这份工具是替一个在校学生写作业，本人不会有"我实习/我上班"的真实素材
    (r"我(之前|以前|原来|上家|上一家|曾经)?[^，。；]{0,6}(实习|上班|就职|入职)",
     "编造的个人履历（实习/工作）"),
    # 兼职/打工同样是编的（实测模型会写"我在奶茶店做过兼职"）
    (r"我(在|曾经在)[^，。；]{0,8}(兼职|打工|上班|实习)",
     "编造的个人履历（兼职/打工）"),
    (r"我(做|干|打)过[^，。；]{0,4}(兼职|暑假工|临时工|小时工)",
     "编造的个人履历（兼职/打工）"),
    (r"我们(公司|单位|企业)(里|的|在|要求|规定|考核)", "认领在职经历（我们公司/单位）"),
]
# 7.8) 引用不存在的前文（讨论区里"楼上/那个例子"必须真的存在）
DANGLING_REFERENCE = r"(楼上|前面(的|那位|同学)|刚才那位|那个例子|有同学说|接上一个)"
# 7.9) 认领共同经历：没有素材就是编的
CLAIMED_COMMUNITY = [
    (r"我们(小组|班|社团|团队)(上次|之前|课上|讨论|做|在)", "认领小组/社团经历"),
    (r"课上(讲|说|提)(过|的)", "声称课上讲过（除非真有课程材料）"),
]
# 7.10) 示弱收尾口癖（防"金句收尾"引出的同构替换品）
WEAK_ENDING = [
    (r"(没太想明白|没完全(想|搞)明白|还在(琢磨|想)|也说不好|没搞懂|没想清楚)[。？!]*$",
     "用\"我没想明白\"收尾"),
]
# 7.11) 普适经验断言
UNIVERSAL_CLAIM = [
    (r"(往往|通常|多半|一般都会)[^。！？]{0,24}(总部|客户|一线|市场|财务|生意|老板|公司)",
     "\"往往……\"式无来源断言"),
]
# 7.12) 课程锚点
COURSE_ANCHOR = ["课上", "教材", "老师", "这门课", "本章", "课本"]
# 8) 真实犹豫：长文至少要有一处，否则过于顺滑
HESITATION = ["说不好", "记不清", "没太想明白", "不太确定", "可能吧", "也说不准",
              "没完全", "有点乱", "？", "?", "大概是", "好像", "应该", "印象里",
              "之类", "吧", "呢", "估计"]

OBJECTIVE_KINDS = {"AI实践客观题"}
CHOICE_RE = re.compile(r"^[A-E]{1,5}$")
JUDGE_RE = re.compile(r"^[对错]$")


def _first_pattern_issue(text, patterns, category):
    """Return the first matching warning in a pattern category."""
    for pattern, name in patterns:
        if re.search(pattern, text):
            return [(category, name)]
    return []


def audit_sample(sample: dict) -> list:
    kind = str(sample.get("kind") or "")
    text = str(sample.get("text") or "")
    issues = []

    if kind in OBJECTIVE_KINDS:
        # 选择题/判断题就该是"字母/对错"，多余的解释性文字本身就是破绽
        if not (CHOICE_RE.match(text.strip()) or JUDGE_RE.match(text.strip())):
            issues.append(("客观题格式", "客观题应只回选项字母或对错，实际: " + text[:40]))
        return issues

    for phrase in AI_PHRASES:
        if phrase in text:
            issues.append(("AI 腔", f"出现模板词「{phrase}」"))
    for phrase in LEAK_PHRASES:
        if phrase in text:
            issues.append(("回显平台判分", f"出现「{phrase}」"))
    for pattern, name in TEMPLATE_PATTERNS:
        if re.search(pattern, text, re.M):
            issues.append(("排版痕迹", f"出现{name}"))

    sentences = [s for s in re.split(r"[。！？!?\n]", text) if s.strip()]
    if len(sentences) >= 4:
        lengths = [len(s) for s in sentences]
        # 只有"句句都是长句且长度几乎一致"才像模板；几句短句长度接近不算问题
        if statistics.pstdev(lengths) < 6 and min(lengths) >= 25:
            issues.append(("句子过于整齐", "全是长度接近的长句，像模板生成"))
    # 口癖分布：不是"用得太多"才算，均匀撒不同口癖同样是机器特征
    habit = {word: text.count(word) for word in MARKED_HABIT if text.count(word)}
    habit_limit = max(2, len(text) // 120)
    if len(habit) > habit_limit or any(count >= 3 for count in habit.values()):
        issues.append(("口癖分布过密", f"不同口癖 {len(habit)} 种 > 上限 {habit_limit}: {habit}"))
    # 金句：全篇扫描（"说到底"在首句、比喻收尾都要算）
    issues.extend(_first_pattern_issue(text, CLOSING_CLICHE, '金句'))
    # 无来源的假具体
    issues.extend(_first_pattern_issue(text, UNSOURCED_SPECIFIC, '无来源的假具体'))
    # 编造的第一人称琐事
    issues.extend(_first_pattern_issue(text, FAKE_PERSONAL, '编造的个人琐事'))
    # 三层排比/对偶：全篇扫描（只看结尾会被"金句位移"绕过，第四、五轮审计都指出）
    issues.extend(_first_pattern_issue(text, STRUCTURE_CLICHE, '三层排比/对偶'))
    # 讨论里引用前文：必须真的带上了被引用的原文（context_refs 是列表），
    # 之前用 has_context=True 就整条跳过是个后门——生成侧自己申报可不算数
    refs = sample.get("context_refs")
    has_refs = isinstance(refs, list) and any(str(r).strip() for r in refs)
    if kind == "主题讨论" and not has_refs and re.search(DANGLING_REFERENCE, text):
        issues.append(("引用不存在的前文", "没有提供被引用的原文，孤立提交时会露馅"))
    # 认领共同经历：context_refs 只能豁免"引用已有回复"，豁免不了新的共同经历声明
    issues.extend(_first_pattern_issue(text, CLAIMED_COMMUNITY, '认领共同经历'))
    # 示弱收尾口癖
    issues.extend(_first_pattern_issue(text.strip(), WEAK_ENDING, '示弱收尾口癖'))
    # 普适经验断言
    issues.extend(_first_pattern_issue(text, UNIVERSAL_CLAIM, '普适经验断言'))
    # 思考题/作业简答要有课程锚点（题目常写"结合课程内容"）
    if kind in {"思考题", "作业简答"} and len(text) >= 60 \
            and not any(word in text for word in COURSE_ANCHOR):
        issues.append(("没有课程锚点", "题目要求结合课程内容，通篇没提课/教材/老师"))
    return issues


def audit_warnings(sample: dict) -> list:
    """软提醒：不构成"一眼假"，但独立审计时值得看的信号."""
    kind = str(sample.get("kind") or "")
    text = str(sample.get("text") or "")
    warnings = []
    sentences = [s for s in re.split(r"[。！？!?\n]", text) if s.strip()]
    # 犹豫词不再算"人味"证据：提示词里就要求过，审计再拿它当证据是自我验证（第五轮审计指出）
    human_marker = (any(word in text for word in COLLOQUIAL)
                    or any(len(s) <= 12 for s in sentences))
    if len(text) >= 200 and not human_marker:
        warnings.append(("缺少人味", "200 字以上没有口语/犹豫/短句，像说明文"))
    if len(text) >= 100 and not any(word in text for word in SPECIFIC):
        warnings.append(("缺少具体例子", "通篇概念，没有具体的人/公司/场景"))
    limit = 200 if kind == "主题讨论" else (560 if kind == "AI实践开放题" else 700)
    if len(text) > limit:
        warnings.append(("偏长", f"{len(text)} 字，{kind} 一般写得更短"))
    return warnings


# 开头骨架：把"课上…讲过"这类归一化后再统计，避免换个知识点就绕过雷同检测
OPENING_SKELETON = re.compile(r"^(课上|我们课上|这门课|课堂上)[^，。；]{0,20}(讲|说|提|把|拆)")


def _pattern_counts(samples, patterns, window):
    """Count matching patterns in each sample's final characters."""
    counts = {}
    for sample in samples:
        tail = str(sample.get("text") or "").strip()[-window:]
        for pattern, name in patterns:
            if re.search(pattern, tail):
                counts[name] = counts.get(name, 0) + 1
    return counts


def _batch_audit(report, samples, skeleton_hits):
    """Add warnings for structures repeated across an entire batch."""
    # 跨样例指纹：同一批次里结尾都是同一种收束/同一个口癖，整批就很可疑
    ending_hits = _pattern_counts(samples, CLOSING_CLICHE, 30)
    habit_hits = {word: sum(word in str(sample.get("text") or "") for sample in samples)
                  for word in MARKED_HABIT}
    total = max(1, len(samples))
    for name, count in ending_hits.items():
        if count >= max(2, total // 2 + 1):
            report["items"][0]["issues"].append(
                ("整批收尾雷同", f"{count}/{total} 条都用「{name}」收尾"))
    # 跨篇结构雷同：同一套排比/递进公式在多篇里复用
    structure_hits = _pattern_counts(samples, STRUCTURE_CLICHE, 80)
    for name, count in structure_hits.items():
        if count >= 2:
            report["items"][0]["issues"].append(
                ("整批结构雷同", f"{count}/{total} 条共用「{name}」"))
    if len(skeleton_hits) >= 2:
        report["items"][0]["issues"].append(
            ("整批开头骨架雷同", f"{len(skeleton_hits)}/{total} 条都用「课上+讲/把+知识点」开头"))
    repeated = {word: count for word, count in habit_hits.items() if total >= 2 and count >= total}
    if repeated:
        report["items"][0]["issues"].append(
            ("整批口癖雷同", f"每条都用了 {list(repeated.keys())}"))


def audit_all(samples: list) -> dict:
    report = {"samples": len(samples), "items": []}
    openings = {}
    skeleton_hits = []
    texts = []
    for sample in samples:
        issues = audit_sample(sample)
        warnings = audit_warnings(sample)
        text = str(sample.get("text") or "")
        opening = text[:12]
        if opening:
            openings[opening] = openings.get(opening, 0) + 1
        if OPENING_SKELETON.match(text.strip()):
            skeleton_hits.append(sample.get("kind"))
        for other in texts:
            if text and text == other:
                issues.append(("重复内容", "与另一条样例完全相同"))
                break
        texts.append(text)
        report["items"].append({
            "kind": sample.get("kind"),
            "prompt": str(sample.get("prompt") or "")[:60],
            "text": text[:120],
            "issues": issues,
            "warnings": warnings,
        })
    for opening, count in openings.items():
        if count > 1:
            for item in report["items"]:
                if str(item.get("text") or "").startswith(opening):
                    item["issues"].append(("开头雷同", f"有 {count} 条样例用同样的开头"))
    _batch_audit(report, samples, skeleton_hits)
    report["problems"] = sum(len(item["issues"]) for item in report["items"])
    report["warnings_total"] = sum(len(item.get("warnings") or []) for item in report["items"])
    return report


def print_report(report: dict) -> None:
    print(f"审计样例 {report['samples']} 条，硬伤 {report['problems']} 处，"
          f"软提醒 {report.get('warnings_total', 0)} 处")
    print("（硬伤必须改；软提醒交给第二遍独立审计判断，不能只看这一份报告）")
    for item in report["items"]:
        flag = "✗" if item["issues"] else "✓"
        print(f"  {flag} [{item['kind']}] {item['text'][:60]}")
        for rule, detail in item["issues"]:
            print(f"      - 硬伤/{rule}: {detail}")
        for rule, detail in item.get("warnings") or []:
            print(f"      · 提醒/{rule}: {detail}")


def selftest() -> int:
    bad = [
        {"kind": "AI实践客观题", "text": "选 D。D：职能层战略需要支撑企业总体战略。依据：回答正确！"},
        {"kind": "思考题", "text": "首先，使命很重要。其次，愿景很重要。最后，目标也很重要。"},
        {"kind": "主题讨论", "text": "**我觉得**这个问题的答案是" + "好的。" * 30},
    ]
    good = [
        {"kind": "AI实践客观题", "text": "D"},
        {"kind": "主题讨论", "text": "使命和考核对不上，墙上那句话很快就没人提了，这个反差课下聊起来挺有意思。"},
    ]
    bad_report = audit_all(bad)
    good_report = audit_all(good)
    ok = bad_report["problems"] >= 3 and good_report["problems"] == 0
    print("自检:", "通过" if ok else "失败", "| 反例问题数", bad_report["problems"], "| 正例问题数", good_report["problems"])
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", help="JSON samples to audit")
    parser.add_argument("--report", help="Optional JSON report destination")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.samples:
        parser.error("--samples is required unless --selftest is selected")
    if not os.path.exists(args.samples):
        print("找不到样例文件:", args.samples)
        return 2
    with open(args.samples, encoding="utf-8") as source:
        samples = json.load(source)
    report = audit_all(samples)
    print_report(report)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as destination:
            json.dump(report, destination, ensure_ascii=False, indent=1)
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
