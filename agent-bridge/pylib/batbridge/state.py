"""Shared live game state: hp/sp/ep/cash/exp + current room.

state_watch.py (or any reader loop) feeds clean lines in; the state is
persisted to agent/memory/state.json so any tool or MCP client can read
"where am I and how am I doing" instantly without touching the bridge.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_PATH = HERE.parents[1] / 'agent' / 'memory' / 'state.json'

# hp: 586 (586) [] sp: 294 (294) [] ep: 212 (212) [] cash: 16661 [] exp: 19227 []
STATUS_RE = re.compile(
    r'hp: (\d+) \((\d+)\).*?sp: (\d+) \((\d+)\).*?ep: (\d+) \((\d+)\).*?'
    r'cash: (\d+).*?exp: (\d+)')


def parse_status(text):
    """状态行 -> dict(hp,hp_max,sp,sp_max,ep,ep_max,cash,exp);不是状态行返回 None。"""
    m = STATUS_RE.search(text)
    if not m:
        return None
    hp, hp_max, sp, sp_max, ep, ep_max, cash, exp = m.groups()
    return {'hp': int(hp), 'hp_max': int(hp_max), 'sp': int(sp),
            'sp_max': int(sp_max), 'ep': int(ep), 'ep_max': int(ep_max),
            'cash': int(cash), 'exp': int(exp)}


class GameState(object):
    """从行流累积的当前状态;任何字段未知时保持原值。"""

    def __init__(self):
        self.hp = self.hp_max = self.sp = self.sp_max = None
        self.ep = self.ep_max = self.cash = self.exp = None
        self.room = None
        self.updated_ms = None
        self.seq = None

    # ---- persistence ----

    @classmethod
    def load(cls, path=None):
        s = cls()
        try:
            data = json.loads(Path(path or STATE_PATH).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return s
        for k, v in data.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

    def save(self, path=None):
        path = Path(path or STATE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=1),
                        encoding='utf-8')

    def as_dict(self):
        return {k: getattr(self, k) for k in
                ('hp', 'hp_max', 'sp', 'sp_max', 'ep', 'ep_max',
                 'cash', 'exp', 'room', 'updated_ms', 'seq')}

    # ---- ingestion ----

    def update_from_lines(self, lines):
        """吃进 clean_lines 的输出;返回是否有变化。"""
        changed = False
        for i, entry in enumerate(lines):
            text = entry['text']
            st = parse_status(text) if text.startswith('hp: ') else None
            if st:
                for k, v in st.items():
                    if getattr(self, k) != v:
                        setattr(self, k, v)
                        changed = True
                continue
            if entry['kind'] == 'exits':
                for cand in reversed(lines[max(0, i - 10):i]):
                    if cand['kind'] == 'room_title?':
                        if self.room != cand['text']:
                            self.room = cand['text']
                            changed = True
                        break
        if lines:
            last = lines[-1]
            self.updated_ms = last.get('time_ms')
            self.seq = last.get('seq_end')
        return changed

    def summary_zh(self):
        """一行中文摘要(给 agent/用户快速看)。"""
        bits = []
        if self.hp is not None:
            bits.append('血 %s/%s' % (self.hp, self.hp_max))
        if self.sp is not None:
            bits.append('法 %s/%s' % (self.sp, self.sp_max))
        if self.ep is not None:
            bits.append('精 %s/%s' % (self.ep, self.ep_max))
        if self.cash is not None:
            bits.append('钱 %s' % self.cash)
        if self.exp is not None:
            bits.append('经验 %s' % self.exp)
        if self.room:
            bits.append('位置[%s]' % self.room)
        else:
            bits.append('位置未知')
        return ' | '.join(bits)
