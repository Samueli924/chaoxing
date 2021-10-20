# -*- coding:utf-8 -*-
from rich.console import Console


console = Console()


def regulate_print(content):
    """
    规范输出的样式
    :param content:
    :return:
    """
    l = len(content)
    if l < 80:
        content = content + (80 - l) * ' '
    else:
        content = content
    console.print(content, end='\r')