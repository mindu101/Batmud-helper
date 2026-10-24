#!/usr/bin/env python3
"""Unit tests for batbridge.state (game state tracking)."""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pylib'))
from batbridge.state import GameState, parse_status


def line(seq, t, text, kind='text'):
    return {'seq_start': seq, 'seq_end': seq, 'time_ms': t, 'text': text,
            'kind': kind, 'repeats': 1}


REAL_STATUS = ('hp: 586 (586) [] sp: 294 (294) [] ep: 212 (212) [] '
               'cash: 16661 [+1113] exp: 19227 []\n')
# 2026-10-24 真实捕获:Dortlewall 北门楼
GATEHOUSE = [
    line(39, 1000, 'Northern gatehouse.', 'room_title?'),
    line(40, 1000, 'You are in the northern gatehouse of Dortlewall.', 'text'),
    line(42, 1001, 'Iron portcullis (closed) leads south.', 'text'),
    line(43, 1002, 'Obvious exit is: north.', 'exits'),
]


class TestState(unittest.TestCase):
    def test_parse_status_real_line(self):
        st = parse_status(REAL_STATUS)
        self.assertEqual(st, {'hp': 586, 'hp_max': 586, 'sp': 294, 'sp_max': 294,
                              'ep': 212, 'ep_max': 212, 'cash': 16661, 'exp': 19227})
        self.assertIsNone(parse_status('some other line'))

    def test_track_status_and_room(self):
        s = GameState()
        self.assertTrue(s.update_from_lines(GATEHOUSE))
        self.assertEqual(s.room, 'Northern gatehouse.')
        self.assertIsNone(s.hp)          # 没有状态行就不编造
        self.assertEqual(s.seq, 43)
        # 状态行到来 -> 更新且房间保持
        self.assertTrue(s.update_from_lines([line(50, 2000, REAL_STATUS)]))
        self.assertEqual(s.hp, 586)
        self.assertEqual(s.exp, 19227)
        self.assertEqual(s.room, 'Northern gatehouse.')
        # 重复同样的内容 -> 无变化
        self.assertFalse(s.update_from_lines([line(51, 2100, REAL_STATUS)]))

    def test_hp_drop_detected(self):
        s = GameState()
        s.update_from_lines([line(1, 1000, REAL_STATUS)])
        hurt = REAL_STATUS.replace('hp: 586', 'hp: 120')
        self.assertTrue(s.update_from_lines([line(2, 2000, hurt)]))
        self.assertEqual((s.hp, s.hp_max), (120, 586))

    def test_save_load_roundtrip_and_summary(self):
        s = GameState()
        s.update_from_lines(GATEHOUSE)
        s.update_from_lines([line(50, 2000, REAL_STATUS)])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'state.json'
            s.save(p)
            s2 = GameState.load(p)
            self.assertEqual(s2.as_dict(), s.as_dict())
        self.assertIn('血 586/586', s.summary_zh())
        self.assertIn('位置[Northern gatehouse.]', s.summary_zh())

    def test_unknown_room_leaves_previous(self):
        s = GameState()
        s.update_from_lines(GATEHOUSE)
        # 只有 exits 没有 title:不猜房间,保持原值
        self.assertFalse(s.update_from_lines(
            [line(60, 3000, 'Obvious exits are: north, south.', 'exits')]))
        self.assertEqual(s.room, 'Northern gatehouse.')


if __name__ == '__main__':
    unittest.main(verbosity=2)
