# :computer: 超星学习通自动化完成任务点

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

## :books: 使用方法

### 源码运行
1. `git clone --depth=1 https://github.com/AneryCoft/chaoxing` 项目至本地
2. `cd chaoxing`
3. `pip install -r requirements.txt` 或者 `pip install .`(通过 pyproject.toml 安装依赖)
4. (可选直接运行) `python main.py`
5. (可选配置文件运行) 复制config_template.ini文件为config.ini文件，修改文件内的账号密码内容, 执行 `python main.py -c config.ini`
6. (可选命令行运行)`python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2,课程ID3...(可选) -a [retry|ask|continue](可选)`

### 打包文件运行
1. 从最新[Releases](https://github.com/AneryCoft/chaoxing/releases)中下载exe文件
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

**外部通知配置说明**

这功能会在所有课程学习任务结束后，或是程序出现错误时，使用外部通知服务推送消息告知你（~~有用但不多~~）

与题库配置类似，不填写视为不使用，按照注释填写想要使用的外部通知服务（也是`provider`，大小写要一致），并填写必要的`url`

## :heart: CONTRIBUTORS

![Alt](https://repobeats.axiom.co/api/embed/d3931e84b4b2f17cbe60cafedb38114bdf9931cb.svg "Repobeats analytics image")  

<a style="margin-top: 15px" href="https://github.com/AneryCoft/chaoxing/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=AneryCoft/chaoxing" />
</a>

## :warning: 免责声明
- 本代码遵循 [GPL-3.0 License](https://github.com/AneryCoft/chaoxing/blob/main/LICENSE) 协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守 [GPL-3.0 License](https://github.com/AneryCoft/chaoxing/blob/main/LICENSE) 协议
- 本代码仅用于**学习讨论**，禁止**用于盈利**
- 他人或组织使用本代码进行的任何**违法行为**与本人无关
