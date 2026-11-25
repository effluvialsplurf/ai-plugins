---
name: lean-design
description: >-
  Replaces EGM in its entirety for creating concise, decision-dense project design suites
  ("start lean design for <slug>", "redesign <project> from <input-doc>", "rearchitect <system>",
  "create design doc and spec for <project>", "lean design status", "lean design drift report").
  Produces exactly 3 zero-duplication documents under docs/designs/<slug>/ — design.md (Design Doc),
  tech-plan.md (Technical Plan), and spec.md (Lean-Runbook Handoff Spec & Implementation Plan) —
  calibrated to a 15-20 minute total read time (60-minute hard ceiling for drastic platform
  rearchitectures). Supports both greenfield design and critique-driven rearchitecture from an
  existing/rejected plan (extracting and structurally eliminating its risks), uses 3-pool native
  swarm routing (never /teamwork) for fresh-context cross-vendor Goldfish review, and enforces
  read-time budgets and 100% BR/RISK/INV/SLICE traceability via design_check.py.
---

# lean-design (Full EGM Replacement · 15–20 Min Read Budget · `lean-runbook` Native)

A general-purpose, token- and reader-budgeted replacement for EGM (`egm-brainstorm` → `egm-draft` →
`egm-review` → `egm-resolve` → `egm-drift-report`). It produces **three tightly coupled, zero-duplication
documents** that a human engineer can read thoroughly in **15–20 minutes** (absolute ceiling **≤ 60 minutes**
for sweeping platform rearchitectures) and that **`lean-runbook`** can execute directly without re-brainstorming.

Run tracker and budget/traceability validator commands with:

`python3 ~/.gemini/config/plugins/lean-runbook/skills/lean-design/scripts/design_check.py <subcommand>`
*(Outside Antigravity, substitute the path to `design_check.py` in your local `ai-plugins` checkout or installed skills directory — the script and templates are 100% pure Python 3.9+ stdlib and Markdown with zero harness dependencies.)*

> **NEVER use `/teamwork` with `lean-design`!** Orchestrate directly in a normal Antigravity 2.0 chat
> using native **`swarm`** across all 3 quota pools (Pool 1: Gemini Models, Pool 2: Claude & GPT,
> Pool 3: Gemini 4 Argon) per `../lean-runbook/references/quota-routing.md`.
>
> **Using outside Antigravity 2.0 or with other model families?** `design_check.py` and `templates/*.md`
> work unmodified anywhere. Map the 4 abstract roles (`design-scout` = fast reader, `design-drafter` =
> strong architect/writer, `goldfish-*` = fresh-context critics with cross-vendor preferred for
> `goldfish-architect`, `drift-auditor` = fast auditor) onto your harness's subagents or fresh sessions.
> For permanent conversion prompts per harness/model family, see `docs/CONVERSION-PROMPTS.md` in the
> `ai-plugins` repository.

---

## Output Suite & Strict Read-Time Budgets

All final outputs live in `docs/designs/<slug>/` (override only if the user specifies a different folder).
Working scratch (Elephant brief & Goldfish reports) lives in `.loop/designs/<slug>/` and is **not** part
of the reader-facing suite.

| # | File | Owns (Single Source of Truth) | Canonical IDs Defined | Standard Target (15–20 min total) | Complex Ceiling (`--complex`, ≤60 min total) |
|---|---|---|---|---|---|
| 1 | `design.md` | Problem, goals, non-goals, Business Requirements, *(if redesign)* Input Risk Audit, target architecture (1 Mermaid diagram + component table), key ADRs & 1-line rejected alternatives | `BR-*`, `RISK-*`, `ADR-*` | ≤ 1,400 words (~7 min) | ≤ 3,600 words (~18 min) |
| 2 | `tech-plan.md` | Subsystem boundaries, data/state contracts (no pasted code), protocols & failure modes, system invariants, risk-elimination verification, migration/cutover/rollback, cross-cutting budgets | `INV-*` (references `BR-*`, `RISK-*`, `ADR-*`) | ≤ 1,400 words (~7 min) | ≤ 3,600 words (~18 min) |
| 3 | `spec.md` | Executable `lean-runbook` handoff: 100% Traceability Matrix, Shared Contracts Seed, acceptance criteria, and either a Single-Slice spec OR a Mini-Series / Epic Vertical Slice Roadmap (`≤3 commits / ≤600 LOC` per slice) | `SLICE-*`, `CUJ-*` (maps 100% of `BR-*`, `RISK-*`, `INV-*`) | ≤ 1,200 words (~6 min) | ≤ 3,300 words (~16 min) |
| **Total** | **3-doc suite** | **Zero duplicated prose across files** | **100% closed traceability** | **≤ 4,000 words (15–20 min)** | **≤ 10,500 words (≤ 55–60 min hard cap)** |

*Technical read time is computed by `design_check.py` as `words / 200` + `0.5 min` per Mermaid diagram / complex table.*

---

## 5-Stage Workflow (Replaces Full EGM Lifecycle)

| # | Stage | Default Native `swarm` Seat & Pool | Output | Exit Gate |
|---|---|---|---|---|
| 0 | **Intake & Recon** | Thin Coordinator + `design-scout` (**Pool 1:** `gemini-3.8-flash-low`, read-only) | Mode (`greenfield` \| `redesign`), tier (`standard` \| `complex`), `.loop/designs/<slug>/recon.md` (≤120 lines) | `design_check.py init <slug> ...` |
| 1 | **Elephant Interrogation** | Main chat (thin Coordinator + user via `ask_question`) | `.loop/designs/<slug>/brief.md` (≤100 lines, locked rulings) | User confirms brief rulings → `design_check.py done brief <slug>` |
| 2 | **Budgeted 3-Doc Draft** | `design-drafter` (**Pool 1:** `gemini-4-neon-high` preferred, or **Pool 4:** `claude-sub` / **Pool 2:** `claude-sonnet-5-5-medium`, read-only on codebase, writes only `docs/designs/<slug>/`) | `design.md`, `tech-plan.md`, `spec.md` | `design_check.py check docs/designs/<slug>` passes (budget + ID traceability + anti-bloat) → `done draft` |
| 3 | **3-Lens Cross-Vendor Goldfish Review** | 3 parallel fresh-context read-only `swarm` critics across all 3 pools (see [references/goldfish-review.md](./references/goldfish-review.md)) | `.loop/designs/<slug>/goldfish-report.md` (≤180 lines, with model receipt) | All 3 lenses complete + consolidated → `done review` |
| 4 | **Resolve, Compress & Handoff** | Main chat (user decisions) + `design-drafter` (compression pass) | Approved 3-doc suite + Reader & `lean-runbook` Handoff Card | `design_check.py check docs/designs/<slug> --strict` exits 0 + user approves → `done resolve` |
| 5 | **Drift Report (Optional, Post-Build)** | `drift-auditor` (**Pool 1:** `gemini-3.8-flash-medium`, read-only) | `docs/designs/<slug>/drift-report.md` (≤150 lines) | Compares merged code/epic against `BR-*`, `RISK-*`, `ADR-*`, `INV-*` |

---

## Stage-by-Stage Execution Rules

### Stage 0: Intake, Mode Detection & Quota Check
1. **Check live quotas:** Call `swarm(action="models", all=True)` and load `swarm_pane` before adding workers.
2. **Detect Mode & Tier:**
   - **Redesign / Rearchitecture Mode (`--mode redesign`):** Triggered whenever the user supplies an existing/rejected EGM plan, RFC, legacy doc, or current platform to reform. Every major risk/flaw in the input becomes a numbered `RISK-*` entry that the new architecture must **structurally eliminate** (not merely mitigate with checklists).
   - **Greenfield Mode (`--mode greenfield`):** New project/feature with no rejected predecessor plan.
   - **Budget Tier:** Default to **`standard` (15–20 min / ≤4,000 words)**. Use **`--complex` (≤60 min / ≤10,500 words)** *only* when the project is a multi-subsystem platform rearchitecture that genuinely cannot fit in 20 minutes without dropping critical contracts.
3. **Initialize & Scout cheaply:**
   - Run `design_check.py init <slug> --mode <greenfield|redesign> [--complex]` (scaffolds templates under `docs/designs/<slug>/` and initializes tracker state).
   - Spawn `design-scout` (`gemini-3.8-flash-low`, `workspace: "inherit"`, read-only; fallback `gpt-oss-120b-medium`) to read any input doc(s) and relevant repo areas and return `.loop/designs/<slug>/recon.md` (**≤120 lines**):
     - Existing system facts (verified file/symbol paths, tech stack, hard constraints)
     - *(Redesign mode)* Extracted **True Business Requirements** vs **Legacy Assumptions / Risks / Failure Modes** in the input plan (separating what the business actually needs from *how* the rejected plan accidentally created risk).

### Stage 1: Elephant Interrogation (Focused, Not Endless)
- Do **not** ask 15 meandering questions. Use `recon.md` to ask **1–2 tight rounds** (prefer `ask_question` with 3–4 concrete high-leverage choices per round) resolving:
  1. **True Business Goals & Explicit Non-Goals** (what survives from the input doc vs what we intentionally kill).
  2. **Risk Elimination Bar** *(Redesign mode)*: confirm the top `RISK-*` failure modes from the input plan and what *structural* property eliminates each (e.g., removing distributed state, replacing sync coupling with idempotent events, eliminating a whole tier).
  3. **Hard Constraints & Cutover Appetite**: downtime/migration tolerance, backward compatibility, team/infra boundaries, and project quiet gate command (if known).
  4. **Target `lean-runbook` Execution Shape**: confirm whether this will execute as a Single Slice, Mini-Series (2–4 slices), or Epic (>4 slices).
- Record locked answers in `.loop/designs/<slug>/brief.md` using [templates/brief.md](./templates/brief.md) (**≤100 lines**), get quick user confirmation, and mark `design_check.py done brief <slug>`.

### Stage 2: Budgeted 3-Doc Drafting (Zero Duplication)
- Spawn `design-drafter` via `swarm(action="add", ...)` on **Pool 1** (**`gemini-4-neon-high`** preferred for non-implementation design work) OR **Pool 4 `claude-sub`** / **Pool 2** (`claude-sonnet-5-5-medium`) when pairing with a Neon critic — fallback to Pool 3 (`gemini-4-argon-medium`) only if Neon < 25%.
- Instruct `design-drafter` to fill [templates/design.md](./templates/design.md), [templates/tech-plan.md](./templates/tech-plan.md), and [templates/spec.md](./templates/spec.md) strictly following these **6 Anti-Bloat Laws**:
  1. **Single Source of Truth by ID:** Define `BR-*`, `RISK-*`, `ADR-*` in `design.md`; define `INV-*` in `tech-plan.md`; define `SLICE-*` and `CUJ-*` in `spec.md`. Downstream docs **cite IDs** (`Satisfies BR-1, BR-3; enforces INV-2`) — **never re-explain requirements or architecture in prose**.
  2. **Tables & Diagrams Over Essays:** Use dense markdown tables and at most **1–2 crisp Mermaid diagrams** per doc. Rejected alternatives are **1-line table rows**, never paragraphs.
  3. **Contracts, Not Code:** Show typed schemas, API/event signatures, and state transitions only. Never paste full implementations or >20-line code blocks.
  4. **Structural Risk Elimination *(Redesign mode)*:** Every `RISK-*` must name the *old mechanism* causing the risk and the *new structural property* that makes the failure mode impossible or strictly bounded. "We will be careful / add monitoring" is forbidden as a primary elimination.
  5. **Executable `lean-runbook` Slices:** Every `SLICE-*` in `spec.md` MUST obey `lean-runbook`'s `≤3 commits / ≤600 LOC` vertical-slice ceiling, specify exact touched boundaries, dependencies, Shared Contracts published/consumed, and concrete acceptance checks (`CUJ-*`). Read [references/lean-runbook-handoff.md](./references/lean-runbook-handoff.md).
  6. **Verify Before Handing Back:** `design-drafter` MUST run `design_check.py check docs/designs/<slug>` and fix any budget overshoot, duplicate prose, large code block, or orphan `BR-*`/`RISK-*`/`INV-*` ID before reporting done.

### Stage 3: 3-Lens Fresh-Context Goldfish Review (Cross-Vendor)
Read [references/goldfish-review.md](./references/goldfish-review.md) and launch **3 parallel fresh-context read-only `swarm` critics**:
1. **`goldfish-clarity` (Pool 1: `gemini-3.8-flash-medium` or `gemini-4-neon-medium`):** Naive-reader clarity, jargon, ambiguity, cross-doc duplication, and **explicit bloat-cut recommendations**.
2. **`goldfish-architect` (Strict opposite vendor flagship from `design-drafter`!):**
   - If Claude drafted (Pool 2 or Pool 4 `claude-sub`) → **`gemini-4-neon-high`** (Pool 1 preferred; fallback `gemini-4-argon-high` if Pool 1 < 25%).
   - If Neon/Argon/Gemini drafted → **Pool 4 `claude-sub` (`opus`, `high`)** or **`claude-opus-5-5-high`** (Pool 2, fallback `claude-sonnet-5-5-high`).
   - Attacks architecture, failure modes, migration/rollback gaps, and audits every `RISK-*` against the input doc (if any) to verify genuine structural elimination.
3. **`goldfish-handoff` (Preferred Neon or Claude):** **`gemini-4-neon-medium`** (when Claude drafted) or **Pool 4 `claude-sub` (`sonnet`) / Pool 2 `claude-sonnet-5-5-high`** (when Neon drafted; fallback `gemini-4-argon-medium`). Audits 100% `BR-*` → `INV-*` → `SLICE-*` coverage, verifies every slice obeys `≤3 commits / ≤600 LOC` with disjoint wave boundaries, and checks that `lean-runbook` can launch directly from `spec.md` with zero rediscovery.

Consolidate findings into `.loop/designs/<slug>/goldfish-report.md` (**≤180 lines**, deduplicated, with `Drafter: <model> | Critics: <models>` receipt verified via `swarm(action="status")`), then retire (`kill`) the 3 critics once consumed.

### Stage 4: Interactive Resolve, Net-Zero Compression & Handoff
1. Present **only real Blockers and Architectural Tradeoffs** to the user (grouped cleanly; auto-resolve obvious typos, broken cross-references, and redundant prose).
2. Send approved resolutions + `goldfish-clarity`'s bloat cuts back to `design-drafter` with the **Net-Zero Bloat Rule**: every word added to clarify a finding must be offset by tightening prose or converting paragraphs to table rows so total read time stays within budget.
3. Run `design_check.py check docs/designs/<slug> --strict` — must exit `0`.
4. Mark every document's header `Status: Approved`, run `design_check.py done resolve <slug>`, retire `design-drafter` and `design-scout`, and present the **Handoff Summary**:
   - Per-doc word count, line count, and estimated read time + total suite read time
   - Clickable `file://` links to `design.md`, `tech-plan.md`, and `spec.md`
   - Exact one-line prompt to launch `lean-runbook` (Single Slice, Mini-Series, or Epic Mode) from `docs/designs/<slug>/spec.md` (see [references/lean-runbook-handoff.md](./references/lean-runbook-handoff.md)).

### Stage 5 (Optional, Post-Build): Compact Drift Report
When the user asks for a drift check after `lean-runbook` lands slices, follow the Drift Report section of [references/lean-runbook-handoff.md](./references/lean-runbook-handoff.md) to emit `docs/designs/<slug>/drift-report.md` (≤150 lines).

---

## Quick Commands
- Init design suite: `design_check.py init <slug> [--mode greenfield|redesign] [--complex]`
- Validate budget, bloat & traceability: `design_check.py check docs/designs/<slug> [--complex] [--strict]`
- Check workflow status: `design_check.py status [<slug>]`
- Mark stage done: `design_check.py done <brief|draft|review|resolve|drift> <slug>`
