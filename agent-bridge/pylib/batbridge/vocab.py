"""Vocabulary notebook writer/reader shared by the MCP server and tools.

Three-layer storage under agent/memory/:
  vocabulary.md   full entries (读音/词性/语境义/原句翻译/相关词/场景记忆)
  vocabulary.txt  `word - English meaning`, one per line, alphabetical
  words.txt       bare word per line, alphabetical

add_entry() keeps all three consistent (date section at top in the .md,
alphabetical insert/dedupe in the txts). load_glossary() returns a
word -> Chinese meaning map (语境义 preferred) for translation consistency.
"""

import os
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # pylib/batbridge
# 记忆根目录可用 BATBRIDGE_MEMORY_DIR 覆盖(测试沙箱/多实例)
MEMORY = Path(os.environ.get('BATBRIDGE_MEMORY_DIR')
              or HERE.parents[1] / 'agent' / 'memory')
MD_PATH = MEMORY / 'vocabulary.md'
TXT_PATH = MEMORY / 'vocabulary.txt'
WORDS_PATH = MEMORY / 'words.txt'


def _ensure_files():
    MEMORY.mkdir(parents=True, exist_ok=True)
    if not MD_PATH.exists():
        MD_PATH.write_text(
            '# 单词本(玩家专属,供回顾)\n\n'
            '> 给用户:聊天里直接发一个词,副驾驶就会整理成词条存档。\n'
            '> 给 agent:用 batbridge.vocab.add_entry 写入,勿手改三份文件的\n'
            '> 一致性规则。\n\n---\n', encoding='utf-8')
    if not TXT_PATH.exists():
        TXT_PATH.write_text(
            'English-only word list (one line per word: word - meaning).\n'
            'Companion to vocabulary.md; kept alphabetical; no Chinese, '
            'no context here.\n\n', encoding='utf-8')
    if not WORDS_PATH.exists():
        WORDS_PATH.write_text('', encoding='utf-8')


def _md_entry(word, phonetic, meaning_zh, meaning_en, sentence, sentence_zh,
              related, note):
    parts = ['### %s' % word]
    if phonetic:
        parts.append('- **读音**:%s' % phonetic)
    parts.append('- **词性/释义(中文)**:%s' % meaning_zh)
    if meaning_en:
        parts.append('- **英文释义**:%s' % meaning_en)
    if sentence:
        src = '- **原句**:`%s`' % sentence
        if sentence_zh:
            src += '\n  翻译:%s' % sentence_zh
        parts.append(src)
    if related:
        parts.append('- **相关词**:%s' % related)
    if note:
        parts.append('- **备注**:%s' % note)
    return '\n'.join(parts) + '\n'


def _alpha_insert(path, line, key):
    """按 key 字母序插入/原位更新一行;返回是否发生变化。
    TXT 文件里含 ' - ' 的行才是词条(前两行是说明);WORDS 文件每行都是词。"""
    is_words_file = path == WORDS_PATH
    lines = path.read_text(encoding='utf-8').splitlines()
    out, inserted, replaced, changed = [], False, False, False
    for ln in lines:
        is_entry = (ln.strip() != '' and (is_words_file or ' - ' in ln))
        if is_entry:
            cur_key = (ln if is_words_file else ln.split(' - ')[0]).strip().lower()
            if cur_key == key:
                replaced = True
                if ln != line:
                    out.append(line)
                    changed = True
                else:
                    out.append(ln)
                continue
            if not inserted and not replaced and cur_key > key:
                out.append(line)
                inserted = changed = True
        out.append(ln)
    if not inserted and not replaced:
        # 没找到位置(比所有词都大):追加到最后一个词条行之后
        last_entry = max((i for i, l in enumerate(out)
                          if l.strip() and (is_words_file or ' - ' in l)),
                         default=-1)
        out.insert(last_entry + 1, line)
        changed = True
    if changed:
        path.write_text('\n'.join(out) + '\n', encoding='utf-8')
    return changed


def add_entry(word, meaning_zh, meaning_en='', phonetic='', sentence='',
              sentence_zh='', related='', note='', date=None):
    """Write one vocabulary entry into all three files. Idempotent for the
    txt layers (same word updates in place); the .md always appends the
    entry under its date section (a word can be re-learned in new contexts).
    """
    word = word.strip()
    if not word or '\n' in word:
        raise ValueError('bad word: %r' % word)
    _ensure_files()
    date = date or time.strftime('%Y-%m-%d')

    md = MD_PATH.read_text(encoding='utf-8')
    entry = _md_entry(word, phonetic, meaning_zh, meaning_en, sentence,
                      sentence_zh, related, note)
    section = '## %s' % date
    if section in md:
        md = md.replace(section + '\n', section + '\n\n' + entry, 1)
    else:
        md = md.rstrip('\n') + '\n\n' + section + '\n\n' + entry
    MD_PATH.write_text(md, encoding='utf-8')

    if meaning_en:
        _alpha_insert(TXT_PATH, '%s - %s' % (word, meaning_en), word.lower())
    _alpha_insert(WORDS_PATH, word, word.lower())
    return {'word': word, 'date': date}


_ENTRY_RE = re.compile(r'^### (.+?)\s*$', re.M)
# 兼容两种格式:手写旧版"这句话里的意思"与 add_entry 新版"词性/释义(中文)"
_MEANING_RE = re.compile(
    r'^- \*\*(?:词性/释义\(中文\)|这句话里的意思)\*\*:(.+)$', re.M)


def load_glossary(path=None):
    """word -> Chinese meaning map from vocabulary.md (最新一条优先),
    供翻译术语一致性使用。"""
    p = Path(path or MD_PATH)
    if not p.exists():
        return {}
    text = p.read_text(encoding='utf-8')
    glossary = {}
    for m in _ENTRY_RE.finditer(text):
        word = m.group(1).strip()
        seg = text[m.end():]
        nxt = _ENTRY_RE.search(seg)
        seg = seg[:nxt.start()] if nxt else seg
        mm = _MEANING_RE.search(seg)
        meaning = mm.group(1).strip() if mm else ''
        if word and meaning:
            glossary[word] = meaning.split(';')[0].strip()  # 取第一义项
    return glossary


def filter_glossary(glossary, lines_text):
    """只保留真正出现在这批行里的词(词边界匹配,大小写不敏感),
    省 token 且不影响一致性。"""
    hits = {}
    low = lines_text.lower()
    for word, meaning in glossary.items():
        if re.search(r'\b%s\b' % re.escape(word.lower()), low):
            hits[word] = meaning
    return hits
