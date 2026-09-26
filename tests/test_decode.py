# -*- coding: utf-8 -*-
"""页面解析测试（使用内联的最小 HTML 片段，不访问网络）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import decode  # noqa: E402


class CourseListTestCase(unittest.TestCase):
    HTML = """
    <div class="course" id="c1" info="i" roleid="3">
      <input class="courseId" value="200">
      <input class="clazzId" value="300">
      <a href="/mycourse/studentcourse?courseid=200&clazzid=300&cpi=999&ut=s"></a>
      <span class="course-name" title="高等数学">高等数学</span>
      <p class="color3" title="张老师">张老师</p>
    </div>
    <div class="course" id="c2">
      <a class="not-open-tip">未开课</a>
    </div>
    """

    def test_parse(self):
        courses = decode.decode_course_list(self.HTML)
        self.assertEqual(len(courses), 1)
        c = courses[0]
        self.assertEqual(c["courseId"], "200")
        self.assertEqual(c["clazzId"], "300")
        self.assertEqual(c["cpi"], "999")
        self.assertEqual(c["title"], "高等数学")

    def test_skip_when_missing_ids(self):
        html = '<div class="course" id="x"><span class="course-name" title="缺ID"></span></div>'
        self.assertEqual(decode.decode_course_list(html), [])


class CoursePointTestCase(unittest.TestCase):
    HTML = """
    <div class="chapter_unit">
      <ul>
        <li><div id="cur101"><a class="clicktitle">第一节</a>
          <input class="knowledgeJobCount" value="2">
          <span class="bntHoverTips">已完成</span></div></li>
        <li><div id="cur102"><a class="clicktitle">第二节</a>
          <span class="bntHoverTips">解锁</span></div></li>
      </ul>
    </div>
    """

    def test_parse(self):
        result = decode.decode_course_point(self.HTML)
        self.assertTrue(result["hasLocked"])
        self.assertEqual(len(result["points"]), 2)
        self.assertEqual(result["points"][0]["id"], "101")
        self.assertTrue(result["points"][0]["has_finished"])
        self.assertTrue(result["points"][1]["need_unlock"])


class CourseCardTestCase(unittest.TestCase):
    def test_not_open(self):
        jobs, info = decode.decode_course_card("<html>章节未开放</html>")
        self.assertEqual(jobs, [])
        self.assertTrue(info["notOpen"])

    def test_marg_with_spaces_and_newlines(self):
        # raw_decode 必须能处理带空格/换行、以及字符串里含 "};" 的情况
        html = '''
        <script>
        var mArg = {
          "defaults": {"knowledgeid": 55, "cpi": "7", "reportUrl": "https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/7"},
          "attachments": [
            {"type": "video", "jobid": "j1", "mid": "m1", "objectId": "obj1", "otherInfo": "nodeId_1-x", "property": {"name": "视频A"}},
            {"type": "document", "jobid": "j2", "mid": "m2", "jtoken": "tk", "otherInfo": "nodeId_2-y", "isPassed": true},
            {"type": "workid", "jobid": "work-3", "mid": "m3", "enc": "e3", "property": {"title": "章节检测"}}
          ]
        };
        </script>
        '''
        jobs, info = decode.decode_course_card(html)
        self.assertEqual(info["knowledgeid"], 55)
        self.assertEqual(info["reportUrl"], "https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/7")
        types = [j["type"] for j in jobs]
        self.assertIn("video", types)
        self.assertIn("workid", types)
        self.assertNotIn("document", types)  # isPassed 的任务应被跳过

    def test_job_false_skipped(self):
        html = 'var mArg = {"defaults": {}, "attachments": [{"type": "video", "job": false, "mid": "m", "objectId": "o"}]};'
        jobs, _ = decode.decode_course_card(html)
        self.assertEqual(jobs, [])


class QuestionsTestCase(unittest.TestCase):
    def test_no_form_returns_empty(self):
        result = decode.decode_questions_info("<html><body>没有表单</body></html>")
        self.assertEqual(result["questions"], [])

    def test_parse_single_choice(self):
        html = """
        <form>
          <input name="workAnswerId" value="777">
          <div class="singleQuesId" data="1001">
            <div class="TiMu" data="0">
              <div class="Zy_TItle"><span>1.</span>下列哪个是水果？</div>
              <ul><li aria-label="A. 苹果">A</li><li aria-label="B. 石头">B</li></ul>
            </div>
          </div>
        </form>
        """
        result = decode.decode_questions_info(html)
        self.assertEqual(result["workAnswerId"], "777")
        self.assertEqual(len(result["questions"]), 1)
        q = result["questions"][0]
        self.assertEqual(q["id"], "1001")
        self.assertEqual(q["type"], "single")
        self.assertIn("苹果", q["options"])


if __name__ == "__main__":
    unittest.main()
