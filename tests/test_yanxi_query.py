# -*- coding: utf-8 -*-
"""Issue #632 的回归测试：言溪题库查询失败时的健壮性。

覆盖以下场景：
- 服务端返回 code=0 且 data/answer 为 None 或 message 缺失时不抛异常，安全返回 None
- 网络层异常（超时/连接错误）不抛出，返回 None（走随机兜底+覆盖率判定）
- 服务端非 200 / 非 JSON 响应不崩
- 正常命中仍返回 answer，且同步更新剩余次数 _times
- 成功但 answer 为空/None 视为未命中，返回 None
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from api.answer import TikuYanxi  # noqa: E402


def _make_tiku():
    """构造一个已初始化的言溪题库实例，避免真实读配置文件."""
    tiku = TikuYanxi.__new__(TikuYanxi)
    # 初始化最小必需状态
    tiku._name = '言溪题库'
    tiku._api = 'https://tk.enncy.cn/query'
    tiku._token = 'TEST_TOKEN'
    tiku._token_index = 0
    tiku._times = 100
    tiku._timeout = 30
    tiku._query_retry_times = 2  # 调小, 加快测试
    tiku._retry_backoff = 0.0    # 测试不等待
    tiku._conf = {'tokens': 'TEST_TOKEN', 'tokens2': 'x'}
    return tiku


def _fake_response(status_code=200, json_data=None, text='{}'):
    resp = unittest.mock.MagicMock(spec=requests.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
        resp.text = json.dumps(json_data, ensure_ascii=False)
    else:
        resp.text = text
    return resp


class YanxiQueryFailureTest(unittest.TestCase):
    def test_query_failure_data_none_no_exception(self):
        """code=0 且 data 为 None 时，不应抛 KeyError/TypeError，返回 None."""
        tiku = _make_tiku()
        resp = _fake_response(json_data={'code': 0, 'data': None, 'message': '请求失败'})
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertIsNone(result)

    def test_query_failure_answer_none_no_exception(self):
        """code=0 且 data.answer 为 None 时，'次数不足' 判断不应抛异常."""
        tiku = _make_tiku()
        resp = _fake_response(json_data={'code': 0, 'data': {'answer': None, 'times': 90}, 'message': '请求失败'})
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertIsNone(result)

    def test_query_missing_message_no_exception(self):
        """响应缺失 message 字段时不抛 KeyError."""
        tiku = _make_tiku()
        resp = _fake_response(json_data={'code': 0, 'data': {'answer': '', 'times': 1}})
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertIsNone(result)

    def test_network_exception_returns_none(self):
        """网络层异常（超时/连接错误）不应抛出，返回 None 走随机兜底."""
        tiku = _make_tiku()
        with patch.object(
            requests, 'get',
            side_effect=requests.exceptions.ConnectTimeout('timeout')
        ):
            result = tiku._query({'title': '某题'})
        self.assertIsNone(result)

    def test_non_200_returns_none(self):
        """非 200 响应返回 None."""
        tiku = _make_tiku()
        resp = _fake_response(status_code=500, text='Internal Server Error')
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        """响应体不是有效 JSON 时返回 None."""
        tiku = _make_tiku()
        resp = _fake_response(status_code=200, json_data=None, text='<html>bad</html>')
        # 让 resp.json() 抛 ValueError
        resp.json.side_effect = ValueError('no json')
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertIsNone(result)

    def test_success_returns_answer_and_updates_times(self):
        """正常命中返回 answer，且 _times 被服务端 times 更新."""
        tiku = _make_tiku()
        resp = _fake_response(json_data={
            'code': 1,
            'data': {'answer': '正确', 'times': 88},
            'message': 'ok',
        })
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertEqual(result, '正确')
        self.assertEqual(tiku._times, 88)

    def test_success_empty_answer_returns_none(self):
        """成功但 answer 为空/None 视为未命中，返回 None."""
        tiku = _make_tiku()
        resp = _fake_response(json_data={
            'code': 1,
            'data': {'answer': '', 'times': 50},
            'message': '未找到',
        })
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertIsNone(result)

    def test_success_times_missing_keeps_previous(self):
        """成功但响应缺 times 时，_times 保留原值."""
        tiku = _make_tiku()
        tiku._times = 77
        resp = _fake_response(json_data={
            'code': 1,
            'data': {'answer': 'B'},
            'message': 'ok',
        })
        with patch.object(requests, 'get', return_value=resp):
            result = tiku._query({'title': '某题'})
        self.assertEqual(result, 'B')
        self.assertEqual(tiku._times, 77)

    def test_insufficient_count_switches_token(self):
        """answer 含'次数不足'时切换 token 并重查（load_token 被调用）."""
        tiku = _make_tiku()
        tiku._conf = {'tokens': 'T1,T2'}
        tiku._token_index = 0
        first = _fake_response(json_data={
            'code': 0,
            'data': {'answer': '次数不足', 'times': 0},
            'message': 'ok',
        })
        second = _fake_response(json_data={
            'code': 1,
            'data': {'answer': 'A', 'times': 10},
            'message': 'ok',
        })
        with patch.object(requests, 'get', side_effect=[first, second]):
            result = tiku._query({'title': '某题'})
        self.assertEqual(result, 'A')
        self.assertEqual(tiku._token_index, 1)


if __name__ == '__main__':
    unittest.main()
