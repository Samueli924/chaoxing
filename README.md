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
20241021更新通知： 感谢[sz134055](https://github.com/sz134055)提交代码[PR #360](https://github.com/Samueli924/chaoxing/pull/360)，**添加了对题库答题的支持**  

## :books: 使用方法

### 源码运行
1. `git clone --depth=1 https://github.com/Samueli924/chaoxing` 项目至本地
2. `cd chaoxing`
3. `pip install -r requirements.txt`
4. (可选直接运行) `python main.py`
5. (可选配置文件运行) 复制config_template.ini文件为config.ini文件，修改文件内的账号密码内容, 执行 `python main.py -c config.ini`
6. (可选命令行运行)`python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2,课程ID3...(可选)`

### 打包文件运行
1. 从最新[Releases](https://github.com/Samueli924/chaoxing/releases)中下载exe文件
2. (可选直接运行) 双击运行即可
3. (可选配置文件运行) 下载config_template.ini文件保存为config.ini文件，修改文件内的账号密码内容, 执行 `./chaoxing.exe -c config.ini`
4. (可选命令行运行)`./chaoxing.exe -u "手机号" -p "密码" -l 课程ID1,课程ID2,课程ID3...(可选)`

### 题库配置说明

在你的配置文件中找到`[tiku]`，按照注释填写想要使用的题库名（即`provider`，大小写要一致），并填写必要信息，如token，然后在启动时添加`-c [你的配置文件路径]`即可。

题库会默认使用根目录下的`config.ini`文件中的配置，所以你可以复制配置模板（参照前面的说明）命名为`config.ini`，并只配置题库项`[tiku]`，这样即使你不填写账号之类的信息，不使用`-c`参数指定配置文件，题库也会根据这个配置文件自动配置并启用。

对于那些有章节检测且任务点需要解锁的课程，必须配置题库。

**提交模式与答题**
不配置题库（既不提供配置文件，也没有放置默认配置文件`config.ini`或填写要使用的题库）视为不使用题库，对于章节检测等需要答题的任务会自动跳过。

提交模式`submit`值为
- `true`：会答完题自动提交，**正确率不做保证**。
- `false`：会答题，但是不会提交，仅保存，随后你可以自行前往学习通查看、修改、提交。**任何填写不正确的`submit`值会被视为`false`**

> 题库名即`answer.py`模块中根据`Tiku`类实现的具体题库类，例如`TikuYanxi`（言溪题库），在填写时，请务必保持大小写一致。


## :heart: CONTRIBUTORS
![Alt](https://repobeats.axiom.co/api/embed/d3931e84b4b2f17cbe60cafedb38114bdf9931cb.svg "Repobeats analytics image")  

<a style="margin-top: 15px" href="https://github.com/Samueli924/chaoxing/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Samueli924/chaoxing" />
</a>

## :warning: 免责声明
- 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE) 协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE) 协议
- 本代码仅用于**学习讨论**，禁止**用于盈利**
- 他人或组织使用本代码进行的任何**违法行为**与本人无关
