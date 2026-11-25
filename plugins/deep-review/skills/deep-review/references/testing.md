# Testing Rubric (adaptive adversarial)

Assess whether the change is meaningfully tested, then PROVE it as far as the
environment allows. ALWAYS do Tier 1. Escalate to Tier 2/3 when possible. State which
tier you reached (the orchestrator records it as `testing_tier`).

You are given: the diff, the changed files, the repo root, and the discovered test
command (may be empty). Emit findings per `output-schema.md`.

### Tier 1 — reason-only (ALWAYS run; zero side effects)
For each changed branch / guard / boundary ask: is there a test that FAILS if I break
this? Judge:
- Coverage: are the changed code paths exercised by any test?
- Assertion discrimination: does each assertion distinguish the right value from a
  wrong one? An assertion like "the rule uses key X" that passes on both `Equals(X)`
  and `NotEquals(X)` is hollow — flag it; pin the discriminating value exactly.
- Behaviour vs implementation: tests assert observable behaviour, not internal calls.
- Hollow tests: over-mocking that just asserts the mock; snapshots with no meaningful
  assertion.
- Missing edge cases: the None/empty/error paths added in this diff.
- Use dimensions: "Test coverage", "Assertion strength", "Test design".

### Tier 2 — prove a few (IF a test command exists AND isolation is possible)
- Pick the 3–5 highest-value mutations Tier 1 identified (flip a comparison, drop a
  guard, negate a condition, change a returned constant).
- Create a THROWAWAY git worktree — never touch the working tree:
  `git worktree add /tmp/deep-review-mut-$RANDOM HEAD`
- For each mutation: apply it in the worktree, run the test command scoped to the
  relevant tests, and record whether any test FAILED.
  - Docker projects: the suite often must run against the worktree via a bind-mounted
    `docker run` — NOT `docker compose exec`, which targets the main repo.
- A mutation that SURVIVES (tests still pass) = a real test gap → finding
  (dimension "Mutation survived", severity usually HIGH).
- ALWAYS clean up: `git worktree remove --force /tmp/deep-review-mut-<the-dir>`.

### Tier 3 — full mutation tool (ONLY if the repo already has one configured)
- If `mutmut` / `cosmic-ray` (Python) or `stryker` (JS/TS) config already exists, run
  it scoped to the changed files; report the mutation score and surviving mutants.
- Do NOT install a tool that isn't already present — that's Tier 2 territory.

### Degradation
If you cannot discover a test command or cannot isolate/run, stay at Tier 1 and SAY SO
explicitly in a finding (dimension "Tier", disposition defensible):
"Ran Tier 1 only — no runnable test command discovered." Never silently claim tests
pass.
