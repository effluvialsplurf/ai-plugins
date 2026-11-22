# Structure & Maintainability Rubric

Be ambitious. Look for "code-judo": a reframing that makes whole branches, helpers, or
layers disappear — prefer DELETING complexity over rearranging it. But do not flood the
review with cosmetic nits; lead with structural findings.

Emit findings per `output-schema.md`. Examples lean Python/Django and JS/TS (React), but
the skill spans all of them — apply the underlying principle, not the example's stack.

### Code-judo simplification
- Signal: a complicated implementation where a different framing removes concepts,
  branches, or a helper layer entirely.
- Why: every concept a reader must hold is ongoing cost; deletion beats redistribution.
- Remedy: propose the simpler framing; show what disappears.
- Phrase: "if we model this as <X>, these three branches collapse into one default."

### Spaghetti-conditional growth
- Signal: new ad-hoc conditionals / special cases bolted into an existing unrelated
  flow; one-off booleans or mode flags threaded through.
- Why: makes surrounding code harder to reason about; becomes permanent debt.
- Remedy: push the logic behind a dedicated abstraction / dispatcher / state, or a
  simpler default with fewer exceptions.
- Phrase: "this special-case branch tangles an already-busy function — isolate it."

### File-size discipline
- Signal: the diff pushes a file past ~1000 lines (soft smell, not a hard rule).
- Why: large files are hard to scan and to hold in context.
- Remedy: extract a focused helper / module / subcomponent.
- Phrase: "this crosses ~1k lines — can we split <responsibility> out first?"

### Right-layer placement & reuse
- Signal: feature-specific logic leaking into shared/general paths; logic that
  duplicates an existing canonical implementation — whether extracted as a helper or
  written inline inside a changed function.
- Why: architectural drift; duplicated logic diverges over time.
- Remedy: move logic to the module that owns the concept; reuse the canonical version.
- How to check: default to SEARCHING — don't pre-judge whether a duplicate exists. For
  any non-trivial logic the diff introduces — named helper OR inline code — grep the
  repo for an existing implementation of that behavior before treating it as new. Do
  NOT skip the search because you doubt a duplicate exists: that hunch is precisely what
  lets duplicates through, the grep is cheap, and a divergent re-implementation is not.
  Search by the behavior/concept (the operation, a distinctive literal, the domain
  noun), NOT by symbol name — the existing version may also be inline under a different
  name; try several phrasings before concluding it's absent. Bias toward over-searching.
  Scope to concepts THIS diff introduces — not unrelated code.
- Phrase: "this re-implements <X> from <file> inline — can we reuse it?"

### Decision-record (ADR) consistency
Only if you were given an `ADR_DIR`. Read the records there — not just ones the diff
touches — and check the change against the decisions they capture.
- Signal: the diff contradicts an accepted ADR (does the opposite of a recorded
  decision), OR makes a decision an ADR documents now stale/inaccurate, OR introduces an
  architecturally significant choice (new dependency, data store, integration boundary,
  auth/tenancy model, public-API shape) with no ADR covering it.
- Why: ADRs are the durable record of WHY the architecture is as it is; silent drift
  makes them lies and erases the rationale future readers depend on.
- Remedy: flag the specific record (`ADR-NNNN`) and the contradiction, OR name the
  decision that needs a new/superseding ADR. Flag only — do NOT write the ADR.
- Severity: an accepted ADR contradicted ⇒ at least HIGH; a missing ADR for a
  significant new choice ⇒ MEDIUM; cosmetic staleness ⇒ LOW.
- Phrase: "this reverses ADR-0007 (chose X over Y) — update or supersede it, or
  reconsider the change."

### Claim-vs-code enforcement (load-bearing assertions)
A claim is *load-bearing* when consumers rely on it: a public docstring, a type hint, an
ADR, a README contract, a named config key. Verify the code actually enforces/implements
what such a claim asserts — this is the DUAL of dead config (dead config is wiring with no
consumer; this is a claim with no enforcement). Same failure shape: an artifact asserting
something nothing backs.
- Signal: the diff adds or changes a load-bearing claim the code doesn't back, OR changes
  code so an existing claim goes false — a docstring promising an exception type / return
  field / side effect that doesn't exist; an ADR or comment naming N call sites when there
  are N+1; a "single source of truth" / "always validated" assertion nothing funnels
  through or enforces; a type hint contradicted by what the function actually returns.
- Why: consumers code against the claim, not the implementation. A claim the code doesn't
  enforce is a latent break (an `except PromisedError` that never catches, an import that
  ImportErrors) and it quietly erodes trust in every other claim nearby.
- How to check: for each load-bearing claim the diff touches, find the code that would
  enforce it and confirm it does — don't take the prose at face value. Grep for the
  promised symbol / the named call sites; if it's absent or partial, flag it.
- Severity: a false public/consumer-facing contract ⇒ HIGH; an inaccurate ADR/internal
  claim ⇒ MEDIUM; a stale non-load-bearing comment ⇒ LOW (often omit).
- Scope: load-bearing claims only. A stale inline comment no consumer reads is low-yield
  noise — skip it; an ADR that lies about a trust boundary is exactly the catch.
- Phrase: "the docstring promises `RAGError` but nothing defines it — drop the claim or
  build the type."

### No magic / no thin wrappers
- Signal: identity / pass-through wrappers that add indirection without clarity; generic
  "magic" mechanisms hiding a simple data-shape assumption.
- Why: indirection without payoff makes the code harder to follow.
- Remedy: inline the wrapper; make the assumption explicit/typed.
- Phrase: "this wrapper just forwards args — can we call the inner function directly?"

### Guard / invariant provenance
Decide keep-vs-drop by WHERE the invariant is enforced, not by what a type hint says.
- DROPPABLE when enforced by a runtime-binding mechanism: a `NOT NULL` DB column, a
  validated model (pydantic/dataclass), an exhaustively-matched enum, or a
  same-file/same-module contract where every caller is visible.
- KEEP at cross-module/process boundaries (view→service, service→extractor), on
  DB-nullable fields, on external input (HTTP/JSON/env), and on soft-delete /
  tenant-scope invariants — that's defense-in-depth; contracts drift across files.
- TS note: prefer precise types over runtime re-checks; treat `as` / `any` / `unknown`
  casts as smells (they bypass a compile-time guarantee).
- Pure-JS note: there is NO compile-time guarantee at all, so a runtime guard at a
  boundary is the ONLY thing enforcing the contract — do NOT recommend dropping it by
  appeal to a "type". JSDoc / `@type` are documentation, not enforcement. A guard is
  droppable only when a runtime mechanism actually binds it (validated input, a
  same-module contract with all callers visible, an upstream throw you can see).
- Python note: type hints are NOT runtime-enforced — a hint is not proof a guard is
  dead. `cast()` / `Any` / `# type: ignore` weaken checking without adding runtime
  safety.
- Signal: a guard removed at a boundary (flag — likely should stay), OR a redundant
  guard added where a runtime-binding mechanism already enforces it (flag — drop it).
- Phrase: "this guard is at a service boundary — keep it; contracts drift across files."
