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

## 4. 真实账号实测 + 抓包验证

> **状态：实测脚本已就绪，需在"新会话"中运行。**

环境变量在**会话启动时**被读入，之后再添加不会进入已运行的会话。因此即便已在环境设置里配置了
`CHAOXING_USERNAME` / `CHAOXING_PASSWORD`，也需要**新开一个会话**（同一环境、同一分支）才能读到，
再运行实测脚本。

已提供实测 + 抓包脚本 [`scripts/live_verify.py`](../scripts/live_verify.py)，一条命令完成：

```bash
python scripts/live_verify.py            # 自动挑选参照课程与目标课程
# 或手动指定
python scripts/live_verify.py --ref 已完成课程ID --target 未完成课程ID
```

脚本会做四件事，对应你的要求：

1. **登录**，并在应用层**抓取每一个 HTTP 请求/响应**（方法、URL、参数、状态码、耗时、响应摘要），
   脱敏后写入 `docs/live_trace.log`——HTTPS 传输层抓包只能得到密文，应用层抓包才能证明与网站的真实交互。
2. **参照课程（已手动完成）**：核对 `has_finished`、待办任务数、是否需要解锁，验证完成状态解析的准确性。
3. **目标课程（未完成）**：实际完成一个任务点，然后**重新拉取页面复核该任务点已从待办中消失**
   （即 `isPassed` 翻转），以此证明**效度**——不是"跑完不报错"，而是"网站侧确实记为完成"。
4. 生成脱敏报告 `docs/LIVE_TEST_RESULTS.md` 与抓包明细 `docs/live_trace.log`。

抓包与脱敏机制已在本会话用真实请求验证可用（登录页 200、课程接口响应均被正确记录，
且请求体中的密码等敏感值不会出现在抓包中）。

**运行环境有效性说明**：本工具通过代理访问公网，`passport2 / mooc1 / mooc2-ans` 等学习通域名均可达
（登录页 `GET` 返回 200，未登录接口返回 302/403），具备真实登录与刷课的网络条件。
