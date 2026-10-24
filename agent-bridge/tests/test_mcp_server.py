#!/usr/bin/env python3
"""E2E test for the MCP stdio server: real process, real stdio JSON-RPC.

Spawns `python3 -m batbridge.mcp_server` with BATBRIDGE_PORT pointing at a
BridgeHarness on 18766, then drives the protocol like a desktop client:
initialize -> initialized -> tools/list -> tools/call (kb + bridge tools),
including the isError paths (guarded kb read, rate limit, connection error).
"""
import json, os, pathlib, queue, subprocess, sys, tempfile, threading, time, unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
BRIDGE = ROOT / 'agent-bridge'
PYLIB = str(BRIDGE / 'pylib')
sys.path.insert(0, PYLIB)

api = ROOT / 'downloads/bat_interfaces.jar'
api_cp = api if api.exists() else BRIDGE / 'build-stubs-compiled'
CP = ':'.join(str(x) for x in [api_cp, BRIDGE / 'build', BRIDGE / 'tests'])
JAVA = pathlib.Path(subprocess.check_output(['/usr/libexec/java_home']).decode().strip()) / 'bin' / 'java'
PORT = 18766
PY = sys.executable

ID = [0]


class McpProc(object):
    def __init__(self, env_extra):
        self.proc = subprocess.Popen(
            [PY, '-m', 'batbridge.mcp_server'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, 'PYTHONPATH': PYLIB, **env_extra}, text=True)
        self.q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            self.q.put(json.loads(line))

    def request(self, method, params=None, timeout=15, notification=False):
        msg = {'jsonrpc': '2.0', 'method': method}
        if not notification:
            ID[0] += 1
            msg['id'] = ID[0]
        if params is not None:
            msg['params'] = params
        self.proc.stdin.write(json.dumps(msg) + '\n')
        self.proc.stdin.flush()
        if notification:
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = self.q.get(timeout=deadline - time.time())
            except queue.Empty:
                raise AssertionError('timeout waiting for response to %s' % method)
            if resp.get('id') == msg['id']:
                return resp
        raise AssertionError('timeout')

    def call(self, tool, args=None):
        resp = self.request('tools/call', {'name': tool, 'arguments': args or {}})
        result = resp['result']
        text = result['content'][0]['text']
        return result, text

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.wait(timeout=5)


class TestMcpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.harness = subprocess.Popen(
            [str(JAVA), '-Djava.awt.headless=true', '-Dbatbridge.port=%d' % PORT,
             '-Dbatbridge.rate.burst=20', '-cp', CP, 'BridgeHarness', cls.tmp.name],
            stdout=subprocess.DEVNULL)
        tokenfile = pathlib.Path(cls.tmp.name) / 'agent-bridge/token.txt'
        for _ in range(100):
            if tokenfile.exists():
                break
            time.sleep(.05)
        cls.env = {'BATBRIDGE_PORT': str(PORT),
                   'BATBRIDGE_TOKEN_FILE': str(tokenfile)}

    @classmethod
    def tearDownClass(cls):
        cls.harness.terminate()
        cls.harness.wait(timeout=5)
        cls.tmp.cleanup()

    def setUp(self):
        self.mcp = McpProc(self.env)
        resp = self.mcp.request('initialize', {
            'protocolVersion': '2025-06-18',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '0'}})
        self.assertEqual(resp['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(resp['result']['serverInfo']['name'], 'batmud-bridge')
        self.mcp.request('notifications/initialized', notification=True)

    def tearDown(self):
        self.mcp.close()

    def test_tools_list(self):
        resp = self.mcp.request('tools/list')
        names = [t['name'] for t in resp['result']['tools']]
        self.assertEqual(names, ['batmud_status', 'batmud_read', 'batmud_send',
                                 'kb_search', 'kb_read', 'kb_list',
                                 'batmud_state', 'find_word', 'vocab_add',
                                 'map_route', 'map_rooms', 'diary_write'])
        for t in resp['result']['tools']:
            self.assertEqual(t['inputSchema']['type'], 'object')

    def test_status_read_send_roundtrip(self):
        _, text = self.mcp.call('batmud_status')
        self.assertIn('"version": "0.4.0"', text)

        _, text = self.mcp.call('batmud_send', {'command': 'look', 'wait_s': 2})
        payload = json.loads(text)
        self.assertTrue(payload['dispatched'])
        self.assertTrue(any(l['text'] == 'ROOM: look' for l in payload['clean_lines']))

        _, text = self.mcp.call('batmud_read', {'after': 0, 'limit': 10})
        payload = json.loads(text)
        self.assertTrue(payload['clean_lines'])
        self.assertIsNone(payload['events'])

        # the harness fires the unicode event ~3s after plugin startup; poll
        payload = None
        for _ in range(80):
            _, text = self.mcp.call('batmud_read', {'after': 0, 'raw': True, 'limit': 500})
            payload = json.loads(text)
            if any('中文' in e['text'] for e in payload['events']):
                break
            time.sleep(.05)
        self.assertTrue(any('中文' in e['text'] for e in payload['events']))

    def test_send_multiline_rejected_via_isError(self):
        result, text = self.mcp.call('batmud_send', {'command': 'look\nscore'})
        self.assertTrue(result['isError'])
        self.assertIn('single line', text)

    def test_kb_tools(self):
        _, text = self.mcp.call('kb_search', {'query': 'merchant shopkeeping',
                                              'scope': 'knowledge'})
        self.assertIn('knowledge/merchant-guide.md', text)
        _, text = self.mcp.call('kb_read', {'path': 'knowledge/merchant-guide.md'})
        self.assertIn('# Merchant Career Guide', text)
        result, text = self.mcp.call('kb_read', {'path': '../../etc/passwd'})
        self.assertTrue(result['isError'])
        _, text = self.mcp.call('kb_list')
        self.assertIn('knowledge/merchant-guide.md', text)

    def test_unknown_tool_is_jsonrpc_error(self):
        resp = self.mcp.request('tools/call', {'name': 'nope', 'arguments': {}})
        self.assertEqual(resp['error']['code'], -32602)

    def test_ping_and_unknown_method(self):
        resp = self.mcp.request('ping')
        self.assertEqual(resp['result'], {})
        resp = self.mcp.request('resources/list')
        self.assertEqual(resp['error']['code'], -32601)


class TestNewToolsWithSandbox(unittest.TestCase):
    """vocab/map/state/diary 工具走沙箱记忆目录,不碰真实文件。"""

    @classmethod
    def setUpClass(cls):
        cls.mem = tempfile.TemporaryDirectory()
        cls.audit = tempfile.TemporaryDirectory()
        # 自带一个 harness(独立于 TestMcpServer 的那个,端口相同但串行运行)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.harness = subprocess.Popen(
            [str(JAVA), '-Djava.awt.headless=true', '-Dbatbridge.port=%d' % PORT,
             '-cp', CP, 'BridgeHarness', cls.tmp.name],
            stdout=subprocess.DEVNULL)
        tokenfile = pathlib.Path(cls.tmp.name) / 'agent-bridge/token.txt'
        for _ in range(100):
            if tokenfile.exists():
                break
            time.sleep(.05)
        # 等中文事件出现(find_word 测试依赖)
        for _ in range(60):
            try:
                from batbridge.client import BridgeClient
                c = BridgeClient(port=PORT, token=tokenfile.read_text().strip())
                if any('world' in e['text'] for e in c.read(0)['events']):
                    break
            except Exception:
                pass
            time.sleep(.1)
        # 沙箱审计日志:今天一条 look
        import time as _t
        today = _t.strftime('%Y-%m-%d')
        lo = int(_t.mktime(_t.strptime(today, '%Y-%m-%d')) * 1000)
        pathlib.Path(cls.audit.name, 'command-log.jsonl').write_text(
            json.dumps({'time_ms': lo + 1000, 'command': 'look',
                        'after_seq': 0}) + '\n', encoding='utf-8')
        cls.env = {'BATBRIDGE_PORT': str(PORT),
                   'BATBRIDGE_TOKEN_FILE': str(tokenfile),
                   'BATBRIDGE_MEMORY_DIR': cls.mem.name,
                   'BATBRIDGE_AUDIT': str(
                       pathlib.Path(cls.audit.name) / 'command-log.jsonl')}

    @classmethod
    def tearDownClass(cls):
        cls.harness.terminate()
        cls.harness.wait(timeout=5)
        cls.tmp.cleanup()
        cls.mem.cleanup()
        cls.audit.cleanup()

    def setUp(self):
        self.mcp = McpProc(self.env)
        self.mcp.request('initialize', {'protocolVersion': '2025-06-18',
                                        'capabilities': {}})
        self.mcp.request('notifications/initialized', notification=True)

    def tearDown(self):
        self.mcp.close()

    def test_vocab_add_writes_three_layers(self):
        result, text = self.mcp.call('vocab_add', {
            'word': 'zombie', 'meaning_zh': '僵尸',
            'meaning_en': 'a reanimated corpse',
            'sentence': 'A zombie shambles north.',
            'sentence_zh': '一只僵尸蹒跚着向北走去。'})
        self.assertFalse(result.get('isError'), text)
        md = (pathlib.Path(self.env['BATBRIDGE_MEMORY_DIR'])
              / 'vocabulary.md').read_text(encoding='utf-8')
        self.assertIn('### zombie', md)
        self.assertIn('僵尸', md)
        words = (pathlib.Path(self.env['BATBRIDGE_MEMORY_DIR'])
                 / 'words.txt').read_text(encoding='utf-8')
        self.assertIn('zombie', words.split())
        # 必填缺失 -> isError
        result, text = self.mcp.call('vocab_add', {'word': 'x'})
        self.assertTrue(result['isError'])

    def test_state_and_map_tools(self):
        _, text = self.mcp.call('batmud_state')
        payload = json.loads(text)
        self.assertIsNone(payload['hp'])
        self.assertIn('位置未知', payload['summary'])
        result, text = self.mcp.call('map_route', {'to': 'nowhere'})
        self.assertTrue(result['isError'])            # 空地图如实报错
        _, text = self.mcp.call('map_rooms', {})
        self.assertEqual(json.loads(text)['count'], 0)

    def test_find_word_against_harness(self):
        _, text = self.mcp.call('find_word', {'word': 'world'})
        payload = json.loads(text)
        self.assertTrue(payload['found'])
        self.assertIn('hello', payload['matches'][0]['text'])
        result, text = self.mcp.call('find_word', {'word': 'zzz_nothing'})
        payload = json.loads(text)
        self.assertFalse(payload['found'])
        self.assertIn('不要编造', payload['hint'])

    def test_diary_write_sandbox(self):
        _, text = self.mcp.call('diary_write', {})
        payload = json.loads(text)
        self.assertIn('look', payload['section'])
        diary_file = pathlib.Path(self.env['BATBRIDGE_MEMORY_DIR']) / 'diary.md'
        self.assertTrue(diary_file.exists())

    def test_tools_list_has_all_twelve(self):
        resp = self.mcp.request('tools/list')
        names = [t['name'] for t in resp['result']['tools']]
        self.assertEqual(names, [
            'batmud_status', 'batmud_read', 'batmud_send',
            'kb_search', 'kb_read', 'kb_list',
            'batmud_state', 'find_word', 'vocab_add',
            'map_route', 'map_rooms', 'diary_write'])


class TestMcpWithoutBridge(unittest.TestCase):
    def test_bridge_tools_report_isError_when_client_down(self):
        mcp = McpProc({'BATBRIDGE_PORT': '18999',
                       'BATBRIDGE_TOKEN_FILE': os.devnull})
        try:
            mcp.request('initialize', {'protocolVersion': '2025-06-18',
                                       'capabilities': {}})
            mcp.request('notifications/initialized', notification=True)
            result, text = mcp.call('batmud_status')
            self.assertTrue(result['isError'])
            self.assertIn('cannot reach AgentBridge', text)
        finally:
            mcp.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
