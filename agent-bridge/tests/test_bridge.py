#!/usr/bin/env python3
"""Integration tests for the AgentBridge plugin.

Loads the real plugin class into a headless harness and exercises the HTTP
API on side port 18766, so it can run while the real game client holds 18765.
Run ./build.sh first.

Run 1 uses a large rate bucket so the functional suite is not throttled and
checks the command audit log. Run 2 uses a tiny bucket (burst 2, refill
400 ms) to test the /command rate limit deterministically.
"""
import json, os, pathlib, socket, subprocess, tempfile, threading, time
import urllib.request, urllib.error

root = pathlib.Path(__file__).resolve().parents[2]
port_dir = root / 'agent-bridge'
TEST_PORT = 18766
BASE = 'http://127.0.0.1:%d' % TEST_PORT

def find_java():
    candidates = []
    if os.environ.get('BAT_JDK'):
        candidates.append(pathlib.Path(os.environ['BAT_JDK']))
    if (root / 'runtime').is_dir():
        candidates += sorted((root / 'runtime').glob('*/Contents/Home'))
    for c in candidates:
        if (c / 'bin' / 'java').exists():
            return c / 'bin' / 'java'
    return pathlib.Path(subprocess.check_output(['/usr/libexec/java_home']).decode().strip()) / 'bin' / 'java'

java = find_java()
api = root / 'downloads/bat_interfaces.jar'
api_cp = api if api.exists() else port_dir / 'build-stubs-compiled'
cp = ':'.join(str(x) for x in [api_cp, port_dir / 'build', port_dir / 'tests'])
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Compile the harness if it is missing or older than its source.
harness_src = port_dir / 'tests' / 'BridgeHarness.java'
harness_cls = port_dir / 'tests' / 'BridgeHarness.class'
if not harness_cls.exists() or harness_cls.stat().st_mtime < harness_src.stat().st_mtime:
    subprocess.check_call([str(java.parent / 'javac'), '-cp',
                           ':'.join(str(x) for x in [api_cp, port_dir / 'build']),
                           '-d', str(port_dir / 'tests'), str(harness_src)])

def start_harness(temp, extra_args=()):
    return subprocess.Popen([str(java), '-Djava.awt.headless=true',
                             '-Dbatbridge.port=%d' % TEST_PORT] + list(extra_args) +
                            ['-cp', cp, 'BridgeHarness', temp],
                            stdout=subprocess.DEVNULL)

def wait_ready(proc, temp):
    tokenfile = pathlib.Path(temp) / 'agent-bridge/token.txt'
    for _ in range(100):
        if tokenfile.exists():
            break
        time.sleep(.05)
    token = tokenfile.read_text()

    def req(path, body=None, auth=True, extra=None, timeout=8):
        h = {'Authorization': 'Bearer ' + token} if auth else {}
        h.update(extra or {})
        r = urllib.request.Request(BASE + path, data=body, headers=h)
        try:
            with opener.open(r, timeout=timeout) as x:
                return x.status, json.loads(x.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    for _ in range(40):
        try:
            status = req('/status')
            if status[0] == 200:
                return token, req
        except OSError:
            pass
        time.sleep(.05)
    raise AssertionError('bridge did not come up')

def read_audit(temp):
    path = pathlib.Path(temp) / 'agent-bridge/command-log.jsonl'
    return [json.loads(l) for l in path.read_text().splitlines()]


# ---- Run 1: functional suite (rate bucket widened so it never throttles) ----

with tempfile.TemporaryDirectory() as temp:
    p = start_harness(temp, ['-Dbatbridge.rate.burst=20'])
    try:
        token, req = wait_ready(p, temp)

        status = req('/status')
        assert status[0] == 200
        assert status[1]['version'] == '0.3.0' and 'oldest_seq' in status[1], status
        assert status[1]['rate_burst'] == 20 and status[1]['rate_refill_ms'] == 3000, status

        # auth, browser-origin rejection, unknown path, wrong methods
        assert req('/status', auth=False)[0] == 401
        assert req('/status', extra={'Origin': 'https://example.com'})[0] == 403
        assert req('/nope')[0] == 404
        assert req('/status', body=b'')[0] == 405
        assert req('/command')[0] == 405

        # unicode output and input preservation (the harness fires this after startup)
        initial = None
        for _ in range(80):
            initial = req('/events?after=0')[1]
            if initial['events']:
                break
            time.sleep(.05)
        assert initial['events'] and '中文' in initial['events'][0]['text']
        assert initial['more'] is False

        # command validation
        assert req('/command', b'look\nscore')[0] == 400                    # multiline
        assert req('/command', b'')[0] == 400                               # empty body (Content-Length: 0)
        assert req('/command', b'{"cmd":"look"}',
                   extra={'Content-Type': 'application/json'})[0] == 415    # accidental JSON body
        raw = socket.create_connection(('127.0.0.1', TEST_PORT), timeout=5)  # no Content-Length at all
        raw.sendall(b'POST /command HTTP/1.1\r\nAuthorization: Bearer ' + token.encode() + b'\r\n\r\n')
        no_length = raw.recv(4096).decode()
        raw.close()
        assert no_length.startswith('HTTP/1.1 411'), no_length.splitlines()[0]

        # dispatch + cursor readback
        sent = req('/command', b'look')
        assert sent[0] == 200 and sent[1]['dispatched']
        events = req('/events?after=' + str(sent[1]['after_seq']))[1]['events']
        assert any(e['text'] == 'ROOM: look' for e in events)
        assert req('/status')[1]['commands_sent'] == 1

        # limit batching with the more flag
        latest = req('/status')[1]['latest_seq']
        for c in (b'a1', b'a2', b'a3'):
            assert req('/command', c)[0] == 200
        batch = req('/events?after=' + str(latest) + '&limit=2')[1]
        assert [e['text'] for e in batch['events']] == ['ROOM: a1', 'ROOM: a2'] and batch['more'] is True
        rest = req('/events?after=' + str(batch['events'][-1]['seq']))[1]
        assert [e['text'] for e in rest['events']] == ['ROOM: a3'] and rest['more'] is False

        # invalid query params are rejected, not silently ignored
        for q in ('after=abc', 'after=', 'limit=0', 'limit=99999', 'wait_ms=99999', 'bogus=1'):
            assert req('/events?' + q)[0] == 400, q

        # long poll: no new events -> empty after the full wait
        latest = req('/status')[1]['latest_seq']
        t0 = time.time()
        empty = req('/events?after=%d&wait_ms=300' % latest, timeout=8)[1]
        assert empty['events'] == [] and time.time() - t0 >= .25, time.time() - t0

        # long poll: event arriving mid-wait returns as soon as it exists
        delayed = threading.Timer(.5, lambda: req('/command', b'delayed'))
        delayed.start()
        t0 = time.time()
        woken = req('/events?after=%d&wait_ms=3000' % latest, timeout=8)[1]
        elapsed = time.time() - t0
        delayed.join()
        assert any(e['text'] == 'ROOM: delayed' for e in woken['events'])
        assert elapsed >= .4, elapsed

        # cursor past the end stays empty
        ahead = req('/events?after=999999')[1]
        assert ahead['events'] == [] and ahead['more'] is False

        assert req('/status')[1]['commands_sent'] == 5

        # audit log: exactly the dispatched commands, in order, nothing else
        audit = read_audit(temp)
        assert [l['command'] for l in audit] == ['look', 'a1', 'a2', 'a3', 'delayed'], audit
        assert all('time_ms' in l and 'session' in l and 'after_seq' in l for l in audit)

        print('run 1 PASS: auth, origin rejection, 405/411/415, Unicode, multiline rejection, '
              'dispatch + cursor readback, limit batching with more flag, long-poll '
              '(empty timeout and wake-on-event), invalid-query rejection, audit log')
    finally:
        p.terminate()
        p.wait(timeout=5)


# ---- Run 2: rate limiting with a tiny bucket (burst 2, refill 400 ms) ----

with tempfile.TemporaryDirectory() as temp:
    p = start_harness(temp, ['-Dbatbridge.rate.burst=2', '-Dbatbridge.rate.refill_ms=400'])
    try:
        token, req = wait_ready(p, temp)

        st = req('/status')[1]
        assert st['rate_burst'] == 2 and st['rate_refill_ms'] == 400, st

        assert req('/command', b'look')[0] == 200      # burst token 1
        assert req('/command', b'look')[0] == 200      # burst token 2
        rejected = req('/command', b'look')            # bucket empty
        assert rejected[0] == 429, rejected
        assert rejected[1]['dispatched'] is False
        assert 0 < rejected[1]['retry_after_ms'] <= 400, rejected
        assert req('/status')[1]['commands_sent'] == 2  # rejection dispatched nothing

        # a second rejection still carries a Retry-After HTTP header
        r = urllib.request.Request(BASE + '/command', data=b'look',
                                   headers={'Authorization': 'Bearer ' + token})
        try:
            opener.open(r, timeout=5)
            raise AssertionError('expected 429')
        except urllib.error.HTTPError as e:
            assert e.code == 429 and int(e.headers['Retry-After']) >= 1, e.headers

        # after retry_after_ms the bucket refills and the same command goes through
        time.sleep(rejected[1]['retry_after_ms'] / 1000 + .15)
        ok = req('/command', b'look')
        assert ok[0] == 200 and ok[1]['dispatched'], ok
        assert req('/status')[1]['commands_sent'] == 3

        audit = read_audit(temp)
        assert [l['command'] for l in audit] == ['look', 'look', 'look'], audit

        print('run 2 PASS: rate limit burst 2, 429 with retry_after_ms + Retry-After header, '
              'rejections dispatch nothing, refill allows retry, audit matches dispatches')
    finally:
        p.terminate()
        p.wait(timeout=5)
