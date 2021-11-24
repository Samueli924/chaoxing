## <center><font color=white size=6 align=center face="微软雅黑"> :computer: 超星学习通自动化</font></center>

<font color=white size=3 face="微软雅黑">:star: 觉得有帮助的朋友可以给个**Star**</font>

## <center><font color=white size=6 align=center face="微软雅黑">:exclamation: 更新通知</font></center>

<font color=white size=3 face="微软雅黑">:grinning: 20211124更新内容：更新了最新的Windows可执行文件版本[Release](https://github.com/Samueli924/chaoxing/releases/tag/2.0.5)</font>

## <center><font color=white size=6 align=center face="微软雅黑">:smile: 其他项目</font></center>

<font color=white size=3 face="微软雅黑">:blush: [智慧树无人值守自动化完成共享课视频任务点](https://github.com/Samueli924/zhihuishu)</font>

## <center><font color=white size=6 align=center face="微软雅黑">:books: 使用方法</font></center>

### <font color=white size=4 align=center face="微软雅黑">:bulb: 一. 可执行exe文件运行方式(Windows本地环境推荐)</font>

<font color=white size=3 align=center face="微软雅黑">1. 在[release](https://github.com/Samueli924/chaoxing/releases)页面下载2.X版本最新文件</font>

<font color=white size=3 align=center face="微软雅黑">2. 启动exe文件(建议放入独立文件夹内运行，因为在运行过程中会在运行当前本地目录生成saves存档Cookies等记录文件)</font>

### <font color=white size=4 align=center face="微软雅黑">:bulb: 二. 使用Python环境运行源文件(Linux, macOS本地环境推荐)</font>  
  
<font color=white size=3 align=center face="微软雅黑">1. git 克隆至本地</font>

<font color=white size=3 align=center face="微软雅黑">2. 执行pip install -r requirements.txt安装相关依赖</font>

<font color=white size=3 align=center face="微软雅黑">3. 执行 python main.py 运行代码</font>

### <font color=white size=4 align=center face="微软雅黑">:bulb: 二. 配置文件运行(Linux服务器环境推荐)</font>

<font color=white size=3 align=center face="微软雅黑">1. git 克隆至本地</font>

<font color=white size=3 align=center face="微软雅黑">2. 执行pip install -r requirements.txt安装相关依赖</font>

<font color=white size=3 align=center face="微软雅黑">3. 修改配置文件config.ini里的内容</font>
    [user]
    usernm = 1XXXXXXXXXX9 # 手机号/用户名
    passwd = 2XXXXXXXXXXX # 用户密码
    courseid = XXXXXXXXX  # 课程ID编号（如果不知道ID，可以先直接运行代码，选择课程后在saves文件夹里找到课程文件夹，文件夹名即为课程ID）
    [play]
    showmd = True # 是否展示程序运行初的注意事项MD内容
    speed = 1 # 视频播放倍速，推荐一倍速
<font color=white size=3 align=center face="微软雅黑">4. (假如存在)删除目录下的saves文件夹</font>

<font color=white size=3 align=center face="微软雅黑">5. 执行 python main.py -c 运行代码</font>

## <center><font color=white size=6 align=center face="微软雅黑"> :grey_exclamation: 提醒&注释</font></center>

<font color=white size=3 color=red face="微软雅黑">:one: 程序在python 3.6的环境下开发完成，建议使用Python 3.6运行本程序</font>  

<font color=white size=3 color=red face="微软雅黑">2️⃣: 程序使用协议自动化，而非github其他的浏览器插件或selenium库自动化，占用资源小且安全有效</font>  

<font color=white size=3 color=red face="微软雅黑">3️⃣: 考虑到了超星学习通的心跳检测刷课方式，本代码的所需时间等于视频的实际观看时间</font>   

<font color=white size=3 color=red face="微软雅黑">注：在0.1.2版本中加入了多倍速的功能，建议不要使用</font>   

<font color=white size=3 color=red face="微软雅黑">:stuck_out_tongue_winking_eye: 本代码仅用于学习交流学习通自动化协议</font>   
  
<font color=white size=3 color=red face="微软雅黑">:stuck_out_tongue_winking_eye: 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)，使用、修改、发行本代码请遵守协议要求</font>   

<font color=white size=3 color=red face="微软雅黑">:grinning: 欢迎issue &pull requests</font>   

## <center><font color=white size=6 align=center face="微软雅黑"> :smile: CONTRIBUTORS</font></center>

<font color=white size=3 color=red face="微软雅黑">:one: 感谢[Shanxuns](https://github.com/Shanxuns)修正查找任务点的正则表达式内容 [Pull #33](https://github.com/Samueli924/chaoxing/pull/33)</font>
