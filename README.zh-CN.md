# 超星学习通自动刷课（命令行版）

[English](README.md) | **中文**

[![CI](https://github.com/Samueli924/chaoxing/actions/workflows/tests.yml/badge.svg)](https://github.com/Samueli924/chaoxing/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/Samueli924/chaoxing?include_prereleases)](https://github.com/Samueli924/chaoxing/releases)
[![Last commit](https://img.shields.io/github/last-commit/Samueli924/chaoxing)](https://github.com/Samueli924/chaoxing/commits/main)
[![许可证](https://img.shields.io/github/license/Samueli924/chaoxing)](LICENSE)

一个命令行工具：不打开浏览器就能完成超星学习通（泛雅）的课程任务，覆盖平台上的两个入口——**章节**（目录）和**任务中心 · 教学任务**。


> **支持范围。** 任务中心支持视频、章节同步、思维阶梯、作业和主题讨论；文档时长类、新版情景对话、思考题与课堂活动/签到需要手动处理。
>
> 只有平台自己的状态复查返回「完成」，程序才会记为完成——绝不因为点过提交就算完成。

本文档中的控制台示例取自程序实际输出的中文界面。

## 覆盖范围

| 入口 | 状态 | 覆盖 |
| --- | :---: | --- |
| **章节（目录）** | ✅ | 全部任务点：视频、文档、阅读、章节测验、直播 |
| **任务中心 · 教学任务** | 🟡 | 见下方分类型表格 |

| 任务点类型 | 状态 | 处理方式 |
| --- | :---: | --- |
| 视频 | ✅ | 走任务引擎播放器的上报接口，按真实播放节奏打点 |
| 章节同步 | ✅ | 复用章节刷课，并调用平台的章节成绩同步 |
| AI 实践 | 🟡 | 支持「思维阶梯」：走 `main-talk` SSE 对话，提交后再请求 end-report 让平台现算成绩。新版情景对话是另一套接口，暂未适配 |
| 作业 | ✅ | 选择 / 判断 / 填空走题库或 AI；简答题由 `api/ai_writer.py` 生成 |
| 主题讨论 | ✅ | 读已有回复做风格参考，生成一条不重复的回复并提交 |
| 文档 | ⚠️ | 需要读到底（readEnd）的文档能完成；只要求阅读时长的文档未能确认平台计入阅读时长，因此保持未完成，同一文档 24 小时内不重复读 |
| 思考题 | ❌ | 不支持——程序会明确提示你手动完成 |
| 课堂活动 / 签到 | ❌ | 不支持 |

## 它不做什么

- **不假装完成。** 只有平台状态复查通过，才记为完成。
- **不加速播放。** 有时长要求的视频按 1 倍速播放；文档按 30 秒节奏打点。
- **不跳过解锁顺序。** 任务中心分组按顺序解锁，程序会重新拉取分组状态，不会往前跳。
- **不在你的机器之外运行。** 没有托管服务、没有埋点，只与超星和你配置的答题服务通信。
- **不处理思考题、课堂活动和签到。**

## 环境要求

- Python 3.13 或更高版本（在 3.13 / 3.14 上测试）
- macOS / Linux / Windows。`./cx` 需要 Bash；Windows 上运行 `python setup_wizard.py`
- 依赖：`python -m pip install -r requirements.txt`（requests、beautifulsoup4、loguru、tqdm、openai、ddddocr 等）
- 可选：AI 答题需要 DeepSeek API Key；题库需要对应的 token；推送通知需要相应的服务

## 快速开始

### 1. 安装 Python 3.13 或更高版本

到 [python.org](https://www.python.org/downloads/) 下载并安装。Windows 安装时勾选 **Add python.exe to PATH**。

### 2. 下载项目

```bash
git clone https://github.com/Samueli924/chaoxing.git
cd chaoxing
python -m pip install -r requirements.txt
```

macOS / Linux 上如果找不到 `python`，用 `python3`。

### 3. 启动向导

macOS / Linux：

```bash
./cx
```

Windows：

```powershell
python setup_wizard.py
```

向导一次只问一个问题：选账号（第一次先添加）→ 登录 → 刷什么 → 讨论怎么处理 → 选课程 → 每门课刷多少个任务点 → 确认。

之后再次运行 `./cx` 会沿用已保存的配置。`cx setup` 改答题方式或通知；`cx --yes` 跳过最后的确认。

> **时间是真实的。** 几小时视频的课程就要跑几小时。让它挂在后台跑，可选的通知能在结束时告诉你。

> **AI 答题走 DeepSeek API**，一门课可能花很少的钱。也可以选题库服务、手动答题，或干脆不答——见[答题](#答题)。

<details>
<summary>其他运行方式</summary>

```bash
python main.py -c config.ini                        # 使用 ~/.chaoxing/config.ini
python main.py -u <phone> -p <password> -l <ids>    # 指定账号和课程
```

向导会自动写好 `~/.chaoxing/config.ini`；仓库里的 `config_template.ini` 有全部选项说明。

</details>

## 使用

| 命令 | 作用 |
| --- | --- |
| `./cx` | 交互向导（推荐） |
| `cx setup` | 修改答题方式或通知 |
| `cx discuss` | 浏览讨论区，回复你挑的帖子（`--list-topics` 只列出） |
| `cx review` | 查看已提交的 AI 写的内容（`--days N`、`--all`、`--list`） |
| `cx --yes` | 同 `./cx`，跳过最后确认 |
| `python main.py -c config.ini` | 用 `~/.chaoxing/config.ini` 直接运行 |
| `python main.py -u <phone> -p <password> -l <ids>` | 指定账号和课程。共享终端里别用 `-p`，会留在命令历史里 |

每次开刷前会先扫描一遍还差什么，只读；扫描失败不会阻断刷课。

```text
  开始前扫描
  ----------------------------------------------
  示例课程
    章节       139 节 - 已完成 37 - 剩余 102，从 1.1 课程介绍 继续
    教学任务   9 个 - 任务点 77 个（已完成 62 - 待完成 9 - 未解锁 6）
    待完成     作业 1 - 主题讨论 1 - 视频 2 - 文档 3 - AI 实践 2
  ----------------------------------------------
```

### 数字与范围

你输入的数字是**这一轮要刷多少个未完成的任务点**。已完成的永远跳过，输入 `all` 或直接回车表示把剩下的都刷完。章节和教学任务分别计数。

| 范围 | 会跑什么 |
| --- | --- |
| 章节 + 任务中心 | 两个入口都跑（推荐） |
| 只刷章节 | 只跑章节 |
| 只刷任务中心 | 只跑教学任务 |
| 只刷讨论 | 只跑讨论，本轮其它全部跳过。也可用 `--only-discussion` |

主题讨论属于任务中心，所以第一、第三种范围也包含它。

### 讨论

| 模式 | 入口 | 做什么 |
| --- | --- | --- |
| 自动刷任务讨论 | 包含在任务中心里 | 按课程要求的顺序走讨论任务点，读已有回复，写一条普通的回复并提交 |
| 讨论区挑帖 | 向导里选，或 `./cx discuss` | 先列出讨论区，你挑帖子（`1,3,5` / `1-3` / `all`），每一条先给草稿，问 `y/n` 再发 |

两种模式都会读已有回复、检查草稿、实时显示，并在提交前存到 `~/.chaoxing/reviews/`。讨论区挑帖必须逐条确认，`--yes` 不会绕过确认。任务讨论遵循 `task_center_submit_mode`：`confirm` 模式逐项确认，`auto` 模式在检查和留痕后发送。客户端检查已有回复以避免重复。

### 答题

| 向导选项 | 配置 `provider` | 说明 |
| --- | --- | --- |
| DeepSeek AI | `AI` | 推荐。需要 DeepSeek API Key |
| 题库 | `TikuYanxi` | 需要题库方提供的 token |
| 题库（GO） | `TikuGo` | 可选授权 |
| 题库 + AI 兜底 | `TikuYanxi,AI` | 更准，仍需要 token |
| 题库（GO）+ AI 兜底 | `TikuGo,AI` | 更准 |
| 手动 | `TikuManual` | 每道题你自己输 |
| 不答题 | *（空）* | 跳过测验，可能卡住章节解锁 |

客观题只提交选项字母或对/错，不会提交解释性长句。简答题和讨论回复由 `api/ai_writer.py` 生成。

### 提交

`task_center_submit_mode = auto`（默认）答完自动在后台提交；`confirm` 每次提交前先给预览并询问。可在配置里改，也可用 `--task-center-submit-mode`。两种方式都以平台状态复查为准。

### 通知（可选）

支持 Bark、ServerChan、Telegram、Qmsg。把 `[notification] provider` 留空即可关闭。开始、结束、被中断、出错时会推送。

### 配置

向导会写好 `~/.chaoxing/config.ini`，`config_template.ini` 有全部选项。常用项：

| 配置项 | 默认值 | 含义 |
| --- | --- | --- |
| `chapter_study` | `true` | 刷章节 |
| `task_center` | `true` | 刷任务中心教学任务 |
| `only_discussion` | `false` | 只刷讨论 |
| `discussion_mode` | `task` | `task` 自动刷任务讨论；`board` 进讨论区挑帖 |
| `jobs` | `2` | 并行处理的任务点数 |
| `speed` | `2` | 视频倍速（有时长要求的视频固定 1 倍速） |
| `max_points_per_course` | *（空）* | 每门课刷多少个未完成章节任务点 |
| `max_tasks_per_course` | *（空）* | 每门课刷多少个未完成教学任务 |
| `task_center_submit_mode` | `auto` | `auto` 或 `confirm` |
| `serial_video` | `false` | 一个视频一个视频地刷（平台回滚进度时用） |
| `ai_practice_min_score` | `85` | AI 实践的目标分数 |
| `ai_practice_max_rounds` | `5` | AI 实践的重试次数 |

## 查看 AI 写的内容

AI 写过并提交上去的实质内容——测验简答、作业简答、讨论回复、AI 实践作答——运行时会实时打印，同时落盘：

```text
~/.chaoxing/reviews/YYYY-MM-DD.md     # 每天一个 Markdown 文件
~/.chaoxing/reviews/index.jsonl       # cx review 用的索引
```

| 命令 | 显示 |
| --- | --- |
| `./cx review` | 今天的记录，输编号看全文 |
| `./cx review --days 7` | 最近 7 天 |
| `./cx review --all` | 全部记录 |
| `./cx review --list` | 只列清单 |

客观题（字母、对/错）不记录，没什么可看的。记录里不会有密码、cookie 或 token。

## 数据与隐私

```text
~/.chaoxing/
  config.ini        # 你的设置
  accounts/         # 按手机号分开的凭据、cookie 和运行配置
  cache.json        # 答案缓存
  reviews/          # 留痕的 AI 文本
  submissions.json  # 本地账本，避免重复提交作业
  chaoxing.log      # 运行日志（默认 DEBUG；CX_LOG_LEVEL=TRACE 更详细）
```

- 这个目录里的内容不会提交到仓库。目录权限 `0700`，文件权限 `0600`。
- 每个手机号各自保存凭据和 cookie，账号之间不会互相覆盖。
- 程序只与超星和你配置的答题服务通信，没有埋点，也不会上传课程内容。
- 登录验证码在本机用 OCR 识别，不发给第三方。
- 请只用于你自己的账号，并遵守学校的相关规定。

## 常见问题

| 问题 | 怎么办 |
| --- | --- |
| 登录验证码一直失败 | 再运行一次 `./cx`；连续失败程序会停 60 秒再试。仍不行就先在浏览器登录一次 |
| 任务中心某个分组一直不解锁 | 分组按顺序解锁，平台同步有延迟，过一会儿再跑 |
| 思考题被跳过 | 不支持，请手动完成 |
| 文档任务一直是未完成 | 已知问题：只要求时长的文档平台不计入。程序不会假装完成，24 小时内不重复读同一份 |
| AI 实践分数低于及格线 | 成绩由平台判，程序用推理模型 + 多数投票作答，并按配置的重试次数再试 |
| AI 答题失败或 Key 被拒 | 检查 Key 和余额。配了兜底链（如 `TikuYanxi,AI`）会换下一个服务，否则跳过该测验 |
| 日志在哪 | `~/.chaoxing/chaoxing.log`。提 issue 时只贴脱敏片段，里面含账号信息 |
| 怎么停下来 | 按 `q` 或 `Ctrl+C`。已经上报给平台的进度会保留，重跑会接着走 |
| 能关掉终端吗 | 不能。视频只有在运行时才走进度，用 `tmux`、`screen` 或 `nohup` 挂着 |
| 重跑会重刷已完成的任务吗 | 不会。先读平台状态，已完成的任务点直接跳过 |
| cookie 过期 | 重新运行 `./cx` 登录，按账号保存的 cookie 会自动刷新 |
| `pip install` 装 `lxml` / `ddddocr` 失败 | 用干净的虚拟环境：`python -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| 提示 `./cx: Permission denied` | 执行一次 `chmod +x cx`；Windows 上改用 `python setup_wizard.py` |

## 开发

```bash
make test      # 离线单测（335 个，不联网、不碰真实账号）
make lint      # 编译检查 + 单测，提交前跑一遍
make test-313  # 用 CI 的版本（3.13）再跑一遍；本机可能是 3.14
make doctor    # 环境自检
```

单测用标准库 `unittest` + 假实现（`FakeSession`、`FakeTC`），不用 pytest、不用 ruff、不联网。CI（[.github/workflows/tests.yml](.github/workflows/tests.yml)）在每次 push 和 PR 时用 Python 3.13 跑一遍。


| 路径 | 作用 |
| --- | --- |
| `cx` | 启动脚本：`./cx`、`cx setup`、`cx discuss`、`cx review`、`cx --yes` |
| `setup_wizard.py` | 交互式配置与刷课向导 |
| `main.py` | CLI 入口、章节任务队列、任务中心编排 |
| `api/base.py` | 超星核心：登录与章节任务点 |
| `api/task_center.py` | 任务中心客户端：分组、任务点、视频与文档上报 |
| `api/discussion.py` | 讨论区：帖子列表、板块解析、挑帖回复 |
| `api/scan.py` | 开始前扫描 |
| `api/review.py` | AI 文本留痕（`cx review`） |
| `api/answer.py` | 题库（含大模型 provider）与答题 |
| `api/ai_writer.py` | 作业与讨论的去 AI 味写作 |
| `tests/` | 离线单测 |
| `docs/` | 使用、排错与架构说明 |

## 仓库约定

- 欢迎提 issue 和 PR，一次改动尽量小而聚焦。
- 不要提交凭据、cookie、token 或个人信息，样例必须脱敏。

## 参考

- 上游项目：[Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)

## 许可证

GPL-3.0，见 [LICENSE](LICENSE)。仅供学习与个人使用；不要用在不是你自己的账号上。请自行遵守学校规定与平台服务条款。
