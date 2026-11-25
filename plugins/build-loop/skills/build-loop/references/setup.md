# Setting up a loop for a project

Guide for setting up an autonomous build loop on a project. The core lesson: build cost controls and measurement in
from the first PR, not after the fact.

## The five decisions

Write these into `.loop/PROJECT.md` before anything is built. They are the loop's spec.

1. **What "rigor" means for this project.** Three to five things that must never reach a merged PR, stated so a
   reviewer can check them. One loop's list: a wrong stored record; a command that differs from what a person's click
   does; a refusal that comes after a change already happened; a read that changes data. Everything else (wording,
   style) is out of scope for fix rounds. Without this list, reviews chase wording forever.
2. **What the human decides.** Which calls stop the loop (real design decisions) and which it rules on and logs. Keep a
   short "how I answer design questions" list it applies first (for example: "keep the old behaviour behind a flag",
   "refuse rather than guess").
3. **What it may touch.** Test data it may reset, local servers it may restart, whether it may push, open PRs or
   merge. Never shared or production environments unless named here. Standing permissions can also go in the repo's
   `CLAUDE.local.md`.
4. **The usage budget.** Which plans the person has and which is scarcest. That decides the version and when to move
   seats.
5. **How you'll know it's working.** See "Measure from the first PR". Decide now.

## PROJECT.md template

```markdown
# <project> loop

## Rigor (never reaches a merged PR)
1.

## How I answer design questions
-

## Permissions
- May touch:
- May not touch:
- Push / open PR / merge:

## Gate commands
- tests:
- typecheck / lint / format:

## Live check
<environment, test data, reset command, what may and may not be touched, or "none">

## PR rules
- target branch:
- body must have:

## Budget
- plans:
- scarcest:
```

## Plan check checklist

Hand this to the plan-check seat with the plan, told to prove the plan wrong against the real code:

- Every claim about existing code cites the function that proves it, and the checker re-reads that function (not its
  name).
- Every path the plan relies on is really reached in production (live values, not just code that exists).
- Every test uses the real class. A stand-in is labelled, justified, and carries the members the real one has.
- Every value a command sends has a named source the code can read.
- Every new write refuses bad input (blank, zero, padded, overflow, wrong type) before any change.
- The failure classes in `.loop/failure-classes.md`.

## Bring-up order

Each step should work before the next.

1. Write the five decisions and the rigor list.
2. Run one feature by hand through every stage with the skills you already use. Note every place you stepped in; those
   become rules in PROJECT.md.
3. Set up `.loop/` (SEATS, PROJECT, failure classes). Restart the session so the plugin's agent definitions load.
4. Run two or three PRs supervised: you approve each stage change. Measure them; this is your baseline.
5. Write scripts for whatever the controller did by hand more than twice (build, restart, test gate, PR chores). One
   line on success, only the failure otherwise.
6. Go autonomous for defined plans only. It stops for design decisions and anything outside PROJECT.md's permissions.
7. After 8 to 10 PRs, tally. Trim a layer only if the tally shows it catching nothing the others don't, and write down
   what would catch its findings instead.

## Where the checks pay

In practice, check layers pay off roughly in order of how early they run, while staying a small share of total tokens:

| Layer | Role | Relative cost |
|---|---|---|
| Plan check, before any code exists | Catches the majority of correctness bugs cheapest | Low |
| Task reviews | Catches implementation bugs before later tasks build on them | Low |
| Whole-branch review | Catches cross-task integration and contract drift | Low |
| Live check, blind test, static analysis | Safety net for real-runtime timing and live-data issues | Small |

Never skip the plan check, keep task reviews on code tasks, and cap fix passes. Keep the live check strict until your
own findings tally shows earlier layers reliably catching runtime issues. A recurring finding across loops is a test
that runs a stand-in instead of the real implementation.

## Measure from the first PR

Reconstructing cost ledgers from raw transcripts after the fact leaves controller spend hard to attribute. Instrument
from day one:

1. **Tag every dispatch** `[slug][stage][task][fresh|resumed]`.
2. **Cost ledger** after every PR: `scripts/loop_ledger.py` (cost by stage) and `scripts/context_breakdown.py` (what
   one job's context is made of). Keep the output in `.loop/<slug>/`.
3. **Findings tally** from each FINDINGS.md: by stage and by kind.
4. **Escapes log** (`.loop/ESCAPES.md`): any bug found after merge, the PR that introduced it, and the layer that should
   have caught it. It is the only measure of what every layer missed, and the most important one when one vendor does
   most of the reviewing.
5. **The real meters**: each plan's usage percent at each PR's start and end.

To trial a change: change one thing, record which PRs had it on, compare against the PRs before, and decide in advance
what result means revert.

## Mistakes already paid for

| Mistake | Instead |
|---|---|
| Planning on code paths nobody proved run in production | The plan cites the function that proves each claim; the plan check verifies it |
| Tests built on stand-ins that behave unlike the real thing | Real classes; stand-ins labelled and justified |
| Writing the next plan long before the current PR's code is final | One plan ahead at most, re-checked against the merged code |
| Review passes that keep finding new wording and new tests | Cap the passes; only a functional finding earns another |
| Rulings made in chat and never written down | A ruling isn't made until it is in the plan or LOOP-STATE |
| Resuming from memory of the conversation | Read LOOP-STATE first, always |
| One agent that explores, writes, fixes and verifies | A fresh agent per phase |
| A detached job that finished silently | Start jobs so their exit notifies the session; one stall watcher over all of them |
| Measuring after the fact | Tags and the ledger from the first PR |
