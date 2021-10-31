# -*- coding:utf-8 -*-
from rich.console import Console
from rich.markdown import Markdown

console = Console()


def print_md(isallow=True):
    if isallow:
        with open("warning.md",'rb') as readme:
            markdown = Markdown(readme.read().decode('utf8'))
        console.print(markdown)
        console.input("\n\n请阅读[red]使用须知[/red]，阅读完成后[red]按回车键[/red]继续")
        console.print('\n\n\n\n\n')
        console.log("[yellow2]开始运行代码[/yellow2]")