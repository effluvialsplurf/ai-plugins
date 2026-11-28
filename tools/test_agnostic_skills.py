"""CUJ-4 / INV-2 / INV-9 for the core lean-runbook skills (SLICE-5): static, harness-neutral text."""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LR = ROOT / "plugins/lean-runbook"
RUNBOOK = LR / "skills/lean-runbook/scripts/runbook.py"
FORBIDDEN = re.compile(
    r"~/\.gemini|CLAUDE_PLUGIN_ROOT|PLUGIN_DATA|gemini-\d|gemini-[a-z]+-|claude-(?:opus|sonnet|haiku|sub)|gpt-\w|"
    r"\b(?:Argon|Neon)\b|swarm\(|swarm_pane|/teamwork|invoke_subagent|run_workflow")
ROLES = ("planner", "builder", "reviewer", "explorer", "orchestrator")


def core_files():
    files = [*LR.glob("skills/*/SKILL.md"), *LR.glob("skills/*/templates/*.md"), *LR.glob("rules/*.md"),
             *(p for p in LR.glob("skills/*/references/*.md") if not p.name.startswith("harness-"))]
    assert len(files) >= 10, files
    return files


def runbook_module():
    spec = importlib.util.spec_from_file_location("runbook_under_test", RUNBOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class AgnosticSkillTests(unittest.TestCase):
    def test_core_text_has_no_provider_ids_or_install_paths(self):
        hits = [f"{f.relative_to(ROOT)}:{n}: {m.group(0)}" for f in core_files()
                for n, line in enumerate(f.read_text().splitlines(), 1) for m in FORBIDDEN.finditer(line)]
        self.assertEqual(hits, [])

    def test_next_guidance_is_harness_neutral_for_every_stage(self):
        mod = runbook_module()
        for i in range(len(mod.STAGES) + 1):
            text = mod.next_guidance({"slug": "s", "done": list(mod.STAGES[:i])})
            self.assertTrue(text)
            self.assertIsNone(FORBIDDEN.search(text), (i, text))

    def test_skill_names_five_roles_and_four_tier_ladder(self):
        text = (LR / "skills/lean-runbook/SKILL.md").read_text()
        for role in ROLES:
            self.assertRegex(text, rf"`{role}`")
        for tier in ("native swarm", "`swarmctl`", "native subagents", "fresh sessions"):
            self.assertIn(tier, text)
        self.assertLess(text.index("native swarm"), text.index("fresh sessions"))

    def test_only_runtime_probe_is_command_v_swarmctl(self):
        for f in LR.glob("skills/*/SKILL.md"):
            probes = re.findall(r"command -v ([\w-]+)", f.read_text())
            self.assertTrue(set(probes) <= {"swarmctl"}, (f, probes))
        self.assertIn("command -v swarmctl", (LR / "skills/lean-runbook/SKILL.md").read_text())

    def test_harness_references_exist_and_skill_links_resolve(self):
        for name in ("antigravity", "claude", "generic"):
            self.assertTrue((LR / f"skills/lean-runbook/references/harness-{name}.md").is_file(), name)
        for f in [*LR.glob("skills/*/SKILL.md"), *LR.glob("skills/*/references/*.md"), *LR.glob("rules/*.md")]:
            for target in re.findall(r"\]\((\./[^)#]+|\.\./[^)#]+)\)", f.read_text()):
                self.assertTrue((f.parent / target).exists(), f"{f.relative_to(ROOT)} -> {target}")
        self.assertIn("harness-antigravity.md", (LR / "rules/AGENTS.md").read_text())

    def test_referenced_commands_and_env_vars_exist(self):
        src = RUNBOOK.read_text() + (LR / "skills/lean-design/scripts/design_check.py").read_text()
        for f in LR.glob("skills/*/SKILL.md"):
            text = f.read_text()
            for var in set(re.findall(r"\b[A-Z][A-Z_]*_DATA\b", text)):
                self.assertIn(var, src, var)
            for cmd in set(re.findall(r"`(?:lean-runbook|lean-design) (start|status|done|skip|finish|init|check)\b", text)):
                self.assertIn(f'"{cmd}"', src, cmd)
        self.assertTrue((LR / "bin/lean-runbook").is_file() and (LR / "bin/lean-design").is_file())


if __name__ == "__main__":
    unittest.main()
