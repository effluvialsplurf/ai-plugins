# Epic Orchestration Mode (Native `swarm` Coordinator + 3-Pool Slice Workers)

Load this reference (along with [harness-antigravity.md](./harness-antigravity.md) and the `swarm_pane` skill) when
**Stage 0** routes a large, brainstorming-heavy, or multi-workstream feature to **Epic Mode** (>4 slices,
evolving scope / unforeseen work, or parallel disjoint slices).

> **CRITICAL — NEVER use `/teamwork` for Epic Mode!**
> `/teamwork` launches an internal `teamwork_orchestrator` subagent that **cannot call `swarm`** and
> forces every worker, scout, critic, and auditor onto `Gemini Models` (`invoke_subagent` tiers only).
> Run Epic Mode directly from a normal Antigravity 2.0 conversation using the native **`swarm`** tool.

## Core Principle: Thin Coordinator, Quota-Balanced Slice Workers
The user should **never** have to manually define subagents or model tiers. The Coordinator uses this
playbook to inspect live quotas, assemble a 3-pool team via `swarm`, track long-term Epic state,
brainstorm design decisions with the user, and dispatch `lean-runbook` Slice Workers in isolated
`workspace: "share"` worktrees.

- **Coordinator owns:** `epic/<epic-slug>` integration branch, `.loop/epics/<epic-slug>/EPIC.md`,
  Swarm `plan.json` (via `swarm_pane`), live quota balancing (`swarm(action="models", all=True)`),
  brainstorming & Goldfish decision checkpoints with the user, cross-family critic dispatch, merging
  completed slices, running full integration `tools/gate.sh`, and retiring finished workers.
- **Coordinator NEVER:** writes slice code directly, runs build loops in its own window, or reads huge
  raw diffs (delegate scouting to `epic-scout`, building to `slice-*`, and diff review to `critic-*`).

---

## 1. Automatic 3-Pool Agent & Model Roster

Run `swarm(action="models", all=True)` at Epic start and before each new wave, then dispatch automatically
across all **3 independent weekly quota pools** (see [harness-antigravity.md](./harness-antigravity.md) for fallbacks):

| Seat | Swarm `name` | `workspace` | Default Model & Pool | When to Spawn |
|---|---|---|---|---|
| **Coordinator** | Main chat | main repo (`epic/<epic-slug>`) | Current chat model (keep thin; switch to `gemini-pro-orchestrator-neon` or `gemini-pro-orchestrator-argon` via `swarm(action="model", ...)` only on quota limit or user request) | Always — stays open for the Epic |
| **Epic Scout** | `epic-scout` | `inherit` (read-only) | **Pool 1:** `gemini-3.8-flash-low` *(fallback: `gpt-oss-120b-medium`)* | Stage 0 recon & checking unforeseen coupling during brainstorming (keep asleep at 0 tokens) |
| **Slice Worker (Wave Slot A)** | `slice-<short-slug>` | **`share`** (isolated git worktree) | **Pool 4:** `claude-sub` (`sonnet` via `gemini-3.8-flash-low` relay) or **Pool 2:** `claude-sonnet-5-5-medium` | Primary slice worker (**cap ≤3 concurrent**, ONLY on disjoint files) |
| **Slice Worker (Wave Slot B)** | `slice-<short-slug>` | **`share`** (isolated git worktree) | **Pool 3:** `gemini-4-argon-medium` | Concurrent wave partner — keeps Neon quota reserved for planning & reviews |
| **Cross-Family Critic** | `critic-<short-slug>` | `inherit` (read-only) | **Opposite flagship pool:**<br>• Claude built → **Pool 1:** **`gemini-4-neon-high`** *(preferred; fallback `gemini-4-argon-high` if Pool 1 < 25%)*<br>• Argon/Gemini built → **Pool 4:** `claude-sub` (`opus`, `high`) or **Pool 2:** `claude-opus-5-5-high` | Stage 5 whole-branch adversarial review before merging into `epic/<epic-slug>` |

> **Why `workspace: "share"` works seamlessly with `lean-runbook`:** `runbook.py` keys state by each
> git worktree's `--show-toplevel` path, so every `share` worker automatically gets its own independent
> Spec Gate. Inspect all active workers at once from the Coordinator with:
> `python3 ~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/scripts/runbook.py status --epic <epic-slug>`

---

## 2. Epic Setup Sequence (Coordinator)

1. **Check quotas & UI setup:** Call `swarm(action="models", all=True)` and read `swarm_pane` skill.
2. **Create integration branch:** `git checkout -b epic/<epic-slug>` (from `main` or user's base branch).
   - Ensure any untracked/ignored files needed by `share` worktrees (such as `tools/gate.sh` or `.loop/epics/<epic-slug>/EPIC.md` if `.loop/` is excluded) are committed on `epic/<epic-slug>` (`git add -f` for `EPIC.md` if needed) before spawning the first `share` worker.
3. **Initialize Epic Ledger:** Write `.loop/epics/<epic-slug>/EPIC.md` using `templates/epic-ledger.md`
   (capture locked gameplay/architecture rulings, initial Slice Board with assigned Builder/Critic pools, and Shared Contracts).
4. **Brainstorm first:** Spawn `epic-scout` (`gemini-3.8-flash-low`, `workspace: "inherit"`) for cheap read-only codebase recon, resolve core Epic design questions with the user (suggest `/grill-me` if helpful), and lock initial rulings in `EPIC.md` before dispatching Slice 1.
5. **Update Swarm Overview:** After adding the first workers, write `<appData>/brain/<conversation-id>/.system_generated/swarm/plan.json` per `swarm_pane`.

---

## 3. Slice Worker Brief Template (Coordinator → `swarm(action="add")`)

Before dispatching a slice:
- Verify dependencies are already merged into `epic/<epic-slug>`.
- Verify target files are disjoint from any other currently running `slice-*` worker.
- Pick the worker's model from the highest-remaining builder pool (**Pool 4** `claude-sub` via `gemini-3.8-flash-low` relay, **Pool 2** `claude-sonnet-5-5-medium`, or **Pool 3** `gemini-4-argon-medium`, alternating across concurrent wave slots) and record its Builder/Critic pools on the Slice Board in `EPIC.md`.

Then post this brief with `workspace: "share"`:

```text
You are Slice Worker `slice-<short-slug>` for Epic `<epic-slug>` (Slice #<N>: `<slice-slug>`).
Read `~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/SKILL.md` and `.loop/epics/<epic-slug>/EPIC.md`.

Your assignment:
- Branch: `git checkout -b slice/<slice-slug> epic/<epic-slug>`
- Scope (<=3 commits, <=600 LOC): <1-3 line description of deliverable & exact target files/subsystems>
- Rely on these Shared Contracts from EPIC.md: <list canonical symbols/files>
- Quiet gate: `<gate_cmd>` (fast: `<fast_cmd>`)
- Rigor rules: `<rigor>`
- Stage 5 Critic: Handled by Coordinator on the opposite model family (`critic-<short-slug>`).

Follow `lean-runbook` strictly inside your worktree:
1. Run `python3 ~/.gemini/config/plugins/lean-runbook/skills/lean-runbook/scripts/runbook.py start <slice-slug> --epic <epic-slug>`.
2. Inspect ONLY your slice's files (do NOT edit code yet) and write `docs/specs/<slice-slug>.md` (<=300 lines, tables over prose) + `.loop/<slice-slug>/LOOP-STATE.md`.
3. Stage 2 Goldfish Gate: Run `workflows/goldfish_gate.py` via `run_workflow` with `clarity_model: "flash"` and `adversarial_model: "inherit"` (so adversarial review stays on your assigned pool), OR verify every claimed symbol/invariant directly if `run_workflow` is unavailable.
4. **CHECKPOINT — STOP & REPORT TO @coordinator:** Post a <=12-line summary of Goldfish blockers/important findings and any design questions. Wait for `@coordinator` rulings and Spec Gate approval (`done goldfish`) before writing code.
5. After gate opens: Write `.loop/<slice-slug>/plan.md` (<=300 lines, <=3 commits, signatures + invariants + test assertions only — NO pasted code, NO scratch dry-runs), then implement TDD commits cleanly (or run `workflows/build_loop.py` with `base_ref: "epic/<epic-slug>"`, `build_model: "inherit"`, `skip_critic: true`).
6. **Unforeseen Work Rule:** If you discover unexpected coupling or missing prerequisites outside your <=3-commit budget, DO NOT expand scope. Report `DISCOVERY: <1-line description>` to `@coordinator` and either pause (if blocking) or continue within scope.
7. When `<gate_cmd>` is green and `git status` is clean, post `@coordinator: READY TO MERGE` with: branch name, commit list, gate output, new Shared Contracts added, and any `DISCOVERY:` items. Keep your worktree intact until `@coordinator` confirms merge.
```

---

## 4. Handling Checkpoints, Unforeseen Work, Cross-Family Review & Merges

### A. Stage 2 Goldfish Checkpoint
- Worker posts Goldfish findings → Coordinator distills only the **real design/gameplay decisions** for the user.
- Once the user decides, Coordinator records any cross-slice rulings in `EPIC.md`, replies to `@slice-<short-slug>` with the decisions, and lets the user approve opening that slice's Spec Gate (`done goldfish`).

### B. Unforeseen Work / Discovery Inbox
- Whenever a worker reports `DISCOVERY: ...`:
  1. Log it immediately in `EPIC.md` Section 4 (Discovery Inbox).
  2. Decide with the user whether to: (a) spin up a fast prerequisite mini-slice, (b) fold it into an upcoming queued slice's brief, or (c) defer it out of the Epic.
  3. Never let an active slice silently balloon past 3 commits / 600 LOC.

### C. Stage 5 Cross-Family Review & Landing a Completed Slice
1. **Spawn Cross-Family Critic (`workspace: "inherit"`, read-only) on the strict opposite vendor:**
   - If `slice-<short-slug>` ran on **Claude** (Pool 2 or Pool 4 `claude-sub`) → pin **`gemini-4-neon-high`** (Pool 1 preferred; fallback `gemini-4-argon-high` if Pool 1 < 25%).
   - If `slice-<short-slug>` ran on **Argon** (Pool 3) or **Gemini** (Pool 1) → pin **Pool 4 `claude-sub` (`opus`, `high`)** or **`claude-opus-5-5-high`** (Pool 2; fallback `claude-sonnet-5-5-high`).
   - Confirm both exact models via `swarm(action="status")` — never silently fall back to same-vendor review; if `swarm` is unavailable, stop and alert the user.
   - **Important git tip for the critic brief:** Because `slice-<short-slug>` still holds `slice/<slice-slug>` checked out in its `share` worktree, tell `critic-<short-slug>` to inspect `git diff epic/<epic-slug>...slice/<slice-slug>` and `git log --oneline epic/<epic-slug>..slice/<slice-slug>` directly (or read files via `git show slice/<slice-slug>:<path>`), never `git checkout slice/<slice-slug>` (which fails with `already used by worktree`).
   - If the critic finds `blocker` or `high` issues, send those findings back to `@slice-<short-slug>` (still awake/waiting in its worktree!) for 1 targeted fix pass, then re-verify with `@critic-<short-slug>`.
   - Once approved, record `Builder: <model> | Critic: <model>` in `.loop/<slice-slug>/branch-review.md` and `EPIC.md`'s Merge Log, then retire the critic: `swarm(action="kill", name="critic-<short-slug>")`.
2. **Merge & Gate on `epic/<epic-slug>` (Coordinator main repo):**
   - `git merge --no-ff slice/<slice-slug>` (or rebase cleanly if needed).
   - Run the full integration quiet gate (`tools/gate.sh`) on `epic/<epic-slug>` to verify cross-slice integration.
3. **Update `.loop/epics/<epic-slug>/EPIC.md`:**
   - Mark slice `Merged` on the Slice Board.
   - Add its new canonical interfaces to **Shared Contracts Registry** so downstream slices see them immediately.
   - Add a 1-line entry to **Merge & Verification Log**.
4. **Clean up:**
   - Run `runbook.py finish --cwd <worker-worktree>` (or have the worker run `runbook.py finish` before retirement).
   - Call `swarm(action="kill", name="slice-<short-slug>")` **only after** its branch is merged into `epic/<epic-slug>` (killing deletes the worker's `share` worktree).
5. **Re-check quotas & dispatch next wave:** Check `swarm(action="models", all=True)` if several slices have landed, update `plan.json`, and dispatch the next unblocked slice(s).
