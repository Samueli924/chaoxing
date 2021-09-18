from rich.console import Console


console = Console()


def regulate_print(content):
    l = len(content)
    if l < 80:
        content = content + (80 - l) * ' '
    else:
        content = content
    console.print(content, end='\r')


def normal_print(content):
    l = len(content)
    if l < 80:
        content = content + (80 - l) * ' '
    else:
        content = content
    console.print(content)