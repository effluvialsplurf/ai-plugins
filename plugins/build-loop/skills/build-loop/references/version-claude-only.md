# Version: Claude only

For someone with a Claude Code plan and nothing else. No second vendor, so the review rule bends the most here, and the
checks that aren't a model's opinion carry more weight.

## Seats (copy into `.loop/SEATS.md`)

The agents inherit the controller's model, so when you copy this table write the model into each `.loop/SEATS.md` row
(planner and reviewer rows opus, builder rows sonnet) and set it per dispatch with the Agent tool's `model` parameter.

| Role | Use | Notes |
|---|---|---|
| Controller | this Claude Code session (Opus) | Kept thin; see `build-loop:context-costs` |
| Design trace | `build-loop:planner` | read-only brief |
| Plan: explorer, then one writer per task file | `build-loop:planner` | fresh agent for each |
| Plan check | `build-loop:reviewer`, fresh context, adversarial | checklist in `setup.md`; it never saw the plan being written |
| Plan fixes | `build-loop:planner`, fresh, one per affected task file | given findings, pack, task file |
| Build each task | `build-loop:builder` | |
| Task review | `build-loop:reviewer` | on tasks that change stored data or behaviour |
| Fix rounds | `build-loop:builder`, fresh, from the handoff | resume only if it reported under 5 minutes ago |
| Re-review after a behaviour fix | `build-loop:reviewer` | Sonnet built the fix, so Opus reviews it |
| Whole-branch review | `build-loop:reviewer`, fresh context | `deep-review:deep-review` rubrics |
| Live check | `build-loop:planner` | if PROJECT.md has one |

## Where the review rule bends

With the suggested seating, Sonnet builds and Opus reviews, so code gets a different model. The plan does not: Opus writes it and Opus checks it.
The plan check is typically the layer that catches the most correctness bugs, and ideally a different vendor runs it. So the plan check here is a known exception, and the loop makes up for it:

1. **Make the plan check adversarial and concrete.** A fresh reviewer that never saw the plan written, told to prove it
   wrong against the real code, with the checklist in `setup.md`.
2. **Lean on checks that aren't a model's opinion.** They cost nothing per PR and catch what a same-family reviewer
   shares a blind spot on:
   - a table of hard inputs (zero, blank, padded, overflow, wrong type) run against every write path;
   - invariants asserted in a shared test helper (a refused command changes nothing; a read changes nothing);
   - a scripted mutation check on each new guard (break the guard, the test must fail);
   - a test that fails when a fixture re-implements a production function.
3. **Keep the whole-branch review**, in a fresh context.
4. **Run the live check on every PR and keep it strict** until the tally shows the earlier layers catching its finds.
5. **Keep the escapes log from day one.** With one family doing all the reviewing, it is how you find the shared blind
   spot.

## Usage

Claude Code shows plan usage with `/usage` (or the account page); no script reads it. Read it at each PR's start and
end, and record both in LOOP-STATE.

On a subscription, Opus counts for more than Sonnet. Planners and nested controllers typically dominate Opus usage,
while reviews remain a small fraction — trim planner and controller context, not the reviews (`build-loop:context-costs`).

Near the limit: finish the task in flight, don't start the next one, leave LOOP-STATE resumable, and tell the person
when it resets.

## If you get a second vendor later

The highest-yield single seat is the plan check. Move that seat first; see `version-claude-codex.md` for the case.
