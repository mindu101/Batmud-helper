#!/usr/bin/env python3
"""Unit tests for mapper.py (rooms, edges, pathfinding) on real captures."""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mapper


def line(seq, t, text, kind='text'):
    return {'seq_start': seq, 'seq_end': seq, 'time_ms': t, 'text': text,
            'kind': kind, 'repeats': 1}


# 2026-10-24 真实捕获:Dortlewall 北门楼的房间块(seq 39-47)
GATEHOUSE = [
    line(39, 1000, 'Northern gatehouse.', 'room_title?'),
    line(40, 1000, 'You are in the northern gatehouse of Dortlewall.', 'text'),
    line(41, 1001, 'Outside, above you is a still, clear night sky.', 'text'),
    line(42, 1001, 'Iron portcullis (closed) leads south.', 'text'),
    line(43, 1002, 'Obvious exit is: north.', 'exits'),
]
STREET = [
    line(50, 3000, 'Street of Dortlewall.', 'room_title?'),
    line(51, 3000, 'A busy street.', 'text'),
    line(52, 3001, 'Obvious exits are: north, south and east.', 'exits'),
]


class TestBasics(unittest.TestCase):
    def test_parse_exits_variants(self):
        self.assertEqual(mapper.parse_exits('Obvious exit is: north.'), ['north'])
        self.assertEqual(mapper.parse_exits('Obvious exits are: north, south and east.'),
                         ['north', 'south', 'east'])
        self.assertEqual(mapper.parse_exits('Obvious exits are: ne and sw.'.lower()),
                         ['northeast', 'southwest'])

    def test_move_alias_canon(self):
        self.assertEqual(mapper.canon_dir('n'), 'north')
        self.assertEqual(mapper.canon_dir('NORTH'), 'north')
        self.assertEqual(mapper.canon_dir('sw'), 'southwest')
        self.assertEqual(mapper.canon_dir('dance'), '')


class TestTracker(unittest.TestCase):
    def make(self):
        st = mapper.MapState()
        tr = mapper.RoomTracker(st)
        return st, tr

    def test_real_gatehouse_room_recorded(self):
        st, tr = self.make()
        rc, ec = tr.on_lines(GATEHOUSE)
        self.assertTrue(rc)
        self.assertFalse(ec)
        rid = mapper.room_id('Northern gatehouse.')
        self.assertEqual(st.rooms[rid]['exits'], ['north'])
        self.assertEqual(st.rooms[rid]['visits'], 1)
        self.assertEqual(tr.current, rid)

    def test_edge_learned_from_move_then_new_room(self):
        st, tr = self.make()
        tr.on_lines(GATEHOUSE)
        tr.on_move(2500, 'north')            # 经桥发送 north
        rc, ec = tr.on_lines(STREET)         # 0.5 秒后出现新房间
        self.assertTrue(ec)
        self.assertEqual(st.edges[mapper.room_id('Northern gatehouse.')]['north'],
                         mapper.room_id('Street of Dortlewall.'))
        # 回头走:street -> south -> gatehouse
        tr.on_move(4000, 'south')
        back = [line(60, 4300, 'Northern gatehouse.', 'room_title?'),
                line(61, 4300, 'You are in the northern gatehouse of Dortlewall.', 'text'),
                line(62, 4301, 'Obvious exit is: north.', 'exits')]
        tr.on_lines(back)
        self.assertEqual(st.rooms[mapper.room_id('Northern gatehouse.')]['visits'], 2)
        self.assertEqual(st.edges[mapper.room_id('Street of dortlewall.')]['south'],
                         mapper.room_id('Northern gatehouse.'))

    def test_no_move_no_edge(self):
        st, tr = self.make()
        tr.on_lines(GATEHOUSE)
        ec = tr.on_lines(STREET)[1]          # 新房间但没有移动命令(传送/登录)
        self.assertFalse(ec)
        self.assertEqual(st.edges, {})

    def test_stale_move_ignored(self):
        st, tr = self.make()
        tr.on_lines(GATEHOUSE)
        tr.on_move(1000, 'north')            # 太早,距新房间 >5s
        ec = tr.on_lines([dict(l, time_ms=30000) for l in STREET])[1]
        self.assertFalse(ec)

    def test_title_detection_survives_batch_split(self):
        # 2026-10-24 实测故障复刻:标题与出口行被切进两次读取,
        # 单批启发式把紧邻出口的"木门"行误判为标题。
        # 修复:跨批滚动窗口 + 段落开头找标题。
        st, tr = self.make()
        batch1 = [  # 第一次读:标题+描述
            line(39, 1000, 'Northern gatehouse.', 'room_title?'),
            line(40, 1000, 'You are in the northern gatehouse. There is a portal here,', 'text'),
        ]
        batch2 = [  # 第二次读:描述尾+门+出口
            line(43, 1001, 'closed and locked, so the only way out is south.', 'text'),
            line(44, 1001, 'Sturdy wooden gate (closed) leads north.', 'text'),
            line(45, 1002, 'Obvious exit is: south.', 'exits'),
        ]
        tr.on_lines(batch1)
        rc, _ = tr.on_lines(batch2)
        self.assertTrue(rc)
        rid = mapper.room_id('Northern gatehouse.')
        self.assertIn(rid, st.rooms)
        self.assertNotIn(mapper.room_id('Sturdy wooden gate (closed) leads north.'),
                         st.rooms)
        self.assertEqual(st.rooms[rid]['exits'], ['south'])

    def test_route_bfs_and_unreachable(self):
        st, tr = self.make()
        tr.on_lines(GATEHOUSE)
        tr.on_move(2500, 'north')
        tr.on_lines(STREET)
        third = [line(70, 5000, 'Market square.', 'room_title?'),
                 line(71, 5000, 'Obvious exits are: west.', 'exits')]
        tr.on_move(4900, 'east')
        tr.on_lines(third)
        steps = st.route(mapper.room_id('Northern gatehouse.'),
                         mapper.room_id('Market square.'))
        self.assertEqual(steps, ['north', 'east'])
        self.assertEqual(st.route(mapper.room_id('Northern gatehouse.'),
                                  mapper.room_id('Northern gatehouse.')), [])
        # 孤岛房间不可达
        st.touch_room('Island', [], 9000)
        self.assertIsNone(st.route(mapper.room_id('Northern gatehouse.'),
                                   mapper.room_id('Island')))


class TestAuditAndState(unittest.TestCase):
    def test_audit_tail_only_new_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'command-log.jsonl'
            p.write_text('{"time_ms":1,"command":"look","after_seq":0}\n'
                         '{"time_ms":2,"command":"n","after_seq":1}\n', encoding='utf-8')
            tail = mapper.AuditTail(p)
            self.assertEqual(tail.new_moves(), [])          # 启动前的历史不读
            with p.open('a', encoding='utf-8') as f:
                f.write('{"time_ms":3,"command":"sw","after_seq":2}\n'
                        '{"time_ms":4,"command":"eat pie","after_seq":3}\n')
            self.assertEqual(tail.new_moves(), [(3, 'southwest')])
            self.assertEqual(tail.new_moves(), [])          # 不重复读

    def test_state_roundtrip(self):
        st = mapper.MapState()
        rid = st.touch_room('Test Room', ['north'], 5)
        st.add_edge(rid, 'north', mapper.room_id('Other'))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'map.json'
            st.save(p)
            st2 = mapper.MapState.load(p)
            self.assertEqual(st2.rooms[rid]['visits'], 1)
            self.assertEqual(st2.edges[rid]['north'], mapper.room_id('Other'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
