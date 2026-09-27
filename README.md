# 📚 超星学习通自动完成任务点

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python" />
  <img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="License" />
</p>

自动完成超星学习通 / 超星尔雅 / 泛雅超星 的视频、音频、文档、阅读、章节检测等任务点，支持**命令行**和**网页控制台**两种使用方式。

> 2026-09-27 整课独立验收通过：118/118（60 视频、58 测验），零待完成；正式本机只读入口校验通过。测验为 55 个 100 分、2 个 80 分、1 个 75 分，课程限制 1 倍速。见 [完整验收记录](docs/NETWORK_ACCEPTANCE_20260927.md)。

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

## 本机整合入口

macOS 可双击 `start.command`，使用已有的 `$HOME/.venv/bin/python`，仅加载 `$HOME/.secrets.env` 中的 `CHAOXING_*` 配置。
其他机器也可运行 `python scripts/local.py --env-file /path/to/account.env --web`。

- 控制台的「本机题库」支持 JSON 导入、查询、编辑、删除和导出，无须另装数据库服务。
- `provider = TikuLocal,AI` 按顺序查询本机题库与已配置模型；网页端也可填写回退顺序。
- `--max-duration 1800` 或 `CHAOXING_MAX_DURATION=1800` 将运行限制在 30 分钟，已发出的请求结束后停止。
- 多账号使用 `python scripts/batch.py profiles.json`，默认只读检查；每个账号独立进程和数据目录。
- 可选的 `resource/chaoxing-player.user.js` 提供网页播放器倍速、静音控制；它不伪造完成进度。

参考项目功能对照、本机恢复记录及验证边界见 [docs/INTEGRATION.md](docs/INTEGRATION.md)。

## 🚀 快速开始（Python 3.10+）

```bash
git clone --depth=1 https://github.com/ieduer/chaoxing
cd chaoxing
pip install -r requirements.txt

python main.py --web                # 打开网页控制台（浏览器访问 http://127.0.0.1:8765 ）
# 或
python main.py                      # 按提示输入手机号、密码并选择课程
python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2
python main.py -c config.ini        # 使用配置文件
```

不使用 git 时，也可以下载 [main 分支的 ZIP](https://github.com/ieduer/chaoxing/archive/refs/heads/main.zip) 解压后在该目录中执行后面几条命令。

网页控制台里：输入手机号、密码 → 勾选要学习的课程 → 选择要完成的任务 → 点击「开始」，进度和日志实时显示。

完整的使用说明（只读检查、网页控制台各选项、命令行与环境变量、题库与重做规则、排错）见 **[docs/TUTORIAL.md](docs/TUTORIAL.md)**。

> 想启用**验证码自动识别**（应对偶发的 403 拦截）：额外安装 `pip install "ddddocr>=1.5.6"`（依赖较大）。不安装也能正常使用，遇到拦截时在浏览器里手动完成一次验证即可。

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
| `TikuCustom` | 自建题库服务器（`POST /api/search`，请求 `{question, type, options, key}`） | 需要 `custom_url`，可选 `custom_key` |
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

确认所选课程的全部任务是否完成，使用只读校验：

```bash
python main.py --verify -l '<COURSE_ID>'
# 本机 env 入口：
python scripts/local.py --verify -l '<COURSE_ID>'
```

`--verify` 逐章回读所有任务卡片，核对读取前后的服务端总进度；不会播放、答题、查询题库或发送通知。只有总进度全部完成、没有待完成任务、所有页面可识别且进度稳定时退出码才为 0，否则为 1。遇到限时停止可重新执行只读校验。它验证平台任务完成状态，不保证答题满分或实际学习效果，也不检查非任务阅读资料的内容质量。

正常命令行和网页执行结束后也会自动做同一校验。章节处理结束、缺题库跳过、未开放或未知任务、读取失败，都不能单独构成“课程已完成”；结果会列出服务端任务进度和校验问题。


逐章节核对任务点解析结果与章节页"已完成任务点"服务端计数是否一致（只读）：

```bash
python scripts/live_verify.py
```

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
    --verify        只读校验全部任务完成状态
-v, --verbose       输出调试日志
```

---

## ❗ 常见问题

- **登录失败/提示需要验证**：账号开启了双因子验证时，请在浏览器登录后，把 cookie 保存到数据目录的 `cookies.txt`，再用 `--use-cookies` 登录。
- **偶发 403 / 需要验证码**：安装 `ddddocr` 可自动识别；或在浏览器里手动完成一次验证。
- **需要答题解锁的章节卡住**：请配置题库并将 `submit` 设为 `true`。

---

## 🙏 致谢

本仓库 fork 自 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)，感谢原项目及所有[贡献者](https://github.com/Samueli924/chaoxing/graphs/contributors)。字体解密参考 [SocialSisterYi](https://github.com/SocialSisterYi)。

<a href="https://github.com/Samueli924/chaoxing/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Samueli924/chaoxing" />
</a>

## ⚖️ 免责声明

本代码遵循 [GPL-3.0 License](LICENSE)，仅用于**学习讨论**，禁止用于**任何盈利用途**。他人或组织使用本代码进行的任何**违法行为**与作者无关。

### 本机连接诊断

Python 连接在建立阶段报 `Bad file descriptor` 时，默认自动使用系统 curl 相容传输。可用 `CHAOXING_HTTP_TRANSPORT=requests` 禁用回退，或设为 `curl` 显式选择。TLS 验证、Cookie 和重定向仍保留；不支持流式请求。验证状态与限制见 [连接及课程验收记录](docs/NETWORK_ACCEPTANCE_20260927.md)。

### 视频有效进度与卡点处理

完成必须同时具备进度接口的肯定结果和独立回读任务卡的 `isPassed=true`；课程结束再核对全部任务卡及稳定的总进度。HTTP 200、播放条到终点及本地线程结束均不足以判定完成。

保留服务端断点，按任务卡指定的现实时间间隔上报（默认 60 秒），倍速不会成倍增加上报频率。媒体请求使用 5 秒连接、10 秒读取超时，标准媒体接口关闭底层叠加重试；临时网络错误最多尝试 3 次同一位置。结尾每轮最多确认 3 次；仍未确认时只补播一次，播放预算最多 180 秒，服务端确认后立即结束。仍不成功则隔离该任务，其他章节继续；不改当音频重播，也不触发整章五轮重播。失败和未确认任务会保留在失败清单，退出码非零。网络恢复等待不计为播放时间。

`--speed 2` 仍受任务卡倍速限制；明确禁用倍速的任务使用 1x。并发数可用 `--jobs` 配置，共享进度上报限流器仍生效；应根据实际服务端确认率选取，而不是单凭本地进度条。参考[实测与开源对照](docs/VIDEO_EFFICIENCY.md)。
