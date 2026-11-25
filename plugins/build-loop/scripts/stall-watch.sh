#!/usr/bin/env bash
# Emits one line when a watched subagent/Codex/Kiro job goes quiet longer than its idle limit, or runs
# past its wall-clock cap. Run it in the background (Monitor or run_in_background); it loops until killed.
# Usage: stall-watch.sh <registry-file>
# Registry lines (tab-separated; re-read every minute, so append jobs as you start them):
#   output_path  idle_min  cap_min  start_epoch  label  [work_paths]
# work_paths (optional, space-separated files or dirs) also count as activity: a plan file being
# edited, or a worktree (its newest file, .git ignored). Agents' own logs can lag behind their edits.
# Needs bash 4+ and GNU find/stat.
set -euo pipefail
[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: $0 <registry-file>" >&2; exit 64; }
[ "${BASH_VERSINFO[0]}" -ge 4 ] || { echo "stall-watch.sh needs bash 4+" >&2; exit 1; }
find --version >/dev/null 2>&1 || { echo "stall-watch.sh needs GNU find" >&2; exit 1; }
REG="$1"; declare -A told
newest() { local t=0 m p; for p in "$@"; do
  if [ -d "$p" ]; then m=$(find "$p" -path '*/.git' -prune -o -path '*/node_modules' -prune -o -type f -newermt '-2 hours' -printf '%T@\n' 2>/dev/null | sort -n | tail -1 || true); m=${m%.*}
  elif [ -e "$p" ]; then m=$(stat -L -c %Y "$p" 2>/dev/null || echo 0); else m=0; fi
  if [ "${m:-0}" -gt "$t" ]; then t=$m; fi; done; echo "$t"; }
while true; do
  now=$(date +%s)
  while IFS=$'\t' read -r path idle cap start label work || [ -n "${path:-}" ]; do
    [ -z "$path" ] && continue
    if [ ! -f "$path" ]; then
      [ -z "${told[$label.missing]:-}" ] && echo "MISSING $label: no output file" && told[$label.missing]=1
      continue
    fi
    m=$(newest "$path" ${work:-}); q=$(( (now - m) / 60 )); r=$(( (now - start) / 60 ))
    if [ "$q" -ge "$idle" ] && [ -z "${told[$label.idle]:-}" ]; then echo "STALL? $label: no activity for ${q}m (limit ${idle}m), running ${r}m"; told[$label.idle]=1; fi
    if [ "$q" -lt "$idle" ]; then unset "told[$label.idle]"; fi
    if [ "$r" -ge "$cap" ] && [ -z "${told[$label.cap]:-}" ]; then echo "OVER CAP $label: running ${r}m (cap ${cap}m)"; told[$label.cap]=1; fi
  done < "$REG"
  sleep 60
done
