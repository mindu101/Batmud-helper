#!/usr/bin/env python3
"""每日小结:收工时一键生成"今天玩了什么",追加进 agent/memory/diary.md。

数据来源(全部本地,不调任何外部服务):
- 命令:审计日志 command-log.jsonl 当天记录(条数、去重清单)
- 单词:vocabulary.md 当天日期段的词条
- 地图:map.json 现状(房间数/边数;顺带报总里程)
- 代码:git log 当天提交
- 经验值:桥事件缓冲里当天的 exp 读数(首尾对比;缓冲只留 2000 条,
  重启过的部分看不到,数字是尽力而为)

用法:
    python3 agent-bridge/tools/diary.py            # 生成/覆盖今天的小结
    python3 agent-bridge/tools/diary.py 2026-10-24 # 指定日期(仅汇总有
                                                  # 时间戳的数据)
同一天重复跑会覆盖当天小节(幂等)。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))

_MEMORY = Path(os.environ.get('BATBRIDGE_MEMORY_DIR')
               or HERE.parent / 'agent' / 'memory')
DIARY_PATH = _MEMORY / 'diary.md'
MAP_PATH = _MEMORY / 'map.json'
VOCAB_PATH = _MEMORY / 'vocabulary.md'
AUDIT_PATH = Path(os.environ.get(
    'BATBRIDGE_AUDIT',
    str(Path.home() / 'batclient' / 'agent-bridge' / 'command-log.jsonl')))
REPO_ROOT = HERE.parents[1]

_EXP_RE = re.compile(r'exp: (\d+)')


def day_bounds(date_str):
    start = time.mktime(time.strptime(date_str, '%Y-%m-%d'))
    return int(start * 1000), int((start + 86400) * 1000)


def commands_of_day(audit_path, lo, hi):
    """[(time_ms, command)] 当天审计记录;文件缺失返回空。"""
    out = []
    try:
        raw = Path(audit_path).read_text(encoding='utf-8')
    except OSError:
        return out
    for ln in raw.splitlines():
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if lo <= rec.get('time_ms', 0) <= hi:
            out.append((rec['time_ms'], rec.get('command', '')))
    return out


def words_of_day(vocab_text, date_str):
    """vocabulary.md 指定日期段下的 ### 单词列表。"""
    m = re.search(r'^## %s\s*$(.*?)(?=^## \d{4}-|\Z)' % re.escape(date_str),
                  vocab_text, re.M | re.S)
    if not m:
        return []
    return re.findall(r'^### (.+?)\s*$', m.group(1), re.M)


def map_snapshot():
    try:
        data = json.loads(Path(MAP_PATH).read_text(encoding='utf-8'))
        rooms = len(data.get('rooms', {}))
        edges = sum(len(v) for v in data.get('edges', {}).values())
        return rooms, edges
    except (OSError, ValueError):
        return 0, 0


def git_commits(date_str, runner=None):
    runner = runner or subprocess.run
    try:
        r = runner(['git', 'log', '--oneline', '--since=%s 00:00:00' % date_str,
                    '--until=%s 23:59:59' % date_str],
                   cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10)
        return [l for l in (r.stdout or '').splitlines() if l.strip()]
    except Exception:
        return []


def exp_of_day(client_factory):
    """桥缓冲里当天 exp 首尾读数;桥不可达返回 None。"""
    try:
        from batbridge.client import BridgeClient
        client = client_factory or BridgeClient
        st = client().status()
        batch = client().read(max(0, st['latest_seq'] - 2000), limit=2000)
    except Exception:
        return None
    lo_ms, _ = 0, 0
    exps = []
    for ev in batch.get('events', []):
        m = _EXP_RE.search(ev.get('text', ''))
        if m:
            exps.append((ev.get('time_ms', 0), int(m.group(1))))
    if len(exps) < 2:
        return None
    return exps[0][1], exps[-1][1]


def build_section(date_str, cmds, words, rooms, edges, commits, exp):
    lines = ['## %s' % date_str, '']
    if exp:
        gained = exp[1] - exp[0]
        lines.append('- 经验:%d → %d(%s%d)' % (exp[0], exp[1],
                     '+' if gained >= 0 else '', gained))
    uniq = []
    for _, c in cmds:
        if c not in uniq:
            uniq.append(c)
    lines.append('- 发出命令 %d 条(去重 %d 种):%s'
                 % (len(cmds), len(uniq), '、'.join(uniq) if uniq else '(无)'))
    lines.append('- 学单词 %d 个:%s' % (len(words), '、'.join(words) if words else '(无)'))
    lines.append('- 地图:共 %d 个房间、%d 条走过的边' % (rooms, edges))
    if commits:
        lines.append('- 工程进展(%d 个提交):' % len(commits))
        lines.extend('  - %s' % c for c in commits)
    lines.append('')
    return '\n'.join(lines)


def write_diary(section, date_str, diary_path=DIARY_PATH):
    """幂等写入:替换当天小节,没有则按日期倒序插入。"""
    path = Path(diary_path)
    header = ('# 游玩日记\n\n> 由 tools/diary.py 生成,同一天重跑会覆盖当天小节。\n\n')
    if not path.exists():
        path.write_text(header + section, encoding='utf-8')
        return 'created'
    text = path.read_text(encoding='utf-8')
    pattern = r'(^## %s\s*$.*?)(?=^## \d{4}-|\Z)' % re.escape(date_str)
    if re.search(pattern, text, re.M | re.S):
        text = re.sub(pattern, lambda m: section.rstrip('\n'), text, flags=re.M | re.S)
        path.write_text(text, encoding='utf-8')
        return 'replaced'
    # 新日期:保持日期倒序(最新在上),插到第一个更老的日期段之前;
    # 都比新日期新则追加到末尾
    insert_at = None
    for mm in re.finditer(r'^## (\d{4}-\d{2}-\d{2})', text, re.M):
        if mm.group(1) < date_str:
            insert_at = mm.start()
            break
    if insert_at is not None:
        text = text[:insert_at] + section + '\n' + text[insert_at:]
        path.write_text(text, encoding='utf-8')
        return 'inserted'
    path.write_text(text.rstrip('\n') + '\n\n' + section, encoding='utf-8')
    return 'appended'


def main():
    ap = argparse.ArgumentParser(description='生成每日游玩小结')
    ap.add_argument('date', nargs='?', default=time.strftime('%Y-%m-%d'))
    a = ap.parse_args()
    lo, hi = day_bounds(a.date)
    cmds = commands_of_day(AUDIT_PATH, lo, hi)
    try:
        vocab_text = Path(VOCAB_PATH).read_text(encoding='utf-8')
    except OSError:
        vocab_text = ''
    words = words_of_day(vocab_text, a.date)
    rooms, edges = map_snapshot()
    commits = git_commits(a.date)
    exp = exp_of_day(None)
    section = build_section(a.date, cmds, words, rooms, edges, commits, exp)
    action = write_diary(section, a.date)
    print(section)
    print('(diary.md: %s)' % action)


if __name__ == '__main__':
    main()
