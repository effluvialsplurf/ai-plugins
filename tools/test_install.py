"""Installer sandbox tests (CUJ-3, EDGE-9, EDGE-11, INV-5, INV-6): install.sh always runs against a temp HOME."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL_HOME = Path(os.path.expanduser("~")).resolve()


def registry(root=ROOT):
    data = json.loads((root / ".claude-plugin/marketplace.json").read_text())
    return {p["name"]: root / p["source"] for p in data["plugins"]}


class Sandbox(unittest.TestCase):
    repo = ROOT

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="install-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.assertNotEqual(self.home, REAL_HOME)
        self.assertTrue(str(self.home).startswith(str(Path(tempfile.gettempdir()).resolve())), "HOME is not a temp dir")
        stub = self.tmp / "stub"
        stub.mkdir()
        (stub / "claude").write_text('#!/bin/sh\necho "$@" >> "$HOME/claude.log"\n')
        (stub / "claude").chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{stub}:{os.environ['PATH']}",
                    "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_DATA_HOME": str(self.home / ".local/share"),
                    "XDG_CACHE_HOME": str(self.home / ".cache"), "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}

    def install(self, *args):
        return subprocess.run(["bash", str(self.repo / "install.sh"), *args], env=self.env, cwd=self.tmp,
                              capture_output=True, text=True, timeout=60)

    def names(self, d):
        return sorted(p.name for p in Path(d).iterdir()) if Path(d).is_dir() else []


class TestInstallRegistry(Sandbox):
    def test_antigravity_links_only_plugins_with_a_root_manifest(self):
        r = self.install("--antigravity")
        self.assertEqual(r.returncode, 0, r.stderr)
        dest = self.home / ".gemini/config/plugins"
        self.assertEqual(self.names(dest), ["lean-runbook"])
        self.assertEqual((dest / "lean-runbook").resolve(), registry()["lean-runbook"].resolve())

    def test_antigravity_then_bin_dir_gives_three_executable_shims(self):
        self.assertEqual(self.install("--antigravity").returncode, 0)
        bindir = self.tmp / "bin"
        r = self.install("--bin-dir", str(bindir))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(bindir), ["lean-design", "lean-runbook", "swarmctl"])
        for p in bindir.iterdir():
            self.assertTrue(p.is_symlink() and os.access(p, os.X_OK), p)

    def test_default_bin_dir_is_filled_for_every_target(self):
        self.assertEqual(self.install("--antigravity").returncode, 0)
        self.assertEqual(self.names(self.home / ".local/bin"), ["lean-design", "lean-runbook", "swarmctl"])

    def test_shims_resolve_their_script_through_the_symlink(self):
        bindir = self.tmp / "bin"
        self.assertEqual(self.install("--bin-dir", str(bindir)).returncode, 0)
        for shim in ("lean-runbook", "lean-design"):
            run = lambda *a: subprocess.run([str(bindir / shim), *a], env=self.env, cwd=self.tmp, capture_output=True, text=True, timeout=30)
            r = run()
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith(f"{shim}:"), r.stdout[:80])  # each script's own banner
            r = run("bogus")
            self.assertEqual(r.returncode, 2, r.stdout)
            self.assertIn("Unknown subcommand", r.stderr)

    def test_skills_target_links_every_skill_of_every_registry_plugin(self):
        dest = self.tmp / "skills"
        self.assertEqual(self.install("--skills", str(dest)).returncode, 0)
        expected = sorted(p.parent.name for src in registry().values() for p in src.glob("skills/*/SKILL.md"))
        self.assertGreaterEqual(len(expected), 7)
        self.assertEqual(self.names(dest), expected)

    def test_claude_target_installs_every_registry_plugin(self):
        r = self.install("--claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = (self.home / "claude.log").read_text()
        for name in registry():
            self.assertIn(f"plugin install {name}@ai-plugins", log)

    def test_registry_is_read_from_marketplace_json(self):
        repo = self.tmp / "repo"
        for rel in ("install.sh", ".claude-plugin/marketplace.json"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, repo / rel)
        shutil.copytree(ROOT / "plugins/lean-runbook", repo / "plugins/zeta")
        data = json.loads((repo / ".claude-plugin/marketplace.json").read_text())
        data["plugins"] = [{"name": "zeta", "source": "./plugins/zeta"}]
        (repo / ".claude-plugin/marketplace.json").write_text(json.dumps(data))
        self.repo = repo
        self.assertEqual(self.install("--antigravity").returncode, 0)
        self.assertEqual(self.names(self.home / ".gemini/config/plugins"), ["zeta"])
        self.assertEqual(self.names(self.home / ".local/bin"), ["lean-design", "lean-runbook"])

    def test_unreadable_registry_fails_without_touching_home(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        shutil.copy(ROOT / "install.sh", repo / "install.sh")
        self.repo = repo
        r = self.install("--antigravity")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("marketplace.json", r.stderr)
        self.assertEqual(self.names(self.home), [])

    def test_install_sh_has_no_literal_plugin_or_skill_names(self):
        text = (ROOT / "install.sh").read_text()
        names = set(registry()) | {p.parent.name for s in registry().values() for p in s.glob("skills/*/SKILL.md")}
        for n in names:
            self.assertIsNone(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text), f"literal name {n} in install.sh")


class TestInstallFixes(Sandbox):
    def fixture(self, plugins):
        repo = self.tmp / "repo"
        (repo / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "install.sh", repo / "install.sh")
        (repo / ".claude-plugin/marketplace.json").write_text(json.dumps({"plugins": plugins}))
        self.repo = repo

    def test_shim_and_skill_with_same_name_get_distinct_backups(self):
        (self.home / ".local/bin").mkdir(parents=True)
        (self.home / ".local/bin/lean-runbook").write_text("old shim")
        old = self.home / ".codex/skills/lean-runbook"
        old.mkdir(parents=True)
        (old / "keep.txt").write_text("old skill")
        r = self.install("--codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(old.resolve(), (registry()["lean-runbook"] / "skills/lean-runbook").resolve())
        self.assertFalse((registry()["lean-runbook"] / "skills/lean-runbook/lean-runbook").exists())
        backups = self.home / ".cache/ai-plugins-backups"
        self.assertEqual(len(self.names(backups)), 2)
        found = sorted(p.read_text() for p in backups.rglob("*") if p.is_file())
        self.assertEqual(found, ["old shim", "old skill"])

    def test_failed_backup_exits_nonzero_and_leaves_existing_dir(self):
        backups = self.home / ".cache/ai-plugins-backups"
        backups.mkdir(parents=True)
        old = self.home / ".codex/skills/lean-runbook"
        old.mkdir(parents=True)
        (old / "keep.txt").write_text("old skill")
        backups.chmod(0o500)
        self.addCleanup(backups.chmod, 0o700)
        r = self.install("--codex", "--only", "lean-runbook")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((old / "keep.txt").read_text(), "old skill")
        self.assertFalse(old.is_symlink())
        self.assertNotIn("linked " + str(old), r.stdout)

    def test_uninstalling_one_target_keeps_shared_shims(self):
        self.assertEqual(self.install("--antigravity").returncode, 0)
        for t in ("--antigravity", "--codex"):
            self.assertEqual(self.install("--uninstall", t).returncode, 0)
            self.assertEqual(self.names(self.home / ".local/bin"), ["lean-design", "lean-runbook", "swarmctl"])
        self.assertEqual(self.install("--uninstall").returncode, 0)
        self.assertEqual(self.names(self.home / ".local/bin"), [])

    def test_target_that_matches_nothing_writes_no_shims(self):
        r = self.install("--antigravity", "--only", "swarmctl")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no plugins matched", r.stderr)
        self.assertEqual(self.names(self.home / ".local/bin"), [])

    def test_invalid_registry_entries_fail_before_any_write(self):
        bad = [{"name": "../../../pwned", "source": "./plugins/../../../pwned"},
               {"name": "evil", "source": "./../outside/evil"},
               {"name": "a\nb", "source": "./plugins/a\nb"},
               {"name": "Up", "source": "./plugins/Up"},
               {"name": "dup", "source": "./plugins/dup"}]
        for entries in [[b] for b in bad[:4]] + [[bad[4], bad[4]]]:
            with self.subTest(entries=entries):
                self.fixture(entries)
                r = self.install("--antigravity")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("marketplace.json", r.stderr)
                self.assertEqual(self.names(self.home), [])
                self.assertFalse((self.home / "pwned").exists())

    def test_registry_reader_ignores_python_modules_in_cwd(self):
        (self.tmp / "json.py").write_text("open('planted-ran', 'w').close()\n")
        self.install("--status")
        self.assertFalse((self.tmp / "planted-ran").exists())


if __name__ == "__main__":
    unittest.main()
