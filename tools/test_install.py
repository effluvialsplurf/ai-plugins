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
        if os.environ.get("GATE_FAST") == "1":
            self.skipTest("installer sandbox tests are skipped by tools/gate.sh --fast")
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


class TestInstallStatic(unittest.TestCase):
    """Non-sandbox static guards that MUST also run under `tools/gate.sh --fast` (INV-6, EDGE-11)."""

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


class TestRepairAndGuards(Sandbox):
    """SLICE-4: legacy link repair (EDGE-3), warnings (EDGE-4), idempotency (CUJ-6)."""

    def link(self, path, target):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)

    def tearDown_home(self):
        for p in list(self.home.iterdir()) + [self.tmp / "skills"]:
            if p.is_symlink() or p.is_file():
                p.unlink()
            elif p.exists():
                shutil.rmtree(p)

    def test_dangling_legacy_antigravity_link_is_repaired_and_foreign_link_untouched(self):
        dest = self.home / ".gemini/config/plugins"
        self.link(dest / "lean-runbook", ROOT / "antigravity/lean-runbook")
        self.link(dest / "other", "/nonexistent/elsewhere")
        r = self.install("--antigravity")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(dest / "lean-runbook"), str(ROOT / "plugins/lean-runbook"))
        self.assertEqual(os.readlink(dest / "other"), "/nonexistent/elsewhere")
        self.assertFalse((self.home / ".cache/ai-plugins-backups").exists())
        self.assertIn("repaired", r.stdout)

    def test_legacy_link_is_repaired_even_when_only_filter_excludes_it(self):
        dest = self.home / ".gemini/config/plugins"
        self.link(dest / "lean-runbook", ROOT / "claude/lean-runbook")
        self.assertEqual(self.install("--antigravity", "--only", "swarmctl").returncode, 1)  # nothing matched, repair still ran
        self.assertEqual(os.readlink(dest / "lean-runbook"), str(ROOT / "plugins/lean-runbook"))

    def test_legacy_antigravity_link_to_plugin_without_root_manifest_is_warned_and_left(self):
        # BR-8/INV-5: plugins without a root plugin.json are not Antigravity plugins; repair must not retarget them.
        dest = self.home / ".gemini/config/plugins"
        self.link(dest / "deep-review", ROOT / "claude/deep-review")
        r = self.install("--antigravity")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(dest / "deep-review"), str(ROOT / "claude/deep-review"))
        self.assertIn("no root plugin.json", r.stderr)

    def test_foreign_and_near_miss_links_are_untouched(self):
        dest = self.home / ".gemini/config/plugins"
        foreign = {"a": f"{ROOT}-old/claude/deep-review", "b": "/x/ai-plugins/claude/deep-review"}
        for n, t in foreign.items():
            self.link(dest / n, t)
        r = self.install("--antigravity")
        self.assertEqual(r.returncode, 0, r.stderr)
        for n, t in foreign.items():
            self.assertEqual(os.readlink(dest / n), t)
        self.assertNotIn("repair", r.stdout + r.stderr)  # foreign links are skipped silently

    def test_foreign_symlink_at_installed_name_is_backed_up_not_deleted(self):
        for flags in ((), ("--copy",)):
            with self.subTest(flags=flags):
                self.tearDown_home()
                dest = self.home / ".gemini/config/plugins"
                self.link(dest / "lean-runbook", f"{ROOT}-old/lean-runbook")
                r = self.install("--antigravity", *flags)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("backed up existing", r.stdout)
                bak = (self.home / ".cache/ai-plugins-backups").iterdir()
                self.assertEqual([os.readlink(p) for p in bak], [f"{ROOT}-old/lean-runbook"])
                self.assertTrue((dest / "lean-runbook").exists())

    def test_dangling_legacy_bin_link_is_repaired_in_place(self):
        bindir = self.tmp / "bin"
        self.link(bindir / "swarmctl", ROOT / "claude/swarmctl/scripts/bin/swarmctl")
        r = self.install("--bin-dir", str(bindir), "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(bindir / "swarmctl"), str(ROOT / "plugins/swarmctl/scripts/bin/swarmctl"))
        self.assertFalse((self.home / ".cache/ai-plugins-backups").exists())

    def test_dangling_legacy_skills_link_is_repaired(self):
        dest = self.tmp / "skills"
        self.link(dest / "lean-runbook", ROOT / "antigravity/lean-runbook/skills/lean-runbook")
        self.assertEqual(self.install("--skills", str(dest), "--only", "lean-design").returncode, 0)
        self.assertEqual(os.readlink(dest / "lean-runbook"), str(ROOT / "plugins/lean-runbook/skills/lean-runbook"))

    def test_legacy_link_without_a_new_home_is_warned_about_and_left(self):
        dest = self.home / ".gemini/config/plugins"
        self.link(dest / "egm-runbook", ROOT / "claude/egm-runbook")
        r = self.install("--antigravity")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(dest / "egm-runbook"), str(ROOT / "claude/egm-runbook"))
        self.assertIn("cannot repair", r.stderr)

    def test_claude_install_updates_the_marketplace_between_add_and_install(self):
        self.assertEqual(self.install("--claude").returncode, 0)
        lines = (self.home / "claude.log").read_text().splitlines()
        self.assertEqual(lines[0], f"plugin marketplace add {ROOT}")
        self.assertEqual(lines[1], "plugin marketplace update ai-plugins")
        self.assertTrue(all(l.startswith("plugin install ") for l in lines[2:]), lines)

    def test_stale_statusline_and_zombie_plugin_warn_without_writing(self):
        cfg = self.home / ".claude"
        (cfg / "plugins").mkdir(parents=True)
        files = {cfg / "settings.json": '{"statusLine": {"type": "command", "command": "python3 %s/claude/egm-runbook/scripts/statusline"}}\n' % ROOT,
                 cfg / "plugins/installed_plugins.json": '{"plugins": {"egm-runbook@ai-plugins": [{}]}}\n'}
        for f, text in files.items():
            f.write_text(text)
        os.utime(cfg / "settings.json", ns=(10**9, 10**9))
        before = {f: (f.read_bytes(), f.stat().st_mode, f.stat().st_mtime_ns) for f in files}
        r = self.install("--claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("statusLine", r.stderr)
        self.assertIn("egm-runbook@ai-plugins", r.stderr)
        self.assertEqual({f: (f.read_bytes(), f.stat().st_mode, f.stat().st_mtime_ns) for f in files}, before)

    def test_zombie_enabled_only_in_settings_json_warns_and_config_dir_is_honored(self):
        alt = self.tmp / "alt-claude"
        alt.mkdir()
        text = '{"enabledPlugins": {"egm-runbook@ai-plugins": true}}\n'
        (alt / "settings.json").write_text(text)
        self.env["CLAUDE_CONFIG_DIR"] = str(alt)
        r = self.install("--claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("egm-runbook@ai-plugins is still installed", r.stderr)
        self.assertNotIn("statusLine", r.stderr)
        self.assertEqual((alt / "settings.json").read_text(), text)
        self.env["CLAUDE_CONFIG_DIR"] = str(self.home / ".claude")
        self.assertNotIn("warning", self.install("--claude").stderr)

    def test_failing_marketplace_update_only_warns_and_install_continues(self):
        (self.tmp / "stub/claude").write_text('#!/bin/sh\necho "$@" >> "$HOME/claude.log"\n[ "$2 $3" = "marketplace update" ] && exit 1\nexit 0\n')
        r = self.install("--claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("marketplace update failed", r.stderr)
        log = (self.home / "claude.log").read_text()
        for name in registry():
            self.assertIn(f"plugin install {name}@ai-plugins", log)

    def test_clean_claude_config_gives_no_warnings(self):
        r = self.install("--claude")
        self.assertNotIn("warning", r.stderr)

    def snapshot(self):
        snap = {}
        for dp, dns, fns in os.walk(self.tmp):  # followlinks=False: links are recorded, not entered
            for n in dns + fns:
                p = Path(dp, n)
                if p.name == "claude.log" or p.parts[len(self.tmp.parts)] in ("stub", "repo"):
                    continue
                st = p.lstat()
                body = p.read_bytes() if p.is_file() and not p.is_symlink() else None
                snap[str(p)] = (os.readlink(p) if p.is_symlink() else None, body, st.st_mtime_ns, st.st_mode)
        return snap

    def test_second_install_changes_nothing_on_the_filesystem(self):
        dest = str(self.tmp / "skills")
        for flags in ((), ("--copy",), ("--skills", dest), ("--skills", dest, "--copy")):
            with self.subTest(flags=flags):
                self.tearDown_home()
                self.assertEqual(self.install(*flags).returncode, 0)
                before = self.snapshot()
                self.assertTrue(before)
                r = self.install(*flags)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertFalse((self.home / ".cache/ai-plugins-backups").exists(), r.stdout)
                self.assertEqual(self.snapshot(), before)

    def test_copy_install_over_changed_copy_backs_it_up_and_recopies(self):
        self.assertEqual(self.install("--antigravity", "--copy").returncode, 0)
        d = self.home / ".gemini/config/plugins/lean-runbook"
        (d / "skills/lean-runbook/SKILL.md").write_text("{}")
        r = self.install("--antigravity", "--copy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.names(self.home / ".cache/ai-plugins-backups")), 1)
        self.assertEqual((d / "skills/lean-runbook/SKILL.md").read_bytes(), (registry()["lean-runbook"] / "skills/lean-runbook/SKILL.md").read_bytes())

    def test_symlinked_repo_path_is_idempotent_and_uninstalls_cleanly(self):
        repo_link = self.tmp / "repo-link"
        repo_link.symlink_to(ROOT)
        self.repo = repo_link
        self.assertEqual(self.install("--antigravity").returncode, 0)
        r2 = self.install("--antigravity")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertFalse((self.home / ".cache/ai-plugins-backups").exists(), r2.stdout)
        st = self.install("--antigravity", "--status")
        self.assertIn("[linked]", st.stdout)
        self.assertNotIn("points elsewhere", st.stdout)
        self.assertEqual(self.install("--uninstall").returncode, 0)
        self.assertEqual(self.names(self.home / ".gemini/config/plugins"), [])
        self.assertEqual(self.names(self.home / ".local/bin"), [])

    def test_failing_claude_plugin_install_exits_nonzero_and_skips_shims(self):
        (self.tmp / "stub/claude").write_text('#!/bin/sh\necho "$@" >> "$HOME/claude.log"\n[ "$2" = "install" ] && exit 1\nexit 0\n')
        r = self.install("--claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Claude Code: done.", r.stdout)
        self.assertEqual(self.names(self.home / ".local/bin"), [])

    def test_string_statusline_in_settings_json_warns_without_crashing(self):
        cfg = self.home / ".claude"
        cfg.mkdir(parents=True)
        (cfg / "settings.json").write_text('{"statusLine": "python3 /x/egm-runbook/scripts/statusline"}\n')
        r = self.install("--claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("statusLine", r.stderr)


if __name__ == "__main__":
    unittest.main()
