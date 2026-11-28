"""EDGE-6 / EDGE-7 / INV-2 / INV-8 for tools/check_agnostic.py (SLICE-6)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/check_agnostic.py"
sys.path.insert(0, str(ROOT / "tools"))
import check_agnostic  # noqa: E402  (red until the script exists)


class Fixture(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_cli(self):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root)], capture_output=True, text=True)


class TestCheckAgnostic(Fixture):
    def test_real_tree_is_clean(self):
        self.assertEqual(check_agnostic.scan(ROOT), [])

    def test_skill_with_model_id_exits_1_naming_the_file(self):
        self.write("plugins/p/skills/s/SKILL.md", "use claude-sonnet-5-5 here\n")
        r = self.run_cli()
        self.assertEqual(r.returncode, 1)
        self.assertIn("plugins/p/skills/s/SKILL.md", r.stdout)

    def test_allowlisted_adapter_references_may_name_models_and_paths(self):
        for name in ("harness-x.md", "version-y.md"):
            self.write(f"plugins/p/skills/s/references/{name}", "claude-opus-5-5 ~/.gemini ${CLAUDE_PLUGIN_ROOT} gpt-6\n")
        self.write("plugins/p/skills/s/SKILL.md", "plain text\n")
        r = self.run_cli()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_install_paths_flagged_in_agents_templates_and_rules(self):
        self.write("plugins/p/agents/a.md", "---\nmodel: inherit\n---\n~/.gemini/config\n")
        self.write("plugins/p/templates/t.md", "${CLAUDE_PLUGIN_ROOT}/x\n")
        self.write("plugins/p/rules/AGENTS.md", "gemini-4-argon\n")
        self.assertEqual(len(check_agnostic.scan(self.root)), 3)

    def test_manifest_dependencies_and_cross_marketplace_allowlist_fail(self):
        self.write("plugins/p/.claude-plugin/plugin.json", json.dumps({"name": "p", "dependencies": ["x"]}))
        self.write(".claude-plugin/marketplace.json", json.dumps({"allowCrossMarketplaceDependenciesOn": ["m"], "plugins": []}))
        hits = check_agnostic.scan(self.root)
        self.assertEqual(len(hits), 2, hits)
        self.assertEqual(self.run_cli().returncode, 1)

    def test_agent_must_declare_model_inherit(self):
        self.write("plugins/p/agents/ok.md", "---\nname: ok\nmodel: inherit\n---\nbody\n")
        self.write("plugins/p/agents/pinned.md", "---\nname: x\nmodel: some-pin\n---\n")
        self.write("plugins/p/agents/none.md", "---\nname: y\n---\n")
        hits = check_agnostic.scan(self.root)
        self.assertEqual(sorted(h.split(":")[0] for h in hits), ["plugins/p/agents/none.md", "plugins/p/agents/pinned.md"])

    def test_each_survivor_now_fails_the_scan(self):
        survivors = ["claude-3-5-sonnet-20241022", "claude-3-opus", "claude-fable-1", "opus-5.5", "gpt-oss-120b", "o4-mini",
                     "gemini-pro", "$HOME/.gemini", "${HOME}/.gemini", "/home/u/.gemini/x", "$CLAUDE_PLUGIN_ROOT/a",
                     "${CLAUDE_PLUGIN_DATA}", "${CLAUDE_PLUGIN_ROOT:-x}", "PLUGIN_DATA", "Sonnet", "HAIKU", "fable"]
        for s in survivors:
            self.write("plugins/p/skills/s/SKILL.md", f"see {s} here\n")
            self.assertTrue(check_agnostic.scan(self.root), s)

    def test_claude_harness_and_codex_names_stay_legal(self):
        self.write("plugins/p/skills/s/SKILL.md", "Claude Code and the codex CLI; claude-code docs\n")
        self.assertEqual(check_agnostic.scan(self.root), [])

    def test_hooks_json_is_text_scanned_but_claude_hooks_dir_is_allowlisted(self):
        self.write("plugins/p/hooks.json", '{"command": "${CLAUDE_PLUGIN_ROOT}/x"}')
        self.write("plugins/q/hooks/hooks.json", '{"command": "${CLAUDE_PLUGIN_ROOT}/x"}')
        self.assertEqual([h.split(":")[0] for h in check_agnostic.scan(self.root)], ["plugins/p/hooks.json"])

    def test_forbidden_manifest_keys_are_found_at_any_depth(self):
        self.write(".claude-plugin/marketplace.json", json.dumps({"plugins": [{"name": "a", "dependencies": ["x"]}]}))
        self.write("plugins/p/.claude-plugin/plugin.json", json.dumps({"metadata": {"allowCrossMarketplaceDependenciesOn": []}}))
        self.assertEqual(len(check_agnostic.scan(self.root)), 2)

    def test_non_object_or_invalid_manifest_fails_closed(self):
        self.write(".claude-plugin/marketplace.json", "[1]")
        self.write("plugins/p/plugin.json", "{nope")
        hits = check_agnostic.scan(self.root)
        self.assertEqual(len(hits), 2, hits)
        self.assertEqual(self.run_cli().returncode, 1)

    def test_agent_frontmatter_edge_cases(self):
        ok = {"q": 'model: "inherit"  # follow controller', "s": "model: 'inherit'", "l": "model: pin\nmodel: inherit"}
        for n, m in ok.items():
            self.write(f"plugins/p/agents/{n}.md", f"---\nname: {n}\n{m}\n---\nbody\n")
        self.write("plugins/p/agents/late.md", "---\nname: x\n---\nmodel: inherit\n---\n")
        self.write("plugins/p/agents/last.md", "---\nmodel: inherit\nmodel: pin\n---\n")
        hits = check_agnostic.scan(self.root)
        self.assertEqual(sorted(h.split(":")[0] for h in hits), ["plugins/p/agents/last.md", "plugins/p/agents/late.md"])


if __name__ == "__main__":
    unittest.main()
