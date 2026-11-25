from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarmctl import (
    ClaudeAdapter,
    SwarmStore,
    TemplateAdapter,
    TurnRequest,
    TurnResult,
    WorkspaceManager,
    ensure_supervisor,
    format_prompt_delta,
    get_adapter,
    run_supervisor_loop,
)
from swarmctl.supervisor import _is_pid_alive


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


class TestSupervisor(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.swarm_dir = self.root / ".swarm" / "default"
        self.db_path = self.swarm_dir / "board.db"
        self.store = SwarmStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def _make_stub(self, name: str, body: str) -> Path:
        p = self.root / name
        p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        p.chmod(0o755)
        return p

    def test_cuj2_mid_turn_message_preserved_and_max_concurrent_enforced(self) -> None:
        self.store.init_swarm("default", str(self.root), max_concurrent=1, max_turns=10)
        self.store.add_worker("w1", "task 1")
        self.store.add_worker("w2", "task 2")

        log_dir = self.root / "logs"
        log_dir.mkdir()
        flag_file = self.root / "w1_started"
        gate_file = self.root / "w1_release"

        stub = self._make_stub(
            "stub_cuj2.py",
            f"import json, os, sys, time\n"
            f"from pathlib import Path\n"
            f"agent = os.environ['SWARMCTL_AGENT']\n"
            f"delta = sys.stdin.read()\n"
            f"log_dir = Path({str(log_dir)!r})\n"
            f"idx = len(list(log_dir.glob(f'{{agent}}_*.txt')))\n"
            f"(log_dir / f'{{agent}}_{{idx}}.txt').write_text(delta, encoding='utf-8')\n"
            f"if agent == 'w1' and idx == 0:\n"
            f"    Path({str(flag_file)!r}).write_text('1', encoding='utf-8')\n"
            f"    deadline = time.monotonic() + 5.0\n"
            f"    while not Path({str(gate_file)!r}).exists() and time.monotonic() < deadline:\n"
            f"        time.sleep(0.01)\n"
            f"print(json.dumps({{'session_id': f'sid-{{agent}}-{{idx}}', 'result': 'done'}}))\n",
        )
        factory = lambda r: ClaudeAdapter(binary=str(stub))

        mid_turn_obs: dict[str, object] = {}

        def injector() -> None:
            deadline = time.monotonic() + 5.0
            while not flag_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            w1_mid = self.store.get_worker("w1")
            w2_mid = self.store.get_worker("w2")
            mid_turn_obs["w1_state"] = w1_mid["state"] if w1_mid else None
            mid_turn_obs["w1_pid"] = w1_mid["pid"] if w1_mid else None
            mid_turn_obs["w2_state"] = w2_mid["state"] if w2_mid else None
            # Post message #3 mentioning @w1 while w1 is mid-turn
            self.store.post_message("coordinator", "@w1 follow-up #3 mid-turn")
            gate_file.write_text("go", encoding="utf-8")

        t = threading.Thread(target=injector)
        t.start()
        rc = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.05,
            tick_sec=0.01,
            adapter_factory=factory,
        )
        t.join(timeout=5.0)
        self.assertEqual(rc, 0)

        # Verify max_concurrent=1 held w2 in waiting while w1 was working with a recorded PID
        self.assertEqual(mid_turn_obs.get("w1_state"), "working")
        self.assertIsNotNone(mid_turn_obs.get("w1_pid"))
        self.assertEqual(mid_turn_obs.get("w2_state"), "waiting")

        # Verify w1 ran turn 0 on seq=1, then turn 1 on seq=3, and w2 ran turn 0 on seq=2
        w1_turn0 = (log_dir / "w1_0.txt").read_text(encoding="utf-8")
        self.assertIn('seq="1"', w1_turn0)
        self.assertNotIn('seq="3"', w1_turn0)
        w1_turn1 = (log_dir / "w1_1.txt").read_text(encoding="utf-8")
        self.assertIn('seq="3"', w1_turn1)
        self.assertNotIn('seq="1"', w1_turn1)
        self.assertTrue((log_dir / "w2_0.txt").exists())

        # Both workers are now waiting with 0 active PIDs
        w1_final = self.store.get_worker("w1")
        w2_final = self.store.get_worker("w2")
        assert w1_final is not None and w2_final is not None
        self.assertEqual(w1_final["state"], "waiting")
        self.assertIsNone(w1_final["pid"])
        self.assertEqual(w1_final["turn_count"], 2)
        self.assertEqual(w1_final["last_seen_seq"], 3)
        self.assertEqual(w1_final["session_id"], "sid-w1-1")
        self.assertEqual(w2_final["state"], "waiting")
        self.assertIsNone(w2_final["pid"])
        self.assertEqual(w2_final["turn_count"], 1)

    def test_cuj3_fork_session_cleared_and_switch_model_applied(self) -> None:
        self.store.init_swarm("default", str(self.root))
        self.store.add_worker("parent", "parent brief", model="sonnet")

        argv_log = self.root / "argv_log.jsonl"
        stub = self._make_stub(
            "stub_cuj3.py",
            f"import json, os, sys\n"
            f"from pathlib import Path\n"
            f"agent = os.environ['SWARMCTL_AGENT']\n"
            f"_ = sys.stdin.read()\n"
            f"with open({str(argv_log)!r}, 'a', encoding='utf-8') as f:\n"
            f"    f.write(json.dumps({{'agent': agent, 'argv': sys.argv[1:]}}) + '\\n')\n"
            f"print(json.dumps({{'session_id': f'sid-{{agent}}', 'result': 'ok'}}))\n",
        )
        factory = lambda r: ClaudeAdapter(binary=str(stub))

        # Run parent turn 1 -> records session_id='sid-parent'
        run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.03, tick_sec=0.01, adapter_factory=factory)
        parent = self.store.get_worker("parent")
        assert parent is not None
        self.assertEqual(parent["session_id"], "sid-parent")

        # Fork child in same CWD -> turn 1 uses --resume sid-parent --fork-session
        child = self.store.add_worker("child", "forked task", model="sonnet", fork_from="parent")
        self.assertEqual(child["fork_session_id"], "sid-parent")
        run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.03, tick_sec=0.01, adapter_factory=factory)

        child_after1 = self.store.get_worker("child")
        assert child_after1 is not None
        self.assertEqual(child_after1["fork_session_id"], "")
        self.assertEqual(child_after1["session_id"], "sid-child")

        # Switch model on child while waiting, then trigger turn 2
        self.store.switch_model("child", "opus")
        self.store.post_message("coordinator", "@child run turn 2 on opus")
        run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.03, tick_sec=0.01, adapter_factory=factory)

        records = [json.loads(ln) for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        child_runs = [r["argv"] for r in records if r["agent"] == "child"]
        self.assertEqual(len(child_runs), 2)
        # Turn 1 had --resume sid-parent --fork-session and --model sonnet
        self.assertIn("--fork-session", child_runs[0])
        self.assertEqual(child_runs[0][child_runs[0].index("--resume") + 1], "sid-parent")
        self.assertEqual(child_runs[0][child_runs[0].index("--model") + 1], "sonnet")
        # Turn 2 had --resume sid-child, NO --fork-session, and --model opus
        self.assertNotIn("--fork-session", child_runs[1])
        self.assertEqual(child_runs[1][child_runs[1].index("--resume") + 1], "sid-child")
        self.assertEqual(child_runs[1][child_runs[1].index("--model") + 1], "opus")

    def test_edge2_killing_reaps_entire_pgid_and_handles_clean_vs_dirty_worktree(self) -> None:
        # Initialize real git repo for WorkspaceManager share worktrees
        _git(self.root, "init")
        (self.root / "README.md").write_text("hello\n", encoding="utf-8")
        _git(self.root, "add", "README.md")
        _git(self.root, "commit", "-m", "initial")

        self.store.init_swarm("default", str(self.root), max_concurrent=4)
        wm = WorkspaceManager()

        wt_clean, br_clean = wm.create(self.root, self.swarm_dir, "w-clean", "share", swarm_id="default")
        wt_dirty, br_dirty = wm.create(self.root, self.swarm_dir, "w-dirty", "share", swarm_id="default")

        self.store.add_worker(
            "w-clean",
            "clean worktree worker",
            workspace_mode="share",
            workspace_path=str(wt_clean),
            branch_name=br_clean,
        )
        self.store.add_worker(
            "w-dirty",
            "dirty worktree worker",
            workspace_mode="share",
            workspace_path=str(wt_dirty),
            branch_name=br_dirty,
        )

        pids_dir = self.root / "pids"
        pids_dir.mkdir()
        stub = self._make_stub(
            "stub_pgid_trap.py",
            f"import os, signal, subprocess, sys, time\n"
            f"from pathlib import Path\n"
            f"agent = os.environ['SWARMCTL_AGENT']\n"
            f"signal.signal(signal.SIGTERM, lambda *_: None)\n"
            f"if agent == 'w-dirty':\n"
            f"    (Path.cwd() / 'uncommitted.txt').write_text('dirty', encoding='utf-8')\n"
            f"child = subprocess.Popen(\n"
            f"    [sys.executable, '-c', 'import signal, time; signal.signal(signal.SIGTERM, lambda *_: None); '\n"
            f"                           '[(time.sleep(0.2)) for _ in range(300)]']\n"
            f")\n"
            f"(Path({str(pids_dir)!r}) / f'{{agent}}.pids').write_text(f'{{os.getpid()}},{{child.pid}}', encoding='utf-8')\n"
            f"for _ in range(300):\n"
            f"    time.sleep(0.2)\n",
        )
        factory = lambda r: ClaudeAdapter(binary=str(stub))

        def killer() -> None:
            s2 = SwarmStore(self.db_path)
            try:
                deadline = time.monotonic() + 5.0
                while (
                    not (pids_dir / "w-clean.pids").exists() or not (pids_dir / "w-dirty.pids").exists()
                ) and time.monotonic() < deadline:
                    time.sleep(0.01)
                s2.mark_killing("w-clean")
                s2.mark_killing("w-dirty")
            finally:
                s2.close()

        t = threading.Thread(target=killer)
        t.start()
        rc = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.05,
            tick_sec=0.02,
            kill_grace_sec=0.1,
            adapter_factory=factory,
            workspace_manager=wm,
        )
        t.join(timeout=5.0)
        self.assertEqual(rc, 0)

        # Verify both parent and child processes in both PGIDs were completely reaped
        for agent in ("w-clean", "w-dirty"):
            raw = (pids_dir / f"{agent}.pids").read_text(encoding="utf-8")
            parent_pid, child_pid = [int(x) for x in raw.split(",")]
            self.assertFalse(_is_pid_alive(parent_pid))
            self.assertFalse(_is_pid_alive(child_pid))
            w = self.store.get_worker(agent)
            assert w is not None
            self.assertEqual(w["state"], "killed")
            self.assertIsNone(w["pid"])

        # Clean worktree was removed; dirty worktree was preserved with a [dirty-worktree] notice (without @w-dirty)
        self.assertFalse(wt_clean.exists())
        self.assertTrue(wt_dirty.exists())
        self.assertTrue((wt_dirty / "uncommitted.txt").exists())

        msgs = self.store.read_board(since=0, limit=50)["messages"]
        dirty_notices = [m for m in msgs if m["sender"] == "system" and "[dirty-worktree]" in m["body"]]
        self.assertEqual(len(dirty_notices), 1)
        self.assertIn("w-dirty", dirty_notices[0]["body"])
        self.assertEqual(dirty_notices[0]["mentions"], [])

    def test_edge2_crash_recovery_orphan_dead_pid_and_adapter_permission_error(self) -> None:
        self.store.init_swarm("default", str(self.root), max_concurrent=4)

        # 1) Non-zero exit worker
        self.store.add_worker("w-crash", "will exit 2")
        # 2) Unmapped permission mode on opencode (readonly -> PermissionError)
        self.store.add_worker("w-perm", "opencode readonly", runner="opencode", permission_mode="readonly")
        # 3) Orphan dead PID already in working state
        self.store.add_worker("w-orphan", "orphan task")
        with self.store._write_tx() as conn:
            conn.execute("UPDATE workers SET state = 'working', pid = 999999 WHERE name = 'w-orphan'")

        crash_stub = self._make_stub(
            "stub_crash.py",
            "import sys\nsys.stderr.write('fatal crash\\n')\nsys.exit(2)\n",
        )

        def factory(runner: str) -> object:
            if runner == "claude":
                return ClaudeAdapter(binary=str(crash_stub))
            return get_adapter(runner)

        # Run supervisor until idle; none of the 3 workers should crash-loop
        rc = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.05,
            tick_sec=0.01,
            adapter_factory=factory,
        )
        self.assertEqual(rc, 0)

        head_seq = self.store.read_board(limit=0)["head_seq"]
        for name, expected_err_substr in [
            ("w-crash", "fatal crash"),
            ("w-perm", "does not support enforced 'readonly' guardrails"),
            ("w-orphan", "Orphan worker PID 999999 died unexpectedly"),
        ]:
            w = self.store.get_worker(name)
            assert w is not None
            self.assertEqual(w["state"], "stopped")
            self.assertIsNone(w["pid"])
            self.assertEqual(w["turn_count"], 1)
            self.assertEqual(w["last_seen_seq"], head_seq)
            self.assertIn(expected_err_substr, w["last_error"])

    def test_edge2_flock_exclusivity_ensure_supervisor_and_unlock_check_relock(self) -> None:
        self.store.init_swarm("default", str(self.root))
        lock_path = self.swarm_dir / "supervisor.lock"

        # 1) When lock is already held exclusively, run_supervisor_loop returns 0 immediately
        #    and ensure_supervisor returns None
        with open(lock_path, "a+", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.01, tick_sec=0.01), 0)
            self.assertIsNone(ensure_supervisor(self.swarm_dir, idle_timeout_sec=0.05, tick_sec=0.01))
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

        # 2) When unlocked, ensure_supervisor spawns a detached supervisor that acquires the lock and exits after idle
        pid = ensure_supervisor(self.swarm_dir, idle_timeout_sec=0.05, tick_sec=0.01)
        self.assertIsNotNone(pid)
        assert pid is not None and pid > 0
        deadline = time.monotonic() + 5.0
        while _is_pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(_is_pid_alive(pid))
        # supervisor.lock is NEVER unlinked
        self.assertTrue(lock_path.exists())

        # 3) Unlock-check-relock race hook: inject work inside on_before_unlock_check
        self.store.add_worker("w1", "initial task")
        stub = self._make_stub(
            "stub_race.py",
            "import json, sys\n_ = sys.stdin.read()\nprint(json.dumps({'session_id': 's1', 'result': 'ok'}))\n",
        )
        factory = lambda r: ClaudeAdapter(binary=str(stub))

        hook_fired = {"count": 0}

        def race_hook() -> None:
            if hook_fired["count"] == 0:
                hook_fired["count"] += 1
                self.store.post_message("coordinator", "@w1 arrived right after unlock")

        rc = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.02,
            tick_sec=0.01,
            adapter_factory=factory,
            on_before_unlock_check=race_hook,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(hook_fired["count"], 1)
        w1 = self.store.get_worker("w1")
        assert w1 is not None
        # Turn 1 processed initial brief (#1), Turn 2 processed race message (#2) after relocking!
        self.assertEqual(w1["turn_count"], 2)
        self.assertEqual(w1["state"], "waiting")

    def test_edge3_self_mention_ignored_timeout_and_max_turns_circuit_breakers(self) -> None:
        self.store.init_swarm("default", str(self.root), max_concurrent=4, max_turns=2)
        w_self = self.store.add_worker("w-self", "post self mention")
        self.store.add_worker("w-timeout", "will timeout")
        self.store.add_worker("w-max", "will reach max_turns=2")

        stub = self._make_stub(
            "stub_edge3.py",
            "import json, os, sys, time\n"
            "_ = sys.stdin.read()\n"
            "agent = os.environ['SWARMCTL_AGENT']\n"
            "if agent == 'w-timeout':\n"
            "    time.sleep(30)\n"
            "print(json.dumps({'session_id': f'sid-{agent}', 'result': 'ok'}))\n",
        )
        factory = lambda r: ClaudeAdapter(binary=str(stub))

        # Run tick until initial turns finish / timeout
        rc = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.05,
            tick_sec=0.02,
            turn_timeout_sec=0.1,
            kill_grace_sec=0.05,
            adapter_factory=factory,
        )
        self.assertEqual(rc, 0)

        # 1) Self-mention by w-self (@w-self) must NOT wake w-self
        self.store.post_message("w-self", "@w-self note to self", token=w_self["worker_token"])
        # Verify w-self also ignores its own @all post by temporarily keeping w-timeout/w-max out of @all or testing w-self in isolation:
        # Trigger w-max's 2nd turn so w-max hits max_turns=2
        self.store.post_message("coordinator", "@w-max second turn to hit max_turns")

        rc2 = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.05,
            tick_sec=0.02,
            turn_timeout_sec=0.5,
            kill_grace_sec=0.05,
            adapter_factory=factory,
        )
        self.assertEqual(rc2, 0)

        # w-self stayed at turn_count == 1
        w_self_row = self.store.get_worker("w-self")
        assert w_self_row is not None
        self.assertEqual(w_self_row["turn_count"], 1)
        self.assertEqual(w_self_row["state"], "waiting")

        # w-timeout halted at turn_count == 1 in state 'stopped'
        w_to_row = self.store.get_worker("w-timeout")
        assert w_to_row is not None
        self.assertEqual(w_to_row["state"], "stopped")
        self.assertIsNone(w_to_row["pid"])
        self.assertEqual(w_to_row["turn_count"], 1)
        self.assertIn("Turn exceeded timeout", w_to_row["last_error"])

        # w-max halted at turn_count == 2 (never 3!) in state 'stopped'
        w_max_row = self.store.get_worker("w-max")
        assert w_max_row is not None
        self.assertEqual(w_max_row["state"], "stopped")
        self.assertIsNone(w_max_row["pid"])
        self.assertEqual(w_max_row["turn_count"], 2)
        self.assertIn("Reached max_turns (2)", w_max_row["last_error"])

        # Both circuit-breaker system notices were posted without @mentions
        msgs = self.store.read_board(since=0, limit=50)["messages"]
        cb_msgs = [m for m in msgs if m["sender"] == "system" and "[circuit-breaker]" in m["body"]]
        self.assertEqual(len(cb_msgs), 2)
        bodies = "\n".join(m["body"] for m in cb_msgs)
        self.assertIn("worker w-timeout halted: turn exceeded timeout", bodies)
        self.assertIn("worker w-max halted: reached max_turns (2)", bodies)
        for m in cb_msgs:
            self.assertEqual(m["mentions"], [])

        # Also verify w-self posting @all does not wake w-self itself
        self.store.mark_killing("w-timeout")
        self.store.mark_killed("w-timeout")
        self.store.post_message("w-self", "@all broadcast from w-self", token=w_self["worker_token"])
        run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.03,
            tick_sec=0.01,
            adapter_factory=factory,
        )
        w_self_after_all = self.store.get_worker("w-self")
        assert w_self_after_all is not None
        self.assertEqual(w_self_after_all["turn_count"], 1)


if __name__ == "__main__":
    unittest.main()
