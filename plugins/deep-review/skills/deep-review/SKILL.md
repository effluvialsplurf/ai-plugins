---
name: deep-review
description: Ambitious, DRY three-axis code review of a diff — correctness (functional), structure/maintainability, and testing (adaptive adversarial). Writes a full review to docs/reviews/ in the repo and optionally posts user-curated PR comments. Use for "deep review", "deep-review", a thorough code-quality review of a branch or PR, or `/deep-review [axes] [fixed-point] [--comment]`. Security is out of scope — run /security-review separately.
---

# Deep Review

Three-axis code-quality review of a diff. Each axis is an isolated sub-agent driven by
a single rubric module; findings merge into one severity-ranked report written to
`docs/reviews/`, with an advisory verdict and optional user-curated PR comments.

**Security is NOT covered here — run `/security-review` (or your dedicated security review) for that.**

This skill is DRY by construction: review dimensions live ONLY in the rubric modules
under `references/`. This file contains process, never dimensions.

## Arguments

`/deep-review [axes] [fixed-point] [--comment]`

- `axes`: any of `correctness` `structure` `testing` (space- or comma-separated).
  Default: all three.
- `fixed-point`: commit SHA / branch / tag / `HEAD~n` / PR number. Default: the
  merge-base with `main`.
- `--comment`: after the review, offer to post user-selected findings to the PR.

## Process

### 1. Pin the diff (once)

- Resolve the fixed point. Default base: `git merge-base main HEAD`.
  - If a PR number was given: `gh pr view <n> --json baseRefName,headRefName,number`,
    then diff the head ref against the base ref.
- Capture once and reuse for every axis:
  - `DIFF` = `git diff <base>...HEAD`
  - `FILES` = `git diff --name-only <base>...HEAD`
  - `COMMITS` = `git log <base>..HEAD --oneline`
- If `DIFF` is empty, stop and report "no changes to review".

### 2. Gather project context

- Read the repo's `CLAUDE.md` / `AGENTS.md` (root, plus the nearest one to the changed
  files) for conventions and — importantly — the **test command**.
- Do NOT hardcode a test command; derive it from these docs. If none is found, the
  testing axis stays at Tier 1.
- Locate the repo's decision-records (ADR) directory — first match of
  `docs/decisions/`, `docs/adr/`, `docs/architecture/decisions/`, or a path named in
  `CLAUDE.md`/`AGENTS.md`. Capture `ADR_DIR` and the list of record filenames. If no
  such directory exists, leave `ADR_DIR` empty.

### 3. Fan out one sub-agent per requested axis (parallel)

Dispatch one fresh, read-only reviewer per requested axis:

- **Claude Code:** Send a single message with one `Agent` call per requested axis, with
  `subagent_type` `deep-review:axis-reviewer` (it carries only the tools a review needs,
  starting at a fraction of a general-purpose agent's context; fall back to
  general-purpose only if that agent type is unavailable).
- **Other harnesses (Antigravity, Codex CLI, Gemini CLI, Cursor, OpenCode, etc.):**
  Spawn one fresh read-only subagent/worker per requested axis in parallel using your
  harness's native mechanism (e.g., Antigravity `swarm` or `invoke_subagent`, or
  whatever subagent tool is available). For cross-vendor review, pin the reviewers to a
  different model family than the author.
- **Single-agent harnesses (no subagent tool):** Run each requested axis sequentially as
  an isolated pass, reading only that axis's rubric module during its pass before
  aggregating in Step 4.

Give each axis reviewer:

- the `DIFF`, `FILES`, and `COMMITS`;
- the path to its rubric module — `references/<axis>.md`, relative to THIS skill's own
  directory (resolve against the skill base dir you were given at invocation) — and an
  instruction to read it and follow it exactly;
- the path to `references/output-schema.md` (same skill dir) and an instruction to emit
  findings in that exact shape;
- signal discipline (NOT a count cap): report every finding that earns its place; lead
  with BLOCKER/HIGH; never drop or downgrade a real BLOCKER/HIGH/MEDIUM to keep the list
  short. Control noise by quality, not quantity — fold near-duplicate nits into one
  line, and omit purely cosmetic trivia that no reviewer would act on. A findings-rich
  diff SHOULD yield a long review; a clean one should yield a short one.
- permission to read full files listed in `FILES` for context, but to review only the
  changes in `DIFF`.

Axis → module:

- `correctness` → `references/correctness.md` (this axis MAY read beyond `FILES` to
  trace callers/consumers of changed signatures, return shapes, raised exceptions, and
  nullability for downstream breakage; findings still attach only to the `DIFF`)
- `structure`   → `references/structure.md` (ALSO pass `ADR_DIR` and its record list,
  and allow this axis to read those records in full — its decision-record-consistency
  check needs ADRs that the `DIFF` may not touch; this axis MAY ALSO grep/read beyond
  `FILES` to find existing canonical implementations its reuse check looks for, but its
  findings still attach only to the `DIFF`)
- `testing`     → `references/testing.md` (ALSO pass the discovered test command and
  the repo root; the rubric explains the tiered adversarial check)

### 4. Aggregate

- Collect every finding. Dedupe: same `location` + same point reported by two axes →
  keep the most severe; if their `resolution` differs, keep `judgment`; note both axes
  in `what`.
- Bucket by attention per the layout in `references/output-schema.md`:
  **attention** (any `judgment`, or correctness MEDIUM+) > **mechanical**
  (worth-fixing `mechanical`) > **noted** (`defensible`).
- Rank within each bucket by severity (BLOCKER > HIGH > MEDIUM > LOW), then by axis
  order (correctness, structure, testing).
- Assign stable IDs `F1…Fn` in that order — attention findings always get the lowest
  IDs.

### 5. Write the review file

- Path: `docs/reviews/<YYYY-MM-DD>-<slug>.md` in the repo, where `<slug>` is the
  branch name slugified, or `pr<n>` for a PR.
- Write frontmatter + body per the "Review file layout" in
  `references/output-schema.md` — sections keyed to human attention (attention /
  mechanical / noted / clean / appendix), NOT one section per axis. Full detail for
  non-attention findings lives in the appendix, never inline.
- Compute the advisory verdict:
  - any unresolved BLOCKER or HIGH ⇒ `REQUEST CHANGES`
  - else any MEDIUM or LOW ⇒ `COMMENT`
  - else ⇒ `APPROVE`

### 6. Terminal summary

Print, in order:

- The `## Needs your attention` findings **verbatim and in full** (`F-id`, severity,
  location, `what`, `why`, `suggested_fix`) — this is the part the human actually
  reads; if the section is empty, say `Nothing needs your attention.` explicitly.
- One line of counts for the rest: `N mechanical (agent-handleable) · N noted ·
  N clean checks`.
- The verdict, the path to the review file, and which testing tier ran.
- This footer verbatim:

`Security not assessed here — run /security-review (or your dedicated security review) for that.`

### 7. PR comments (only with `--comment`)

Curation is **entirely user-driven** — never auto-select by severity.

- Print the full ranked finding list with IDs (`F1` … `Fn`), each as a one-liner:
  `F3 [HIGH] app/foo.py:42 — <what>`.
- Ask: `Which findings to post to PR #<n>? (IDs like F1,F3,F7 / all / none)`.
- For the chosen IDs, show the EXACT inline comments that will be posted
  (file:line + body), then ask `Post these N comments? (y/n)`.
- Only on explicit `y`, post inline via `gh` (e.g.
  `gh api repos/{owner}/{repo}/pulls/{n}/comments` per finding, using the diff's
  file + line). Never post without confirmation.
- If the current branch has no PR, say so and skip posting.
