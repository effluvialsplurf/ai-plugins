---
name: lean-runbook
description: >-
  Token-efficient, 3-pool quota-balanced 5-stage EGM + Build-Loop workflow for Antigravity 2.0
  ("start lean runbook for <slug>", "start lean runbook epic for <epic>", "lean runbook status",
  "run the lean loop"). Performs Stage 0 vertical-slice triage and live quota checks via native `swarm`
  (NEVER `/teamwork`, which forces Gemini-only subagents), routing to 1 slice, 2-4 sequential slices,
  or Epic Orchestrator mode with isolated `workspace: "share"` Slice Workers. Enforces a <=300-line
  compact EGM spec, 2-pass parallel Goldfish gate (hook-enforced no-code before signoff), <=300-line
  contract plan, TDD build loop with 1-line quiet gates, and true cross-family adversarial whole-branch
  review distributed across Claude & GPT, Gemini 4 Argon, and Gemini Models pools.
---

# lean-runbook (Antigravity 2.0 Native · 3-Pool Quota-Balanced)

A disciplined, token-budgeted workflow combining Stage 0 vertical-slice triage, EGM's fresh-context
Goldfish review, and **3-pool quota-balanced native `swarm` orchestration** — scaling seamlessly from
single vertical slices to multi-worker **Epic Orchestration**.

Run state commands with:

`python3 ~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/scripts/runbook.py <subcommand>`
*(Outside Antigravity, substitute the path to `runbook.py` in your local checkout or installed skills directory — the CLI subcommands `start`, `status`, `done`, `skip`, `finish` and all `templates/*.md` are pure Python 3.9+ stdlib and Markdown.)*

State lives outside the repo (`${PLUGIN_DATA}` or `~/.cache/lean-runbook/`) and is keyed per git working
tree, so parallel `workspace: "share"` workers automatically get independent Spec Gates. Lifecycle hooks
enforce the no-code-before-Goldfish gate and warn if specs or plans exceed the 300-line token budget.

> **NEVER use `/teamwork` with `lean-runbook`!** `/teamwork` launches an internal `teamwork_orchestrator`
> subagent that **lacks the `swarm` tool** and runs every worker, scout, and critic on `Gemini Models`
> (`invoke_subagent` tiers only) — burning a single quota pool and defeating cross-family review.
> Always run `lean-runbook` directly in a normal Antigravity 2.0 chat using the native **`swarm`** tool.
>
> **Automatic 3-Pool Routing:** Never ask the user to manually define subagents or model tiers. Always
> run `swarm(action="models", all=True)` at Stage 0 and assign seats across **Pool 1 (Gemini Models)**,
> **Pool 2 (Claude & GPT)**, and **Pool 3 (Gemini 4 Argon)** per [references/quota-routing.md](./references/quota-routing.md).
>
> **Using outside Antigravity 2.0 or with other model families?** The 5-stage vertical-slice workflow,
> `runbook.py` CLI, and `templates/*.md` work on any harness/model family; however, `hooks.json`,
> `workflows/*.py` (`run_workflow`), `rules/AGENTS.md`, and `swarm` commands are Antigravity-native.
> See `docs/PORTABILITY.md` and `docs/CONVERSION-PROMPTS.md` in the `ai-plugins` repo to convert hooks,
> model seats, and orchestration to Claude Code, Codex CLI, Gemini CLI, OpenCode, Cursor, or open-weights models.

## Stage 0: Pre-Flight, Quota Check & 3-Way Scope Triage (BEFORE `runbook.py start`)

> **Incoming from `lean-design` (`docs/designs/<slug>/spec.md`)?** If the user points to an approved
> `lean-design` suite (`design.md`, `tech-plan.md`, `spec.md`), **skip redundant brainstorming**:
> read `spec.md` directly (cite `BR-*`/`RISK-*`/`INV-*` by ID) and seed either `docs/specs/<slug>.md`
> (Single Slice), the approved Slice Roadmap (Mini-Series), or `.loop/epics/<slug>/EPIC.md` Sections
> 1–3 (Epic Mode) straight from `spec.md`. For project-level design/rearchitecture before implementation,
> invoke the sibling `lean-design` skill first.

Whenever the user asks to build a feature, feature set, or epic, **do not cram everything into one spec**:
1. **Check live quotas:** Call `swarm(action="models", all=True)` and read [references/quota-routing.md](./references/quota-routing.md).
2. **Load `swarm_pane` skill** before adding the first workers so the Swarm Overview UI stays organized.
3. **Scout cheaply:** Spawn `scout` (or `epic-scout`) on **`gemini-3.8-flash-low`** (`workspace: "inherit"`, read-only; fallback `gpt-oss-120b-medium` if Pool 1 < 25%) to inspect the touched repo area, then route using the **Scope & Vertical-Slice Rubric**:

| Signal | Single Slice (1 loop) | Mini-Series (2–4 sequential slices) | Epic Mode (Native `swarm` Orchestrator) |
|---|---|---|---|
| **Estimated size** | ≤3 commits & ≤600 LOC | 4–10 commits (2–4 slices) | **>4 slices** or multi-system overhaul |
| **Subsystem span** | 1–2 tightly coupled layers | 3–4 layers with linear dependencies | Many interacting systems + parallelizable workstreams |
| **Requirements clarity** | Clear, bounded CUJs | Mostly clear; cleanly sliceable up front | **Heavy brainstorming / evolving scope / unforeseen work expected** |
| **Spec complexity** | ≤300 lines (≤10 key CUJs) | 2–4 compact specs | Needs a long-lived Epic Ledger (`EPIC.md`) + Discovery Inbox |
| **Risk isolation** | Uniform risk profile | 1 high-risk slice + low-risk plumbing | Mixed risks requiring per-slice pool routing & cross-slice integration gates |

**Routing action:**
- **Single Slice:** State briefly why it fits 1 slice (`~N commits, ~M LOC`) + your 3-pool seat plan, and immediately run `runbook.py start <slug>`.
- **Mini-Series (2–4 slices):** Propose a **Slice Roadmap table** (`Slice # | Slug | Testable Deliverable | Est. Commits/LOC | Depends On | Builder / Critic Pools`), get user approval (suggest `/grill-me` if fuzzy), record deferred slugs in Slice 1's Out of Scope, start **Slice 1 only**, and recommend `/compact` between slices.
- **Epic Mode (>4 slices, open-ended brainstorming, or parallel workstreams):**
  **Read [references/epic-orchestration.md](./references/epic-orchestration.md)** and follow it directly in this chat (do **NOT** advise `/teamwork`). Keep the main chat as a thin **Epic Coordinator** owning `epic/<epic-slug>` + `.loop/epics/<epic-slug>/EPIC.md` (from [templates/epic-ledger.md](./templates/epic-ledger.md)), and dispatch isolated **`workspace: "share"` Slice Workers** distributed across Claude Sonnet 5.5 and Gemini 4 Argon.

### Pre-Flight Environment Check
- **Quiet gate discovery:** Detect `tools/gate.sh` (or ask the user for the repo's quiet test command to pass as `gate_cmd`/`fast_cmd`).
- **`run_workflow` permissions (when used inside a worker):** Commands executed inside `run_workflow` via `call_tool` cannot prompt interactively—ensure sandbox execution (`proceed-in-sandbox`) or allowlist `tools/gate.sh` and `git`.

## 5 Stages & Hard Budgets (3-Pool Default)

| # | Stage | Default Native `swarm` Seat & Pool | Artifact & Hard Budget | Gate / Exit |
|---|---|---|---|---|
| 1 | **Compact EGM Spec** | Thin Coordinator + `scout` (**Pool 1:** `gemini-3.8-flash-low`, read-only) | `docs/specs/<slug>.md` (**≤300 lines**, ≤3 commits / ≤600 LOC slice) + init `.loop/<slug>/LOOP-STATE.md` | Gate **CLOSED** (hook blocks repo code edits) |
| 2 | **2-Pass Goldfish Gate** | 2 parallel read-only `swarm` reviewers: `goldfish-clarity` (**Pool 1:** `gemini-3.8-flash-medium`) + `goldfish-critic` (**Pool 3:** `gemini-4-argon-medium`, or Pool 2 `claude-opus-5-5-medium`) | `.loop/<slug>/goldfish-report.md` (clarity + adversarial verification vs real code) | Resolve findings with user → `done goldfish` (**user-approved `force_ask` opens Gate**) |
| 3 | **Contract Plan** | 1 fresh read-only `planner-<slug>` (**Pool 3:** `gemini-4-argon-medium`, or Pool 2 `claude-sonnet-5-5-high`) | `.loop/<slug>/plan.md` (**≤300 lines**, signatures + invariants + test assertions only) | **Zero pasted full code; zero scratch-repo dry-runs** |
| 4 | **TDD Build Loop** | `builder-<slug>` / `slice-<slug>` (**Pool 2:** `claude-sonnet-5-5-medium`; alternate Pool 3 `gemini-4-argon-medium` on parallel waves) — optionally driving `workflows/build_loop.py` with `build_model: "inherit", skip_critic: true` | Commits directly on feature branch + `.loop/<slug>/LOOP-STATE.md` | 1-line quiet gate (`tools/gate.sh`) after every commit; fresh fixer on FAIL only (max 2) |
| 5 | **Adversarial Diff & Ship** | Fresh read-only `critic-<slug>` on **strict opposite vendor**: Claude/GPT built → **Pool 3** (`gemini-4-argon-high`); any Gemini built → **Pool 2** (`claude-opus-5-5-high`). Verify both models via `swarm(action="status")`! | `.loop/<slug>/branch-review.md` (with `Builder:` & `Critic:` model receipt) → 1 fixer pass for blocker/high → PR/merge | Quiet gate green → `finish` → `swarm(action="kill", ...)` retired workers (suggest `/compact` before next slice) |

## How to Organize Agents in Antigravity 2.0

### 1. Default: Native `swarm` Across All 3 Quota Pools (Read [references/quota-routing.md](./references/quota-routing.md))
Always prefer `swarm(action="add", model=...)` over `invoke_subagent` for Stage 0–5 seats so you never drain `Gemini Models` alone:
- **Why:** `invoke_subagent` and `run_workflow` only accept abstract tiers (`inherit`, `flash_lite`, `flash`, `pro`), which all hit `Gemini Models` when called from a Gemini main window. Native `swarm` pins exact models across **Gemini Models**, **Claude & GPT**, and **Gemini 4 Argon**, and exposes live remaining quotas via `swarm(action="models", all=True)`.
- **Keep the Coordinator thin:** Main chat handles user decisions, spec approval, `EPIC.md`/`LOOP-STATE.md`, and merges — never heavy file reading, coding, or raw diff inspection.
- **Rebalance dynamically:** If any pool drops below 25% remaining (or hits a 5-hour limit), shift new seats to the highest-remaining pool and switch `waiting` workers with `swarm(action="model", name=..., model=...)`.

### 2. Using `run_workflow` Inside a Non-Gemini Swarm Worker (Optional Deterministic Inner Loop)
When a `claude-sonnet-5-5-medium` or `gemini-4-argon-medium` Slice Worker wants zero-token Python loop orchestration across 2–3 commits:
- **Stages 4 (inside Slice Worker):** Call `run_workflow` with `ScriptPath` set to `~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/workflows/build_loop.py` and `Args: {"slug": "<slug>", "spec_path": "...", "plan_path": "...", "gate_cmd": "tools/gate.sh", "fast_cmd": "tools/gate.sh --fast", "base_ref": "<base>", "build_model": "inherit", "skip_critic": true, "tasks": [...]}`.
  - Setting `"build_model": "inherit"` keeps TDD builders/fixers on the worker's Claude/Argon pool (not Gemini Models).
  - Setting `"skip_critic": true` avoids paying twice when the Coordinator runs Stage 5 with a cross-family `swarm` critic (`critic-<slug>`).
- **Stage 2 fallback (only if `swarm` is unavailable):** Call `run_workflow` with `workflows/goldfish_gate.py` (`clarity_model: "flash"`, `adversarial_model: "inherit"` when called from a Claude/Argon worker, or `"pro"` otherwise).

## 5 Non-Negotiable Anti-Bloat Rules
1. **Vertical Slices Only:** Always run Stage 0 triage first. Never put >3 commits or >600 LOC in one loop—split larger features into 2–4 sequential vertical slices.
2. **Tables Over Prose:** Use [templates/compact-spec.md](./templates/compact-spec.md), [templates/contract-plan.md](./templates/contract-plan.md), and [templates/loop-state.md](./templates/loop-state.md). Rejected alternatives are 1-line table rows, never essays.
3. **No Scratch-Copy Dry-Runs:** Planners are read-only and write contracts (signatures, invariants, edge-case tables, test assertions). Builders implement & run tests directly on the branch.
4. **1-Line Quiet Gate:** Every project should expose a quiet gate script (e.g., `tools/gate.sh`) that prints 1 line on PASS (`GATE OK`) and only the failing tail on FAIL.
5. **Respect the Spec Gate:** Never attempt to bypass `hooks.json`. When Stage 2 is resolved (or the user explicitly wants an override), run `runbook.py done goldfish` or `runbook.py skip gate --reason "..."` — the hook prompts the user for explicit approval via `force_ask`.

## Quick Commands
- Start slice: `runbook.py start <slug> [--epic <epic-slug>]`
- Check status: `runbook.py status` (or `runbook.py status --all` / `--epic <epic-slug>` across worktrees)
- Mark stage done: `runbook.py done <spec|goldfish|plan|build|review>` (user approves `goldfish`)
- Override gate: `runbook.py skip gate --reason "<why>"` (user approves)
- Clear active feature: `runbook.py finish`
