# Spec: <Feature / Vertical Slice Name>

- **Slug:** `<slug>`
- **Date:** `<YYYY-MM-DD>`
- **Status:** Draft | Goldfish-Reviewed | Approved | Implemented
- **Slice Scope:** ≤3 commits, ≤600 LOC (split larger overhauls into sequential slices)
- **Parent Feature / Roadmap:** `standalone` (or `Slice X of Y: <slug-1> -> <slug-2> -> <slug-3>`)

## 1. Objective & Boundaries
- **Goal (1–2 sentences):** What changes for the user and why.
- **Out of Scope:**
  - Bullet list of what this slice explicitly does NOT change.

## 2. Decisions & Invariants
Numbered rules binding on implementation and review. Keep each row to 1–2 lines.

| ID | Rule / Decision | Source / Rationale |
|---|---|---|
| D1 | | |
| D2 | | |

## 3. Rejected Alternatives (1 Line Each)
Record rejected approaches briefly so future sessions don't re-litigate them.

| Alternative | Why Rejected |
|---|---|
| | |

## 4. Public Interfaces & Data Shapes
Exact function signatures, state fields, config/tuning keys, and ownership only. **No prose essays, no pasted implementations.**

- `path/to/file.ext` (Create | Modify):
  - `func_name(arg: Type) -> ReturnType` — contract & error/edge behavior
  - `CONST_OR_KEY` — meaning & starting value

## 5. Critical User Journeys & Edge Cases

| ID | Given | When | Then (Observable Outcome) |
|---|---|---|---|
| CUJ-1 | | | |
| EDGE-1 | Bad/empty/boundary input | | Refuses cleanly without mutating state |

## 6. Verification Gate
- **Quiet gate command:** `tools/gate.sh` (or project test command)
- **New/updated tests required:**
  - `test_file`: specific behaviors & mutation checks to prove
