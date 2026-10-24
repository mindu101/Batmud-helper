#!/usr/bin/env python3
"""Refresh the live-snapshot section of memory/short-term.md from the bridge.

Only rewrites between the snapshot markers; goals/notes sections are kept.
Safe to run any time: bridge down -> writes an explicit 'unreachable' note.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))

from batbridge.client import BridgeClient, BridgeConnectionError
from batbridge.lines import clean_lines

SNAP_START = '<!-- snapshot:start -->'
SNAP_END = '<!-- snapshot:end -->'


def snapshot_text():
    try:
        client = BridgeClient()
        st = client.status()
        batch = client.read(max(0, st['latest_seq'] - 40), limit=40)
        lines, _ = clean_lines(batch['events'])
        recent = '\n'.join('  - [%s] %s' % (l['kind'], l['text'][:60]) for l in lines[-8:]) or '  - (无输出)'
        return (
            '- 刷新时间:%s\n'
            '- 桥接:版本 %s,session `%s`,连接%s,latest_seq %s,'
            'commands_sent %s,落盘%s,限速 突发%s/每%sms回1。\n'
            '- 最近画面(最多 8 行,已做行整理):\n%s\n'
        ) % (time.strftime('%Y-%m-%d %H:%M:%S'), st['version'], st['session'],
             '正常' if st['connected'] else '断开', st['latest_seq'],
             st['commands_sent'], '开' if st['persisting'] else '关',
             st['rate_burst'], st['rate_refill_ms'], recent)
    except (BridgeConnectionError, OSError) as e:
        return ('- 刷新时间:%s\n- **桥接不可达**(%s)\n'
                '  接班者注意:先确认 BatMUD 客户端已启动,再重跑本脚本。\n'
                % (time.strftime('%Y-%m-%d %H:%M:%S'), e))


def main():
    path = HERE / 'memory' / 'short-term.md'
    text = path.read_text(encoding='utf-8')
    if SNAP_START not in text or SNAP_END not in text:
        raise SystemExit('short-term.md 缺少快照标记,拒绝盲写')
    head, rest = text.split(SNAP_START, 1)
    _, tail = rest.split(SNAP_END, 1)
    path.write_text(head + SNAP_START + '\n\n' + snapshot_text() + '\n' + SNAP_END + tail,
                    encoding='utf-8')
    print('short-term.md 实时快照已刷新')


if __name__ == '__main__':
    main()
