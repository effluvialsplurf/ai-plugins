#!/usr/bin/env python3
"""End-to-end tests for the dual-protocol hook adapter (BR-1, INV-3, INV-4, EDGE-2, EDGE-5)."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
RUNBOOK = HERE / "runbook.py"
DESIGN = HERE.parents[1] / "lean-design/scripts/design_check.py"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo, self.data, home = self.tmp / "repo", self.tmp / "data", self.tmp / "home"
        for d in (self.repo, self.data, home):
            d.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PLUGIN_DATA", "PLUGIN_DATA")}
        self.env.update(LEAN_RUNBOOK_DATA=str(self.data), HOME=str(home))
        self.rb("--cwd", str(self.repo), "start", "feat")

    def rb(self, *args, stdin=None, cwd=None):
        return subprocess.run([sys.executable, str(RUNBOOK), *args], input=stdin, env=self.env, text=True, capture_output=True, cwd=cwd)

    def hook(self, event, payload, *flags):
        r = self.rb("hook", event, *flags, stdin=payload if isinstance(payload, str) else json.dumps(payload))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)


class TestHooks(Base):
    def payloads(self, kind, arg, extra):
        cwd = str(self.repo)
        if kind == "cmd":
            return {"claude": {"tool_name": "Bash", "tool_input": {"command": arg}, "cwd": cwd},
                    "antigravity": {"toolCall": {"name": "run_command", "args": {"CommandLine": arg}}, "cwd": cwd}}
        if kind == "edit":
            return {"claude": {"tool_name": "Edit", "tool_input": {"file_path": arg, "old_string": "x", "new_string": extra}, "cwd": cwd},
                    "antigravity": {"toolCall": {"name": "replace_file_content", "args": {"TargetFile": arg, "TargetContent": "x", "ReplacementContent": extra}}, "cwd": cwd}}
        return {"claude": {"tool_name": "Write", "tool_input": {"file_path": arg, "content": extra}, "cwd": cwd},
                "antigravity": {"toolCall": {"name": "write_file", "args": {"Path": arg, "Content": extra}}, "cwd": cwd}}

    def test_closed_gate_yields_equal_decisions_on_both_protocols(self):
        spec = self.repo / "docs/specs/feat.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("x\n" * 309)
        r, d = str(self.repo), str(self.data)
        cases = [
            ("write", f"{r}/app.py", "x", "deny"), ("write", f"{r}/a/../../repo/app.py", "x", "deny"),
            ("write", f"{d}/repos/z/state.json", "{}", "deny"), ("write", str(spec), "line\n" * 120, "allow"),
            ("write", str(spec), "line\n" * 350, "ask"), ("edit", str(spec), "y\n" * 30, "ask"), ("edit", str(spec), "y", "allow"),
            ("cmd", "lean-runbook done goldfish", "", "ask"), ("cmd", "python3 /p/runbook.py skip gate --reason r", "", "ask"),
            ("cmd", "lean-runbook start o --force", "", "ask"), ("cmd", "lean-runbook finish", "", "ask"),
            ("cmd", "lean-runbook status", "", "allow"), ("cmd", "ls -la", "", "allow"),
            ("cmd", "cat $HOME/.cache/lean-runbook/repos/z/state.json", "", "deny"),
            ("cmd", "cat ~/.cache/lean-\"runbook\"/repos/z/state.json", "", "deny"),
            ("cmd", f"lean-runbook status; rm -rf {d}", "", "deny"),
        ]
        for kind, arg, extra, want in cases:
            for harness, payload in self.payloads(kind, arg, extra).items():
                with self.subTest(harness=harness, kind=kind, arg=arg[:40], extra=extra[:6]):
                    out = self.hook("pre-tool-use", payload, "--harness", harness)
                    got = out.get("hookSpecificOutput", {}).get("permissionDecision", "allow") if harness == "claude" \
                        else out["decision"].replace("force_ask", "ask")
                    self.assertEqual(got, want, out)

    def test_unparseable_payloads_fail_open_and_harness_flag_overrides(self):
        for raw in ("{not json", "", "[1]", "null", json.dumps({"cwd": str(self.repo), "mystery": 1})):
            for flags in ((), ("--harness", "claude"), ("--harness", "antigravity")):
                out = self.hook("pre-tool-use", raw, *flags)
                self.assertEqual(out.get("decision", "allow"), "allow", (raw, flags))
        agy = self.payloads("write", f"{self.repo}/a.py", "x")["antigravity"]
        self.assertEqual(self.hook("pre-tool-use", agy)["decision"], "deny")
        self.assertEqual(self.hook("pre-tool-use", agy, "--harness", "claude"), {})
        self.assertEqual(self.hook("pre-tool-use", self.payloads("cmd", "ls", "")["claude"], "--harness", "antigravity"), {"decision": "allow"})

    def test_session_start_injects_script_paths_on_both_protocols(self):
        ctx = self.hook("session-start", {"cwd": str(self.repo)}, "--harness", "claude")["hookSpecificOutput"]
        steps = self.hook("session-start", {"cwd": str(self.repo), "workspacePaths": [str(self.repo)]})["injectSteps"]
        self.assertEqual(ctx["hookEventName"], "SessionStart")
        for text in (ctx["additionalContext"], steps[0]["systemMessage"]["systemMessage"]):
            self.assertIn("feat", text)
            self.assertIn(str(RUNBOOK), text)
            self.assertIn(str(DESIGN), text)


class TestPreCommit(Base):
    def stage(self, name):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text("x\n")
        subprocess.run(["git", "-C", str(self.repo), "add", name], check=True)

    def test_blocks_staged_code_only_while_gate_closed_and_fails_closed(self):
        self.stage("docs/specs/feat.md")
        self.assertEqual(self.rb("--cwd", str(self.repo), "pre-commit").returncode, 0)
        self.stage("app.py")
        r = self.rb("--cwd", str(self.repo), "pre-commit")
        self.assertEqual((r.returncode, "app.py" in r.stderr), (1, True))
        self.rb("--cwd", str(self.repo), "done", "goldfish")
        self.assertEqual(self.rb("--cwd", str(self.repo), "pre-commit").returncode, 0)
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(self.rb("pre-commit", cwd=str(plain)).returncode, 1)


class TestDataRoot(unittest.TestCase):
    def test_env_override_wins_and_plugin_data_is_ignored(self):
        for path, name, default in ((RUNBOOK, "LEAN_RUNBOOK_DATA", "lean-runbook"), (DESIGN, "LEAN_DESIGN_DATA", "lean-design")):
            spec = importlib.util.spec_from_file_location(path.stem, path)
            mod = sys.modules[path.stem] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}, clear=True):
                os.environ.update({"CLAUDE_PLUGIN_DATA": "/x/claude", "PLUGIN_DATA": "/x/plugin"})
                self.assertEqual(mod.data_root(), Path(home) / ".cache" / default)
                os.environ[name] = "/x/override"
                self.assertEqual(mod.data_root(), Path("/x/override"))


if __name__ == "__main__":
    unittest.main()
