---
name: lean-runbook
description: >-
  Token-efficient 5-stage EGM + Build-Loop workflow for Antigravity 2.0 ("start lean runbook for <slug>",
  "lean runbook status", "run the lean loop"). Enforces a <=300-line compact EGM spec, 2-pass parallel
  Goldfish gate (hook-enforced no-code before spec signoff), <=300-line contract plan (no full-code plans
  or scratch dry-runs), Python run_workflow TDD build loop with 1-line quiet gates, and fresh adversarial
  whole-branch review with cross-family model routing.
---

# lean-runbook (Antigravity 2.0 Native)

A disciplined, token-budgeted 5-stage workflow combining EGM's fresh-context Goldfish review with a
zero-token Python-orchestrated build loop (`run_workflow`). Designed to minimize token waste while
catching real correctness bugs where reviews actually pay.

Run state commands with:

`python3 ~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/scripts/runbook.py <subcommand>`

State lives outside the repo (`${PLUGIN_DATA}` or `~/.cache/lean-runbook/`). Lifecycle hooks enforce
the no-code-before-Goldfish gate and warn if specs or plans exceed the 300-line token budget.

## 5 Stages & Hard Budgets

| # | Stage | Orchestration Primitive | Artifact & Hard Budget | Gate / Exit |
|---|---|---|---|---|
| 1 | **Compact EGM Spec** | Main window + `lean-scout` (`flash_lite`/`flash`, read-only) | `docs/specs/<slug>.md` (**≤300 lines**, ≤3 commits / ≤600 LOC slice) | Gate **CLOSED** (hook blocks repo code edits) |
| 2 | **2-Pass Goldfish Gate** | `run_workflow` → [workflows/goldfish_gate.py](./workflows/goldfish_gate.py) | `.loop/<slug>/goldfish-report.md` (parallel Flash clarity + Pro adversarial vs code) | Resolve findings with user → `done goldfish` (**user-approved `force_ask` opens Gate**) |
| 3 | **Contract Plan** | 1 fresh `lean-planner` (**read-only — NO Bash/shell!**) | `.loop/<slug>/plan.md` (**≤300 lines**, signatures + invariants + test assertions only) | **Zero pasted full code; zero scratch-repo dry-runs** |
| 4 | **TDD Build Loop** | `run_workflow` → [workflows/build_loop.py](./workflows/build_loop.py) (or `/teamwork` cross-family mode) | Commits directly on feature branch + `.loop/<slug>/LOOP-STATE.md` | Python runs 1-line quiet gate (`tools/gate.sh`) after every commit; fresh fixer on FAIL only (max 2) |
| 5 | **Adversarial Diff & Ship** | Fresh Adversarial Branch Critic (built into `build_loop.py`, or cross-family `/teamwork` seat) | `.loop/<slug>/branch-review.md` → 1 fixer pass for blocker/high only → PR | Quiet gate green → `finish` |

## How to Organize Agents in Antigravity 2.0

### 1. Define Lean Subagents Once Per Session (Stages 1 & 3)
Use `define_subagent` with minimal write permissions so read-only seats stay cheap and can never dry-run scratch copies:
- **`lean-scout`** (`EnableWriteTools: false`, invoke with `Model: "flash_lite"` or `"flash"`): file lookups, symbol tracing, call-graph checks.
- **`lean-planner`** (`EnableWriteTools: false`, invoke with `Model: "inherit"` or `"pro"`): reads the approved `docs/specs/<slug>.md` + cited source files and returns the ≤300-line Contract Plan text for the main window to write to `.loop/<slug>/plan.md`. Because `EnableWriteTools: false`, it **cannot execute Bash or waste turns prototyping in scratch folders**.

### 2. Run Deterministic Loops in Python (`run_workflow` — Stages 2, 4 & 5)
Never keep the main orchestration window awake polling subagents or running test commands between commits:
- **Stage 2:** Call `run_workflow` with `ScriptPath` set to `~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/workflows/goldfish_gate.py` and `Args: {"slug": "<slug>", "spec_path": "docs/specs/<slug>.md"}`.
- **Stages 4–5:** Call `run_workflow` with `ScriptPath` set to `~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/workflows/build_loop.py` and `Args: {"slug": "<slug>", "spec_path": "...", "plan_path": "...", "gate_cmd": "tools/gate.sh", "fast_cmd": "tools/gate.sh --fast", "tasks": [...]}`.
- Every workflow agent returns a **strict JSON schema** (≤15-line handoff). Passing gates cost **0 LLM tokens**.

### 3. Optional Cross-Family `/teamwork` Mode
When working on a high-risk vertical slice where you want **true cross-vendor verification** across separate model families/quotas, run Stages 4–5 via `/teamwork` (`swarm`):
- **Coordinator:** `Orchestrator (Neon)` (or `Orchestrator (Argon)`) — thin controller, state in `.loop/<slug>/LOOP-STATE.md`.
- **Scout:** `Gemini 3.8 Flash (Low)`.
- **Builders (cap ≤3; use `workspace: "share"` only for disjoint files):** `Claude Sonnet 5.5 (Medium)` (or `Gemini 4 Neon (Medium)`).
- **Adversarial Critic (`workspace: "inherit"`):** Cross-family flagship — if Claude built, pin **`Gemini 4 Argon (High)`**; if Gemini built, pin **`Claude Opus 5.5 (High)`**.

## 5 Non-Negotiable Anti-Bloat Rules
1. **Vertical Slices Only:** Never put >3 commits or >600 LOC in one loop. Split large overhauls into 2–4 sequential mini-loops.
2. **Tables Over Prose:** Use [templates/compact-spec.md](./templates/compact-spec.md) and [templates/contract-plan.md](./templates/contract-plan.md). Rejected alternatives are 1-line table rows, never essays.
3. **No Scratch-Copy Dry-Runs:** Planners write contracts (signatures, invariants, edge-case tables, test assertions). Builders implement & run tests directly on the branch.
4. **1-Line Quiet Gate:** Every project should expose a quiet gate script (e.g., `tools/gate.sh`) that prints 1 line on PASS (`GATE OK`) and only the failing tail on FAIL.
5. **Respect the Spec Gate:** Never attempt to bypass `hooks.json`. When Stage 2 is resolved (or the user explicitly wants an override), run `runbook.py done goldfish` or `runbook.py skip gate --reason "..."` — the hook prompts the user for explicit approval via `force_ask`.

## Quick Commands
- Start feature: `runbook.py start <slug>`
- Check status: `runbook.py status`
- Mark stage done: `runbook.py done <spec|goldfish|plan|build|review>` (user approves `goldfish`)
- Override gate: `runbook.py skip gate --reason "<why>"` (user approves)
- Clear active feature: `runbook.py finish`
