#!/usr/bin/env python3
"""Find where a word appeared in recent game output (context for the vocab book).

Usage: python3 agent-bridge/agent/find_word.py <word> [max_age_seq]

Scans the bridge's in-memory event buffer (up to 2000 events) for lines
containing the word (case-insensitive), prints them with seq numbers so the
co-pilot agent can quote the original sentence in a vocabulary entry.
If the bridge is down or the word isn't in the buffer, it says so —
the agent should then ask the user for the sentence instead of guessing.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))

from batbridge.client import BridgeClient, BridgeConnectionError
from batbridge.lines import clean_lines


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        raise SystemExit('usage: find_word.py <word>')
    word = sys.argv[1].strip().lower()
    try:
        client = BridgeClient()
        st = client.status()
        batch = client.read(max(0, st['latest_seq'] - 2000), limit=2000)
    except (BridgeConnectionError, OSError) as e:
        print('bridge unreachable: %s' % e)
        print('ask the user for the sentence instead of guessing context')
        return
    lines, _ = clean_lines(batch['events'])
    hits = [l for l in lines if word in l['text'].lower()]
    if not hits:
        print('"%s" not in the current buffer (latest_seq=%d).' % (word, st['latest_seq']))
        print('note: buffer holds the last 2000 events and resets on client restart;')
        print('if the user saw it earlier, ask them for the sentence.')
        return
    for l in hits[-10:]:
        print('[%d|%s] %s' % (l['seq_start'], l['kind'], l['text']))


if __name__ == '__main__':
    main()
