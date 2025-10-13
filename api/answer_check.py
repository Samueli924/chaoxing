def check_single(answer):
    _t = cut(answer)
    if _t is not None and len(_t) == 1:
        return True
    else:
        return False


def check_multiple(answer):
    _t = cut(answer)
    if _t is not None and len(_t) > 0:
        return True
    return False


def check_judgement(answer, true_list, false_list):
    if answer in true_list:
        return 1
    elif answer in false_list:
        return 0
    else:
        return -1


def check_completion(answer):
    if len(answer) > 0:
        return True
    else:
        return False


def check_answer(answer, type, tiku):  # 只会写小杯代码，这里用个tiku感觉怪怪的，但先这么写着
    if type == 'single':
        if check_single(answer) and check_judgement(answer, tiku.true_list, tiku.false_list) == -1:
            return True
    elif type == 'multiple':
        if check_multiple(answer) and check_judgement(answer, tiku.true_list, tiku.false_list) == -1:
            return True
    elif type == 'completion':
        if check_completion(answer):
            return True
    elif type == 'judgement':
        if check_judgement(answer, tiku.true_list, tiku.false_list) != -1:
            return True
    else:  # 未知类型不匹配
        return True
    return False


def cut(answer):
    cut_char = [
        "\n",
        ",",
        "，",
        "|",
        "\r",
        "\t",
        "#",
        "*",
        "-",
        "_",
        "+",
        "@",
        "~",
        "/",
        "\\",
        ".",
        "&",
        " ",
        "、",
    ]
    if answer is None:
        return None

    answer = str(answer)
    for char in cut_char:
        if char not in answer:
            continue
        res = [opt.strip() for opt in answer.split(char) if opt.strip()]
        if res:
            return res
    stripped = answer.strip()
    return [stripped] if stripped else None
