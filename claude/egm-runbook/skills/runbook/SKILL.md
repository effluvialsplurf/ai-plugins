---
name: runbook
description: Use when the user starts, resumes or asks about the per-feature egm + superpowers workflow ("start the runbook for <feature>", "where are we", "what's next", "runbook status", "skip the gate"). Tracks the nine steps from egm brainstorm to the optional drift report, shows the exact next command, and records overrides. Never runs egm skills itself.
---

# egm runbook

One feature, one fixed workflow. State lives in the plugin data dir (never in the repo); hooks block
code and build skills until the egm review is concluded.

Run every subcommand with:

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/runbook.py" --data-dir "${CLAUDE_PLUGIN_DATA}" <subcommand>`

(written `runbook <subcommand>` below). Run it from inside the repo.

## Steps

| # | Step | Who | Output |
|---|---|---|---|
| 1 | `/egm:egm-brainstorm` | user types | `concepts_brief.md` in the folder named by `EGM artifact directory:` in the project CLAUDE.md, else the repo root |
| 2 | `/egm:egm-draft` | user types | `docs/designs/<feature>.md` |
| 3 | `/egm:egm-review` | user types | review reports; the consolidated preset writes `consolidated_review_report.md` |
| 4 | `/egm:egm-resolve` | user types | approved fixes applied to the doc. **Gate: egm review concluded. No code in steps 1-4.** |
| 5 | `superpowers:writing-plans` | Claude, after user agrees | full-code plan with the egm doc as spec. Alternative covering 5-8: build-loop, "start the loop from docs/designs/x.md report <path>" |
| 6 | `superpowers:subagent-driven-development` | Claude, after user agrees | the build |
| 7 | `deep-review` on the diff, then `deep-review:receiving-deep-review` | Claude, after user agrees | `docs/reviews/<date>-<slug>.md` |
| 8 | `superpowers:finishing-a-development-branch` | Claude, after user agrees | PR or merge |
| 9 | `/egm:egm-drift-report` (optional) | user types | `<YYYY-MM-DD>_DRIFT_REPORT.md` |

## Subcommands

- `start <feature>`: create the state and make it active.
- `status`: where things stand plus the exact next command. Marks a step done when its artifact exists (brief, design doc, recorded review/plan/drift path, deep-review file); resolve, build and finish need `done`.
- `next`: just the next-command guidance.
- `record <artifact> <path>`: artifact is one of `brief`, `design`, `review`, `plan`, `deep-review`, `drift`.
- `done <step> [--reason "..."]`: step is 1-9 or a name (`brainstorm draft review resolve plan build deep-review finish drift`). For steps 1-4 `--reason` is required and the completion is logged in the overrides. **User-only for steps 1-4.**
- `skip <step> --reason "..."`: explicit override, logged with a timestamp. `skip gate --reason "..."` lifts the no-code gate and the blocked skills. **User-only.**
- `start <feature> --force` resets an existing feature (the old state is archived in `history/` and the override log is kept); without it `start` refuses (use `switch` to resume). **`--force` is user-only.**
- `switch <feature>`, `finish`.

## How to behave

- Present the next step plainly: the step, why, the exact command.
- **Never run an egm skill** (`/egm:*`); they are user-only. For steps 1-4 and 9, tell the user what to type, then wait.
- For steps 5-8, invoke the named skill only after the user agrees.
- Do not use `superpowers:brainstorming` for design work in this workflow; send the user to `/egm:egm-brainstorm`.
## Gate changes are the user's, never yours

Opening, bypassing or erasing the design gate is done only by the user, typing a `!` command at the prompt (the `!` prefix runs the command directly, outside your tools, so hooks do not see it). A hook denies these in your Bash tool:

- `done` for steps 1-4 (by number or name), any `skip`, `start ... --force`
- `record` of `brief`, `design`, `review` or `resolve`
- `finish` and `switch` while the gate is closed
- any command naming the runbook data dir or pointer file, and any Write/Edit into them

Never run these, never try another route to the same effect (editing the state files, `sed`, a different script path), and never retry a denied command. When the user wants to finish the egm steps or override the gate, show them the exact command to type, with the real path from `${CLAUDE_PLUGIN_ROOT}` filled in and their reason as a placeholder to complete:

`! python3 ${CLAUDE_PLUGIN_ROOT}/scripts/runbook.py done resolve --reason "..."`

`! python3 ${CLAUDE_PLUGIN_ROOT}/scripts/runbook.py skip gate --reason "..."`

The hook's deny message, the SessionStart context and `status` print the same commands, already filled in. You may still run `status`, `next`, `start <feature>` (without `--force`), `record plan|deep-review|drift <path>`, and `done` for steps 5-9, and only when the user says that step is finished.

## How to behave

- Present the next step plainly: the step, why, the exact command.
- **Never run an egm skill** (`/egm:*`); they are user-only. For steps 1-4 and 9, tell the user what to type, then wait.
- For steps 5-8, invoke the named skill only after the user agrees.
- Do not use `superpowers:brainstorming` for design work in this workflow; send the user to `/egm:egm-brainstorm`.
- If a hook blocks something, say why and ask the user whether to finish the egm steps or override the gate; the user types the command.
