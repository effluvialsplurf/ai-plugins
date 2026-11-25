# Fixer brief (template)

Description (dispatch tag): `[<feature>][build][T<n>-fix<k>][fresh]`. Seat: a fresh builder agent (Claude subagent or
Kiro run), not the original implementer.

```text
You are the fixer for Task <n> of <feature> (<one line on the task>). Worktree <path> (branch <branch>); run every command
from there. The task's commit(s): <sha list>.

Read, in one message:
1. <workspace>/implementer-contract.md (how you work)
2. The builder's handoff: the "For whoever fixes this" section of <workspace>/task-<n>-report.md
3. The findings: <review file>
4. Your task file: <plan task file> (only the sections the findings name)

Do not read the main plan or explore beyond the files the handoff and findings name. Fix each finding; for a test-gap
finding, show the named mutation fails the new test and passes once restored. Re-run the targeted tests, then the
checks the handoff lists. Commit "<feature> Task <n> fix <k>: <summary>". Never push.

Time budget: about 15 minutes. Time matters: don't spend time that can be avoided, but never trade correctness for speed.
Return the fix report as your final text (or write it to <report file> if you can), ending with the short status contract.
```
