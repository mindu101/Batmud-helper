"""Search over the project's game knowledge notes (knowledge/, sources/, research/).

Simple, dependency-free ranking: term frequency with a title boost. Good
enough for a few dozen markdown files; no index to maintain.

CLI:
    python3 -m batbridge.kb search "merchant skills" --scope knowledge --limit 5
    python3 -m batbridge.kb read knowledge/merchant-guide.md
    python3 -m batbridge.kb list
"""

import argparse
import json
import sys
from pathlib import Path

# pylib/batbridge/kb.py -> repo root is three levels up
_DEFAULT_ROOT = Path(__file__).resolve().parents[3]
_SCOPES = ('knowledge', 'sources', 'research')
_MAX_TF = 5          # cap per-term frequency so one word can't dominate
_SNIPPET_LEN = 160


def _iter_markdown(root, scope):
    for name in (_SCOPES if scope in (None, 'all') else (scope,)):
        base = root / name
        if not base.is_dir():
            continue
        for p in sorted(base.rglob('*.md')):
            if p.is_file():
                yield p


def _score_file(path, terms, root):
    """Return (score, best_line_no, best_line) or None if no term hits."""
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    lines = text.splitlines()
    if not lines:
        return None
    title = next((l for l in lines[:5] if l.startswith('#')), lines[0])
    title_l = title.lower()
    score, best_line_no, best_hits = 0, None, -1
    for i, line in enumerate(lines, 1):
        low = line.lower()
        hits = sum(1 for t in terms if t in low)
        if hits > best_hits and hits > 0:
            best_hits, best_line_no = hits, i
    for t in terms:
        tf = sum(1 for line in lines if t in line.lower())
        if tf:
            score += min(tf, _MAX_TF) * (3 if t in title_l else 1)
    if score == 0 or best_line_no is None:
        return None
    snippet = lines[best_line_no - 1].strip()
    if len(snippet) > _SNIPPET_LEN:
        snippet = snippet[:_SNIPPET_LEN - 1] + '…'
    rel = path.relative_to(root).as_posix()
    return {'path': rel, 'score': score, 'line': best_line_no,
            'snippet': snippet, 'title': title.lstrip('# ').strip()}


def search(query, root=None, scope='all', limit=10):
    """Search markdown notes; returns ranked [{path, score, line, snippet, title}]."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    root = Path(root or _DEFAULT_ROOT)
    results = []
    for p in _iter_markdown(root, scope):
        r = _score_file(p, terms, root)
        if r:
            results.append(r)
    results.sort(key=lambda r: (-r['score'], r['path']))
    return results[:max(1, limit)]


def read(rel_path, root=None):
    """Read a note by repo-relative path; refuses anything outside the note scopes."""
    root = Path(root or _DEFAULT_ROOT)
    p = (root / rel_path).resolve()
    try:
        parts = p.relative_to(root.resolve()).parts
    except ValueError:
        raise ValueError('path outside notes root: %r' % rel_path)
    if not parts or parts[0] not in _SCOPES or p.suffix not in ('.md', '.txt') \
            or not p.is_file():
        raise ValueError('not a note path: %r' % rel_path)
    return p.read_text(encoding='utf-8', errors='replace')


def list_notes(root=None, scope='all'):
    root = Path(root or _DEFAULT_ROOT)
    return [p.relative_to(root).as_posix() for p in _iter_markdown(root, scope)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog='batbridge.kb', description=__doc__.splitlines()[0])
    ap.add_argument('--root', default=None, help='repo root (default: auto-detect)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('search', help='rank notes by query terms')
    s.add_argument('query')
    s.add_argument('--scope', choices=_SCOPES + ('all',), default='all')
    s.add_argument('--limit', type=int, default=10)
    r = sub.add_parser('read', help='print one note (repo-relative path)')
    r.add_argument('path')
    sub.add_parser('list', help='list all note files')
    a = ap.parse_args(argv)

    if a.cmd == 'search':
        out = search(a.query, a.root, a.scope, a.limit)
    elif a.cmd == 'read':
        try:
            out = read(a.path, a.root)
        except ValueError as e:
            raise SystemExit(str(e))
    else:
        out = list_notes(a.root)
    if isinstance(out, list):
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(out)


if __name__ == '__main__':
    main()
