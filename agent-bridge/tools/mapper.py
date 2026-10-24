#!/usr/bin/env python3
"""地图收集与寻路:记录走过的房间,支持"带我去某房间"。

设计给副驾驶用:你(用户)说"去 XXX 房间",agent 跑
    python3 agent-bridge/tools/mapper.py route "XXX"
拿到一步步的移动序列,经你同意后逐条发送(每步之间读回输出确认房间变了)。

数据来源(被动收集,玩的时候顺手跑着 record):
- 房间:事件流里的 room_title? + exits 行(lines.py 已分类)
- 边(哪个方向通向哪个房间):审计日志 command-log.jsonl 里的移动命令
  与其后 5 秒内出现的新房间做时间关联

已知限制(诚实记录):
- 房间以标题为唯一键;BatMUD 存在同名房间,会误合并(用 exits 辅助区分,
  但标题相同就合并)。发现明显不对可手工修 map.json。
- 只学习"经桥发送"的移动;你直接在客户端里打字走路不产生边,只记房间。
- 出口列表(exits)是"声称的出口",边(edges)是"走过的路";寻路只信边。

子命令:
    record          跟随事件流记录(与翻译窗并行开着)
    rooms [关键词]   列房间(标题/到访次数/已知边)
    route <目标>     从最近房间到目标的移动序列(--from 可指定起点)
    stats           统计
"""
import argparse
import json
import os
import re
import sys
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))

from batbridge.client import BridgeClient, BridgeConnectionError
from batbridge.lines import clean_lines

MAP_PATH = HERE.parent / 'agent' / 'memory' / 'map.json'
AUDIT_PATH = Path(os.environ.get(
    'BATBRIDGE_AUDIT',
    Path.home() / 'batclient' / 'agent-bridge' / 'command-log.jsonl'))

_DIRS = ('north', 'south', 'east', 'west', 'up', 'down',
         'northeast', 'northwest', 'southeast', 'southwest')
_DIR_ALIASES = {'n': 'north', 's': 'south', 'e': 'east', 'w': 'west',
                'u': 'up', 'd': 'down', 'ne': 'northeast', 'nw': 'northwest',
                'se': 'southeast', 'sw': 'southwest'}
_DIR_ALIASES.update({d: d for d in _DIRS})
_MOVE_RE = re.compile(r'^(%s)$' % '|'.join(sorted(_DIR_ALIASES, key=len, reverse=True)))
MOVE_WINDOW_MS = 5000   # 移动命令与其后新房间的时间关联窗口


def canon_dir(word):
    return _DIR_ALIASES.get(word.lower().strip(), '')


def parse_exits(text):
    """'Obvious exits are: north, south and east.' -> ['north','south','east']"""
    words = re.findall(r'[a-z]+', text.lower())
    return [canon_dir(w) for w in words if w in _DIR_ALIASES]


def room_id(title):
    return ' '.join(title.split()).lower()


class MapState(object):
    def __init__(self):
        self.rooms = {}   # id -> {title, exits[], visits, first_seq, last_seq}
        self.edges = {}   # id -> {dir: id}

    @classmethod
    def load(cls, path=MAP_PATH):
        s = cls()
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            s.rooms = data.get('rooms', {})
            s.edges = data.get('edges', {})
        except (OSError, ValueError):
            pass
        return s

    def save(self, path=MAP_PATH):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'rooms': self.rooms, 'edges': self.edges},
                                   ensure_ascii=False, indent=1), encoding='utf-8')

    def touch_room(self, title, exits, seq):
        rid = room_id(title)
        r = self.rooms.setdefault(rid, {'title': title.strip(), 'exits': [],
                                        'visits': 0, 'first_seq': seq, 'last_seq': seq})
        r['visits'] += 1
        r['last_seq'] = max(r['last_seq'], seq or 0)
        for d in exits:
            if d and d not in r['exits']:
                r['exits'].append(d)
        return rid

    def add_edge(self, a, d, b):
        if not a or not b or a == b or not d:
            return False
        slot = self.edges.setdefault(a, {})
        if slot.get(d) == b:
            return False
        slot[d] = b
        return True

    def latest_room(self):
        if not self.rooms:
            return None
        return max(self.rooms.items(), key=lambda kv: kv[1]['last_seq'])[0]

    def route(self, a, b):
        """BFS 最短路径;返回 dir 列表,不可达返回 None。"""
        if a == b:
            return []
        prev = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            for d, nxt in sorted(self.edges.get(cur, {}).items()):
                if nxt in prev or not nxt:
                    continue
                prev[nxt] = (cur, d)
                if nxt == b:
                    path = []
                    node = nxt
                    while prev[node]:
                        node, step = prev[node]
                        path.append(step)
                    return list(reversed(path))
                q.append(nxt)
        return None


class AuditTail(object):
    """增量读审计日志,产出移动命令 (time_ms, dir)。"""

    def __init__(self, path=AUDIT_PATH):
        self.path = Path(path)
        self.offset = 0
        if self.path.exists():
            self.offset = self.path.stat().st_size  # 只看启动之后的新命令

    def new_moves(self):
        moves = []
        if not self.path.exists():
            return moves
        with self.path.open('rb') as f:
            f.seek(self.offset)
            chunk = f.read()
            self.offset = f.tell()
        for raw in chunk.splitlines():
            try:
                rec = json.loads(raw.decode('utf-8'))
            except ValueError:
                continue
            cmd = (rec.get('command') or '').strip()
            if _MOVE_RE.match(cmd):
                moves.append((rec.get('time_ms', 0), canon_dir(cmd)))
        return moves


class RoomTracker(object):
    """把行流 + 移动命令流汇成房间/边状态。"""

    def __init__(self, state):
        self.state = state
        self.current = None
        self.pending_moves = []   # [(time_ms, dir)]

    def on_move(self, time_ms, direction):
        self.pending_moves.append((time_ms, direction))

    def on_lines(self, lines):
        """返回 (rooms_changed, edges_changed)。"""
        rc = ec = False
        # 先丢弃过期移动(超时没等到新房间的,多半是撞墙/失败)
        now = max((l.get('time_ms') or 0) for l in lines) if lines else 0
        if now:
            self.pending_moves = [m for m in self.pending_moves
                                  if now - m[0] <= 2 * MOVE_WINDOW_MS]
        for i, entry in enumerate(lines):
            if entry['kind'] != 'exits':
                continue
            title = None
            for cand in reversed(lines[max(0, i - 10):i]):
                if cand['kind'] == 'room_title?':
                    title = cand['text']
                    break
            exits = parse_exits(entry['text'])
            if not title:
                # 有出口无标题:把出口并进当前房间,不动房间指针
                if self.current and exits:
                    r = self.state.rooms[self.current]
                    for d in exits:
                        if d not in r['exits']:
                            r['exits'].append(d)
                    rc = True
                continue
            rid = self.state.touch_room(title, exits, entry.get('seq_end'))
            rc = True
            # 关联:最近一条早于本房间出现、且在窗口内的移动命令
            t = entry.get('time_ms') or 0
            move_dir = ''
            while self.pending_moves and self.pending_moves[0][0] <= t:
                mt, move_dir = self.pending_moves.pop(0)
                if t - mt > MOVE_WINDOW_MS:
                    move_dir = ''
            if self.current and move_dir:
                ec = self.state.add_edge(self.current, move_dir, rid) or ec
            self.current = rid
        return rc, ec


def cmd_record():
    client = BridgeClient()
    state = MapState.load()
    tracker = RoomTracker(state)
    audit = AuditTail()
    after = client.status()['latest_seq']
    print('记录中(map.json 会即时保存;Ctrl-C 退出)')
    while True:
        try:
            batch = client.read(after, wait_ms=1000)
        except (BridgeConnectionError, OSError) as e:
            sys.stderr.write('桥不可达:%s,3 秒后重试\n' % e)
            time.sleep(3)
            continue
        events = batch.get('events', [])
        if not events:
            for tm, d in audit.new_moves():
                tracker.on_move(tm, d)
            continue
        after = events[-1]['seq']
        lines, _ = clean_lines(events)
        for tm, d in audit.new_moves():
            tracker.on_move(tm, d)
        rc, ec = tracker.on_lines(lines)
        if rc or ec:
            state.save()


def cmd_rooms(query):
    state = MapState.load()
    for rid, r in sorted(state.rooms.items(), key=lambda kv: -kv[1]['visits']):
        if query and query.lower() not in r['title'].lower():
            continue
        edges = state.edges.get(rid, {})
        dests = ', '.join('%s→%s' % (d, state.rooms[t]['title']) for d, t in sorted(edges.items()))
        print('%s(到访 %d)%s%s' % (r['title'], r['visits'],
              '  走过的路: ' + dests if dests else '',
              ''))


def cmd_route(to_title, from_title=None):
    state = MapState.load()
    if not state.rooms:
        raise SystemExit('map.json 还是空的:先跑 record 走几个房间')
    to_id = room_id(to_title)
    matches = [rid for rid in state.rooms if rid == to_id or to_id in rid]
    if not matches:
        cands = [r['title'] for rid, r in state.rooms.items() if to_id.split()[0] in rid]
        raise SystemExit('地图里没有"%"%s' % (to_title, (';相近的:' + ';'.join(cands[:5])) if cands else ''))
    to_id = matches[0]
    from_id = room_id(from_title) if from_title else state.latest_room()
    if from_id not in state.rooms:
        raise SystemExit('起点不在地图里: %s' % from_title)
    steps = state.route(from_id, to_id)
    if steps is None:
        raise SystemExit('暂时走不到(地图还没学到这条路):%s -> %s'
                         % (state.rooms[from_id]['title'], state.rooms[to_id]['title']))
    print('从 %s 到 %s,共 %d 步:' % (state.rooms[from_id]['title'],
                                     state.rooms[to_id]['title'], len(steps)))
    cur = from_id
    for i, d in enumerate(steps, 1):
        cur = state.edges[cur][d]
        print('  %d. %-9s -> %s' % (i, d, state.rooms[cur]['title']))
    print('提示:这是已走过的路;执行时每步之间读回输出确认房间变化。')


def cmd_stats():
    state = MapState.load()
    n_edges = sum(len(v) for v in state.edges.values())
    print('房间 %d 个,走过的边 %d 条;地图文件:%s' % (len(state.rooms), n_edges, MAP_PATH))


def main():
    ap = argparse.ArgumentParser(description='BatMUD 房间地图:记录与寻路')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('record', help='跟随事件流记录房间与边')
    r = sub.add_parser('rooms', help='列出房间')
    r.add_argument('query', nargs='?')
    t = sub.add_parser('route', help='给出到某房间的移动序列')
    t.add_argument('to')
    t.add_argument('--from', dest='frm')
    sub.add_parser('stats')
    a = ap.parse_args()
    {'record': cmd_record, 'rooms': lambda: cmd_rooms(a.query),
     'route': lambda: cmd_route(a.to, a.frm), 'stats': cmd_stats}[a.cmd]()


if __name__ == '__main__':
    main()
