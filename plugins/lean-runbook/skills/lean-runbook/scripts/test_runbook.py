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
        self.env = {**os.environ, "LEAN_RUNBOOK_DATA": str(self.data)}

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
            [sys.executable, str(RUNBOOK), "hook", "session-start" if mode.endswith("start") else "pre-tool-use", "--harness", "antigravity"],
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

    def test_epic_parallel_worktrees_have_isolated_gates_and_aggregate_status(self) -> None:
        # Need an initial commit before adding git worktrees
        (self.repo / "README.md").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(
            [
                "git", "-C", str(self.repo),
                "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "init",
            ],
            check=True,
        )

        wt_a = Path(self.tmp.name) / "wt-stage-schema"
        wt_b = Path(self.tmp.name) / "wt-stage-hud"
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "slice/stage-schema", str(wt_a)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "slice/stage-hud", str(wt_b)],
            check=True,
        )

        # Start two slices under the same epic in two separate share worktrees
        ra = subprocess.run(
            [sys.executable, str(RUNBOOK), "--cwd", str(wt_a), "start", "stage-schema", "--epic", "progression-system"],
            env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(ra.returncode, 0, ra.stderr)
        self.assertIn("[epic: progression-system]", ra.stdout)

        rb = subprocess.run(
            [sys.executable, str(RUNBOOK), "--cwd", str(wt_b), "start", "stage-hud", "--epic", "progression-system"],
            env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(rb.returncode, 0, rb.stderr)

        # Open gate ONLY in worktree A; worktree B must remain CLOSED
        r_open = subprocess.run(
            [sys.executable, str(RUNBOOK), "--cwd", str(wt_a), "done", "goldfish"],
            env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(r_open.returncode, 0, r_open.stderr)

        pw_a = self.run_hook("hook-pre-write", {
            "cwd": str(wt_a),
            "toolCall": {"name": "edit_file", "args": {"Path": str(wt_a / "stage.gd")}},
        })
        self.assertEqual(pw_a["decision"], "allow")

        pw_b = self.run_hook("hook-pre-write", {
            "cwd": str(wt_b),
            "toolCall": {"name": "edit_file", "args": {"Path": str(wt_b / "hud.gd")}},
        })
        self.assertEqual(pw_b["decision"], "deny")

        # Main coordinator repo (no active slice) stays unblocked and can inspect all slices
        r_all = self.run_cli("status", "--epic", "progression-system")
        self.assertEqual(r_all.returncode, 0, r_all.stderr)
        self.assertIn("active slices (2)", r_all.stdout)
        self.assertIn("stage-schema", r_all.stdout)
        self.assertIn("Gate: OPEN", r_all.stdout)
        self.assertIn("stage-hud", r_all.stdout)
        self.assertIn("Gate: CLOSED", r_all.stdout)

        # Filtering by a different epic shows none
        r_other = self.run_cli("status", "--epic", "other-epic")
        self.assertEqual(r_other.returncode, 0, r_other.stderr)
        self.assertIn("no active slices for epic 'other-epic'", r_other.stdout)


if __name__ == "__main__":
    unittest.main()
