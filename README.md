# :computer: 超星学习通自动化完成任务点(请更新至2.1.0版本)

:star: 觉得有帮助的朋友可以给个**Star**

## :point_up: 更新通知

20211208更新内容：适配了超星最新的协议接口，添加了对于结课课程的判断，请更新至最新的2.1.0版本，使用2.1.0版本时老版本的saves文件夹需要删除

## :question: 反馈方式  

想要交流脚本运行或运行有问题需要提问的朋友可以选择加入Telegram群聊，我会在群聊中尽量尽快回复你的消息  
[点此加入群聊](https://t.me/samueli924)  

## :books: 三种使用方法(请根据自己的运行环境选择)

### :one: 可执行exe文件运行方式(Windows本地环境推荐)

1. 在[release](https://github.com/Samueli924/chaoxing/releases)页面下载2.X版本最新文件</font>

2. 启动exe文件(建议放入独立文件夹内运行，因为在运行过程中会在运行当前本地目录生成saves存档Cookies等记录文件)</font>


### :two: 使用Python环境运行源文件(Linux, macOS本地环境推荐) 

1. git 克隆至本地

2. 执行pip install -r requirements.txt安装相关依赖

3. 执行 python main.py 运行代码


### :three: 配置文件运行(Linux服务器环境推荐)

1. git 克隆至本地

2. 执行pip install -r requirements.txt安装相关依赖

3. 修改配置文件config.ini里的内容如下

    >[user]  
    >usernm = 1XXXXXXXXXX9 # 手机号/用户名  
    >passwd = 2XXXXXXXXXXX # 用户密码  
    >courseid = XXXXXXXXX  # 课程ID编号（如果不知道ID，可以先直接运行代码，选择课程后在saves文件夹里找到课程文件夹，文件夹名即为课程ID)    
    
    >[play]  
    >showmd = True # 是否展示程序运行初的注意事项MD内容  
    >speed = 1 # 视频播放倍速，推荐一倍速  
   
4. (假如存在)删除目录下的saves文件夹

5. 执行 python main.py -c 运行代码


## :question: FAQ(常见问题)

1. 程序相关
    - 问: 程序如何实现完成视频任务点?运行时会有**风险**吗?  
   答: 程序使用从超星AndroidApp中逆向得到的**API发送协议包**完成任务。在超星不更新其API协议的前提下能够**确保安全**  
    - 问: 为什么程序运行时间和实际时间一样，不能**一键瞬间完成**所有任务吗?  
   答: 本程序设计的初衷是在确保**绝对安全**的前提下提高效率，所以在代码中没有添加一键完成所有任务的代码。实际上，一键完成功能十分容易，在Github上已经有许多相关的优秀repo可供下载  
    - 问: 程序用到了哪些第三方库?  
   答: 本程序仅用到了requests库负责完成任务，以及rich库负责输出结果。不同于Github中存在的一些其他使用selenium库的repo，具有内存占用小，带宽占用小的优点
2. 运行相关
    - 问: 为什么我在服务器运行这个程序会出现 **Connection Error**?  
   答: 根据过去一段时间报告的BUG推测，超星的API屏蔽了**阿里云的服务器**IP段，所以无法在阿里云服务器运行
    - 问: 为什么Windows版本的exe文件不能**调倍速**?  
   答: Windows版本**可以调节倍速**，只需要把库根目录中的config.ini下载到本地exe所在目录，在配置完毕后，使用命令行**chaoxing_X.X.X.exe -c** 运行即可
3. 计划相关(TODO LIST: 预计2022年1月初更新,在此之前仅更新修复BUG)
    - 更新计划详见[Projects](https://github.com/Samueli924/chaoxing/projects/1)
    

## :heart: CONTRIBUTORS
### :one: 感谢[Shanxuns](https://github.com/Shanxuns)修正查找任务点的正则表达式内容 [Pull #33](https://github.com/Samueli924/chaoxing/pull/33)
### 对于代码有任何问题或建议欢迎Pull&Request


## :warning: 免责声明
- 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守[GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议  
- 本代码仅用于**学习讨论**，禁止**用于盈利**
- 他人或组织使用本代码进行的任何**违法行为**与本人无关
