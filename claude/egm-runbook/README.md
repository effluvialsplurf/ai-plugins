# egm-runbook

A per-feature runbook for one fixed workflow: egm design first, then the superpowers build. It tracks where the feature is, tells you the exact next command, and blocks code and build skills until the egm review is concluded.

## Steps

1. `/egm:egm-brainstorm` -> `concepts_brief.md` (in the folder named by the `EGM artifact directory:` line of the project CLAUDE.md, else the repo root)
2. `/egm:egm-draft` -> `docs/designs/<feature>.md`
3. `/egm:egm-review` -> review reports (`consolidated_review_report.md` for the consolidated preset)
4. `/egm:egm-resolve` -> approved fixes applied. **Gate: no code in steps 1-4.**
5. `superpowers:writing-plans` with the egm doc as spec (or build-loop started from the egm doc, which covers 5-8)
6. `superpowers:subagent-driven-development`
7. `deep-review` on the diff, then `deep-review:receiving-deep-review`
8. `superpowers:finishing-a-development-branch`
9. Optional: `/egm:egm-drift-report`

egm skills are user-only (`disable-model-invocation`), so Claude tells you what to type for steps 1-4 and 9 and never runs them.

## Use

`/egm-runbook:runbook start <feature>`, then `status`, `next`, `record <artifact> <path>`, `done <step>`, `skip <step> --reason "..."`, `switch <feature>`, `finish`. `status` marks a step done when its artifact exists on disk; resolve, build and finish need `done`.

State is kept in the plugin data dir (`${CLAUDE_PLUGIN_DATA}`; files are written atomically), keyed by repo and feature: `STATE.md` (readable) and `state.json`. Nothing is written into the project repo.

## Hooks

- SessionStart: injects the active feature, step and next command; shows any `*.md` alerts in `~/.claude/workflow-alerts/` as a warning (even with no feature active).
- UserPromptSubmit: one-line reminder of the step and next command.
- PreToolUse on Write/Edit/MultiEdit/NotebookEdit: while steps 1-4 are open, blocks code files (by extension) inside the repo. Markdown, anything under `docs/` and the egm artifact directory are allowed.
- PreToolUse on Bash: denies gate-changing runbook commands and commands naming the state location (see Override). Also guards Write/Edit/MultiEdit/NotebookEdit into the state location.
- PreToolUse on Skill: blocks `superpowers:writing-plans`, `subagent-driven-development`, `executing-plans`, `build-loop:build-loop`, and `superpowers:brainstorming` while steps 1-4 are open.

Hooks print nothing when the repo has no active feature, and fail open on any internal error.

## Override

Overrides come only from the user, typed at the Claude Code prompt with the `!` prefix, never from Claude:

```
! python3 <plugin-dir>/scripts/runbook.py skip gate --reason "..."
! python3 <plugin-dir>/scripts/runbook.py done resolve --reason "..."
```

`skip gate` marks the remaining steps 1-4 skipped, logs the reason and time in `STATE.md`, and lifts the blocks. `done <step> --reason` on a design step (1-4) is logged as a completion. Steps whose artifact exists are marked done automatically, with no override. The deny messages, the SessionStart context and `status` print these commands with the real path filled in while the gate is closed.

`!` shell-mode commands do not trigger PreToolUse hooks. This was verified by testing (a logging Bash PreToolUse hook saw Claude's own Bash calls but not a typed `! command`) and matches the hooks documentation: "PreToolUse runs only when Claude calls a tool." So the hooks only ever see Claude's tool calls, and a PreToolUse hook on Bash can deny Claude's attempts to run gate-changing commands while the user's own commands pass.

Denied when Claude runs them through Bash: `done` for steps 1-4 (by number or name), any `skip`, `record` of `brief`, `design`, `review` or `resolve`, `start ... --force`, `finish` and `switch` while the gate is closed, and any command naming the data dir or pointer file. Writes to the data dir or pointer file are denied at every step. `start --force` archives the old state under `history/` and carries the override log forward, so a restart never erases it.

## Known gaps

- The Bash block matches command text. It stops accidental and casual self-overrides, not deliberate obfuscation. How it matches:
  - Backslash-newline is removed as the shell does, `$'...'` is decoded (simple escapes, `\xHH`, octal, `\u`), and `2>&1`, `>&`, `&>` stay part of the redirect.
  - Here-doc bodies are skipped. They are scanned only when the command the here-doc belongs to is a shell (`bash <<EOF`, `bash <<'EOF' 2>&1`, `<<EOF bash`), or when the delimiter is unquoted so the shell expands `$( )` in them. `$( )`, backticks, the string given to `sh -c`/`bash -c` (after any further option words, such as `--`) and the arguments of `eval` are scanned again as shell text.
  - Any token whose basename is `runbook.py` or `runbook`, or an unquoted glob that can match `runbook.py`, counts wherever it sits in the command. Wrappers such as `timeout`, `sudo`, `env`, `{ }`, `if`/`for` bodies, `xargs` and `find -exec` need no special handling. A script path counts even when quoted or when it contains a space. The words after it, minus redirection operators and their targets, are read as runbook arguments. Other quoted text (commit messages, `grep` patterns, `echo` strings) is ignored.
  - Nesting depth is capped at 4 and the nested rescans of one command at 64. When either cap is hit, the command is denied with "command too complex for the runbook gate check; ask the user to run it", unless a precise gate hit is found first.
- Accepted false positives (denied although harmless): an unquoted mention such as `grep -n runbook.py skip file` or `echo runbook.py skip gate` (quote the text: `grep -n "runbook.py skip" file`); a quoted bare `"runbook"` or a quoted path ending in `runbook.py` followed by words such as `done` or `skip`; any command whose text contains the data dir or pointer location as a substring, such as `~/.cache/egm-runbook-notes`; and a command nested deeper than the caps.
- Accepted gaps: a relative path to the state files after `cd`; the script path held in a variable; copying or symlinking the script under another name; `python3 -c` (or `python3 - <<EOF`) importing the module; a pipe or here-string into a shell (`echo "..." | bash`, `bash <<<"..."`); a quoted command string handed to a program other than a shell (for example `ssh host 'python3 .../runbook.py skip gate'`); here-doc delimiters other than a quoted string or letters, digits and underscores (for example `<<END-1`); escaped or nested backticks; and other built-up strings.
- The CLI rejects option abbreviations (`--cw`, `--fo`); the hook also treats any prefix of a known option as that option.
- Code written through Bash (`sed`, heredocs, `tee`) is not blocked: the Bash hook only guards the runbook's own commands and state.
- "Code" is decided by file extension only; `Makefile`, `Dockerfile` and `Jenkinsfile` are matched by name, and `.ipynb`, `.tf` and `.hcl` count as code. JSON and YAML are allowed.
- A symlink inside the repo that points outside it is resolved first, so a code file reached that way is not blocked.
- One active feature per repo. `start` refuses to overwrite an existing feature without `--force`; `switch` changes the active one.
- If the active feature's `state.json` is unreadable, the hooks fail open (the gate is off) and SessionStart and UserPromptSubmit say so.

## Status line (optional)

A plugin cannot set the status line. Point your own settings at the script:

```json
{ "statusLine": { "type": "command", "command": "python3 /path/to/egm-runbook/scripts/statusline" } }
```

The status line process has no `CLAUDE_PLUGIN_DATA`, so every hook run leaves a pointer to the data dir at `~/.cache/egm-runbook/data-dir`; the script reads it (or `--data-dir <path>`). The pointer is one per user, not per install: with several installs (for example from different marketplaces) the one used last wins. It prints `runbook: my-feature · 6/9 build`, or nothing without an active feature.

## Install

From the marketplace: `/plugin install egm-runbook@ai-plugins`. To try a checkout without installing: `claude --plugin-dir claude/egm-runbook`. Requires Python 3.9+; standard library only.

## Tests

`python3 -m unittest discover -s claude/egm-runbook/scripts/tests` from the repo root.
