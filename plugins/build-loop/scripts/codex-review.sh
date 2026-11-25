#!/usr/bin/env bash
# Narrowed whole-branch review through `codex exec`: correctness rubric only, one thread, minimal CODEX_HOME (auth
# only: no AGENTS.md, no memories, no hooks, so no CLAUDE.md or personal-setup reads), read-only sandbox, live web
# search on (`--search`, a top-level flag that goes before `exec`) so the reviewer can open the docs a change cites.
# Usage: [TAG="[feat][codex-review][p1]"] codex-review.sh <worktree> <base> <context-file> <rubric-file> <out.md> [--dry-run]
#   worktree      checkout at the branch head to review; the diff is <base>...HEAD there
#   base          commit/branch the review diffs against (e.g. origin/main)
#   context-file  short product/house-rules text pasted into the prompt (what the change is for, what is out of scope)
#   rubric-file   the correctness rubric pasted into the prompt, e.g. the deep-review plugin's
#                 skills/deep-review/references/correctness.md from wherever that plugin is installed. Passed in, not
#                 found by path, because the plugin's install location varies.
#   out.md        Codex's output is written here (stdout and stderr)
# Env: CODEX_MODEL (default gpt-6-astra), CODEX_EFFORT (default high), CODEX_AUTH_FILE (default $HOME/.codex/auth.json),
#   CODEX_SCHEMA_FILE (optional: finding output schema appended to the prompt; without it the prompt asks for
#   severity, location, what, why, suggested fix per finding), TAG (opens the prompt so cost reports can attribute the
#   run), LOOP_DIR (session logs are archived to <LOOP_DIR or <repo root>/.loop>/codex-sessions).
# Run with the Bash tool's run_in_background; never background codex with &.
set -euo pipefail
DRY=0; ARGS=()
for a in "$@"; do if [ "$a" = --dry-run ]; then DRY=1; else ARGS+=("$a"); fi; done
[ "${#ARGS[@]}" -eq 5 ] || { echo "usage: $0 <worktree> <base> <context-file> <rubric-file> <out.md> [--dry-run]" >&2; exit 64; }
WT="${ARGS[0]}"; BASE="${ARGS[1]}"; CTX="${ARGS[2]}"; RUBRIC="${ARGS[3]}"; OUT="${ARGS[4]}"
MODEL="${CODEX_MODEL:-gpt-6-astra}"; EFFORT="${CODEX_EFFORT:-high}"; AUTH="${CODEX_AUTH_FILE:-$HOME/.codex/auth.json}"
command -v codex >/dev/null || { echo "codex CLI not found on PATH (install Codex CLI and log in)" >&2; exit 127; }
command -v git >/dev/null || { echo "git not found on PATH" >&2; exit 127; }
[ -f "$CTX" ] && [ -f "$RUBRIC" ] || { echo "missing context file or rubric file" >&2; exit 2; }
[ -z "${CODEX_SCHEMA_FILE:-}" ] || [ -f "$CODEX_SCHEMA_FILE" ] || { echo "missing schema file $CODEX_SCHEMA_FILE" >&2; exit 2; }
[ "$DRY" = 1 ] || [ -f "$AUTH" ] || { echo "Codex auth file not found: $AUTH (log in to Codex, or set CODEX_AUTH_FILE)" >&2; exit 2; }
git -C "$WT" rev-parse --verify -q "$BASE^{commit}" >/dev/null || { echo "base $BASE not found in $WT" >&2; exit 2; }
if [ -n "${CODEX_SCHEMA_FILE:-}" ]; then
  FORMAT="Follow the rubric exactly; emit findings in the output schema; security is out of scope.

## output schema

$(cat "$CODEX_SCHEMA_FILE")"
else
  FORMAT="Follow the rubric exactly; security is out of scope. Emit each finding with: severity, location (file:line), what, why, suggested fix."
fi
PROMPT="Review git diff $BASE...HEAD for correctness only. Do not spawn helper agents; work in one thread.

Product context: $(cat "$CTX")

Two named hunts (do both, and say in the review that you did):
(a) Any path where state changes but the caller is told failure, refusal or \"unchanged\" (and the reverse: the reply says set or changed but nothing changed).
(b) Any sentence in the changed docs (READMEs, contract docs, ADRs) that the code contradicts.

$FORMAT

## correctness rubric

$(cat "$RUBRIC")"
[ -n "${TAG:-}" ] && PROMPT="$TAG $PROMPT"
# A fresh minimal home per run, so the session log found below is this run's.
H="${TMPDIR:-/tmp}/codex-review-home-$(basename "$WT")"
HEAD_SHA="$(git -C "$WT" rev-parse --short=10 HEAD)"
if [ "$DRY" = 1 ]; then
  echo "head $HEAD_SHA, base $BASE, prompt $(printf '%s' "$PROMPT" | wc -c) chars"
  echo "cd $WT && CODEX_HOME=$H codex --search exec -m $MODEL -c model_reasoning_effort=$EFFORT -C $WT --skip-git-repo-check \"<prompt>\" < /dev/null > $OUT 2>&1"
  exit 0
fi
rm -rf "$H"; mkdir -p "$H"
ln -s "$AUTH" "$H/auth.json"
printf 'sandbox_mode = "read-only"\nmodel_reasoning_effort = "%s"\n' "$EFFORT" > "$H/config.toml"
USAGE="$(dirname "$0")/codex-usage.sh"
echo "before: $("$USAGE" 2>&1 || true)"
START=$(date +%s); set +e
(cd "$WT" && CODEX_HOME="$H" codex --search exec -m "$MODEL" -c model_reasoning_effort="$EFFORT" -C "$WT" --skip-git-repo-check \
  "$PROMPT" < /dev/null > "$OUT" 2>&1)
RC=$?; set -e
LOG="$(find "$H/sessions" -name '*.jsonl' 2>/dev/null | head -1 || true)"
# The next run wipes $H, so keep the session log where codex-usage.sh and cost reports can read it.
if [ -n "${LOOP_DIR:-}" ]; then BASE_DIR=$LOOP_DIR
elif C=$(git -C "$WT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then BASE_DIR=$(dirname "$C")/.loop
else BASE_DIR=$PWD/.loop; fi
ARCH="$BASE_DIR/codex-sessions"
if [ -n "$LOG" ]; then mkdir -p "$ARCH" && cp "$LOG" "$ARCH/"; fi
AFTER=""; if [ -n "$LOG" ]; then AFTER="$(grep -o '"used_percent":[0-9.]*' "$LOG" | tail -1 | cut -d: -f2 || true)"; fi
echo "after: codex weekly ${AFTER:-?}% used"
echo "exit $RC, $(( $(date +%s) - START ))s, head $HEAD_SHA"
echo "$OUT"
