#!/usr/bin/env python3
"""游戏状态监视:跟随事件流,持续更新 agent/memory/state.json。

开个终端跑着(与翻译窗/地图并行):
    python3 agent-bridge/tools/state_watch.py

之后任何工具/agent 读 state.json 即可秒得当前血法精/现金/经验/所在房间;
MCP 工具 batmud_state 也从这里取数。Ctrl-C 退出。
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))

from batbridge.client import BridgeClient, BridgeConnectionError
from batbridge.lines import clean_lines
from batbridge.state import GameState

INTERVAL_ON_DOWN = 3


def run(client, state, out=sys.stderr, sleep=time.sleep, stop=None):
    after = None
    while stop is None or not stop():
        try:
            if after is None:
                after = client.status()['latest_seq']
            batch = client.read(after, wait_ms=1000)
        except (BridgeConnectionError, OSError) as e:
            out.write('桥不可达:%s,%ds 后重试\n' % (e, INTERVAL_ON_DOWN))
            out.flush()
            sleep(INTERVAL_ON_DOWN)
            continue
        events = batch.get('events', [])
        if not events:
            continue
        after = events[-1]['seq']
        lines, _ = clean_lines(events)
        if state.update_from_lines(lines):
            state.save()
            out.write('%s\n' % state.summary_zh())
            out.flush()


def main():
    try:
        client = BridgeClient()
    except OSError as e:
        sys.stderr.write('桥 token 不可读:%s\n' % e)
        return 2
    state = GameState.load()
    print('状态监视中(state.json 即时保存;Ctrl-C 退出)当前:%s'
          % state.summary_zh())
    try:
        run(client, state)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
