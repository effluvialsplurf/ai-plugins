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


if __name__ == "__main__":
    unittest.main()
