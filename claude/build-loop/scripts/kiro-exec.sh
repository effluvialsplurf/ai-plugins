#!/usr/bin/env bash
# Inner loop for kiro-run.sh (runs detached, from the work directory); not meant to be called by hand.
# Resumes the same Kiro session after a network drop ("dispatch failure"), up to 6 attempts, a minute apart, so a
# Wi-Fi or hotspot switch doesn't lose the reading. Each attempt is capped at $KIRO_TIMEOUT seconds (default 5400 =
# 90 minutes).
# Args: model tools prompt log done label role effort resume_id
set -euo pipefail
model=$1; tools=$2; prompt=$3; log=$4; done_file=$5; label=$6; role=$7; effort=$8; sid=${9:-}
cont="Your previous turn was cut off by a network error before you finished. Carry on with the same task from where you
stopped; don't re-read what you already read unless you need it. Same brief, house rules and report file as before.
Save the output file early and add to it as you go, so a later drop doesn't lose the work."
# The "Credits:" line covers only Kiro's last turn, so the ledger also records the plan meter's rise over the run
# (approximate when runs overlap). Run from a temp dir so the usage call loads no project context.
meter() { (cd "${TMPDIR:-/tmp}" && timeout 60 kiro-cli chat --no-interactive --trust-tools=@none/none "/usage" < /dev/null 2>&1) |
  sed 's/\x1b\[[0-9;]*[mGK]//g' | grep -o 'Credits ([0-9.]*' | grep -o '[0-9.]*$' | head -1 || true; }
# This run's session: the one whose preview starts with its [run <label>] tag. Never "the newest": parallel runs in
# one workdir would take each other's id. Prints nothing when it can't tell.
own_sid() { kiro-cli chat -l 2>&1 | sed 's/\x1b\[[0-9;]*[mGK]//g' |
  awk -v tag="[run $label]" '/SessionId: /{id=$NF; next} id && index($0, tag) {print id; exit} {id=""}' || true; }
start=$(date +%s); attempt=1; rc=1
# KIRO_NEW_BRIEF=1 with a resume id: continue the same session (keeps its reading) on a new brief, e.g. a plan revision.
if [ -n "$sid" ] && [ -z "${KIRO_NEW_BRIEF:-}" ]; then prompt=$cont; fi
: > "$log"   # create the log before the slow meter read, so the stall watcher sees it at once
m0=$(meter)
while :; do
  resume=(); [ -n "$sid" ] && resume=(--resume-id "$sid")
  echo "=== kiro-exec attempt $attempt $(date +%T) ${sid:+resume $sid}" >> "$log"
  mark=$(wc -l < "$log")
  rc=0
  timeout "${KIRO_TIMEOUT:-5400}" kiro-cli chat --no-interactive ${resume[@]+"${resume[@]}"} --model "$model" --effort "$effort" \
    --trust-tools="$tools" "$prompt" < /dev/null >> "$log" 2>&1 || rc=$?
  [ $rc -eq 0 ] && break
  tail -n +"$mark" "$log" | grep -q "dispatch failure" || break
  [ $attempt -ge 6 ] && break
  if [ -z "$sid" ]; then
    sid=$(own_sid)
    [ -z "$sid" ] && break
  fi
  prompt=$cont; attempt=$((attempt+1)); sleep 60
done
cr=$(sed 's/\x1b\[[0-9;]*[mGK]//g' "$log" | grep -o "Credits: [0-9.]*" | awk '{s+=$2} END {if (NR) printf "%.2f", s}' || true)
secs=$(( $(date +%s)-start )); m1=$(meter)
rise=""; if [ -n "$m0" ] && [ -n "$m1" ]; then rise=$(awk -v a="$m0" -v b="$m1" 'BEGIN{printf "%.2f", b-a}'); fi
printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$(date +%F\ %H:%M)" "$label" "$model" "$role" "${cr:-?}" "$secs" "${rise:-?}" \
  >> "$(dirname "$log")/credits.tsv"
# The session id lets the controller resume this run for a fix round (KIRO_NEW_BRIEF=1 KIRO_RESUME_ID=<id>).
[ -z "$sid" ] && sid=$(own_sid)
echo "exit $rc credits ${cr:-?} meter-rise ${rise:-?} attempts $attempt session ${sid:-?}" > "$done_file"
