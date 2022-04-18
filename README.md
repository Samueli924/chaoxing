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

:star: 觉得有帮助的朋友可以给个**Star**

## :point_up: 更新通知  
20220404更新通知： 适配超星学习通最新接口的v2.3.0版本已发布，现已适配所有的视频任务。  

## :question: 反馈方式  

[我的Telegram群组](https://t.me/Samueli924)

## :books: 使用方法

### 源码运行(推荐)
1. 提前准备： Python版本>=3.9 因为使用到了:=表达式。urllib3=1.25.11 因为后面的版本对代理的支持有变化。
2. git clone 项目至本地
3. pip install -r requirements.txt
4. python main.py 运行程序
5. 可选参数 -debug 开启DEBUG模式 --no-adopt 禁用自适应速率 --no-log 不输出日志 --no-logo 隐藏开头项目LOGO --no-sec 关闭隐私保护

## :question: FAQ(常见问题)

1. 程序相关
    - 问: 程序如何实现完成视频任务点?运行时会有**风险**吗?  
   答: 程序使用从超星AndroidApp中逆向得到的**API发送协议包**完成任务。在超星不更新其API协议的前提下能够**确保安全**  
    - 问: 为什么程序运行时间和实际时间一样，不能**一键瞬间完成**所有任务吗?  
   答: 本程序设计的初衷是在确保**绝对安全**的前提下提高效率，所以在代码中没有添加一键完成所有任务的代码。实际上，一键完成功能十分容易，在Github上已经有许多相关的优秀repo可供下载  
    - 问: 程序用到了哪些第三方库?  
   答: 本程序仅用到了requests库负责完成任务。不同于Github中存在的一些其他使用selenium库的repo，具有内存占用小，带宽占用小的优点  
    
## :heart: CONTRIBUTORS  
### :one:感谢[huajijam](https://github.com/huajijam)对chaoxing项目的贡献! [PR #73](https://github.com/Samueli924/chaoxing/pull/73)
### :two:感谢[ljy0309](https://github.com/lyj0309)修复Attachments BUG! [PR #70](https://github.com/Samueli924/chaoxing/pull/70)
### :three:感谢[Shanxuns](https://github.com/Shanxuns)修正查找任务点的正则表达式内容 [Pull #33](https://github.com/Samueli924/chaoxing/pull/33)  
### 对于代码有任何问题或建议欢迎Pull&Request  


## :warning: 免责声明  
- 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守[GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE)协议  
- 本代码仅用于**学习讨论**，禁止**用于盈利**  
- 他人或组织使用本代码进行的任何**违法行为**与本人无关  
