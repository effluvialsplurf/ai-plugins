#!/usr/bin/env python3
"""Cost ledger for one Claude Code session and its subagents, grouped by job category.

Usage: loop_ledger.py <project-dir> <session-id> [substring ...]
  <project-dir> is ~/.claude/projects/<encoded-project-path>; <session-id> is the session's transcript name
  (the folder <project-dir>/<session-id>/subagents/ holds the subagent transcripts).
  Optional substrings keep only jobs whose description contains one of them, e.g. "[feat]" for one feature.
  e.g. loop_ledger.py ~/.claude/projects/-home-me-code-myrepo <session-id> "[feat]"

wtok = fresh + 1.25 x cache-write + 0.1 x cache-read + 5 x output (a weighted token count).
Subagent output is under-counted in transcripts, so read wtok as "context cost", which is most of it anyway.
Categories come from the [feature][stage] tag at the start of each subagent's description when there is one,
else from keywords in it (plan, sdd-controller, implement, fix, review, other).
Env: LOOP_LEDGER_MIN_WTOK (default 1500000) hides groups cheaper than that; 0 shows every group.
Read-only.
"""
import sys
import json, os, glob, collections, re, statistics
if len(sys.argv) < 3:
    sys.exit(__doc__)
base = os.path.expanduser(sys.argv[1])
sid = sys.argv[2]
flt = [f.lower() for f in sys.argv[3:]]
M=1e6
MIN_W = float(os.environ.get('LOOP_LEDGER_MIN_WTOK', 1.5e6))  # hide groups cheaper than this (set 0 to show all)
def cat(desc):
    d = (desc or '').lower()
    tag = re.match(r'\[[^\]]+\]\[([^\]]+)\]', d)  # [feature][stage] dispatch tag, when present
    if tag: return tag.group(1)
    if d.startswith('sdd controller'): return 'sdd-controller'
    if d.startswith('plan') or 'write plan' in d or 'plan ' in d[:12]: return 'plan'
    if 'implement' in d: return 'implement'
    if 'fix' in d: return 'fix'
    if 'review' in d or 'audit' in d or 'verify' in d or 'check' in d: return 'review'
    if 'spec' in d or 'design' in d or 'brainstorm' in d: return 'spec/design'
    return 'other'
rows = []
tool_bytes = collections.defaultdict(lambda: collections.Counter())
bash_kinds = collections.defaultdict(lambda: collections.Counter())
for p in glob.glob(f'{base}/{sid}/subagents/**/*.jsonl', recursive=True):
    meta = p[:-6] + '.meta.json'; desc=''; 
    if os.path.exists(meta):
        try: desc = json.load(open(meta)).get('description') or ''
        except Exception: pass
    if flt and not any(f in desc.lower() for f in flt): continue
    seen = {}; order=[]; model=None; names={}; c=cat(desc); inputs={}
    for line in open(p, errors='ignore'):
        try: d = json.loads(line)
        except Exception: continue
        m = d.get('message') or {}
        if d.get('type')=='assistant':
            if isinstance(m.get('content'), list):
                for b in m['content']:
                    if isinstance(b, dict) and b.get('type')=='tool_use':
                        names[b['id']] = b['name']; inputs[b['id']] = b.get('input') or {}
            u = m.get('usage')
            if u:
                model = m.get('model') or model
                mid = m.get('id')
                if mid not in seen: order.append(mid)
                seen[mid] = (u.get('input_tokens',0), u.get('cache_creation_input_tokens',0), u.get('cache_read_input_tokens',0), u.get('output_tokens',0))
        elif d.get('type')=='user' and isinstance(m.get('content'), list):
            for b in m['content']:
                if isinstance(b, dict) and b.get('type')=='tool_result':
                    cc = b.get('content'); n = len(cc) if isinstance(cc, str) else sum(len(x.get('text','')) for x in cc if isinstance(x, dict)) if isinstance(cc, list) else 0
                    nm = names.get(b.get('tool_use_id'), '?')
                    tool_bytes[c][nm] += n; tool_bytes[c]['_n_'+nm] += 1
                    if nm == 'Bash':
                        cmd = (inputs.get(b.get('tool_use_id'), {}).get('command') or '')
                        k = 'pytest' if 'pytest' in cmd else 'git' if re.search(r'\bgit\b', cmd) else 'cat/sed/grep' if re.search(r'\b(cat|sed|grep|rg|head|tail|ls|find|wc)\b', cmd) else 'python' if 'python' in cmd else 'other'
                        bash_kinds[c][k] += n; bash_kinds[c]['_n_'+k] += 1
    calls = [seen[i] for i in order]
    if not calls: continue
    ctx = [a+b+cr for a,b,cr,o in calls]
    w = sum(a+1.25*b+0.1*cr+5*o for a,b,cr,o in calls)
    rows.append(dict(cat=c, model=model, desc=desc, n=len(calls), first=ctx[0], last=ctx[-1], avg=sum(ctx)/len(ctx), w=w, cw=sum(x[1] for x in calls), cr=sum(x[2] for x in calls), out=sum(x[3] for x in calls)))
g = collections.defaultdict(list)
for r in rows: g[(r['cat'], (r['model'] or '').replace('claude-',''))].append(r)
print('cat,model: jobs calls/job first-ctx(median) last-ctx(median) avgctx  cw/job  wtok  share')
tot = sum(r['w'] for r in rows)
for k,v in sorted(g.items(), key=lambda kv:-sum(r['w'] for r in kv[1])):
    w=sum(r['w'] for r in v)
    if w < MIN_W: continue
    print(f" {k[0]:14s} {k[1]:12s} jobs={len(v):3d} calls/job={sum(r['n'] for r in v)/len(v):4.0f} first={statistics.median(r['first'] for r in v)/1e3:4.0f}k last={statistics.median(r['last'] for r in v)/1e3:4.0f}k avg={sum(r['avg']*r['n'] for r in v)/sum(r['n'] for r in v)/1e3:4.0f}k cw/job={sum(r['cw'] for r in v)/len(v)/1e3:4.0f}k out/job={sum(r['out'] for r in v)/len(v)/1e3:3.0f}k wtok={w/M:6.1f}M {100*w/tot:4.1f}%")
print('\nTool-result chars by category (top tools), chars/4 ~ tokens')
for c in ['implement','review','plan','sdd-controller','fix','other']:
    tb = tool_bytes[c]; items = sorted(((k,v) for k,v in tb.items() if not k.startswith('_n_')), key=lambda kv:-kv[1])[:6]
    print(' ', c, '; '.join(f"{k} {v/4/1e6:.2f}Mtok/{tb['_n_'+k]}calls" for k,v in items))
    bk = bash_kinds[c]; items = sorted(((k,v) for k,v in bk.items() if not k.startswith('_n_')), key=lambda kv:-kv[1])
    print('     bash:', '; '.join(f"{k} {v/4/1e6:.2f}Mtok/{bk['_n_'+k]}" for k,v in items))
print('\nother-category sample descs:', [r['desc'][:50] for r in sorted([r for r in rows if r['cat']=='other'], key=lambda r:-r['w'])[:12]])
print('review sample:', [ (r['desc'][:45], r['model'][-8:], round(r['w']/M,2)) for r in sorted([r for r in rows if r['cat']=='review'], key=lambda r:-r['w'])[:8]])
