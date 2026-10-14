# -*- coding: utf-8 -*-
"""自动签到的回归测试: 活动筛选、签到流程与配置读取."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.process import pending_sign_activities, sign_in_course, sign_succeeded  # noqa: E402

COURSE = {"courseId": "267844236", "clazzId": "156654129", "cpi": "405606059", "title": "舌尖上的植物学"}

ACTIVITIES = [
    {"activeType": 2, "status": 1, "activeId": 1001, "name": "签到"},
    # activeType 在不同接口版本里也可能是字符串
    {"activeType": "sign", "status": 1, "activeId": 1002, "name": "二次签到"},
    # 已结束(status=2)的签到
    {"activeType": 2, "status": 2, "activeId": 1003, "name": "上周的签到"},
    # 非签到活动(投票)
    {"activeType": 4, "status": 1, "activeId": 1004, "name": "投票"},
    # 缺少 activeId
    {"activeType": 2, "status": 1, "name": "坏数据"},
]


class PendingSignActivitiesTest(unittest.TestCase):
    def test_only_active_signs(self):
        """只保留进行中的签到活动, 忽略其他类型与已结束的活动."""
        pending = pending_sign_activities(ACTIVITIES)
        self.assertEqual([a["activeId"] for a in pending], [1001, 1002])

    def test_empty_and_none(self):
        self.assertEqual(pending_sign_activities([]), [])
        self.assertEqual(pending_sign_activities(None), [])


class SignSucceededTest(unittest.TestCase):
    def test_success_text(self):
        """成功文本大小写与结尾标点不敏感, 已签到同样视为完成."""
        for text in ("success", "Success", "success.", "签到成功！", "您已经签到", "已签到"):
            self.assertTrue(sign_succeeded(text), text)

    def test_failure_text(self):
        """距离限制、非本班学生、空返回和否定表述都不能算成功."""
        for text in ("您当前位置距离签到地点有 500米", "签到失败", "非本班学生",
                     "unsuccessful", "not success", "签到未成功", "", None):
            self.assertFalse(sign_succeeded(text), text)


class SignInCourseTest(unittest.TestCase):
    def test_signs_each_pending_activity(self):
        chaoxing = mock.MagicMock()
        chaoxing.get_activity_list.return_value = ACTIVITIES
        chaoxing.sign_in_normal.return_value = "success"
        self.assertEqual(sign_in_course(chaoxing, COURSE), 2)
        called_ids = [c.args[1] for c in chaoxing.pre_sign.call_args_list]
        self.assertEqual(called_ids, [1001, 1002])

    def test_no_activity_returns_zero(self):
        chaoxing = mock.MagicMock()
        chaoxing.get_activity_list.return_value = [ACTIVITIES[3]]
        self.assertEqual(sign_in_course(chaoxing, COURSE), 0)
        chaoxing.sign_in_normal.assert_not_called()

    def test_activity_list_failure_does_not_raise(self):
        """活动列表拿不到时不能把整个刷课流程带崩."""
        chaoxing = mock.MagicMock()
        chaoxing.get_activity_list.side_effect = RuntimeError("boom")
        self.assertEqual(sign_in_course(chaoxing, COURSE), 0)

    def test_sign_failure_continues(self):
        """单个签到抛异常时, 后续活动仍要继续处理."""
        chaoxing = mock.MagicMock()
        chaoxing.get_activity_list.return_value = ACTIVITIES
        chaoxing.sign_in_normal.side_effect = ["success", RuntimeError("boom")]
        self.assertEqual(sign_in_course(chaoxing, COURSE), 1)

    def test_failed_response_text_not_counted(self):
        """pre_sign/sign_in_normal 对非 200 不抛异常, 返回失败文案时不能计入成功."""
        chaoxing = mock.MagicMock()
        chaoxing.get_activity_list.return_value = ACTIVITIES
        chaoxing.sign_in_normal.side_effect = ["success", "您当前位置距离签到地点有 500米"]
        self.assertEqual(sign_in_course(chaoxing, COURSE), 1)


class AutoSignConfigTest(unittest.TestCase):
    def _load(self, body):
        fd, path = tempfile.mkstemp(suffix=".ini")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf8") as f:
                f.write(body)
            import main
            return main.load_config_from_file(path)[0]
        finally:
            os.remove(path)

    def test_true(self):
        common = self._load("[common]\nauto_sign = true\n")
        self.assertIs(common["auto_sign"], True)

    def test_absent_defaults_to_false(self):
        """老配置文件没有这一项时不能默认开启签到."""
        common = self._load("[common]\nspeed = 1\n")
        self.assertIs(common["auto_sign"], False)


if __name__ == "__main__":
    unittest.main()
