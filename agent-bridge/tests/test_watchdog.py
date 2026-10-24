#!/usr/bin/env python3
"""Unit tests for watchdog state machine (injected check/notifier/launcher)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import watchdog as wd


class Script(object):
    """按次返回预设状态;stop 在第 n 次后为真。"""

    def __init__(self, states, interval=0):
        self.states = list(states)
        self.i = 0
        self.interval = interval
        self.launches = []

    def check(self):
        return self.states[min(self.i, len(self.states) - 1)]

    def sleep(self, s):
        self.i += 1

    def stop(self):
        return self.i >= len(self.states)


def run(script, **kw):
    notes = []
    history = wd.run_watch(script.check, notifier=lambda t, m: notes.append((t, m)),
                           sleep=script.sleep, stop=script.stop, **kw)
    return history, notes


class TestWatchdog(unittest.TestCase):
    def test_transition_notifies_once_per_change(self):
        s = Script([wd.OK, wd.OK, wd.BRIDGE_DOWN, wd.BRIDGE_DOWN, wd.OK])
        history, notes = run(s)
        self.assertEqual([h[0] for h in history], [wd.OK, wd.BRIDGE_DOWN, wd.OK])
        self.assertEqual(len(notes), 3)          # 状态不变不重复通知
        self.assertIn('桥不可达', notes[1][1])
        self.assertIn('恢复', notes[2][1])

    def test_game_down_distinct_from_bridge_down(self):
        s = Script([wd.GAME_DOWN])
        _, notes = run(s)
        self.assertIn('游戏服务器', notes[0][1])
        self.assertNotIn('桥不可达', notes[0][1])

    def test_relaunch_fires_once_per_episode(self):
        s = Script([wd.OK, wd.BRIDGE_DOWN, wd.BRIDGE_DOWN, wd.BRIDGE_DOWN])
        launches = []
        history, notes = run(s, relaunch=True, launcher=lambda: launches.append(1))
        self.assertEqual(len(launches), 1)       # 一集掉线只拉起一次
        self.assertIn('自动重启客户端', notes[1][1])
        self.assertEqual([h[1] for h in history], [False, True])

    def test_relaunch_recovers_after_ok(self):
        s = Script([wd.BRIDGE_DOWN, wd.OK, wd.BRIDGE_DOWN])
        launches = []
        run(s, relaunch=True, launcher=lambda: launches.append(1))
        self.assertEqual(len(launches), 2)       # 恢复后再掉线会再拉起

    def test_no_relaunch_by_default(self):
        s = Script([wd.BRIDGE_DOWN])
        launches = []
        run(s, launcher=lambda: launches.append(1))
        self.assertEqual(launches, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
