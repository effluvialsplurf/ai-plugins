# Contract Plan: <slug>

- **Spec:** `docs/specs/<slug>.md`
- **Budget:** ≤300 lines total · ≤3 commits · **Signatures, invariants & test assertions only (NO pasted full implementations, NO scratch-repo dry-runs)**
- **Quiet Gate:** `tools/gate.sh` (fast inner loop: `tools/gate.sh --fast`)

## Shared Invariants & Touched Symbols
- Verified existing symbols (cited by `file::function`, never fragile line numbers):
  - `file.ext::fn_name` — current behavior relied upon
- Rigor rules (must never regress):
  1. No hardcoded configuration or magic numbers outside central config.
  2. Real classes in tests (no stand-ins re-implementing production logic).
  3. Quiet gate exits 0 with zero script/type errors.

## Commits (Sequential Pipeline)

### Commit 1: `<short-id>` — `<commit message>`
- **Files (exact):** `file_a.ext`, `test_a.ext`
- **Interface & Behavior Contract:**
  - Exact signatures, state transitions, constants, and refusal guards to add/change.
- **Test-First Assertions:**
  - Red → green unit/integration checks proving each invariant & edge case.
- **Gate:** `tools/gate.sh --fast` (or `tools/gate.sh`)

### Commit 2: `<short-id>` — `<commit message>`
- **Files (exact):** ...
- **Interface & Behavior Contract:** ...
- **Test-First Assertions:** ...
- **Gate:** `tools/gate.sh`
