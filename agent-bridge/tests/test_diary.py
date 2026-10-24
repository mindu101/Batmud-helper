#!/usr/bin/env python3
"""Unit tests for diary.py with temp files and injected dependencies."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import diary as dy


def ts(date='2026-10-24', h=12):
    import time
    return int(time.mktime(time.strptime('%s %d:00:00' % (date, h), '%Y-%m-%d %H:%M:%S')) * 1000)


class TestDiary(unittest.TestCase):
    def test_commands_of_day_filters_and_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'command-log.jsonl'
            p.write_text('\n'.join(json.dumps(r) for r in [
                {'time_ms': ts(h=1), 'command': 'look'},
                {'time_ms': ts(h=2), 'command': 'help robot'},
                {'time_ms': ts('2026-10-23', 12), 'command': 'old'},
                {'time_ms': ts(h=23), 'command': 'n'},
            ]) + '\n', encoding='utf-8')
            lo, hi = dy.day_bounds('2026-10-24')
            cmds = dy.commands_of_day(p, lo, hi)
            self.assertEqual([c for _, c in cmds], ['look', 'help robot', 'n'])

    def test_words_of_day(self):
        text = ('# 单词本\n\n## 2026-10-24\n\n### portcullis\n内容\n\n### dryad\n内容\n\n'
                '## 2026-10-22\n\n### old word\n')
        self.assertEqual(dy.words_of_day(text, '2026-10-24'), ['portcullis', 'dryad'])
        self.assertEqual(dy.words_of_day(text, '2026-10-25'), [])

    def test_build_section_content(self):
        s = dy.build_section('2026-10-24',
                             cmds=[(1, 'look'), (2, 'look')],
                             words=['portcullis'], rooms=3, edges=2,
                             commits=['abc123 did x'], exp=(19000, 19227))
        self.assertIn('## 2026-10-24', s)
        self.assertIn('+227', s)
        self.assertIn('发出命令 2 条(去重 1 种)', s)
        self.assertIn('look', s)
        self.assertIn('portcullis', s)
        self.assertIn('3 个房间、2 条', s)
        self.assertIn('abc123 did x', s)

    def test_write_diary_idempotent_and_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'diary.md'
            first = dy.build_section('2026-10-24', [], [], 0, 0, [], None)
            self.assertEqual(dy.write_diary(first, '2026-10-24', p), 'created')
            older = dy.build_section('2026-10-22', [], [], 0, 0, [], None)
            # 唯一已有的 10-24 比它新,所以 10-22 追加到末尾,仍保持倒序
            self.assertEqual(dy.write_diary(older, '2026-10-22', p), 'appended')
            text = p.read_text(encoding='utf-8')
            self.assertLess(text.index('## 2026-10-24'), text.index('## 2026-10-22'))
            # 重跑同一天:覆盖而不是重复
            again = dy.build_section('2026-10-24', [(1, 'look')], ['w'], 1, 1, [], None)
            self.assertEqual(dy.write_diary(again, '2026-10-24', p), 'replaced')
            text = p.read_text(encoding='utf-8')
            self.assertEqual(text.count('## 2026-10-24'), 1)
            self.assertIn('look', text)

    def test_git_commits_injected(self):
        def fake_runner(cmd, cwd=None, capture_output=True, text=True, timeout=None):
            class R:
                stdout = 'aaa1 first\nbbb2 second\n'
            return R()
        commits = dy.git_commits('2026-10-24', runner=fake_runner)
        self.assertEqual(commits, ['aaa1 first', 'bbb2 second'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
