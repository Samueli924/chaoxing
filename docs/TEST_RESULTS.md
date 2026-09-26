# 测试结果

日期：2026-09-26　运行环境：Linux，Python 3.10.20 与 3.13.12

## 1. 单元测试

`python -m unittest discover -s tests`

| 环境 | 结果 |
| --- | --- |
| Python 3.13 | **57 passed** |
| Python 3.10 | **57 passed** |

覆盖范围：

- `test_settings.py`：配置优先级（CLI > 环境变量 > 文件 > 默认）、占位符识别、数值裁剪、含 `%` 的密码、课程列表分隔。
- `test_answer_check.py`：选项匹配（字母/正文/多选/精确 vs 包含/不误删首字母）、判断题与多选可比较化、答案切分、题库名解析、大模型输出提取。
- `test_decode.py`：课程列表、章节（含解锁/已完成）、`mArg`（含空格换行与值内 `};`）、`job:false` 跳过、`isPassed` 跳过、无表单题目页、单选题解析。
- `test_job_processor.py`：未开放不无限重试、达上限停止、continue 跳过、错误重试、成功不重试、空章节成功、**未开放章节等待前序章节**、停止信号、ask 模式。
- `test_web.py`：首页与各 API、`/api/ping`、状态默认值、**缺少 CSRF 头被拒**、登录校验、未登录不能开始、访问口令校验、题库覆盖项白名单。

## 2. 对真实网站的核对（只读）

在容器内直接抓取线上页面/脚本进行核对（不涉及任何账号）：

- ✅ 登录页 `login.js?v=20260908`：AES 密钥、字段、返回分支均与代码对齐。
- ✅ 播放器 `videojs-ext.min.js?v=2026-0902-1207`：上报 URL 组成、enc 盐值与模板一致。
- ✅ `documentJob.js?v=2026-0227-1800`：文档完成接口已迁移到 `/mooc-ans/job/document`，代码已跟进。
- ✅ 各接口未登录行为：`courselistdata`/`knowledge/cards`/`studentstudyAjax` 返回 302 跳转登录页；`/ananas/job/*` 旧地址返回 403、`/mooc-ans/job/*` 返回"用户未登录"。
- ✅ 题库连通性：`TikuGo`(q.icodef.com) 免 token 返回正确答案；`TikuYanxi`(tk.enncy.cn) 返回体格式确认。

## 3. 端到端冒烟（本地，无需账号）

- ✅ `python main.py --help` 正常。
- ✅ `python main.py --web` 启动，`GET /` 返回 200，`/api/ping`、`/api/state` 正常，题库列表与默认值正确。
- ✅ `python main.py --check`（无凭据）干净报错并生成报告，不崩溃。
- ✅ `python main.py`（非交互、无凭据）给出明确的中文提示。

## 4. 待完成：真实账号实测

> **状态：待用户提供凭据后进行。**

本环境中**未检测到**学习通账号凭据（已检查 `CHAOXING_USERNAME` / `CHAOXING_PASSWORD` 等环境变量，均未设置），因此"用已完成课程做参照、对未完成课程实测"这一步尚未执行。

请在**云环境设置**中添加以下环境变量后新开会话，我将据此完成实测并把结果补充到本文件：

- `CHAOXING_USERNAME`：手机号
- `CHAOXING_PASSWORD`：密码
- （可选）`CHAOXING_COURSE_LIST`：指定用于实测的课程ID

计划的实测内容：

1. 登录并读取课程列表，核对账号可见课程。
2. 对**已手动完成**的课程运行 `--check`，核对"已完成"状态解析是否准确（`has_finished`、覆盖率、是否需要解锁）。
3. 对**未完成**的课程实际完成任务点（视频/文档/章节检测），记录每类任务的成功率与耗时。
4. 将脱敏后的运行日志与结果汇总写入本文件并推送。
