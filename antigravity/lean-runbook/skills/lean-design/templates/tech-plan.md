# Technical Plan: <Project / Platform Name>

- **Slug:** `<slug>`
- **Date:** `<YYYY-MM-DD>`
- **Status:** Draft | Goldfish-Reviewed | Approved
- **Suite:** [Design Doc](./design.md) · [Technical Plan](./tech-plan.md) · [Lean-Runbook Spec](./spec.md)
- **Target Budget:** ≤1,400 words (~7 min read) *(complex ceiling: ≤3,600 words)*

> **Rule:** Cite `BR-*`, `RISK-*`, and `ADR-*` from `design.md` by ID — do not repeat business prose. Show contracts, schemas, and state transitions only — **no pasted implementations**.

## 1. Subsystem Boundaries & Ownership
Exact modules/services/packages, code boundaries, and dependency direction (no cycles).

| Subsystem | Repo Path / Boundary | Public Entrypoint(s) | Allowed Dependencies | Implements |
|---|---|---|---|---|
| `<Sub A>` | `path/to/sub_a/` | `fn_or_endpoint(...)` | none | `ADR-1`, `BR-1` |
| `<Sub B>` | `path/to/sub_b/` | | `Sub A` | `BR-2` |

## 2. Data, State & Contract Shapes
Concise schemas, message envelopes, and state ownership only (≤20-line blocks).

- **`<Entity / Store / Contract Name>`** (Owner: `<Subsystem>`, Persistence: `<DB / File / Memory>`):
  - Fields / invariants: `id: UUID`, `version: int`, `status: Enum(...)`
  - Concurrency / idempotency rule: `<e.g., optimistic lock on version; idempotency key TTL 24h>`

## 3. Core Flows, Failure Modes & System Invariants
Optional: **one** concise sequence/state diagram if timing or failure recovery is non-trivial.

### System Invariants (Binding on Implementation & Review)
| ID | Invariant (Must Always Hold) | Enforced By (Mechanism) | Failure Behavior (Fail-Closed / Retry / Fallback) |
|---|---|---|---|
| `INV-1` | | | |
| `INV-2` | | | |

## 4. Risk Elimination Verification *(Required when `design.md` defines `RISK-*`)*
Proves every `RISK-*` from `design.md` is structurally eliminated, not wishfully mitigated.

| Risk ID | Structural Mechanism | Invariant(s) | Automated Proof / Test Strategy |
|---|---|---|---|
| `RISK-1` | | `INV-1` | `<unit / fault-injection / integration check>` |
| `RISK-2` | | `INV-2` | |

## 5. Migration, Cutover & Rollback Strategy
*(For greenfield projects with no migration, replace with a 3-line Deployment & Rollback note.)*

| Phase | Action & Coexistence Boundary | Entry Gate | Rollback Trigger & Procedure |
|---|---|---|---|
| Phase 1 | | | |
| Phase 2 | | | |

## 6. Cross-Cutting Budgets (Non-Trivial Items Only)
Omit boilerplate rows; include only binding budgets that affect architecture or tests.

| Concern | Binding Requirement / Budget | Verification |
|---|---|---|
| Performance / Scale | `<e.g., p99 < 50ms at 1k rps>` | |
| Security / AuthZ | `<trust boundary, secret handling, tenant isolation>` | |
| Observability / Ops | `<structured logs, metrics, alertable invariants>` | |
