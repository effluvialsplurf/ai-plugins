# Version: Claude + Kiro

For someone with both Claude Code and a Kiro plan. Claude Code runs the loop; Kiro serves as the second vendor for
high-risk plan checks and as a reserve when Claude usage approaches its limit. Keep Kiro for targeted high-value seats
rather than running entire PRs end-to-end on it.

## Seats (copy into `.loop/SEATS.md`)

| Role | Use | Fallback | Notes |
|---|---|---|---|
| Controller | this Claude Code session (Opus) | | |
| Design trace | `build-loop:planner` | `kiro:claude-opus-5.5` | read-only brief |
| Plan: explorer, then one writer per task file | `build-loop:planner` | `kiro:claude-opus-5.5` | |
| Plan check | `build-loop:reviewer`, fresh, adversarial | | **plus** `kiro:gpt-5.6-sol` on high-risk plans (below) |
| Plan fixes | `build-loop:planner`, fresh, per task file | `kiro:claude-opus-5.5` | |
| Build each task | `build-loop:builder` | `kiro:claude-opus-5.5` | |
| Task review | `build-loop:reviewer` | | on tasks that change stored data or behaviour |
| Fix rounds | `build-loop:builder`, fresh, from the handoff | `kiro:claude-opus-5.5` | |
| Re-review after a behaviour fix | `build-loop:reviewer` | | |
| Whole-branch review | `build-loop:reviewer`, fresh | | |
| Live check | `build-loop:planner` | `kiro:claude-opus-5.5` | Kiro can't start a background server: the controller starts it first |

`kiro:<model>` means a run through `${CLAUDE_PLUGIN_ROOT}/scripts/kiro-run.sh` (arguments in its header).

## Kiro's two jobs

1. **A second vendor for the plan check.** Kiro offers GPT 5.6 Sol: not the current Codex generation, and the most
   expensive model on Kiro's list, but the only non-Claude reader you have. Spend it on high-risk plans only (ones that
   change stored data, money, or a path many features share). Optional trial: for your first three plans, run it beside
   the fresh Opus check and record what each finds in FINDINGS.md; if it finds nothing Opus didn't, stop paying for it.
2. **Reserve when the Claude seat runs low.** Kiro runs Claude models on its own meter, so it finishes an in-flight PR
   without changing who builds and who reviews. Don't start the next plan; finish the current PR's build tasks and fix
   rounds on Kiro (about 45 credits a task with its fix round), and stop there.

## Where the review rule bends

Same as Claude only, except on the high-risk plans that 5.6 Sol also reads. Opus writes the plan and Opus checks it, so
apply every compensation in `version-claude-only.md` ("Where the review rule bends"): adversarial plan check, hard-input
tables, invariant helpers, mutation checks, a strict live check, the escapes log.

## Calling Kiro

```bash
kiro-cli chat --no-interactive --model claude-opus-5.5 --effort high --trust-tools= "<prompt>" < /dev/null
```

Use `kiro-run.sh` for loop work rather than calling `kiro-cli` directly: it runs detached (survives a Claude Code exit),
tags the prompt with the run label, writes a `.done` marker and a credits line, and resumes after network drops.
Quirks already paid for:

- **Always pass `--model` and `--effort`.** Without `--effort` Kiro uses a default nobody can see.
- **`< /dev/null`**, or it can wait on stdin forever in a background shell.
- **It can't start a background server.** A `nohup ... &` never returns and the run hits the 90-minute cap. Start
  servers from the controller and tell the brief not to touch them.
- **Runs cap at 90 minutes.** Split briefs that might run longer; tell it to save the output file early.
- **Two runs in one work directory confuse each other** (session ids and credits get swapped). Give parallel runs
  different directories.
- **Watch finished runs with one watcher** over all `.done` files, not a wait per run: a wait that ends on any run
  reports only that one, and the rest sit unnoticed.
- **Never edit a running shell script in place**: bash reads scripts as it runs them. Write a new file and `mv` it over.
- Kiro loads its own steering files and skills from `~/.kiro/`. Say in the brief when a commit is wanted.
- Its code-search tool creates `.kiro/settings/lsp.json` in the work directory; remove `.kiro/` after a run.

## Credits

Model multipliers change over time — run `kiro-cli chat --list-models` to check current rates and meter your first run of
each job type. Set a monthly budget split up front (reserve a slice for high-risk plan checks and hold a buffer for
overflow) and record each run's `Credits:` line per PR. `scripts/kiro-usage.sh` prints the plan meter and the run ledger.
Credits reset at midnight UTC on the 1st, not local midnight.

## Asking for Codex

The smallest useful ask is one seat, the plan check: see "The case for a second vendor" in `version-claude-codex.md`.
