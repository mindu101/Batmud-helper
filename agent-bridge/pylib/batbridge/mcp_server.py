"""Minimal MCP (Model Context Protocol) stdio server exposing the bridge and KB.

Dependency-free implementation of the MCP stdio transport: newline-delimited
JSON-RPC 2.0 over stdin/stdout, everything else goes to stderr. Implements
the stable subset a desktop agent needs:

    initialize, notifications/initialized, ping, tools/list, tools/call

Tools:
    batmud_status()                          bridge connection/cursor state
    batmud_read(after, limit, wait_ms, raw)  clean logical lines (or raw events)
    batmud_send(command, wait_s)             dispatch + collect, 429 surfaced
    batmud_state()                           hp/sp/ep/cash/exp + room (state.json)
    find_word(word)                          where a word appeared in the buffer
    vocab_add(word, meaning_zh, ...)         write a 3-layer vocabulary entry
    map_route(to, from_room)                 BFS steps to a room (walked edges only)
    map_rooms(query)                         list known rooms
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
from pathlib import Path

from . import kb
from .client import BridgeClient, BridgeError, BridgeConnectionError
from .lines import clean_lines

# map_route/map_rooms/diary_write 的实现住在 tools/(mapper.py/diary.py)
_TOOLS_DIR = Path(__file__).resolve().parents[2] / 'tools'
if _TOOLS_DIR.is_dir() and str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

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
    {'name': 'batmud_state',
     'description': 'Current game state from state.json (needs state_watch.py '
                    'running): hp/sp/ep current+max, cash, exp, current room. '
                    'Fields stay null until observed — never fabricated.',
     'inputSchema': _schema({})},
    {'name': 'find_word',
     'description': 'Find where a word appeared in recent game output (for '
                    'vocabulary entries). Returns matching lines with seq. '
                    'If not in the buffer, ask the user for the sentence '
                    'instead of inventing a context.',
     'inputSchema': _schema({
         'word': {'type': 'string', 'description': 'the English word to find'},
     }, ['word'])},
    {'name': 'vocab_add',
     'description': 'Record a vocabulary entry into the 3-layer word book '
                    '(full md entry + English-only txt + bare words.txt). '
                    'meaning_zh should be the meaning IN THE GAME CONTEXT. '
                    'After writing, retell the entry to the user in Chinese.',
     'inputSchema': _schema({
         'word': {'type': 'string'},
         'meaning_zh': {'type': 'string', 'description': '中文语境义'},
         'meaning_en': {'type': 'string', 'description': 'English definition'},
         'phonetic': {'type': 'string'},
         'sentence': {'type': 'string', 'description': 'game sentence it appeared in'},
         'sentence_zh': {'type': 'string', 'description': '整句中文翻译'},
         'related': {'type': 'string'},
         'note': {'type': 'string'},
     }, ['word', 'meaning_zh'])},
    {'name': 'map_route',
     'description': 'Steps from the current room to a target room using only '
                    'edges actually walked (map.json from mapper.py record). '
                    'Show the steps to the user and get approval before '
                    'sending any movement command.',
     'inputSchema': _schema({
         'to': {'type': 'string', 'description': 'target room title (fuzzy ok)'},
         'from_room': {'type': 'string', 'description': 'start room (default: latest)'},
     }, ['to'])},
    {'name': 'map_rooms',
     'description': 'List known rooms (visits, walked edges).',
     'inputSchema': _schema({
         'query': {'type': 'string', 'description': 'filter by keyword'},
     })},
    {'name': 'diary_write',
     'description': 'Generate/refresh the daily diary section (XP delta, '
                    'commands, new words, map size, commits).',
     'inputSchema': _schema({
         'date': {'type': 'string', 'description': 'YYYY-MM-DD (default: today)'},
     })},
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

    def tool_batmud_state(self, args):
        from batbridge.state import GameState
        s = GameState.load()
        return json.dumps(dict(summary=s.summary_zh(), **s.as_dict()),
                          ensure_ascii=False)

    def tool_find_word(self, args):
        word = args.get('word')
        if not word or not isinstance(word, str):
            raise ToolError('word is required')
        try:
            client = self._bridge()
            st = client.status()
            batch = client.read(max(0, st['latest_seq'] - 2000), limit=2000)
        except BridgeConnectionError as e:
            raise ToolError('%s — 若用户刚才看到了这个词,请用户把原句发来,'
                            '不要凭空调用' % e)
        from batbridge.lines import clean_lines
        lines, _ = clean_lines(batch['events'])
        hits = [l for l in lines if word.lower() in l['text'].lower()]
        if not hits:
            return json.dumps({'found': False,
                               'hint': '当前缓冲(2000 条)里没有这个词;'
                                       '问用户要原句,不要编造出处'},
                              ensure_ascii=False)
        return json.dumps({'found': True, 'matches': [
            {'seq': l['seq_start'], 'kind': l['kind'], 'text': l['text']}
            for l in hits[-10:]]}, ensure_ascii=False)

    def tool_vocab_add(self, args):
        from batbridge import vocab
        word, meaning_zh = args.get('word'), args.get('meaning_zh')
        if not word or not isinstance(word, str) or not meaning_zh:
            raise ToolError('word 与 meaning_zh 必填')
        try:
            r = vocab.add_entry(
                word, meaning_zh=meaning_zh,
                meaning_en=args.get('meaning_en', ''),
                phonetic=args.get('phonetic', ''),
                sentence=args.get('sentence', ''),
                sentence_zh=args.get('sentence_zh', ''),
                related=args.get('related', ''),
                note=args.get('note', ''))
        except ValueError as e:
            raise ToolError(str(e))
        return json.dumps(dict(r, note='已写入三层单词本;'
                                       '请把词条内容用中文向用户复述一遍'),
                          ensure_ascii=False)

    def tool_map_route(self, args):
        import mapper
        to = args.get('to')
        if not to or not isinstance(to, str):
            raise ToolError('to is required')
        state = mapper.MapState.load()
        if not state.rooms:
            raise ToolError('map.json 为空:先跑 tools/mapper.py record 走几个房间')
        to_id = mapper.room_id(to)
        matches = [rid for rid in state.rooms if rid == to_id or to_id in rid]
        if not matches:
            raise ToolError('地图里没有 %r;可用 map_rooms 查已记录的房间' % to)
        to_id = matches[0]
        frm = args.get('from_room')
        from_id = mapper.room_id(frm) if frm else state.latest_room()
        if from_id not in state.rooms:
            raise ToolError('起点不在地图里: %r' % frm)
        steps = state.route(from_id, to_id)
        if steps is None:
            raise ToolError('暂时走不到(还没学到这条路):%s -> %s'
                            % (state.rooms[from_id]['title'],
                               state.rooms[to_id]['title']))
        cur, path = from_id, []
        for i, d in enumerate(steps, 1):
            cur = state.edges[cur][d]
            path.append('%d. %s -> %s' % (i, d, state.rooms[cur]['title']))
        return json.dumps({'from': state.rooms[from_id]['title'],
                           'to': state.rooms[to_id]['title'],
                           'steps': steps, 'detail': path,
                           'note': '展示给用户并取得同意后,逐步发送,'
                                   '每步读回输出确认房间变化'},
                          ensure_ascii=False)

    def tool_map_rooms(self, args):
        import mapper
        state = mapper.MapState.load()
        query = (args.get('query') or '').lower()
        out = []
        for rid, r in sorted(state.rooms.items(),
                             key=lambda kv: -kv[1]['visits'])[:50]:
            if query and query not in r['title'].lower():
                continue
            out.append({'title': r['title'], 'visits': r['visits'],
                        'exits': r['exits'],
                        'edges': {d: state.rooms[t]['title']
                                  for d, t in state.edges.get(rid, {}).items()}})
        return json.dumps({'count': len(state.rooms), 'rooms': out},
                          ensure_ascii=False)

    def tool_diary_write(self, args):
        import time as _time

        import diary
        date = args.get('date') or _time.strftime('%Y-%m-%d')
        lo, hi = diary.day_bounds(date)
        cmds = diary.commands_of_day(diary.AUDIT_PATH, lo, hi)
        try:
            vocab_text = diary.VOCAB_PATH.read_text(encoding='utf-8')
        except OSError:
            vocab_text = ''
        words = diary.words_of_day(vocab_text, date)
        rooms, edges = diary.map_snapshot()
        commits = diary.git_commits(date)
        exp = diary.exp_of_day(None)
        section = diary.build_section(date, cmds, words, rooms, edges,
                                      commits, exp)
        action = diary.write_diary(section, date)
        return json.dumps({'action': action, 'section': section},
                          ensure_ascii=False)

    HANDLERS = {
        'batmud_status': tool_status,
        'batmud_read': tool_read,
        'batmud_send': tool_send,
        'kb_search': tool_kb_search,
        'kb_read': tool_kb_read,
        'kb_list': tool_kb_list,
        'batmud_state': tool_batmud_state,
        'find_word': tool_find_word,
        'vocab_add': tool_vocab_add,
        'map_route': tool_map_route,
        'map_rooms': tool_map_rooms,
        'diary_write': tool_diary_write,
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
