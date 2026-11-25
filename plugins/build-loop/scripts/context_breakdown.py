#!/usr/bin/env python3
"""Where does each subagent job's context come from?

Usage: context_breakdown.py <session-dir-with-subagents> [substring ...]
  <session-dir> is ~/.claude/projects/<project>/<session-id> (the folder that holds subagents/).
  Optional substrings filter jobs by description (case-insensitive), e.g. "T3" "fix".

Per job it prints: calls, context at the first and last call, average context, cache writes,
cache writes that followed a gap of more than 5 minutes (a likely cache expiry), and the
tool-result volume by tool and by kind of Bash command. Tokens for tool results are chars / 4.
Read-only.
"""
import collections, datetime, glob, json, os, re, sys

def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))

def bash_kind(cmd):
    if re.search(r"\b(jest|pytest|npm (run )?test|check-all|typecheck|eslint|prettier|tsc)\b", cmd):
        return "tests/checks"
    if re.search(r"\bgit\b", cmd):
        return "git"
    if re.search(r"\b(cat|sed|grep|rg|head|tail|ls|find|wc|awk)\b", cmd):
        return "reads"
    return "other"

def scan(path):
    seen, order, names, inputs = {}, [], {}, {}
    tools, kinds, paths = collections.Counter(), collections.Counter(), collections.Counter()
    for line in open(path, errors="ignore"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        m = d.get("message") or {}
        content = m.get("content")
        if d.get("type") == "assistant":
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        names[b["id"]] = b["name"]
                        inputs[b["id"]] = b.get("input") or {}
            u = m.get("usage")
            if u and d.get("timestamp"):
                mid = m.get("id")
                if mid not in seen:
                    order.append(mid)
                seen[mid] = (ts(d["timestamp"]), u.get("input_tokens", 0),
                             u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0))
        elif d.get("type") == "user" and isinstance(content, list):
            for b in content:
                if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                    continue
                c = b.get("content")
                n = len(c) if isinstance(c, str) else sum(len(x.get("text", "")) for x in c if isinstance(x, dict)) if isinstance(c, list) else 0
                tid = b.get("tool_use_id")
                name = names.get(tid, "?")
                tools[name] += n
                inp = inputs.get(tid, {})
                if name == "Bash":
                    kinds[bash_kind(inp.get("command") or "")] += n
                if name == "Read" and inp.get("file_path"):
                    paths[os.path.basename(inp["file_path"])] += n
    calls = [seen[i] for i in order]
    if not calls:
        return None
    ctx = [a + b + c for _, a, b, c in calls]
    late_cw = sum(cw for i, (t, _, cw, cr) in enumerate(calls)
                  if i and (t - calls[i - 1][0]).total_seconds() > 300 and cw > 20000 and cr < cw)
    return dict(n=len(calls), first=ctx[0], last=ctx[-1], avg=sum(ctx) / len(ctx), cw=sum(c[2] for c in calls),
                cr=sum(c[3] for c in calls), late_cw=late_cw, tools=tools, kinds=kinds, paths=paths)

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root, filters = sys.argv[1], [f.lower() for f in sys.argv[2:]]
    k = lambda v: f"{v / 1e3:.0f}k"
    for p in sorted(glob.glob(os.path.join(root, "subagents", "**", "*.jsonl"), recursive=True)):
        meta, desc, atype = p[:-6] + ".meta.json", "", ""
        if os.path.exists(meta):
            try:
                mj = json.load(open(meta))
                desc, atype = mj.get("description") or "", mj.get("agentType") or ""
            except Exception:
                pass
        if filters and not any(f in desc.lower() for f in filters):
            continue
        s = scan(p)
        if not s:
            continue
        print(f"{atype} | {desc[:70]}")
        print(f"  calls {s['n']}  ctx first {k(s['first'])} last {k(s['last'])} avg {k(s['avg'])}  "
              f"c-read {s['cr'] / 1e6:.1f}M  c-write {k(s['cw'])} (after >5 min gaps: {k(s['late_cw'])})")
        print("  tool results (tokens): " + ", ".join(f"{n} {k(v / 4)}" for n, v in s["tools"].most_common(5)))
        print("  bash by kind: " + ", ".join(f"{n} {k(v / 4)}" for n, v in s["kinds"].most_common()))
        print("  top reads: " + ", ".join(f"{n} {k(v / 4)}" for n, v in s["paths"].most_common(6)))

if __name__ == "__main__":
    main()
