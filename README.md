# :computer: 超星学习通自动化 - 图形化界面版

> :bulb: 本仓库是 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) 的 Fork，在原命令行版基础上新增了**本地 Web 图形化控制界面**（`webgui.py`）。双击即用，无需命令行，适合不熟悉命令行的 Windows 用户。

<p align="center">
    <a href="https://github.com/Donghs05/chaoxing10086" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/github/stars/Donghs05/chaoxing10086" alt="Github Stars" />
    </a>
    <a href="https://github.com/Donghs05/chaoxing10086" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/github/forks/Donghs05/chaoxing10086" alt="Github Forks" />
    </a>
    <a href="https://github.com/Donghs05/chaoxing10086" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/github/languages/code-size/Donghs05/chaoxing10086" alt="Code-size" />
    </a>
    <a href="https://github.com/Samueli924/chaoxing" target="_blank" style="margin-right: 20px; font-style: normal; text-decoration: none;">
        <img src="https://img.shields.io/badge/上游-Samueli924%2Fchaoxing-blue" alt="Upstream" />
    </a>
</p>

:muscle: 本项目的最终目的是通过开源消灭所谓的付费刷课平台，希望有能力的朋友都可以为这个项目提交代码，支持本项目的良性发展

:star: 觉得有帮助的朋友可以给个Star

## :sparkles: 本仓库新增功能

| 功能 | 说明 |
|---|---|
| :globe_with_meridians: 图形化界面 | 本地 Web 控制面板，双击 `启动网站.bat` 即可在浏览器里操作 |
| :lock: 安全加固 | Host 头白名单、CSRF token 校验、进程锁，防止并发冲突 |
| :video_camera: 实时日志 | SSE 推送刷课日志到网页，实时查看进度 |
| :file_folder: 课程选择 | 登录后自动拉取课程列表，勾选要刷的课程 |
| :shield: 防风控参数 | 倍速、并发数、章节延迟、API 间隔等可调 |

## :books: 使用方法

### 图形化界面运行（Windows 推荐，无需命令行）

1. 准备依赖（需 Python 3.13+）

```bash
pip install -r requirements.txt
```

2. 双击 `启动网站.bat`

   - 会弹出黑色命令行窗口（标题为 `Chaoxing Console - close this window to STOP`），并自动打开浏览器访问 `http://127.0.0.1:5000`
   - 网站只监听本机 127.0.0.1，不会暴露到局域网/公网

3. 在网页里填写账号密码，点「拉取课程」勾选要刷的课程，按需调整倍速/并发/防风控节奏，点「开始学习」即可

   - 刷课日志会同时在网页日志面板和黑色命令行窗口里实时显示
   - 关闭方式：双击 `关闭网站.bat`，或直接关闭黑色命令行窗口（会一并停止正在运行的刷课任务）

4. 配置文件说明

   - 首次运行会在同目录生成 `config_gui.ini`（保存你填写的账号、课程 ID、防风控参数等）
   - 模板见 `config_gui_example.ini`，可参考其中的字段说明
   - `config_gui.ini` 默认被 `.gitignore` 忽略，不会上传到 GitHub

> Tips：单实例保护 —— 如果端口 5000 已被占用（说明网站已在运行），`启动网站.bat` 会直接打开浏览器而不会重复启动；如需重启请先 `关闭网站.bat`。

### 命令行运行（同上游）

```bash
git clone --depth=1 https://github.com/Donghs05/chaoxing10086
cd chaoxing10086
pip install -r requirements.txt
python main.py
```

更多命令行参数、题库配置、Docker 运行等说明，请参考[上游仓库 README](https://github.com/Samueli924/chaoxing#readme)。

## :link: 与上游的关系

- 本仓库 Fork 自 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)，遵循原项目的 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE) 协议
- 本仓库的改动（图形化界面 + 安全加固）已通过 [PR #634](https://github.com/Samueli924/chaoxing/pull/634) 提交给上游，等待原作者审核合并
- 如果上游合并，建议直接使用上游仓库；在此之前，本仓库可作为带图形化界面的临时替代

## :heart: 致谢

- 感谢 [Samueli924](https://github.com/Samueli924) 和[所有上游贡献者](https://github.com/Samueli924/chaoxing/graphs/contributors)的开源工作
- 感谢 [CodeRabbit](https://coderabbit.ai) 的 AI 代码审核

## :warning: 免责声明

- 本代码遵循 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE) 协议，允许**开源/免费使用和引用/修改/衍生代码的开源/免费使用**，不允许**修改和衍生的代码作为闭源的商业软件发布和销售**，禁止**使用本代码盈利**，以此代码为基础的程序**必须**同样遵守 [GPL-3.0 License](https://github.com/Samueli924/chaoxing/blob/main/LICENSE) 协议
- 本代码仅用于**学习讨论**，禁止**用于盈利**
- 他人或组织使用本代码进行的任何**违法行为**与本人无关
