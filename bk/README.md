# fxxk_chaoxing
超星学习通/超星尔雅/泛雅超星/mooc1-1.chaoxing/刷任务点
每日 git api调用次数有限，所以请不要不停重复运行本程序
# 相关库
import requests
import time
import hashlib
import re
import os
import random
from urllib.parse import unquote
import json

# 使用方法
git clone 至本地后 
直接cd进目录
命令行运行'python best.py'
输入账号密码
选择课程
开始自动刷任务点

# 实现方式
全程使用requests库
模拟安卓端登录
读取课程数据
模拟浏览器发送看视频GET请求

# 已实现功能
自动看所有的视频任务点

# TODO
自动看所有的ppt任务点
自动看所有的pdf任务点

# 注意事项
由于超星加入了心跳时间，故此代码的看视频时间和现实所需时间是一致的，可以将代码挂在任意平台运行
代码运行过程中会在当前路径生成配置文件，所以请放入单独一个文件夹中
更新后请放置于同一目录运行以使用本地配置文档
# 欢迎issue &pull requests

