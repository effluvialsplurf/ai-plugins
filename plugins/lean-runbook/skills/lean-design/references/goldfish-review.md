# 3-Lens Fresh-Context Goldfish Review (Cross-Vendor · 3-Pool Balanced)

This playbook replaces `/egm:egm-review` and `/egm:egm-resolve`. Every Goldfish critic is a **fresh
read-only `swarm` worker** with **zero prior conversation history** (`fork` MUST be omitted) so it
experiences the 3-doc suite exactly like a cold human engineer reading it for the first time.

> **Prerequisite:** `design_check.py check docs/designs/<slug>` MUST pass before launching Goldfish.
> Never waste critic tokens reviewing a bloated draft with broken IDs.

---

## 1. 3-Pool Critic Seat Assignment (Mandatory Cross-Vendor Verification)

Check `swarm(action="models", all=True)` before spawning and pin exact opposite vendors from `design-drafter`:

| Critic Seat | `swarm` Name | Default Model & Pool | If `design-drafter` Used Neon/Gemini (Pool 1/3) | If `design-drafter` Used Claude (Pool 4 / Pool 2) |
|---|---|---|---|---|
| **Lens 1: Clarity & Bloat Auditor** | `goldfish-clarity` | **Pool 1:** `gemini-3.8-flash-medium` *(or `gemini-4-neon-medium`)* | `gemini-3.8-flash-medium` (Pool 1) | `gemini-3.8-flash-medium` (Pool 1) |
| **Lens 2: Adversarial Architect & Risk Critic** | `goldfish-architect` | **Strict opposite flagship vendor** | **Pool 4:** `claude-sub` (`opus`, `high`) or **Pool 2:** `claude-opus-5-5-high` *(fallback: `sonnet` `high`)* | **Pool 1:** **`gemini-4-neon-high`** *(preferred; fallback `gemini-4-argon-high` if Pool 1 < 25%)* |
| **Lens 3: Requirements & `lean-runbook` Handoff Auditor** | `goldfish-handoff` | **Neon or Claude** | **Pool 4:** `claude-sub` (`sonnet`) or **Pool 2:** `claude-sonnet-5-5-high` | **Pool 1:** **`gemini-4-neon-medium`** *(fallback `gemini-4-argon-medium`)* |

- Always verify the actual Drafter + Critic models via `swarm(action="status")` and record the receipt at
  the top of `.loop/designs/<slug>/goldfish-report.md`:
  `Drafter: <model> | Clarity: <model> | Architect: <model> | Handoff: <model>`
- Never silently downgrade Lens 2 to the same vendor as `design-drafter`.

---

## 2. Exact Critic Briefs (Spawn All 3 in Parallel, `workspace: "inherit"`)

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

Reply to @coordinator in <=45 lines grouped into: `BLOCKER` (ambiguity that would cause wrong code), `DUPLICATION`, and `CUT/TIGHTEN` (exact section + suggested replacement).
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

Reply to @coordinator in <=60 lines grouped into: `BLOCKER` (broken architecture / uneliminated risk / false repo claim), `TRADEOFF` (real design fork needing user ruling), and `OVER-ENGINEERING` (simplifications).
```

### Lens 3 — `goldfish-handoff` (Requirements & `lean-runbook` Execution Readiness Auditor)
```text
You are `goldfish-handoff`, a staff delivery engineer auditing execution readiness for `lean-runbook`.
Read:
- docs/designs/<slug>/design.md
- docs/designs/<slug>/tech-plan.md
- docs/designs/<slug>/spec.md
- ~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/SKILL.md (for slice rules)

Do NOT edit any files. Audit strictly for:
1. 100% Traceability: Does EVERY `BR-*` in `design.md`, EVERY `RISK-*` (if any), and EVERY `INV-*` in `tech-plan.md` map to at least one concrete `SLICE-*` and testable `CUJ-*` / `EDGE-*` in `spec.md`? Are any acceptance criteria untestable or vague?
2. `lean-runbook` Slice Hygiene: Can EVERY `SLICE-*` realistically land in <=3 commits and <=600 LOC? Flag oversized slices that must be split, hidden circular dependencies, or parallel waves touching overlapping files.
3. Cold-Start Handoff: Could `lean-runbook` (Single Slice, Mini-Series, or Epic Mode) start immediately from `spec.md` without re-brainstorming? Are Shared Contracts and quiet gate commands explicit?

Reply to @coordinator in <=50 lines grouped into: `BLOCKER` (missing traceability / oversized slice / unbuildable contract), `SLICE-SPLIT` (exact split recommendation), and `HANDOFF-GAP`.
```

---

## 3. Consolidating & Resolving (Zero-Bloat Resolution Protocol)

1. Coordinator merges all 3 responses into `.loop/designs/<slug>/goldfish-report.md` (**≤180 lines**), deduplicating overlapping issues into 4 buckets:
   - **`Blockers`** (must fix before approval)
   - **`User Tradeoffs`** (requires explicit user decision — present these via `ask_question` or crisp A/B options)
   - **`Auto-Fixes & Duplication Cuts`** (Coordinator approves automatically without nagging the user)
   - **`Deferred / Rejected`** (1-line rationale)
2. Retire all 3 critics immediately: `swarm(action="kill", name="goldfish-clarity")`, `goldfish-architect`, `goldfish-handoff`.
3. Send the user's rulings + approved fixes + bloat cuts to `design-drafter` with the **Net-Zero Bloat Rule**:
   - *"Apply every approved resolution AND every `DUPLICATION` / `CUT/TIGHTEN` fix. Do not grow total word count above the tier budget. Run `design_check.py check docs/designs/<slug> --strict` and report the final read-time table."*
4. If a major architectural pivot occurred during Resolve (e.g., an entire subsystem or migration strategy changed), run **one targeted re-check** on `goldfish-architect` for the changed section only — never an endless review loop.
