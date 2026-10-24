#!/usr/bin/env python3
"""Integration tests for batbridge.client.BridgeClient against a live harness.

Two harness runs: a wide rate bucket for functional checks, then a tiny
bucket to verify BridgeError carries 429 retry_after_ms.
"""
import os, pathlib, subprocess, sys, tempfile, time, unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
BRIDGE = ROOT / 'agent-bridge'
sys.path.insert(0, str(BRIDGE / 'pylib'))

from batbridge.client import BridgeClient, BridgeError, BridgeConnectionError
from batbridge.lines import clean_lines

api = ROOT / 'downloads/bat_interfaces.jar'
api_cp = api if api.exists() else BRIDGE / 'build-stubs-compiled'
CP = ':'.join(str(x) for x in [api_cp, BRIDGE / 'build', BRIDGE / 'tests'])
JAVA = pathlib.Path(subprocess.check_output(['/usr/libexec/java_home']).decode().strip()) / 'bin' / 'java'
PORT = 18766


class HarnessBase(unittest.TestCase):
    java_args = ()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = subprocess.Popen(
            [str(JAVA), '-Djava.awt.headless=true', '-Dbatbridge.port=%d' % PORT]
            + list(self.java_args) + ['-cp', CP, 'BridgeHarness', self.tmp.name],
            stdout=subprocess.DEVNULL)
        tokenfile = pathlib.Path(self.tmp.name) / 'agent-bridge/token.txt'
        for _ in range(100):
            if tokenfile.exists():
                break
            time.sleep(.05)
        self.client = BridgeClient(port=PORT, token=tokenfile.read_text().strip())
        for _ in range(40):
            try:
                self.client.status()
                return
            except BridgeConnectionError:
                time.sleep(.05)
        self.fail('bridge harness did not come up')

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)
        self.tmp.cleanup()


class TestFunctional(HarnessBase):
    java_args = ('-Dbatbridge.rate.burst=20',)

    def test_status_and_version(self):
        st = self.client.status()
        self.assertEqual(st['version'], '0.4.0')
        self.assertIn('oldest_seq', st)

    def test_read_returns_unicode_event(self):
        for _ in range(80):
            batch = self.client.read(0)
            if batch['events']:
                break
            time.sleep(.05)
        self.assertTrue(any('中文' in e['text'] for e in batch['events']))

    def test_send_and_collect(self):
        r = self.client.send('look', wait_s=2)
        self.assertTrue(r['dispatch']['dispatched'])
        self.assertTrue(any(e['text'] == 'ROOM: look' for e in r['events']))
        lines, stats = clean_lines(r['events'])
        self.assertEqual([l['text'] for l in lines], ['ROOM: look'])
        self.assertEqual(stats['events'], 1)

    def test_multiline_rejected(self):
        with self.assertRaises(BridgeError) as ctx:
            self.client.send('look\nscore')
        self.assertEqual(ctx.exception.code, 400)

    def test_connection_error_message(self):
        bad = BridgeClient(port=PORT, token='wrong-token-but-bridge-up')
        bad._token = 'nope'  # 401 path proves HTTP errors surface as BridgeError
        with self.assertRaises(BridgeError) as ctx:
            bad.status()
        self.assertEqual(ctx.exception.code, 401)


class TestRateLimited(HarnessBase):
    java_args = ('-Dbatbridge.rate.burst=2', '-Dbatbridge.rate.refill_ms=400',)

    def test_429_carries_retry_after(self):
        self.client.send('look')
        self.client.send('look')
        with self.assertRaises(BridgeError) as ctx:
            self.client.send('look')
        self.assertEqual(ctx.exception.code, 429)
        self.assertTrue(0 < ctx.exception.retry_after_ms <= 400)
        self.assertFalse(ctx.exception.body['dispatched'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
