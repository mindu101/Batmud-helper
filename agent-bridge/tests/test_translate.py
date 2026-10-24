#!/usr/bin/env python3
"""Unit tests for translate_window (mocked DeepSeek API, fake clock)."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pylib'))
import translate_window as tw


class FakeTime(object):
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def advance(self, s):
        self.now += s


class FakeClient(object):
    def __init__(self, batches):
        self.batches = list(batches)

    def status(self):
        return {'latest_seq': 0}

    def read(self, after, wait_ms=0):
        return self.batches.pop(0) if self.batches else {'events': []}


def ev(seq, text):
    return {'seq': seq, 'time_ms': 0, 'text': text, 'raw': text}


class TestHelpers(unittest.TestCase):
    def test_status_line_local_translation(self):
        line = 'hp: 586 (586) [] sp: 294 (294) [] ep: 212 (212) [] cash: 16661 [+1113] exp: 19227 []\n'
        self.assertEqual(tw.format_status_zh(line),
                         '血 586 | 法 294 | 精 212 | 钱 16661 | 经验 19227')
        self.assertIsNone(tw.format_status_zh('some other line'))

    def test_parse_translations(self):
        self.assertEqual(tw.parse_translations('["一","二"]', 2), ['一', '二'])
        self.assertIsNone(tw.parse_translations('["一"]', 2))       # 长度不符
        self.assertIsNone(tw.parse_translations('不是json', 1))      # 非法 JSON
        self.assertEqual(tw.parse_translations('[42]', 1), ['42'])   # 非字符串转 str

    def test_call_api_builds_prompt_and_parses(self):
        seen = {}

        def fake_post(url, payload, key):
            seen['url'], seen['key'] = url, key
            seen['payload'] = payload
            return {'choices': [{'message': {'content': '["甲","乙"]'}}]}

        result = tw.call_api(['a', 'b'], 'sk-test', post=fake_post)
        self.assertEqual(result, ['甲', '乙'])
        self.assertTrue(seen['url'].startswith('https://api.deepseek.com'))
        self.assertEqual(seen['key'], 'sk-test')
        self.assertEqual(seen['payload']['messages'][0]['role'], 'system')
        self.assertEqual(json.loads(seen['payload']['messages'][1]['content']), ['a', 'b'])

    def test_user_content_glossary_tail(self):
        base = tw.build_user_content(['a line'])
        self.assertEqual(json.loads(base), ['a line'])   # 无术语表时是纯 JSON
        with_g = tw.build_user_content(['a line'], {'portcullis': '铁闸门'})
        self.assertTrue(with_g.startswith(base))         # 行在前,术语表在尾
        self.assertIn('"portcullis": "铁闸门"', with_g.split('术语表:')[1])

    def test_is_junk(self):
        self.assertTrue(tw.is_junk('NoMapSupport'))
        self.assertTrue(tw.is_junk('  ~~*~  '))
        self.assertTrue(tw.is_junk('123 456'))
        self.assertFalse(tw.is_junk('You are in a room.'))

    def test_usage_tracker_persists_and_summarizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'usage.json'
            u = tw.UsageTracker(p)
            u.add({'prompt_tokens': 100, 'completion_tokens': 20,
                   'prompt_cache_hit_tokens': 60})
            u.add({'prompt_tokens': 50, 'completion_tokens': 10})
            u2 = tw.UsageTracker(p)                      # 重启后加载累计值
            self.assertEqual(u2.totals['calls'], 2)
            self.assertEqual(u2.totals['prompt_cache_hit_tokens'], 60)
            self.assertIn('2 次调用', u2.summary())
            self.assertIn('40%', u2.summary())           # 60/150 命中率

    def test_call_api_rejects_bad_reply(self):
        def fake_post(url, payload, key):
            return {'choices': [{'message': {'content': '随心所欲的回答'}}]}
        with self.assertRaises(ValueError):
            tw.call_api(['a'], 'k', post=fake_post)

    def test_cache_fifo(self):
        c = tw.TranslationCache(max_entries=2)
        c.put('a', '1'); c.put('b', '2'); c.put('c', '3')
        self.assertNotIn('a', c)
        self.assertEqual(c['c'], '3')


class TestRunLoop(unittest.TestCase):
    def setUp(self):
        self._real_time = tw.time
        self.ft = FakeTime()
        tw.time = self.ft

    def tearDown(self):
        tw.time = self._real_time

    def make_stop(self, after):
        n = [0]

        def stop():
            n[0] += 1
            return n[0] >= after
        return stop

    def fake_post_ok(self, calls):
        def post(url, payload, key):
            raw = payload['messages'][1]['content']
            calls.append(json.loads(raw.split('\n术语表:')[0]))  # 剥掉术语表尾
            n = len(calls[-1])
            return {'choices': [{'message': {'content': json.dumps(['译%d' % i for i in range(n)])}}],
                    'usage': {'prompt_tokens': 9}}
        return post

    def usage_sandbox(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tw.UsageTracker(Path(tmp.name) / 'u.json')

    def test_batching_cache_and_status_line(self):
        calls = []
        empty = {'events': []}
        batch1 = {'events': [ev(1, 'Iron portcullis (closed) leads south.\n'),
                             ev(2, 'You feel hungry.\n'),
                             ev(3, 'NoMapSupport'),
                             ev(4, 'hp: 100 (100) [] sp: 50 (50) [] ep: 9 (9) [] cash: 1 [] exp: 2 []\n')]}
        batch2 = {'events': [ev(5, 'Iron portcullis (closed) leads south.\n')]}  # 重复行
        client = FakeClient([batch1] + [empty] * 8 + [batch2] + [empty] * 3)
        out = io.StringIO()
        usage = self.usage_sandbox()
        tw.run(client, out, 'k', post=self.fake_post_ok(calls), usage=usage,
               sleep=self.ft.advance, stop=self.make_stop(14))
        text = out.getvalue()
        # 状态行走本地格式化,不进 API 批
        self.assertIn('血 100 | 法 50 | 精 9', text)
        self.assertNotIn('hp: 100', text)
        # 杂线(NoMapSupport)不显示也不翻译
        self.assertNotIn('NoMapSupport', text)
        # 首批两行一次请求;第二批的重复行命中缓存,不产生第二次请求
        self.assertEqual(calls, [['Iron portcullis (closed) leads south.',
                                  'You feel hungry.']])
        self.assertIn('中│ 译0', text)
        self.assertIn('中│ 译1', text)
        self.assertEqual(text.count('EN│ Iron portcullis'), 2)
        # 用量被统计(1 次成功调用)
        self.assertEqual(usage.totals['calls'], 1)

    def test_api_failure_shows_original_and_backs_off(self):
        calls = []

        def post(url, payload, key):
            calls.append(1)
            raise OSError('connection refused')

        batches = [{'events': [ev(1, 'A line.\n')]}]
        client = FakeClient(batches + [{'events': []}] * 8)
        out = io.StringIO()
        tw.run(client, out, 'k', post=post, usage=self.usage_sandbox(),
               sleep=self.ft.advance, stop=self.make_stop(12))
        text = out.getvalue()
        self.assertIn('翻译暂缺', text)
        self.assertIn('A line.', text)   # 原文始终可见
        self.assertIn('退避', text)
        self.assertEqual(len(calls), 1)  # 退避期间不重试同一批


if __name__ == '__main__':
    unittest.main(verbosity=2)
