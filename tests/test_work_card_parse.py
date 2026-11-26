# -*- coding: utf-8 -*-
"""作业卡片解析的回归测试: job 字段缺失的 workid 卡片不再被丢弃."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.decode import _process_attachment_cards, _process_work_task  # noqa: E402


# 真实抓取到的"练习1"作业卡片结构：没有 job 字段，作业ID藏在 property._jobid
REAL_WORK_CARD_WITHOUT_JOB = {
    "begins": 0,
    "otherInfo": "nodeId_1041511324-cpi_427736946",
    "ends": 0,
    "property": {
        "module": "work",
        "worktype": "workA",
        "mid": "180350769341757573903942",
        "title": "练习1",
        "workid": "5046cd0550394be09cd7d6fa60683c35",
        "_jobid": "work-5046cd0550394be09cd7d6fa60683c35",
    },
    "mid": "180350769341757573903942",
    "enc": "7fb117291cf60a00adc176a214b21597",
    "type": "workid",
    "aid": "2073846339",
    # 注意：没有 "job" 字段
}


class WorkCardParseTest(unittest.TestCase):
    def test_work_card_without_job_field_kept(self):
        """job=None 的 workid 卡片必须被解析成作业任务，不能被丢弃."""
        jobs = _process_attachment_cards([dict(REAL_WORK_CARD_WITHOUT_JOB)])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["type"], "workid")

    def test_jobid_extracted_from_property(self):
        """作业ID应从 property._jobid 提取，带 work- 前缀."""
        job = _process_work_task(dict(REAL_WORK_CARD_WITHOUT_JOB))
        self.assertEqual(job["jobid"], "work-5046cd0550394be09cd7d6fa60683c35")
        self.assertEqual(job["mid"], "180350769341757573903942")
        self.assertEqual(job["enc"], "7fb117291cf60a00adc176a214b21597")

    def test_jobid_from_card_takes_priority(self):
        """card 顶层的 jobid 应优先于 property 中的值."""
        card = dict(REAL_WORK_CARD_WITHOUT_JOB)
        card["jobid"] = "work-top-level"
        job = _process_work_task(card)
        self.assertEqual(job["jobid"], "work-top-level")

    def test_passed_card_still_skipped(self):
        """已通过的作业卡片仍应被跳过."""
        card = dict(REAL_WORK_CARD_WITHOUT_JOB)
        card["isPassed"] = True
        jobs = _process_attachment_cards([card])
        self.assertEqual(len(jobs), 0)

    def test_read_card_without_job_still_works(self):
        """原有的无 job 阅读卡片处理不受影响."""
        read_card = {
            "type": "read",
            "property": {"read": False, "title": "阅读材料", "id": "123"},
            "jobid": "read-123",
        }
        jobs = _process_attachment_cards([read_card])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["type"], "read")


if __name__ == "__main__":
    unittest.main()
