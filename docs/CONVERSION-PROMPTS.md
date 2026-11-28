# Harness & Model-Family Conversion Prompts

Not every component in `ai-plugins` can be drop-in agnostic (for example: Antigravity's `swarm` +
`run_workflow` + `hooks.json`, Claude Code's `hooks.json` + `!` override + `agents/*.md`, or
provider-specific CLI wrappers and transcript parsers). See [`docs/PORTABILITY.md`](./PORTABILITY.md)
for the exact verification matrix.

When a plugin cannot be used as-is on your target harness or model family, **copy the matching
prompt below into your coding agent** inside a clone of `ai-plugins`. Each prompt instructs your
agent to convert the plugin cleanly, preserve all core safety invariants, and verify the result.

## Quick Start (3 Steps)

1. Clone this repository locally:
   ```bash
   git clone https://github.com/effluvialsplurf/ai-plugins.git ~/Projects/ai-plugins
   cd ~/Projects/ai-plugins
   ```
2. Check [`docs/PORTABILITY.md`](./PORTABILITY.md):
   - Core skills (`deep-review`, `receiving-deep-review`, `context-costs`, `lean-design`, `lean-runbook`, `swarmctl`) and CLI shims (`lean-runbook`, `lean-design`, `swarmctl`) are already harness-agnostic and install directly via `./install.sh --skills <your-skills-dir>` (and natively in both Claude Code and Antigravity 2.0 via `./install.sh`).
   - If you want custom native hooks, IDE rules, or model-seat adapters for another harness/model family, create a branch (e.g., `git checkout -b port/<your-harness>` — note `converted/` is untracked unless you add it to `.gitignore` or commit on your port branch) and run the appropriate prompt below.
3. Install the converted output into your harness's plugin or skills directory (see [README.md](../README.md#installation)).

## Shared Conversion Invariants (Apply to All Prompts Below)

Every conversion prompt below MUST preserve these invariants (include or cite this block when running any prompt):

- **Design & Slice Budgets:** Keep `lean-design`'s 3-doc zero-duplication suite, read-time budgets (`15–20 min` standard / `≤60 min` complex), and 100% `BR-*`/`RISK-*`/`INV-*`/`SLICE-*` traceability; keep `lean-runbook`'s `≤300`-line spec/plan guard, `≤3`-commit / `≤600`-LOC vertical-slice cap, fresh-context Goldfish gate, and 1-line quiet test gate.
- **Hidden Guidance & Template Coupling:** Rewrite Antigravity-specific `next_guidance()` strings in `runbook.py` and `design_check.py`, replace hardcoded `~/.gemini/config/plugins/lean-runbook/...` paths with relative or target-install paths, replace example model IDs in `templates/epic-ledger.md`, and adapt Claude/Kiro wording in `build-loop/templates/{implementer-contract,fixer-brief,dispatch}.md`.
- **Spec-Gate Fidelity & Known Gaps:** Native `PreToolUse` hooks enforce four properties: (1) blocking code **edits** (not just commits) using `CODE_EXTENSIONS` / `CODE_BASENAMES`, (2) preventing the agent from self-opening/bypassing the gate (`done goldfish`, `skip gate`, `start --force`) or tampering with the state directory, (3) enforcing the `>320`-line spec/plan budget guard, and (4) failing open on internal hook error. When a target harness lacks `PreToolUse` hooks and falls back to a git `pre-commit` hook, explicitly document the known gap (`git commit --no-verify` bypasses client-side hooks and edits aren't blocked pre-commit), keep the agent forbidden from self-opening the gate in persistent rules, and optionally add a CI check.

---

## Prompt 1: Convert for OpenAI / GPT / Codex CLI

Use this prompt in **Codex CLI** (or any OpenAI/GPT coding harness) to adapt `plugins/lean-runbook`
and/or `plugins/build-loop` for OpenAI GPT models and Codex CLI.

```text
You are converting workflow plugins in this `ai-plugins` repository for **Codex CLI** and the **OpenAI / GPT model family**.

Target plugins to convert (edit a new copy under `converted/codex/` so originals stay intact):
- `plugins/lean-runbook` (`lean-design` + `lean-runbook` skills, scripts, templates)
- `plugins/build-loop` (`build-loop` + `context-costs` skills, templates, scripts)

Follow these conversion rules strictly:
1. **Inspect first:** Read `docs/PORTABILITY.md`, the "Shared Conversion Invariants" in `docs/CONVERSION-PROMPTS.md`, and the target plugin's `SKILL.md`, `references/`, `scripts/`, `hooks.json`, and `templates/`.
2. **Replace harness-specific orchestration:**
   - Replace harness adapter references with Codex CLI native subagents, `swarmctl`, OR headless `codex exec` calls (`codex --search exec -m <model> -c model_reasoning_effort=<effort> ... < /dev/null`).
   - Keep `plugins/build-loop/scripts/codex-review.sh` and `codex-usage.sh` working; update default `CODEX_MODEL` / `CODEX_EFFORT` to match my current Codex CLI, and note that `codex-review.sh` requires a file-based auth token at `~/.codex/auth.json` (or `CODEX_AUTH_FILE`, not OS keyring-only auth).
   - Replace `${CLAUDE_PLUGIN_ROOT}` and `~/.gemini/config/plugins/lean-runbook/...` with `~/.codex/skills/<skill-name>/...` (or a configurable `AI_PLUGINS_DIR` env var), rewrite Antigravity-specific `next_guidance()` strings in `runbook.py` / `design_check.py`, and update sample model cells in `templates/epic-ledger.md` and Claude/Kiro wording in `build-loop/templates/{implementer-contract,fixer-brief,dispatch}.md`.
   - Replace references to `CLAUDE.md` with `AGENTS.md`, and remove hard requirements on Claude's `superpowers:*` or `/egm:*` skills (keep `lean-design` as the self-contained design workflow).
3. **Remap model seats to the OpenAI / GPT family:**
   - Replace Antigravity 3-pool model IDs and hardcoded `claude-opus-*` / `claude-sonnet-*` IDs with configurable GPT tiers (verify exact current model IDs in my Codex CLI before writing them):
     - Scout / Clarity / Drift: fast/mini GPT tier (`effort=low` or `medium`)
     - Planner / Drafter: flagship GPT reasoning model (`effort=high`)
     - Builder / Fixer: primary GPT coding model (`effort=medium` or `high`)
     - Adversarial Critic / Plan Check / Branch Review:
       - If a second vendor CLI (`claude` or `gemini`) is installed on PATH, wire it as the optional cross-vendor critic seat.
       - Otherwise, configure a fresh, zero-history `codex exec` review seat with minimal `CODEX_HOME` (no personal `AGENTS.md`) AND embed the Single-Vendor Compensation rules from `docs/PORTABILITY.md`.
   - Remove Antigravity's `rules/AGENTS.md` 3-pool quota rules and replace them with Codex rate-limit hygiene (`codex-usage.sh` checks + thin controller + fresh context per stage).
4. **Convert lifecycle hooks into a portable Spec Gate:**
   - Keep `lean-design/scripts/design_check.py` and `lean-runbook/scripts/runbook.py` CLI subcommands (`start`, `status`, `done`, `skip`, `finish`, `--epic`, `--cwd`) intact — they are pure Python 3.9+ stdlib.
   - Replace Antigravity/Claude `hooks.json` with a portable git `pre-commit` hook script (`scripts/install-git-gate.sh`) using `runbook.py`'s `CODE_EXTENSIONS`/`CODE_BASENAMES` to reject staged code commits when `Gate: CLOSED` (failing open on internal error), plus `AGENTS.md` rules forbidding code edits, self-opening the gate (`done goldfish`/`skip gate`/`start --force`), state-dir tampering, or exceeding the 300-line spec/plan budget. Explicitly document the `--no-verify` bypass gap (and optional CI gate).
5. **Preserve all Shared Conversion Invariants** (see top of `docs/CONVERSION-PROMPTS.md`).
6. **Verify before finishing:**
   - Run all unit tests (`design_check.py`, `runbook.py`) and a `--dry-run` of `codex-review.sh` if applicable.
   - Print exact install commands to copy/symlink `converted/codex/skills/*` into `~/.codex/skills/` and add the `AGENTS.md` snippet.
```

---

## Prompt 2: Convert for Google Gemini / Gemini CLI (Non-Antigravity)

Use this prompt in **Gemini CLI** (or any Gemini-powered harness outside Antigravity 2.0) to adapt
`plugins/lean-runbook` and/or `plugins/build-loop` so they run cleanly without Antigravity's
proprietary `swarm`, `run_workflow`, or 3-pool quota tools.

```text
You are converting workflow plugins in this `ai-plugins` repository for **Gemini CLI** and the **Google Gemini model family** (outside Antigravity 2.0).

Target plugins to convert (write the converted output under `converted/gemini-cli/` so originals stay intact):
- `plugins/lean-runbook` (`lean-design` + `lean-runbook`)
- `plugins/build-loop` (`build-loop` + `context-costs`)
- `plugins/deep-review` (verify fallback paths work smoothly in Gemini CLI)

Follow these conversion rules strictly:
1. **Inspect first:** Read `docs/PORTABILITY.md`, the "Shared Conversion Invariants" in `docs/CONVERSION-PROMPTS.md`, and the target `SKILL.md` files, `references/`, `scripts/`, `hooks.json`, `templates/`, and `workflows/`.
2. **Strip Antigravity-only primitives:**
   - Remove all references to Antigravity's `swarm(...)`, `workspace: "share"`, `swarm_pane`, `run_workflow` (`workflows/build_loop.py`, `workflows/goldfish_gate.py`), `ask_question`, `/teamwork`, and Antigravity's 3-pool quota routing (`rules/AGENTS.md`).
   - Replace parallel `workspace: "share"` workers with explicit `git worktree add` commands and Gemini CLI subagents (or headless `gemini -p "<brief>"` runs in separate worktrees).
   - Replace hardcoded `~/.gemini/config/plugins/lean-runbook/...` and `${CLAUDE_PLUGIN_ROOT}` paths with `~/.gemini/skills/<skill-name>/...`, rewrite Antigravity-specific `next_guidance()` strings in `runbook.py` / `design_check.py`, and update sample model cells in `templates/epic-ledger.md` and Claude/Kiro wording in `build-loop/templates/{implementer-contract,fixer-brief,dispatch}.md`.
   - Replace `CLAUDE.md` references with `GEMINI.md` (and `AGENTS.md`).
3. **Remap model seats to the Gemini model family:**
   - Verify the exact model IDs supported by my Gemini CLI / API plan before writing them, and assign:
     - Scout / Goldfish Clarity / Drift Auditor: Gemini Flash tier (fast, cheap, read-only)
     - Planner / Drafter / Goldfish Technical Critic: Gemini Pro / flagship reasoning tier
     - Builder / Fixer: Gemini Pro or fast coding tier
     - Adversarial Branch Critic / Plan Check:
       - If `claude` or `codex` CLI is available on PATH, configure it as an optional cross-vendor critic command (passing the diff and rubric file, read-only).
       - Otherwise, use a fresh zero-history Gemini Pro session AND enable the Single-Vendor Compensation checklist from `docs/PORTABILITY.md` (boundary-input tables, invariant helpers, Tier-2 mutation checks, `.loop/ESCAPES.md`).
4. **Convert hooks & Spec Gate for Gemini CLI (following Shared Conversion Invariants):**
   - Keep `design_check.py` and `runbook.py` CLI subcommands intact (already pure Python 3.9+ stdlib).
   - Convert `hooks.json` / `hooks/hooks.json` and `runbook.py hook` to Gemini CLI's hook event schema (if supported by my installed Gemini CLI version, preserving fail-open behavior, `CODE_EXTENSIONS`/`CODE_BASENAMES`, no self-opening of the gate, and the 300-line guard), OR wire the built-in `lean-runbook pre-commit` into `.git/hooks/pre-commit` + `GEMINI.md` gate rules (explicitly noting the `--no-verify` gap).
5. **Adapt `context-costs` for Gemini:**
   - Keep Rules 1-12 intact; replace Claude's 5m/1h prompt-cache notes and `~/.claude/projects/` script instructions with Gemini context-caching guidance and Gemini CLI session/token tracking.
6. **Verify before finishing:**
   - Run all Python unit tests for `design_check.py` and `runbook.py` (including any new hook tests).
   - Print exact install commands for `~/.gemini/skills/` and `GEMINI.md`.
```

---

## Prompt 3: Anthropic Claude / Claude Code (Already Native)

`plugins/lean-runbook` (`lean-design` + `lean-runbook`), `plugins/deep-review`, `plugins/build-loop`, and `plugins/swarmctl` already ship natively for Claude Code with `.claude-plugin/plugin.json`, `hooks/hooks.json`, and `model: inherit` agents — no conversion prompt is needed. Install directly via:

```text
/plugin marketplace add effluvialsplurf/ai-plugins
/plugin install lean-runbook@ai-plugins
/plugin install swarmctl@ai-plugins
```

Or from a local clone: `./install.sh --claude` (which also installs the `lean-runbook`, `lean-design`, and `swarmctl` CLI shims into `~/.local/bin`).

---

## Prompt 4: Convert for Open-Weights / Local / Multi-Provider Models (DeepSeek, Qwen, Llama, Kimi, GLM, Mistral)

Use this prompt when running **open-weights or local models** via **Ollama, vLLM, llama.cpp,
LM Studio, OpenRouter, Together, Fireworks, Groq, Bedrock, LiteLLM**, or harnesses like **OpenCode,
Cline, Roo Code, Aider, or Continue**.

```text
You are converting workflow plugins in this `ai-plugins` repository for **open-weights / local / multi-provider models**.

My environment:
- Harness: <e.g., OpenCode / Cline / Roo Code / Aider / custom CLI>
- Provider / Runtime: <e.g., OpenRouter / Ollama / vLLM / LiteLLM / Bedrock>
- Available models & context windows:
  - Fast / Scout model: <e.g., qwen3-32b / deepseek-v3 / llama-4-scout (32k–128k)>
  - Builder / Coder model: <e.g., qwen3-coder / deepseek-v3 / devstral>
  - Planner / Reasoning model: <e.g., deepseek-r1 / qwen3-thinking / kimi-k2-thinking>
  - Second-family Critic model (optional, "none" if single model): <e.g., different open-weights family or API model>

Target plugins to convert (write output under `converted/open-weights/` so originals stay intact):
- `plugins/lean-runbook` (`lean-design` + `lean-runbook`)
- `plugins/build-loop` (`build-loop` + `context-costs`)
- `plugins/deep-review` (verify it runs cleanly with my harness)

Follow these conversion rules strictly (preserving all "Shared Conversion Invariants" from the top of `docs/CONVERSION-PROMPTS.md`):
1. **Remove all proprietary vendor & harness lock-in:**
   - Replace every hardcoded Claude, Gemini, Antigravity `swarm`, `run_workflow`, Kiro, and Codex reference (including `next_guidance()` strings in `runbook.py`/`design_check.py`, sample model cells in `templates/epic-ledger.md`, and Claude/Kiro wording in `build-loop/templates/{implementer-contract,fixer-brief,dispatch}.md`) with my configured models above and a single editable `.loop/SEATS.md` file.
   - Replace `${CLAUDE_PLUGIN_ROOT}` and `~/.gemini/config/plugins/...` with my local repo/skills path (`<MY_SKILLS_DIR>`).
2. **Optimize for open-weights / smaller context windows & no guaranteed prompt caching:**
   - Keep `lean-design`'s 15-20 min word budgets and `lean-runbook`'s <=300-line spec/plan caps (tighten slice limits to `<=2 commits / <=350 LOC` if my builder's reliable context window is <=64k tokens).
   - Remove Anthropic 5m/1h cache TTL assumptions from `context-costs`; focus on the universal rules: fresh context per phase, file-backed handoffs (`.loop/<slug>/LOOP-STATE.md`), batched file reads, and 1-line quiet test gates.
   - Ensure every agent prompt uses explicit, structured output formats (markdown tables or strict YAML/JSON blocks) and never relies on harness-specific structured-output SDK hooks unless my harness supports them.
3. **Wire cross-family review OR strict single-model compensation:**
   - If I listed a Second-family Critic model above (e.g., Qwen builds -> DeepSeek reviews), pin Plan Check, Goldfish Architect, and Whole-Branch Review to that second family in a fresh context.
   - If I only have one model, enforce the Single-Vendor Compensation rules from `docs/PORTABILITY.md`: zero-history review context, mandatory concrete failing-input proof, boundary-input test tables, invariant assertions, Tier-2 mutation checks, and `.loop/ESCAPES.md`.
4. **Replace proprietary hooks with a portable git Spec Gate:**
   - Keep `design_check.py` and `runbook.py` CLI subcommands as-is (pure Python 3.9+ stdlib, zero external deps).
   - Generate a small `scripts/install-git-gate.sh` that installs a `.git/hooks/pre-commit` check using `CODE_EXTENSIONS`/`CODE_BASENAMES` to reject staged code commits when `Gate: CLOSED` (failing open on internal error), add persistent rules forbidding code edits / gate self-opening / state tampering / >300-line specs, and document the `--no-verify` bypass gap.
5. **Verify before finishing:**
   - Run the Python unit tests for `design_check.py` and `runbook.py`, and test the git pre-commit gate in a temp git repo.
   - Print exact install steps for my harness (`<MY_SKILLS_DIR>` and persistent rules file).
```

---

## Prompt 5: Convert for IDE Harnesses (Cursor, Windsurf, Kiro, OpenCode, Cline / Roo Code)

Use this prompt to install and adapt any plugin into an IDE-based AI coding harness.

```text
You are adapting workflow plugins from this `ai-plugins` repository for my IDE harness: **<Cursor | Windsurf | Kiro | OpenCode | Cline | Roo Code>**.

My primary model(s):
- Primary Builder/Chat model: <model>
- Strongest Planner/Critic model: <model>
- Optional Second-Vendor Critic model: <model or "none">

Plugins I want to use: <deep-review | lean-design | lean-runbook | build-loop | swarmctl>

Follow these conversion rules (preserving all "Shared Conversion Invariants" from the top of `docs/CONVERSION-PROMPTS.md`, including `lean-design`'s 15–20m/60m budgets, `lean-runbook`'s ≤300-line and ≤3-commit/≤600-LOC caps, and fresh-context Goldfish review):
1. **Inspect `docs/PORTABILITY.md`** and the selected plugin(s) in this repo.
2. **Convert skill & rule formats to my IDE's native layout** (output under `converted/<harness>/`):
   - Rewrite hardcoded `~/.gemini/config/plugins/...` and `${CLAUDE_PLUGIN_ROOT}` paths, `next_guidance()` strings in `runbook.py`/`design_check.py`, `templates/epic-ledger.md` model cells, and Claude/Kiro wording in `build-loop/templates/{implementer-contract,fixer-brief,dispatch}.md`.
   - **Cursor:** `.cursor/skills/<skill>/SKILL.md` + `.cursor/rules/*.mdc` (with concise `alwaysApply` rule to read `.loop/<slug>/LOOP-STATE.md` first).
   - **Windsurf:** `.windsurf/skills/<skill>/SKILL.md` + `.windsurfrules` summary.
   - **Kiro:** `~/.kiro/skills/<skill>/SKILL.md` + `.kiro/steering/` files (and keep `kiro-run.sh` / `kiro-usage.sh` if using Kiro CLI).
   - **OpenCode:** `~/.config/opencode/skills/<skill>/SKILL.md` + `AGENTS.md` + OpenCode subagent config.
   - **Cline / Roo Code:** `~/.agents/skills/<skill>/SKILL.md` (or `.clinerules/` / custom modes for Scout, Planner, Builder, Critic).
3. **Adapt subagent dispatch:**
   - Where my IDE supports native subagents or custom modes, wire each workflow stage (`scout`, `planner`/`drafter`, `builder`, `critic`, `axis-reviewer`) to them.
   - Where my IDE is single-thread per chat tab, replace subagent calls with explicit **Fresh-Tab Handoff Prompts** that reference the exact brief file (`.loop/<slug>/...`) and output report path so the user can open a fresh tab, switch models for cross-vendor review, and paste one line.
4. **Adapt Spec Gates & scripts:**
   - Keep `design_check.py` and `runbook.py` CLI subcommands pointing to their installed path.
   - If my IDE supports pre-tool hooks, translate `hooks.json` to its hook format (preserving `CODE_EXTENSIONS`/`CODE_BASENAMES`, no gate self-opening, >320-line budget warning, and fail-open behavior); otherwise generate a `.git/hooks/pre-commit` Spec Gate script + persistent rule forbidding code edits/self-opening while `Gate: CLOSED` and document the `--no-verify` bypass gap.
5. **Verify & document:**
   - Run all relevant Python unit tests.
   - Print exact copy/symlink commands to install `converted/<harness>/` into my machine or target project.
```

---

## Prompt 6: Universal "Bring Your Own Model Family & Harness" Meta-Prompt

If you use a **new, custom, internal, or future harness or model family** not listed above, fill in
the `{{PLACEHOLDERS}}` and paste this prompt into your agent.

```text
You are adapting plugins from the `ai-plugins` repository to a custom harness and model family.

## Target Environment
- **Target Harness:** {{TARGET_HARNESS}} (e.g., Amp, Goose, Factory Droid, Zed AI, internal CLI)
- **Target Model Family:** {{MODEL_FAMILY}} (e.g., Grok, Nova, Mistral, Command, Llama, internal model)
- **Model Seats:**
  - Fast / Scout / Clarity: {{FAST_MODEL}}
  - Planner / Drafter: {{PLANNER_MODEL}}
  - Builder / Fixer: {{BUILDER_MODEL}}
  - Adversarial Critic (different vendor preferred): {{CRITIC_MODEL}}
- **Plugins to Convert:** {{PLUGINS}} (e.g., deep-review, lean-design, lean-runbook, build-loop, swarmctl)
- **Target Skills / Rules Directory:** {{SKILLS_DIR}}
- **Persistent Instructions File:** {{RULES_FILE}} (e.g., AGENTS.md)
- **Subagent Mechanism:** {{SUBAGENT_MECHANISM}} (e.g., native subagent tool / CLI command `<cmd>` / sequential fresh sessions)
- **Hook Support:** {{HOOKS_SUPPORT}} (e.g., describe native hook JSON schema, or "none — use git pre-commit hook")

## Conversion Instructions
1. Read `docs/PORTABILITY.md`, the "Shared Conversion Invariants" in `docs/CONVERSION-PROMPTS.md`, and every file inside the selected plugin(s).
2. Write the converted package to `converted/{{TARGET_HARNESS}}/` without modifying the original plugin directories.
3. Replace all Antigravity-specific (`swarm`, `run_workflow`, `swarm_pane`, `force_ask`, `~/.gemini/config/plugins/...`, `next_guidance()` strings, `templates/epic-ledger.md` model cells) and Claude-Code-specific (`Agent`, `superpowers:*`, `/egm:*`, `${CLAUDE_PLUGIN_ROOT}`, `~/.claude/projects/`, `!` shell override, Claude/Kiro wording in `build-loop/templates/`) constructs with `{{TARGET_HARNESS}}` equivalents.
4. Replace all hardcoded model IDs with the 4 seats above (put them in one editable `.loop/SEATS.md` or config table so they can be swapped anytime without editing skill prose).
5. If `{{CRITIC_MODEL}}` is the same vendor as `{{BUILDER_MODEL}}` or `{{PLANNER_MODEL}}`, embed the Single-Vendor Compensation rules from `docs/PORTABILITY.md` (fresh zero-history context, concrete failing-input evidence, boundary-input test tables, invariant assertions, mutation checks, `.loop/ESCAPES.md`).
6. Preserve all Shared Conversion Invariants (design read-time budgets, ≤300-line spec/plan & ≤3-commit/≤600-LOC slice caps, fresh-context Goldfish review, pure Python 3.9+ stdlib `design_check.py` & `runbook.py` CLI). Convert hooks per `{{HOOKS_SUPPORT}}` (preserving `CODE_EXTENSIONS`/`CODE_BASENAMES`, no self-opening of the gate, >320-line budget warning, fail-open semantics, and documenting the `--no-verify` gap if falling back to git `pre-commit`).
7. Run the existing Python unit tests (`python3 -m unittest discover ...`) to confirm zero regressions, and output exact installation commands for `{{SKILLS_DIR}}` and `{{RULES_FILE}}`.
```
