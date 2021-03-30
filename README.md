# fxxk_chaoxing

# --20210328更新版本添加了多倍速功能（多倍速有风险，使用请谨慎）--

# 喜欢使用的朋友请给个Star

超星学习通/超星尔雅/泛雅超星/mooc1-1.chaoxing/刷任务点
=======

直接下载可执行程序exe文件（版本较落后，建议使用代码）
https://github.com/xz454867105/fxxk_chaoxing/releases

# 作者其他刷课项目
## 单开命令行版（稳定开发版，BUG少）
https://github.com/xz454867105/fxxk_chaoxing
## 多用户Pyqt版（Beta版，存在较多BUG）
https://github.com/xz454867105/chaoxing_Multi
## 升级版chaoxing（开发中，尚未开放）
https://github.com/xz454867105/chaoxing_pro
## 智慧树Selenium版(稳定开发版，BUG少)
https://github.com/xz454867105/fxxk_zhihuishu


# 注释
## 本代码安全不封号

## 考虑到了超星学习通的心跳检测刷课方式，本代码的所需时间等于视频的实际观看时间

## 将代码运行或直接运行exe文件即可自动开始发送看视频GET请求

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
## git clone 至本地后 cd进目录
## 命令行运行'python best.py'
## 输入账号密码
## 选择课程
## 开始自动刷任务点


# 实现方式
全程使用requests库
模拟安卓端登录
读取课程数据
模拟浏览器发送看视频GET请求

# 已实现功能
自动看所有的视频任务点
自动看所有的ppt任务点


# 注意事项
由于超星加入了心跳时间，故此代码的看视频时间和现实所需时间是一致的，可以将代码挂在任意平台运行
代码运行过程中会在当前路径生成配置文件，所以请放入单独一个文件夹中
更新后请放置于同一目录运行以使用本地配置文档
# 本代码仅用于学习交流
# 欢迎issue &pull requests

