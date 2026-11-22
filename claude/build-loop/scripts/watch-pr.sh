#!/usr/bin/env bash
# Blocks until something on a PR needs attention, then prints what and exits.
# Usage: watch-pr.sh <owner/repo> <pr-number> <seen-file> [interval-seconds]
# <seen-file> holds ids already handled, one per line (comment/review ids, and check:<sha10>:<name>
# lines exactly as printed). The script never writes it; the caller appends after handling.
# Prints "EVENT merged", "EVENT closed", "EVENT comments" (+ one line per new comment/review),
# or "EVENT checks-failed" (+ one check:<sha10>:<name> line per failed check). Needs gh, logged in.
# Run it in the background and re-launch it after handling each event.
set -euo pipefail
[ $# -ge 3 ] || { echo "usage: $0 <owner/repo> <pr-number> <seen-file> [interval-seconds]" >&2; exit 64; }
command -v gh >/dev/null || { echo "gh not found on PATH (install GitHub CLI and run gh auth login)" >&2; exit 127; }
REPO="$1"; PR="$2"; SEEN="$3"; INTERVAL="${4:-120}"
touch "$SEEN"

while true; do
  info=$(gh pr view "$PR" -R "$REPO" --json state,headRefOid --jq '"\(.state) \(.headRefOid)"' 2>/dev/null) || { sleep "$INTERVAL"; continue; }
  read -r state sha <<<"$info"
  case "$state" in
    MERGED) echo "EVENT merged"; exit 0 ;;
    CLOSED) echo "EVENT closed"; exit 0 ;;
  esac

  # Inline review comments (automated review bots post these) and top-level comments. Our own replies share the
  # PR author's login, so the caller records their ids in <seen-file> rather than the script filtering by author.
  new=$( { gh api "repos/$REPO/pulls/$PR/comments" --paginate --jq '.[] | "inline \(.id) \(.user.login) \(.path):\(.line // .original_line)"' ;
           gh api "repos/$REPO/issues/$PR/comments" --paginate --jq '.[] | "issue \(.id) \(.user.login)"' ;
           gh api "repos/$REPO/pulls/$PR/reviews" --paginate --jq '.[] | select(.state != "COMMENTED" or (.body | length) > 0) | "review \(.id) \(.user.login) \(.state)"' ; } 2>/dev/null \
         | while read -r kind id rest; do grep -qx "$id" "$SEEN" || echo "$kind $id $rest"; done || true)
  if [ -n "$new" ]; then echo "EVENT comments"; echo "$new"; exit 0; fi

  # Failed checks, keyed by head commit so a check failing again after a fix push is reported again.
  failed=$(gh pr checks "$PR" -R "$REPO" --json name,bucket --jq '.[] | select(.bucket=="fail") | .name' 2>/dev/null \
           | while read -r name; do grep -qx "check:${sha:0:10}:$name" "$SEEN" || echo "check:${sha:0:10}:$name"; done || true)
  if [ -n "$failed" ]; then echo "EVENT checks-failed"; echo "$failed"; exit 0; fi

  sleep "$INTERVAL"
done
