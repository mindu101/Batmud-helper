#!/usr/bin/env python3
"""Unit tests for batbridge.lines (line reassembly + noise filtering)."""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pylib'))
from batbridge.lines import clean_lines, render


def ev(seq, text):
    return {'seq': seq, 'time_ms': 0, 'text': text, 'raw': text}


class TestCleanLines(unittest.TestCase):
    def test_fragment_reassembly(self):
        # a game line split across three events rejoins into one logical line
        lines, _ = clean_lines([ev(1, 'You are in the northern gate'),
                                ev(2, 'house of Dortlewall, and the'),
                                ev(3, 'portcullis is closed.\n')])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['seq_start'], 1)
        self.assertEqual(lines[0]['seq_end'], 3)
        self.assertIn('portcullis is closed.', lines[0]['text'])

    def test_empty_events_dropped_with_count(self):
        # '' merges into the next event's text, so only 2 logical empties here
        lines, stats = clean_lines([ev(1, '\n'), ev(2, ''), ev(3, '   \n'),
                                    ev(4, 'real line\n')])
        self.assertEqual([l['text'] for l in lines], ['real line'])
        self.assertEqual(stats['dropped_empty'], 2)

    def test_ansi_and_batclient_markup_stripped(self):
        text = '\u001b[1;32mDawnmist\u001b[0m exclaims \'Hello.\'\n'
        raw_ish = 'Obvious exit is: \u001b[1m\u001b<31north\u001b|north\u001b>31\u001b[0m.\n'
        lines, _ = clean_lines([ev(1, text), ev(2, raw_ish)])
        self.assertEqual(lines[0]['text'], 'Dawnmist exclaims \'Hello.\'')
        self.assertEqual(lines[1]['text'], 'Obvious exit is: north.')
        self.assertEqual(lines[1]['kind'], 'exits')

    def test_duplicate_collapse_preserves_count(self):
        lines, stats = clean_lines([ev(1, 'You hit the orc.\n'),
                                    ev(2, 'You hit the orc.\n'),
                                    ev(3, 'You hit the orc.\n')])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['repeats'], 3)
        self.assertEqual(lines[0]['seq_end'], 3)
        self.assertEqual(stats['collapsed'], 2)

    def test_prompt_kind_for_unterminated_tail(self):
        lines, _ = clean_lines([ev(1, 'line one\n'), ev(2, 'Password: ')])
        self.assertEqual(lines[0]['kind'], 'text')
        self.assertEqual(lines[1]['kind'], 'prompt')

    def test_chat_detection(self):
        for text, want in [("Dawnmist exclaims 'Hello, Deepseek.'\n", True),
                           ("Algernon tells you 'hi'\n", True),
                           ("Wiz chats: anyone here?\n", True),
                           ("You are in the northern gatehouse.\n", False)]:
            lines, _ = clean_lines([ev(1, text)])
            self.assertEqual(lines[0]['kind'], 'chat' if want else 'text', text)

    def test_room_title_heuristic(self):
        # realistic look output: short title, long description, exits line
        lines, _ = clean_lines([
            ev(1, 'Northern gatehouse.\n'),
            ev(2, 'You are in the northern gatehouse of Dortlewall. If you would like\n'),
            ev(3, 'to continue your adventures, go south through the portcullis.\n'),
            ev(4, 'Iron portcullis (closed) leads south.\n'),
            ev(5, 'Obvious exit is: south.\n'),
        ])
        kinds = [l['kind'] for l in lines]
        self.assertEqual(kinds, ['room_title?', 'text', 'text', 'text', 'exits'])

    def test_render_is_compact_and_tagged(self):
        lines, _ = clean_lines([ev(1, 'a\n'), ev(2, 'b\n'), ev(3, 'b\n')])
        r = render(lines)
        self.assertIn('[1-1|text] a', r)
        self.assertIn('[2-3|text (x2)] b', r)

    def test_real_login_capture_regression(self):
        # excerpt of the actual stream captured from the live client on
        # 2026-10-24 (session fe752bc3, seqs 39-48): fragments, empty
        # events, repeated prompts, markup, chat — as the plugin emits it.
        real = [
            ev(39, 'Northern gatehouse.\n'),
            ev(40, 'You are in the northern gatehouse of Dortlewall. If you would like to redo the\n'),
            ev(41, 'first part of the tutorial, you should go north and follow the\n'),
            ev(42, 'instructions there. If you would like to continue your adventures, go\n'),
            ev(43, 'south through the portcullis. Please remember the tutorial command, it\n'),
            ev(44, 'holds valuable information about getting started in BatMUD.\n'),
            ev(45, 'Outside, above you is a still, clear night sky.\n'),
            ev(46, 'Iron portcullis (closed) leads south.\n'),
            ev(47, 'Obvious exit is: north.\n'),
            ev(48, 'Dawnmist the dryad, welcoming new adventurers\n'),
            ev(49, "Dawnmist exclaims 'Hello, Deepseek. Now that you're done with the tutorial, you should try out the story!'  \n"),
            ev(50, ''),
            ev(51, 'If you want to check out the story, ask dawnmist about story.\n'),
            ev(52, ''),
        ]
        lines, stats = clean_lines(real)
        self.assertEqual(stats['events'], 14)          # seqs 39..52
        self.assertEqual(stats['dropped_empty'], 1)    # trailing ''; '' at 50 merged into 51
        kinds = [l['kind'] for l in lines]
        texts = [l['text'] for l in lines]
        self.assertEqual(texts[0], 'Northern gatehouse.')
        self.assertEqual(kinds[0], 'room_title?')
        exits = next(l for l in lines if l['text'].startswith('Obvious exit'))
        self.assertEqual(exits['kind'], 'exits')
        chat = next(l for l in lines if l['text'].startswith("Dawnmist exclaims"))
        self.assertEqual(chat['kind'], 'chat')
        # nothing collapsed: all lines distinct
        self.assertEqual(stats['collapsed'], 0)
        self.assertEqual(len(lines), 12)

    def test_repeated_login_prompt_collapse(self):
        real = [ev(1, 'Please enter your choice or name: \n'),
                ev(2, '\n'),
                ev(3, 'Please enter your choice or name: \n'),
                ev(4, 'Please enter your choice or name: \n')]
        lines, stats = clean_lines(real)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['repeats'], 3)
        self.assertEqual(stats['dropped_empty'], 1)

    def test_protocol_noise_not_merged_into_next_line(self):
        # 真实场景(2026-10-24 seq 38-39):NoMapSupport 无换行,
        # 曾与随后的房间标题粘成 'NoMapSupportNorthern gatehouse.'
        lines, stats = clean_lines([ev(38, 'NoMapSupport'),
                                    ev(39, 'Northern gatehouse.\n'),
                                    ev(40, 'Obvious exit is: north.\n')])
        self.assertEqual([l['text'] for l in lines],
                         ['Northern gatehouse.', 'Obvious exit is: north.'])
        self.assertEqual(lines[0]['kind'], 'room_title?')
        self.assertEqual(stats.get('dropped_noise'), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
