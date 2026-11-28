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
- **Hooks:** the plugin's `hooks/hooks.json` registers `python3 "${CLAUDE_PLUGIN_ROOT}/skills/lean-runbook/scripts/runbook.py" hook session-start|pre-tool-use --harness claude` (`SessionStart`; `PreToolUse` on `Write|Edit|MultiEdit|NotebookEdit|Bash`); no setup beyond installing the plugin.
- **Shim fallback:** a marketplace-only install has no `PATH` shims; run `scripts/runbook.py` and `scripts/design_check.py` relative to each skill's own directory (the skill's base directory shown when it loads, `<base directory>/scripts/`; `${CLAUDE_PLUGIN_ROOT}` exists only inside hooks, MCP config and skill/command/agent bodies, not in Bash tool calls). Once a feature is active, the SessionStart context also prints the absolute path (it prints `{}` before that).
- **Cross-family review:** a Claude `builder` needs a non-Claude `reviewer` seated through `swarmctl`; otherwise note the same-family review in `branch-review.md`.
