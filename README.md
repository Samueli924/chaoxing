# 📚 超星学习通自动完成任务点

<p align="center">
  <a href="https://github.com/Samueli924/chaoxing"><img src="https://img.shields.io/github/stars/Samueli924/chaoxing" alt="Stars" /></a>
  <a href="https://github.com/Samueli924/chaoxing"><img src="https://img.shields.io/github/forks/Samueli924/chaoxing" alt="Forks" /></a>
  <a href="https://github.com/Samueli924/chaoxing/releases"><img src="https://img.shields.io/github/v/release/Samueli924/chaoxing?display_name=tag&sort=semver" alt="Release" /></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python" />
</p>

自动完成超星学习通 / 超星尔雅 / 泛雅超星 的视频、音频、文档、阅读、章节检测等任务点，支持**命令行**和**网页控制台**两种使用方式。

> ⚠️ 本项目仅用于学习与技术交流，请遵守学校与平台的相关规定，使用产生的一切后果由使用者自行承担。通过开源消灭付费刷课平台，欢迎贡献代码，觉得有用请点个 Star ⭐

---

## ✨ 特性

- **只需手机号 + 密码即可运行**，其余全部有合理默认值，开箱即用
- **网页控制台**：不熟悉命令行的用户可以在浏览器里登录、勾选课程、选择任务、查看进度（`--web`）
- 视频 / 音频 / 文档 / 阅读 / 章节检测 / 直播 全类型任务点
- 多门课程、多章节**并发**完成；闯关式课程会自动按顺序解锁
- 章节检测支持多种题库并可**按顺序回退**：GO题（免费）、言溪、LIKE、AI 大模型、硅基流动、自建题库、手动输入
- 章节检测提交后**自动核对成绩并针对错题重做**
- 完成后可选**推送通知**（Server酱 / Qmsg / Bark / Telegram）
- 支持**增加章节学习次数**
- 一次登录后自动保存登录状态，下次无需重复输入

---

## 🚀 快速开始（三选一）

### 方式一：网页控制台（最简单，推荐新手）

1. 从 [Releases](https://github.com/Samueli924/chaoxing/releases) 下载 `chaoxing-win64.zip` 并解压
2. **双击 `chaoxing.exe`**，会自动打开浏览器进入控制台（也可手动访问 http://127.0.0.1:8765 ）
3. 在网页里输入手机号、密码 → 勾选要学习的课程 → 选择要完成的任务 → 点击「开始」，进度和日志实时显示

> 源码运行方式：`python main.py --web`

### 方式二：可执行文件（命令行）

从 [Releases](https://github.com/Samueli924/chaoxing/releases) 下载解压后：

```bat
chaoxing.exe -u 手机号 -p 密码
:: 或直接双击运行，按提示输入
```

### 方式三：源码运行（Python 3.10+）

```bash
git clone --depth=1 https://github.com/Samueli924/chaoxing
cd chaoxing
pip install -r requirements.txt

python main.py                      # 按提示输入手机号、密码并选择课程
# 或
python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2
# 或使用配置文件
python main.py -c config.ini
# 或打开网页控制台
python main.py --web
```

> 想启用**验证码自动识别**（应对偶发的 403 拦截）：额外安装 `pip install "ddddocr>=1.5.6"`（依赖较大）。不安装也能正常使用，遇到拦截时在浏览器里手动完成一次验证即可。Releases 里的 exe 已内置该功能。

---

## ⚙️ 配置

程序会**自动查找**当前目录或程序目录下的 `config.ini`，也可用 `-c` 指定。把 `config_template.ini` 复制成 `config.ini`，通常**只需填手机号和密码**：

```ini
[common]
username = 手机号
password = 密码
; course_list =            ; 留空则运行时选择

[tiku]
provider = TikuGo          ; 免费题库，无需任何配置
submit = false             ; 只保存答案不提交；改成 true 则自动提交（正确率不保证）
```

完整可选项见 [`config_template.ini`](config_template.ini) 内的注释。

### 也可以用环境变量（适合 Docker / 服务器）

| 环境变量 | 说明 |
| --- | --- |
| `CHAOXING_USERNAME` / `CHAOXING_PASSWORD` | 手机号 / 密码 |
| `CHAOXING_COURSE_LIST` | 课程ID，逗号分隔 |
| `CHAOXING_TIKU_PROVIDER` | 题库，如 `TikuGo` |
| `CHAOXING_TIKU_SUBMIT` | 是否提交答案 `true`/`false` |
| `CHAOXING_DATA_DIR` | cookies / 缓存 / 日志的存放目录 |
| `CHAOXING_WEB_HOST` / `CHAOXING_WEB_PORT` / `CHAOXING_WEB_TOKEN` | 网页控制台监听地址 / 端口 / 访问口令 |

优先级：命令行参数 > 环境变量 > 配置文件 > 默认值。

---

## 🐳 Docker

```bash
docker build -t chaoxing .

# 网页控制台模式（默认）：对外开放时会自动生成访问口令并打印到日志
docker run -d -p 8765:8765 -v $(pwd)/data:/data \
  -e CHAOXING_WEB_TOKEN=自定义口令 chaoxing

# 命令行模式
docker run -it -v $(pwd)/data:/data chaoxing -u 手机号 -p 密码
```

`/data` 用于持久化登录状态、答案缓存与日志。

---

## 🧩 题库说明

在 `[tiku]` 的 `provider` 中填写题库名（多个用英文逗号分隔，按顺序回退）：

| provider | 题库 | 是否需要配置 |
| --- | --- | --- |
| `TikuGo` | GO题 / 网课小工具 | 免费，无需配置（可选填 `go_authorization` 解除限流）|
| `TikuYanxi` | 言溪题库 | 需要 `tokens` |
| `TikuLike` | LIKE 知识库 | 需要 `tokens` |
| `AI` | 任意兼容 OpenAI 接口的大模型 | 需要 `endpoint` / `key` / `model` |
| `SiliconFlow` | 硅基流动 | 需要 `siliconflow_key` |
| `TikuAdapter` | [自建题库](https://github.com/DokiDoki1103/tikuAdapter) | 需要 `url` |
| `TikuManual` | 手动输入（命令行交互）| 无 |

- `submit = false`（默认）：只保存搜到的答案，不提交，可自行到学习通检查修改后提交。
- `submit = true`：达到覆盖率即提交；**需要解锁的章节**会强制提交以继续后续学习。**正确率不做保证。**
- 不配置题库时，章节检测会被自动跳过（可能导致需要答题解锁的章节无法继续）。

---

## 🔍 自检

网站结构变动导致异常时，可运行只读自检（登录后检查各页面能否解析，不完成也不提交任何任务）：

```bash
python main.py --check
```

会在数据目录生成 `selfcheck_report.md`。

---

## 🖥️ 常用命令行参数

```
-u, --username      手机号
-p, --password      密码
-l, --list          课程ID列表，逗号分隔（不填则运行时选择）
-c, --config        配置文件路径（默认自动查找 config.ini）
-s, --speed         视频倍速 1~2（默认1）
-j, --jobs          并发章节数（默认4）
-a, --notopen-action  未开放章节的处理 retry/ask/continue
-lc, --add-learning-count  完成后增加章节学习次数
-tc, --target-count 章节学习次数目标（默认100）
    --web           启动网页控制台
    --host/--port   网页控制台监听地址/端口
    --check         只读自检
-v, --verbose       输出调试日志
```

---

## ❗ 常见问题

- **登录失败/提示需要验证**：账号开启了双因子验证时，请在浏览器登录后，把 cookie 保存到数据目录的 `cookies.txt`，再用 `--use-cookies` 登录。
- **偶发 403 / 需要验证码**：安装 `ddddocr` 可自动识别；或在浏览器里手动完成一次验证。
- **需要答题解锁的章节卡住**：请配置题库并将 `submit` 设为 `true`。

---

## 🙏 致谢

感谢 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) 及所有[贡献者](https://github.com/Samueli924/chaoxing/graphs/contributors)。字体解密参考 [SocialSisterYi](https://github.com/SocialSisterYi)。

<a href="https://github.com/Samueli924/chaoxing/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Samueli924/chaoxing" />
</a>

## ⚖️ 免责声明

本代码遵循 [GPL-3.0 License](LICENSE)，仅用于**学习讨论**，禁止用于**任何盈利用途**。他人或组织使用本代码进行的任何**违法行为**与作者无关。
