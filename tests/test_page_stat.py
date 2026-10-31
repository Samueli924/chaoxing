import unittest

from api.decode import decode_course_point


class TestPageStatAligned(unittest.TestCase):
    def test_page_stat_exposed(self):
        html = """
        <div>已完成任务点: <span>263</span> / 265</div>
        <div class="chapter_unit">
            <ul>
                <li><div id="cur101"><a class="clicktitle">1.1</a><span class="bntHoverTips">已完成</span></div></li>
            </ul>
        </div>
        """
        result = decode_course_point(html)
        self.assertEqual(result["page_finished"], 263)
        self.assertEqual(result["page_total"], 265)

    def test_page_stat_absent_is_zero(self):
        result = decode_course_point('<div class="chapter_unit"><ul></ul></div>')
        self.assertEqual(result["page_finished"], 0)
        self.assertEqual(result["page_total"], 0)


if __name__ == "__main__":
    unittest.main()
