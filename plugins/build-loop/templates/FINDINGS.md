# Findings: [FEATURE]

One row per real finding (not nits that were dismissed on the spot). Ids are stable: never renumber. Update Status and
Fix commit as the finding moves; add the row when the finding is first seen.

- Stage: which stage caught it (self-review | task review | whole-branch review | codex review | PR review | CI | live check).
- Seat / model: who found it (e.g. sonnet reviewer, Kiro opus, Codex, human).
- Kind: correctness | test gap | docs | other.
- Severity: critical | important | minor.
- Status: open | fixing | fixed | defensible (kept, reason in LOOP-STATE Decisions) | wont-fix.

| id | stage | seat / model | kind | severity | status | fix commit |
|----|-------|--------------|------|----------|--------|------------|
| F1 | | | | | | |
