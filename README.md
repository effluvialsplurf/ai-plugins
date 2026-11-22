# ai-plugins

Personal AI workflow plugins for **Claude Code**, **Antigravity 2.0**, and **any Agent-Skills-compatible harness**
(Codex CLI, Gemini CLI, Cursor, Windsurf, OpenCode, Kiro, Cline/Roo Code, or local/open-weights model setups),
organized in a single repository for clean installation, live local iteration, or prompt-guided conversion to your
harness and model family.

## Repository Layout

```text
ai-plugins/
├── .claude-plugin/
│   └── marketplace.json      # Claude Code marketplace manifest (ai-plugins)
├── docs/
│   ├── PORTABILITY.md        # Plugin-by-plugin harness & model-family verification matrix
│   └── CONVERSION-PROMPTS.md # Copy-paste prompts to convert non-agnostic layers per model family/harness
├── install.sh                # Installer for Antigravity, Claude Code, and any Agent Skills directory
├── claude/
│   ├── egm-runbook/          # Per-feature EGM design + superpowers build runbook & Claude Code hooks
│   ├── build-loop/           # Multi-stage planned build loop (Claude/Kiro/Codex/Custom) + context-costs skill
│   └── deep-review/          # Three-axis code review (correctness, structure, testing) + receiving-deep-review
└── antigravity/
    └── lean-runbook/         # Token-efficient lean-design + 5-stage lean-runbook workflow for Antigravity 2.0
```

## Plugins & Portability Overview

| Plugin | Primary Harness | Portability Verdict | What Works Anywhere vs. Needs Conversion |
| --- | --- | --- | --- |
| [`deep-review`](./claude/deep-review) | Claude Code *(portable)* | **Agnostic via instruction** | All rubrics (`correctness`, `structure`, `testing`), output schema, and `SKILL.md` fallbacks work on **any** harness & model family (parallel subagents or sequential fresh passes; no `superpowers` required outside Claude Code). |
| [`build-loop`](./claude/build-loop) | Claude Code *(portable core)* | **Methodology agnostic; agents/scripts coupled** | `templates/{LOOP-STATE,FINDINGS,task-review}.md`, `setup.md`, `failure-classes.md`, `version-custom-harness.md`, `watch-pr.sh`, `stall-watch.sh` *(Bash 4+ & GNU `find`/`stat`)*, and `context-costs` Rules 1–12 work anywhere. `agents/*.md` (hardcoded Claude IDs), Claude/Kiro wording in `templates/{implementer-contract,fixer-brief,dispatch}.md`, `loop_ledger.py`/`context_breakdown.py` (Claude transcripts), and Kiro/Codex CLI wrappers require conversion for other harnesses. |
| [`lean-runbook`](./antigravity/lean-runbook) (`lean-design` + `lean-runbook`) | Antigravity 2.0 *(portable CLI & templates)* | **Core CLI & templates agnostic; hooks/swarm Antigravity-native** | `design_check.py`, `runbook.py` CLI (`start`/`status`/`done`/`skip`/`finish`), and Markdown templates (`design.md`, `tech-plan.md`, `spec.md`, `compact-spec.md`, `contract-plan.md`, `loop-state.md`) are pure Python 3.9+ stdlib / Markdown. `SKILL.md` `swarm`/path prose, `next_guidance()` strings, `epic-ledger.md` sample models, `hooks.json`, `workflows/*.py` (`run_workflow`), and `rules/AGENTS.md` 3-pool quotas are Antigravity-native and require conversion elsewhere. |
| [`egm-runbook`](./claude/egm-runbook) | Claude Code | **Claude Code native (requires conversion)** | `scripts/runbook.py` CLI is pure Python 3.9+ stdlib, but `hooks/hooks.json`, `!` shell-mode override, `scripts/statusline`, and `/egm:*`/`superpowers:*` step names are Claude-Code-specific. On Antigravity, use `lean-runbook` instead; on other harnesses, convert via [`docs/CONVERSION-PROMPTS.md`](./docs/CONVERSION-PROMPTS.md). |

For the full component-by-component audit, role-to-model-family seat matrix (Anthropic Claude, Google Gemini,
OpenAI/Codex, and Open-Weights/Local models), and single-vendor compensation rules, see
**[`docs/PORTABILITY.md`](./docs/PORTABILITY.md)**.

---

## Installation

Choose the section matching your harness. All scripts require **Python 3.9+** (standard library only; no `pip install`).

### 1. Claude Code

#### Option A: Install directly from GitHub (recommended)

In Claude Code:

```text
/plugin marketplace add google/elephant-goldfish-model
/plugin install egm@egm
/plugin install superpowers@claude-plugins-official

/plugin marketplace add effluvialsplurf/ai-plugins
/plugin install deep-review@ai-plugins
/plugin install build-loop@ai-plugins
/plugin install egm-runbook@ai-plugins
```

*(Install only the plugin(s) you want — e.g., `deep-review@ai-plugins` alone requires only `superpowers@claude-plugins-official`, and `egm@egm` is only needed for `egm-runbook`.)* Restart Claude Code after installing.

#### Option B: Install from a local clone (all or a subset)

```bash
git clone https://github.com/effluvialsplurf/ai-plugins.git ~/Projects/ai-plugins
cd ~/Projects/ai-plugins

./install.sh --claude                           # Register local marketplace + install all 3 Claude plugins + statusLine
./install.sh --claude --only deep-review        # Install a single plugin
./install.sh --claude --only deep-review,build-loop
```

To test a single plugin live without installing it into your marketplace:

```bash
claude --plugin-dir claude/deep-review
claude --plugin-dir claude/build-loop
claude --plugin-dir claude/egm-runbook
```

> **Want Antigravity's `lean-design` + `lean-runbook` natively in Claude Code?** Use **Prompt 3** in
> [`docs/CONVERSION-PROMPTS.md`](./docs/CONVERSION-PROMPTS.md#prompt-3-convert-antigravity-lean-runbook--lean-design-for-anthropic-claude--claude-code).

---

### 2. Antigravity 2.0

```bash
git clone https://github.com/effluvialsplurf/ai-plugins.git ~/Projects/ai-plugins
cd ~/Projects/ai-plugins

./install.sh --antigravity                      # Symlink antigravity/* into ~/.gemini/config/plugins/ (live edits)
./install.sh --antigravity --copy               # Standalone copy instead of symlinks
```

You can also install the portable Claude skills (`deep-review`, `receiving-deep-review`, `context-costs`, `build-loop`) into Antigravity's user skills folder if you want them alongside `lean-runbook`:

```bash
./install.sh --skills ~/.gemini/config/skills --only deep-review,context-costs
```

*(Note: avoid installing `lean-design` / `lean-runbook` into `~/.gemini/config/skills` if `lean-runbook` is already linked as a plugin in `~/.gemini/config/plugins`, so Antigravity doesn't load duplicate copies.)*

Or install both Antigravity and Claude Code at once with `./install.sh` (defaults to `--all --link`).

---

### 3. Any Other Harness (Codex CLI, Gemini CLI, Cursor, Windsurf, OpenCode, Kiro, Cline/Roo Code, Open-Weights)

Clone the repository once, then install the **portable Agent Skills** (`deep-review`, `receiving-deep-review`,
`build-loop`, `context-costs`, `lean-design`, `lean-runbook`) into your harness's skills directory with `./install.sh`:

```bash
git clone https://github.com/effluvialsplurf/ai-plugins.git ~/Projects/ai-plugins
cd ~/Projects/ai-plugins
```

#### Built-in Harness Presets

```bash
./install.sh --codex                            # Symlink portable skills -> ~/.codex/skills
./install.sh --gemini-cli                       # Symlink portable skills -> ~/.gemini/skills
./install.sh --opencode                         # Symlink portable skills -> ~/.config/opencode/skills
./install.sh --agents                           # Symlink portable skills -> ~/.agents/skills (cross-harness standard)
```

#### Custom Directory or Single-Plugin Subset (Cursor, Windsurf, Kiro, Repo-Local, etc.)

```bash
# Install ALL portable skills into any directory (add --copy instead of symlink if preferred)
./install.sh --skills ~/.cursor/skills
./install.sh --skills .cursor/skills --copy     # Project-local install
./install.sh --skills ~/.windsurf/skills
./install.sh --skills ~/.kiro/skills

# Install ONLY a single plugin or specific skills
./install.sh --codex --only deep-review                     # deep-review + receiving-deep-review
./install.sh --gemini-cli --only lean-design                # lean-design (3-doc suite + design_check.py)
./install.sh --agents --only deep-review,lean-design,context-costs
./install.sh --skills ~/.agents/skills --only egm-runbook   # explicitly include egm-runbook skill
```

#### Manual Install (No `install.sh` Needed)

Every skill is a standard directory containing `SKILL.md`. Copy or symlink any skill folder directly into your harness's skills directory:

- `claude/deep-review/skills/deep-review` & `claude/deep-review/skills/receiving-deep-review`
- `claude/build-loop/skills/build-loop` & `claude/build-loop/skills/context-costs` *(keep `claude/build-loop/{templates,scripts}` handy in your clone)*
- `antigravity/lean-runbook/skills/lean-design` *(self-contained with `scripts/design_check.py` and `templates/`)*
- `antigravity/lean-runbook/skills/lean-runbook` *(self-contained with `scripts/runbook.py` CLI and `templates/`)*

---

### 4. Converting Non-Agnostic Plugins to Your Model Family / Harness

If you want full native orchestration, hooks, model seat routing, or IDE rule files for **`lean-runbook`**, **`build-loop`**, or **`egm-runbook`** on a different harness or model family:

1. Check [`docs/PORTABILITY.md`](./docs/PORTABILITY.md) to see which components need conversion and pick your model seats.
2. Open [`docs/CONVERSION-PROMPTS.md`](./docs/CONVERSION-PROMPTS.md) and copy the ready-made prompt for your target family/harness:
   - **OpenAI / GPT / Codex CLI** (Prompt 1)
   - **Google Gemini / Gemini CLI (non-Antigravity)** (Prompt 2)
   - **Anthropic Claude / Claude Code** — porting `lean-design` + `lean-runbook` (Prompt 3)
   - **Open-Weights / Local / Multi-Provider** — DeepSeek, Qwen, Llama, Kimi, GLM, Mistral via Ollama/vLLM/OpenRouter/OpenCode/Cline/Aider (Prompt 4)
   - **IDE Harnesses** — Cursor, Windsurf, Kiro, OpenCode, Cline/Roo Code (Prompt 5)
   - **Universal Meta-Prompt** — any custom or future harness/model family (Prompt 6)
3. Paste the prompt into your agent inside your `ai-plugins` clone; it writes the converted package under `converted/<harness>/`, runs the unit tests, and prints exact install commands.

---

### Managing Installs (`install.sh` Options)

```bash
./install.sh --status                           # Check Antigravity + Claude Code status
./install.sh --codex --status                   # Check skills link status in ~/.codex/skills
./install.sh --uninstall                        # Remove Antigravity symlinks & print Claude Code uninstall commands
./install.sh --codex --uninstall                # Remove skill symlinks in ~/.codex/skills pointing to this repo
./install.sh --help                             # Full usage
```

---

## Iterating on Plugins

- **Antigravity / Symlinked Skills:** With `--link` (default), edits inside `ai-plugins` take effect immediately on the next agent turn (no copy step needed).
- **Claude Code:**
  - Test a single plugin live without reinstalling:
    ```bash
    claude --plugin-dir claude/egm-runbook
    ```
  - Validate the marketplace and plugin manifests:
    ```bash
    claude plugin validate .
    ```
  - Pull updated versions after editing:
    ```bash
    claude plugin marketplace update ai-plugins
    ```

### Running Tests

```bash
python3 -m unittest discover -s claude/egm-runbook/scripts/tests -v
python3 -m unittest discover -s antigravity/lean-runbook/skills/lean-runbook/scripts -v
python3 -m unittest discover -s antigravity/lean-runbook/skills/lean-design/scripts -v
```

### Adding a New Plugin

- **Claude Code:** Add the plugin folder under `claude/<name>/` (with `.claude-plugin/plugin.json`), register it in `.claude-plugin/marketplace.json`, and validate with `claude plugin validate .`.
- **Antigravity:** Add the plugin folder under `antigravity/<name>/` (with `plugin.json`) and re-run `./install.sh --antigravity`.
- **Portability:** Add an entry for the new plugin in `docs/PORTABILITY.md` and `SKILL_CATALOG` in `install.sh` so non-native harnesses can install its portable skills cleanly.
