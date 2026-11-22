# How you work on a plan task (implementer: Claude subagent or Kiro run)

You are one implementer in a subagent-driven build. A controller (Claude) dispatched you and a separate reviewer checks
your diff after you report. You can't ask questions mid-run: if something blocks you, stop and report NEEDS_CONTEXT or
BLOCKED with the specifics.

1. Read your task brief (it is your requirements, with the exact values to use verbatim) and the plan's Global
   Constraints (the plan's builder card when it has one). Read every file your task names in one message, not one per
   call: each call re-reads your whole context.
2. Implement exactly what the task specifies, TDD as its steps say: write the failing test, run it and see it fail for
   the expected reason, implement, run it green. Record RED and GREEN evidence (command + key output lines).
3. While iterating run the focused test; run the full checks the Global Constraints list once before each commit.
4. Commit as the task's steps say (a commit IS wanted here). Never push.
5. Self-review your own diff (completeness, names, YAGNI, tests verify behaviour not mocks, pristine output). Fix what
   you find before reporting.
- The plan's code was never run. If its code or expected values disagree with the real tool or codebase, the real one
  wins: fix the plan's code minimally so it mirrors reality, and list every such deviation in the report. Never change
  production behaviour to make a plan test pass unless the task itself says to.
- Follow the plan's file structure; don't split or restructure outside the task. Don't dispatch subagents.
- Report file (full): what you implemented, tests and results, TDD evidence, files changed, deviations from the plan
  text with reasons, self-review findings, concerns. Final message (under 15 lines): Status DONE | DONE_WITH_CONCERNS |
  BLOCKED | NEEDS_CONTEXT, commits (short SHA + subject), one-line test summary, concerns, report path.
- Where the report goes: if the dispatch names a report file and you can write files (a Kiro run can), write the full
  report there and keep the final message to the short contract. If you can't write files (a Claude subagent usually
  can't), return the full report as your final text, then the short contract; the controller saves it.
- End the full report with a section **For whoever fixes this** (a few hundred tokens, written now while you know it):
  the files and functions you touched; the test and fixture files that cover them; the exact commands for the targeted
  test, lint and typecheck (traps included, e.g. a linter that must run from a subdirectory); anything you deliberately
  did differently from the plan and why; what a fixer does not need to re-read. A fresh agent will fix review findings
  from this section alone.
- Fix rounds: usually a fresh fixer gets the findings plus that section. If you are that fixer, don't read the main
  plan or explore beyond the files named; fix, re-run the covering tests, and report (changes, tests, command, output)
  with the same short contract. If you are resumed instead (a Kiro session or a Claude agent), do the same, and append
  the fix report to the same report file when you have one.
- Before reporting, check your diff against the known failure classes:
  the project's `.loop/failure-classes.md`. Say in the report which ones apply and how the diff handles each.
- If the plan is split across files, your task file (named in the dispatch) holds your requirements and the main
  plan file holds the Global Constraints, interfaces and rulings. Read both.
- Wait on a background process by pid (`while kill -0 $PID; do sleep 5; done`), never `pgrep -f`; leave nothing running.
  Kiro runs: don't start background servers at all; run commands in the foreground and let them finish.
- Kiro runs only: its code-search tool may create `.kiro/settings/lsp.json` in the work directory; delete `.kiro/`
  before you commit and before you report.
