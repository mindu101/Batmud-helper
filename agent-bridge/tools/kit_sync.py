#!/usr/bin/env python3
"""记忆自动入库:把 agent/memory/ 与套件文档的变更 commit + push。

记忆是这套系统最不可再生的资产(单词本、地图、日记、长期记忆),
攒在工作区里忘了提交就丢了。会话收尾跑一下:

    python3 agent-bridge/tools/kit_sync.py            # 有变更才提交
    python3 agent-bridge/tools/kit_sync.py --dry-run  # 只看会提交什么

会做的事:
- git add agent-bridge/agent/ AGENTS.md(knowledge/ 的笔记也顺带)
- 自动生成提交信息(变更文件分类汇总)
- push 到 origin(不可推送时退回只提交,明确告知)
绝不提交:token、~/.deepseek_api_key 等本机凭据(它们本来就不在仓库)。
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATHS = ['agent-bridge/agent', 'AGENTS.md', 'knowledge', 'sources',
         'research']


def git(*args, **kw):
    return subprocess.run(['git', '-C', str(REPO)] + list(args),
                          capture_output=True, text=True, timeout=60, **kw)


def status_lines():
    out = git('status', '--porcelain', '--', *PATHS).stdout
    return [l for l in out.splitlines() if l.strip()]


def classify(paths):
    cats = {'memory': [], 'notes': []}
    for l in paths:
        p = l[3:].strip()
        if 'agent/memory' in p or p.startswith('agent-bridge/agent'):
            cats['memory'].append(p)
        else:
            cats['notes'].append(p)
    return cats


def main():
    ap = argparse.ArgumentParser(description='副驾驶记忆自动入库')
    ap.add_argument('--dry-run', action='store_true', help='只显示将提交的内容')
    a = ap.parse_args()

    if git('rev-parse', '--is-inside-work-tree').returncode != 0:
        sys.exit('不在 git 仓库里: %s' % REPO)

    changed = status_lines()
    if not changed:
        print('记忆与笔记无变更,无需入库。')
        return 0

    cats = classify(changed)
    summary = []
    if cats['memory']:
        summary.append('记忆 %d 个文件(%s)' % (
            len(cats['memory']),
            ', '.join(sorted({p.rstrip('/').rsplit('/', 1)[-1]
                              for p in cats['memory']})[:6])))
    if cats['notes']:
        summary.append('笔记 %d 个文件' % len(cats['notes']))
    message = 'kit: auto-sync memories and notes (%s)' % '; '.join(summary)

    if a.dry_run:
        print('将提交:\n' + '\n'.join('  ' + l for l in changed))
        print('信息: %s' % message)
        return 0

    existing = [p for p in PATHS if (REPO / p).exists()]
    git('add', '-A', '--', *existing)
    r = git('commit', '-m', message)
    if r.returncode != 0:
        sys.exit('提交失败: %s' % (r.stderr.strip() or r.stdout.strip()))
    print('已提交: %s' % message)

    p = git('push', 'origin', 'HEAD')
    if p.returncode == 0:
        print('已推送到 origin。')
    else:
        print('推送失败(提交已在本地): %s' % p.stderr.strip())
    return 0


if __name__ == '__main__':
    sys.exit(main())
