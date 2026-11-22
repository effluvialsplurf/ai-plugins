#!/usr/bin/env bash
# Print the logged-in Codex account's weekly usage (from the newest session log) and when it resets.
# Usage: codex-usage.sh
# Looks in: $CODEX_SESSION_DIRS (space-separated dirs, if set), else <CODEX_HOME or ~/.codex>/sessions plus the
# session logs codex-review.sh archives (<LOOP_DIR or <repo root>/.loop>/codex-sessions), since review runs use their
# own minimal CODEX_HOME. The figure is account-wide, so the newest log from any of them is current.
set -euo pipefail
command -v codex >/dev/null || { echo "codex CLI not found on PATH (install Codex CLI and log in)" >&2; exit 127; }
if [ -n "${CODEX_SESSION_DIRS:-}" ]; then dirs=($CODEX_SESSION_DIRS)
else
  if [ -n "${LOOP_DIR:-}" ]; then base=$LOOP_DIR
  elif c=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then base=$(dirname "$c")/.loop
  else base=$PWD/.loop; fi
  dirs=("${CODEX_HOME:-$HOME/.codex}/sessions" "$base/codex-sessions")
fi
f=$(find "${dirs[@]}" -name '*.jsonl' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2- || true)
[ -z "$f" ] && { echo "codex: no session logs in: ${dirs[*]}"; exit 1; }
line=$(grep -o '"primary":{"used_percent":[0-9.]*,"window_minutes":[0-9]*,"resets_at":[0-9]*' "$f" | tail -1 |
  sed 's/.*used_percent":\([0-9.]*\).*resets_at":\([0-9]*\)/\1 \2/' || true)
[ -z "$line" ] && { echo "codex: no usage data in $f"; exit 1; }
read -r pct at <<<"$line"
echo "codex weekly ${pct}% used, resets $(date -d @"$at" '+%a %b %-d %H:%M' 2>/dev/null || date -r "$at" '+%a %b %-d %H:%M')"
