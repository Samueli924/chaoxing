import configparser
import getopt
import sys
from rich.console import Console


console = Console()
config = configparser.ConfigParser()


def has_config():
    try:
        options, _ = getopt.getopt(sys.argv[1:], "c", ["config"])
        for option, value in options:
            if option in ("-c", "--config"):
                config.read(filenames='config.ini', encoding="utf-8")
                return config
    except getopt.GetoptError:
        return False


def get_config(config):
    try:
        isallow = config.getboolean("play", "showmd")
    except configparser.NoOptionError:
        isallow = True

    try:
        usernm = config.get("user", "usernm")
        passwd = config.get("user", "passwd")
    except configparser.NoOptionError:
        usernm = ''
        passwd = ''
    try:
        courseid = str(config.get("user", "courseid"))
    except configparser.NoOptionError:
        courseid = ''
    try:
        speed = config.get("play", "speed")
    except configparser.NoOptionError:
        speed = 1
    return isallow,usernm,passwd,courseid,speed

def get_params():
    config = has_config()
    if config:
        console.log("启动方式：[yellow]配置文件启动[/yellow]")
        return get_config(config)
    else:
        console.log("启动方式：[yellow]无配置文件启动[/yellow]")
        return True, '', '', '', 1
