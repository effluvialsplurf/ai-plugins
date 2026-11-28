---
name: lean-runbook
description: >-
  Use when asked to start, resume or check a lean runbook ("start lean runbook for <slug>", "start lean runbook
  epic for <epic>", "lean runbook status", "run the lean loop"), or to build a feature or epic that needs
  vertical-slice triage, a Goldfish-reviewed spec gate before code, and a TDD build loop.
---

# lean-runbook (Harness-Agnostic · Role-Based Seats)

A disciplined, token-budgeted workflow combining Stage 0 vertical-slice triage, EGM's fresh-context
Goldfish review, and **role-based worker orchestration** — scaling seamlessly from
single vertical slices to multi-worker **Epic Orchestration**.

Run state commands with the `lean-runbook` shim (on `PATH` after `install.sh`):

`lean-runbook <subcommand>`
*(No shim, e.g. the first `start` in a marketplace-only install? Run `python3 <skill dir>/scripts/runbook.py <subcommand>`, relative to this skill's own directory. Once a feature is active, the session-start context also prints the absolute path. The CLI and `templates/*.md` are pure Python 3.9+ stdlib and Markdown.)*

State lives outside the repo (`LEAN_RUNBOOK_DATA` or `~/.cache/lean-runbook/`) and is keyed per git working
tree, so parallel worktree workers automatically get independent Spec Gates. Lifecycle hooks
enforce the no-code-before-Goldfish gate and warn if specs or plans exceed the 300-line token budget.

## Roles & Dispatch Ladder

Seats use five abstract roles: `planner`, `builder`, `reviewer`, `explorer`, `orchestrator`. The `orchestrator` is
the main chat: it stays thin (user decisions, spec approval, `EPIC.md`/`LOOP-STATE.md`, merges) and never does
heavy reading, coding, or raw diff review. Dispatch every other role down this ladder, using the first tier that exists:
1. **native swarm** — the harness's own multi-agent or swarm tool, if it has one;
2. **`swarmctl`** — the local worker swarm, only if `command -v swarmctl` succeeds;
3. **native subagents** — the harness's fresh-context subagents;
4. **fresh sessions** — a new chat per role, handing off through the artifact files.

Never ask the user to define workers or model tiers. Prefer a strong model for `planner` and `reviewer`, a mid model
for `builder`, a fast one for `explorer`, and a different model family for the final `reviewer` when available.
Model names, tool calls, and quota routing live only in `references/harness-*.md`; read yours: [Claude Code](./references/harness-claude.md), [Antigravity](./references/harness-antigravity.md), or [generic](./references/harness-generic.md) (the fallback for any other harness).

## Stage 0: Pre-Flight & Scope Triage (BEFORE `lean-runbook start`)

> **Incoming from `lean-design` (`docs/designs/<slug>/spec.md`)?** If the user points to an approved
> `lean-design` suite (`design.md`, `tech-plan.md`, `spec.md`), **skip redundant brainstorming**:
> read `spec.md` directly (cite `BR-*`/`RISK-*`/`INV-*` by ID) and seed either `docs/specs/<slug>.md`
> (Single Slice), the approved Slice Roadmap (Mini-Series), or `.loop/epics/<slug>/EPIC.md` Sections
> 1–3 (Epic Mode) straight from `spec.md`. For project-level design/rearchitecture before implementation,
> invoke the sibling `lean-design` skill first.

Whenever the user asks to build a feature, feature set, or epic, **do not cram everything into one spec**:
1. **Pick a dispatch tier:** walk the ladder above and read your harness reference.
2. **Plan seats:** decide which tier serves each role before adding the first worker.
3. **Scout cheaply:** dispatch a read-only `explorer` (fast model) to inspect the touched repo area, then route using the **Scope & Vertical-Slice Rubric**:

| Signal | Single Slice (1 loop) | Mini-Series (2–4 sequential slices) | Epic Mode (`orchestrator` + slice workers) |
|---|---|---|---|
| **Estimated size** | ≤3 commits & ≤600 LOC | 4–10 commits (2–4 slices) | **>4 slices** or multi-system overhaul |
| **Subsystem span** | 1–2 tightly coupled layers | 3–4 layers with linear dependencies | Many interacting systems + parallelizable workstreams |
| **Requirements clarity** | Clear, bounded CUJs | Mostly clear; cleanly sliceable up front | **Heavy brainstorming / evolving scope / unforeseen work expected** |
| **Spec complexity** | ≤300 lines (≤10 key CUJs) | 2–4 compact specs | Needs a long-lived Epic Ledger (`EPIC.md`) + Discovery Inbox |
| **Risk isolation** | Uniform risk profile | 1 high-risk slice + low-risk plumbing | Mixed risks requiring per-slice pool routing & cross-slice integration gates |

**Routing action:**
- **Single Slice:** State briefly why it fits 1 slice (`~N commits, ~M LOC`) + your seat plan, and immediately run `lean-runbook start <slug>`.
- **Mini-Series (2–4 slices):** Propose a **Slice Roadmap table** (`Slice # | Slug | Testable Deliverable | Est. Commits/LOC | Depends On | Builder / Reviewer`), get user approval (suggest a short grilling interview if fuzzy), record deferred slugs in Slice 1's Out of Scope, start **Slice 1 only**, and recommend compacting or clearing context between slices.
- **Epic Mode (>4 slices, open-ended brainstorming, or parallel workstreams):**
  Keep the main chat a thin Epic Coordinator owning `epic/<epic-slug>` + `.loop/epics/<epic-slug>/EPIC.md` (from [templates/epic-ledger.md](./templates/epic-ledger.md)); dispatch one `builder` Slice Worker per slice in its own git worktree (≤3 concurrent, disjoint files) and review each on a different model family. Antigravity specifics: [harness-antigravity-epic.md](./references/harness-antigravity-epic.md); other harnesses follow its §2-4, substituting their own delegation tier for `swarm`, the `lean-runbook` shim (or `scripts/runbook.py`) for its install-specific script paths, and a fresh `reviewer` for its workflow-runner calls.

### Pre-Flight Environment Check
- **Quiet gate discovery:** Detect `tools/gate.sh` (or ask the user for the repo's quiet test command as the project's gate and fast commands).
- **Unattended workers:** workers that cannot prompt interactively need `tools/gate.sh` and `git` pre-approved (sandbox or allowlist).

## 5 Stages & Hard Budgets

| # | Stage | Seat (role) | Artifact & Hard Budget | Gate / Exit |
|---|---|---|---|---|
| 1 | **Compact EGM Spec** | `orchestrator` + read-only `explorer` | `docs/specs/<slug>.md` (**≤300 lines**, ≤3 commits / ≤600 LOC slice) + init `.loop/<slug>/LOOP-STATE.md` | Gate **CLOSED** (hook blocks repo code edits) |
| 2 | **2-Pass Goldfish Gate** | 2 parallel read-only `reviewer`s: `goldfish-clarity` (fast) + `goldfish-critic` (strong; verifies claims against real code) | `.loop/<slug>/goldfish-report.md` | Resolve findings with user → `done goldfish` (user approves; the hook asks) |
| 3 | **Contract Plan** | 1 fresh read-only `planner` | `.loop/<slug>/plan.md` (**≤300 lines**, signatures + invariants + test assertions only) | **Zero pasted full code; zero scratch-repo dry-runs** |
| 4 | **TDD Build Loop** | `builder` (mid model; parallel waves only on disjoint files) | Commits on the feature branch + `.loop/<slug>/LOOP-STATE.md` | 1-line quiet gate (`tools/gate.sh`) after every commit; fresh fixer on FAIL only (max 2) |
| 5 | **Adversarial Diff & Ship** | Fresh read-only `reviewer`, a different model family from the `builder` when available; if the families match, tell the user and record it in `branch-review.md`, and never claim cross-family when both are the same family | `.loop/<slug>/branch-review.md` (with `Builder:` & `Reviewer:` model receipt) → 1 fixer pass for blocker/high → PR/merge | Quiet gate green → `lean-runbook finish` → retire workers (suggest compacting context before next slice) |

## Organizing Agents
- **Keep the orchestrator thin:** never read large diffs or write slice code in the main chat.
- **Retire workers** once their output is consumed; move seats to whichever tier or model pool has capacity.
- **Per-harness details** (tool calls, model pools, workflows, quota rules): `references/harness-*.md`.

## 5 Non-Negotiable Anti-Bloat Rules
1. **Vertical Slices Only:** Always run Stage 0 triage first. Never put >3 commits or >600 LOC in one loop—split larger features into 2–4 sequential vertical slices.
2. **Tables Over Prose:** Use [templates/compact-spec.md](./templates/compact-spec.md), [templates/contract-plan.md](./templates/contract-plan.md), and [templates/loop-state.md](./templates/loop-state.md). Rejected alternatives are 1-line table rows, never essays.
3. **No Scratch-Copy Dry-Runs:** Planners are read-only and write contracts (signatures, invariants, edge-case tables, test assertions). Builders implement & run tests directly on the branch.
4. **1-Line Quiet Gate:** Every project should expose a quiet gate script (e.g., `tools/gate.sh`) that prints 1 line on PASS (`GATE OK`) and only the failing tail on FAIL.
5. **Respect the Spec Gate:** Never bypass the hook gate. When Stage 2 is resolved (or the user explicitly wants an override), run `lean-runbook done goldfish` or `lean-runbook skip gate --reason "..."` — the hook asks the user for explicit approval.

## Quick Commands
- Start slice: `lean-runbook start <slug> [--epic <epic-slug>]`
- Check status: `lean-runbook status` (or `lean-runbook status --all` / `--epic <epic-slug>` across worktrees)
- Mark stage done: `lean-runbook done <spec|goldfish|plan|build|review>` (user approves `goldfish`)
- Override gate: `lean-runbook skip gate --reason "<why>"` (user approves)
- Clear active feature: `lean-runbook finish`
