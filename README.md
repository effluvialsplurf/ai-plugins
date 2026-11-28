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
├── install.sh                # Registry-driven installer (reads marketplace.json) for Antigravity, Claude Code, Agent Skills dirs, PATH shims
├── tools/
│   ├── gate.sh               # Quiet verification gate: tests, manifests, hooks, agnostic grep
│   └── check_agnostic.py     # INV-2 / INV-8 grep gate (no model IDs or install paths outside adapter files)
└── plugins/
    ├── lean-runbook/         # lean-design + lean-runbook; Claude Code and Antigravity 2.0 hooks, PATH shims
    ├── swarmctl/             # Local worker swarm: CLI + stdio MCP (Claude plugin only; never an Antigravity plugin)
    ├── build-loop/           # Multi-stage planned build loop (Claude/Kiro/Codex/Custom) + context-costs skill
    └── deep-review/          # Three-axis code review (correctness, structure, testing) + receiving-deep-review
```

## Plugins & Portability Overview

| Plugin | Primary Harness | Portability Verdict | What Works Anywhere vs. Needs Conversion |
| --- | --- | --- | --- |
| [`deep-review`](./plugins/deep-review) | Claude Code *(portable)* | **Agnostic via instruction** | All rubrics, output schema, and `SKILL.md` fallbacks work on **any** harness (parallel subagents or sequential fresh passes). `superpowers` is optional; no manifest dependencies. |
| [`build-loop`](./plugins/build-loop) | Claude Code *(portable core)* | **Methodology agnostic; scripts coupled** | Templates, `setup.md`, `failure-classes.md`, `version-custom-harness.md`, `watch-pr.sh`, `stall-watch.sh` and `context-costs` work anywhere. Agents use `model: inherit`; `loop_ledger.py`/`context_breakdown.py` (Claude transcripts) and Kiro/Codex wrappers need conversion elsewhere. |
| [`lean-runbook`](./plugins/lean-runbook) (`lean-design` + `lean-runbook`) | Claude Code and Antigravity 2.0 | **Agnostic core; harness text in `references/harness-*.md`** | One hook adapter (`runbook.py hook`, auto-detects the payload) gates writes on both harnesses; `pre-commit` and the `lean-runbook` / `lean-design` PATH shims cover the rest. Core skills name 5 roles and a 4-tier dispatch ladder; provider detail lives in `references/harness-{claude,antigravity,generic}.md`. |
| [`swarmctl`](./plugins/swarmctl) | any MCP-capable harness | **Agnostic (CLI + stdio MCP)** | Claude plugin via `mcpServers`; elsewhere put the `swarmctl` shim on `PATH`. Never installed into Antigravity (it would shadow the built-in `swarm`). |

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
/plugin marketplace add effluvialsplurf/ai-plugins
/plugin install deep-review@ai-plugins
/plugin install build-loop@ai-plugins
/plugin install lean-runbook@ai-plugins
/plugin install swarmctl@ai-plugins
```

*(Install only the plugin(s) you want. No plugin declares dependencies; `superpowers@claude-plugins-official` is optional and the skills fall back to plain instructions without it.)* Restart Claude Code after installing.

#### Option B: Install from a local clone (all or a subset)

```bash
git clone https://github.com/effluvialsplurf/ai-plugins.git ~/Projects/ai-plugins
cd ~/Projects/ai-plugins

./install.sh --claude                           # Register local marketplace + install every Claude plugin
./install.sh --claude --only deep-review        # Install a single plugin
./install.sh --claude --only deep-review,build-loop
```

To test a single plugin live without installing it into your marketplace:

```bash
claude --plugin-dir plugins/deep-review
claude --plugin-dir plugins/build-loop
claude --plugin-dir plugins/lean-runbook
```

> `lean-design` + `lean-runbook` run natively in Claude Code from this repo (`/plugin install lean-runbook@ai-plugins`); `./install.sh --bin-dir` puts the CLI shims on `PATH`.

---

### 2. Antigravity 2.0

```bash
git clone https://github.com/effluvialsplurf/ai-plugins.git ~/Projects/ai-plugins
cd ~/Projects/ai-plugins

./install.sh --antigravity                      # Symlink plugins/* that have a root plugin.json into ~/.gemini/config/plugins/ (swarmctl is skipped)
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
`build-loop`, `context-costs`, `lean-design`, `lean-runbook`, `swarmctl`) into your harness's skills directory with `./install.sh`:

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
./install.sh --bin-dir ~/.local/bin                         # PATH shims: lean-runbook, lean-design, swarmctl
```

#### Manual Install (No `install.sh` Needed)

Every skill is a standard directory containing `SKILL.md`. Copy or symlink any skill folder directly into your harness's skills directory:

- `plugins/deep-review/skills/deep-review` & `plugins/deep-review/skills/receiving-deep-review`
- `plugins/build-loop/skills/build-loop` & `plugins/build-loop/skills/context-costs` *(keep `plugins/build-loop/{templates,scripts}` handy in your clone)*
- `plugins/lean-runbook/skills/lean-design` *(self-contained with `scripts/design_check.py` and `templates/`)*
- `plugins/lean-runbook/skills/lean-runbook` *(self-contained with `scripts/runbook.py` CLI and `templates/`)*
- `plugins/swarmctl/skills/swarmctl` *(pair with `./install.sh --bin-dir ~/.local/bin --only swarmctl` and register `swarmctl mcp` as a stdio MCP server)*

---

### 4. Converting Non-Agnostic Plugins to Your Model Family / Harness

If you want full native orchestration, hooks, model seat routing, or IDE rule files for **`lean-runbook`** or **`build-loop`** on a different harness or model family:

1. Check [`docs/PORTABILITY.md`](./docs/PORTABILITY.md) to see which components need conversion and pick your model seats.
2. Open [`docs/CONVERSION-PROMPTS.md`](./docs/CONVERSION-PROMPTS.md) and copy the ready-made prompt for your target family/harness:
   - **OpenAI / GPT / Codex CLI** (Prompt 1)
   - **Google Gemini / Gemini CLI (non-Antigravity)** (Prompt 2)
   - **Anthropic Claude / Claude Code** — `lean-design` + `lean-runbook` already run natively here (`/plugin install lean-runbook@ai-plugins`); Prompt 3 is only for porting other tooling
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
    claude --plugin-dir plugins/lean-runbook
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
tools/gate.sh            # full gate: layout/manifests, agnostic grep, every suite (>=86 tests), installer sandbox tests
tools/gate.sh --fast     # same, but skips the installer sandbox tests
```

One `gate: PASS (N tests)` line means success; otherwise the failing section's tail is printed and the exit code is non-zero.

### Adding a New Plugin

- Add the plugin folder under `plugins/<name>/` with `.claude-plugin/plugin.json` (Claude Code), plus a root `plugin.json` only if it should be an Antigravity plugin, and register it in `.claude-plugin/marketplace.json` with source `./plugins/<name>`. `install.sh` and the gate derive everything from there (no plugin lists to edit).
- Keep skills, agents, templates and rules free of model IDs, `~/.gemini` and `${CLAUDE_PLUGIN_ROOT}` outside `references/harness-*.md` / `references/version-*.md`; agents use `model: inherit`; manifests declare no `dependencies`. `tools/check_agnostic.py` enforces this.
- Add an entry for the plugin to `docs/PORTABILITY.md`, then run `claude plugin validate .` and `tools/gate.sh`.
