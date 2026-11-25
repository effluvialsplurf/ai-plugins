# `lean-runbook` Handoff & Post-Build Drift Report

`docs/designs/<slug>/spec.md` is engineered so **`lean-runbook`** can pick up execution immediately
without repeating Stage 0–1 brainstorming or re-reading legacy documents.

---

## 1. Handoff Mapping by Execution Shape

### Case A: Single Slice (`≤3 commits`, `≤600 LOC`)
- `docs/designs/<slug>/spec.md` already contains the locked rulings, contracts, CUJs, and quiet gate.
- Copy or link the slice-ready spec to `docs/specs/<slug>.md` (verify `≤300 lines`), citing `docs/designs/<slug>/design.md` and `docs/designs/<slug>/tech-plan.md` in the header.
- **Launch prompt for user:**
  `Start lean runbook for <slug> using docs/designs/<slug>/spec.md`
- Inside `lean-runbook`: Stage 1 is satisfied almost instantly; Stage 2 Goldfish checks only codebase symbol alignment before Stage 3 Contract Plan → Stage 4 TDD Build → Stage 5 Cross-Family Review.

### Case B: Mini-Series (`2–4 sequential slices`)
- `docs/designs/<slug>/spec.md` Section 4 provides the exact approved **Slice Roadmap** (`SLICE-1`..`SLICE-N`), Section 3 provides the **Shared Contracts**, and Section 6 provides **Per-Slice Contract Seeds**.
- **Launch prompt for user:**
  `Start lean runbook for <slice-slug-1> from docs/designs/<slug>/spec.md (Mini-Series Slice 1 of N)`
- Each slice creates its compact `docs/specs/<slice-slug>.md` (≤300 lines) directly from its seed in `spec.md` + cites `BR-*`/`INV-*` by ID. Recommend `/compact` between slices.

### Case C: Epic Mode (`>4 slices` or Parallel Platform Rearchitecture)
- `docs/designs/<slug>/spec.md` maps **1-to-1** onto `.loop/epics/<slug>/EPIC.md` (`templates/epic-ledger.md`):

| `docs/designs/<slug>/spec.md` Section | Seeds `.loop/epics/<slug>/EPIC.md` Section |
|---|---|
| Section 1 (`Locked Execution Rulings E1..En`) | Section 1 (`Epic Goal & Locked Design Rulings`) |
| Section 3 (`Shared Contracts Registry Seed`) | Section 2 (`Shared Contracts Registry`) — marked `(planned)` until each slice merges |
| Section 4 (`Vertical Slice Roadmap`) | Section 3 (`Slice Board`, adding Builder/Critic pools from live `swarm(action="models", all=True)`) |
| Section 5 & 6 (`CUJs` + `Per-Slice Contract Seeds`) | Pasted directly into each `workspace: "share"` Slice Worker's brief |

- **Launch prompt for user:**
  `Start lean runbook epic for <slug> using docs/designs/<slug>/spec.md`
- The Epic Coordinator creates `epic/<slug>`, commits `.loop/epics/<slug>/EPIC.md` (pre-populated from `spec.md`), and dispatches Wave 1 `workspace: "share"` Slice Workers across Claude Sonnet 5.5 and Gemini 4 Argon immediately!

---

## 2. Final Handoff Card (Printed at End of `lean-design` Stage 4)

Always finish Stage 4 with a compact summary card like this:

```markdown
### Design Suite Approved: `<slug>`
- **Design Doc:** [design.md](file:///.../docs/designs/<slug>/design.md) — `X words (~Ym read)`
- **Technical Plan:** [tech-plan.md](file:///.../docs/designs/<slug>/tech-plan.md) — `X words (~Ym read)`
- **Lean-Runbook Spec:** [spec.md](file:///.../docs/designs/<slug>/spec.md) — `X words (~Ym read)`
- **Total Suite Read Time:** **~Zm** (`total_words` words | Budget: `<standard 15-20m | complex <=60m>`)
- **Traceability:** `N/N BR-*`, `M/M RISK-*`, `K/K INV-*` mapped across `S` vertical slices (all ≤3 commits / ≤600 LOC)
- **Review Receipt:** `Drafter: <model> | Critics: <clarity>, <architect>, <handoff>`

**Next Step (`lean-runbook`):**
> `Start lean runbook <epic | for <slice-slug-1>> using docs/designs/<slug>/spec.md`
```

---

## 3. Stage 5 (Optional, Post-Build): Compact Drift Report

Replaces `/egm:egm-drift-report`. Run after `lean-runbook` finishes a feature or Epic (or mid-Epic milestone):

1. Spawn a single read-only `drift-auditor` (**Pool 1:** `gemini-3.8-flash-medium`, fallback `gpt-oss-120b-medium`) with access to:
   - `docs/designs/<slug>/{design.md,tech-plan.md,spec.md}`
   - `.loop/epics/<slug>/EPIC.md` (if Epic) + `git log --oneline <base>..HEAD` + relevant source/test files
2. Auditor checks every `BR-*`, `RISK-*`, `ADR-*`, and `INV-*` against the **actual codebase and tests** and writes `docs/designs/<slug>/drift-report.md` (**≤150 lines**):
   - **Summary counts:** `Matched | Drifted (Intentional) | Drifted (Accidental) | Unverified`
   - **Drift Table:** `ID | Planned Contract | Actual Implementation | Classification | Recommended Action (Update Doc vs Fix Code)`
   - **Unplanned Additions:** Any significant subsystem/contract added during build that should be backfilled into `design.md` or `tech-plan.md`.
3. Mark `design_check.py done drift <slug>` and retire `drift-auditor`.
