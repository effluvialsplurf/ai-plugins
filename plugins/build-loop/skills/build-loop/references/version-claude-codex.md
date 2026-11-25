# Version: Claude + Codex (Kiro optional)

The full multi-vendor setup: Claude Code controls, plans and builds; Codex (OpenAI) reviews; Kiro, if you have
it, is the reserve. Every review is cross-vendor, so the review rule holds without exceptions.

## Seats (copy into `.loop/SEATS.md`)

| Role | Use | Fallback | Notes |
|---|---|---|---|
| Controller | this Claude Code session (Opus) | | |
| Design trace | `build-loop:planner` | `kiro:claude-opus-5.5` | read-only brief |
| Plan: explorer, then one writer per task file | `build-loop:planner` | `kiro:claude-opus-5.5` | |
| Plan check | `codex:gpt-6.1-sol`, effort high | `codex:gpt-6-astra` | nobody waits on it, so the cheaper model |
| Plan fixes | `build-loop:planner`, fresh, per task file | `kiro:claude-opus-5.5` | |
| Build each task | `build-loop:builder` | `kiro:claude-opus-5.5` | |
| Task review | `codex:gpt-6.1-sol` | `build-loop:reviewer` | rubric pasted into the prompt, read-only |
| Fix rounds | `build-loop:builder`, fresh, from the handoff | `kiro:claude-opus-5.5` | |
| Re-review after a behaviour fix | `codex:gpt-6.1-sol` | `build-loop:reviewer` | never Sonnet: Sonnet built the fix |
| Whole-branch review | `codex:gpt-6-astra` via `scripts/codex-review.sh` | `build-loop:reviewer` | correctness rubric only, one thread |
| Live check | `build-loop:planner` | `kiro:claude-opus-5.5` | |

`codex:<model>` means `codex exec`; `kiro:<model>` means `scripts/kiro-run.sh` (see `version-claude-kiro.md` for Kiro).
Model names were current on 2026-10-04; check what your Codex CLI offers.

## Calling Codex

```bash
codex --search exec -m gpt-6.1-sol -c model_reasoning_effort=high "<prompt>" < /dev/null > .loop/<slug>/raw/<job>.md 2>&1
```

- **`--search` goes before `exec`** (top-level flag). It gives the model live web search with page opening, so
  reviewers can open the docs a change cites; the read-only sandbox still blocks network calls from the shell.
- **Always `< /dev/null`.** Without it `codex exec` waits on stdin forever in a background shell.
- The answer is the text after the last line that is exactly `codex`, up to `tokens used`. Copy only that into
  FINDINGS or the report; keep raw output in a machine folder, not next to the files people read.
- `codex review --base` can't take a prompt, so use `codex exec` with the rubric text pasted in. Codex's sandbox may not
  read `~/.claude`, so paste rubrics rather than pointing at plugin paths.
- **Run reviews with a minimal `CODEX_HOME`** (what `codex-review.sh` does). Codex's own `AGENTS.md` can pull in your
  personal instructions and skew a review.
- **Don't tell a reviewer to "stop" when blocked.** Reviewers can abort the whole brief on that wording. Say:
  "leave that item, carry on with what doesn't depend on it, and report it".
- Narrowing the whole-branch review to the correctness rubric in one thread cuts usage substantially while keeping
  High-severity coverage intact.

## The case for a second vendor

A second model family catches blind spots that a single family shares with itself:

- Cross-family plan checks catch subtle contract and wiring bugs before any code is written, which is far cheaper than
  discovering them during build or post-PR review.
- Cross-family whole-branch reviews reliably spot classes of bugs that same-family task reviews can gloss over (such as
  tests disabling behaviour that production enables).

The point is diversity of perspective — a second model family notices different failure modes — not that one model is
universally better. Track your own findings tally to verify where each seat pays off.

## Usage

`scripts/codex-usage.sh` prints the weekly `used_percent` from the newest Codex session log. It shows the last account
that ran, so after switching accounts, run any small `codex exec` first. Check it after every Codex run and at the
start of each stage; tell the person at 25, 50, 75 and 95 percent.

At about 95%: let a Codex run already in flight finish, start no new one, and either move Codex seats to their fallback
for the rest of the PR or pause Codex-dependent work, whichever PROJECT.md's budget says. Record which in LOOP-STATE.
