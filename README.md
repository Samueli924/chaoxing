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

### 源码运行（Python 3.13+）

1. clone 项目至本地

```bash
git clone --depth=1 https://github.com/Samueli924/chaoxing 
cd chaoxing
```

2. 安装依赖

```bash
pip install -r requirements.txt
```
或使用 `pip install .`（通过 pyproject.toml 安装依赖）

3. (可选直接运行)

```bash
python main.py
```

4. (可选配置文件运行)

> 复制config_template.ini文件为config.ini文件，修改文件内的账号密码内容

```bash
python main.py -c config.ini
```

5. (可选命令行运行)

```bash
python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2,课程ID3...(可选) -a [retry|ask|continue](可选)
```

> Tips:  
> 如果已安装低版本 Python 推荐使用 `uv` 运行：

```bash
uv run --python 3.13 main.py
```

使用配置文件运行 ：
```bash
uv run --python 3.13 main.py -c config.ini
```

### 打包文件运行
1. 从最新[Releases](https://github.com/Samueli924/chaoxing/releases)中下载exe文件
2. (可选直接运行) 双击运行即可
3. (可选配置文件运行) 下载config_template.ini文件保存为config.ini文件，修改文件内的账号密码内容, 执行 `./chaoxing.exe -c config.ini`
4. (可选命令行运行)`./chaoxing.exe -u "手机号" -p "密码" -l 课程ID1,课程ID2,课程ID3...(可选) -a [retry|ask|continue](可选)`

### Docker运行
1. 构建Docker镜像
   ```bash
   docker build -t chaoxing .
   ```

2. 运行Docker容器
   ```bash
   # 直接运行（将使用默认配置模板）
   docker run -it chaoxing
   
   # 使用自定义配置文件运行
   docker run -it -v /本地路径/config.ini:/config/config.ini chaoxing
   ```

3. 配置说明
   - Docker版本默认使用挂载到 `/config/config.ini` 的配置文件
   - 首次运行时，会自动将 `config_template.ini` 复制到该位置作为模板
   - 可以将本地编辑好的配置文件挂载到容器中，按照上述示例命令操作

### 题库配置说明

在你的配置文件中找到`[tiku]`，按照注释填写想要使用的题库名（即`provider`，大小写要一致），并填写必要信息，如token，然后在启动时添加`-c [你的配置文件路径]`即可。

题库会默认使用根目录下的`config.ini`文件中的配置，所以你可以复制配置模板（参照前面的说明）命名为`config.ini`，并只配置题库项`[tiku]`，这样即使你不填写账号之类的信息，不使用`-c`参数指定配置文件，题库也会根据这个配置文件自动配置并启用。

对于那些有章节检测且任务点需要解锁的课程，必须配置题库。

**提交模式与答题**
不配置题库（既不提供配置文件，也没有放置默认配置文件`config.ini`或填写要使用的题库）视为不使用题库，对于章节检测等需要答题的任务会自动跳过。
题库覆盖率：搜到的题目占总题目的比例
提交模式`submit`值为

- `true`：会答完题，达到题库题目覆盖率提交，没达到只保存，**正确率不做保证**。
- `false`：会答题，但是不会提交，仅保存搜到答案的，随后你可以自行前往学习通查看、修改、提交。**任何填写不正确的`submit`值会被视为`false`**

> 题库名即`answer.py`模块中根据`Tiku`类实现的具体题库类，例如`TikuYanxi`（言溪题库），在填写时，请务必保持大小写一致。

### 已关闭任务点处理配置说明

在配置文件的 `[common]` 部分，可以通过 `notopen_action` 选项配置遇到已关闭任务点时的处理方式:

- `retry` (默认): 遇到关闭的任务点时尝试重新完成上一个任务点，如果连续重试 3 次仍然失败 (或未配置题库及自动提交) 则停止
- `ask`: 遇到关闭的任务点时询问用户是否继续。选择继续后会自动跳过连续的关闭任务点，直到遇到开放的任务点
- `continue`: 自动跳过所有关闭的任务点，继续检查和完成后续任务点

也可以通过命令行参数 `-a` 或 `--notopen-action` 指定处理方式，例如：

```bash
python main.py -a ask  # 使用询问模式
```

### 章节学习次数配置说明

在配置文件的 `[common]` 部分，可以通过下面两个选项控制章节学习次数功能：

- `add_learning_count = false`：是否在完成刷课任务后，继续对课程章节执行学习次数增加
- `target_count = 100`：章节学习次数的目标总次数，程序会轮询课程章节直到达到该次数

当前实现会先完成所选课程的任务点，再统一执行章节学习次数增加流程。如果开启了 `add_learning_count`，它会作为刷课完成后的追加步骤执行，而不是独立模式。

**外部通知配置说明**

这功能会在所有课程学习任务结束后，或是程序出现错误时，使用外部通知服务推送消息告知你（~~有用但不多~~）

与题库配置类似，不填写视为不使用，按照注释填写想要使用的外部通知服务（也是`provider`，大小写要一致），并填写必要的`url`

## :heart: CONTRIBUTORS

![Alt](https://repobeats.axiom.co/api/embed/d3931e84b4b2f17cbe60cafedb38114bdf9931cb.svg "Repobeats analytics image")  

<a style="margin-top: 15px" href="https://github.com/Samueli924/chaoxing/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Samueli924/chaoxing" />
</a>

## :warning: 免责声明
- 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE) 协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE) 协议
- 本代码仅用于**学习讨论**，禁止**用于盈利**
- 他人或组织使用本代码进行的任何**违法行为**与本人无关

## 任务中心与交互式入口

新增任务中心教学任务：视频、文档阅读、章节同步、作业、主题讨论和 AI 实践。
任务按分组顺序解锁，完成状态以平台复查为准；失败不会影响章节任务。
思考题暂不支持，文档时长是否有效取决于平台返回的状态。
真实观看时长、请求间隔和顺序解锁不能通过配置绕过。

```sh
python setup_wizard.py
./cx
./cx discuss
./cx review
```

向导支持选择账号、课程和任务范围。讨论区挑帖必须逐条预览和确认，
`--yes` 不绕过这一确认。任务讨论遵循 `task_center_submit_mode`：
`confirm` 逐项确认；`auto` 在检查与留痕后发送。

账号配置、密码、Cookie、缓存和日志保存在 `~/.chaoxing/`。
生成的实质性文字在请求之前持久化到 `~/.chaoxing/reviews/`；
写入失败会阻止该项提交。记录区分取消、失败、未确认和平台接受。
客观题选项显示在运行记录中，不进入正文复核文件。
文本检查不能完整判断真实性，用户仍应复核内容。

可选题库和模型服务会接收问题及相关上下文；写作服务可能接收讨论参考文本，
通知服务会接收配置的通知。日志脱敏不能去除任意正文中的所有私人事实。
不要公开凭据、账号数据或原始抓包；若凭据已公开，应在来源处撤销或更换。
删除当前文件不会清除 Git 历史。公开贡献仅包含可维护的代码、
用户文档和合成测试数据；工作笔记保存在仓库之外。

## 安装包和离线验证

```sh
pip install .
chaoxing --help
chaoxing-setup
python -m unittest discover -s tests -t .
python tools/audit/publication_guard.py
python tools/audit/01_human_likeness_audit.py --selftest
```

安装包包含字体映射和配置模板，支持在仓库目录之外运行。
生成内容、取消和失败状态、顺序解锁与接口解析均有离线回归测试。
开发时还应检查 Python 3.13、安装包和上游自动审查结果。
公开贡献应从最新上游历史建立，按功能拆分并说明依赖，保留许可与作者归属。
