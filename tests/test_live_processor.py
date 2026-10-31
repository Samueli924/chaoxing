import unittest
from unittest.mock import MagicMock, patch
from api.live import Live
from api.live_process import LiveProcessor
from api.task_runner import TaskStateHub


class TestLiveProcessor(unittest.TestCase):
    def tearDown(self):
        hub = TaskStateHub()
        hub.set_task_running(False)
        hub.set_web_mode(False)
        hub.clear_workers()

    def test_live_custom_session(self):
        mock_session = MagicMock()
        live = Live(
            attachment={"property": {"title": "测试直播", "streamName": "s1", "vdoid": "v1"}},
            defaults={"userid": "100", "clazzId": "200", "knowledgeid": "300"},
            course_id="c1",
            session=mock_session,
        )
        self.assertIs(live.session, mock_session)

        mock_resp = MagicMock()
        mock_resp.text = "@success"
        mock_session.get.return_value = mock_resp

        self.assertTrue(live.do_finish())
        mock_session.get.assert_called_once()

    def test_run_live_updates_hub_state(self):
        hub = TaskStateHub()
        hub.set_web_mode(True)
        hub.set_task_running(True)
        hub.set_global_speed(2.0)

        mock_live = MagicMock()
        mock_live.name = "形势与政策第二次直播"
        mock_live.get_status.return_value = {
            "temp": {"data": {"duration": 180}}
        }
        recorded_states = []

        def side_effect_finish():
            snap = hub.get_snapshot()
            if snap["workers"]:
                recorded_states.append(dict(snap["workers"][0]))
            return True

        mock_live.do_finish.side_effect = side_effect_finish

        with patch("time.sleep", return_value=None):
            success = LiveProcessor.run_live(mock_live, speed=2.0, course_title="形势与政策")
            self.assertTrue(success)

        self.assertEqual(len(recorded_states), 2)
        self.assertEqual(recorded_states[0]["position"], 1)
        self.assertEqual(recorded_states[0]["duration"], 2)
        self.assertEqual(recorded_states[0]["unit"], "分钟")
        self.assertEqual(recorded_states[1]["position"], 2)
        self.assertEqual(recorded_states[1]["duration"], 2)

        snapshot = hub.get_snapshot()
        self.assertEqual(len(snapshot["workers"]), 0)

    def test_skip_100_percent_completed_course(self):
        from api.decode import decode_course_point
        from main import is_course_finished, process_course

        html_100 = """
        <div>完成任务点: <span>15</span> / 15</div>
        <div class="chapter_unit">
            <ul>
                <li><div id="cur101"><a class="clicktitle">第一章 导论</a></div></li>
                <li><div id="cur102"><a class="clicktitle">1.1 视频</a><span class="bntHoverTips">已完成</span></div></li>
            </ul>
        </div>
        """
        point_list = decode_course_point(html_100)
        self.assertEqual(point_list["progress"], 100)
        self.assertTrue(point_list["is_finished"])
        self.assertTrue(is_course_finished({"title": "测试课"}, point_list))

        mock_cx = MagicMock()
        mock_cx.get_course_point.return_value = point_list
        with patch("main.JobProcessor") as mock_jp:
            process_course(
                mock_cx,
                {"courseId": "1", "clazzId": "2", "cpi": "3", "title": "满分课程"},
                {"speed": 1.0, "jobs": 1},
            )
            mock_jp.assert_not_called()

        html_partial = """
        <div>完成任务点: <span>199</span> / 200</div>
        <div class="chapter_unit">
            <ul>
                <li><div id="cur101"><a class="clicktitle">第一章</a></div></li>
            </ul>
        </div>
        """
        partial_list = decode_course_point(html_partial)
        self.assertEqual(partial_list["progress"], 99)
        self.assertFalse(partial_list["is_finished"])
        self.assertFalse(is_course_finished({"title": "未完课"}, partial_list))

        html_locked = """
        <div>完成任务点: <span>5</span> / 5</div>
        <div class="chapter_unit">
            <ul>
                <li><div id="cur101"><a class="clicktitle">1.1 已完成小节</a><span class="bntHoverTips">已完成</span></div></li>
                <li><div id="cur102"><a class="clicktitle">1.2 待解锁小节</a><span class="bntHoverTips">待解锁</span></div></li>
            </ul>
        </div>
        """
        locked_list = decode_course_point(html_locked)
        self.assertTrue(locked_list["hasLocked"])
        self.assertEqual(locked_list["progress"], 99)
        self.assertFalse(locked_list["is_finished"])
        self.assertFalse(is_course_finished({"title": "闯关课程"}, locked_list))

        empty_list = decode_course_point("<html><body>Error</body></html>")
        self.assertEqual(empty_list["progress"], 0)
        self.assertFalse(empty_list["is_finished"])
        self.assertFalse(is_course_finished({"title": "异常空白页"}, empty_list))
        self.assertFalse(is_course_finished({"title": "带过期进度缓存", "progress": 100}, locked_list))

        html_no_jobs = """
        <div class="chapter_unit">
            <ul>
                <li><div id="cur101"><a class="clicktitle">第一章 导论</a></div></li>
                <li><div id="cur102"><a class="clicktitle">1.1 阅读材料</a></div></li>
            </ul>
        </div>
        """
        no_jobs = decode_course_point(html_no_jobs)
        self.assertEqual(no_jobs["progress"], 100)
        self.assertTrue(no_jobs["is_finished"])

        html_has_jobs_unfinished = """
        <div class="chapter_unit">
            <ul>
                <li><div id="cur101"><a class="clicktitle">第一章</a></div></li>
                <li><div id="cur102"><a class="clicktitle">1.1 视频</a><input class="knowledgeJobCount" value="2"/></div></li>
            </ul>
        </div>
        """
        jobs_unfin = decode_course_point(html_has_jobs_unfinished)
        self.assertEqual(jobs_unfin["progress"], 0)
        self.assertFalse(jobs_unfin["is_finished"])


if __name__ == "__main__":
    unittest.main()
