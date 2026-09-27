# 真实账号实测报告

- 测试时间：2026-09-26 15:12 → 2026-09-26 15:15
- 运行环境：Python 3.13.12，Linux
- 测试对象：学习通网页端（登录 passport2.chaoxing.com，课程 mooc1 / mooc2-ans）
- 模式：只读核对
- 登录：成功（登录成功）

## 1. 任务点解析是否准确（与服务端计数对比）

章节页顶部的"已完成任务点: 完成数/总数"由学习通服务端统计。逐章节读取任务卡片后，本工具判定为"待完成"的任务点数应当等于 总数 − 完成数。

| 课程 | 时点 | 服务端 完成/总数 | 服务端待完成 | 工具解析待完成 | 一致 | 章节已完成标记与卡片一致 |
| --- | --- | --- | --- | --- | --- | --- |
| 国家安全教育 | 只读核对 | 1/118 | 117 | 117 | ✅ | ✅ |
| 大学生安全教育 | 只读核对 | 78/78 | 0 | 0 | ✅ | ✅ |

## 2. 抓包记录（应用层，已脱敏）

共记录 325 个 HTTP 请求。完整记录保存在本机数据目录 `live_trace.jsonl`，不提交到仓库。

| 接口 | 次数 | 状态码 |
| --- | --- | --- |
| `GET mooc1.chaoxing.com/mooc-ans/knowledge/cards` | 317 | 200×317 |
| `GET passport2.chaoxing.com/mooc/accountManage` | 2 | 200×2 |
| `GET mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse` | 2 | 200×2 |
| `GET passport2.chaoxing.com/login` | 1 | 200×1 |
| `POST passport2.chaoxing.com/fanyalogin` | 1 | 200×1 |
| `POST mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata` | 1 | 200×1 |
| `GET mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction` | 1 | 200×1 |

每个接口的一条示例：

```
GET mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid=15***78&courseid=266882195&knowledgeid=1240709658&ut=s&cpi=56***59&v=2025-0424-1038-3&mooc2=1&num=0  -> 200 text/html 27019B
GET passport2.chaoxing.com/mooc/accountManage  -> 200 text/html 29918B
GET mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid=266882195&clazzid=15***78&cpi=56***59&ut=s  -> 200 text/html 189274B  含: 已完成任务点
GET passport2.chaoxing.com/login  -> 200 text/html 34108B
POST passport2.chaoxing.com/fanyalogin [+表单]  -> 200 text/html 52B  {"url":"https%3A%2F%2Fi.chaoxing.com","status":true}
POST mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata [+表单]  -> 200 text/html 6609B
GET mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction  -> 200 text/html 119171B
```
