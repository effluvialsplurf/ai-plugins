"""Stage 2: 2-Pass Parallel Goldfish Spec Gate via Antigravity run_workflow.

Runs TWO fresh-context Goldfish reviewers in parallel with ZERO prior drafting history:
  1. Clarity & Structure Reviewer (default clarity_model="flash"): ambiguity, missing CUJs, scope creep, line budget.
  2. Adversarial Codebase Critic (default adversarial_model="inherit"): verifies every claimed file/function/invariant
     against real repo code, hunts contradictions, edge-case breaks, and unverified assumptions.
     Using "inherit" keeps the adversarial pass on the calling Swarm worker's model pool (e.g. Claude Sonnet or
     Gemini 4 Argon) instead of forcing extra Gemini Models usage; pass "pro" explicitly if desired.

Note: When orchestrating from a main chat on Gemini Models, prefer spawning two read-only `swarm` workers
(`goldfish-clarity` on `gemini-3.8-flash-medium` + `goldfish-critic` on `gemini-4-argon-medium` or
`claude-opus-5-5-medium`) per `references/quota-routing.md` to balance across all 3 quota pools.

Args expected (pass via run_workflow Args dict):
  slug:              Feature slug (e.g. "example-feature")
  spec_path:         Path to compact EGM spec (e.g. "docs/specs/example-feature.md")
  rigor:             Optional short list of project rigor rules (string)
  clarity_model:     Optional run_workflow tier ("inherit"|"flash_lite"|"flash"|"pro", default: "flash")
  adversarial_model: Optional run_workflow tier ("inherit"|"flash_lite"|"flash"|"pro", default: "inherit")
"""
import json
import os

VALID_TIERS = {"inherit", "flash_lite", "flash", "pro"}

slug = args["slug"]
spec_path = args["spec_path"]
rigor = args.get("rigor", "No hardcoded config/magic numbers; real classes in tests; clean quiet gate.")
clarity_model = args.get("clarity_model", "flash")
adversarial_model = args.get("adversarial_model", "inherit")

for arg_name, tier in (("clarity_model", clarity_model), ("adversarial_model", adversarial_model)):
    if tier not in VALID_TIERS:
        raise ValueError(
            f"Invalid {arg_name}={tier!r} for run_workflow (allowed: {sorted(VALID_TIERS)}). "
            "For exact Claude/GPT/Argon model IDs, dispatch native `swarm` workers instead."
        )

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
5. Vertical-slice sizing: Does this truly fit <=3 commits / <=600 LOC and <=2 tightly coupled layers?
   If it exceeds those bounds or bundles >=3 independently testable layers (e.g., data/state + gameplay logic + UI/HUD + persistence),
   flag it as a `blocker` and propose a concrete 2-4 sequential vertical-slice split in `question_or_fix`.
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
    (f"Goldfish Clarity ({clarity_model})", clarity_model, "research", clarity_prompt),
    (f"Goldfish Adversarial Critic ({adversarial_model})", adversarial_model, "research", adversarial_prompt),
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
    f"- **Clarity ({clarity_model}):** {clarity_res['verdict']} — {clarity_res['summary']}",
    f"- **Adversarial ({adversarial_model}):** {adv_res['verdict']} — {adv_res['summary']}",
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

append_section(f"Pass 1: Clarity & Structure ({clarity_model})", clarity_res["findings"])
append_section(f"Pass 2: Adversarial Codebase Verification ({adversarial_model})", adv_res["findings"])

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
