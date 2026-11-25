#!/usr/bin/env python3
"""End-to-end tests for the dual-protocol hook adapter (BR-1, INV-3, INV-4, EDGE-2, EDGE-5)."""
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
RUNBOOK = HERE / "runbook.py"
DESIGN = HERE.parents[1] / "lean-design/scripts/design_check.py"


def cmds(want, *lines):
    return [("cmd", line, "", want) for line in lines]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo, self.data, home = self.tmp / "repo", self.tmp / "data", self.tmp / "home"
        for d in (self.repo, self.data, home):
            d.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PLUGIN_DATA", "PLUGIN_DATA") and not k.startswith("GIT_")}
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
        if kind == "edit":  # extra: [(old, new, replace_all), ...]; a single edit uses the flat Edit forms
            e = [{"old_string": o, "new_string": n, "replace_all": m} for o, n, m in extra]
            c = [{"TargetContent": o, "ReplacementContent": n, "AllowMultiple": m} for o, n, m in extra]
            one = len(e) == 1
            return {"claude": {"tool_name": "Edit" if one else "MultiEdit", "tool_input": {"file_path": arg, **(e[0] if one else {"edits": e})}, "cwd": cwd},
                    "antigravity": {"toolCall": {"name": "replace_file_content", "args": {"TargetFile": arg, **(c[0] if one else {"ReplacementChunks": c})}}, "cwd": cwd}}
        return {"claude": {"tool_name": "Write", "tool_input": {"file_path": arg, "content": extra}, "cwd": cwd},
                "antigravity": {"toolCall": {"name": "write_file", "args": {"Path": arg, "Content": extra}}, "cwd": cwd}}

    def check(self, cases):
        for kind, arg, extra, want in cases:
            for harness, payload in self.payloads(kind, arg, extra).items():
                with self.subTest(harness=harness, kind=kind, arg=arg[:60], extra=extra[:6]):
                    out = self.hook("pre-tool-use", payload, "--harness", harness)
                    got = out.get("hookSpecificOutput", {}).get("permissionDecision", "allow") if harness == "claude" else out["decision"].replace("force_ask", "ask")
                    self.assertEqual(got, want)

    def test_closed_gate_yields_equal_decisions_on_both_protocols(self):
        spec, fresh = (str(self.repo / "docs/specs" / n) for n in ("feat.md", "new.md"))
        Path(spec).parent.mkdir(parents=True)
        Path(spec).write_text("x\n" * 309)
        r, d, grow = str(self.repo), str(self.data), ("x", "x\ny", True)
        self.check([
            ("write", f"{r}/app.py", "x", "deny"), ("write", f"{r}/a/../../repo/app.py", "x", "deny"), ("write", f"{d}/repos/z/state.json", "{}", "deny"),
            ("write", spec, "line\n" * 120, "allow"), ("write", spec, "l\n" * 320, "allow"), ("write", spec, "l\n" * 321, "ask"), ("write", spec, "line\n" * 350, "ask"),
            ("edit", spec, [("x", "y\n" * 30, False)], "ask"), ("edit", spec, [("x", "y", False)], "allow"), ("edit", spec, [grow], "ask"),
            ("edit", spec, [("x", "x\ny", False)], "allow"), ("edit", spec, [("zzz", "q\n" * 60, True)], "allow"), ("edit", spec, [grow, ("y\n", "", True)], "allow"),
            ("edit", fresh, [("", "l\n" * 400, False)], "ask"), ("edit", fresh, [("", "l\n", False)], "allow"),
            *cmds("ask", "lean-runbook done goldfish", "python3 /p/runbook.py skip gate --reason r", "lean-runbook start o --force", "lean-runbook finish",
                  "~/.local/bin/lean-runbook done goldfish", "/usr/local/bin/lean-runbook done goldfish", '"$HOME/.local/bin/lean-runbook" skip gate --reason x',
                  "lean-runbook done --reason ok goldfish", "lean-runbook done GOLDFISH", "lean-runbook done 02", "lean-runbook done --cwd . goldfish",
                  "lean-runbook skip --reason r gate", "lean-runbook skip GATE", "lean-runbook start --force feat", "lean-runbook start feat \\\n --force"),
            *cmds("allow", "lean-runbook status", "ls -la", "lean-runbook done spec", "lean-runbook start feat", "~/.local/bin/lean-runbook status"),
            *cmds("deny", "cat $HOME/.cache/lean-runbook/repos/z/state.json", "cat ~/.cache/lean-\"runbook\"/repos/z/state.json", f"lean-runbook status; rm -rf {d}")])

    def test_state_dir_exemption_needs_the_cli_as_command_word_and_holds_without_active_feature(self):
        d = self.env["LEAN_RUNBOOK_DATA"] = str(self.tmp / "my data" / "lean-runbook")  # spaces, and ends in lean-runbook
        self.rb("--cwd", str(self.repo), "start", "feat")
        self.check([*cmds("deny", "rm -rf ~/.cache/lean-runbook", "rm -rf ~/.cache/lean-runbook/", 'rm -rf "$HOME/.cache/lean-runbook"', 'rm -rf "$HOME/.cache/lean-runbook/"',
                          "cd ~/.cache/lean-runbook && rm -rf .", f'rm -rf "{d}"', f'rm -rf "{d}/"', f'rm -rf "{d}" # lean-runbook', f'cat "{d}/x" lean-runbook',
                          f'echo lean-runbook > "{d}/state.json"', f'lean-runbook status > "{d}/x"', "rm -rf ~/.cache/lean-runbook # lean-runbook"),
                    *cmds("allow", "lean-runbook status", "~/.local/bin/lean-runbook status", 'python3 "/p q/runbook.py" status', f'LEAN_RUNBOOK_DATA="{d}" lean-runbook status',
                          f'python3 "{d}/../x/runbook.py" status')])
        self.rb("--cwd", str(self.repo), "finish")  # no active feature: only the state-dir protection applies
        self.check([("write", f"{d}/repos/z/state.json", "{}", "deny"), ("write", f"{self.repo}/app.py", "x", "allow"),
                    *cmds("deny", f"rm -rf {d}", "cat $HOME/.cache/lean-runbook/x"), *cmds("allow", "lean-runbook done goldfish", "ls")])

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
            for needle in ("feat", str(RUNBOOK), str(DESIGN)):
                self.assertIn(needle, text)


class TestPreCommit(Base):
    def stage(self, name):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text("x\n")
        subprocess.run(["git", "-C", str(self.repo), "add", name], check=True)

    def pc(self, **kw):
        return self.rb("--cwd", str(self.repo), "pre-commit", **kw)

    def test_blocks_closed_gate_and_fails_closed_on_corrupt_or_unreadable_state(self):
        self.stage("docs/specs/feat.md")
        self.assertEqual(self.pc().returncode, 0)
        self.stage("app.py")
        r = self.pc()
        self.assertEqual((r.returncode, "app.py" in r.stderr), (1, True))
        self.rb("--cwd", str(self.repo), "done", "goldfish")
        self.assertEqual(self.pc().returncode, 0)
        (self.tmp / "plain").mkdir()
        self.assertEqual(self.rb("pre-commit", cwd=str(self.tmp / "plain")).returncode, 1)
        state = next(self.data.glob("repos/*/state.json"))
        for body in ("", "{not", "null", "[]", '"s"'):
            state.write_text(body)
            self.assertEqual(self.pc().returncode, 1, body)
        state.write_text("{}")
        for target in (state, state.parent) if os.geteuid() else ():
            mode = target.stat().st_mode
            target.chmod(0)
            rc = self.pc().returncode
            target.chmod(mode)
            self.assertEqual(rc, 1, target)
        self.env["LEAN_RUNBOOK_DATA"] = str(self.tmp / "no-state")
        self.assertEqual(self.pc().returncode, 0)


class TestDataRoot(unittest.TestCase):
    def test_env_override_wins_and_plugin_data_is_ignored(self):
        for path, name, default in ((RUNBOOK, "LEAN_RUNBOOK_DATA", "lean-runbook"), (DESIGN, "LEAN_DESIGN_DATA", "lean-design")):
            data_root = runpy.run_path(str(path))["data_root"]
            with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home, "CLAUDE_PLUGIN_DATA": "/x/claude", "PLUGIN_DATA": "/x/plugin"}, clear=True):
                self.assertEqual(data_root(), Path(home) / ".cache" / default)
                os.environ[name] = "/x/override"
                self.assertEqual(data_root(), Path("/x/override"))


if __name__ == "__main__":
    unittest.main()
