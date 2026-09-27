# 使用教程

本教程面向会用命令行的用户，按"安装 → 只读检查 → 运行 → 排错"的顺序说明。文中"实测"指 2026-09-26
在 passport2.chaoxing.com 用测试账号（2 门课程）得到的结果，详见 [TEST_RESULTS.md](TEST_RESULTS.md) 第 4 节。

## 1. 准备

- Python 3.10 或更高版本（3.10 与 3.13 均已测试）。
- 能访问 `passport2.chaoxing.com`、`mooc1.chaoxing.com`、`mooc2-ans.chaoxing.com` 的网络。
- 学习通账号：手机号 + 密码。开启了双因子登录的账号改用 cookies 登录（见第 7 节）。

## 2. 安装

```bash
git clone --depth=1 https://github.com/ieduer/chaoxing
cd chaoxing
python -m venv .venv                     # 可选：使用虚拟环境
. .venv/bin/activate                     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

可选：`pip install "ddddocr>=1.5.6"` 启用验证码自动识别（依赖较大，不装也能用）。

## 3. 先做只读检查

在做任何会产生学习记录的操作之前，先确认登录和页面解析在你的账号上正常：

```bash
python main.py --check                   # 登录、课程列表、章节、任务卡片、视频信息接口
python scripts/live_verify.py            # 逐章节核对任务点解析与服务端计数
```

`live_verify.py` 会读取每门课章节页顶部的"已完成任务点: 完成数/总数"（服务端统计），再逐章节读取任务卡片，
检查工具判定的"待完成任务点数"是否等于 总数 − 完成数。两者一致说明解析可信；报告写入
`docs/LIVE_TEST_RESULTS.md`，逐请求记录写入数据目录的 `live_trace.jsonl`（不含密码，报告中的 ID 与令牌已脱敏）。

两个脚本都只发 GET 请求读取页面，不完成、不提交任何任务。

## 4. 网页控制台

```bash
python main.py --web                     # 浏览器打开 http://127.0.0.1:8765
```

1. **登录**：输入手机号和密码。密码只在内存中用于登录学习通，不会回传给页面。登录后状态保存在数据目录的 `cookies.txt`（权限 0600），下次可直接勾选"使用上次的登录"；点"退出登录"会删除这个文件。
2. **选择课程**：列表显示课程名、授课教师、课程ID与班级ID，同一课程的多个班级会分别列出。
3. **选择任务**：
   - 完成任务点：视频、音频、文档、阅读、章节检测等。
   - 增加章节学习次数：逐个访问章节，每个章节停留 30 秒。
4. **章节检测**（四选一）：

   | 选项 | 行为 |
   | --- | --- |
   | 跳过 | 不答题。需要提交章节检测才能解锁后续章节的课程会卡住。 |
   | 只保存不提交 | 搜到的答案填入并保存，不提交；任务点不会完成，可自行到学习通检查后提交。 |
   | 自动提交 | 题库能答出的题目比例达到 `cover_rate`（默认 90%）才提交，否则只保存。 |
   | 自动提交并重做 | 不论题库覆盖多少都提交，再按批改结果重做（最多 10 次），见第 6 节。 |

5. **更多设置**：
   - 视频倍速（1–2）：默认请求原生最高 2 倍，仅任务卡明确允许时使用；禁止或限制不明时自动用 1 倍。可手动选择更低倍速。
   - 并发默认 12，任务出错后自动按 12 → 8 → 4 → 2 → 1 降档；在途任务收尾后继续后续任务。错误与有限失败保留，不会因降档把失败记为完成。
   - 同时进行的章节数（默认 4）：实测 4 个视频并行播放均被服务端正常计入。
   - 遇到未开放章节：稍后重试，或直接跳过。
6. **开始 / 停止**：进度条、日志与结果汇总实时刷新；随时可以停止。再次运行时已完成的任务点会被跳过。

对外开放控制台（`--host 0.0.0.0`）时必须设置访问口令 `CHAOXING_WEB_TOKEN`，未设置时会自动生成并打印到日志。

## 5. 命令行

```bash
python main.py                                 # 交互：输入账号、选择课程
python main.py -u 手机号 -p 密码 -l 课程ID1,课程ID2
python main.py -c config.ini                   # 使用配置文件
python main.py --use-cookies                   # 使用数据目录中的 cookies.txt 登录
```

不指定课程且不在交互终端中运行时，会学习全部课程。常用参数见 `python main.py --help`。

### 配置文件与环境变量

把 `config_template.ini` 复制为 `config.ini`，通常只需填写 `username` 和 `password`，其余项都有默认值。
所有配置项也可以用环境变量提供，适合 Docker 或服务器：

| 环境变量 | 对应配置 |
| --- | --- |
| `CHAOXING_USERNAME` / `CHAOXING_PASSWORD` | `[common] username` / `password` |
| `CHAOXING_COURSE_LIST` | `[common] course_list` |
| `CHAOXING_SPEED` / `CHAOXING_JOBS` / `CHAOXING_NOTOPEN_ACTION` | `[common]` 中的同名项 |
| `CHAOXING_WORK_MAX_RETRIES` | `[common] work_max_retries` |
| `CHAOXING_TIKU_<配置项>` | `[tiku]` 中的任意项，例如 `CHAOXING_TIKU_PROVIDER=TikuGo` |
| `CHAOXING_NOTIFICATION_<配置项>` | `[notification]` 中的任意项 |
| `CHAOXING_DATA_DIR` | cookies / 答案缓存 / 日志的存放目录（默认当前目录） |

优先级：命令行参数 > 环境变量 > 配置文件 > 默认值。

## 6. 章节检测（题库）

在 `[tiku]` 中设置 `provider`，多个题库用英文逗号分隔，按顺序回退：

| provider | 说明 | 需要的配置 |
| --- | --- | --- |
| `TikuGo` | GO题，免费 | 无（可选 `go_authorization`） |
| `TikuYanxi` / `TikuLike` | 言溪 / LIKE 知识库 | `tokens` |
| `AI` | 任意兼容 OpenAI 接口的大模型 | `endpoint`、`key`、`model` |
| `SiliconFlow` | 硅基流动 | `siliconflow_key`（可选 `siliconflow_model`） |
| `TikuAdapter` | tikuAdapter 自建题库 | `url` |
| `TikuCustom` | 自建题库服务器（见下） | `custom_url`（可选 `custom_key`） |
| `TikuManual` | 在命令行中手动输入 | 无 |

使用大模型的示例：

```ini
[tiku]
provider = AI
endpoint = https://api.deepseek.com/v1
key = 你的 API Key
model = deepseek-chat
submit = true
```

启动时会先发一个测试请求检查大模型是否可用（`check_llm_connection = false` 可关闭）。

`TikuCustom` 的接口约定：`POST custom_url`，请求体
`{"question": 题目, "type": "0"~"7", "options": [选项正文], "key": 密钥}`；成功时返回
`{"code": 1 或 -1, "data": {"answer": 答案}}` 或 `{"code": 1, "answer": 答案}`。多选答案可用 `#` 分隔（如 `A#C`），
约定的题型代码为 0 单选、1 多选、2 填空、3 判断、4 简答、5 名词解释、6 论述、7 计算；本工具把名词解释、论述、计算题按简答题（4）发送。

### 提交与重做

- `submit = false`（默认）：只保存搜到的答案。
- `submit = true`：题库覆盖率达到 `cover_rate` 时提交；课程需要提交章节检测才能解锁后续章节时，覆盖率不足也会提交。
- 提交后，工具读取作答记录（`/work/record-list`、`/work/record-detail`）中每道题的对错标记。有答错且还有重做机会时，
  通过网页"重做"按钮使用的 `/work/retest` 重新作答：答对的题沿用原答案；答错的题如果页面公布了正确答案就直接使用，
  否则换一个还没试过的答案（大模型题库会带上错误反馈重新作答）。最多重做 `work_max_retries` 次（默认 3）。
- 测验不允许重做（`/work/retest` 返回失败）时保留当前成绩，不再尝试。

## 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| 登录提示手机号或密码错误 | 在浏览器登录 passport2.chaoxing.com 确认账号密码（首尾空格会被自动去掉）。 |
| 提示需要先修改密码 | 学习通要求改密（密码过于简单或过期），在浏览器登录修改后再试。 |
| 提示开启了双因子登录 | 在浏览器登录后，把请求头中的 `Cookie` 内容保存到数据目录的 `cookies.txt`，再用 `--use-cookies`。 |
| 视频进度上报返回 403 / 需要验证码 | 安装 `ddddocr` 自动识别，或在浏览器中手动完成一次验证。 |
| 章节未开放 | 可能是前一章节的章节检测未提交，或章节尚未开放 / 已关闭；按 `notopen_action` 重试或跳过。 |
| 想看每个请求的细节 | 加 `-v` 运行；日志在数据目录的 `chaoxing.log`（默认 DEBUG，`-v` 时为 TRACE，含原始页面）。 |

## 8. 实测中观察到的网页行为（2026-09）

- **任务点标记**：任务卡片数据中只有未完成的任务点带 `job: true`，完成后该字段被去掉；未设为任务点的参考 PDF、
  插入图书也没有该字段。工具据此只处理 `job: true` 的附件。
- **标签页数量**：章节的任务卡片按 `num=0,1,2...` 分页，不存在的标签页返回未填充的模板（`mArg = $mArg`），
  工具遇到即停止，每章约 3 个请求。
- **视频完成**：进度上报接口为任务卡片中 `defaults.reportUrl` 加 `/{dtoken}`，服务端返回
  `{"isPassed": ..., "videoTimeLimit": ..., "hasJobLimit": ...}`；部分视频在播放到一定比例后即返回 `isPassed: true`。
- **章节检测**：提交接口 `POST /mooc-ans/work/addStudentWorkNew` 返回 `{"msg": "success!", "stuStatus": 4, ...}`；
  作答记录"第1次"对应 `times=0`；已批阅页面每题带 `marking_dui`（对）/ `marking_cuo`（错）/ `marking_bandui`（部分正确）标记。
- **加密字体**：题目文字使用加密字体，解码后个别字会落到 CJK 部首补充区（如"胸⻣""⻝堂"），工具已映射回常用汉字。

## 9. 数据与隐私

- 数据目录（`CHAOXING_DATA_DIR`，默认当前目录）保存 `cookies.txt`（等同登录凭据）、`cache.json`（答案缓存）与 `chaoxing.log`。
- 网页控制台默认只监听 `127.0.0.1`；写操作要求自定义请求头以防跨站请求；已保存的题库密钥不会回传给页面。
- `scripts/live_verify.py` 的抓包记录只保存在本机数据目录，报告中的用户ID、学校ID、班级ID、令牌均已脱敏。
