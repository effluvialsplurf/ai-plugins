# 3-Pool Quota-Balanced Model Routing (Antigravity 2.0 Native `swarm`)

Distribute token consumption across all **3 independent weekly quota pools** instead of draining a single pool.

## Why `/teamwork`, `invoke_subagent`, and `run_workflow` Drain Gemini-Only Quota

| Mechanism | Can Pick Claude / GPT / Argon? | What Actually Happens |
|---|---|---|
| **`/teamwork` slash command** | **No** | Launches an internal `teamwork` subagent (`sentinel` → `teamwork_orchestrator`) that **does not have the `swarm` tool**. Every worker, scout, critic, and auditor runs via `invoke_subagent` on **Gemini Models** (`gemini-4-hydrogen-*`). Even "Cross-Family Critics" silently run on Gemini. |
| **`invoke_subagent` / `run_workflow`** | **Only via `inherit` inside a non-Gemini worker** | Only accepts abstract tiers (`inherit`, `flash_lite`, `flash`, `pro`). Calling `flash` or `pro` always hits **Gemini Models**; `inherit` inherits the caller's model. |
| **Native `swarm` tool (in a normal chat)** | **Yes — all 3 pools + live quotas** | Available directly in standard Antigravity 2.0 conversations (no `/teamwork` needed). Supports exact model IDs (`swarm(action="add", model=...)`), isolated git worktrees (`workspace: "share"`), live quota checks (`swarm(action="models", all=True)`), and live model switching (`swarm(action="model", ...)`). |

> **Hard Rule:** Never tell the user to run `/teamwork` for `lean-runbook` slices or epics. Always orchestrate directly from a normal conversation using the native **`swarm`** tool.

---

## 1. The 3 Independent Quota Pools

Run `swarm(action="models", all=True)` at Stage 0 (or start of an Epic wave) to verify exact IDs and live `quota_remaining`:

| Pool | Reset Window | Exact Model IDs | Primary Strength |
|---|---|---|---|
| **Pool 1: Gemini Models** | 5-hour + Weekly | `gemini-3.8-flash-{low,medium,high}`<br>`gemini-4-neon-{low,medium,high,xhigh}`<br>`gemini-4-hydrogen-{low,medium,high,xhigh}`<br>`gemini-pro-orchestrator-neon` | **Preferred for all non-implementation & review steps** (`gemini-4-neon-medium` for planning/Goldfish, `gemini-4-neon-high` for cross-vendor reviews when Claude built), plus cheap scouting & clarity passes (`gemini-3.8-flash-low` / `-medium`) |
| **Pool 2: Claude & GPT** | Independent 5-hour + Weekly | `claude-sonnet-5-5-{low,medium,high}`<br>`claude-opus-5-5-{low,medium,high}`<br>`gpt-oss-120b-medium` | Primary TDD Builder / Slice Worker (`claude-sonnet-5-5-medium`, or Pool 4 `claude-sub`), flagship Adversarial Critic when Gemini built (`claude-opus-5-5-high`, or Pool 4 `claude-sub` `opus` `high`), lightweight clarity/alt (`gpt-oss-120b-medium`) |
| **Pool 3: Gemini 4 Argon** | Independent Weekly | `gemini-4-argon-{low,medium,high}`<br>`gemini-pro-orchestrator-argon` | Parallel implementation Slice Worker (`gemini-4-argon-medium`), and fallback for planning/review only if Pool 1 Neon drops below 25% |

---

## 2. Default Seat Matrix (All Slices & Epics — Neon for Non-Implementation & Reviews)

Use this allocation by default so **every** feature — Single Slice, Mini-Series, and Epic — uses **Gemini 4 Neon** for planning, Goldfish, and reviews, while spreading implementation across Claude (Pool 2 / Pool 4 `claude-sub`) and Argon (Pool 3) with **true cross-family verification**:

| Stage / Seat | Swarm `name` | `workspace` | Default Model | Pool | Fallback if Pool < 25% |
|---|---|---|---|---|---|
| **Coordinator** | Main chat | main repo | User's current chat model (stay thin!) | Any | Switch via `swarm(action="model", model="gemini-pro-orchestrator-neon")` or `"gemini-pro-orchestrator-argon"` only if quota/capacity hits limit or user asks |
| **Stage 0–1 Scout** | `scout` (or `epic-scout`) | `inherit` (read-only) | `gemini-3.8-flash-low` | **Pool 1** | `gpt-oss-120b-medium` (Pool 2) or `claude-sonnet-5-5-low` (Pool 2) |
| **Stage 2 Goldfish Clarity** | `goldfish-clarity` | `inherit` (read-only) | `gemini-3.8-flash-medium` *(or `gemini-4-neon-medium`)* | **Pool 1** | `gpt-oss-120b-medium` (Pool 2) |
| **Stage 2 Goldfish Critic** | `goldfish-critic` | `inherit` (read-only) | **`gemini-4-neon-medium`** | **Pool 1** | `gemini-4-argon-medium` (Pool 3) or `claude-opus-5-5-medium` (Pool 2) / Pool 4 `claude-sub` |
| **Stage 3 Contract Planner** | `planner-<slug>` | `inherit` (read-only) | **`gemini-4-neon-medium`** *(or `gemini-4-neon-high` for complex slices)* | **Pool 1** | `gemini-4-argon-medium` (Pool 3) or `claude-sonnet-5-5-high` (Pool 2) / Pool 4 `claude-sub` |
| **Stage 4 Builder / Slice Worker** | `builder-<slug>` or `slice-<slug>` | `inherit` (1 slice) or **`share`** (parallel / epic) | `claude-sonnet-5-5-medium` (Pool 2) or **Pool 4 `claude-sub`** (`sonnet`) | **Pool 2 / Pool 4** | `gemini-4-argon-medium` (Pool 3), or `gemini-4-neon-medium` (Pool 1) if Pools 2, 3 & 4 are exhausted |
| **Stage 5 Adversarial Critic** | `critic-<slug>` | `inherit` (read-only) | **Strict opposite vendor from Builder:**<br>• Claude/GPT built (`claude-*`/`gpt-*`/`claude-sub/*`) → **`gemini-4-neon-high`**<br>• Argon/Neon/Gemini built → `claude-opus-5-5-high` (Pool 2) or **Pool 4 `claude-sub` (`opus`, `high`)** | **Pool 1** / **Pool 2 or 4** | `gemini-4-argon-high` (if Neon < 25%) or `claude-sonnet-5-5-high` / Pool 4 `sonnet` `high` (if Opus 5h-limited). **Never claim cross-family if both are Gemini or both are Claude.** |

### Cross-Vendor Verification Receipt (Mandatory for Stage 5)
1. **Strict vendor opposition:** Any `gemini-*` builder MUST be reviewed by a `claude-*` / `claude-sub/*` critic (`claude-opus-5-5-high` or Pool 4 `claude-sub` `opus` `high`, fallback `sonnet` `high`). Any `claude-*` / `claude-sub/*` / `gpt-*` builder MUST be reviewed by a `gemini-*` critic (**`gemini-4-neon-high`** preferred; fallback `gemini-4-argon-high`).
2. **Verify via `swarm(action="status")`:** Before marking Stage 5 done, verify from `swarm(action="status")` (and `[claude-sub receipt]` if Pool 4 was used) that the builder and critic actually ran on opposite vendors, and record both exact model IDs at the top of `.loop/<slug>/branch-review.md` (and in `EPIC.md`'s Merge Log):
   `Builder: <exact-model-id> | Critic: <exact-model-id>`
3. **Fail loud if `swarm` is unavailable:** Never silently downgrade a cross-family review to `invoke_subagent` or `run_workflow` (which run on the same vendor). If `swarm` is not available in the current session, stop and tell the user before merging.

### Parallel Wave Load-Balancing (2–3 Concurrent `workspace: "share"` Slices)
When running 2–3 disjoint slices concurrently in an Epic wave, **split builders across Claude (Pool 4 / Pool 2) and Argon (Pool 3)** so Neon quota stays reserved for planning & reviews:
- **Worker 1:** Pool 4 `claude-sub` (`sonnet` via `gemini-3.8-flash-low` relay) or `claude-sonnet-5-5-medium` (Pool 2) → reviewed by **`gemini-4-neon-high`** (Pool 1)
- **Worker 2:** `gemini-4-argon-medium` (Pool 3) → reviewed by **Pool 4 `claude-sub` (`opus`, `high`)** or `claude-opus-5-5-high` (Pool 2)
- **Worker 3 (if needed):** Pick whichever of Pool 2, Pool 4, Pool 3, or Pool 1 (`gemini-4-neon-medium`) has the highest remaining quota from `swarm(action="models", all=True)`.

---

## 3. Using `run_workflow` Safely Inside Non-Gemini Swarm Workers

When a `swarm` Slice Worker (e.g., `claude-sonnet-5-5-medium` or `gemini-4-argon-medium`) uses `run_workflow` for deterministic Python loops:
- **`build_loop.py`:**
  - Always pass `"build_model": "inherit"` so every TDD Builder and Fixer inherits the worker's own pool (Claude Sonnet or Gemini 4 Argon) instead of dropping back to Gemini Models.
  - Pass `"skip_critic": true` whenever the Coordinator will run Stage 5 with a dedicated cross-family `swarm` critic (`critic-<slug>`). This eliminates paying for a redundant same-family review pass.
- **`goldfish_gate.py`:**
  - Prefer spawning `goldfish-clarity` + `goldfish-critic` via `swarm(action="add", ...)` directly so Pass 1 and Pass 2 run across two pools (e.g., Flash + Argon or GPT + Argon).
  - If running `goldfish_gate.py` inside a Claude/Argon worker, pass `"clarity_model": "flash"` (tiny Pool 1 cost) and `"adversarial_model": "inherit"` (stays on the worker's Claude/Argon pool instead of hitting Gemini Pro!).

---

## 4. Quota Hygiene & Lifecycle Rules

1. **Check live quotas first:** Call `swarm(action="models", all=True)` once per session or wave before choosing builder/critic pools.
2. **Keep the Coordinator thin:** Even if the main chat is on `Gemini 4 Neon (High)`, keeping all scouting, planning, building, and diff-reading on `swarm` workers keeps main-window token burn near zero.
3. **Reuse idle read-only workers:** `waiting` workers cost **0 tokens**. Keep `scout` / `epic-scout` alive across stages instead of respawning it.
4. **Retire finished workers cleanly:**
   - Kill one-shot reviewers/planners (`goldfish-*`, `planner-*`, `critic-*`) once their report is consumed.
   - Kill `workspace: "share"` Slice Workers **only after** their branch is merged into `epic/<epic-slug>` (killing deletes the `share` worktree).
5. **Switch instead of killing on quota exhaustion:** If a `waiting` worker's pool hits a limit, move it to another pool with `swarm(action="model", name="<worker>", model="<new-model>")` so it keeps its context.
6. **Avoid branch checkout collisions in read-only critics:** When a `share` Slice Worker still has `slice/<slug>` checked out, instruct `critic-<slug>` to inspect `git diff epic/<epic-slug>...slice/<slug>` directly (or `git checkout --detach slice/<slug>`) so it never wastes turns hitting `already used by worktree`.
