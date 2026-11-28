# Harness Adapter: Generic (Codex CLI, Gemini CLI, OpenCode, Cursor, open-weights)

Use when no dedicated adapter exists. The CLIs and templates are plain Python 3.9+ and Markdown.

| Role | Seat | Model |
|---|---|---|
| `orchestrator` | main session | whatever you chat with; keep thin |
| `explorer` | read-only subagent or fresh session | cheapest capable |
| `planner` | fresh session | strongest available |
| `builder` | fresh session on the feature branch | mid-tier |
| `reviewer` | fresh session | strongest, a different family from the `builder` when you have one |

- **Ladder:** use `swarmctl` (tier 2) when `command -v swarmctl` succeeds; otherwise native subagents (tier 3) or one fresh session per role (tier 4), handing off only through `docs/specs/`, `.loop/`, and git.
- **Gate:** without hooks, call `lean-runbook pre-commit` from a git `pre-commit` hook so the Spec Gate still blocks code commits.
- **Shims:** run `install.sh --bin-dir <dir>` once to put `lean-runbook` and `lean-design` on `PATH`.
