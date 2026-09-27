# 代码盘点与修复清单

本次基于对 [passport2.chaoxing.com](https://passport2.chaoxing.com/) 及 mooc1 / mooc2-ans 各页面**真实运行行为**的分析，对仓库做了一次系统性排查与重构。以下为发现的问题与对应修复。

## 一、与最新网页不一致 / 会导致功能失效的问题

| # | 位置 | 问题 | 修复 |
| --- | --- | --- | --- |
| 1 | `base.py` `SessionManager` | 每次 `SessionManager()` 都新建一个 `requests.Session`（`__init__` 在单例上反复执行），连接池与 cookie 无法复用，`request` 被反复 `functools.partial` 包裹导致超时叠加 | 改为真正的进程内单例会话，统一超时、连接池与重试 |
| 2 | `base.py` 登录 | 登录只判断 `status`，未处理**弱密码强制改密**(`weakpwd`)、**双因子登录**(`containTwoFactorLogin`)、`msg2`/`mes` 等最新字段；`t` 传布尔而网页传字符串 `"true"`；缺少 `independentNameId` | 按线上 `login.js` 的 `loginByPhoneAndPwdSubmit` 对齐字段与所有返回分支，给出明确的中文错误 |
| 3 | `base.py` cookie 校验 | 用关键字判断是否登录页，易误判 | 改为 `allow_redirects=False` 判断是否 302 跳转到 passport2 |
| 4 | `base.py` 视频上报 | 上报 URL 硬编码为 `/mooc-ans/multimedia/log/a/{cpi}/{dtoken}`，未使用服务端下发的 `reportUrl`；参数顺序/`courseEngineInfo` 与播放器不一致；`isPassed` 缺字段时 `resp.json()["isPassed"]` 会抛异常 | 优先使用 `defaults.reportUrl`，参数顺序与 `videojs-ext.min.js` 对齐，补 `courseEngineInfo`，安全解析 JSON |
| 5 | `base.py` 视频结尾 | 视频播放到结尾若服务器一直不判定完成，`while not passed` **死循环** | 增加结尾重报上限（`MAX_END_REPORTS`），超过则失败重试 |
| 6 | `base.py` 文档任务 | 完成文档用旧的 `/ananas/job/document`，线上 `documentJob.js` 已改为 `/mooc-ans/job/document` 且新增 `checkMicroTopic`/`courseEngineInfo` | 优先 `/mooc-ans/job/...`，旧地址兜底，补齐新参数；阅读任务同理 |
| 7 | `base.py` 章节检测重做 | 重做逻辑把「获取题目」也算进重试轮次，`attempt` 被消耗；错误反馈 `set_work_feedback` 是**全局字段**，多线程互相污染；老师未公布答案时也会重做白白耗次数；随机答案会被当作"已知答案"提交 | 重写：反馈改为**线程局部**、按题目 ID 记忆已知正确答案、仅在能改进时才重做、老师未公布答案则不重做、只提交搜到的答案 |
| 8 | `decode.py` `mArg` 解析 | 用 `html.replace(" ", "")` 去空格再正则，会破坏选项/标题里的空格，且遇到值中含 `};` 会截断 | 改用 `json.JSONDecoder().raw_decode` 从 `mArg={` 处精确解析 |
| 9 | `decode.py` 任务卡片 | 无 `job` 字段的视频/文档任务被误当作"特殊任务"丢弃；音频任务无法与视频区分；缺少 `reportUrl`、`workid/schoolid/worktype` 等线上答题必需字段 | 按 `type` 分派、识别音频、补齐 work 任务全部字段 |
| 10 | `decode.py` 题目页 | 页面无 `<form>` 时 `soup.find("form").find_all(...)` 抛 `AttributeError` | 无表单时返回空题目列表，交由上层跳过 |
| 11 | `captcha.py` | `submitCaptcha` 判断 `status_code == 302`，但 requests 默认跟随跳转，永远拿不到 302，验证码**永远验证失败**；且 `verify=False` 关闭了 TLS 校验 | `allow_redirects=False` 判断跳转，移除 `verify=False` |
| 12 | `answer.py` 匹配 | 单选/多选答案匹配用"去掉首字母 + 子序列"，会把 `Python` 误删成 `ython`、`北京` 误配到 `北京大学` | 新增 `answer_check.match_choice`：字母答案 > 正文精确 > 包含 > 相似度 > 子序列，多选按字母排序 |

## 二、健壮性 / 安全问题

| # | 位置 | 问题 | 修复 |
| --- | --- | --- | --- |
| 13 | `answer.py` `Tiku.query` | 引用了不存在的 `cache_dao` 变量，一旦启用反馈路径直接崩溃 | 重写 `query`/`query_all`，统一缓存与线程局部反馈 |
| 14 | `answer.py` `CacheDAO` | 每次读写都读整份 JSON 文件，多线程下反复读写、易损坏 | 改为进程内共享内存副本 + 原子写 + 锁 |
| 15 | `answer.py` `TikuLike` | `likeapi_search`/`likeapi_retry` 从 ini 读出的是字符串，`"false"` 被当成 `True`；`retry=false` 时循环一次都不执行 | 统一布尔解析，修正重试次数逻辑 |
| 16 | `answer.py` 多处 | `requests` 请求 `verify=False` 关闭 TLS、且无超时，可能永久挂起 | 移除 `verify=False`，全部加超时 |
| 17 | `answer.py` `SiliconFlow` | 与 `AI` 大量重复代码，且各自的思考模型处理不一致 | `SiliconFlow` 继承 `AI`，仅覆盖配置项 |
| 18 | `answer.py` 缺失键 | `self._conf['submit']` 等直接按键取值，配置缺项即 `KeyError` | 全部改为带默认值读取，占位符（`xxx`）视为未填写 |
| 19 | `notification.py` | Telegram 用 HTML 解析但未转义，报错信息含 `<` 会发送失败；`globals()[provider]` 可被任意类名命中；密钥 URL 明文写日志 | 转义消息、白名单查表、日志脱敏、统一超时 |
| 20 | `cookies.py` | cookie 文件明文且可被其他用户读；无法兼容浏览器复制的 cookie | 权限 `0600`、兼容 `Cookie:` 前缀与换行、去重 |
| 21 | `logger.py` | 控制台恒为 TRACE 级别，`--verbose` 从未生效；日志文件无保留策略；密码等可能入日志 | 控制台默认 INFO、`--verbose` 才 DEBUG，日志文件加 `retention` |
| 22 | `main.py` 调度 | `JobProcessor` 的 worker 异常直接 `raise` 使线程静默退出，`task_queue.join()` **永久阻塞**；未开放章节固定间隔盲重试；`notopen_action=ask` 从未实现 | 重写为 `scheduler.py`：异常安全、按前序章节依赖延后、退避重试、实现 ask、支持停止与结果汇总 |
| 23 | `cxsecret_font.py` | 字体映射表路径基于当前工作目录，换目录运行即报错 | 改为基于模块/打包目录的 `resource_path` |
| 24 | `font_decoder.py` | base64 提取正则脆弱，字体 CSS 写法变化即失效 | 放宽正则，解析失败时安全降级为不解密 |

## 三、部署易用性问题

| # | 问题 | 修复 |
| --- | --- | --- |
| 25 | 配置模板 138 行、必填项淹没在大量可选项中 | 精简为"只需手机号+密码"，其余默认并加注释；占位符自动视为空 |
| 26 | 只能 Python 3.13 运行（`requires-python>=3.13`） | 降到 **3.10+**，在 3.10 与 3.13 均通过测试 |
| 27 | `requirements.txt` 含未使用的 `celery`/`flask`/`chardet`/`argparse`，`app.py` 为无用的 celery 脚手架 | 精简依赖、删除 `app.py`，`ddddocr` 改为可选 extra |
| 28 | 不会用命令行的用户无法使用 | 新增**网页控制台**（`--web`），双击 exe 即自动打开浏览器 |
| 29 | 无法应对网站结构变动的排查 | 新增只读自检 `--check` |
| 30 | 数据文件（cookies/缓存/日志）散落工作目录，Docker 无法持久化 | 统一 `CHAOXING_DATA_DIR`，Docker 挂载 `/data` |

## 四、线上核对结论（截至 2026-09）

以下为对真实网页/接口的核对结果，作为上述修复的依据：

- 登录：`passport2.chaoxing.com/fanyalogin`，AES 密钥仍为 `u2oh6Vu^HWe4_AES`（CBC/PKCS7，key=iv），`t="true"` 时对手机号与密码加密 —— 与线上 `login.js?v=20260908` 一致。
- 课程列表：`mooc2-ans/visit/courselistdata`，未登录返回 302 跳转登录页。
- 章节：`mooc2-ans/mycourse/studentcourse`；任务卡片：`mooc1/mooc-ans/knowledge/cards`。
- 视频进度：`reportUrl + "/" + dtoken`，enc 盐值 `d_yHJ!$pdA~5`，模板 `[{clazzId}][{userid}][{jobid}][{objectId}][{playTime*1000}][盐][{duration*1000}][0_{duration}]` —— 与 `videojs-ext.min.js?v=2026-0902-1207` 一致。
- 文档完成：`mooc1/mooc-ans/job/document`（旧 `/ananas/job/document` 已 403）—— 与 `documentJob.js?v=2026-0227-1800` 一致。
- 章节检测：`mooc1/mooc-ans/api/work` 取题、`work/addStudentWorkNew` 提交、`work/record-list` + `work/record-detail` 核对成绩。
- 题库连通性：`TikuGo`(q.icodef.com) 免 token 可用；`TikuYanxi`(tk.enncy.cn) 接口格式确认。
