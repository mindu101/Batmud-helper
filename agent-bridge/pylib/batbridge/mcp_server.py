"""Minimal MCP (Model Context Protocol) stdio server exposing the bridge and KB.

Dependency-free implementation of the MCP stdio transport: newline-delimited
JSON-RPC 2.0 over stdin/stdout, everything else goes to stderr. Implements
the stable subset a desktop agent needs:

    initialize, notifications/initialized, ping, tools/list, tools/call

Tools:
    batmud_status()                          bridge connection/cursor state
    batmud_read(after, limit, wait_ms, raw)  clean logical lines (or raw events)
    batmud_send(command, wait_s)             dispatch + collect, 429 surfaced
    kb_search(query, scope, limit)           search game knowledge notes
    kb_read(path)                            read one note (guarded)
    kb_list()                                list note files

Run:
    BATBRIDGE_PORT=18765 PYTHONPATH=agent-bridge/pylib python3 -m batbridge.mcp_server

Tool errors are returned as results with isError=true so the calling agent
sees the message instead of a transport failure.
"""

import io
import json
import os
import sys
import traceback

from . import kb
from .client import BridgeClient, BridgeError, BridgeConnectionError
from .lines import clean_lines

SERVER_NAME = 'batmud-bridge'
SERVER_VERSION = '0.1.0'
DEFAULT_PROTOCOL_VERSION = '2024-11-05'


def _schema(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': required or []}


def _int_schema(description, minimum=None, maximum=None):
    s = {'type': 'integer', 'description': description}
    if minimum is not None:
        s['minimum'] = minimum
    if maximum is not None:
        s['maximum'] = maximum
    return s


TOOLS = [
    {'name': 'batmud_status',
     'description': 'BatMUD bridge status: connection, session, latest_seq, rate limits.',
     'inputSchema': _schema({})},
    {'name': 'batmud_read',
     'description': 'Read new game output after a cursor. Default returns clean '
                    'logical lines (fragments rejoined, empty lines dropped, '
                    'duplicates collapsed, exits/chat/room-title classified). '
                    'Set raw=true for the raw event JSON.',
     'inputSchema': _schema({
         'after': _int_schema('return events with seq > this (default 0)'),
         'limit': _int_schema('max events per batch, 1..2000 (default 500)', 1, 2000),
         'wait_ms': _int_schema('long-poll up to this many ms if nothing new (0..10000)', 0, 10000),
         'raw': {'type': 'boolean', 'description': 'return raw events instead of clean lines'},
     })},
    {'name': 'batmud_send',
     'description': 'Dispatch ONE single-line game command. dispatched=true only '
                    'means the client accepted it; verify the output you read back. '
                    'Rate limited: burst 3 then 1 per 3s. A 429 result means the '
                    'command was NOT sent and names retry_after_ms; a timeout means '
                    'outcome unknown — never retry blindly.',
     'inputSchema': _schema({
         'command': {'type': 'string', 'description': 'single-line command, e.g. "look"'},
         'wait_s': _int_schema('seconds to collect output after dispatch (default 2)', 0, 30),
     }, ['command'])},
    {'name': 'kb_search',
     'description': 'Search the curated BatMUD knowledge notes (knowledge/, sources/, research/).',
     'inputSchema': _schema({
         'query': {'type': 'string', 'description': 'space-separated search terms'},
         'scope': {'type': 'string', 'enum': ['all', 'knowledge', 'sources', 'research']},
         'limit': _int_schema('max results (default 10)', 1, 50),
     }, ['query'])},
    {'name': 'kb_read',
     'description': 'Read one knowledge note by repo-relative path (e.g. '
                    'knowledge/merchant-guide.md). Path is guarded to the note dirs.',
     'inputSchema': _schema({
         'path': {'type': 'string'},
     }, ['path'])},
    {'name': 'kb_list',
     'description': 'List all knowledge note files.',
     'inputSchema': _schema({})},
]


class ToolError(Exception):
    """Becomes a tool result with isError=true."""


class McpServer(object):
    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self._client = None  # lazy BridgeClient

    def log(self, msg):
        sys.stderr.write('[batmud-mcp] %s\n' % msg)
        sys.stderr.flush()

    # ---- tool implementations (raise ToolError for isError results) ----

    def _bridge(self):
        if self._client is None:
            try:
                self._client = BridgeClient()
            except OSError as e:
                raise ToolError('bridge token unavailable: %s' % e)
        return self._client

    def tool_status(self, args):
        try:
            return json.dumps(self._bridge().status(), ensure_ascii=False)
        except BridgeConnectionError as e:
            raise ToolError(str(e))

    def tool_read(self, args):
        after = int(args.get('after', 0))
        limit = int(args.get('limit', 500))
        wait_ms = int(args.get('wait_ms', 0))
        raw = bool(args.get('raw', False))
        try:
            batch = self._bridge().read(after, limit, wait_ms)
        except BridgeConnectionError as e:
            raise ToolError(str(e))
        if raw:
            return json.dumps(batch, ensure_ascii=False)
        lines, stats = clean_lines(batch['events'])
        batch = dict(batch)
        batch['events'] = None
        batch['clean_lines'] = lines
        batch['stats'] = stats
        return json.dumps(batch, ensure_ascii=False)

    def tool_send(self, args):
        command = args.get('command')
        if not command or not isinstance(command, str):
            raise ToolError('command is required and must be a string')
        if '\n' in command or '\r' in command:
            raise ToolError('command must be a single line')
        wait_s = float(args.get('wait_s', 2))
        try:
            result = self._bridge().send(command, wait_s)
        except BridgeError as e:
            if e.code == 429:
                raise ToolError('rate limited: command NOT sent; retry after '
                                '%sms (burst 3, refill 3s)' % e.retry_after_ms)
            if e.code == 504:
                raise ToolError('dispatch timeout, outcome UNKNOWN — do not '
                                'retry blindly; read output first')
            raise ToolError('bridge %s: %s' % (e.code, json.dumps(e.body, ensure_ascii=False)))
        except BridgeConnectionError as e:
            raise ToolError(str(e))
        lines, stats = clean_lines(result['events'])
        return json.dumps({'dispatched': result['dispatch']['dispatched'],
                           'after_seq': result['dispatch']['after_seq'],
                           'clean_lines': lines, 'stats': stats}, ensure_ascii=False)

    def tool_kb_search(self, args):
        query = args.get('query')
        if not query or not isinstance(query, str):
            raise ToolError('query is required')
        scope = args.get('scope', 'all')
        if scope not in ('all', 'knowledge', 'sources', 'research'):
            raise ToolError('scope must be all/knowledge/sources/research')
        limit = int(args.get('limit', 10))
        return json.dumps(kb.search(query, scope=scope, limit=limit), ensure_ascii=False)

    def tool_kb_read(self, args):
        path = args.get('path')
        if not path or not isinstance(path, str):
            raise ToolError('path is required')
        try:
            return kb.read(path)
        except ValueError as e:
            raise ToolError(str(e))

    def tool_kb_list(self, args):
        return json.dumps(kb.list_notes(), ensure_ascii=False)

    HANDLERS = {
        'batmud_status': tool_status,
        'batmud_read': tool_read,
        'batmud_send': tool_send,
        'kb_search': tool_kb_search,
        'kb_read': tool_kb_read,
        'kb_list': tool_kb_list,
    }

    # ---- JSON-RPC plumbing ----

    def dispatch(self, msg):
        """Handle one decoded JSON-RPC message; return a response dict or None."""
        method = msg.get('method')
        msg_id = msg.get('id')
        is_notification = msg_id is None
        try:
            if method == 'initialize':
                requested = (msg.get('params') or {}).get('protocolVersion')
                return self._result(msg_id, {
                    'protocolVersion': requested or DEFAULT_PROTOCOL_VERSION,
                    'capabilities': {'tools': {'listChanged': False}},
                    'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
                })
            if method == 'notifications/initialized':
                return None
            if method == 'ping':
                return self._result(msg_id, {})
            if method == 'tools/list':
                return self._result(msg_id, {'tools': TOOLS})
            if method == 'tools/call':
                params = msg.get('params') or {}
                name = params.get('name')
                handler = self.HANDLERS.get(name)
                if handler is None:
                    if is_notification:
                        return None
                    return self._error(msg_id, -32602, 'unknown tool: %r' % name)
                try:
                    text = handler(self, params.get('arguments') or {})
                except ToolError as e:
                    return self._result(msg_id, {'content': [{'type': 'text', 'text': str(e)}],
                                                 'isError': True})
                except Exception:
                    self.log('tool %s crashed:\n%s' % (name, traceback.format_exc()))
                    return self._result(msg_id, {'content': [{'type': 'text',
                        'text': 'internal error in %s (see server log)' % name}],
                        'isError': True})
                return self._result(msg_id, {'content': [{'type': 'text', 'text': text}]})
            if not is_notification:
                return self._error(msg_id, -32601, 'method not found: %r' % method)
            return None
        except Exception:
            self.log('dispatch crashed:\n%s' % traceback.format_exc())
            if is_notification:
                return None
            return self._error(msg_id, -32603, 'internal error')

    @staticmethod
    def _result(msg_id, result):
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}

    @staticmethod
    def _error(msg_id, code, message):
        return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}

    def serve(self):
        for raw in self.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                self.stdout.write(json.dumps(self._error(None, -32700,
                        'parse error')) + '\n')
                self.stdout.flush()
                continue
            resp = self.dispatch(msg)
            if resp is not None:
                self.stdout.write(json.dumps(resp, ensure_ascii=False) + '\n')
                self.stdout.flush()


def main():
    # stdout is the protocol channel; never let prints leak into it
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', newline='\n')
    McpServer().serve()


if __name__ == '__main__':
    main()
