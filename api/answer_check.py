import re
from difflib import SequenceMatcher
from typing import Optional

TRUE_WORDS = ['true', 't', '1', '对', '正确', '√', '✓', '✔', '是', 'yes', 'y']
FALSE_WORDS = ['false', 'f', '0', '错', '错误', '×', '✗', '✘', '否', 'no', 'n', '不对', '不正确']


def check_single(answer):
    if answer is None:
        return False

    text = str(answer).strip()
    if not text:
        return False

    # 单选答案文本中常见逗号（中英文）是句内标点，不应据此判定为多选。
    # 仅在出现明显“多段答案”分隔符时，才判定为非单选。
    strong_delimiters = ["\n", "|", "#", "\t", "\r", "、"]
    for sep in strong_delimiters:
        parts = [p.strip() for p in text.split(sep) if p.strip()]
        if len(parts) > 1:
            return False

    return True


def check_multiple(answer):
    _t = cut(answer)
    if _t is not None and len(_t) > 0:
        return True
    return False


def check_judgement(answer, true_list, false_list):
    val = str(answer).strip().lower()
    if val in TRUE_WORDS or val in [x.lower() for x in true_list]:
        return 1
    elif val in FALSE_WORDS or val in [x.lower() for x in false_list]:
        return 0
    else:
        return -1


def check_completion(answer):
    return len(str(answer).strip()) > 0


def check_answer(answer, type, tiku):  # 只会写小杯代码，这里用个tiku感觉怪怪的，但先这么写着
    # 如果是手动模式或多题库回退包装器，直接信任
    # （手动模式豁免常规校验；回退包装器因其子题库在各自环节均已单独校验过，此处无需二次校验，以防二次过滤误杀）
    if getattr(tiku, 'is_manual', False) or getattr(tiku, 'skip_answer_validation', False):
        return True

    true_list = getattr(tiku, 'true_list', None) or []
    false_list = getattr(tiku, 'false_list', None) or []
    if type == 'single':
        if check_single(answer) and check_judgement(answer, true_list, false_list) == -1:
            return True
    elif type == 'multiple':
        if check_multiple(answer) and check_judgement(answer, true_list, false_list) == -1:
            return True
    elif type == 'completion':
        if check_completion(answer):
            return True
    elif type == 'judgement':
        if check_judgement(answer, true_list, false_list) != -1:
            return True
    else:  # 未知类型不匹配
        return True
    return False


# 切分多选答案时的分隔符，优先使用几乎不会出现在选项正文中的“强分隔符”
CUT_CHARS = [
    "\n", "\r", "\t", "#", "|", ";", "；",
    ",", "，", "、", " ",
    "*", "-", "_", "+", "@", "~", "/", "\\", ".", "&",
]


def cut(answer):
    if answer is None:
        return None

    answer = str(answer)
    for char in CUT_CHARS:
        if char not in answer:
            continue
        res = [opt.strip() for opt in answer.split(char) if opt.strip()]
        if res:
            return res
    stripped = answer.strip()
    return [stripped] if stripped else None


# ---------------------------------------------------------------------------
# 答案与选项匹配
# ---------------------------------------------------------------------------

_VARIANT_CHARS = str.maketrans({
    '⻛': '风',
    '⻔': '门',
    '⻋': '车',
    '⻢': '马',
})
_PUNCTUATION_RE = re.compile(r'[，。！？；：,.!?;:()（）\[\]【】"“”‘’\'\-_/\\|、·…．]')
# 选项固定以字母编号开头，例如 "A. 苹果"、"A、苹果"、"A苹果"
_OPTION_LABEL_RE = re.compile(r'^\s*([A-Za-z])\s*[.、:：)）．]?\s*')
# 题库答案仅在编号后紧跟分隔符时才视为编号，避免把 "Python" 的首字母当成编号去掉
_ANSWER_LABEL_RE = re.compile(r'^\s*[A-Za-z]\s*[.、:：)）．]\s*|^\s*[A-Za-z]\s+(?=\S)')
_LETTER_SEPARATORS_RE = re.compile(r'[\s,，、;；|#/]+')


def normalize_text(text) -> str:
    """统一异体字、去掉空白与标点并转为小写，用于答案比较."""
    if text is None:
        return ""
    normalized = str(text).translate(_VARIANT_CHARS)
    normalized = re.sub(r'\s+', '', normalized)
    normalized = _PUNCTUATION_RE.sub('', normalized)
    return normalized.lower()


def option_letter(option: str) -> str:
    match = _OPTION_LABEL_RE.match(option or "")
    return match.group(1).upper() if match else ""


def option_body(option: str) -> str:
    return _OPTION_LABEL_RE.sub('', option or '', count=1).strip()


def answer_body(answer: str) -> str:
    return _ANSWER_LABEL_RE.sub('', answer or '', count=1).strip()


def split_options(options) -> list[str]:
    if isinstance(options, list):
        return [str(o).strip() for o in options if str(o).strip()]
    return [o.strip() for o in str(options or "").split("\n") if o.strip()]


def judgement_value(answer, true_list=None, false_list=None) -> Optional[bool]:
    """把判断题答案转换为布尔值，无法识别时返回 None."""
    result = check_judgement(answer, true_list or [], false_list or [])
    if result == 1:
        return True
    if result == 0:
        return False
    return None


def is_subsequence(needle: str, haystack: str) -> bool:
    iterator = iter(haystack)
    return all(c in iterator for c in needle)


def _option_score(part_norm: str, body_norm: str) -> float:
    if part_norm == body_norm:
        return 1.0
    shorter, longer = sorted((len(part_norm), len(body_norm)))
    if part_norm in body_norm or body_norm in part_norm:
        return 0.8 + 0.19 * shorter / longer
    ratio = SequenceMatcher(None, part_norm, body_norm).ratio()
    if ratio >= 0.8:
        return ratio
    if is_subsequence(part_norm, body_norm):
        # 题库答案常省略选项中的个别字，作为最后的兜底
        return 0.6 + 0.19 * len(part_norm) / len(body_norm)
    return 0.0


def best_option(part: str, labeled_options: list[tuple[str, str]]) -> str:
    part_norm = normalize_text(answer_body(part))
    if not part_norm:
        return ""
    best_letter, best_score = "", 0.0
    for letter, body in labeled_options:
        body_norm = normalize_text(body)
        if not body_norm:
            continue
        score = _option_score(part_norm, body_norm)
        if score > best_score:
            best_letter, best_score = letter, score
            if score == 1.0:
                break
    return best_letter


def match_choice(answer, options, multiple: bool = False) -> str:
    """把题库返回的答案匹配为选项字母，多选题按字母排序；无法匹配时返回空字符串."""
    if answer is None:
        return ""
    labeled = [(option_letter(o), option_body(o)) for o in split_options(options)]
    labeled = [(letter, body) for letter, body in labeled if letter]
    if not labeled:
        return ""
    valid_letters = {letter for letter, _ in labeled}
    text = str(answer).strip()
    if not text:
        return ""

    # 1. 答案本身就是选项字母，例如 "B"、"ABD"、"A,C"
    compact = _LETTER_SEPARATORS_RE.sub('', text).upper()
    if (compact and re.fullmatch(r'[A-Z]+', compact) and len(set(compact)) == len(compact)
            and set(compact) <= valid_letters and (multiple or len(compact) == 1)):
        # 纯字母答案也可能恰好是某个选项的正文（例如 "DNA"），此时按正文匹配
        if not any(normalize_text(body) == normalize_text(text) for _, body in labeled):
            return "".join(sorted(compact))

    # 2. 按选项正文匹配：完全一致 > 包含关系 > 相似度 > 子序列
    parts = (cut(text) or []) if multiple else [text]
    chosen: list[str] = []
    for part in parts:
        letter = best_option(part, labeled)
        if letter and letter not in chosen:
            chosen.append(letter)
    if not chosen:
        return ""
    if multiple:
        return "".join(sorted(chosen))
    return chosen[0]


def comparable_answer(answer, type_label: str = "") -> str:
    """把作答记录中的“我的答案/正确答案”规整为可比较的形式."""
    text = str(answer or "").strip()
    if not text:
        return ""
    is_judgement = "判断" in type_label
    value = judgement_value(text)
    if value is not None and (is_judgement or not type_label):
        return "T" if value else "F"
    compact = _LETTER_SEPARATORS_RE.sub('', text).upper()
    if re.fullmatch(r'[A-Z]+', compact) and ("选" in type_label or len(compact) <= 7):
        return "".join(sorted(compact))
    return normalize_text(text)
