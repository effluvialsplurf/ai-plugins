# Correctness Rubric (functional)

Review the diff for functional correctness only. Security is OUT of scope (the user
runs `/security-review` separately). You MAY surface a functional defect that happens
to carry security weight (an unscoped tenant query, an unhandled None) — report it as
a correctness finding — but do NOT run a systematic vulnerability sweep.

Be ambitious and concrete. Don't stop at pattern-matching the dimensions below: for
each risky path the diff changes, try to CONSTRUCT a specific input the surrounding
code could actually produce, then trace it through the change to a wrong result, a
crash, or corrupt state — a defect you can demonstrate with a concrete value beats a
vague "this looks off". Trace OUTWARD too: a changed signature, return shape, raised
exception, or nullability ripples to callers and consumers the diff may NOT touch —
follow that blast radius (read beyond the changed files when needed) and flag any
breakage you find as a correctness finding, citing the affected caller.

Emit findings per `output-schema.md`. Example phrasings below lean Python; they apply
equally to JS/TS and any other language — match the principle to the diff's stack (e.g.
a swallowed `catch (e) {}` is the JS form of the bare-`except` smell).

### Logic errors
- Signal: wrong conditions, inverted booleans, off-by-one, mis-ordered operations,
  incorrect control flow, copy-paste that wasn't fully adapted.
- Why: the code does the wrong thing while looking plausible.
- Remedy: correct the condition/flow; add the missing branch.
- Phrase: "this condition looks inverted — should it be `not is_active`?"

### Edge cases
- Signal: empty / None / zero / negative / boundary inputs; unhandled enum variants;
  first/last iteration behaviour.
- Why: the happy path works; the edge crashes or corrupts.
- Remedy: handle the boundary explicitly, or prove it can't occur.
- Phrase: "what happens when `items` is empty here?"

### Error handling
- Signal: bare `except Exception` (catch specific types instead); swallowed errors;
  failure paths that leave state half-applied; missing error returns.
- Why: real failures get hidden or leave inconsistent state.
- Remedy: catch specific exceptions; surface or log appropriately; keep the failure
  path consistent.
- Phrase: "this `except Exception` hides the real error — catch the specific type."

### Data integrity
- Signal: writes that can leave related rows inconsistent; missing transaction
  boundaries where partial state matters; an unscoped query that should be
  tenant/owner-scoped; a `.get()`/lookup whose not-found path isn't handled.
- Why: silent data corruption or wrong-tenant data is worse than a crash.
- Remedy: wrap related writes in a transaction; scope the query; handle not-found.
- Phrase: "these two updates aren't atomic — a failure between them leaves X stale."

### Concurrency & async
Engage this ONLY when the diff touches concurrent code (async/await, threads, tasks,
locks, shared mutable state, retries); stay silent on straight-line single-threaded
changes.
- Signal: shared mutable state mutated without a lock; check-then-act races (the state
  can change between the check and the act); an `await`/yield point that interleaves
  with state assumed atomic; cancellation not propagated, or not shielded where it must
  complete; tasks/futures spawned but never awaited or cleaned up on every path;
  double-execution under retry; locks acquired in inconsistent order (deadlock); a
  blocking call on an async path.
- Why: these pass every test run and fail only under real timing/interleaving — the
  costliest class to reproduce and the easiest to ship green.
- Remedy: guard the shared state; make check-and-act atomic; await/shield/cancel
  deliberately; ensure spawned work is awaited and cleaned up on all paths; make retried
  work idempotent.
- Phrase: "two coroutines can interleave between this check and this write — what stops
  a double <X>?"

### Cited sources
Engage this ONLY when the diff adds or changes a comment that cites a docs page, spec or
ADR as the reason for a setting, or adds an `UNSOURCED` marker.
- Signal: open each cited URL or ADR yourself (web fetch or search) and find the cited
  section. Flag a page that doesn't say what the comment claims, code that doesn't match
  the page (names, values, keys, ports, limits), a dead link, and a docs link that
  redirects to an index page (a common sign of a made-up URL). Report every citation as
  verified / mismatch (quote the page) / dead link / couldn't fetch. A citation you didn't
  open is unreviewed: say so, never pass it.
- Why: a plausible URL with a confident claim reads as verified. Models write these from
  memory, and only opening the page catches a wrong one.
- Remedy: fix the code or the comment to match the page; cite the right page; or mark the
  setting `UNSOURCED` with the reason.
- Phrase: "the cited page lists seven actions; this deny list has six — `ec2:DetachNetworkInterface`
  is missing."
