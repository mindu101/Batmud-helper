#!/usr/bin/env python3
"""Unit tests for batbridge.kb (knowledge note search)."""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pylib'))
from batbridge import kb


def make_tree(tmp):
    root = Path(tmp)
    (root / 'knowledge').mkdir()
    (root / 'sources' / 'in-game-help').mkdir(parents=True)
    (root / 'knowledge' / 'merchant-guide.md').write_text(
        '# Merchant Guide\n\nBargain and Shopkeeping are merchant skills.\n'
        'Charisma affects the Bargain skill directly.\n', encoding='utf-8')
    (root / 'knowledge' / 'combat.md').write_text(
        '# Combat Notes\n\nMerchant economics are irrelevant here. Swing swords.\n',
        encoding='utf-8')
    (root / 'sources' / 'in-game-help' / 'capture.md').write_text(
        '# Raw capture\n\nhelp merchants output follows.\n', encoding='utf-8')
    return root


class TestKb(unittest.TestCase):
    def test_search_ranks_and_finds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            res = kb.search('merchant bargain', root)
            self.assertTrue(res)
            self.assertEqual(res[0]['path'], 'knowledge/merchant-guide.md')
            self.assertIn('Bargain', res[0]['snippet'])
            self.assertEqual(res[0]['title'], 'Merchant Guide')

    def test_title_boost_beats_body_mentions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            res = kb.search('merchant', root)
            # title match (3x weight) outranks more frequent body-only mention
            self.assertEqual(res[0]['path'], 'knowledge/merchant-guide.md')

    def test_scope_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            res = kb.search('merchants', root, scope='sources')
            self.assertEqual([r['path'] for r in res], ['sources/in-game-help/capture.md'])

    def test_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            res = kb.search('the', root, limit=1)
            self.assertEqual(len(res), 1)

    def test_no_hits_and_empty_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            self.assertEqual(kb.search('zzz_nonexistent', root), [])
            self.assertEqual(kb.search('', root), [])

    def test_read_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            self.assertIn('Merchant Guide', kb.read('knowledge/merchant-guide.md', root))
            for bad in ('../outside.md', '/etc/passwd', 'knowledge',
                        'knowledge/nope.md', 'secret.md'):
                self.assertRaises(ValueError, kb.read, bad, root)
            # a real file outside the three note scopes is still refused
            (root / 'secret.md').write_text('x', encoding='utf-8')
            self.assertRaises(ValueError, kb.read, 'secret.md', root)

    def test_list_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_tree(tmp)
            listing = kb.list_notes(root)
            self.assertIn('knowledge/combat.md', listing)
            self.assertIn('sources/in-game-help/capture.md', listing)
            self.assertEqual(len(listing), 3)

    def test_real_project_smoke(self):
        # runs against the actual repository: must find the merchant guide
        real_root = Path(__file__).resolve().parents[2]
        res = kb.search('merchant shopkeeping', str(real_root), scope='knowledge', limit=3)
        self.assertTrue(res, 'no results from real knowledge base')
        self.assertEqual(res[0]['path'], 'knowledge/merchant-guide.md')


if __name__ == '__main__':
    unittest.main(verbosity=2)
