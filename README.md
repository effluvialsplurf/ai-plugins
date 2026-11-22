# ai-plugins

Personal AI workflow plugins for **Claude Code** and **Antigravity**, organized in a single repository so they can be installed cleanly on any machine or symlinked locally for fast iteration.

## Repository Layout

```text
ai-plugins/
├── .claude-plugin/
│   └── marketplace.json      # Claude Code marketplace manifest (ai-plugins)
├── install.sh                # Local symlink/copy installer for Antigravity + Claude Code
├── claude/
│   ├── egm-runbook/          # Per-feature EGM design + superpowers build runbook & hooks
│   ├── build-loop/           # Multi-stage planned build loop + context-costs skill
│   └── deep-review/          # Three-axis code review (correctness, structure, testing)
└── antigravity/
    └── lean-runbook/         # Token-efficient 5-stage EGM + run_workflow loop for Antigravity 2.0
```

## Plugins

### Claude Code (`claude/`)

| Plugin | Purpose | Dependencies |
| --- | --- | --- |
| [`egm-runbook`](./claude/egm-runbook) | Tracks per-feature state across EGM design and superpowers build steps; hooks block code/build skills until EGM review is concluded. Includes a Claude Code `statusline` script. | `egm@egm`, `superpowers@claude-plugins-official`, Python 3.9+ |
| [`build-loop`](./claude/build-loop) | Runs a planned feature end-to-end with planner, builder, and reviewer agents (Claude-only, Claude + Kiro, or Claude + Codex) plus the `context-costs` skill. | `superpowers@claude-plugins-official`, `deep-review@ai-plugins` |
| [`deep-review`](./claude/deep-review) | Three-axis branch/PR code review (correctness, structure, testing) and `receiving-deep-review` skill for acting on findings. | `superpowers@claude-plugins-official` |

### Antigravity (`antigravity/`)

| Plugin | Purpose | Dependencies |
| --- | --- | --- |
| [`lean-runbook`](./antigravity/lean-runbook) | Token-budgeted 5-stage EGM + Build-Loop workflow native to Antigravity 2.0: compact specs (≤300 lines), 2-pass parallel Goldfish gate (`run_workflow`), contract plans, TDD build loop, and adversarial whole-branch review with hook-enforced gates. | Python 3.9+ |

## Installation

### Option 1: Install Claude Code plugins directly from GitHub

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

Restart Claude Code after installing.

### Option 2: Clone locally for easy installation & live iteration

```bash
git clone git@github.com:effluvialsplurf/ai-plugins.git ~/Projects/ai-plugins
cd ~/Projects/ai-plugins
./install.sh
```

`./install.sh` supports:

- `./install.sh` — symlinks `antigravity/*` into `~/.gemini/config/plugins/` and registers/installs `claude/*` from this local checkout
- `./install.sh --antigravity` — symlink Antigravity plugins only (add `--copy` for a standalone copy)
- `./install.sh --claude` — register this repo as a local Claude Code marketplace, install the plugins, and point `statusLine` to `claude/egm-runbook/scripts/statusline`
- `./install.sh --status` — inspect current link/install state
- `./install.sh --uninstall` — remove Antigravity symlinks pointing to this repo

## Iterating on Plugins

- **Antigravity:** With `./install.sh --link`, edits under `antigravity/<plugin>/` take effect immediately on the next agent turn (no copy step needed).
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
```

### Adding a New Plugin

- **Claude Code:** Add the plugin folder under `claude/<name>/` (with `.claude-plugin/plugin.json`), register it in `.claude-plugin/marketplace.json`, and validate with `claude plugin validate .`.
- **Antigravity:** Add the plugin folder under `antigravity/<name>/` (with `plugin.json`) and re-run `./install.sh --antigravity`.
