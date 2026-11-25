"""Unified-layout checks (CUJ-1, E3, E4, EDGE-8) against the real repo tree."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = {"build-loop", "deep-review", "lean-runbook", "swarmctl"}


def tracked(*paths):
    out = subprocess.run(["git", "ls-files", *paths], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.split()


class TestLayout(unittest.TestCase):
    def test_no_tracked_legacy_trees(self):
        self.assertEqual(tracked("claude", "antigravity"), [])

    def test_plugins_dir_holds_exactly_four_plugins(self):
        self.assertEqual({p.name for p in (ROOT / "plugins").iterdir() if p.is_dir()}, PLUGINS)

    def test_marketplace_sources_match_plugins_and_drop_egm_runbook(self):
        data = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        sources = {p["name"]: p["source"] for p in data["plugins"]}
        self.assertEqual(sources, {n: f"./plugins/{n}" for n in PLUGINS})
        self.assertNotIn("egm-runbook", json.dumps(data))

    def test_every_marketplace_source_has_a_claude_manifest(self):
        for n in PLUGINS:
            self.assertTrue((ROOT / "plugins" / n / ".claude-plugin/plugin.json").is_file(), n)

    def test_lean_runbook_claude_manifest_is_metadata_only(self):
        data = json.loads((ROOT / "plugins/lean-runbook/.claude-plugin/plugin.json").read_text())
        self.assertEqual(data["name"], "lean-runbook")
        self.assertFalse({"hooks", "mcpServers", "dependencies"} & set(data))

    def test_swarmctl_has_no_antigravity_root_manifest(self):
        self.assertFalse((ROOT / "plugins/swarmctl/plugin.json").exists())

    def test_egm_runbook_is_gone(self):
        self.assertFalse((ROOT / "plugins/egm-runbook").exists())
        self.assertEqual(tracked("*egm-runbook*"), [])

    def test_packaging_test_resolves_repo_root_via_parents_4(self):
        src = (ROOT / "plugins/swarmctl/scripts/tests/test_mcp_packaging.py").read_text()
        self.assertIn("REPO_ROOT = Path(__file__).resolve().parents[4]", src)


if __name__ == "__main__":
    unittest.main()
