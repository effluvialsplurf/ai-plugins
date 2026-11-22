# Epic Ledger: <Epic Name>

Read this file first after compaction or when dispatching/merging any slice. Keep total file ≤150 lines.

- **Epic Slug:** `<epic-slug>`
- **Integration Branch:** `epic/<epic-slug>` (branched from `<base-branch>`)
- **Quiet Gate:** `tools/gate.sh` (fast: `tools/gate.sh --fast`)
- **Project Rigor Rules:** `<e.g., no magic numbers outside config; real classes in tests; clean quiet gate>`

## 1. Epic Goal & Locked Design Rulings
Short, binding architectural & gameplay decisions settled with the user.

| ID | Ruling | Rationale |
|---|---|---|
| E1 | | |
| E2 | | |

## 2. Shared Contracts Registry (Already Merged into `epic/<epic-slug>`)
Canonical files, types, signals, and entrypoints that downstream slices MUST rely on (no guessing).

- `path/to/file.ext::symbol` — contract / behavior (added in `<slice-slug>`)

## 3. Slice Board (≤3 commits / ≤600 LOC per slice)

| # | Slice Slug | Worker | Status | Est. Size | Depends On | Builder / Critic Pools | Branch |
|---|---|---|---|---|---|---|---|
| 1 | `<slice-1>` | `slice-<1>` | Queued \| Spec \| Goldfish \| Building \| Merged \| Blocked | 2c / ~300 LOC | none | `claude-sonnet-5-5-medium` / `gemini-4-argon-high` | `slice/<slice-1>` |
| 2 | `<slice-2>` | `slice-<2>` | Queued | 2c / ~350 LOC | #1 | `gemini-4-argon-medium` / `claude-opus-5-5-high` | `slice/<slice-2>` |

## 4. Unforeseen Work / Discovery Inbox
Logged by Slice Workers instead of scope-creeping their active slice. Triage with the user.

| ID | From Slice | Discovery / Unexpected Coupling | Disposition |
|---|---|---|---|
| D1 | `<slice>` | `<1-line description>` | Open \| New slice `#N` \| Fold into `#M` \| Deferred |

## 5. Merge & Verification Log
- `<YYYY-MM-DD>` initialized `epic/<epic-slug>`
- *(Per merged slice: `<date> #<N> <slug> (<sha>) | Builder: <model> | Critic: <model> | Gate: <result>`)*
