#!/usr/bin/env bash
# Run one brief-driven task on Kiro instead of a Claude subagent, to save Claude usage.
# Usage: kiro-run.sh <label> <workdir> <brief.md> <report.md> [model] [role] [effort]
#   model:  default $KIRO_MODEL, else claude-opus-5.5. Always passed explicitly with --effort (never rely on defaults).
#   effort: low|medium|high|xhigh|max, default high (match the Claude subagents).
#   role:   build (read, write, shell; may commit) | review (read, shell for git/tests; no edits). Default build.
# State dir: $KIRO_RUNS_DIR, else $LOOP_DIR/kiro-runs, else <repo root>/.loop/kiro-runs (repo root = main checkout, even
# when <workdir> is a linked worktree). Add .loop/ to .gitignore or .git/info/exclude.
# Env: KIRO_EXTRA_RULES (text appended to the house rules in the prompt), KIRO_TIMEOUT (seconds, default 5400 = the
#   90-minute cap per attempt), KIRO_RESUME_ID, KIRO_NEW_BRIEF (below).
# Detached, so it survives a Claude Code exit. Log: <state>/<label>.log;
# on exit writes <label>.done ("exit <rc> credits <n> ... session <id>"). Wait with:
#   until [ -f <state>/<label>.done ]; do sleep 20; done
# Network drops are resumed automatically (kiro-exec.sh). To resume a run that gave up: KIRO_RESUME_ID=<session id from
# `kiro-cli chat -l` in workdir> kiro-run.sh ... (same args). Add KIRO_NEW_BRIEF=1 to give that session a new brief
# (e.g. revise the plan it wrote). The old log is kept as <label>.log.<n>.
# Quirks: do not run two Kiro runs in one workdir at the same time (they confuse each other: shared checkout, and
# session lookup); use one worktree per run. Kiro can't run background servers, so the house rules forbid starting any.
set -euo pipefail
[ $# -ge 4 ] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 64; }
command -v kiro-cli >/dev/null || { echo "kiro-cli not found on PATH (install Kiro CLI and log in)" >&2; exit 127; }
label=$1; workdir=$2; brief=$3; report=$4
model=${5:-${KIRO_MODEL:-claude-opus-5.5}}; role=${6:-build}; effort=${7:-high}
[ -d "$workdir" ] || { echo "workdir not found: $workdir" >&2; exit 2; }
[ -f "$brief" ] || { echo "brief not found: $brief" >&2; exit 2; }
loop_dir() {
  if [ -n "${LOOP_DIR:-}" ]; then echo "$LOOP_DIR"; return; fi
  local c; c=$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || { echo "$PWD/.loop"; return; }
  echo "$(dirname "$c")/.loop"
}
out=${KIRO_RUNS_DIR:-$(loop_dir "$workdir")/kiro-runs}; mkdir -p "$out"; rm -f "$out/$label.done"
case $role in
  # build and review trust web_search/web_fetch so they can open the docs they cite (checked on kiro-cli 2.21.1).
  build)  tools=read,write,shell,grep,glob,web_search,web_fetch; mode="You may edit files in the work directory and commit to its current branch." ;;
  # review keeps write so it can save its report (headless Kiro can't ask); the prompt limits writes to that one file.
  review) tools=read,write,shell,grep,glob,web_search,web_fetch; mode="Read-only review: the only file you may write is the report file named below. Do not edit anything else, commit, stash or check out. Shell is for git show/diff/log and running tests only." ;;
  *) echo "role must be build or review" >&2; exit 2 ;;
esac
# Context a Claude subagent would load on its own: the repo's CLAUDE.md and the files it points to.
ctx="Before the brief's inputs, read the project rules a Claude agent would load: $workdir/CLAUDE.md if it exists, and the
files it points to that fit the task. If those rules say to ask before committing, the commit rule below wins."
rules="House rules (they override steering where they conflict): commit only if the brief asks you to (it's allowed then); never push;
never use bare git stash; never read secrets or .env files; never start background servers or long-running processes
(run commands in the foreground and let them finish); stop and report rather than guess.${KIRO_EXTRA_RULES:+ $KIRO_EXTRA_RULES}"
# The [run <label>] tag starts the prompt so kiro-exec.sh can find this run's own session in `kiro-cli chat -l`
# (its preview shows the prompt's first words); "newest session" is wrong when runs overlap in one workdir.
prompt="[run $label] You are working for a Claude Code controller, headless. Read this file first; it is your requirements: $brief
$ctx
Work directory: $workdir. $mode
$rules
Write your full report to $report. Your final message is only: status (DONE / DONE_WITH_CONCERNS / BLOCKED), commit SHAs, a one-line test summary, concerns."
n=1; while [ -e "$out/$label.log.$n" ]; do n=$((n+1)); done; [ -e "$out/$label.log" ] && mv "$out/$label.log" "$out/$label.log.$n"
cd "$workdir"
# kiro-exec.sh runs Kiro, resumes the same session after a network drop (up to 6 attempts), then appends label, model,
# role, credits and seconds to credits.tsv.
setsid nohup "$(dirname "$0")/kiro-exec.sh" "$model" "$tools" "$prompt" "$out/$label.log" "$out/$label.done" "$label" \
  "$role" "$effort" "${KIRO_RESUME_ID:-}" > /dev/null 2>&1 < /dev/null &
echo "started $label ($model, $role, effort $effort): log $out/$label.log, done file $out/$label.done"
