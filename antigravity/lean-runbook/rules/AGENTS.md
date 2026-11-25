# Multi-Pool Token & Model Routing (Antigravity 2.0)

This workspace's plan has **3 independent weekly quota pools**:
1. **Gemini Models** — `gemini-3.8-flash-*`, `gemini-4-neon-*`, `gemini-4-hydrogen-*`, `gemini-pro-orchestrator-neon`
2. **Claude & GPT** — `claude-sonnet-5-5-*`, `claude-opus-5-5-*`, `gpt-oss-120b-medium`
3. **Gemini 4 Argon** — `gemini-4-argon-*`, `gemini-pro-orchestrator-argon`

## Rules for Balancing Quota Across All 3 Pools
- **Never use `/teamwork` for multi-model or `lean-runbook` work.** `/teamwork` launches an internal `teamwork_orchestrator` hierarchy that lacks the `swarm` tool and forces every worker, scout, and critic onto Gemini Models (`invoke_subagent` tiers only). Always orchestrate directly in a normal chat via the native **`swarm`** tool.
- **Avoid piling heavy work onto `invoke_subagent` or a Gemini main window.** `invoke_subagent` and `run_workflow` only accept abstract tiers (`inherit`, `flash_lite`, `flash`, `pro`), which hit Gemini Models when called from a Gemini session.
- **Keep trivial work (1–2 turns, quick Q&A, single tiny edit) in the main chat** — no swarm overhead.
- **For substantive coding, planning, debugging, code review, or multi-step features**, call `swarm(action="models", all=True)` once to inspect live quotas and distribute workers across all pools (**prefer `gemini-4-neon-*` over Argon for all non-implementation and review steps**):
  - **Scouting / Read-only lookup (`inherit`):** `gemini-3.8-flash-low` (Pool 1; or `gpt-oss-120b-medium` if Pool 1 is low).
  - **Building / Implementation (`inherit` or `share`):** `claude-sonnet-5-5-medium` (Pool 2) or Pool 4 `claude-sub` (personal Claude subscription) primary; alternate with `gemini-4-argon-medium` (Pool 3) when running parallel workers or when Claude pools are low.
  - **Planning / Design / Spec Review (`inherit`):** **`gemini-4-neon-medium`** / **`gemini-4-neon-high`** (Pool 1 preferred; fallback `gemini-4-argon-medium` if Pool 1 < 25%, or `claude-sonnet-5-5-high` / Pool 4 `claude-sub`).
  - **Adversarial Review / Critic (`inherit`):** Always **strict cross-vendor** opposite the builder — **Claude** built (`claude-*`/`gpt-*`/`claude-sub/*`) → **`gemini-4-neon-high`** (Pool 1 preferred; fallback `gemini-4-argon-high` if Pool 1 < 25%); **Gemini** built (`gemini-*`) → **`claude-opus-5-5-high`** (Pool 2) or **Pool 4 `claude-sub` (`opus`, `high`)** (fallback `claude-sonnet-5-5-high`). Never treat Gemini reviewing Gemini as cross-family; if `swarm` is unavailable (e.g., inside `/teamwork`), warn the user instead of silently running same-family review.
- **Rebalance dynamically:** If any pool drops below 25% remaining or hits a 5-hour limit, route new workers to the highest-remaining pool and use `swarm(action="model", ...)` to move `waiting` workers (never `kill` + `add` just to change models).
- Full seat matrices and `lean-runbook` integration live in `lean-runbook/references/quota-routing.md`.
