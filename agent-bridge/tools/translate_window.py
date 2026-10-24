#!/usr/bin/env python3
"""双语跟随窗:实时滚动游戏画面,英文原文 + DeepSeek 中文翻译。

用法(另开一个终端窗口跑着即可):
    export DEEPSEEK_API_KEY=sk-xxxx        # 或把 key 存进 ~/.deepseek_api_key
    python3 agent-bridge/tools/translate_window.py

行为:
- 跟随桥的事件流(长轮询),先做行重组/去噪(lines.py),
  打印 "EN│ 原文" 与 "中│ 译文" 两行。
- hp/sp/ep/cash/exp 状态行本地格式化成中文,不花 API。
- 已翻译过的行走缓存,不重复花钱;渠道闲聊重复刷屏基本零成本。
- 批量翻译:安静 ~1.2 秒或攒满 15 行才发一次请求;API 挂了不挡画面,
  原文照常显示并给出提示,退避后自动重试新内容。
- Ctrl-C 退出。参数:--after N 从指定 seq 开始(默认从当前最新开始)。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))

from batbridge.client import BridgeClient, BridgeConnectionError
from batbridge.lines import clean_lines

API_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/') + '/chat/completions'
MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-flash')  # DeepSeek-V4.1-Flash
BATCH_QUIET_S = 1.2     # 无新行持续多久就翻译
MAX_BATCH = 8           # 单次请求最多行数(小批次更快返回,不易超时)
MAX_PENDING = 45        # 失败重试期间最多积压的行数,超出则最旧的以"暂缺"落地
CACHE_MAX = 1000        # 行级翻译缓存上限(FIFO 淘汰)
API_TIMEOUT = 30
BACKOFF_S = 5           # API 失败后的退避

SYSTEM_PROMPT = (
    '你是文字网游 BatMUD 的画面翻译助手。用户给你一个 JSON 数组,'
    '每项是一行游戏英文原文。把每一行翻成自然的简体中文,保留人名/地名,'
    '游戏黑话给通行中文说法。若输入末尾附有"术语表",译名必须与术语表完全一致。'
    '译文保持简洁,不要添加注释或原文。'
    '只输出一个 JSON 数组,第 i 项对应第 i 行的译文,'
    '不要输出任何其他文字或代码块标记。'
)
# 本提示词保持字节级稳定:DeepSeek 前缀缓存自动生效,命中部分约 1/10 价;
# 会变的内容(待翻行、术语表)全部放 user 消息,术语表固定放末尾。

# 无字母的行(纯符号/数字/ASCII art)与已知协议杂音:不显示不翻译
_JUNK_RE = re.compile(r'^[\W_0-9]*$', re.UNICODE)
KNOWN_JUNK = {'nomapsupport'}

USAGE_PATH = Path.home() / '.deepseek_usage.json'
GLOSSARY_REFRESH_FLUSHES = 50   # 每翻译多少批后重读单词本,学到新词能生效

_STATUS_RE = re.compile(
    r'^hp: (\d+) \(\d+\).*?sp: (\d+) \(\d+\).*?ep: (\d+) \(\d+\).*?'
    r'cash: (\d+).*?exp: (\d+)')


def load_key():
    """DEEPSEEK_API_KEY 环境变量,或 ~/.deepseek_api_key 文件。"""
    key = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    if key:
        return key
    f = Path.home() / '.deepseek_api_key'
    if f.exists():
        return f.read_text().strip()
    return ''


def format_status_zh(text):
    """hp/sp/ep/cash/exp 状态行 -> 中文状态条(本地完成,不调 API)。"""
    m = _STATUS_RE.search(text)
    if not m:
        return None
    hp, sp, ep, cash, exp = m.groups()
    return '血 %s | 法 %s | 精 %s | 钱 %s | 经验 %s' % (hp, sp, ep, cash, exp)


def parse_translations(content, n):
    """从模型回复里解析长度为 n 的译文数组;失败返回 None。"""
    try:
        data = json.loads(content)
    except ValueError:
        return None
    if not isinstance(data, list) or len(data) != n:
        return None
    return [x if isinstance(x, str) else str(x) for x in data]


def build_user_content(lines, glossary=None):
    """待翻行在前,命中的术语表附在末尾(保持前缀尽量稳定)。"""
    content = json.dumps(lines, ensure_ascii=False)
    if glossary:
        content += '\n术语表:' + json.dumps(glossary, ensure_ascii=False)
    return content


def is_junk(text):
    """无字母/已知协议杂音:不值得看也不值得翻译。"""
    t = text.strip()
    return t.lower() in KNOWN_JUNK or bool(_JUNK_RE.match(t))


class UsageTracker(object):
    """累计 DeepSeek usage(含缓存命中),落盘 ~/.deepseek_usage.json。"""

    def __init__(self, path=None):
        self.path = Path(path or USAGE_PATH)
        self.totals = {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
                       'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 0}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.totals.update({k: v for k, v in data.items() if k in self.totals})
        except (OSError, ValueError):
            pass

    def add(self, usage):
        self.totals['calls'] += 1
        for k in ('prompt_tokens', 'completion_tokens',
                  'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'):
            self.totals[k] += int(usage.get(k) or 0)
        try:
            self.path.write_text(json.dumps(self.totals), encoding='utf-8')
        except OSError:
            pass

    def summary(self):
        t = self.totals
        hit = t['prompt_cache_hit_tokens']
        prompt = t['prompt_tokens'] or (hit + t['prompt_cache_miss_tokens'])
        pct = ('%d%%' % (100.0 * hit / prompt)) if prompt else 'n/a'
        return ('翻译 API 累计:%d 次调用,输入 %d tokens(缓存命中 %d,%s),'
                '输出 %d tokens' % (t['calls'], prompt, hit, pct,
                                    t['completion_tokens']))


def call_api(lines, key, post=None, glossary=None, on_usage=None):
    """翻一批行;post/on_usage 可注入以便测试。返回译文列表或抛异常。"""
    post = post or _http_post_json
    payload = {
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': build_user_content(lines, glossary)},
        ],
        'temperature': 0.3,
        'stream': False,
    }
    body = post(API_URL, payload, key)
    if on_usage is not None:
        try:
            on_usage(body.get('usage') or {})
        except Exception:
            pass
    content = body['choices'][0]['message']['content']
    result = parse_translations(content, len(lines))
    if result is None:
        raise ValueError('模型回复不是合法的译文数组: %r' % content[:200])
    return result


def _make_opener():
    """直连(不走系统代理);有 certifi 就带上其 CA 包
    (python.org 的 macOS Python 3.8 不带系统证书,curl 正常而 urllib 报
    self signed certificate in certificate chain 即此因)。"""
    handlers = [urllib.request.ProxyHandler({})]
    try:
        import ssl

        import certifi
        handlers.append(urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=certifi.where())))
    except ImportError:
        pass
    return urllib.request.build_opener(*handlers)


def _http_post_json(url, payload, key):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + key,
                 'Content-Type': 'application/json'})
    with _make_opener().open(req, timeout=API_TIMEOUT) as res:
        return json.loads(res.read().decode('utf-8'))


class TranslationCache(dict):
    """dict + FIFO 淘汰;重复行(渠道刷屏)命中缓存不再花钱。"""

    def __init__(self, max_entries=CACHE_MAX):
        super().__init__()
        self.max_entries = max_entries

    def put(self, k, v):
        if len(self) >= self.max_entries:
            self.pop(next(iter(self)))
        self[k] = v


def emit(out, text_zh, text_en):
    out.write('中│ %s\n' % text_zh)
    if text_en is not None:
        out.write('EN│ %s\n' % text_en)
    out.flush()


def run(client, out, key, post=None, after=None, sleep=time.sleep, stop=None,
        usage=None):
    """主循环;client/out/post/sleep/stop/usage 均可注入以便测试。"""
    from batbridge import vocab

    cache = TranslationCache()
    usage = usage if usage is not None else UsageTracker()
    glossary = vocab.load_glossary()
    flush_count = [0]

    def batch_glossary(texts):
        """只注入本批行里出现的术语:一致性更好且省 token。"""
        return vocab.filter_glossary(glossary, '\n'.join(texts))

    if after is None:
        after = client.status()['latest_seq']
    pending = []          # 待翻译的干净行
    last_new_ts = time.time()
    api_down_until = 0

    def flush_pending():
        nonlocal api_down_until
        if not pending:
            return
        if time.time() < api_down_until:
            # 退避中:整批保留待重试;积压过多时最旧的先落地,避免窗口滞后
            while len(pending) > MAX_PENDING:
                entry = pending.pop(0)
                emit(out, '(翻译暂缺) ' + entry['text'], entry['text'])
            return
        texts = [e['text'] for e in pending]
        try:
            translations = call_api(texts, key, post,
                                    glossary=batch_glossary(texts),
                                    on_usage=usage.add)
        except Exception as e:
            api_down_until = time.time() + BACKOFF_S
            out.write('— 翻译服务异常(%s),保留 %d 行待重试,退避 %ds:%s\n'
                      % (type(e).__name__, len(pending), BACKOFF_S, e))
            out.flush()
            return  # 不丢批次:退避结束后原批重试
        for entry, zh in zip(pending, translations):
            cache.put(entry['text'], zh)
            emit(out, zh, entry['text'])
        del pending[:]
        flush_count[0] += 1
        if flush_count[0] % GLOSSARY_REFRESH_FLUSHES == 0:
            glossary.update(vocab.load_glossary())  # 学到新词后生效

    while stop is None or not stop():
        try:
            batch = client.read(after, wait_ms=1000)
        except BridgeConnectionError as e:
            out.write('— 桥不可达(客户端没开或已退出):%s\n' % e)
            out.flush()
            sleep(3)
            continue
        events = batch.get('events', [])
        if events:
            after = events[-1]['seq']
            lines, _ = clean_lines(events)
            for entry in lines:
                text = entry['text']
                if text.startswith('hp: ') and format_status_zh(text):
                    emit(out, format_status_zh(text), None)  # 状态条本地中文化
                elif is_junk(text):
                    continue                                 # 杂线:不显示不翻译
                elif text in cache:
                    emit(out, cache[text], text)
                else:
                    pending.append(entry)
            last_new_ts = time.time()
        quiet = time.time() - last_new_ts >= BATCH_QUIET_S
        if pending and (quiet or len(pending) >= MAX_BATCH):
            flush_pending()
        sleep(0.2)  # 每轮固定小睡:退避挂起期间时钟/节奏也能推进


def main():
    ap = argparse.ArgumentParser(description='BatMUD 双语跟随窗(DeepSeek 翻译)')
    ap.add_argument('--after', type=int, default=None, help='从指定 seq 开始(默认当前最新)')
    a = ap.parse_args()
    key = load_key()
    if not key:
        sys.stderr.write(
            '未找到 DeepSeek API key。\n'
            '  方式一:export DEEPSEEK_API_KEY=sk-xxxx\n'
            '  方式二:把 key 写入 ~/.deepseek_api_key 文件\n')
        return 2
    try:
        client = BridgeClient()
    except OSError as e:
        sys.stderr.write('桥 token 不可读: %s\n' % e)
        return 2
    try:
        run(client, sys.stdout, key, after=a.after)
    except KeyboardInterrupt:
        pass
    sys.stderr.write(UsageTracker().summary() + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
