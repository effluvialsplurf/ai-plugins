# Harness & Model-Family Portability Verification

This document verifies every plugin and component in `ai-plugins` for **harness agnosticism** and
**model-family portability**. It separates what works out of the box anywhere, what works anywhere
through embedded fallback instructions, and what depends on harness-native APIs and requires
conversion via [`docs/CONVERSION-PROMPTS.md`](./CONVERSION-PROMPTS.md).

---

## 1. Plugin Verification Summary

| Plugin | Verdict | Portable Today (Any Harness / Model) | Harness- or Model-Specific (Needs Conversion Elsewhere) |
|---|---|---|---|
| **`claude/deep-review`** | **Harness- & model-agnostic (via instruction)** | `references/{correctness,structure,testing,output-schema}.md`, `skills/deep-review/SKILL.md`, `skills/receiving-deep-review/SKILL.md` (with built-in fallbacks for non-Claude subagents and non-`superpowers` planning; note `receiving-deep-review` still names `/writing-plans` as its default route label) | `.claude-plugin/plugin.json` marketplace dependency (`superpowers@claude-plugins-official`) and `agents/axis-reviewer.md` (Claude Code agent frontmatter `tools:` list, though `model: inherit` keeps its prompt model-agnostic; skills-only installs omit `agents/`). |
| **`claude/build-loop`** | **Methodology agnostic; runtime partially coupled** | `templates/{LOOP-STATE,FINDINGS,task-review}.md`, `references/{setup,failure-classes,version-custom-harness}.md`, `scripts/watch-pr.sh`, `scripts/stall-watch.sh` *(requires Bash 4+ and GNU `find`/`stat`)*, `skills/context-costs/SKILL.md` (core formula & Rules 1–12), `skills/build-loop/SKILL.md` (with `version-custom-harness.md`) | `agents/{planner,builder,reviewer}.md` (hardcoded `claude-opus-5-5` / `claude-sonnet-5-5` + Claude Code frontmatter), `templates/{implementer-contract,fixer-brief,dispatch}.md` (wording assumes a Claude subagent / Kiro controller), `scripts/{loop_ledger.py,context_breakdown.py}` (parse `~/.claude/projects/` JSONL), `scripts/kiro-*.sh` (Kiro CLI), `scripts/codex-*.sh` (Codex CLI + `~/.codex/auth.json` file), `${CLAUDE_PLUGIN_ROOT}` variable, Claude 5m/1h prompt-cache specifics. |
| **`antigravity/lean-runbook`** (`lean-design` + `lean-runbook`) | **Core CLI & templates agnostic; orchestration & hooks Antigravity-native** | `skills/lean-design/scripts/design_check.py` (pure Python 3.9+ stdlib, except 1 informational `next_guidance()` string mentioning `swarm`), `skills/lean-design/templates/*.md`, `skills/lean-runbook/scripts/runbook.py` **CLI** (`start`, `status`, `done`, `skip`, `finish`, `--epic`, `--cwd`, `PLUGIN_DATA`/`LEAN_RUNBOOK_DATA`), `skills/lean-runbook/templates/{compact-spec,contract-plan,loop-state}.md` | `skills/lean-design/SKILL.md` & `skills/lean-runbook/SKILL.md` + `references/*.md` (Antigravity `swarm` / `workspace: "share"` / `swarm_pane` / `ask_question` / `/teamwork` prose and hardcoded `~/.gemini/config/plugins/lean-runbook/...` paths), `runbook.py` `next_guidance()` strings & `hook-*` subcommands, `templates/epic-ledger.md` (sample cells list `claude-sonnet-5-5-medium` / `gemini-4-argon-*`), `hooks.json` (`injectSteps`, `force_ask`, `toolCall.args`), `rules/AGENTS.md` (Antigravity 3-pool quotas & exact model IDs), `workflows/{build_loop,goldfish_gate}.py` (Antigravity `run_workflow` DSL). |
| **`claude/egm-runbook`** | **Cannot be drop-in agnostic (requires conversion)** | `scripts/runbook.py` **CLI** (`start`, `status`, `next`, `record`, `done`, `skip`, `switch`, `finish`) with `--data-dir <path>` (pure Python 3.9+ stdlib) | `hooks/hooks.json` + `runbook.py hook` (Claude Code `SessionStart`/`UserPromptSubmit`/`PreToolUse` JSON schema + `Write\|Edit\|MultiEdit\|NotebookEdit\|Skill\|Bash` matchers), Claude Code `!` user-shell override model, `scripts/statusline` (Claude Code `statusLine` JSON stdin), hardcoded `/egm:*` & `superpowers:*` workflow steps and blocked skill names. |
| **`claude/swarmctl`** | **Harness-agnostic (CLI + stdio MCP)** | `scripts/bin/swarmctl` CLI and the NDJSON stdio MCP server (`swarmctl mcp`; tools `swarm`, `post_message`, `read_board`, `swarm_wait`) work with any MCP-capable harness; pure Python stdlib, no third-party deps; `skills/swarmctl/SKILL.md` is portable. For non-Claude harnesses run `./install.sh --bin-dir ~/.local/bin --only swarmctl` and register `swarmctl mcp` as a stdio MCP server. | `.claude-plugin/plugin.json` `mcpServers` entry using `${CLAUDE_PLUGIN_ROOT}` (Claude Code only). Linux-only: the kill-time token check reads `/proc/<pid>/environ` (non-Linux skips/refuses signalling); `share` workspaces need `git` for worktrees. |

---

## 2. Why Some Layers Cannot Be Drop-In Agnostic

Five technical boundaries prevent 100% zero-edit portability across every coding harness:

1. **Lifecycle hook protocols & override gates differ per harness.**
   - Claude Code uses `SessionStart` / `UserPromptSubmit` / `PreToolUse` (`permissionDecision`, `additionalContext`) and relies on the user's `!` shell prefix bypassing `PreToolUse`.
   - Antigravity 2.0 uses `SessionStart` / `PreToolUse` (`injectSteps`, `decision: "allow" | "deny" | "force_ask"`, camelCase `toolCall.args`).
   - Harnesses without tool-call hooks (or with different schemas) must convert the Spec Gate into their native hook format or a portable `.git/hooks/pre-commit` check calling `runbook.py status`.
2. **Multi-agent dispatch & git worktree isolation have no universal tool API.**
   - Claude Code uses the `Agent` tool + `.claude-plugin` agent markdown files.
   - Antigravity 2.0 uses native `swarm(action="add", model=..., workspace="share")` and `run_workflow`.
   - Other harnesses use native subagents, headless CLI calls (`codex exec`, `gemini -p`, `kiro-cli`, `opencode run`), or sequential fresh chat sessions fed `.loop/<slug>/*.md` brief files.
3. **Model IDs and quota/rate-limit pools are provider-specific.**
   - Model strings (`claude-sonnet-5-5`, `gemini-4-argon-high`, `gpt-6.1-sol`, `deepseek-r1`, `qwen3-coder`, etc.) change per provider and release. All workflows in this repo operate on **abstract capability roles** (see Section 3) so any model family can fill every seat.
4. **Plugin manifests and install variables differ.**
   - Claude Code uses `.claude-plugin/plugin.json`, `${CLAUDE_PLUGIN_ROOT}`, and `${CLAUDE_PLUGIN_DATA}`.
   - Antigravity uses `plugin.json`, `${PLUGIN_DATA}`, and `~/.gemini/config/plugins/<name>/`.
   - Agent-Skills-compatible harnesses (Codex CLI, Gemini CLI, Cursor, OpenCode, `~/.agents/skills`) load `SKILL.md` folders directly without a marketplace manifest.
5. **Session telemetry & prompt-cache billing are harness-specific.**
   - `build-loop/scripts/{loop_ledger.py,context_breakdown.py}` parse Claude Code JSONL transcripts under `~/.claude/projects/`.
   - `build-loop/scripts/{codex-usage.sh,kiro-usage.sh}` parse Codex and Kiro session logs.

---

## 3. Universal Role-to-Model-Family Seat Matrix

Every workflow in this repository (`deep-review`, `build-loop`, `lean-design`, `lean-runbook`) reduces to
**five abstract roles**. Pick the row for your primary model family, and whenever possible assign the
**Adversarial Critic** seat to a **different model family** to avoid shared blind spots.

| Workflow Role | Anthropic Claude | Google Gemini | OpenAI / GPT / Codex | Open-Weights / Local / Multi-Provider *(OpenRouter, Ollama, vLLM, LiteLLM)* |
|---|---|---|---|---|
| **Coordinator / Controller** *(kept thin)* | Claude Sonnet (mid/high) or Opus | Gemini Pro / Neon / Argon | Flagship GPT coding/reasoning model | Strong tool-calling model (e.g., Qwen3-Coder, DeepSeek-V3/R1, Kimi, GLM, Llama 4) |
| **Scout / Clarity / Drift Auditor** *(fast, cheap, read-only)* | Claude Haiku / Sonnet (low) | Gemini Flash (low/medium) | GPT mini / nano / fast tier | Fast small/mid model (e.g., Qwen3 14B–32B, Mistral Small, GPT-OSS, DeepSeek-V3 fast) |
| **Planner / Drafter** *(architecture & contracts)* | Claude Opus or Sonnet (high) | Gemini Pro / Argon (medium/high) | Top GPT reasoning model (`effort=high`) | Strongest reasoning/architect model available (e.g., DeepSeek-R1, Qwen3-Thinking, Kimi-Thinking) |
| **Builder / Fixer** *(TDD code + tests)* | Claude Sonnet (medium/high) | Gemini Argon / Neon / Pro (medium) | Codex / GPT coding tier | Best local/API coding model (e.g., Qwen3-Coder, DeepSeek-V3, GLM-Code, Devstral) |
| **Adversarial Critic / Plan Check / Branch Review** *(fresh context, read-only)* | **Cross-vendor preferred:** Gemini Pro/Argon or GPT reasoning.<br>*Same-vendor fallback:* fresh Claude Opus (high) | **Cross-vendor preferred:** Claude Opus/Sonnet or GPT reasoning.<br>*Same-vendor fallback:* fresh Gemini Pro/Argon (high) | **Cross-vendor preferred:** Claude Opus/Sonnet or Gemini Pro/Argon.<br>*Same-vendor fallback:* fresh top GPT reasoning model | **Cross-vendor preferred:** different open-weights family (e.g., Qwen builds → DeepSeek reviews) or an API frontier critic.<br>*Single-model fallback:* fresh context + strict compensation below |

### Single-Vendor / Single-Model Compensation Rules

If you only have access to **one** model family (or one local model), every plugin still works reliably if you enforce four non-negotiable compensations:

1. **Always clear context before reviewing.** Never let the session that wrote a spec, plan, or diff review its own output — start a fresh subagent or fresh chat window with zero drafting history.
2. **Require concrete evidence.** Every review finding must cite a real file/function and a concrete failing input (never style nits).
3. **Shift weight to deterministic checks.** Add boundary-input test tables (empty, zero, negative, whitespace, overflow, invalid types), shared invariant assertions, and Tier-2 mutation checks (`deep-review` Testing Rubric) — tests do not share LLM blind spots.
4. **Track escapes.** Keep `.loop/ESCAPES.md` (from `build-loop`) or update `.loop/failure-classes.md` whenever a post-merge bug slips past review.

---

## 4. Harness Equivalence Map

| Harness | Skills Install Directory | Persistent Rules File | Subagent / Parallel Mechanism | Gate Enforcement Option |
|---|---|---|---|---|
| **Claude Code** | Marketplace (`/plugin install`) or `~/.claude/skills/` | `CLAUDE.md` / `CLAUDE.local.md` | Native `Agent` tool (`agents/*.md`) | Native `hooks/hooks.json` + `!` user override |
| **Antigravity 2.0** | `~/.gemini/config/plugins/<name>/` (or `~/.gemini/config/skills/`) | `rules/AGENTS.md` / `AGENTS.md` | Native `swarm` (`workspace: "share"`) + `run_workflow` | Native `hooks.json` (`force_ask` / `deny`) |
| **Codex CLI** | `~/.codex/skills/` (or `~/.agents/skills/`) | `AGENTS.md` | Subagents or `codex exec` headless runs | Instruction gate + optional `.git/hooks/pre-commit` |
| **Gemini CLI** | `~/.gemini/skills/` (or `~/.agents/skills/`) | `GEMINI.md` / `AGENTS.md` | Subagents or `gemini -p` headless runs | Gemini CLI hooks or `.git/hooks/pre-commit` |
| **OpenCode** | `~/.config/opencode/skills/` (or `~/.agents/skills/`) | `AGENTS.md` | Native subagents or `opencode run` | Plugin hooks or `.git/hooks/pre-commit` |
| **Cursor** | `.cursor/skills/` or `~/.cursor/skills/` | `.cursor/rules/*.mdc` / `AGENTS.md` | Subagents / fresh Composer tabs | Cursor hooks or `.git/hooks/pre-commit` |
| **Windsurf** | `.windsurf/skills/` or `~/.agents/skills/` | `.windsurfrules` / `AGENTS.md` | Fresh Cascade sessions | Instruction gate + `.git/hooks/pre-commit` |
| **Kiro** | `~/.kiro/skills/` or `.kiro/steering/` | `.kiro/steering/*.md` | `kiro-cli chat --no-interactive` | Kiro hooks or `.git/hooks/pre-commit` |
| **Cline / Roo Code / Aider / Other** | `~/.agents/skills/` (or repo `.agents/skills/`) | `.clinerules` / `AGENTS.md` / `CONVENTIONS.md` | Fresh sessions or CLI calls per brief file | `.git/hooks/pre-commit` calling `runbook.py` |
