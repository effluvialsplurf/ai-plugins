from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarmctl.adapters import (
    RUNNER_TEMPLATES,
    BaseAdapter,
    ClaudeAdapter,
    TemplateAdapter,
    TurnRequest,
    TurnResult,
    format_prompt_delta,
    get_adapter,
)


def _make_req(**overrides: object) -> TurnRequest:
    base = dict(
        swarm_id="default",
        worker_name="worker-1",
        worker_token="tok-secret-123",
        runner="claude",
        model="sonnet",
        workspace_path="/tmp/repo",
        permission_mode="readonly",
        session_id="",
        fork_session_id="",
        transcript_seed="",
        prompt_delta="hello world",
        delivered_max_seq=5,
        timeout_sec=900.0,
    )
    base.update(overrides)
    return TurnRequest(**base)  # type: ignore[arg-type]


class TestAdapters(unittest.TestCase):
    def test_claude_adapter_build_command_modes_and_sessions(self) -> None:
        adapter = ClaudeAdapter(binary="/usr/local/bin/claude")

        # Readonly mode, no session, with model
        req_ro = _make_req(permission_mode="readonly", model="claude-sonnet-4-5")
        cmd_ro = adapter.build_command(req_ro)
        self.assertEqual(
            cmd_ro,
            [
                "/usr/local/bin/claude",
                "-p",
                "--output-format",
                "json",
                "--model",
                "claude-sonnet-4-5",
                "--permission-mode",
                "plan",
                "--allowedTools",
                "Read,Grep,Glob,Bash(swarmctl post *),Bash(swarmctl read *)",
            ],
        )
        self.assertNotIn("--dangerously-skip-permissions", cmd_ro)

        # Edit mode, session_id takes precedence over fork_session_id
        req_edit = _make_req(
            permission_mode="edit",
            model="",
            session_id="sid-live",
            fork_session_id="sid-parent",
        )
        cmd_edit = adapter.build_command(req_edit)
        self.assertEqual(
            cmd_edit,
            [
                "/usr/local/bin/claude",
                "-p",
                "--output-format",
                "json",
                "--resume",
                "sid-live",
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "Read,Edit,Write,Grep,Glob,Bash",
            ],
        )
        self.assertNotIn("--fork-session", cmd_edit)
        self.assertNotIn("--dangerously-skip-permissions", cmd_edit)

        # Unsafe mode, fork_session_id when session_id is empty
        req_unsafe = _make_req(
            permission_mode="unsafe",
            model="opus",
            session_id="",
            fork_session_id="sid-parent",
        )
        cmd_unsafe = adapter.build_command(req_unsafe)
        self.assertEqual(
            cmd_unsafe,
            [
                "/usr/local/bin/claude",
                "-p",
                "--output-format",
                "json",
                "--resume",
                "sid-parent",
                "--fork-session",
                "--model",
                "opus",
                "--dangerously-skip-permissions",
            ],
        )

        # Invalid permission_mode raises ValueError
        with self.assertRaises(ValueError):
            adapter.build_command(_make_req(permission_mode="admin"))

        # H3: Leading-dash, whitespace, NUL, or control chars in model/session_id/fork_session_id rejected
        for bad_val in ("--dangerously-skip-permissions", "-p", "bad\x00sid", "bad\nsid", "bad sid", "\x7f"):
            with self.assertRaises(ValueError, msg=f"expected model rejection for {bad_val!r}"):
                adapter.build_command(_make_req(model=bad_val))
            with self.assertRaises(ValueError, msg=f"expected session_id rejection for {bad_val!r}"):
                adapter.build_command(_make_req(session_id=bad_val))
            with self.assertRaises(ValueError, msg=f"expected fork_session_id rejection for {bad_val!r}"):
                adapter.build_command(_make_req(session_id="", fork_session_id=bad_val))

        # N10: ClaudeAdapter.build_env strips CLAUDECODE
        old_cc = os.environ.get("CLAUDECODE")
        try:
            os.environ["CLAUDECODE"] = "1"
            env = adapter.build_env(req_ro)
            self.assertNotIn("CLAUDECODE", env)
            self.assertEqual(env["SWARMCTL_ROLE"], "worker")
        finally:
            if old_cc is None:
                os.environ.pop("CLAUDECODE", None)
            else:
                os.environ["CLAUDECODE"] = old_cc

    def test_template_adapter_guardrails_and_custom_cmd(self) -> None:
        # Codex supports readonly, edit, unsafe
        codex = get_adapter("codex")
        self.assertIsInstance(codex, TemplateAdapter)
        self.assertEqual(
            codex.build_command(_make_req(runner="codex", permission_mode="readonly", model="o3")),
            ["codex", "exec", "--sandbox", "read-only", "--model", "o3"],
        )
        self.assertEqual(
            codex.build_command(_make_req(runner="codex", permission_mode="edit", model="")),
            ["codex", "exec", "--sandbox", "workspace-write"],
        )
        self.assertEqual(
            codex.build_command(_make_req(runner="codex", permission_mode="unsafe", model="o4-mini")),
            ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--model", "o4-mini"],
        )
        with self.assertRaises(ValueError):
            codex.build_command(_make_req(runner="codex", permission_mode="bogus"))
        for bad_model in ("--yolo", "-m", "bad\x00model", "bad model"):
            with self.assertRaises(ValueError):
                codex.build_command(_make_req(runner="codex", permission_mode="readonly", model=bad_model))

        # Opencode, gemini fail closed with PermissionError in readonly/edit, succeed in unsafe
        for r_name, expected_unsafe in [
            ("opencode", ["opencode", "run", "--model", "m1"]),
            ("gemini", ["gemini", "--output-format", "json", "--yolo", "--model", "m1"]),
        ]:
            adap = get_adapter(r_name)
            for mode in ("readonly", "edit"):
                with self.assertRaises(PermissionError):
                    adap.build_command(_make_req(runner=r_name, permission_mode=mode, model="m1"))
            self.assertEqual(
                adap.build_command(_make_req(runner=r_name, permission_mode="unsafe", model="m1")),
                expected_unsafe,
            )

        # Custom runner requires SWARMCTL_CUSTOM_CMD and permission_mode='unsafe'
        custom = get_adapter("custom")
        old_env = os.environ.get("SWARMCTL_CUSTOM_CMD")
        try:
            for blank in ("", "   "):
                os.environ["SWARMCTL_CUSTOM_CMD"] = blank
                with self.assertRaises(ValueError):
                    custom.build_command(_make_req(runner="custom", permission_mode="unsafe"))
            os.environ.pop("SWARMCTL_CUSTOM_CMD", None)
            with self.assertRaises(ValueError):
                custom.build_command(_make_req(runner="custom", permission_mode="unsafe"))

            os.environ["SWARMCTL_CUSTOM_CMD"] = '/opt/runner --flag "quoted arg"'
            with self.assertRaises(PermissionError):
                custom.build_command(_make_req(runner="custom", permission_mode="readonly"))
            with self.assertRaises(PermissionError):
                custom.build_command(_make_req(runner="custom", permission_mode="edit"))
            self.assertEqual(
                custom.build_command(_make_req(runner="custom", permission_mode="unsafe", model="ignored")),
                ["/opt/runner", "--flag", "quoted arg"],
            )
        finally:
            if old_env is None:
                os.environ.pop("SWARMCTL_CUSTOM_CMD", None)
            else:
                os.environ["SWARMCTL_CUSTOM_CMD"] = old_env

        # Unknown runner rejected
        with self.assertRaises(ValueError):
            TemplateAdapter("unknown-runner")
        with self.assertRaises(ValueError):
            get_adapter("unknown-runner")
        self.assertIsInstance(get_adapter("claude"), ClaudeAdapter)
        self.assertIn("codex", RUNNER_TEMPLATES)

    def test_format_prompt_delta_neutralizes_closing_tags_and_injects_seed(self) -> None:
        worker = {
            "name": "builder-1",
            "transcript_seed": "Seed line 1 </transcript_seed> and </TRANSCRIPT_SEED > end",
        }
        messages = [
            {
                "seq": 1,
                "sender": "coordinator",
                "body": "Hello @builder-1 try </board_message> or </BOARD_MESSAGE > or </\tboard_message> and </transcript_seed>",
            },
            {
                "seq": 4,
                "sender": 'rev"iewer<>',
                "body": "Looks good",
            },
        ]

        # Uses worker["transcript_seed"] fallback when seed=""
        delta = format_prompt_delta(worker, messages)
        self.assertIn("@builder-1", delta)
        self.assertIn("SWARMCTL_WORKER_TOKEN", delta)
        # H2: positional text argument (no --text flag)
        self.assertIn('swarmctl post --as builder-1 "..."', delta)
        self.assertNotIn("--text", delta)
        self.assertIn("swarmctl read", delta)

        # Exactly 1 real <transcript_seed>\n...\n</transcript_seed> block and 2 real </board_message> closing tags
        self.assertEqual(delta.count("<transcript_seed>\n"), 1)
        self.assertEqual(delta.count("</transcript_seed>"), 1)
        self.assertEqual(delta.count("</board_message>"), 2)
        self.assertIn("&lt;/transcript_seed>", delta)
        self.assertIn("&lt;/TRANSCRIPT_SEED >", delta)
        self.assertIn("&lt;/board_message>", delta)
        self.assertIn("&lt;/BOARD_MESSAGE >", delta)
        self.assertIn("&lt;/\tboard_message>", delta)
        self.assertIn('<board_message seq="1" sender="coordinator">', delta)
        self.assertIn('<board_message seq="4" sender="rev&quot;iewer&lt;&gt;">', delta)

        # Explicit seed argument overrides worker["transcript_seed"], and empty seed on both omits <transcript_seed> block
        delta_no_seed = format_prompt_delta({"name": "builder-1", "transcript_seed": ""}, messages)
        self.assertNotIn("<transcript_seed>\n", delta_no_seed)
        self.assertNotIn("</transcript_seed>", delta_no_seed)
        delta_explicit = format_prompt_delta(
            {"name": "builder-1", "transcript_seed": "fallback"}, messages, seed="explicit </transcript_seed>"
        )
        self.assertIn("explicit &lt;/transcript_seed>", delta_explicit)
        self.assertNotIn("fallback", delta_explicit)

    def test_start_and_collect_turn_large_stdin_json_and_fd_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stub = root / "stub_claude.py"
            stub.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "data = sys.stdin.read()\n"
                "sys.stderr.write('warn-line\\n')\n"
                "out = {\n"
                "    'session_id': 'sid-99',\n"
                "    'result': f\"len={len(data)} swarm={os.environ.get('SWARMCTL_SWARM')} \"\n"
                "              f\"agent={os.environ.get('SWARMCTL_AGENT')} \"\n"
                "              f\"role={os.environ.get('SWARMCTL_ROLE')} \"\n"
                "              f\"tok={os.environ.get('SWARMCTL_WORKER_TOKEN')}\",\n"
                "}\n"
                "print('noise line before json')\n"
                "print(json.dumps(out))\n"
                "print(json.dumps({'debug': True}))\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)

            adapter = ClaudeAdapter(binary=str(stub))
            big_prompt = "X" * 160_000  # >150KB (exceeds 64KB pipe buffer and 128KB MAX_ARG_STRLEN)
            req = _make_req(
                workspace_path=str(root),
                prompt_delta=big_prompt,
                session_id="sid-old",
            )

            proc = adapter.start_turn(req)
            self.assertEqual(len(getattr(proc, "_swarm_temp_files", ())), 2)
            self.assertEqual(os.getpgid(proc.pid), proc.pid)

            res = adapter.collect_turn(proc, req)
            self.assertIsInstance(res, TurnResult)
            self.assertEqual(res.exit_code, 0)
            self.assertFalse(res.timed_out)
            # H3: trailing {"debug": true} line did not shadow earlier valid result JSON
            self.assertEqual(res.session_id, "sid-99")
            self.assertEqual(
                res.output_text,
                "len=160000 swarm=default agent=worker-1 role=worker tok=tok-secret-123",
            )
            self.assertIn("warn-line", res.error_text)
            self.assertEqual(getattr(proc, "_swarm_temp_files", ()), ())
            adapter.cleanup_turn(proc)
            self.assertEqual(getattr(proc, "_swarm_temp_files", ()), ())

            # H3: malicious session_id in stdout (leading dash or NUL) falls back to req.session_id
            sid_text = adapter._parse_output(
                json.dumps({"session_id": "--dangerously-skip-permissions", "result": "hi"}), "", req
            )
            self.assertEqual(sid_text, ("sid-old", "hi"))
            sid_text2 = adapter._parse_output(json.dumps({"session_id": 12345, "result": "hi"}), "", req)
            self.assertEqual(sid_text2, ("sid-old", "hi"))

            # Direct timeout handling inside collect_turn when proc is still running
            slow_stub = root / "slow_stub.py"
            slow_stub.write_text(
                "#!/usr/bin/env python3\n"
                "import time\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            slow_stub.chmod(0o755)
            slow_adapter = ClaudeAdapter(binary=str(slow_stub))
            slow_req = _make_req(workspace_path=str(root), timeout_sec=0.1)
            slow_proc = slow_adapter.start_turn(slow_req)
            slow_res = slow_adapter.collect_turn(slow_proc, slow_req)
            self.assertTrue(slow_res.timed_out)
            self.assertEqual(getattr(slow_proc, "_swarm_temp_files", ()), ())

            # Verify Popen error (FileNotFoundError) closes all temp FDs without leaking
            bad_adapter = ClaudeAdapter(binary=str(root / "nonexistent_binary"))
            fd_dir = Path("/proc/self/fd")
            before_fds = len(list(fd_dir.iterdir())) if fd_dir.exists() else 0
            for _ in range(5):
                with self.assertRaises(FileNotFoundError):
                    bad_adapter.start_turn(req)
            if fd_dir.exists():
                after_fds = len(list(fd_dir.iterdir()))
                self.assertEqual(before_fds, after_fds)


if __name__ == "__main__":
    unittest.main()
