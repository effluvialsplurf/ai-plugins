#!/usr/bin/env bash
# Quiet verification gate: one "gate: PASS (N tests)" line, or the failing tail and exit 1.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIN_TESTS=86
(( $# <= 1 )) || { echo "usage: tools/gate.sh [--fast]" >&2; exit 2; }
case "${1:-}" in ""|--fast) ;; *) echo "usage: tools/gate.sh [--fast]" >&2; exit 2 ;; esac
cd "$ROOT"
# --fast: installer sandbox tests (tools/test_install.py) skip themselves; only executed tests count toward MIN_TESTS.
if [[ "${1:-}" == "--fast" ]]; then export GATE_FAST=1; else unset GATE_FAST; fi

fail() { echo "gate: FAIL ($1)"; [[ -n "${2:-}" ]] && printf '%s\n' "$2" | tail -40; exit 1; }

out="$(python3 - <<'PY' 2>&1
import json, sys
from pathlib import Path
bad = []
for d in ("claude", "antigravity"):
    p = Path(d)
    if p.exists() and any((f.is_file() or f.is_symlink()) and f.suffix != ".pyc" for f in p.rglob("*")):
        bad.append(f"legacy layout dir still has files: {d}")
files = [Path(".claude-plugin/marketplace.json"), *sorted(Path("plugins").glob("*/.claude-plugin/plugin.json")),
         *sorted(Path("plugins").glob("*/plugin.json")), *sorted(Path("plugins").glob("*/hooks.json")),
         *sorted(Path("plugins").glob("*/hooks/hooks.json"))]
parsed = {}
for f in files:
    try:
        parsed[f] = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        bad.append(f"invalid JSON {f}: {e}")
for p in parsed.get(files[0], {}).get("plugins", []):
    src = p.get("source", "")
    if src != f"./plugins/{p.get('name')}":
        bad.append(f"marketplace source {src!r} is not ./plugins/{p.get('name')}")
    root = Path(src)
    if not ((root / ".claude-plugin/plugin.json").is_file() or (root / "plugin.json").is_file()):
        bad.append(f"marketplace plugin {p.get('name')} has no manifest at {src}")
print("\n".join(bad)); sys.exit(1 if bad else 0)
PY
)" || fail "layout/manifests" "$out"

out="$(python3 tools/check_agnostic.py 2>&1)" || fail "agnostic" "$out"

total=0
for suite in plugins/swarmctl/scripts/tests plugins/lean-runbook/skills/lean-runbook/scripts \
             plugins/lean-runbook/skills/lean-design/scripts tools; do
  [[ -d "$suite" ]] || fail "missing suite $suite"
  out="$(python3 -m unittest discover -s "$suite" 2>&1)" || fail "suite $suite" "$out"
  n="$(grep -oE '^Ran [0-9]+ test' <<<"$out" | grep -oE '[0-9]+' | tail -1)"
  sk="$(grep -oE 'skipped=[0-9]+' <<<"$out" | grep -oE '[0-9]+' | tail -1)"
  exec_n=$(( ${n:-0} - ${sk:-0} ))
  (( exec_n > 0 )) || fail "suite $suite executed 0 tests" "$out"
  total=$((total + exec_n))
done
(( total >= MIN_TESTS )) || fail "$total tests < $MIN_TESTS"
echo "gate: PASS ($total tests)"
