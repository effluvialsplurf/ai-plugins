"""Stage 2: 2-Pass Parallel Goldfish Spec Gate via Antigravity run_workflow.

Runs TWO fresh-context Goldfish reviewers in parallel with ZERO prior drafting history:
  1. Clarity & Structure Reviewer (model="flash"): ambiguity, missing CUJs, scope creep, line budget.
  2. Adversarial Codebase Critic (model="pro"): verifies every claimed file/function/invariant against
     real repo code, hunts contradictions, edge-case breaks, and unverified assumptions.

Args expected (pass via run_workflow Args dict):
  slug:      Feature slug (e.g. "example-feature")
  spec_path: Path to compact EGM spec (e.g. "docs/specs/example-feature.md")
  rigor:     Optional short list of project rigor rules (string)
"""
import json
import os

slug = args["slug"]
spec_path = args["spec_path"]
rigor = args.get("rigor", "No hardcoded config/magic numbers; real classes in tests; clean quiet gate.")

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "NEEDS_RESOLUTION"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["blocker", "important", "minor"]},
                    "location": {"type": "string"},
                    "issue": {"type": "string"},
                    "question_or_fix": {"type": "string"},
                },
                "required": ["id", "severity", "location", "issue", "question_or_fix"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["verdict", "findings", "summary"],
}

phase("goldfish-parallel-review")
log(f"Starting 2-Pass Goldfish Gate on {spec_path}")

clarity_prompt = f"""You are a fresh-context Goldfish Clarity & Structure Reviewer.
You have NO prior conversation history — judge ONLY the spec file `{spec_path}` and its immediate repo context.
Read `{spec_path}` in full (do not modify any files). Check:
1. Line budget & conciseness (target <=300 lines; flag bloat/essays).
2. Are Decisions & Invariants unambiguous, testable, and free of internal contradictions?
3. Does every CUJ & Edge Case have a concrete Given/When/Then outcome?
4. Are Out-of-Scope boundaries sharp enough to prevent creep?
5. Is the slice small enough (<=3 commits, <=600 LOC)?
Skip cosmetic prose nits. Return ONLY real clarity/completeness gaps via finish()."""

adversarial_prompt = f"""You are a fresh-context Adversarial Goldfish Technical Critic.
Your job is to PROVE `{spec_path}` WRONG against the real codebase — not to praise it.
Read `{spec_path}` and verify EVERY claimed file, symbol, function signature, call site, and invariant
by reading the real source files in this workspace (do not edit any files).
Project rigor rules: {rigor}
Check specifically:
1. Contradictions between spec claims and actual code (cite `file::function`).
2. Hidden coupling: callers, shared singletons/globals, tests, or state machines that will break.
3. Missing failure/edge handling (zero, empty, NaN/INF, re-entrancy, persistent-state pollution).
4. Any implicit design decision left open that would force a builder to guess.
Report only verified, concrete findings via finish()."""

review_specs = [
    ("Goldfish Clarity (Flash)", "flash", "research", clarity_prompt),
    ("Goldfish Adversarial Critic (Pro)", "pro", "research", adversarial_prompt),
]

clarity_res, adv_res = await parallel(
    review_specs,
    lambda item: agent(
        prompt=item[3],
        role=item[0],
        model=item[1],
        type_name=item[2],
        workspace="inherit",
        schema=FINDINGS_SCHEMA,
    ),
)

# Write consolidated compact report to .loop/<slug>/goldfish-report.md
out_dir = os.path.join(".loop", slug)
os.makedirs(out_dir, exist_ok=True)
report_path = os.path.join(out_dir, "goldfish-report.md")

all_blockers = [f for f in clarity_res["findings"] + adv_res["findings"] if f["severity"] == "blocker"]
all_important = [f for f in clarity_res["findings"] + adv_res["findings"] if f["severity"] == "important"]
all_minor = [f for f in clarity_res["findings"] + adv_res["findings"] if f["severity"] == "minor"]

lines = [
    f"# Goldfish Gate Report: {slug}",
    f"- **Spec:** `{spec_path}`",
    f"- **Clarity (Flash):** {clarity_res['verdict']} — {clarity_res['summary']}",
    f"- **Adversarial (Pro):** {adv_res['verdict']} — {adv_res['summary']}",
    f"- **Totals:** {len(all_blockers)} blocker · {len(all_important)} important · {len(all_minor)} minor",
    "",
]

def append_section(title, items):
    lines.append(f"## {title}")
    if not items:
        lines.append("- None.")
    for f in items:
        lines.append(
            f"- **[{f['severity'].upper()}] {f['id']}** (`{f['location']}`): {f['issue']} -> *{f['question_or_fix']}*"
        )
    lines.append("")

append_section("Pass 1: Clarity & Structure (Flash)", clarity_res["findings"])
append_section("Pass 2: Adversarial Codebase Verification (Pro)", adv_res["findings"])

with open(report_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))

log(f"Wrote {report_path}: {len(all_blockers)} blocker, {len(all_important)} important, {len(all_minor)} minor")
print(json.dumps({
    "report_path": report_path,
    "blockers": len(all_blockers),
    "important": len(all_important),
    "minor": len(all_minor),
    "clarity_verdict": clarity_res["verdict"],
    "adversarial_verdict": adv_res["verdict"],
}, indent=2))
