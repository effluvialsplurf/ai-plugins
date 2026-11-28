"""Stages 4-5: Python-Orchestrated TDD Build Loop + Quiet Gate + Adversarial Branch Critic.

Eliminates main-LLM controller overhead by running loop dispatch, quiet gate execution, and retry
routing in zero-token Python. Every subagent returns a strict compact JSON schema (<=15-line handoff).

Args expected (pass via run_workflow Args dict):
  slug:         Feature slug (e.g. "example-feature")
  spec_path:    Path to compact EGM spec (e.g. "docs/specs/example-feature.md")
  plan_path:    Path to compact contract plan (e.g. ".loop/example-feature/plan.md")
  gate_cmd:     Full quiet gate command (default: "tools/gate.sh")
  fast_cmd:     Fast inner-loop gate command (default: "tools/gate.sh --fast")
  base_ref:     Git base ref for branch diff review (default: "main")
  build_model:  Builder tier ("inherit" | "flash_lite" | "flash" | "pro", default: "inherit")
                When invoked inside a Claude/Argon Swarm Slice Worker, keep "inherit" so builds stay on that pool.
  critic_model: Reviewer tier (default: "inherit"; ignored when skip_critic=True)
  skip_critic:  Bool (default: False). Set True when the Coordinator runs Stage 5 via a dedicated
                cross-family native `swarm` critic (avoids paying twice for single-family review).
  tasks:        List of dicts: [{"id": "c1", "title": "...", "commit_msg": "...", "fast_only": False}]
                (Hard cap: <= 3 commits per vertical slice)
"""
import json
import os

VALID_TIERS = {"inherit", "flash_lite", "flash", "pro"}

slug = args["slug"]
spec_path = args["spec_path"]
plan_path = args["plan_path"]
gate_cmd = args.get("gate_cmd", "tools/gate.sh")
fast_cmd = args.get("fast_cmd", "tools/gate.sh --fast")
base_ref = args.get("base_ref", "main")
build_model = args.get("build_model", "inherit")
critic_model = args.get("critic_model", "inherit")
skip_critic = bool(args.get("skip_critic", False))
tasks = args["tasks"]

for arg_name, tier in (("build_model", build_model), ("critic_model", critic_model)):
    if tier not in VALID_TIERS:
        raise ValueError(
            f"Invalid {arg_name}={tier!r} for run_workflow (allowed: {sorted(VALID_TIERS)}). "
            "For exact Claude/GPT/Argon model IDs, dispatch native `swarm` workers instead."
        )

if len(tasks) > 3:
    raise ValueError(
        f"Vertical-slice cap exceeded: {len(tasks)} commits requested (max 3 per loop). "
        "Split into sequential <=3-commit slices to prevent cross-commit drift."
    )

BUILD_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked"]},
        "commit_sha": {"type": "string"},
        "files_touched": {"type": "array", "items": {"type": "string"}},
        "handoff": {"type": "string"},
        "concerns": {"type": "string"},
    },
    "required": ["status", "files_touched", "handoff"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "REQUEST_CHANGES"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["blocker", "high", "medium", "low"]},
                    "kind": {"type": "string", "enum": ["correctness", "test_gap", "rigor", "docs"]},
                    "location": {"type": "string"},
                    "what": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["id", "severity", "kind", "location", "what", "fix"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["verdict", "findings", "summary"],
}


async def run_quiet_gate(cmd, label):
    try:
        out = await call_tool(
            "run_command",
            CommandLine=cmd,
            toolSummary=label,
            WaitMsBeforeAsync=10000,
        )
        ok = ("GATE FAIL" not in out and "gate: FAIL" not in out) and (
            "Command exited with code 0" in out or "gate: PASS" in out or "GATE OK" in out or "GATE FAST OK" in out
        )
        return ok, out
    except ToolError as exc:
        return False, str(exc.message)


phase("stage-4-tdd-build-loop")


async def build_one_commit(task):
    tid = task["id"]
    title = task.get("title", tid)
    commit_msg = task.get("commit_msg", f"feat: {title}")
    cmd = fast_cmd if task.get("fast_only") else gate_cmd

    log(f"[{tid}] Dispatching fresh TDD builder: {title}")
    builder_prompt = f"""You are a fresh TDD Builder for commit `{tid}` ({title}).
Read ONLY `{plan_path}` (section `{tid}` + Shared Invariants) and the exact files listed for `{tid}`.
Also check `{spec_path}` only if a rule reference needs clarification.
Rules:
1. Work test-first: add/update the assertions specified for `{tid}` and verify red -> green.
2. Batch reads and edits cleanly. Do not touch files outside `{tid}`'s scope.
3. Run `{cmd}` before finishing.
4. Stage and commit ONLY `{tid}`'s files with message: `{commit_msg}` (skip commit if status is blocked).
5. Return via finish() with a concise <=15-line `handoff` (files touched, tests run, what not to re-read)."""

    res = await agent(
        prompt=builder_prompt,
        role=f"Builder {tid}",
        model=build_model,
        type_name="self",
        workspace="inherit",
        schema=BUILD_SCHEMA,
    )
    if res["status"] == "blocked":
        raise RuntimeError(f"Builder {tid} reported blocked: {res.get('concerns') or res['handoff']}")

    # Deterministic Python gate check (0 LLM tokens!)
    for attempt in range(2):
        ok, gate_out = await run_quiet_gate(cmd, f"Quiet gate after {tid}")
        if ok:
            log(f"[{tid}] Gate PASS")
            return {"task": tid, **res}

        log(f"[{tid}] Gate FAILED (retry {attempt + 1}/2) — dispatching fresh fixer")
        fixer_prompt = f"""You are a fresh Fixer for commit `{tid}` ({title}).
The quiet gate `{cmd}` failed. Fix ONLY the root cause, re-run `{cmd}` until green, and amend/commit cleanly.
Previous builder handoff:
{res['handoff']}

Failing gate output (tail):
{gate_out[-2500:]}"""
        res = await agent(
            prompt=fixer_prompt,
            role=f"Fixer {tid} #{attempt + 1}",
            model=build_model,
            type_name="self",
            workspace="inherit",
            schema=BUILD_SCHEMA,
        )

    ok, gate_out = await run_quiet_gate(cmd, f"Final gate check for {tid}")
    if not ok:
        raise RuntimeError(f"Commit {tid} failed gate after 2 fix retries:\n{gate_out[-1500:]}")
    return {"task": tid, **res}


build_results = await pipeline(tasks, build_one_commit)

# Always run the FULL quiet gate before branch review
phase("full-gate-before-review")
full_ok, full_out = await run_quiet_gate(gate_cmd, "Full quiet gate before review")
if not full_ok:
    raise RuntimeError(f"Full quiet gate failed before branch review:\n{full_out[-2000:]}")
log("Full quiet gate PASS before branch review")

if skip_critic:
    log("Skipping in-workflow critic (skip_critic=True) — Stage 5 handled by cross-family Swarm Critic")
    print(json.dumps({
        "slug": slug,
        "commits_built": len(build_results),
        "review_verdict": "DEFERRED_TO_SWARM_CRITIC",
        "review_report": None,
        "actionable_findings_fixed": 0,
        "fix_commit": None,
    }, indent=2))
else:
    # Stage 5: 1 Fresh Adversarial Whole-Branch Critic
    phase("stage-5-adversarial-branch-review")
    try:
        diff_stat = await call_tool(
            "run_command",
            CommandLine=f"git diff --stat {base_ref}...HEAD",
            toolSummary="Branch diff summary",
            WaitMsBeforeAsync=5000,
        )
    except ToolError as exc:
        diff_stat = f"(diff summary unavailable: {exc.message})"
    critic_prompt = f"""You are a fresh-context Adversarial Whole-Branch Code Reviewer.
Your job is to find REAL bugs, missing edge-case tests, and spec/rigor violations — never style nits.
Review the diff `{base_ref}...HEAD` against `{spec_path}` and repo rigor rules (`CLAUDE.md` / `.loop/PROJECT.md` if present).
Diff summary:
{diff_stat}

Instructions:
1. Run `git diff {base_ref}...HEAD` (targeted by file if large) and inspect touched production & test files.
2. Hunt specifically for: real behavioral bugs, state leaks between tests, stand-in fixtures masking broken wiring,
   hardcoded configuration/magic numbers, and stale docs.
3. Do NOT edit any code. Return structured findings via finish()."""

    review = await agent(
        prompt=critic_prompt,
        role="Adversarial Branch Critic",
        model=critic_model,
        type_name="research",
        workspace="inherit",
        schema=REVIEW_SCHEMA,
    )

    # Save review report
    out_dir = os.path.join(".loop", slug)
    os.makedirs(out_dir, exist_ok=True)
    review_path = os.path.join(out_dir, "branch-review.md")
    rev_lines = [
        f"# Whole-Branch Review: {slug}",
        f"- **Verdict:** {review['verdict']} — {review['summary']}",
        "",
    ]
    for f in review["findings"]:
        rev_lines.append(
            f"- **[{f['severity'].upper()} / {f['kind']}] {f['id']}** (`{f['location']}`): {f['what']} -> *{f['fix']}*"
        )
    with open(review_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rev_lines) + "\n")

    actionable = [f for f in review["findings"] if f["severity"] in ("blocker", "high")]
    fix_res = None
    if actionable:
        phase("stage-5-review-fix-pass")
        log(f"Branch Critic found {len(actionable)} blocker/high findings — dispatching 1 fixer pass")
        findings_txt = "\n".join(
            f"- [{f['severity'].upper()}] {f['id']} ({f['location']}): {f['what']} | Fix: {f['fix']}"
            for f in actionable
        )
        fix_res = await agent(
            prompt=f"""Fix all blocker/high findings from whole-branch review, add regression tests, run `{gate_cmd}`, and commit as `fix: branch review findings for {slug}`.
Findings:
{findings_txt}""",
            role="Review Fixer",
            model=build_model,
            type_name="self",
            workspace="inherit",
            schema=BUILD_SCHEMA,
        )
        final_ok, final_out = await run_quiet_gate(gate_cmd, "Final quiet gate after review fixes")
        if not final_ok:
            raise RuntimeError(f"Final quiet gate failed after review fixes:\n{final_out[-1500:]}")
        log("Final quiet gate PASS after review fixes")

    print(json.dumps({
        "slug": slug,
        "commits_built": len(build_results),
        "review_verdict": review["verdict"],
        "review_report": review_path,
        "actionable_findings_fixed": len(actionable),
        "fix_commit": fix_res.get("commit_sha") if fix_res else None,
    }, indent=2))
