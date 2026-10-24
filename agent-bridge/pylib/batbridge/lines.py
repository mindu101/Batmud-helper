"""Line reassembly and noise filtering for AgentBridge event streams.

The plugin records every trigger callback as one event; a single game line
may arrive split across several events, and the stream contains empty
events, client protocol fragments and repeated login prompts. This module
turns raw events into clean logical lines an agent can parse reliably:

    clean_lines(events) -> [{seq_start, seq_end, text, kind, repeats}]

Rules (documented, conservative):
- reassembly: event text is concatenated in seq order; a fragment that does
  not end with a newline is joined with the next event's text.
- ANSI/BatClient markup is stripped from text defensively.
- whitespace-only lines are dropped (counted in the stats).
- consecutive exact-duplicate lines collapse into one entry with a
  ``repeats`` count (repeat counts matter for combat spam).
- kind classification is heuristic and marked as such:
    exits       "Obvious exit(s) is/are: ..." (reliable regex)
    chat        speech verbs: says/exclaims/tells you/chats/gossips/...
    room_title? first short line within 10 lines before an exits line
                (heuristic; BatMUD prints the room title above the
                description when you enter or look)
    prompt      trailing fragment without a newline (incomplete line)
    text        everything else
"""

import re

_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-B]')
# BatClient hotkey markup: ESC<N>visible ESC|command-copy ESC>N — keep the
# visible part, drop the command copy and the markers.
_BATHOTKEY_RE = re.compile(r'\x1b<\d*([^|]*?)\x1b\|.*?\x1b>\d*', re.DOTALL)
_BATCODE_RE = re.compile(r'\x1b[<>]\d*|\x1b\|')
_EXITS_RE = re.compile(r"^Obvious exits?\s+(?:is|are):\s*.+", re.IGNORECASE)
_CHAT_RE = re.compile(
    r"(?:\b(?:says?|exclaims?|asks?|tells you|chats?|gossips?|auctions?|"
    r"shouts?|whispers?|narrates?|reports?|emotes?)\b[:,\s])", re.IGNORECASE)
_TITLE_MAX_LEN = 48
_TITLE_WINDOW = 10  # how many lines before an exits line to look for a title


def _strip_markup(text):
    return _BATCODE_RE.sub('', _ANSI_RE.sub('', _BATHOTKEY_RE.sub(r'\1', text)))


def clean_lines(events, collapse_repeats=True):
    """Turn bridge events into clean logical lines.

    events: iterable of {seq, time_ms, text, raw} dicts (seq order assumed).
    Returns (lines, stats) where stats reports dropped/collapsed counts.
    """
    lines, stats = [], {'events': 0, 'dropped_empty': 0, 'collapsed': 0}
    buf, seq_start, seq_end, open_frag, last_time = [], None, None, False, None

    def flush():
        """Emit one logical line from the buffer."""
        if not buf:
            return
        text = ''.join(buf)
        del buf[:]
        text = _strip_markup(text)
        if not text.strip():
            stats['dropped_empty'] += 1
            return
        entry = {'seq_start': seq_start, 'seq_end': seq_end, 'time_ms': last_time,
                 'text': text.rstrip('\n'), 'kind': 'text', 'repeats': 1}
        if not text.endswith('\n'):
            entry['kind'] = 'prompt'  # incomplete: no terminating newline
        lines.append(entry)

    for ev in events:
        stats['events'] += 1
        text = ev.get('text') or ''
        seq = ev.get('seq')
        last_time = ev.get('time_ms', last_time)
        if seq_start is None:
            seq_start = seq
        seq_end = seq
        buf.append(text)
        if text.endswith('\n'):
            flush()
            seq_start = None
    flush()  # trailing fragment (kind stays 'prompt' if unterminated)

    for entry in lines:
        if _EXITS_RE.match(entry['text']):
            entry['kind'] = 'exits'
        elif _CHAT_RE.search(entry['text']):
            entry['kind'] = 'chat'

    # Room-title heuristic: first short line within the window above an
    # exits line. Marked with '?' because it is a guess, not protocol.
    for i, entry in enumerate(lines):
        if entry['kind'] != 'exits':
            continue
        for cand in lines[max(0, i - _TITLE_WINDOW):i]:
            if (cand['kind'] == 'text' and len(cand['text']) <= _TITLE_MAX_LEN
                    and not cand['text'].endswith((',', ';'))):
                cand['kind'] = 'room_title?'
                break

    if collapse_repeats:
        out = []
        for entry in lines:
            if (out and entry['kind'] == out[-1]['kind'] != 'prompt'
                    and entry['text'] == out[-1]['text']):
                out[-1]['repeats'] += 1
                out[-1]['seq_end'] = entry['seq_end']
                stats['collapsed'] += 1
            else:
                out.append(entry)
        lines = out

    return lines, stats


def render(lines):
    """Compact text rendering for agents and humans."""
    out = []
    for e in lines:
        rep = ' (x%d)' % e['repeats'] if e['repeats'] > 1 else ''
        out.append('[%d-%d|%s%s] %s' % (
            e['seq_start'], e['seq_end'], e['kind'], rep, e['text']))
    return '\n'.join(out)
