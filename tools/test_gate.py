"""Self-tests for tools/gate.sh (EDGE-10): the gate must fail closed."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent / "gate.sh"
SUITES = (
    "plugins/swarmctl/scripts/tests",
    "plugins/lean-runbook/skills/lean-runbook/scripts",
    "plugins/lean-runbook/skills/lean-design/scripts",
    "tools",
)
PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
FAILING = "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.fail('boom-marker')\n"


class GateFixture(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        for s in SUITES:
            (self.root / s).mkdir(parents=True)
            (self.root / s / "test_x.py").write_text(PASSING)
        shutil.copy(GATE, self.root / "tools/gate.sh")  # unpatched; gate() patches the floor per run
        (self.root / "plugins/demo/.claude-plugin").mkdir(parents=True)
        (self.root / "plugins/demo/.claude-plugin/plugin.json").write_text('{"name": "demo"}')
        (self.root / ".claude-plugin").mkdir()
        self.write_marketplace('{"plugins": [{"name": "demo", "source": "./plugins/demo"}]}')

    def write_marketplace(self, text):
        (self.root / ".claude-plugin/marketplace.json").write_text(text)

    def patch_floor(self, floor):
        text = GATE.read_text()
        self.assertEqual(text.count("MIN_TESTS=86\n"), 1)
        (self.root / "tools/gate.sh").write_text(text.replace("MIN_TESTS=86\n", f"MIN_TESTS={floor}\n"))

    def gate(self, *args, min_tests="4", env=None):
        if min_tests is not None:
            self.patch_floor(min_tests)
        return subprocess.run(["bash", str(self.root / "tools/gate.sh"), *args], env={**os.environ, **(env or {})},
                              capture_output=True, text=True, timeout=120)


class TestGate(GateFixture):
    def test_passes_with_one_pass_line(self):
        r = self.gate("--fast")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "gate: PASS (4 tests)"), r.stderr)

    def test_fails_when_suite_directory_is_missing(self):
        shutil.rmtree(self.root / SUITES[0])
        r = self.gate("--fast")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gate: FAIL", r.stdout)
        self.assertIn(SUITES[0], r.stdout)

    def test_fails_with_tail_when_suite_fails(self):
        (self.root / SUITES[1] / "test_x.py").write_text(FAILING)
        r = self.gate("--fast")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("boom-marker", r.stdout)
        self.assertNotIn("gate: PASS", r.stdout)

    def test_fails_when_too_few_tests_collected(self):
        r = self.gate("--fast", min_tests="5")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("4 tests < 5", r.stdout)

    def test_fails_on_invalid_manifest_json(self):
        (self.root / "plugins/demo/.claude-plugin/plugin.json").write_text("{nope")
        r = self.gate("--fast")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("plugin.json", r.stdout)

    def test_fails_on_legacy_layout_dir(self):
        (self.root / "claude").mkdir()
        (self.root / "claude/x.txt").write_text("x")
        r = self.gate("--fast")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("claude", r.stdout)

    def test_fails_when_marketplace_source_has_no_manifest(self):
        self.write_marketplace('{"plugins": [{"name": "ghost", "source": "./plugins/ghost"}]}')
        r = self.gate("--fast")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ghost", r.stdout)

    def test_environment_cannot_lower_the_86_floor(self):
        r = self.gate("--fast", min_tests=None, env={"GATE_MIN_TESTS": "0"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("4 tests < 86", r.stdout)

    def test_rejects_unknown_option(self):
        r = self.gate("--bogus")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
