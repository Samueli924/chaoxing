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
        self.assertIsNone(result["jobProgress"])

    def test_job_progress(self):
        html = ('<h2 class="xs_head_name fl"><i class="catalog_points_yi fl"></i>\n\n'
                '已完成任务点: <span style="color:#00B368">70</span>/78\n<div class="catalog_jindu"></div></h2>')
        self.assertEqual(decode.decode_course_point(html)["jobProgress"], {"done": 70, "total": 78})
        self.assertEqual(decode.decode_course_point("已完成任务点：3 / 10")["jobProgress"], {"done": 3, "total": 10})


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
            {"type": "video", "job": true, "jobid": "j1", "mid": "m1", "objectId": "obj1", "otherInfo": "nodeId_1-x", "property": {"name": "视频A"}},
            {"type": "document", "jobid": "j2", "mid": "m2", "jtoken": "tk", "otherInfo": "nodeId_2-y", "isPassed": true},
            {"type": "workid", "job": true, "jobid": "work-3", "mid": "m3", "enc": "e3", "property": {"title": "章节检测"}}
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

    def test_only_job_true_attachments_are_pending(self):
        # 与线上数据一致：已完成的任务点没有 job 字段（章节检测连 isPassed 也没有），
        # 未设为任务点的参考 PDF / 插入图书同样没有 job 字段，都不应被当作待完成任务
        html = '''mArg = {"defaults": {"knowledgeid": 1}, "attachments": [
          {"type": "video", "job": true, "isPassed": false, "jobid": "v1", "mid": "m1", "objectId": "o1",
           "otherInfo": "nodeId_1-cpi_2-rt_d&courseId=3", "property": {"name": "第一讲.mp4", "module": "insertvideo"}},
          {"type": "workid", "jobid": "work-done", "mid": "m2", "enc": "e", "otherInfo": "nodeId_1",
           "property": {"module": "work", "title": "已提交的章节检测"}},
          {"type": "video", "isPassed": true, "jobid": "v0", "mid": "m0", "objectId": "o0", "property": {"module": "insertvideo"}},
          {"type": "document", "mid": "m3", "otherInfo": "nodeId_1", "property": {"module": "insertdoc", "name": "参考资料.pdf"}},
          {"otherInfo": "nodeId_1", "jtoken": "t", "mid": "m4", "property": {"module": "insertbook", "bookname": "急救手册"}}
        ]};'''
        jobs, _ = decode.decode_course_card(html)
        self.assertEqual([(j["type"], j["jobid"]) for j in jobs], [("video", "v1")])
        self.assertEqual(jobs[0]["otherinfo"], "nodeId_1-cpi_2-rt_d")

    def test_legacy_read_task_without_job(self):
        html = '''mArg = {"defaults": {}, "attachments": [
          {"type": "read", "jobid": "r1", "jtoken": "t", "property": {"read": false, "title": "阅读"}},
          {"type": "read", "property": {"read": false, "title": "没有 jobid 的阅读附件"}},
          {"type": "read", "jobid": "r2", "property": {"read": true, "title": "已读"}}
        ]};'''
        jobs, _ = decode.decode_course_card(html)
        self.assertEqual([j["jobid"] for j in jobs], ["r1"])

    def test_missing_tab_placeholder(self):
        # 请求的 num 超出标签页数量时，模板中的 mArg 不会被填充
        html = '<script>(function(){ mArg = ""; try{ mArg = $mArg; }catch(e){} uParse(".ans-cc",null,mArg);})();</script>'
        jobs, info = decode.decode_course_card(html)
        self.assertEqual(jobs, [])
        self.assertEqual(info, {"noCard": True})

    def test_empty_tab_is_not_placeholder(self):
        html = 'mArg = ""; try{ mArg = {"defaults": {"knowledgeid": 9}, "attachments": []}; }catch(e){}'
        jobs, info = decode.decode_course_card(html)
        self.assertEqual(jobs, [])
        self.assertNotIn("noCard", info)
        self.assertEqual(info["knowledgeid"], 9)


class FontRadicalTestCase(unittest.TestCase):
    def test_simplified_radicals_become_characters(self):
        # 加密字体解码后，部分简体字会落到 CJK 部首补充区的同形部首上（实测题目中出现 "胸⻣"、"⻝堂"）
        from api.cxsecret_font import KX_RADICALS_TAB
        self.assertEqual("胸⻣中下1/3处，来不及去⻝堂，⼈".translate(KX_RADICALS_TAB), "胸骨中下1/3处，来不及去食堂，人")


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
