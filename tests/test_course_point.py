import unittest

from api.decode import decode_course_point

_NESTED_HTML = """
<div>已完成任务点: <span>2</span> / 4</div>
<div class="chapter_unit">
    <ul>
        <li>
            <div class="chapter_item" id="cur201"><a class="clicktitle">2.1 任务一</a></div>
            <ul>
                <li><div class="chapter_item" id="cur202"><a class="clicktitle">2.1.1 课前</a><span class="bntHoverTips">已完成</span></div></li>
                <li><div class="chapter_item" id="cur203"><a class="clicktitle">2.1.2 课中</a><span class="bntHoverTips">已完成</span></div></li>
            </ul>
        </li>
        <li>
            <div class="chapter_item" id="cur204"><a class="clicktitle">2.2 任务二</a></div>
            <ul>
                <li><div class="chapter_item" id="cur205"><a class="clicktitle">2.2.1 课前</a><span class="bntHoverTips">1个待完成任务点</span></div></li>
                <li><div class="chapter_item" id="cur206"><a class="clicktitle">2.2.2 课中</a><span class="bntHoverTips">1个待完成任务点</span></div></li>
            </ul>
        </li>
    </ul>
</div>
"""


class TestNestedChapterPoint(unittest.TestCase):
    def test_parent_nodes_are_not_tasks(self):
        result = decode_course_point(_NESTED_HTML)
        ids = [p["id"] for p in result["points"]]
        self.assertEqual(ids, ["202", "203", "205", "206"])

    def test_nested_progress_kept(self):
        result = decode_course_point(_NESTED_HTML)
        self.assertEqual(result["progress"], 50)
        self.assertFalse(result["is_finished"])

    def test_leaf_only_unit_still_parsed(self):
        html = """
        <div class="chapter_unit">
            <ul>
                <li><div class="chapter_item" id="cur301"><a class="clicktitle">1.1 引言</a></div></li>
            </ul>
        </div>
        """
        result = decode_course_point(html)
        self.assertEqual([p["id"] for p in result["points"]], ["301"])


if __name__ == "__main__":
    unittest.main()
