#!/usr/bin/env python3
"""Unit tests for lean-runbook CLI & Antigravity 2.0 hook handlers."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parent / "runbook.py"


class LeanRunbookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.data = Path(self.tmp.name) / "data"
        self.repo.mkdir()
        self.data.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.env = {**os.environ, "PLUGIN_DATA": str(self.data)}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(RUNBOOK), "--cwd", str(self.repo), *args],
            env=self.env,
            text=True,
            capture_output=True,
        )

    def run_hook(self, mode: str, payload: dict) -> dict:
        res = subprocess.run(
            [sys.executable, str(RUNBOOK), mode],
            input=json.dumps(payload),
            env=self.env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(res.stdout)

    def test_no_active_feature_allows_everything(self) -> None:
        ss = self.run_hook("hook-session-start", {"cwd": str(self.repo)})
        self.assertEqual(ss, {})
        pw = self.run_hook("hook-pre-write", {
            "cwd": str(self.repo),
            "toolCall": {"name": "write_file", "args": {"Path": str(self.repo / "app.py"), "Content": "x"}},
        })
        self.assertEqual(pw["decision"], "allow")

    def test_spec_gate_blocks_code_but_allows_specs_and_opens_on_goldfish(self) -> None:
        r = self.run_cli("start", "example-feature")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Gate: CLOSED", r.stdout)

        # SessionStart injects 1-line summary
        ss = self.run_hook("hook-session-start", {"cwd": str(self.repo)})
        msg = ss["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("example-feature", msg)
        self.assertIn("Gate: CLOSED", msg)

        # Code edit inside repo is denied while gate is closed
        pw_code = self.run_hook("hook-pre-write", {
            "cwd": str(self.repo),
            "toolCall": {"name": "edit_file", "args": {"Path": str(self.repo / "app.py")}},
        })
        self.assertEqual(pw_code["decision"], "deny")

        # Spec markdown <=300 lines is allowed
        pw_spec = self.run_hook("hook-pre-write", {
            "cwd": str(self.repo),
            "toolCall": {
                "name": "write_file",
                "args": {"Path": str(self.repo / "docs/specs/example-feature.md"), "Content": "line\n" * 120},
            },
        })
        self.assertEqual(pw_spec["decision"], "allow")

        # Spec >320 lines triggers force_ask token guardrail
        pw_bloat = self.run_hook("hook-pre-write", {
            "cwd": str(self.repo),
            "toolCall": {
                "name": "write_file",
                "args": {"Path": str(self.repo / "docs/specs/example-feature.md"), "Content": "line\n" * 350},
            },
        })
        self.assertEqual(pw_bloat["decision"], "force_ask")
        self.assertIn("Token Guardrail", pw_bloat["reason"])

        # Attempting to open gate via run_command triggers force_ask (never silent!)
        pc_open = self.run_hook("hook-pre-cmd", {
            "cwd": str(self.repo),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "python3 runbook.py done goldfish"}},
        })
        self.assertEqual(pc_open["decision"], "force_ask")

        pc_skip = self.run_hook("hook-pre-cmd", {
            "cwd": str(self.repo),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "python3 runbook.py skip gate --reason test"}},
        })
        self.assertEqual(pc_skip["decision"], "force_ask")

        # Direct tampering with state dir is denied
        pc_tamper = self.run_hook("hook-pre-cmd", {
            "cwd": str(self.repo),
            "toolCall": {"name": "run_command", "args": {"CommandLine": f"rm -rf {self.data}"}},
        })
        self.assertEqual(pc_tamper["decision"], "deny")

        # Once user approves `done goldfish`, gate opens and code edits are allowed
        r2 = self.run_cli("done", "goldfish", "--reason", "all findings resolved")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("Gate: OPEN", r2.stdout)

        pw_code2 = self.run_hook("hook-pre-write", {
            "cwd": str(self.repo),
            "toolCall": {"name": "edit_file", "args": {"Path": str(self.repo / "app.py")}},
        })
        self.assertEqual(pw_code2["decision"], "allow")

        # Plan >320 lines still triggers token guardrail
        pw_plan_bloat = self.run_hook("hook-pre-write", {
            "cwd": str(self.repo),
            "toolCall": {
                "name": "write_file",
                "args": {"Path": str(self.repo / ".loop/example-feature/plan.md"), "Content": "line\n" * 400},
            },
        })
        self.assertEqual(pw_plan_bloat["decision"], "force_ask")

        # Finish clears active feature
        r3 = self.run_cli("finish")
        self.assertEqual(r3.returncode, 0)
        self.assertEqual(self.run_hook("hook-session-start", {"cwd": str(self.repo)}), {})


if __name__ == "__main__":
    unittest.main()
