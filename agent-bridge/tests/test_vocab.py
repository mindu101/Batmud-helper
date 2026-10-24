#!/usr/bin/env python3
"""Unit tests for batbridge.vocab (three-layer word book)."""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pylib'))
from batbridge import vocab


class VocabSandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name)
        self._paths = vocab.MD_PATH, vocab.TXT_PATH, vocab.WORDS_PATH
        vocab.MD_PATH = self.mem / 'vocabulary.md'
        vocab.TXT_PATH = self.mem / 'vocabulary.txt'
        vocab.WORDS_PATH = self.mem / 'words.txt'
        vocab.MEMORY = self.mem

    def tearDown(self):
        vocab.MD_PATH, vocab.TXT_PATH, vocab.WORDS_PATH = self._paths
        vocab.MEMORY = vocab.MD_PATH.parents[0]
        self.tmp.cleanup()

    def test_add_entry_writes_three_layers(self):
        vocab.add_entry('portcullis', meaning_zh='铁闸门',
                        meaning_en='iron grating over a castle gateway',
                        phonetic='/ˈpɔːtkʌlɪs/',
                        sentence='Iron portcullis (closed) leads south.',
                        sentence_zh='一道铁闸门(关着)通向南方。',
                        related='gate; drawbridge', date='2026-10-24')
        md = vocab.MD_PATH.read_text(encoding='utf-8')
        self.assertIn('### portcullis', md)
        self.assertIn('## 2026-10-24', md)
        self.assertIn('铁闸门', md)
        txt = vocab.TXT_PATH.read_text(encoding='utf-8')
        self.assertIn('portcullis - iron grating over a castle gateway', txt)
        words = vocab.WORDS_PATH.read_text(encoding='utf-8')
        self.assertEqual(words.strip(), 'portcullis')

    def test_alphabetical_order_and_dedupe(self):
        vocab.add_entry('zombie', meaning_zh='僵尸', date='2026-10-24')
        vocab.add_entry('apple', meaning_zh='苹果', date='2026-10-24')
        vocab.add_entry('portcullis', meaning_zh='铁闸门', date='2026-10-24')
        vocab.add_entry('apple', meaning_zh='苹果(公司/果实)', date='2026-10-24')
        words = [l for l in vocab.WORDS_PATH.read_text(encoding='utf-8').splitlines() if l.strip()]
        self.assertEqual(words, ['apple', 'portcullis', 'zombie'])
        # md 里同词两次学习是允许的(新语境),txt/words 去重
        md = vocab.MD_PATH.read_text(encoding='utf-8')
        self.assertEqual(md.count('### apple'), 2)

    def test_glossary_load_and_filter(self):
        vocab.add_entry('portcullis', meaning_zh='铁闸门', date='2026-10-24')
        vocab.add_entry('dryad', meaning_zh='树妖', date='2026-10-24')
        g = vocab.load_glossary()
        self.assertEqual(g['portcullis'], '铁闸门')
        hits = vocab.filter_glossary(g, 'The PORTCULLIS is closed.')
        self.assertEqual(hits, {'portcullis': '铁闸门'})   # 词边界+大小写不敏感
        self.assertEqual(vocab.filter_glossary(g, 'nothing here'), {})

    def test_bad_word_rejected(self):
        self.assertRaises(ValueError, vocab.add_entry, '', 'x')
        self.assertRaises(ValueError, vocab.add_entry, 'a\nb', 'x')


if __name__ == '__main__':
    unittest.main(verbosity=2)
