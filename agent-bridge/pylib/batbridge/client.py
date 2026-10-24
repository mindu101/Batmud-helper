"""BridgeClient: thin, dependency-free HTTP client for the AgentBridge plugin.

Semantics mirror the plugin contract:
- dispatched=true only means the client accepted the command; verify output.
- a 429 rejection means the command was NOT sent; retry after retry_after_ms.
- a 504 timeout means the outcome is unknown; never retry blindly.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 18765
DEFAULT_TOKEN_FILE = Path.home() / 'batclient/agent-bridge/token.txt'
MAX_WAIT_MS = 10000


class BridgeError(Exception):
    """Non-2xx bridge response; .code is the HTTP status, .body the parsed JSON."""

    def __init__(self, code, body):
        self.code, self.body = code, body
        super().__init__('%s %s' % (code, json.dumps(body, ensure_ascii=False)))

    @property
    def retry_after_ms(self):
        return self.body.get('retry_after_ms') if isinstance(self.body, dict) else None


class BridgeConnectionError(Exception):
    pass


class BridgeClient(object):
    def __init__(self, port=None, token_file=None, token=None):
        self.port = int(port or os.environ.get('BATBRIDGE_PORT', DEFAULT_PORT))
        if token is None:
            token_file = Path(token_file or os.environ.get('BATBRIDGE_TOKEN_FILE')
                              or DEFAULT_TOKEN_FILE)
            token = token_file.read_text().strip()
        self._token = token
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path, body=None, timeout=10):
        req = urllib.request.Request(
            'http://127.0.0.1:%d%s' % (self.port, path),
            data=None if body is None else body.encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self._token,
                     'Content-Type': 'text/plain; charset=utf-8'})
        try:
            with self._opener.open(req, timeout=timeout) as res:
                return json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                parsed = json.loads(e.read().decode('utf-8'))
            except Exception:
                parsed = {}
            raise BridgeError(e.code, parsed)
        except OSError as e:
            raise BridgeConnectionError(
                'cannot reach AgentBridge on 127.0.0.1:%d (is the BatMUD client '
                'running?): %s' % (self.port, e))

    def status(self):
        return self._request('/status')

    def read(self, after=0, limit=500, wait_ms=0):
        wait_ms = max(0, min(int(wait_ms), MAX_WAIT_MS))
        return self._request('/events?after=%d&limit=%d&wait_ms=%d'
                             % (after, limit, wait_ms), timeout=wait_ms / 1000.0 + 10)

    def send(self, command, wait_s=0.0):
        """Dispatch one single-line command; optionally collect output after it."""
        try:
            dispatch = self._request('/command', command)
        except BridgeError:
            raise
        result = {'dispatch': dispatch, 'events': [], 'lines': None}
        if wait_s > 0:
            deadline = time.time() + min(wait_s, 30)
            after = dispatch['after_seq']
            while time.time() < deadline:
                batch = self.read(after, wait_ms=int(max(0, (deadline - time.time()) * 1000)))
                if batch['events']:
                    result['events'].extend(batch['events'])
                    after = batch['events'][-1]['seq']
                    if not batch.get('more'):
                        break
                elif not batch.get('more'):
                    break
        return result

    def follow(self, after=None):
        """Yield new events forever (long-poll); stops when the bridge dies."""
        if after is None:
            after = self.status()['latest_seq']
        while True:
            batch = self.read(after, wait_ms=MAX_WAIT_MS)
            for ev in batch['events']:
                yield ev
            if batch['events']:
                after = batch['events'][-1]['seq']
