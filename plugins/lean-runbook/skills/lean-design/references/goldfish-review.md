# 3-Lens Fresh-Context Goldfish Review (Cross-Family)

This playbook replaces `/egm:egm-review` and `/egm:egm-resolve`. Every Goldfish critic is a **fresh
read-only worker** with **zero prior conversation history** (never fork the main context) so it
experiences the 3-doc suite exactly like a cold human engineer reading it for the first time.

> **Prerequisite:** `design_check.py check docs/designs/<slug>` MUST pass before launching Goldfish.
> Never waste critic tokens reviewing a bloated draft with broken IDs.

---

## 1. Critic Seat Assignment (Mandatory Cross-Family Verification)

Pick a dispatch tier (see `../../lean-runbook/SKILL.md`) and pin a model family different from `design-drafter`'s where available (models: your `harness-*.md`):

| Critic Seat | Name | Role & Model |
|---|---|---|
| **Lens 1: Clarity & Bloat Auditor** | `goldfish-clarity` | `reviewer`, fast model |
| **Lens 2: Adversarial Architect & Risk Critic** | `goldfish-architect` | `reviewer`, strongest model, **different family from `design-drafter`** |
| **Lens 3: Requirements & `lean-runbook` Handoff Auditor** | `goldfish-handoff` | `reviewer`, mid-to-strong model |

- Always record the actual Drafter + Critic models (from worker status) as a receipt at
  the top of `.loop/designs/<slug>/goldfish-report.md`:
  `Drafter: <model> | Clarity: <model> | Architect: <model> | Handoff: <model>`
- Never silently downgrade Lens 2 to the same vendor as `design-drafter`.

---

## 2. Exact Critic Briefs (Spawn All 3 in Parallel, Read-Only)

### Lens 1 — `goldfish-clarity` (Clarity, Ambiguity & Read-Time Compression)
```text
You are `goldfish-clarity`, a fresh-context reader with zero prior context.
Read ONLY:
- docs/designs/<slug>/design.md
- docs/designs/<slug>/tech-plan.md
- docs/designs/<slug>/spec.md

Do NOT edit any files. Audit strictly for:
1. Cold-reader comprehension: undefined jargon, implicit assumptions, ambiguous nouns, or hand-wavy verbs ("handles", "manages", "ensures appropriately").
2. Cross-doc duplication: flag ANY business requirement, rationale, or architecture prose repeated across design.md / tech-plan.md / spec.md that should be replaced with an ID citation (`BR-*`, `RISK-*`, `ADR-*`, `INV-*`).
3. Concrete bloat cuts: identify the top 3-5 paragraphs/tables that can be compressed or cut to pull total read time closer to 15-20 minutes without losing decisions or contracts.

Reply to the coordinator in <=45 lines grouped into: `BLOCKER` (ambiguity that would cause wrong code), `DUPLICATION`, and `CUT/TIGHTEN` (exact section + suggested replacement).
```

### Lens 2 — `goldfish-architect` (Adversarial Architect & Risk Elimination Auditor)
```text
You are `goldfish-architect`, an adversarial principal architect with zero prior context.
Read:
- docs/designs/<slug>/design.md
- docs/designs/<slug>/tech-plan.md
- docs/designs/<slug>/spec.md
- Any real codebase files cited in `tech-plan.md` (verify symbols/paths actually exist!)
- [REDESIGN MODE ONLY] The original input/rejected plan at `<input-doc-path>`

Do NOT edit any files. Attack the design ruthlessly:
1. Structural Risk Audit [Redesign mode]: For EVERY `RISK-*` (and any major risk in `<input-doc-path>` that the design forgot to list!), verify whether the new architecture **structurally eliminates** it vs merely renaming, relocating, or hoping monitoring catches it.
2. Failure Modes & Concurrency: Find race conditions, partial-failure states, split-brain ownership, retry storms, schema/migration deadlocks, or irreversible cutover cliffs.
3. Codebase Reality Check: Verify every existing repo file/symbol/constraint referenced in `tech-plan.md` is accurate.
4. Over-Engineering Check: Flag any abstraction, tier, or indirection that adds complexity without serving a `BR-*` or eliminating a `RISK-*`.

Reply to the coordinator in <=60 lines grouped into: `BLOCKER` (broken architecture / uneliminated risk / false repo claim), `TRADEOFF` (real design fork needing user ruling), and `OVER-ENGINEERING` (simplifications).
```

### Lens 3 — `goldfish-handoff` (Requirements & `lean-runbook` Execution Readiness Auditor)
```text
You are `goldfish-handoff`, a staff delivery engineer auditing execution readiness for `lean-runbook`.
Read:
- docs/designs/<slug>/design.md
- docs/designs/<slug>/tech-plan.md
- docs/designs/<slug>/spec.md
- `<absolute path to the lean-runbook SKILL.md; coordinator fills in>` (for slice rules)

Do NOT edit any files. Audit strictly for:
1. 100% Traceability: Does EVERY `BR-*` in `design.md`, EVERY `RISK-*` (if any), and EVERY `INV-*` in `tech-plan.md` map to at least one concrete `SLICE-*` and testable `CUJ-*` / `EDGE-*` in `spec.md`? Are any acceptance criteria untestable or vague?
2. `lean-runbook` Slice Hygiene: Can EVERY `SLICE-*` realistically land in <=3 commits and <=600 LOC? Flag oversized slices that must be split, hidden circular dependencies, or parallel waves touching overlapping files.
3. Cold-Start Handoff: Could `lean-runbook` (Single Slice, Mini-Series, or Epic Mode) start immediately from `spec.md` without re-brainstorming? Are Shared Contracts and quiet gate commands explicit?

Reply to the coordinator in <=50 lines grouped into: `BLOCKER` (missing traceability / oversized slice / unbuildable contract), `SLICE-SPLIT` (exact split recommendation), and `HANDOFF-GAP`.
```

---

## 3. Consolidating & Resolving (Zero-Bloat Resolution Protocol)

1. Coordinator merges all 3 responses into `.loop/designs/<slug>/goldfish-report.md` (**≤180 lines**), deduplicating overlapping issues into 4 buckets:
   - **`Blockers`** (must fix before approval)
   - **`User Tradeoffs`** (requires explicit user decision — present these as crisp A/B options)
   - **`Auto-Fixes & Duplication Cuts`** (Coordinator approves automatically without nagging the user)
   - **`Deferred / Rejected`** (1-line rationale)
2. Retire all 3 critics immediately (`goldfish-clarity`, `goldfish-architect`, `goldfish-handoff`).
3. Send the user's rulings + approved fixes + bloat cuts to `design-drafter` with the **Net-Zero Bloat Rule**:
   - *"Apply every approved resolution AND every `DUPLICATION` / `CUT/TIGHTEN` fix. Do not grow total word count above the tier budget. Run `design_check.py check docs/designs/<slug> --strict` and report the final read-time table."*
4. If a major architectural pivot occurred during Resolve (e.g., an entire subsystem or migration strategy changed), run **one targeted re-check** on `goldfish-architect` for the changed section only — never an endless review loop.
