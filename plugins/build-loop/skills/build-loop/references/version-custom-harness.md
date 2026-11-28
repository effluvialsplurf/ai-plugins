# Version: Custom Harness / Any Model Family

Use this seat template when running `build-loop` on **any harness or model family** outside the three
Claude-Code-centric setups (`Claude only`, `Claude + Kiro`, `Claude + Codex`) — for example:

- **OpenAI / Codex CLI** (GPT reasoning + coding models)
- **Google Gemini / Gemini CLI / Antigravity** (Gemini Flash / Pro / Neon / Argon, or Antigravity multi-pool `swarm`)
- **Open-Weights / Local / Multi-Provider** (DeepSeek, Qwen, Llama, Mistral, Kimi, GLM via OpenRouter, Ollama, vLLM, LiteLLM, OpenCode, Cline/Roo Code, Aider)
- **IDE Harnesses** (Cursor, Windsurf, Kiro standalone, VS Code Copilot/Agent mode)

## 1. Fill In `.loop/SEATS.md` By Role Capability (Not Vendor Name)

The build loop only cares about **four abstract model tiers** and **one rule**: *the reviewer seat must not be the same
conversation—and ideally not the same model family—as the author seat.*

| Role | Target Capability | Recommended Assignment | Fallback |
|---|---|---|---|
| **Controller** | Reliable tool use, long session discipline (kept thin) | Your main harness session (mid/flagship tier) | Any model with reliable file + shell tools |
| **Explorer / Design trace** | Fast, cheap large-context reader (read-only) | Fast/cheap tier (e.g., Gemini Flash, GPT-mini/nano, Claude Haiku/Sonnet, Qwen/DeepSeek fast) | Main tier |
| **Planner & Plan fixes** | Strongest architecture & spec-writing model | Flagship reasoning tier (Family A) | Strongest available coding model |
| **Plan check** *(highest-yield cross-vendor seat!)* | Adversarial verification against live code (read-only) | **Different vendor flagship (Family B)** — fresh context | Different model in Family A (fresh context + strict compensation below) |
| **Builder & Fix rounds** | High-throughput, accurate code + test editing | Fast/mid coding tier (Family A) | Flagship tier |
| **Task review & Re-review** | Adversarial code review (read-only) | **Family B** (or higher-tier Family A if single-vendor) | Fresh context on flagship tier |
| **Whole-branch review** | Deep diff audit (`deep-review` correctness rubric) | **Family B flagship** (fresh context) | Fresh context on flagship tier |
| **Live check** | Runtime/integration smoke test against real environment | Mid/flagship tier | Main session |

## 2. Harness Feature Substitutions

| `build-loop` Concept | Claude Code Default | Harness-Agnostic Substitution |
|---|---|---|
| Subagent dispatch | `Agent` tool (`build-loop:planner`, `builder`, `reviewer`) | Your harness's native subagent/worker tool (e.g., Antigravity `swarm`, Codex CLI subagent, OpenCode/Cursor subagent), a CLI call (`codex exec`, `gemini -p`, `kiro-cli`, `opencode run`), or a **fresh chat session** given the brief file in `.loop/<slug>/`. |
| `${CLAUDE_PLUGIN_ROOT}` | Installed Claude plugin directory | Local path to your cloned `ai-plugins/plugins/build-loop` directory. |
| Project instructions (`CLAUDE.md`) | `CLAUDE.md` / `CLAUDE.local.md` | Your harness's persistent instruction file (`AGENTS.md`, `GEMINI.md`, `.cursor/rules`, `.windsurfrules`, `.kiro/steering/`). Add the rule: *"After compaction or restart, read `.loop/<slug>/LOOP-STATE.md` first."* |
| Plan & build sub-skills | `superpowers:writing-plans`, `superpowers:subagent-driven-development` | Follow the stage table in `SKILL.md` directly using `templates/` (`implementer-contract.md`, `dispatch.md`, `task-review.md`, `fixer-brief.md`) — no `superpowers` plugin required. |
| Background stall watch | `scripts/stall-watch.sh`, `scripts/watch-pr.sh` | Works anywhere with **Bash 4+** (not macOS default Bash 3.2), GNU `find`/`stat`, and `gh` CLI. |
| Usage / cost ledger | `scripts/loop_ledger.py` (reads `~/.claude/projects/`) | Claude-Code-only. Track per-stage usage with your provider's CLI/dashboard or wrap CLI invocations to log elapsed time and token counts in `.loop/<slug>/LOOP-STATE.md`. |

## 3. Single-Vendor Compensation (When You Only Have One Model Family)

If all seats run on the same vendor (e.g., OpenAI-only, Gemini-only, or one local open-weights model), apply the same
non-negotiable compensations as `version-claude-only.md`:

1. **Always use a fresh, zero-history context** for Plan Check, Task Review, and Whole-Branch Review.
2. **Shift weight to deterministic checks** that do not share LLM blind spots:
   - Boundary/hard-input test tables (empty, zero, negative, whitespace, overflow, invalid types) on every write path.
   - Shared invariant assertions (e.g., rejected writes leave state byte-for-byte unchanged).
   - Manual or automated mutation checks on every new guard (break the guard → tests must fail).
   - No stand-in mocks re-implementing production logic under test.
3. **Keep `.loop/ESCAPES.md`** (see `references/setup.md`) from your first PR to catch recurring model-family blind spots and promote them into `.loop/failure-classes.md` or automated tests.

## 4. Full Conversion to Your Harness

To rewrite `agents/*.md`, scripts, and skill instructions natively for your harness and model family, use the
copy-paste conversion prompts in `docs/CONVERSION-PROMPTS.md` at the root of the `ai-plugins` repository.
