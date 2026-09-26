# 真实账号实测报告

- 测试时间：2026-09-26 14:40 → 2026-09-26 14:53
- 运行环境：Python 3.13.12，Linux
- 测试对象：学习通网页端（登录 passport2.chaoxing.com，课程 mooc1 / mooc2-ans）
- 模式：只读核对 + 实际完成课程
- 登录：成功（登录成功）
- 章节检测答题来源：GO题（网课小工具题库）（提交，覆盖率阈值 0%，最多重做 10 次）

## 1. 任务点解析是否准确（与服务端计数对比）

章节页顶部的"已完成任务点: 完成数/总数"由学习通服务端统计。逐章节读取任务卡片后，本工具判定为"待完成"的任务点数应当等于 总数 − 完成数。

| 课程 | 时点 | 服务端 完成/总数 | 服务端待完成 | 工具解析待完成 | 一致 | 章节已完成标记与卡片一致 |
| --- | --- | --- | --- | --- | --- | --- |
| 大学生安全教育 | 运行前 | 70/78 | 8 | 8 | ✅ | ✅ |
| 大学生安全教育 | 运行后 | 78/78 | 0 | 0 | ✅ | ✅ |

## 2. 实际完成课程

```
========== 运行结果 ==========
课程数: 1  章节数: 42  完成: 42  失败: 0  未开放跳过: 0
```

### 章节检测成绩（运行后逐个打开已批阅页面读取）

| 课程 | 章节检测数 | 已提交 | 满分(100) | 最低分 | 未提交 |
| --- | --- | --- | --- | --- | --- |
| 大学生安全教育 | 38 | 36 | 28 | 33.3 | 2 |

未满分的章节检测：

- 大学生安全教育 / 5.4 反恐安全：75.0 分（错 1 题）
- 大学生安全教育 / 6.1 重视防灾减灾，降低灾害损失：66.7 分（错 1 题）
- 大学生安全教育 / 6.2 地震逃生技术：66.7 分（错 1 题）
- 大学生安全教育 / 7.1 心理危机的识别：42.9 分（错 4 题）
- 大学生安全教育 / 7.3 抑郁障碍：66.6 分（错 1 题）
- 大学生安全教育 / 7.4 焦虑障碍：66.7 分（错 1 题）
- 大学生安全教育 / 7.6 进食障碍：66.7 分（错 1 题）
- 大学生安全教育 / 7.7 精神病性障碍：33.3 分（错 2 题）

## 3. 抓包记录（应用层，已脱敏）

共记录 459 个 HTTP 请求。完整记录保存在本机数据目录 `live_trace.jsonl`，不提交到仓库。

视频进度上报共 24 次，其中服务端返回 isPassed=true 4 次、false 20 次、其它 0 次。

| 接口 | 次数 | 状态码 |
| --- | --- | --- |
| `GET mooc1.chaoxing.com/mooc-ans/knowledge/cards` | 256 | 200×256 |
| `post q.icodef.com/wyn-nb` | 70 | 200×68, EXC×2 |
| `GET mooc1.chaoxing.com/mooc-ans/api/work` | 49 | 200×49 |
| `GET mooc1.chaoxing.com/mooc-ans/multimedia/log/a/{cpi}/{dtoken}` | 24 | 200×24 |
| `POST mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew` | 11 | 200×11 |
| `GET mooc1.chaoxing.com/mooc-ans/work/record-list` | 11 | 200×11 |
| `GET mooc1.chaoxing.com/mooc-ans/work/record-detail` | 11 | 200×11 |
| `GET mooc1.chaoxing.com/mooc-ans/work/retest` | 7 | 200×7 |
| `GET mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew` | 7 | 200×7 |
| `GET mooc1.chaoxing.com/ananas/status/{objectid}` | 4 | 200×4 |
| `GET mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse` | 3 | 200×3 |
| `GET passport2.chaoxing.com/mooc/accountManage` | 2 | 200×2 |
| `GET passport2.chaoxing.com/login` | 1 | 200×1 |
| `POST passport2.chaoxing.com/fanyalogin` | 1 | 200×1 |
| `POST mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata` | 1 | 200×1 |
| `GET mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction` | 1 | 200×1 |

每个接口的一条示例：

```
GET mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid=15***37&courseid=265547835&knowledgeid=1198005345&ut=s&cpi=56***59&v=2025-0424-1038-3&mooc2=1&num=0  -> 200 text/html 26964B
post q.icodef.com/wyn-nb [+表单]  -> 200 application/json 126B  {"code":-1,"data":"李恒雅正在睡觉觉🛏(未搜索到答案)","msg":"李恒雅正在睡觉觉🛏(未搜索到答案)"}
GET mooc1.chaoxing.com/mooc-ans/api/work?api=1&workId=37***54&jobid=work-37***54&originJobId=work-37***54&needRedirect=true&skipHeader=true&knowledgeid=1198005420&ktoken=32***d4&cpi=56***59&ut=s&clazzId=15***37&type=&enc=c0***b2&mooc2=1&courseid=265547835  -> 200 text/html 121645B  (跳转到 /mooc-ans/work/doHomeWorkNew)
GET mooc1.chaoxing.com/mooc-ans/multimedia/log/a/56***59/93***3d?clazzId=15***37&playingTime=470&duration=470&clipTime=0_470&objectId=dd***15&otherInfo=no***5f&courseId=265547835&jobid=175041553670135&userid=46***81&isdrag=4&view=pc&enc=06***03&rt=0.9&dtype=Video&_t=1790433724317&attDuration=470&attDurationEnc=ab***3e&courseEngineInfo=false  -> 200 application/json 61B  {"isPassed":false,"videoTimeLimit":false,"hasJobLimit":false}
POST mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew [+表单]  -> 200 text/html 371B  {"msg":"success!","stuStatus":4,"backUrl":"","url":"/mooc-ans/api/work?courseid=265547835&workId=a5***47&clazzId=15***37&knowledgeid=
GET mooc1.chaoxing.com/mooc-ans/work/record-list?courseId=265547835&classId=15***37&workId=54729146&workAnswerId=56***33&cpi=56***59&api=1&mooc2=1&ut=s  -> 200 text/html 12608B
GET mooc1.chaoxing.com/mooc-ans/work/record-detail?courseId=265547835&classId=15***37&workId=54729146&workAnswerId=56***33&cpi=56***59&times=0&ut=s&isdisplaytable=0&firstHeader=2&isWork=false&workSystem=0&api=1&archive=false&mooc2=1  -> 200 text/html 13427B  含: 本次成绩,我的答案
GET mooc1.chaoxing.com/mooc-ans/work/retest?courseId=265547835&classId=15***37&workId=54728861&workAnswerId=56***34&knowledgeid=1198005415&jobid=work-63***7e&originJobId=work-63***7e&enc=ae***95&cpi=56***59&mooc2=1&wMicroNodeId=0  -> 200 text/html 360B  {"msg":"sucess","url":"/mooc-ans/work/doHomeWorkNew?courseId=265547835&workAnswerId=56172034&workId=54728861&api=1&knowledgeid=1198005415&classId=15***37&oldW
GET mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew  -> 200 text/html 124864B
GET mooc1.chaoxing.com/ananas/status/dd***15?k=12***79&flag=normal&ro=0  -> 200 application/json 995B  {"length":328324616,"thumbnailsEnc":"0d***64","screenshot":"https://p2.cldisk.com/sv-w9/video/88/77/ab/dd***15
GET mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid=265547835&clazzid=15***37&cpi=56***59&ut=s  -> 200 text/html 105709B  含: 已完成任务点
GET passport2.chaoxing.com/mooc/accountManage  -> 200 text/html 29918B
GET passport2.chaoxing.com/login  -> 200 text/html 34108B
POST passport2.chaoxing.com/fanyalogin [+表单]  -> 200 text/html 52B  {"url":"https%3A%2F%2Fi.chaoxing.com","status":true}
POST mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata [+表单]  -> 200 text/html 6609B
GET mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction  -> 200 text/html 119171B
```
