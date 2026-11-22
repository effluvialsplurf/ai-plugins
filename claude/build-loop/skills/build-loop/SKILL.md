---
name: build-loop
description: Use when setting up, starting, resuming or running a planned piece of work end to end with agents (design, plan, plan check, build, review, PR), where this Claude Code session is the controller and subagents or other models (Kiro, Codex) take the seats. Also on "run the loop", "set up the loop", "start a new plan", "start the loop from an egm design doc", or when the repo has a `.loop/` folder.
---

# Build loop

One long-running Claude Code session, the **controller**, takes a feature through fixed stages. It does little of the
work itself: it hands each stage to a fresh agent, reads the result, records it, and moves on. The human answers design
questions; the loop does the rest and stops only for what the human must decide.

Three ideas make it work:

1. **The plan carries the code.** The planner writes complete code and tests into the plan; builders transcribe and
   test. Lighter plans tend to reduce upfront planning cost at the expense of extra fix rounds and missed bugs.
2. **Nothing is signed off by the model that produced it.** A different vendor is best, a different model next, a fresh
   adversarial context last (and that is an exception to name, not the rule met).
3. **State lives in files, not in the conversation.** The controller can be compacted or restarted at any time and lose
   nothing.

How to keep a loop cheap (cost is calls times context) is the companion skill `build-loop:context-costs`. Read it
before the first build; it applies to any work with subagents, not only this loop.

## Setup: once per project

1. **Pick the version for the tools this person has.** Run `command -v codex; command -v kiro-cli`, propose a version
   from the table, and confirm it with the user before going on (having a CLI installed is not the same as having a
   plan that covers loop work).

   | Has | Version | Read |
   |---|---|---|
   | Claude Code only | Claude only | `references/version-claude-only.md` |
   | Claude Code + Kiro | Claude + Kiro | `references/version-claude-kiro.md` |
   | Claude Code + Codex (Kiro optional) | Claude + Codex | `references/version-claude-codex.md` |
   | Any other harness or model family (Gemini, OpenAI/Codex, Open-Weights, Cursor, OpenCode, Antigravity) | Custom / Agnostic | `references/version-custom-harness.md` |

2. **Make `.loop/` in the repo root** and add it to `.git/info/exclude` (or `.gitignore` if the team wants it).
   - `.loop/SEATS.md`: copy the chosen version's seat table. It is the one place that says which model does each role,
     so work can move when a limit is near. Read it at the start of every stage; a change takes effect on the next
     dispatch.
   - `.loop/PROJECT.md`: the five decisions, gate commands, live check, PR rules and standing permissions. The template
     and what each decision means are in `references/setup.md`.
   - `.loop/failure-classes.md`: copy `references/failure-classes.md` and grow it. Every brief links it.
3. **Bring it up in order** (`references/setup.md`, "Bring-up order"): one feature by hand, then two or three
   supervised PRs, then autonomous for defined plans only. Don't start autonomous.

## Each piece of work

Make `.loop/<slug>/` with `LOOP-STATE.md` and `FINDINGS.md` from `${CLAUDE_PLUGIN_ROOT}/templates/`. A resumed or
compacted session **reads LOOP-STATE.md first**, before anything in the conversation. Put that rule in the project's
CLAUDE.md too; it is re-read after a compaction.

Briefs and reports are files in `.loop/<slug>/` as well: an agent gets a brief file in and writes a report file out,
and the controller takes back only status, commits and concerns.

**Starting from an egm design doc (optional).** If the human gives a design doc from the egm plugin ("start the loop
from `docs/designs/x.md`"), ask once whether it has been through egm-review and egm-resolve. If not, don't start the
loop; tell the human to finish those egm steps first. If so, the controller records the doc as the design source by
setting `Design input: egm <doc> [report <path>]` in LOOP-STATE; the report is the egm review report, if the human has
one. Blank or absent means the stages below run as written. The human runs the egm skills beforehand (for example
`/egm:egm-draft`, `/egm:egm-review`, `/egm:egm-resolve`); the loop doesn't invoke them or dispatch egm's sub-agents
(`egm:egm-*`).

## Stages

| Stage | Do | Leave when |
|---|---|---|
| design | The design-trace seat traces what exists. Put numbered decisions to the human: domain questions first, then engineering defaults they can accept in one line, each with a recommendation. **Stop** for answers unless PROJECT.md's "how I answer design questions" settles them. With `Design input: egm`, see "Design input: egm" below. | Decisions recorded in LOOP-STATE |
| plan | The planner writes a full-code plan (superpowers:writing-plans format), each file under 1,000 lines. Split it: an explorer writes the skeleton (file map, interfaces, decisions) and a pack of the exact code tasks lean on; one fresh writer per task file. | Plan written |
| plan check | The plan-check seat tries to prove the plan wrong against the real code (checklist in `references/setup.md`). Fixes go to a fresh agent per affected task file, given the findings, the pack and the task file, never one agent over the whole plan. | No open blocker |
| build | superpowers:subagent-driven-development with the seats from SEATS.md. Copy `templates/implementer-contract.md`, `dispatch.md`, `task-review.md` and `fixer-brief.md` into `.loop/<slug>/`. One task at a time, a task review after each task that changes stored data or behaviour. Fix rounds go to a fresh builder fed the "For whoever fixes this" handoff. Every ruling goes in the ledger: `Ruling: what, why, cost if wrong`. | Every task complete |
| branch review | The whole-branch review seat reads the full diff (`deep-review:deep-review` rubrics). Fix real findings; one verification pass; only a new correctness finding earns another full pass. | Clean |
| check | Run the gate commands from PROJECT.md. If PROJECT.md has a live check, its seat runs it with PROJECT.md's limits written into the brief. | Gate green, live check recorded |
| pr | Push the branch and open the PR per PROJECT.md. Watch it with `scripts/watch-pr.sh` only where a bot comments. | PR open |
| done | Merge only if PROJECT.md grants it for this repo; otherwise hand the PR to the human. Note the result in LOOP-STATE and suggest what's next. | |

One plan ahead at most. A plan written long before the current PR's code is final gets re-checked against the merged
code before it is built.

**Design input: egm.** With `Design input` set (see "Each piece of work"):

- **Design:** the egm doc is the agreed design; don't redo it. The design-trace seat only reads and reports: it reads
  the doc (and the report, only if a path is given), traces the doc's claims against the real code, and proposes only
  what later stages need that the doc lacks, such as numbered decisions it leaves open. A contradiction between the
  doc and the code goes to the human as a numbered decision; the planner never settles it silently. If the doc has no
  open decisions and no contradictions, the seat's report lists what it traced (which doc claims it checked against
  which files), the controller writes "design: no open decisions" in LOOP-STATE, and design passes straight to plan
  without the human stop; the stop stays for any decision that does arise.
- **Plan:** the doc's "Detailed Implementation Plan" (files with rationale, no code) is input only. The plan is still a
  full-code plan in the format above; nothing from the egm section stands in for code or tests.

## Always

- **A ruling isn't made until it is written** into the plan or LOOP-STATE. Rulings made only in chat are lost at the
  next compaction.
- **Stop only for** a decision the human must make, a destructive or outward-facing step PROJECT.md doesn't grant, or
  a plan too broken to rule on. Everything else gets a ruling and the loop continues. When the human must act: one
  short notification, the question at the top of LOOP-STATE with a recommendation first, and the loop carries on with
  whatever doesn't depend on the answer.
- **Never end a turn with something in flight.** Start long jobs so their exit notifies the session; run one
  `scripts/stall-watch.sh` over all background jobs; give every dispatch a time budget in its brief.
- **Tag every dispatch**: start each agent description with `[slug][stage][task][fresh|resumed]` so the cost ledger can
  attribute it.
- **Cap review passes.** Reviews chase wording forever unless the rigor list in PROJECT.md says what counts. Only a
  functional finding earns another pass.
- **Turn a repeating finding into a check.** A class an expensive reviewer catches every time is a missing test or
  script. Add it to `.loop/failure-classes.md` when it repeats or cost a fix round.
- **Near a usage limit** (the version file says how to read each meter): stop starting new plans, finish the in-flight
  PR as the version file says, and leave LOOP-STATE resumable.
- One plain-English line per milestone in LOOP-STATE's log, so a person can follow from their phone.

## What ships with this plugin

| Path | Use |
|---|---|
| `agents/planner.md` | Opus. Design traces, plans, plan fixes, live checks |
| `agents/builder.md` | Sonnet. Build tasks, fix rounds, doc and skill updates |
| `agents/reviewer.md` | Opus. Plan checks, task reviews, branch reviews, re-reviews (read-only except its report) |
| `templates/` | LOOP-STATE, FINDINGS, implementer contract, dispatch, task-review brief, fixer brief |
| `scripts/stall-watch.sh`, `scripts/watch-pr.sh` | Waiting without stalling |
| `scripts/kiro-run.sh`, `scripts/kiro-usage.sh` | Kiro seats (Claude + Kiro and Claude + Codex versions) |
| `scripts/codex-review.sh`, `scripts/codex-usage.sh` | Codex seats (Claude + Codex version) |
| `scripts/loop_ledger.py`, `scripts/context_breakdown.py` | Cost by stage after every PR (see `build-loop:context-costs`) |

Script arguments are in each script's header comment. Run them as `${CLAUDE_PLUGIN_ROOT}/scripts/<name>` (outside Claude
Code, replace `${CLAUDE_PLUGIN_ROOT}` with your local checkout path to `claude/build-loop`, and see
`references/version-custom-harness.md` for harness/model substitutions). Scripts that
keep state default to `.loop/` at the main checkout's root (shared by every worktree); set `LOOP_DIR` to move it.
`codex-review.sh` takes the rubric as a file: pass the `deep-review` plugin's `references/correctness.md`.
`stall-watch.sh` and `codex-usage.sh` need GNU `find`/`stat` (Linux or WSL; on macOS install coreutils and findutils).

When copying a template into `.loop/<slug>/`, fill its `[PLACEHOLDERS]` before dispatch; agents and Kiro don't expand
variables.
