# -*- coding: utf-8 -*-
"""强制刷音视频时长模式 (force_video_time) 的单元测试."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.decode import _process_attachment_cards  # noqa: E402


class ForceVideoTimeDecodeTest(unittest.TestCase):
    def _sample_cards(self):
        return [
            # 已完成的任务点视频 (isPassed=True, job=True)
            {
                "type": "video",
                "isPassed": True,
                "job": True,
                "jobid": "job-video-passed",
                "otherInfo": "nodeId_1-cpi_2",
                "playTime": 120000,
                "attDuration": 300,
                "property": {
                    "mid": "mid-1",
                    "objectid": "obj-video-1",
                    "name": "passed_video.mp4",
                    "jobid": "job-video-passed",
                },
            },
            # 已完成且 job=None 的章节视频 (或非任务点视频)
            {
                "type": "video",
                "isPassed": True,
                "job": None,
                "otherInfo": "nodeId_1-cpi_2",
                "property": {
                    "mid": "mid-2",
                    "objectId": "obj-video-2",
                    "name": "nontask_video.mp4",
                    "_jobid": "job-video-nontask",
                },
            },
            # 已完成的章节测验 (应在两种模式下均被跳过)
            {
                "type": "workid",
                "isPassed": True,
                "job": True,
                "otherInfo": "nodeId_1-cpi_2",
                "enc": "enc-1",
                "property": {
                    "workid": "work-1",
                    "jobid": "job-work-1",
                },
            },
        ]

    def test_default_skips_passed_and_nontask_videos(self):
        job_list = _process_attachment_cards(self._sample_cards(), force_video_time=False)
        self.assertEqual(len(job_list), 0)

    def test_force_video_time_keeps_passed_and_nontask_videos_only(self):
        job_list = _process_attachment_cards(self._sample_cards(), force_video_time=True)
        self.assertEqual(len(job_list), 2)
        self.assertEqual(job_list[0]["type"], "video")
        self.assertEqual(job_list[0]["objectid"], "obj-video-1")
        self.assertEqual(job_list[1]["type"], "video")
        self.assertEqual(job_list[1]["objectid"], "obj-video-2")
        self.assertEqual(job_list[1]["jobid"], "job-video-nontask")


if __name__ == "__main__":
    unittest.main()
