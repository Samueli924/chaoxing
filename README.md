# :computer: 超星学习通自动化完成任务点(命令行版)

<p align="center">
    <a href="https://github.com/Samueli924/chaoxing" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/github/stars/Samueli924/chaoxing" alt="Github Stars" />
    </a>
    <a href="https://github.com/Samueli924/chaoxing" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/github/forks/Samueli924/chaoxing" alt="Github Forks" />
    </a>
    <a href="https://github.com/Samueli924/chaoxing" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/github/languages/code-size/Samueli924/chaoxing" alt="Code-size" />
    </a>
    <a href="https://github.com/Samueli924/chaoxing" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/github/v/release/Samueli924/chaoxing?display_name=tag&sort=semver" alt="version" />
    </a>
</p>
:muscle: 本项目的最终目的是通过开源消灭所谓的付费刷课平台，希望有能力的朋友都可以为这个项目提交代码，支持本项目的良性发展    

:star: 觉得有帮助的朋友可以给个Star

## :point_up: 更新通知  

20220919 更新：

    3.更详细的bug输出，并尝试修复一个非固定的dict（class Exception未修复, 音频任务也会报错，后续修复)
    
    2.添加完成文档文件任务点功能（Beta）设置self.filebeta=0关闭此功能
    
    1.针对403无权限问题添加额外的信息输出，添加一次连接错误重试（或许有用）


20220918 更新：暂时修复获取视频403没有权限的状况

20220426 更新： 已尝试修复验证码BUG，请拉取最新源码（推荐）或使用最新exe可执行文件。出现BUG需要提交Issue的请携带运行截图与日志文件一起提交。  

## :books: 使用方法

### 源码运行(推荐)
1. 提前准备： Python版本>=3.9 因为使用到了:=表达式。urllib3=1.25.11 因为后面的版本对代理的支持有变化。
2. `git clone --depth=1 https://github.com/Samueli924/chaoxing` 项目至本地
3. `cd chaoxing`
4. `pip install -r requirements.txt`
5. `python main.py` 运行程序
6. 可选参数 -debug 开启DEBUG模式 --no-log 不输出日志 --no-logo 隐藏开头项目LOGO --no-sec 关闭隐私保护

### 使用Docker运行
1. `git clone --depth=1 https://github.com/Samueli924/chaoxing` 获取项目源码
2. `docker-compose run --rm app`, 在交互式终端中运行容器

你可以在终端中使用`ctrl+p+q`来让容器退出交互式终端并在后台运行

## :heart: CONTRIBUTORS  
### :one:感谢[huajijam](https://github.com/huajijam)对chaoxing项目的贡献! [PR #73](https://github.com/Samueli924/chaoxing/pull/73)
### :two:感谢[ljy0309](https://github.com/lyj0309)修复Attachments BUG! [PR #70](https://github.com/Samueli924/chaoxing/pull/70)
### :three:感谢[Shanxuns](https://github.com/Shanxuns)修正查找任务点的正则表达式内容 [Pull #33](https://github.com/Samueli924/chaoxing/pull/33)  
### :four:感谢[B1gM8c](https://github.com/B1gM8c)修复登录密码加密BUG[Pull #118](https://github.com/Samueli924/chaoxing/pull/118)  
### :five:感谢[RyaoChengfeng](https://github.com/RyaoChengfeng)添加Docker运行支持[Pull #125](https://github.com/Samueli924/chaoxing/pull/125)  
### 对于代码有任何问题或建议欢迎Pull&Request  


## :warning: 免责声明  
- 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守[GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议  
- 本代码仅用于**学习讨论**，禁止**用于盈利**  
- 他人或组织使用本代码进行的任何**违法行为**与本人无关  
