# -*- coding: utf-8 -*-
"""读取章节任务点：按标签页依次请求，遇到不存在的标签页即停止（不访问网络）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.base import Chaoxing  # noqa: E402

TAB_VIDEO = ('mArg = ""; try{ mArg = {"defaults": {"knowledgeid": 11, "cpi": 5, '
             '"reportUrl": "https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/5"}, "attachments": ['
             '{"type": "video", "job": true, "jobid": "v1", "mid": "m", "objectId": "o", "otherInfo": "nodeId_11"}]}; }catch(e){}')
TAB_WORK = ('mArg = ""; try{ mArg = {"defaults": {"knowledgeid": 11}, "attachments": ['
            '{"type": "workid", "job": true, "jobid": "work-1", "mid": "m2", "enc": "e", "otherInfo": "nodeId_11"}]}; }catch(e){}')
TAB_MISSING = 'mArg = ""; try{ mArg = $mArg; }catch(e){}'


class _Resp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200
        self.url = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"
        self.history = []
        self.headers = {}


class _NoopRateLimiter:
    def limit_rate(self, *args, **kwargs):
        return None


class GetJobListTestCase(unittest.TestCase):
    def _chaoxing(self, pages):
        cx = Chaoxing()
        cx.rate_limiter = _NoopRateLimiter()
        requested = []

        def fake_get(url, **kwargs):
            num = kwargs["params"]["num"]
            requested.append(num)
            return _Resp(pages[num] if num < len(pages) else TAB_MISSING)

        cx._get_with_relogin = fake_get
        cx.study_emptypage = lambda course, point: None
        return cx, requested

    COURSE = {"clazzId": "1", "courseId": "2", "cpi": "5", "title": "课程"}
    POINT = {"id": "11", "title": "1.1 导论"}

    def test_stops_after_last_tab(self):
        cx, requested = self._chaoxing([TAB_VIDEO, TAB_WORK])
        jobs, info = cx.get_job_list(self.COURSE, self.POINT)
        self.assertEqual([j["jobid"] for j in jobs], ["v1", "work-1"])
        self.assertEqual(requested, [0, 1, 2])  # 第 3 个标签页不存在，之后不再请求
        self.assertEqual(info["knowledgeid"], 11)
        self.assertNotIn("noCard", info)

    def test_falls_back_to_all_tabs_when_page_unrecognised(self):
        # 页面格式变化、无法识别标签页是否存在时，仍按旧逻辑尝试全部标签页
        cx, requested = self._chaoxing([TAB_VIDEO] + ["<html>unknown</html>"] * 6)
        jobs, _ = cx.get_job_list(self.COURSE, self.POINT)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(requested, list(range(7)))

    def test_not_open(self):
        cx, requested = self._chaoxing(["<html>章节未开放</html>"])
        jobs, info = cx.get_job_list(self.COURSE, self.POINT)
        self.assertEqual(jobs, [])
        self.assertTrue(info["notOpen"])
        self.assertEqual(requested, [0])


if __name__ == "__main__":
    unittest.main()
