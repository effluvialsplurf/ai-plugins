# Harness Adapter: Claude Code

Maps the five roles and the dispatch ladder in `../SKILL.md` onto Claude Code. Adapter text only; core skills stay model-neutral.

| Role | Claude Code seat | Model |
|---|---|---|
| `orchestrator` | main chat | session model; keep thin |
| `explorer` | `Explore` subagent (read-only) | `haiku` |
| `planner` | fresh read-only subagent | `opus` |
| `builder` | `general-purpose` subagent or `build-loop:builder` | `sonnet` |
| `reviewer` | fresh read-only subagent (`build-loop:reviewer`, `deep-review:axis-reviewer`) | `opus`, or a non-Claude family via `swarmctl` |

- **Ladder:** Claude Code has no native swarm tool, so tier 1 is skipped. Use `swarmctl` (tier 2) when `command -v swarmctl` succeeds, else the `Agent` tool (tier 3), else fresh sessions (tier 4).
- **Hooks:** the plugin's `hooks/hooks.json` runs `lean-runbook hook ... --harness claude`; no setup beyond installing the plugin.
- **Shim fallback:** a marketplace-only install has no `PATH` shims; use the `runbook.py` and `design_check.py` paths from the SessionStart context.
- **Cross-family review:** a Claude `builder` needs a non-Claude `reviewer` seated through `swarmctl`; otherwise note the same-family review in `branch-review.md`.
