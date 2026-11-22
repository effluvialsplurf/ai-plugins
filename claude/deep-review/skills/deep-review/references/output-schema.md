# Finding Output Schema

Every axis sub-agent emits a list of findings in this exact shape. Do NOT assign
`id` — the orchestrator numbers findings after merging.

## Per-finding fields

- `severity`: one of BLOCKER | HIGH | MEDIUM | LOW
  - BLOCKER: ship-stopping — a correctness defect or structural regression that will
    bite soon.
  - HIGH: should fix before merge.
  - MEDIUM: worth fixing; not blocking.
  - LOW: nit / polish.
- `axis`: correctness | structure | testing (your axis).
- `dimension`: the rubric dimension name this finding came from.
- `location`: `path/to/file.ext:line` (single most relevant line; a range is fine).
- `what`: one sentence — the finding.
- `why`: one sentence — the cost/risk if it ships.
- `suggested_fix`: concrete direction (prose or a short snippet; not required to be a
  full diff).
- `disposition`: worth-fixing | defensible.
  - `defensible` ⇒ append the rebuttal, e.g. "consistent with existing pattern in this
    file" or "guard is at a cross-module boundary". Use it when something looks
    flaggable but is justifiable — surface it, don't suppress it.
- `resolution`: mechanical | judgment.
  - `mechanical` ⇒ the `suggested_fix` is complete and there is exactly one reasonable
    way to apply it — no design choice, trade-off, or intent question. A competent
    implementer could apply it without asking anything (add/strengthen a test, pin an
    assertion, handle a None path, scope a stale claim to what the code does).
  - `judgment` ⇒ acting on it requires a decision the fix can't make alone: a
    trade-off, a design direction, or a call about intent or scope. If your
    `suggested_fix` says "either … or …", or the right move depends on what the
    author intended, it is `judgment` — do not default to `mechanical` because a fix
    is *stated*; the test is whether applying it requires *choosing*.

## Emit format (markdown the orchestrator can parse)

For each finding output one block:

```
- severity: HIGH
  axis: correctness
  dimension: Edge cases
  location: app/services/foo.py:42
  what: `lookup()` can return None but the caller dereferences it unconditionally.
  why: Raises AttributeError on the not-found path; the user sees a 500.
  suggested_fix: Guard the None case and return a 404, or use get_object_or_404.
  disposition: worth-fixing
  resolution: mechanical
```

If you have no findings for your axis, output exactly: `No findings.`

## Review file layout (orchestrator only)

Frontmatter (title, date, pr/branch, base, verdict, testing_tier, counts,
security_assessed), then the body in this order. Sections are keyed to **human
attention**, not axis — the contract is: the human reads section 3 and can stop.

1. Lead paragraph — verdict plus the reasoning in a few sentences.
2. `## Scope` — the scope table.
3. `## Needs your attention` — FULL finding blocks for: every `judgment` finding
   (any axis, any severity), plus every **correctness** finding MEDIUM or above
   (logic errors get human eyes even when the fix is mechanical).
4. `## Mechanical (Claude-handleable)` — one compact table row per remaining
   worth-fixing `mechanical` finding:
   `F-id · severity · location · what (one line) · fix (one line)`.
5. `## Noted, no action` — one line per `defensible` finding, any axis:
   `F-id · severity · what — rebuttal`.
6. `## Clean (checked, no finding)` — at most ~5 one-line bullets.
7. `## Appendix — full finding details` — full blocks (same `### F-id` heading
   shape) for every finding NOT already printed in full in section 3, so the
   receiving session loses no detail. The human never needs to read this.

ID assignment: attention findings first, then mechanical, then noted —
severity-ranked within each group — so "read F1 onward until the mechanical
table starts" holds.
