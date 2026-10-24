#!/usr/bin/env python3
"""Local BatMUD bridge client. Never uses HTTP_PROXY/HTTPS_PROXY.

Examples:
  bridge_cli.py status
  bridge_cli.py read --after 0 --limit 100 --wait-ms 5000
  bridge_cli.py send look --wait 3
  bridge_cli.py follow
"""
import argparse, json, pathlib, sys, time
import urllib.request, urllib.error

HOST = 'http://127.0.0.1:18765'
DEFAULT_TOKEN = pathlib.Path.home() / 'batclient/agent-bridge/token.txt'
MAX_WAIT_MS = 10000  # server-side cap for one long poll


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--token-file', type=pathlib.Path, default=DEFAULT_TOKEN)
    s = p.add_subparsers(dest='action', required=True)
    s.add_parser('status', help='connection and cursor state')
    r = s.add_parser('read', help='read new game output after a cursor')
    r.add_argument('--after', type=int, default=0, help='only return events with seq > this')
    r.add_argument('--limit', type=int, default=500, help='max events per batch (1..2000)')
    r.add_argument('--wait-ms', type=int, default=0, help='block up to this many ms if there is nothing new')
    c = s.add_parser('send', help='dispatch one single-line command')
    c.add_argument('command')
    c.add_argument('--wait', type=float, default=0, help='after dispatch, long-poll up to this many seconds for new output')
    f = s.add_parser('follow', help='stream new output continuously (Ctrl-C to stop)')
    f.add_argument('--after', type=int, default=None, help='start cursor (default: current latest_seq)')
    a = p.parse_args()

    try:
        token = a.token_file.read_text().strip()
    except OSError as e:
        raise SystemExit(f'cannot read token file {a.token_file}: {e}')

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, body=None, timeout=10):
        req = urllib.request.Request(
            HOST + path,
            data=None if body is None else body.encode('utf-8'),
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'text/plain; charset=utf-8'})
        try:
            with opener.open(req, timeout=timeout) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            raise SystemExit(f'{e.code} {e.read().decode()}')
        except urllib.error.URLError as e:
            raise SystemExit(f'cannot reach AgentBridge at {HOST} (is the BatMUD client running?): {e.reason}')

    def poll(after, wait_ms, limit=500):
        wait_ms = min(wait_ms, MAX_WAIT_MS)
        return request(f'/events?after={after}&limit={limit}&wait_ms={wait_ms}', timeout=wait_ms / 1000 + 10)

    if a.action == 'status':
        result = request('/status')
    elif a.action == 'read':
        result = poll(a.after if a.after >= 0 else 0, a.wait_ms, a.limit)
    elif a.action == 'send':
        result = request('/command', a.command)
        if a.wait > 0:
            deadline = time.time() + min(a.wait, 30)
            after, collected = result['after_seq'], []
            while time.time() < deadline:
                batch = poll(after, int((deadline - time.time()) * 1000))
                events = batch.get('events', [])
                collected += events
                if events:
                    after = events[-1]['seq']
                    if not batch.get('more'):
                        break
            result = {'dispatch': result, 'output': {'events': collected, 'latest_seq': after}}
    else:  # follow
        after = a.after if a.after is not None else request('/status')['latest_seq']
        print(f'following from seq {after} (Ctrl-C to stop)', file=sys.stderr)
        try:
            while True:
                batch = poll(after, MAX_WAIT_MS)
                for e in batch.get('events', []):
                    print(f"{e['seq']}\t{e['text']}")
                if batch.get('events'):
                    after = batch['events'][-1]['seq']
        except KeyboardInterrupt:
            pass
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
