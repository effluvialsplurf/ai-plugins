# Implementation Spec (`lean-runbook` Handoff): <Project / Platform Name>

- **Slug:** `<slug>`
- **Date:** `<YYYY-MM-DD>`
- **Status:** Draft | Goldfish-Reviewed | Approved
- **Suite:** [Design Doc](./design.md) · [Technical Plan](./tech-plan.md) · [Lean-Runbook Spec](./spec.md)
- **Recommended `lean-runbook` Mode:** `Single Slice` | `Mini-Series (2-4 slices)` | `Epic (>4 slices)`
- **Quiet Gate Command:** `<e.g., tools/gate.sh>` *(fast: `<tools/gate.sh --fast>`)*
- **Target Budget:** ≤1,200 words (~6 min read) *(complex ceiling: ≤3,300 words)*

> **Purpose:** Translates every `BR-*` (`design.md`) and `INV-*` (`tech-plan.md`) into executable
> vertical slices (`≤3 commits / ≤600 LOC` each) and acceptance checks ready to feed directly into `lean-runbook`.

## 1. Locked Execution Rulings (Seeds `EPIC.md` Section 1 / Spec Section 2)
Copy-ready binding rulings distilled from `ADR-*` and `INV-*` (1 line each).

| ID | Ruling | Source |
|---|---|---|
| `E1` | | `ADR-1`, `INV-1` |
| `E2` | | `ADR-2`, `RISK-1` |

## 2. Requirement & Invariant Traceability Matrix (100% Coverage Required)
Every `BR-*` from `design.md`, every `RISK-*` (if any), and every `INV-*` from `tech-plan.md` MUST appear below.

| Source ID | Mapped Slice(s) | Acceptance Check ID(s) | Verification Type |
|---|---|---|---|
| `BR-1` | `SLICE-1` | `CUJ-1`, `EDGE-1` | Unit + Integration |
| `BR-2` | `SLICE-2` | `CUJ-2` | Integration |
| `RISK-1` | `SLICE-1` | `EDGE-1` | Fault-injection / Negative test |
| `INV-1` | `SLICE-1` | `CUJ-1`, `EDGE-1` | Unit |

## 3. Shared Contracts Registry Seed (Seeds `EPIC.md` Section 2)
Canonical files, types, and entrypoints that slices publish and downstream slices consume.

- `path/to/contract.ext::SymbolName` — `<exact signature / schema contract>` (Published by: `SLICE-1`)

## 4. Vertical Slice Roadmap (Implementation Plan)
Every slice MUST fit `≤3 commits` and `≤600 LOC`. Parallel waves MUST touch disjoint files.

| ID | Slice Slug | Wave | Depends On | Est. Size | Touched Files / Subsystems | Deliverable & Exit Gate | Covers |
|---|---|---|---|---|---|---|---|
| `SLICE-1` | `<slice-slug-1>` | 1 | none | 2c / ~300 LOC | `path/a`, `tests/a` | `<testable behavior + gate>` | `BR-1`, `RISK-1`, `INV-1` |
| `SLICE-2` | `<slice-slug-2>` | 2 | `SLICE-1` | 2c / ~350 LOC | `path/b`, `tests/b` | `<testable behavior + gate>` | `BR-2`, `INV-2` |

## 5. Acceptance Criteria & Edge Cases (CUJs)
Observable, testable proofs binding on `lean-runbook` Stage 4 TDD builders and Stage 5 critics.

| ID | Slice | Given | When | Then (Observable Outcome) |
|---|---|---|---|---|
| `CUJ-1` | `SLICE-1` | | | |
| `EDGE-1` | `SLICE-1` | `<invalid / fault / legacy-risk trigger>` | | `<fails closed / structurally prevented>` |

## 6. Per-Slice Contract Seeds *(1–3 concise bullets per slice; omit if Single Slice)*
- **`SLICE-1` (`<slice-slug-1>`):**
  - **Publishes:** `<file::symbol>`
  - **Key Invariants & Tests:** `<exact assertions to prove red -> green>`
- **`SLICE-2` (`<slice-slug-2>`):**
  - **Consumes:** `<file::symbol>` · **Publishes:** `<file::symbol>`
  - **Key Invariants & Tests:** `<exact assertions to prove red -> green>`

## 7. `lean-runbook` Launch Handoff
- **Start command / prompt:**
  - *(Single Slice)* Copy/adapt this spec to `docs/specs/<slug>.md` (already ≤300 lines) and run `start lean runbook for <slug>`.
  - *(Mini-Series)* Start `lean-runbook` with Slice 1 (`<slice-slug-1>`) referencing `docs/designs/<slug>/spec.md`.
  - *(Epic)* Run `start lean runbook epic for <slug> using docs/designs/<slug>/spec.md` — seed `.loop/epics/<slug>/EPIC.md` directly from Sections 1, 3, and 4 above.
