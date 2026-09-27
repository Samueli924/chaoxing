# 本机整合与功能核验

日期：2026-09-27 UTC。基线：`ieduer/chaoxing` main `2089f7e5a51faab180c3ac5bb7220cd69037b737`。

## 本机恢复

唯一工作目录为 `/Users/ylsuen/chaoxing/chaoxing`。原目录的 origin 是 `Closty/chaoxing`，Git HEAD 为 `52f9fbe`，内容主要是旧签到工具，另有不完整的未跟踪文件。
逐文件与指定仓库比较：21 个本机 Python 文件是主线文件的严格前缀；旧 `cx.py` 属于另一项目。主线 54 个跟踪文件现已恢复；新功能在这一完整基线上实现。
原始文件全部保存在 `.git/chaoxing-recovery-20260927/`，包括未跟踪文件；旧 Git 历史仍保留在 `master` 分支，旧远端改名 `legacy-closty`。备份不提交到公开仓库。保留日期复核：2026-10-27。
回退本次新增功能可使用本次整合提交的 `git revert`；恢复整合前布局时必须先另存新工作，再依据旧 `master` 和上述原档备份恢复，不要对当前目录执行 reset/clean。

## 公开项目核查与功能对应

以下为 README、仓库元数据和本项目源代码的对照，不代表已在各个平台上逐个运行这些第三方项目。没有复制第三方实现；仍采用当前仓库的 GPL-3.0 主线。

| 参考仓库 | 核查结果与功能对应 |
| --- | --- |
| [pang-qin/chaoxing-toolkit](https://github.com/pang-qin/chaoxing-toolkit) | README 宣称 Vue 控制台、自建题库、AI；GitHub 未识别出授权。主线已有 Web/AI/自建题库客户端，本次独立补入 SQLite 题库管理。 |
| [fysh1010/chaoxing-script](https://github.com/fysh1010/chaoxing-script) | MIT，浏览器脚本及模型配置参考；主线保留 OpenAI 兼容接口、硅基流动，新增加轻量真实播放器控件。 |
| [ymylive/chaoxing-fanya](https://github.com/ymylive/chaoxing-fanya) | 已重定向 sweetcornna/chaoxing-fanya，GPL-3.0。Web/CLI、OCR、通知为 README 宣称；主线已有 Web/CLI 与通知，可选 OCR 未安装或实测。 |
| [Master-cai/chaoxingxuexi](https://github.com/Master-cai/chaoxingxuexi) | MIT，最后 push 2020-03-05。16 倍/秒过属于旧项目宣称，未证明当前可用；未纳入完成保证。 |
| [Hai-M-Feng/ChaoXing_AutoStudy](https://github.com/Hai-M-Feng/ChaoXing_AutoStudy) | 已重定向 HaiMFeng，Apache-2.0。主线已有章节调度和 1–2 倍配置，本次增加单次运行时限。 |
| [1seconder/ChaoXingAutoPlayVideo](https://github.com/1seconder/ChaoXingAutoPlayVideo) | GPL-3.0，最后 push 2018-10-30；README 明确只支持 H5，且不支持同页多个视频。不能据此保证当前无痕后台播放。 |
| [dsxksss/chaoxing_ft](https://github.com/dsxksss/chaoxing_ft) | Flutter 安卓/Windows 工具，GitHub 未识别授权；未移植原生客户端，现有 Web 控制台提供跨平台访问。 |
| [jet-isnt-haha/chaoxingXXT-Video-AutoPlayer](https://github.com/jet-isnt-haha/chaoxingXXT-Video-AutoPlayer) | MIT，Puppeteer 多账号配置参考；本次新增逐账号独立进程与独立数据目录，无需额外浏览器运行时。 |
| [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) | GPL-3.0，目标仓库的上游。保留协议请求、章节调度、任务类型、题库、答题反馈重做与只读自检。 |
| [guowang23333/CxKitty-](https://github.com/guowang23333/CxKitty-) | GPL-3.0，协议解析路线。目标主线已有同类执行架构，不并入另一套登录和全局会话。 |

## 本次新增

1. 本机题库 `/bank`：SQLite 持久化；按题目、题型、选项顺序精确匹配；JSON 批次导入整批校验、编辑、查询、分页、导出、删除。数据文件为 `CHAOXING_DATA_DIR/question_bank.sqlite3`，权限 0600。
2. `TikuLocal` 可单独使用，也可与 `TikuCustom,AI` 等顺序组合。网页新增回退顺序输入，切换题库时保存当前页面内的配置草稿；密钥不写浏览器存储，退出时清空。
3. `--max-duration` / `CHAOXING_MAX_DURATION` / 网页「运行时限」：0 不限，1–86400 秒；到时通过已有停止信号结束，已发出的请求不会被强制截断。总结区分手动停止和时限停止。
4. `start.command` 与 `scripts/local.py`：使用现有 Python 环境，只按字面读取指定 env 文件的 CHAOXING_* 变量，不 source、不执行命令、不输出凭据。默认数据保存在项目 `data/`。
5. `scripts/batch.py`：各账号独立子进程、Cookie/缓存/日志目录；串行执行，默认只读检查。实际执行要求 `--run`、明确课程列表及有限运行时间；默认禁用通知。
6. `resource/chaoxing-player.user.js`：可选的 HTML5 播放、静音与 1–2 倍控件；不自动忽略弹题，不屏蔽可见性事件，不绕过验证，不伪造播放结束。自动章节运行由主线排程器负责。该脚本只做语法检查，未安装到用户浏览器。

题库 HTTP 查询入口为 `POST /api/search`，需要 `X-Requested-With: chaoxing-web`；控制台配置访问口令时也需要原有 `X-Token`。它是本机控制台的受保护接口，不声称与所有第三方题库客户端即插即用。项目内直接选 `TikuLocal` 无需 HTTP 或密钥。

批次配置示例（仅别名及 env 文件位置，不在 JSON 中写凭据）：

```json
[{"name":"test-account","env_file":"account.env","courses":["<COURSE_ID>"],"max_duration":1800}]
```

```sh
python scripts/batch.py profiles.json           # 只读检查
python scripts/batch.py profiles.json --run     # 会产生学习记录，按该账号配置保存或提交答题
```

## 本次验证

- 现有 `/Users/ylsuen/.venv` 补齐缺失依赖；没有建立新环境或升级现有套件。下载包按 PyPI SHA-256 验证。
- `python -m unittest discover -s tests`：97 项通过。涵盖主线解析、排程、答题处理，以及新增题库事务/HTTP/鉴权、回退、配置、时限、env 字面读取与账号隔离。均为本机模拟测试；测试日志中的「提交成功」不代表真实提交。
- 所有 Python 文件语法解析通过；控制台、题库页、可选 userscript 的 JavaScript 语法检查通过；`git diff --check` 通过。
- Brave 本机测试：题目新增、列表回读、整页重新载入后持久化、返回控制台入口通过。测试只用合成题目，隔离数据随任务清理。
- Brave 已登录真实课程：目录、章节点页、任务卡片、视频组件的 HTTP 200 与数据结构得到确认，见 `BROWSER_VERIFICATION_20260927.json`。未点击播放，也未调用真实答题提交。

## 未完成的验收与限制

- 本次 shell 中 Python 对公开站点和超星均报 `OSError: [Errno 9] Bad file descriptor`；curl 和 Brave 通道可用。这是当前运行环境中的复现结果，尚未定位根因；不能据此宣称 Python 登录和学习任务端到端通过。
- 浏览器抓包事件缓冲曾截断，因此保存的是有限结构观察，不是完整 HAR。未保存 Cookie、授权标头、响应原文或个人记录。
- 多账号仅做配置/隔离测试，未使用多个真实账号运行；通知、付费模型、OCR、Android/Windows 打包和真实章节提交/完成回读未在本次执行。
- 16 倍秒过、无痕、反检测和“1.5–2 倍保证安全”没有当前实测证据，不提供这些承诺。平台实际倍速、暂停、弹题及验证要求仍需正常处理。
