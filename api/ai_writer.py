# -*- coding: utf-8 -*-
"""生成并检查问答和讨论回复."""
#
# 任务中心的问答（思考题、作业简答）和主题讨论不能用模板腔：
# 平台上老师和同学一眼就能看出 AI 味，讨论区还要求和其他同学的回复风格一致。
#
# 这个模块负责两件事：
# 1. 用配置里的大模型（[tiku] 段的 endpoint / key / model）生成内容
# 2. 严格"去 AI 味"：提示词约束 + 生成后清洗 + 长度/风格对齐参考文本
#
# 注意：这里只负责写字，不负责任何提交动作。

import configparser
import json
import os
import re
import statistics
import time
from typing import Optional

import requests
from loguru import logger

from api import llm
from api import paths
from api.privacy import register_config

# 一眼假的 AI 腔，生成后直接替换/删掉
# 这些词出现在句首/段首就是模板腔，连同后面的顿断一起删掉
AI_SMELL_PATTERNS = [
    (r"(^|[。！？!?\n])[ \t]*(首先|其次|再次|最后|另外|此外|总之|总而言之|综上所述|总的来说|值得注意的是)[，,：:]?", r"\1"),
    (r"(^|[。！？!?\n])[ \t]*(作为一名|作为一个|作为一位)[^，,。]{0,12}[，,]", r"\1"),
    (r"(希望(这个|以上)?(回答|内容|讨论)?(对你|对大家)?(有所)?帮助)[。！!]?", ""),
    (r"(如有(任何)?(疑问|问题|需要)[^。]{0,20})[。！!]?", ""),
    (r"(让我们(一起)?(来)?(看看|探讨|学习))[^。]{0,10}[。！!]?", ""),
]
MARKDOWN_NOISE = re.compile(
    r"\x60{3}.*?\x60{3}|^#{1,6}[ \t]*|^[ \t]*[-*+][ \t]+|^[ \t]*\d+[.、][ \t]*",
    re.M | re.S,
)


class HumanLikeWriter:
    """用大模型生成"像真人写的"课程问答 / 讨论回复."""

    def __init__(self, tiku_config: Optional[dict] = None, config_path: Optional[str] = None):
        """Initialize configuration and runtime state."""
        cfg = dict(tiku_config or {})
        if not cfg:
            cfg = self._read_tiku_config(config_path)
        register_config(cfg)
        self.endpoint = (cfg.get("endpoint") or "").strip()
        self.key = (cfg.get("key") or "").strip()
        self.model = (cfg.get("model") or "").strip()
        self.proxy = (cfg.get("http_proxy") or "").strip() or None
        # thinking 策略：auto 让模型自己推理（V4.1 flash 默认带推理，写作质量更好）
        self.thinking = llm.normalize_thinking(cfg.get("thinking", "auto"))
        try:
            self.interval = float(cfg.get("min_interval_seconds") or 0)
        except (TypeError, ValueError):
            self.interval = 0.0
        self._last_call = 0.0

    @staticmethod
    def _read_tiku_config(config_path: Optional[str] = None) -> dict:
        path = config_path or paths.config_path()
        if not os.path.exists(path):
            return {}
        parser = configparser.ConfigParser()
        try:
            parser.read(path, encoding="utf-8")
            return dict(parser.items("tiku")) if parser.has_section("tiku") else {}
        except Exception:
            return {}

    @property
    def available(self) -> bool:
        return bool(self.endpoint and self.key and self.model)
    def _thinking_steps(self) -> list:
        """按配置的 thinking 模式返回尝试顺序（默认 auto：先让模型自己推理）."""
        return llm.thinking_steps(self.thinking)

    # ------------------------------------------------------------------ 底层

    def _chat(self, system: str, user: str, temperature: float = 0.95, max_tokens: int = 800) -> str:
        if not self.available:
            raise RuntimeError("没有配置可用的大模型（[tiku] endpoint / key / model）")
        if self.interval > 0 and self._last_call:
            wait = self.interval - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
        url = self.endpoint.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        steps = self._thinking_steps()
        for index, step in enumerate(steps):
            payload.pop("thinking", None)
            payload.update(llm.thinking_payload(step))
            try:
                resp = requests.post(
                    url,
                    headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
                    json=payload,
                    proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None,
                    timeout=60,
                )
            except Exception as exc:
                if payload.get("thinking") and llm.is_thinking_param_error(exc) and index + 1 < len(steps):
                    continue
                raise
            self._last_call = time.time()
            if resp.status_code >= 400:
                # 有的部署不认 thinking 参数：去掉它再试一次
                if payload.get("thinking") and index + 1 < len(steps) and "thinking" in (resp.text or "").lower():
                    continue
                resp.raise_for_status()
            data = resp.json()
            content = (data["choices"][0]["message"]["content"] or "").strip()
            if content:
                return content
            logger.debug("大模型第 {} 档 thinking={} 返回空内容（model={}）", index + 1, step, self.model)
            if index + 1 < len(steps):
                time.sleep(1.0)
                continue
        raise RuntimeError("大模型连续返回空内容，拿不到可用文本（检查 model / thinking / max_tokens 配置）")

    # ------------------------------------------------------------ 去 AI 味

    @staticmethod
    def clean(text: str) -> str:
        """把明显的 AI 腔和 markdown 痕迹洗掉."""
        if not text:
            return ""
        text = MARKDOWN_NOISE.sub("", text)
        for pattern, repl in AI_SMELL_PATTERNS:
            text = re.sub(pattern, repl, text, flags=re.M)
        # 破折号是中文里很常见的停顿，别一律替换成逗号：全文都没有破折号本身就是一种"机器排版"
        text = text.replace("**", "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text).strip()
        return text

    @staticmethod
    def style_reference(posts) -> str:
        """把同学们的回复整理成风格参考（长度、口吻、用词）."""
        lines = []
        for index, post in enumerate(posts or [], 1):
            if isinstance(post, dict):
                content = post.get("content") or post.get("text") or ""
            else:
                content = str(post)
            content = re.sub(r"\s+", " ", content).strip()
            if content:
                lines.append(str(index) + ". " + content[:160])
        return "\n".join(lines)

    # ------------------------------------------------------------ 对外接口

    SYSTEM_STYLE = (
        "你在帮一名普通本科生写课程平台上的作业/讨论内容。"
        "写出来的东西必须像一个真人随手打的，不能有 AI 腔：\n"
        "1. 禁止出现：首先、其次、最后、总之、总而言之、综上所述、值得注意的是、"
        "总的来说、希望对你有所帮助、作为一名学生、让我们一起来看看。\n"
        "2. 不要用整齐的分点罗列，不要写小标题，不要用 emoji，不要用 markdown。\n"
        "3. 句子长短要拉开：至少有一句 12 字以内的短句，不要每句都是四五十字的长句。\n"
        "4. 口语词（我觉得、其实、反正、可能、感觉、挺、有点）整段最多用 2 次，"
        "更不要每个段落都用同一个词；结尾不要用\"反正……\"这类泛泛的总结，"
        "可以停在一个具体的观察、疑问或没解决的地方。\n"
        "5. 不许编造个人履历和查不到的数据：不要写\"我实习的公司\"\"我是部门负责人\""
        "\"客户留存/毛利/三年数据\"这类真伪可被当面核对的内容。想举例子就用"
        "课堂上讲过的概念、公开报道的案例，或者写成假设句（\"如果我在那样的公司……\"）。\n"
        "6. 例子要具体但不要用全网答案库里最烂大街的那几个（强生信条、阿里 102 年、"
        "双减教培、PEST 定义……），尽量用身边可感知的场景或课上的案例。\n"
        "7. 结构上不要'起承转合金句收尾'：全文最多一句总结，结尾禁止用"
        "\"不是……而是……\"\"真正难的是\"\"说到底\"这类可被引用的金句；"
        "也**不要**拿\"我还没太想明白\"\"我也在琢磨\"当固定收尾——那只是换了个样子的口癖。"
        "结尾朴素地停在一个具体观察上就行，允许话没说完，但不要刻意示弱。\n"
        "7.1 思考题/作业简答这类要评分的内容，不要示弱收尾，也不要通篇不表态。\n"
        "7.2 不许认领共同经历：\"我们小组上次讨论\"\"社团活动时\"\"课上讲的某个案例\""
        "这类说法必须有素材支撑；没给素材就只写课程概念、公开报道或假设句。\n"
        "7.3 不许写\"往往/通常/多半\"开头的普适经验断言（例：\"总部给的模型和一线看到的往往差很多\"），"
        "这类句子既没有来源又容易被追问。\n"
        "7.4 回答要围绕题目里的概念。只有提供了真实课程材料，才能引用教材、老师或课堂；"
        "没有素材就解释题目概念或使用明确的假设句，不得编造材料来源。\n"
        "7.5 引用政策/事件要小心时间线和因果，拿不准就只说背景、不下因果结论。\n"
        "8. 引用公开政策/事件时，必须能说出时间或文件名称；说不出来就别举例。"
        "不要写\"某公司\"\"某个区域\"\"多少小时\"\"几十单\"这种既模糊又当事实用的说法。\n"
        "9. 不要编个人琐事：\"我上个月注册了个App\"\"我前几天去面试\"这种没有依据的"
        "第一人称经历一律不写，没有真实素材就用课堂案例、公开事实或假设句。\n"
        "10. 不要用\"三层递进\"排比收尾（\"A管的是……，B管的是……，C管的是……\"、"
        "\"从……到……再到……\"），也不要用对偶句凑工整；结尾朴素一点。\n"
        "11. 观点要清楚、态度认真，可以有一点点不完美的口语表达，全篇不要每句都通顺工整。\n"
        "12. 只输出正文，不要任何解释或前后缀。"
    )

    # 输出侧硬黑名单：这些字样一旦出现在正文里，就是把平台的判分反馈回显给学生看
    LEAK_PATTERNS = (
        r"回答正确", r"回答错误", r"真遗憾", r"本题考核知识点", r"正确答案是",
        r"正确答案为", r"依据\s*[:：]", r"平台判据", r"你的回答", r"得分\s*\d",
        r"参考解析", r"答案解析",
    )
    HABIT_WORDS = ("我觉得", "其实", "反正", "感觉", "可能", "挺", "有点")
    # 结尾金句/总结腔：审计指出"每篇都交一句可被引用的结论"是最强的机器指纹
    CLOSING_CLICHE = (
        r"不是[^。！？]{0,24}而是", r"并非[^。！？]{0,24}而是",
        r"真正(难|重要|关键)的是", r"说到底", r"这才是", r"归根到底",
    )
    # 无来源的"假具体"：既模糊又当事实用，老师一问就穿
    UNSOURCED_SPECIFIC = (
        r"某(个|家|一)?(公司|企业|品牌|区域|城市|行业|领域|产线)", r"多少(小时|天|单|人)",
        r"几十(单|万|个)", r"大概(几|几十)", r"近(三|两)年(的)?(数据|指标)",
        r"(一些|不少|部分)(做|的)?[^，。；]{0,10}(品牌|企业|公司|商家|机构)",
        r"之前(看过|了解过|刷到过)[^，。；]{0,12}(案例|例子|新闻)",
    )
    # 真实犹豫/口语碎片：长文里至少要有 1 处，否则太顺滑
    HESITATION = ("说不好", "记不清", "没太想明白", "不太确定", "可能吧", "也说不准",
                  "没完全", "有点乱", "？", "?", "忘了", "大概是", "好像", "应该",
                  "印象里", "之类", "吧", "呢", "估计")
    # 显式模板连接词：生成器也要拦，不然审计器会抓（两边规则要一致）
    AI_CONNECTORS = ("首先", "其次", "再次", "最后", "总之", "总而言之", "综上所述",
                     "总的来说", "值得注意的是", "由此可见", "不难看出", "在当今社会")
    # 三层递进/排比收尾：同一账号多篇都用同一套结构，是最容易被老师看出的破绽
    STRUCTURE_CLICHE = (
        r"从[^，。；]{0,14}到[^，。；]{0,14}再到",
        r"[^，。；]{0,12}管的是[^，。；]{0,14}，[^，。；]{0,12}(管|是)的是",
        r"[^，。；]{0,10}管[^，。；]{0,8}，[^，。；]{0,10}管[^，。；]{0,8}，[^，。；]{0,10}管",
        r"先[^，。；]{0,10}再[^，。；]{0,10}(最后|才能|然后)",
        r"不是[^，。；]{0,14}，(而)?是[^，。；]{0,16}",
    )
    # 没有依据的第一人称琐事（编造个人经历）
    FAKE_PERSONAL = (
        r"我(上个月|上上个月|前几天|上周|最近|上次|昨天)(注册|下载|买了|报名|参加|去|跟|面)",
        r"我(一个|有个)(朋友|同学|亲戚)(跟|在|做|说)",
        # 在校学生不会有真实的实习/在职经历，写了就是编的
        r"我(之前|以前|原来|上家|上一家|曾经)?[^，。；]{0,6}(实习|上班|就职|入职)",
        # 兼职/打工同样是编的（实测模型会写"我在奶茶店做过兼职"）
        r"我(在|曾经在)[^，。；]{0,8}(兼职|打工|上班|实习)",
        r"我(做|干|打)过[^，。；]{0,4}(兼职|暑假工|临时工|小时工)",
        r"我们(公司|单位|企业)(里|的|在|要求|规定|考核)",
        r"我(去年|前年|以前|曾经|曾|今年)[^。！？]{0,20}(参加|参与|做过|调查|实习|培训|面试)",
    )
    # 认领共同经历（没有素材支撑时一律算编造）
    CLAIMED_COMMUNITY = (
        r"我们(小组|班|社团|团队)(上次|之前|课上|讨论|做|在)",
        r"(上次|之前|课上)(我们)?(小组|讨论|活动|讲)时",
        r"课上(讲|说|提)(过|的)",
        r"老师(说|讲|提)(过|的)|教材(上|里)(说|讲|提)|教材上",
        r"我们(的)?(小组|班级?|社团|团队)[^。！？]{0,20}(曾经|做过|调查|讨论过|参加过)",
        r"(根据|按照|正如)[^，。！？]{0,20}(教材|课本|老师|教师)",
        r"(老师|教师|教材|课本|课堂|课上)[^。！？]{0,20}(强调|指出|讲过|说过|写过|论述|介绍过|解释过|教过)",
    )
    # 示弱收尾：上一版为了防"金句收尾"引入，结果自己变成了统一口癖
    WEAK_ENDING = (r"(没太想明白|没完全(想|搞)明白|还在(琢磨|想)|也说不好|说不好|没搞懂|没想清楚)[。？!]*$",)
    # 普适经验断言
    UNIVERSAL_CLAIM = (
        r"(往往|通常|多半|一般都会)[^。！？]{0,24}(总部|客户|一线|市场|财务|生意|老板|公司)",
    )
    # 课程锚点
    COURSE_ANCHOR = ("课上", "教材", "老师", "这门课", "本章", "第几章", "课本")

    @classmethod
    def find_leak(cls, text: str):
        """返回正文里命中的"平台话术"（空列表表示干净）."""
        return [pattern for pattern in cls.LEAK_PATTERNS if re.search(pattern, str(text or ""))]

    @classmethod
    def habit_stats(cls, text: str) -> dict:
        return {word: str(text or "").count(word) for word in cls.HABIT_WORDS
                if str(text or "").count(word)}

    @staticmethod
    def cut_at_sentence(text: str, max_chars: int) -> str:
        """按整句截断，避免在句子中间被硬切（真人不会写半句话）."""
        text = str(text or "")
        if len(text) <= max_chars:
            return text
        window = text[:max_chars]
        cut = max(window.rfind(mark) for mark in "。！？!")
        return window[:cut + 1] if cut > 0 else window

    @classmethod
    def style_problems(cls, text: str, require_hesitation: bool = False,
                       require_course_anchor: bool = False) -> list:
        """真人化自检：返回命中的问题（空列表=过检）."""
        #
        # 检查范围：
        # 结尾金句、无来源的假具体、口癖分布过密、长文没有一处真实的犹豫。
        text = str(text or "")
        problems = []
        # No authenticated course or personal source material is accepted by this
        # API. Reject source attribution and narrated experience conservatively,
        # rather than enumerating time adverbs that a model can paraphrase.
        checks = [
            (re.search('教材|课本|讲义|老师|教师|教授|授课|课上|课堂|(?:本章|本节|课程|讲义|原文).{0,8}(?:写|说|指出|提及|提到|强调)', text), '未经提供的课程来源'),
            (re.search('(?<!如果)(?<!假如)(?<!假设)我(?!觉得|认为|倾向|更支持|不支持|建议|理解|赞同|同意|支持|们(?:可以|应该|需要|认为))', text), '未经提供的个人经历'),
            ('我' in text and re.search('曾经|去年|前年|当时|参加过|参加的|实习|培训|亲身|亲自|经营过|我们组', text), '未经提供的个人经历'),
            (cls.find_leak(text), '平台判分话术'),
        ]
        problems.extend(message for matched, message in checks if matched)
        stats = cls.habit_stats(text)
        # 长文里出现几种不同口癖是正常的，按长度放宽；"同一个词反复用"才一定有问题
        habit_limit = max(2, len(text) // 120)
        checks = [
            (len(stats) > habit_limit or any((count >= 3 for count in stats.values())), '口癖分布过密'),
            (any((re.search(pattern, text) for pattern in cls.CLOSING_CLICHE)), '金句收束'),
            (any((re.search(pattern, text) for pattern in cls.UNSOURCED_SPECIFIC)), '无来源的假具体'),
            (any((re.search(pattern, text) for pattern in cls.FAKE_PERSONAL)), '编造的个人琐事'),
            (any((word in text for word in cls.AI_CONNECTORS)), '模板连接词'),
            (any((re.search(pattern, text.strip()) for pattern in cls.WEAK_ENDING)), '示弱收尾口癖'),
            (any((re.search(pattern, text) for pattern in cls.CLAIMED_COMMUNITY)), '认领共同经历'),
            (any((re.search(pattern, text) for pattern in cls.UNIVERSAL_CLAIM)), '普适经验断言'),
            (require_course_anchor and (not any((word in text for word in cls.COURSE_ANCHOR))), '没有课程锚点'),
            (any((re.search(pattern, text) for pattern in cls.STRUCTURE_CLICHE)), '三层排比/对偶'),
        ]
        problems.extend(message for matched, message in checks if matched)
        # 句句都是长度接近的长句 = 低突发度，AIGC 检测的高权重特征
        sentences = [s for s in re.split(r"[。！？!?\n]", text) if s.strip()]
        if len(sentences) >= 4:
            lengths = [len(s) for s in sentences]
            if statistics.pstdev(lengths) < 6 and min(lengths) >= 25:
                problems.append("句子过于整齐")
        # 只对"讨论/开放问答"这种口语场景要求犹豫痕迹；正式的思考题/作业简答
        # 本来就写得工整，硬塞"记不清"反而不像学生。
        if require_hesitation and len(text) >= 120 \
                and not any(mark in text for mark in cls.HESITATION):
            problems.append("通篇太顺，没有犹豫/口语碎片")
        return problems

    def _generate_text(self, user: str, max_chars: int, require_hesitation: bool = False,
                       require_course_anchor: bool = False, **kwargs) -> str:
        """生成 + 自检：不合格就重写，平台判分话术残留直接报错."""
        #
        # 宁可失败也不能把"回答正确/依据：/本题考核知识点"这类平台判分话术
        # 写进要提交给老师的正文里（）。
        text = ""
        last_problems = []
        for attempt in range(1, 4):
            raw = self._chat(self.SYSTEM_STYLE, user, **kwargs)
            text = self.cut_at_sentence(self.clean(raw), max_chars)
            last_problems = self.style_problems(
                text, require_hesitation=require_hesitation,
                require_course_anchor=require_course_anchor,
            )
            if not last_problems:
                return self.cut_at_sentence(text, max_chars)
            logger.debug("生成内容不合格（第 {} 次）：{}", attempt, "、".join(last_problems))
            overused = [word for word, count in self.habit_stats(text).items() if count >= 2]
            extra = ("；这一版里「" + "、".join(overused) + "」用多了，换掉") if overused else ""
            # 把这一版具体踩到的问题回给模型，比笼统说"写得像人一点"有效
            extra += "；这一版的问题是：" + "、".join(last_problems) + "，请针对这些改"
            user = (user + "\n注意：不要出现\"回答正确/依据/本题考核知识点/你的回答\"这类平台判分用语；"
                           "不要用\"不是……而是……\"\"真正难的是\"\"说到底\"收尾；"
                           "不要写\"某公司/某个区域/多少小时/几十单\"这种编出来的具体；"
                           "口语词不要反复用同一个；句子长短要拉开，"
                           "至少插一句 12 字以内的短句，不要每句都是四五十字的长句；"
                           "不要用\"我还没太想明白\"结尾；不要认领小组/社团/课堂经历；"
                           "不要写\"往往/通常\"开头的普适断言；围绕题目中的概念；"
                           "可以留一处不那么确定的表达，但不要用固定的那几句；"
                           "结尾不要每篇都点题或落在一句有味道的话上；"
                           "不要编造教材、老师或课堂来源" + extra + "。")
        if "平台判分话术" in last_problems:
            raise RuntimeError("生成内容里仍带有平台判分话术")
        # 编造个人履历（实习/兼职/在职）是硬伤：宁可不提交，也不能把假经历发给老师
        if "编造的个人琐事" in last_problems:
            raise RuntimeError("生成内容里仍在编造个人经历（实习/兼职/在职）")
        raise RuntimeError("生成内容重写后仍未通过检查：" + "、".join(last_problems))

    def answer(self, question: str, requirement: str = "", references=None,
               max_chars: int = 220) -> str:
        """给问答题/简答题写一段像真人的回答."""
        refs = self.style_reference(references)
        user = (
            "题目：" + question + "\n"
            + ("补充要求：" + requirement + "\n" if requirement else "")
            + ("可以参考的同学答案：\n" + refs + "\n" if refs else "")
            + "请写一段 " + str(max(60, max_chars - 60)) + "~" + str(max_chars) + " 字的回答，"
              "不要照抄参考内容，用你自己的话讲清楚观点和理由。"
        )
        return self._generate_text(user, max_chars)

    def discussion(self, topic: str, requirement: str = "", existing_posts=None,
                   max_chars: int = 180, revision_hint: str = "",
                   previous_reply: str = "") -> str:
        """给主题讨论写一条回复：目标"班里中等水平"的普通回复，不显眼也不掉队."""
        #
        # 用户实测反馈：太机灵、太有个人风格（"要我说…我甚至觉得…"）反而不像普通同学。
        # 所以这里明确要求平实、普通、长度和多数同学接近；不追求语言上的亮点。
        refs = self.style_reference(existing_posts)
        user = (
            "讨论主题：" + topic + "\n"
            + ("老师的要求：" + requirement + "\n" if requirement else "")
            + ("上一版草稿：\n" + str(previous_reply).strip() + "\n" if previous_reply else "")
            + ("用户希望这样调整：" + str(revision_hint).strip() + "\n" if revision_hint else "")
            + ("同学们已经发过的回复：\n" + refs + "\n" if refs else "")
            + "请再写一条 " + str(max(30, max_chars - 50)) + "~" + str(max_chars) + " 字的回复：\n"
              "- 目标是班里**中等水平**：直接回答老师的问题，一句明确观点 + 一两条"
              "课本上/常识性的理由，语气平实、普通、不显眼；\n"
              "- 不要写巧妙的类比，不要抖机灵，不要金句/排比，不要引经据典式展开；\n"
              "- 也不要刻意示弱、不要用方言口癖、不要为了口语化而硬加语气词；\n"
              "- 可以正常用“我认为/我觉得”开头，句子长短适中，不要每句都四五十字；\n"
              "- 长度和上面多数同学差不多，不要写成 800 字小论文，也不要只写一句半；\n"
              "- 直接给正文，不要写“我同意楼上”这类空话；\n"
              + ("- 上面确实有同学的回复：只模仿他们的语气和长度，"
                 "不要引用/复述某条回复的原话、楼层或编号（很容易编造出没出现过的话）；\n"
                 if refs else
                 "- 这次没有同学回复可参考：请写一条能独立成立的回复，"
                 "不要出现“楼上/前面那位/那个例子”这类指代别人发言的说法；\n")
              + "- 不要编造个人经历（兼职/实习/打工/任职），没有真实经历就写课程里的说法、"
                "公开案例或假设句（\u201c如果\u2026\u201d），也不要认领小组/班级经历。"
              + ("\n- 必须吸收用户的调整方向，重新写一版完整正文；不要解释改了哪里，也不要照抄上一版。"
                 if revision_hint or previous_reply else "")
        )
        return self._generate_text(user, max_chars)

    def practice_answer(self, question: str, requirement: str = "", context: str = "",
                        max_chars: int = 520) -> str:
        """为 AI 实践的开放题生成更完整的课程回答."""
        user = (
            "AI 实践题目：" + str(question or "") + "\n"
            + ("实践要求：" + str(requirement) + "\n" if requirement else "")
            + ("当前维度/知识点：" + str(context) + "\n" if context else "")
            + "请结合课程里的概念和一个具体场景回答，说明你的判断和可能的取舍。"
              "没有真实经历就写成假设句或课堂案例，不要编造实习/职位/数据。"
              "结尾不要总结升华，可以停在一处还不确定的地方。"
              "回答要自然、具体、连贯，控制在 180~" + str(max(240, max_chars))
              + " 字，只输出回答正文。"
        )
        return self._generate_text(user, max_chars, require_hesitation=True,
                                   temperature=0.7, max_tokens=900)

    # AI 实践的客观题用多票自洽：同一个 prompt 采样几次取多数，降低偶发误判
    OBJECTIVE_VOTES = 3

    def _vote(self, system: str, user: str, parse, votes: int = None, **kwargs):
        """把一个 parse 函数套在多次采样上，返回票数最多的结果."""
        count = max(1, int(votes or self.OBJECTIVE_VOTES))
        tally: dict = {}
        for _ in range(count):
            try:
                raw = self._chat(system, user, **kwargs)
            except Exception as e:
                logger.warning("多票作答第 {} 次调用失败: {}", _ + 1, e)
                continue
            key = parse(raw)
            if key:
                tally[key] = tally.get(key, 0) + 1
        if not tally:
            return None
        best = max(tally.items(), key=lambda item: item[1])
        if len(tally) > 1:
            logger.debug("多票结果: {} -> 取 {}", tally, best[0])
        return best[0]

    def choose_options(self, question: str, options, multiple: bool = False,
                       context: str = "", exclude=None) -> str:
        """为 AI 实践选择题选项，只返回平台需要的 A/B/C... 字母."""
        option_lines = []
        for item in options or []:
            if isinstance(item, dict):
                letter = str(item.get("option") or "").strip().upper()
                content = str(item.get("optionContent") or item.get("content") or "")
            else:
                letter, content = "", str(item)
            if letter:
                option_lines.append(f"{letter}. {content}")
        if not option_lines:
            raise ValueError("选择题没有有效选项")
        mode = "多选，可选择一个或多个" if multiple else "单选，只选择一个"
        user = (
            "课程测验题。\n"
            "题目：" + str(question or "") + "\n"
            + ("考点提示：" + context + "\n" if context else "")
            + "选项：\n" + "\n".join(option_lines) + "\n"
            + "作答要求：\n"
              "1) 先确定题目考的是哪个课程概念，再逐个选项对照概念判断；\n"
              "2) 表述绝对化的选项（一定、总是、唯一、完全）通常不是标准答案，"
              "除非符合教材原意；\n"
              "3) " + mode + "；\n"
              "4) 最后一行的格式必须是「答案：X」（多选按字母顺序连写，如 答案：ABD），"
              "前面可以有一两句简短判断依据，不要再写别的。"
        )
        valid = {line.split(".", 1)[0].strip().upper() for line in option_lines}

        def parse(raw):
            letters = self._extract_letters(raw, valid)
            return "".join(letters) or None

        voted = self._vote(
            "你是这门课程的答题助手，只依据课程理论作答，"
            "以选出标准答案为目标，不要靠选项格式或长度猜。",
            user,
            parse,
            temperature=0.5,
            max_tokens=400,
        )
        if not voted:
            raise ValueError("模型没有返回有效选择题选项")
        selected = [letter for letter in voted]
        order = {letter: index for index, letter in enumerate("ABCDE")}
        if not multiple:
            answer = selected[0]
            # 平台判断题的是平台自己的大模型，同一个答案会被反复判错；
            # 重试时换一个还没试过的选项，才有机会跳出循环。
            banned = {str(item).strip().upper() for item in (exclude or [])}
            if answer in banned:
                for letter in sorted(valid, key=lambda x: order.get(x, 99)):
                    if letter not in banned:
                        logger.info("选择题 {} 已判错过，改用 {} 重试", answer, letter)
                        return letter
            return answer
        selected = sorted(set(selected), key=lambda letter: order.get(letter, 99))
        answer = "".join(selected)
        banned_sets = {"".join(sorted(str(item).upper())) for item in (exclude or [])}
        if answer in banned_sets:
            for letter in sorted(valid, key=lambda x: order.get(x, 99)):
                if letter not in answer:
                    logger.info("多选题 {} 已判错过，补上 {} 重试", answer, letter)
                    return "".join(sorted(answer + letter, key=lambda x: order.get(x, 99)))
        return answer

    @staticmethod
    def _recent_feedback(data: dict, limit: int = 3, max_chars: int = 600) -> str:
        """从 AI 实践对话里提取平台最近的解析/判据."""
        #
        # 平台的 preAppendContent 在判错时会直接把正确概念讲出来
        # （例如"公司层战略是企业最高管理层制定的面向企业整体的总体战略，核心是确定经营领域"），
        # 把它作为作答依据喂回模型，能显著提高重复题的正确率。
        hints = []
        messages = list((data or {}).get("messageList") or [])[-24:]
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            payload = message.get("content")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    payload = None
            if not isinstance(payload, dict):
                continue
            text = str(payload.get("preAppendContent") or "").strip()
            if not text:
                continue
            if not any(key in text for key in ("正确", "遗憾", "误解", "知识点", "核心")):
                continue
            text = re.sub(r"\s+", " ", text)
            if text not in hints:
                hints.append(text[:max_chars])
            if len(hints) >= limit:
                break
        return "；".join(reversed(hints))

    @staticmethod
    def _extract_letters(raw: str, valid: set) -> list:
        """从模型输出里取选项字母：优先「答案：X」，否则只看最后一行."""
        text = str(raw or "")
        marked = re.findall(r"答案\s*[:：]?\s*([A-Ea-e]{1,5})", text)
        if marked:
            source = marked[-1]
        else:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            source = lines[-1] if lines else ""
        letters = []
        for letter in re.findall(r"[A-E]", source.upper()):
            if letter in valid and letter not in letters:
                letters.append(letter)
        return letters

    def choose_judgement(self, question: str, context: str = "", exclude=None) -> str:
        """为 AI 实践判断题返回平台使用的“对”或“错”."""
        user = (
            "课程判断题。\n"
            "题目：" + str(question or "") + "\n"
            + ("考点提示：" + context + "\n" if context else "")
            + "作答要求：先依据课程概念判断这句话成立不成立，"
              "最后一行只写「答案：对」或「答案：错」，前面可以有一句简短理由。"
        )
        def parse(raw):
            text = str(raw or "")
            marked = re.findall(r"答案\s*[:：]?\s*([对错])", text)
            if marked:
                return marked[-1]
            tail = "".join(line.strip() for line in text.splitlines()[-1:])
            if "对" in tail and "错" not in tail:
                return "对"
            if "错" in tail and "对" not in tail:
                return "错"
            return None

        answer = self._vote(
            "你是这门课程的答题助手，严格依据课程理论判断正误。",
            user,
            parse,
            temperature=0.3,
            max_tokens=200,
        )
        if not answer:
            raise ValueError("模型没有返回明确的判断题答案")
        banned = {str(item).strip() for item in (exclude or [])}
        if answer in banned:
            flipped = "错" if answer == "对" else "对"
            logger.info("判断题 {} 已判错过，改用 {} 重试", answer, flipped)
            return flipped
        return answer
