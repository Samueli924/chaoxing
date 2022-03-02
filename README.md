# :computer: 超星学习通自动化完成任务点(命令行版)

<p align="center">
    <a href="https://github.com/Samueli924/chaoxing" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://so.samuelchen.cn/badge-chaoxing" alt="Github Stars" />
    </a>
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
    <a href="https://t.me/Samueli924" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/badge/-Telegram-blue?logo=telegram" alt="Telegram" />
    </a>
</p>

:star: 觉得有帮助的朋友可以给个**Star**

## :point_up: 更新通知

20220302 当前程序的接口能用于>80%的课程，存在部分新设课程使用超星的最新接口，使用本程序会出现一些报错内容。但鉴于本人已毕业，无测试相关课程的条件，且近期较为繁忙，故无继续更新接口的计划。假如还有需要的朋友可以尝试Fork本项目，抓取最新的接口提交pr，为本项目提供帮助。谢谢

## :smile: 相关项目

[Samueli924/chaoxing web版超星自动化库](https://github.com/Samueli924/chaoxing_web)

## :question: 反馈方式  

<!-- 想要交流脚本运行或运行有问题需要提问的朋友可以选择加入Telegram群聊，我会在群聊中尽量尽快回复你的消息  
[点此加入群聊](https://t.me/samueli924)   -->
暂时停止提供反馈途径

## :books: 使用方法

[使用方法](https://blog.samuelchen.cn/archives/samueli924chaoxing-readme)

## :question: FAQ(常见问题)

1. 程序相关
    - 问: 程序如何实现完成视频任务点?运行时会有**风险**吗?  
   答: 程序使用从超星AndroidApp中逆向得到的**API发送协议包**完成任务。在超星不更新其API协议的前提下能够**确保安全**  
    - 问: 为什么程序运行时间和实际时间一样，不能**一键瞬间完成**所有任务吗?  
   答: 本程序设计的初衷是在确保**绝对安全**的前提下提高效率，所以在代码中没有添加一键完成所有任务的代码。实际上，一键完成功能十分容易，在Github上已经有许多相关的优秀repo可供下载  
    - 问: 程序用到了哪些第三方库?  
   答: 本程序仅用到了requests库负责完成任务，以及rich库负责输出结果。不同于Github中存在的一些其他使用selenium库的repo，具有内存占用小，带宽占用小的优点  
    
## :heart: CONTRIBUTORS  
### :one: 感谢[Shanxuns](https://github.com/Shanxuns)修正查找任务点的正则表达式内容 [Pull #33](https://github.com/Samueli924/chaoxing/pull/33)  
### 对于代码有任何问题或建议欢迎Pull&Request  


## :warning: 免责声明  
- 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守[GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议  
- 本代码仅用于**学习讨论**，禁止**用于盈利**  
- 他人或组织使用本代码进行的任何**违法行为**与本人无关  
