#!/usr/bin/env bash
# Print Kiro's plan usage (credits used of the monthly allowance, reset date) and this repo's per-run ledger total.
# Usage: kiro-usage.sh
# Ledger: $KIRO_RUNS_DIR/credits.tsv, else $LOOP_DIR/kiro-runs/credits.tsv, else <repo root>/.loop/kiro-runs/credits.tsv.
set -euo pipefail
command -v kiro-cli >/dev/null || { echo "kiro-cli not found on PATH (install Kiro CLI and log in)" >&2; exit 127; }
if [ -n "${LOOP_DIR:-}" ]; then base=$LOOP_DIR
elif c=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then base=$(dirname "$c")/.loop
else base=$PWD/.loop; fi
L=${KIRO_RUNS_DIR:-$base/kiro-runs}/credits.tsv
# Run from a temp dir so the usage call loads no project context.
(cd "${TMPDIR:-/tmp}" && timeout 60 kiro-cli chat --no-interactive --trust-tools=@none/none "/usage" < /dev/null 2>&1) |
  sed 's/\x1b\[[0-9;]*[mGK]//g' | grep -E "Estimated Usage|Credits \(" || echo "kiro: no usage lines found (logged in?)"
[ -f "$L" ] && awk -F'\t' '{v=($7!="" && $7!="?")?$7:$5} v!="?"{s+=v;n++} END{printf "ledger: %d runs, %.2f credits (meter rise where recorded, else last-turn credits)\n", n, s}' "$L"
true
