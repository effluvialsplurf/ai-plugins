from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarmctl import SwarmStore, WorkspaceManager
from swarmctl.cli import (
    CLAUDE_MODELS,
    CLAUDE_MODELS_ALL,
    build_parser,
    main,
    resolve_repo_root,
    resolve_swarm_dir,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = (Path(self.tmp.name) / "repo").resolve()
        self.repo.mkdir()
        _git(self.repo, "init")
        (self.repo / "README.md").write_text("# test repo\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-m", "initial commit")
        self.swarm_dir = self.repo / ".swarm" / "default"
        self.db_path = self.swarm_dir / "board.db"
        self._saved_env = dict(os.environ)
        for k in ("SWARMCTL_SWARM", "SWARMCTL_WORKER_TOKEN", "SWARMCTL_ROLE", "SWARMCTL_AGENT"):
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved_env)
        self.tmp.cleanup()

    def _run_cli(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        old_cwd = Path.cwd()
        old_env = dict(os.environ)
        try:
            if env is not None:
                os.environ.update(env)
            if cwd is not None:
                os.chdir(cwd)
            with redirect_stdout(out), redirect_stderr(err):
                code = main(argv)
        finally:
            os.chdir(old_cwd)
            os.environ.clear()
            os.environ.update(old_env)
        return code, out.getvalue(), err.getvalue()

    def test_init_title_models_and_json_placement(self) -> None:
        parser = build_parser()
        self.assertIsNotNone(parser)

        # models works without initialized swarm or repo
        code, out, err = self._run_cli(["models", "--json"], cwd=Path(self.tmp.name))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["default_runner"], "claude")
        self.assertEqual(tuple(data["claude_models"]), CLAUDE_MODELS)
        self.assertEqual(data["runners"]["claude"]["guardrails"], ["readonly", "edit", "unsafe"])
        self.assertEqual(data["runners"]["gemini"]["guardrails"], ["unsafe"])

        code, out, err = self._run_cli(["--json", "models", "--all"], cwd=Path(self.tmp.name))
        self.assertEqual(code, 0, err)
        data_all = json.loads(out)
        self.assertEqual(tuple(data_all["claude_models"]), CLAUDE_MODELS_ALL)

        # init with --json after subcommand
        code, out, err = self._run_cli(
            ["--repo", str(self.repo), "init", "--title", "Initial Swarm", "--model", "sonnet", "--json"]
        )
        self.assertEqual(code, 0, err)
        meta = json.loads(out)
        self.assertEqual(meta["swarm_id"], "default")
        self.assertEqual(meta["title"], "Initial Swarm")
        self.assertEqual(meta["default_model"], "sonnet")

        # title update with --json before subcommand
        code, out, err = self._run_cli(["--repo", str(self.repo), "--json", "title", "Updated Title"])
        self.assertEqual(code, 0, err)
        meta2 = json.loads(out)
        self.assertEqual(meta2["title"], "Updated Title")

        # status with --json before and after subcommand
        code1, out1, _ = self._run_cli(["--repo", str(self.repo), "--json", "status"])
        code2, out2, _ = self._run_cli(["--repo", str(self.repo), "status", "--json"])
        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertEqual(json.loads(out1), json.loads(out2))

    def test_edge1_fail_closed_on_invalid_swarm_uninitialized_db_and_invalid_worker_name(self) -> None:
        # Invalid --swarm ../evil must fail before touching filesystem
        code, out, err = self._run_cli(["--repo", str(self.repo), "--swarm", "../evil", "status"])
        self.assertEqual(code, 1)
        self.assertIn("swarm", err.lower())
        self.assertFalse((self.repo / ".swarm").exists())

        with self.assertRaises(ValueError):
            resolve_swarm_dir(self.repo, "../evil")

        # Uninitialized swarm must not create .swarm or board.db
        code, out, err = self._run_cli(["--repo", str(self.repo), "--swarm", "typo", "read"])
        self.assertEqual(code, 1)
        self.assertTrue(len(err.strip()) > 0)
        self.assertFalse((self.repo / ".swarm" / "typo" / "board.db").exists())

        code, out, err = self._run_cli(["--repo", str(self.repo), "status"])
        self.assertEqual(code, 1)
        self.assertFalse(self.db_path.exists())

        # Init now, then try invalid worker name UPPER
        self._run_cli(["--repo", str(self.repo), "init"])
        code, out, err = self._run_cli(
            ["--repo", str(self.repo), "add", "UPPER", "--brief", "do work", "--no-wake"]
        )
        self.assertEqual(code, 1)
        self.assertIn("worker", err.lower())

        # Missing --repo directory fails closed
        code, out, err = self._run_cli(["--repo", str(self.repo / "nonexistent"), "models"])
        self.assertEqual(code, 1)

    def test_add_strips_token_prevalidates_guardrails_and_rolls_back_worktree_on_db_error(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])

        # Add inherit worker (JSON & human output must never leak worker_token)
        code, out, err = self._run_cli(
            ["--repo", str(self.repo), "add", "w1", "--brief", "check repo", "--no-wake", "--json"]
        )
        self.assertEqual(code, 0, err)
        w1 = json.loads(out)
        self.assertEqual(w1["name"], "w1")
        self.assertEqual(w1["permission_mode"], "readonly")
        self.assertEqual(w1["brief_seq"], 1)
        self.assertNotIn("worker_token", w1)
        self.assertNotIn("worker_token", out)

        with SwarmStore(self.db_path) as store:
            raw_w1 = store.get_worker("w1")
            assert raw_w1 is not None
            token_val = raw_w1["worker_token"]
        self.assertNotIn(token_val, out)

        code_h, out_h, err_h = self._run_cli(
            ["--repo", str(self.repo), "add", "w2", "--brief", "human add", "--no-wake"]
        )
        self.assertEqual(code_h, 0, err_h)
        with SwarmStore(self.db_path) as store:
            raw_w2 = store.get_worker("w2")
            assert raw_w2 is not None
            self.assertNotIn(raw_w2["worker_token"], out_h)

        # Invalid runner or leading-dash model rejected before creating share worktree
        code, _, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "add",
                "w3",
                "--brief",
                "x",
                "--runner",
                "invalid_runner",
                "--workspace",
                "share",
                "--no-wake",
            ]
        )
        self.assertEqual(code, 1)
        self.assertFalse((self.swarm_dir / "worktrees" / "w3").exists())

        code, _, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "add",
                "w3",
                "--brief",
                "x",
                "--model=-malicious",
                "--workspace",
                "share",
                "--no-wake",
            ]
        )
        self.assertEqual(code, 1)
        self.assertFalse((self.swarm_dir / "worktrees" / "w3").exists())

        # Unsupported runner guardrail (gemini without --unsafe) rejected before creating share worktree
        code, _, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "add",
                "w3",
                "--brief",
                "x",
                "--runner",
                "gemini",
                "--workspace",
                "share",
                "--no-wake",
            ]
        )
        self.assertEqual(code, 1)
        self.assertFalse((self.swarm_dir / "worktrees" / "w3").exists())

        # Rollback share worktree if store.add_worker fails (e.g. invalid --fork member)
        code, _, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "add",
                "w3",
                "--brief",
                "x",
                "--workspace",
                "share",
                "--fork",
                "nonexistent_member",
                "--no-wake",
            ]
        )
        self.assertEqual(code, 1)
        self.assertFalse((self.swarm_dir / "worktrees" / "w3").exists())
        branch_res = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/swarm/default/w3"],
            cwd=str(self.repo),
        )
        self.assertNotEqual(branch_res.returncode, 0)

    def test_status_and_read_filters_and_seqs_validation(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])
        self._run_cli(["--repo", str(self.repo), "add", "w1", "--brief", "b1", "--no-wake"])
        self._run_cli(["--repo", str(self.repo), "post", "m2", "--no-wake"])
        self._run_cli(["--repo", str(self.repo), "post", "m3", "--no-wake"])

        # read --since 1 --limit 1
        code, out, err = self._run_cli(
            ["--repo", str(self.repo), "read", "--since", "1", "--limit", "1", "--json"]
        )
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual([m["seq"] for m in res["messages"]], [2])
        self.assertEqual(res["head_seq"], 3)

        # read --seqs 1,3 overrides --since and --limit
        code, out, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "read",
                "--since",
                "2",
                "--limit",
                "1",
                "--seqs",
                "1,3",
                "--json",
            ]
        )
        self.assertEqual(code, 0, err)
        res_seqs = json.loads(out)
        self.assertEqual([m["seq"] for m in res_seqs["messages"]], [1, 3])

        # invalid --seqs 1,abc exits 1
        code, _, err = self._run_cli(["--repo", str(self.repo), "read", "--seqs", "1,abc"])
        self.assertEqual(code, 1)

        code, _, err = self._run_cli(["--repo", str(self.repo), "read", "--seqs", "1,"])
        self.assertEqual(code, 1)

        # read --status matches status without worker_token
        code_s, out_s, _ = self._run_cli(["--repo", str(self.repo), "status", "--json"])
        code_r, out_r, _ = self._run_cli(["--repo", str(self.repo), "read", "--status", "--json"])
        self.assertEqual(code_s, 0)
        self.assertEqual(code_r, 0)
        self.assertEqual(json.loads(out_s), json.loads(out_r))
        for w in json.loads(out_s)["workers"]:
            self.assertNotIn("worker_token", w)

    def test_edge5_model_switch_states_and_validation(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])
        self._run_cli(["--repo", str(self.repo), "add", "w1", "--brief", "b1", "--no-wake"])

        # Valid switch on waiting worker
        code, out, err = self._run_cli(["--repo", str(self.repo), "model", "w1", "sonnet", "--json"])
        self.assertEqual(code, 0, err)
        w1 = json.loads(out)
        self.assertEqual(w1["model"], "sonnet")
        self.assertNotIn("worker_token", w1)

        # Leading-dash model rejected
        code, _, err = self._run_cli(["--repo", str(self.repo), "model", "w1", "--", "--bad"])
        self.assertEqual(code, 1)

        # Working state rejected
        with SwarmStore(self.db_path) as store:
            store.claim_runnable_workers()
        code, _, err = self._run_cli(["--repo", str(self.repo), "model", "w1", "opus"])
        self.assertEqual(code, 1)

        # Killed state rejected
        with SwarmStore(self.db_path) as store:
            store.mark_killed("w1")
        code, _, err = self._run_cli(["--repo", str(self.repo), "model", "w1", "opus"])
        self.assertEqual(code, 1)

    def test_edge4_kill_clean_dirty_force_locked_and_unlocked_pid_verification(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])

        # 1. Clean share worktree kill removes worktree & branch and marks killed
        self._run_cli(
            ["--repo", str(self.repo), "add", "wclean", "--brief", "b", "--workspace", "share", "--no-wake"]
        )
        wt_clean = self.swarm_dir / "worktrees" / "wclean"
        self.assertTrue(wt_clean.is_dir())
        code, out, err = self._run_cli(["--repo", str(self.repo), "kill", "wclean", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["state"], "killed")
        self.assertNotIn("worker_token", data)
        self.assertFalse(wt_clean.exists())

        # Killing already-killed without --force fails closed
        code, _, err = self._run_cli(["--repo", str(self.repo), "kill", "wclean"])
        self.assertEqual(code, 1)

        # 2. Dirty share worktree without --force fails closed preserving worktree and state
        self._run_cli(
            ["--repo", str(self.repo), "add", "wdirty", "--brief", "b", "--workspace", "share", "--no-wake"]
        )
        wt_dirty = self.swarm_dir / "worktrees" / "wdirty"
        (wt_dirty / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        code, _, err = self._run_cli(["--repo", str(self.repo), "kill", "wdirty"])
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        self.assertTrue(wt_dirty.exists())
        with SwarmStore(self.db_path) as store:
            w_row = store.get_worker("wdirty")
            assert w_row is not None
            self.assertEqual(w_row["state"], "waiting")

        # Dirty share worktree with --force removes worktree/branch and marks killed
        code, out, err = self._run_cli(["--repo", str(self.repo), "kill", "wdirty", "--force", "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["state"], "killed")
        self.assertFalse(wt_dirty.exists())

        # 3. Already-killed worker with leftover dirty worktree cleaned up by kill --force
        self._run_cli(
            ["--repo", str(self.repo), "add", "wleft", "--brief", "b", "--workspace", "share", "--no-wake"]
        )
        wt_left = self.swarm_dir / "worktrees" / "wleft"
        (wt_left / "untracked.txt").write_text("leftover\n", encoding="utf-8")
        with SwarmStore(self.db_path) as store:
            store.mark_killed("wleft")
        code, out, err = self._run_cli(["--repo", str(self.repo), "kill", "wleft", "--force", "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["state"], "killed")
        self.assertFalse(wt_left.exists())

        # 4. Locked supervisor path: timeout fails closed without force-removing worktree; active supervisor transitions to killed
        self._run_cli(
            ["--repo", str(self.repo), "add", "wlock", "--brief", "b", "--workspace", "share", "--no-wake"]
        )
        wt_lock = self.swarm_dir / "worktrees" / "wlock"
        lock_f = open(self.swarm_dir / "supervisor.lock", "a+", encoding="utf-8")
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with patch("swarmctl.cli._safe_ensure_supervisor", return_value=None):
                code, _, err = self._run_cli(
                    ["--repo", str(self.repo), "kill", "wlock", "--force", "--timeout", "0.1"]
                )
            self.assertEqual(code, 1)
            self.assertTrue(wt_lock.exists())

            # Now simulate supervisor finishing the kill while locked
            def _bg_finish() -> None:
                time.sleep(0.08)
                with SwarmStore(self.db_path) as s2:
                    s2.mark_killed("wlock")

            t = threading.Thread(target=_bg_finish)
            t.start()
            with patch("swarmctl.cli._safe_ensure_supervisor", return_value=None):
                code, out, err = self._run_cli(
                    ["--repo", str(self.repo), "kill", "wlock", "--force", "--timeout", "1.0", "--json"]
                )
            t.join()
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["state"], "killed")
            self.assertFalse(wt_lock.exists())
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            lock_f.close()

        # 5. Unlocked path verifies /proc/<pid>/environ token before signaling
        self._run_cli(["--repo", str(self.repo), "add", "wpid", "--brief", "b", "--no-wake"])
        with SwarmStore(self.db_path) as store:
            w_pid_row = store.get_worker("wpid")
            assert w_pid_row is not None
            real_token = w_pid_row["worker_token"]

        # Spawn a dummy sleeper WITHOUT the worker token -> must refuse to kill recycled PID
        sleeper_bad = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            with SwarmStore(self.db_path) as store:
                store.set_worker_pid("wpid", sleeper_bad.pid)
            code, _, err = self._run_cli(["--repo", str(self.repo), "kill", "wpid"])
            self.assertEqual(code, 1)
            self.assertIsNone(sleeper_bad.poll())
        finally:
            os.killpg(sleeper_bad.pid, signal.SIGKILL)
            sleeper_bad.wait()

        # Spawn a sleeper WITH matching SWARMCTL_WORKER_TOKEN -> unlocked kill terminates it and marks killed
        env_good = {**os.environ, "SWARMCTL_WORKER_TOKEN": real_token}
        sleeper_good = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=env_good,
            start_new_session=True,
        )
        try:
            with SwarmStore(self.db_path) as store:
                store.set_worker_pid("wpid", sleeper_good.pid)
            code, out, err = self._run_cli(["--repo", str(self.repo), "kill", "wpid", "--json"])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["state"], "killed")
            sleeper_good.wait(timeout=2.0)
        finally:
            if sleeper_good.poll() is None:
                try:
                    os.killpg(sleeper_good.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                sleeper_good.wait()

    def test_edge6_post_and_worker_role_auth_and_worktree_repo_discovery(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])
        self._run_cli(
            ["--repo", str(self.repo), "add", "w1", "--brief", "b1", "--workspace", "share", "--no-wake"]
        )
        with SwarmStore(self.db_path) as store:
            w1_row = store.get_worker("w1")
            assert w1_row is not None
            w1_token = w1_row["worker_token"]
            w1_wt = Path(w1_row["workspace_path"])

        # Coordinator post with leading-dash text via --
        code, out, err = self._run_cli(
            ["--repo", str(self.repo), "post", "--no-wake", "--json", "--", "-leading-dash message"]
        )
        self.assertEqual(code, 0, err)
        msg = json.loads(out)
        self.assertEqual(msg["sender"], "coordinator")
        self.assertEqual(msg["body"], "-leading-dash message")

        # Worker-mode repo discovery from inside a subdirectory of .swarm/default/worktrees/w1
        sub_dir = w1_wt / "nested" / "dir"
        sub_dir.mkdir(parents=True)
        self.assertEqual(resolve_repo_root(None, cwd=sub_dir), self.repo)

        worker_env = {
            "SWARMCTL_ROLE": "worker",
            "SWARMCTL_AGENT": "w1",
            "SWARMCTL_WORKER_TOKEN": w1_token,
        }

        # Valid worker post from inside share worktree subdir succeeds and does NOT spawn supervisor
        with patch("swarmctl.cli.ensure_supervisor") as mock_sup:
            code, out, err = self._run_cli(["post", "hello from w1", "--json"], env=worker_env, cwd=sub_dir)
            self.assertEqual(code, 0, err)
            w_msg = json.loads(out)
            self.assertEqual(w_msg["sender"], "w1")
            self.assertEqual(w_msg["body"], "hello from w1")
            mock_sup.assert_not_called()

        # Worker mode spoofing --as coordinator fails closed
        code, _, err = self._run_cli(
            ["post", "--as", "coordinator", "spoof"], env=worker_env, cwd=sub_dir
        )
        self.assertEqual(code, 1)

        # Worker mode missing token fails closed
        code, _, err = self._run_cli(
            ["post", "no token"],
            env={"SWARMCTL_ROLE": "worker", "SWARMCTL_AGENT": "w1"},
            cwd=sub_dir,
        )
        self.assertEqual(code, 1)

        # Forbidden coordinator subcommands in worker mode fail closed
        for forbidden_argv in (
            ["init"],
            ["add", "rogue", "--brief", "x"],
            ["model", "w1", "opus"],
            ["kill", "w1"],
            ["title", "hijack"],
            ["supervise", "--daemon"],
            ["mcp", "--role", "coordinator"],
        ):
            code, _, err = self._run_cli(forbidden_argv, env=worker_env, cwd=sub_dir)
            self.assertEqual(code, 1, f"Expected exit 1 for {forbidden_argv}")

    def test_cuj4_and_edge5_wait_batched_wakeup_and_timeout(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])
        self._run_cli(["--repo", str(self.repo), "add", "w1", "--brief", "b1", "--no-wake"])
        with SwarmStore(self.db_path) as store:
            w1_row = store.get_worker("w1")
            assert w1_row is not None
            w1_token = w1_row["worker_token"]

        # Idle timeout exits 0 with timed_out: true
        code, out, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "wait",
                "--for",
                "coordinator",
                "--since",
                "1",
                "--timeout",
                "0.15",
                "--poll-sec",
                "0.05",
                "--json",
            ]
        )
        self.assertEqual(code, 0, err)
        res_to = json.loads(out)
        self.assertEqual(res_to, {"messages": [], "timed_out": True, "head_seq": 1})

        # timeout == 0 polls once and returns immediately
        code, out, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "wait",
                "--for",
                "coordinator",
                "--since",
                "1",
                "--timeout",
                "0",
                "--json",
            ]
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["timed_out"])

        # Burst > 20 messages (25 noise messages + 1 @coordinator mention at the end)
        def _post_burst() -> None:
            time.sleep(0.08)
            with SwarmStore(self.db_path) as s2:
                for i in range(25):
                    s2.post_message("w1", f"progress update {i}", token=w1_token)
                s2.post_message("w1", "@coordinator finished all 25 items", token=w1_token)

        t = threading.Thread(target=_post_burst)
        t0 = time.monotonic()
        t.start()
        code, out, err = self._run_cli(
            [
                "--repo",
                str(self.repo),
                "wait",
                "--for",
                "coordinator",
                "--since",
                "1",
                "--timeout",
                "3.0",
                "--poll-sec",
                "0.05",
                "--json",
            ]
        )
        elapsed = time.monotonic() - t0
        t.join()
        self.assertEqual(code, 0, err)
        self.assertLess(elapsed, 0.6)
        res_wake = json.loads(out)
        self.assertFalse(res_wake["timed_out"])
        self.assertEqual(len(res_wake["messages"]), 26)
        self.assertEqual(res_wake["head_seq"], 27)
        self.assertIn("@coordinator", res_wake["messages"][-1]["body"])

    def test_cuj4_tail_batched_follow_and_sigint_clean_exit(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])
        with SwarmStore(self.db_path) as store:
            for i in range(25):
                store.post_message("coordinator", f"msg-{i + 1}")

        # Default tail without --since prints last 20 messages (seqs 6..25)
        code, out, err = self._run_cli(["--repo", str(self.repo), "tail"])
        self.assertEqual(code, 0, err)
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 20)
        self.assertTrue(lines[0].startswith("[#6] coordinator: msg-6"))
        self.assertTrue(lines[-1].startswith("[#25] coordinator: msg-25"))

        # tail --since 0 drains all 25 messages
        code, out, err = self._run_cli(["--repo", str(self.repo), "tail", "--since", "0", "--json"])
        self.assertEqual(code, 0, err)
        objs = [json.loads(ln) for ln in out.strip().splitlines() if ln.strip()]
        self.assertEqual(len(objs), 25)
        self.assertEqual(objs[0]["seq"], 1)
        self.assertEqual(objs[-1]["seq"], 25)

        # tail --follow streams new message within <=500ms and exits 0 on SIGINT
        scripts_root = str(Path(__file__).resolve().parents[1])
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys; from swarmctl.cli import main; raise SystemExit(main())",
                "--repo",
                str(self.repo),
                "tail",
                "--since",
                "25",
                "--follow",
                "--poll-sec",
                "0.05",
                "--json",
            ],
            env={**os.environ, "PYTHONPATH": scripts_root},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.1)
            t0 = time.monotonic()
            with SwarmStore(self.db_path) as s2:
                s2.post_message("coordinator", "live streamed message")
            assert proc.stdout is not None
            line = proc.stdout.readline()
            latency = time.monotonic() - t0
            self.assertLess(latency, 0.5)
            streamed = json.loads(line)
            self.assertEqual(streamed["seq"], 26)
            self.assertEqual(streamed["body"], "live streamed message")

            proc.send_signal(signal.SIGINT)
            rc = proc.wait(timeout=2.0)
            self.assertEqual(rc, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()

    def test_supervise_daemon_and_mcp_lazy_import_error(self) -> None:
        self._run_cli(["--repo", str(self.repo), "init"])

        with patch("swarmctl.cli.ensure_supervisor", return_value=4242) as mock_ens:
            code, out, err = self._run_cli(
                ["--repo", str(self.repo), "supervise", "--daemon", "--json"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out), {"pid": 4242, "already_running": False})
            mock_ens.assert_called_once()

        with patch("swarmctl.cli.ensure_supervisor", return_value=None):
            code, out, err = self._run_cli(
                ["--repo", str(self.repo), "supervise", "--daemon", "--json"]
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out), {"pid": None, "already_running": True})

        # mcp lazy-import failure exits 1 cleanly without Python traceback
        code, out, err = self._run_cli(["--repo", str(self.repo), "mcp"])
        self.assertEqual(code, 1)
        self.assertIn("MCP server is not available yet", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
