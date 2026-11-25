# Build failure classes (starter set)

Mistakes that got past a builder and cost a fix round or worse in earlier loop runs, grouped so plans, implementers and
reviewers check for them up front. Copy this to `.loop/failure-classes.md` and grow it: add a line only when a class
repeats or cost a live check or an extra review round. One line each, with where it bit.

Every implementer contract, plan brief and task-review dispatch links the project's copy.

## Plan and contract claims

1. **A claim about the code needs the function that proves it.** What an event records, what a reply reports, what a
   field covers: cite the member and re-read it, not its name.
2. **Reachability, two ways.** Production really runs the path (live values, not just code), and the caller can read
   every value it must send.

## Code

3. **Anything a write stores is pinned by its own test.** One test per field that changes only that field. Check
   fields a subclass stores under another name.
4. **Every new write refuses before any change**: a blocked state, a nonfinite number, a wrong type (boolean or blank
   where a number is meant). "Already set" returns before doing anything.
5. **Test stand-ins carry the members the real object has** that the code reads, and cite them. A stand-in that behaves
   unlike the real thing hides the bug. (The most common finding by far.)
6. **Legacy files behind a flag:** the flag-off path is the old lines verbatim, with a flag-off vs flag-on twin test for
   every moved body.
7. **Mirror the system's own conversion path**, even when it looks roundabout, and say why in a comment. Never
   re-derive a unit conversion by hand.
8. **Disabled or hidden in the UI means refused.** Treat CSS-only hiding as a bug to report, not a guard.

## Docs

9. **Markdown tables:** escape `|` in cells and check the table renders; formatters pass broken tables.
10. **Cite code by file and function name, never line number.** Line numbers rot within a PR.

## Agent guidance

11. **A blocked item is not a blocked brief.** Report it and carry on with the parts that don't depend on it.
12. **Match the action to the request's scope.** One item vs all of them; "every X" means check each one.
