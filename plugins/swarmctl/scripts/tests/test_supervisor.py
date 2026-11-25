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
from swarmctl.supervisor import _is_pgid_alive, _is_pid_alive, _reap_pgid_step


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

    def test_cuj2_mid_turn_message_preserved_template_adapter_and_max_concurrent_enforced(self) -> None:
        self.store.init_swarm("default", str(self.root), max_concurrent=1, max_turns=10)
        self.store.add_worker("w1", "task 1")
        # w2 uses TemplateAdapter ("custom") in unsafe mode to exercise TemplateAdapter via supervisor
        self.store.add_worker("w2", "task 2", runner="custom", permission_mode="unsafe")

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
        old_custom = os.environ.get("SWARMCTL_CUSTOM_CMD")
        os.environ["SWARMCTL_CUSTOM_CMD"] = str(stub)
        try:
            def factory(runner: str) -> object:
                if runner == "claude":
                    return ClaudeAdapter(binary=str(stub))
                return get_adapter(runner)

            mid_turn_obs: dict[str, object] = {}

            def injector() -> None:
                s2 = SwarmStore(self.db_path)
                try:
                    deadline = time.monotonic() + 5.0
                    while not flag_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    w1_mid = s2.get_worker("w1")
                    w2_mid = s2.get_worker("w2")
                    mid_turn_obs["w1_state"] = w1_mid["state"] if w1_mid else None
                    mid_turn_obs["w1_pid"] = w1_mid["pid"] if w1_mid else None
                    mid_turn_obs["w2_state"] = w2_mid["state"] if w2_mid else None
                    s2.post_message("coordinator", "@w1 follow-up #3 mid-turn")
                    gate_file.write_text("go", encoding="utf-8")
                finally:
                    s2.close()

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
        finally:
            if old_custom is None:
                os.environ.pop("SWARMCTL_CUSTOM_CMD", None)
            else:
                os.environ["SWARMCTL_CUSTOM_CMD"] = old_custom

        self.assertEqual(mid_turn_obs.get("w1_state"), "working")
        self.assertIsNotNone(mid_turn_obs.get("w1_pid"))
        self.assertEqual(mid_turn_obs.get("w2_state"), "waiting")

        w1_turn0 = (log_dir / "w1_0.txt").read_text(encoding="utf-8")
        self.assertIn('seq="1"', w1_turn0)
        self.assertNotIn('seq="3"', w1_turn0)
        w1_turn1 = (log_dir / "w1_1.txt").read_text(encoding="utf-8")
        self.assertIn('seq="3"', w1_turn1)
        self.assertNotIn('seq="1"', w1_turn1)
        self.assertTrue((log_dir / "w2_0.txt").exists())

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

    def test_cuj3_fork_session_cross_cwd_seed_and_switch_model_applied(self) -> None:
        self.store.init_swarm("default", str(self.root))
        self.store.add_worker("parent", "parent brief", model="sonnet")

        argv_log = self.root / "argv_log.jsonl"
        stub = self._make_stub(
            "stub_cuj3.py",
            f"import json, os, sys\n"
            f"from pathlib import Path\n"
            f"agent = os.environ['SWARMCTL_AGENT']\n"
            f"delta = sys.stdin.read()\n"
            f"with open({str(argv_log)!r}, 'a', encoding='utf-8') as f:\n"
            f"    f.write(json.dumps({{'agent': agent, 'argv': sys.argv[1:], 'has_seed': '<transcript_seed>\\n' in delta}}) + '\\n')\n"
            f"print(json.dumps({{'session_id': f'sid-{{agent}}', 'result': 'ok'}}))\n",
        )
        factory = lambda r: ClaudeAdapter(binary=str(stub))

        # Run parent turn 1 -> records session_id='sid-parent'
        run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.03, tick_sec=0.01, adapter_factory=factory)
        parent = self.store.get_worker("parent")
        assert parent is not None
        self.assertEqual(parent["session_id"], "sid-parent")

        # 1) Same-CWD fork -> uses --resume sid-parent --fork-session, no <transcript_seed>
        child = self.store.add_worker("child", "forked task", model="sonnet", fork_from="parent")
        self.assertEqual(child["fork_session_id"], "sid-parent")
        self.assertEqual(child["transcript_seed"], "")

        # 2) Cross-CWD share fork -> uses <transcript_seed>, no --fork-session, cleared after turn 1
        cross_dir = self.root / "share-cross"
        cross_dir.mkdir()
        child_cross = self.store.add_worker(
            "child-cross", "cross task", workspace_mode="share", workspace_path=str(cross_dir), fork_from="parent"
        )
        self.assertEqual(child_cross["fork_session_id"], "")
        self.assertTrue(child_cross["transcript_seed"])

        run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.03, tick_sec=0.01, adapter_factory=factory)

        child_after1 = self.store.get_worker("child")
        cross_after1 = self.store.get_worker("child-cross")
        assert child_after1 is not None and cross_after1 is not None
        self.assertEqual(child_after1["fork_session_id"], "")
        self.assertEqual(child_after1["session_id"], "sid-child")
        self.assertEqual(cross_after1["transcript_seed"], "")

        # Switch model on child while waiting, then trigger turn 2
        self.store.switch_model("child", "opus")
        self.store.post_message("coordinator", "@child @child-cross run turn 2")
        run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.03, tick_sec=0.01, adapter_factory=factory)

        records = [json.loads(ln) for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        child_runs = [r for r in records if r["agent"] == "child"]
        cross_runs = [r for r in records if r["agent"] == "child-cross"]
        self.assertEqual(len(child_runs), 2)
        self.assertEqual(len(cross_runs), 2)

        # Same-CWD turn 1 vs turn 2
        self.assertIn("--fork-session", child_runs[0]["argv"])
        self.assertFalse(child_runs[0]["has_seed"])
        self.assertEqual(child_runs[0]["argv"][child_runs[0]["argv"].index("--model") + 1], "sonnet")
        self.assertNotIn("--fork-session", child_runs[1]["argv"])
        self.assertEqual(child_runs[1]["argv"][child_runs[1]["argv"].index("--model") + 1], "opus")

        # Cross-CWD turn 1 injected <transcript_seed>; turn 2 did not
        self.assertNotIn("--fork-session", cross_runs[0]["argv"])
        self.assertTrue(cross_runs[0]["has_seed"])
        self.assertFalse(cross_runs[1]["has_seed"])

    def test_edge2_killing_reaps_entire_pgid_orphan_killing_and_clean_vs_dirty_worktree(self) -> None:
        _git(self.root, "init")
        (self.root / "README.md").write_text("hello\n", encoding="utf-8")
        _git(self.root, "add", "README.md")
        _git(self.root, "commit", "-m", "initial")

        self.store.init_swarm("default", str(self.root), max_concurrent=4)
        wm = WorkspaceManager()

        wt_clean, br_clean = wm.create(self.root, self.swarm_dir, "w-clean", "share", swarm_id="default")
        wt_dirty, br_dirty = wm.create(self.root, self.swarm_dir, "w-dirty", "share", swarm_id="default")

        self.store.add_worker(
            "w-clean", "clean worktree worker", workspace_mode="share", workspace_path=str(wt_clean), branch_name=br_clean
        )
        self.store.add_worker(
            "w-dirty", "dirty worktree worker", workspace_mode="share", workspace_path=str(wt_dirty), branch_name=br_dirty
        )
        # Also test Step 1 orphan 'killing' worker (not in active, with a real detached PGID)
        orphan_proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        self.store.add_worker("w-orphan-kill", "orphan killing worker")
        with self.store._write_tx() as conn:
            conn.execute(
                "UPDATE workers SET state = 'killing', pid = ? WHERE name = 'w-orphan-kill'",
                (orphan_proc.pid,),
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

        # Reap our local Popen handle for orphan_proc
        orphan_proc.poll()
        self.assertFalse(_is_pid_alive(orphan_proc.pid))
        w_ok = self.store.get_worker("w-orphan-kill")
        assert w_ok is not None
        self.assertEqual(w_ok["state"], "killed")
        self.assertIsNone(w_ok["pid"])

        for agent in ("w-clean", "w-dirty"):
            raw = (pids_dir / f"{agent}.pids").read_text(encoding="utf-8")
            parent_pid, child_pid = [int(x) for x in raw.split(",")]
            self.assertFalse(_is_pid_alive(parent_pid))
            self.assertFalse(_is_pid_alive(child_pid))
            w = self.store.get_worker(agent)
            assert w is not None
            self.assertEqual(w["state"], "killed")
            self.assertIsNone(w["pid"])

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

        self.store.add_worker("w-crash", "will exit 2")
        self.store.add_worker("w-perm", "opencode readonly", runner="opencode", permission_mode="readonly")

        # Freshly exited subprocess PID instead of hardcoded 999999
        dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
        dead_proc.wait(timeout=5.0)
        dead_pid = dead_proc.pid

        self.store.add_worker("w-orphan", "orphan task")
        with self.store._write_tx() as conn:
            conn.execute("UPDATE workers SET state = 'working', pid = ? WHERE name = 'w-orphan'", (dead_pid,))

        crash_stub = self._make_stub(
            "stub_crash.py",
            "import sys\nsys.stderr.write('fatal crash\\n')\nsys.exit(2)\n",
        )

        def factory(runner: str) -> object:
            if runner == "claude":
                return ClaudeAdapter(binary=str(crash_stub))
            return get_adapter(runner)

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
            ("w-orphan", f"Orphan worker PID {dead_pid} died unexpectedly"),
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

        # 1) When lock is held exclusively, run_supervisor_loop returns 0 and ensure_supervisor returns None
        with open(lock_path, "a+", encoding="utf-8") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(run_supervisor_loop(self.swarm_dir, idle_timeout_sec=0.01, tick_sec=0.01), 0)
            self.assertIsNone(ensure_supervisor(self.swarm_dir, idle_timeout_sec=0.05, tick_sec=0.01))
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)

        # 2) Queue real work for a custom runner and verify ensure_supervisor's detached daemon processes it
        stub = self._make_stub(
            "stub_daemon.py",
            "import json, sys\n_ = sys.stdin.read()\nprint(json.dumps({'session_id': 's-daemon', 'result': 'ok'}))\n",
        )
        old_custom = os.environ.get("SWARMCTL_CUSTOM_CMD")
        os.environ["SWARMCTL_CUSTOM_CMD"] = str(stub)
        try:
            self.store.add_worker("w-daemon", "daemon task", runner="custom", permission_mode="unsafe")
            pid = ensure_supervisor(self.swarm_dir, idle_timeout_sec=0.05, tick_sec=0.01)
            self.assertIsNotNone(pid)
            assert pid is not None and pid > 0
            deadline = time.monotonic() + 5.0
            while _is_pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(_is_pid_alive(pid))
            self.assertTrue(lock_path.exists())
            w_daemon = self.store.get_worker("w-daemon")
            assert w_daemon is not None
            self.assertEqual(w_daemon["turn_count"], 1)
            self.assertEqual(w_daemon["state"], "waiting")
        finally:
            if old_custom is None:
                os.environ.pop("SWARMCTL_CUSTOM_CMD", None)
            else:
                os.environ["SWARMCTL_CUSTOM_CMD"] = old_custom

        # 3) Verify `python3 -m swarmctl.supervisor --help` emits zero runpy RuntimeWarnings on stderr (N10)
        scripts_root = str(Path(__file__).resolve().parents[1])
        env = {**os.environ, "PYTHONPATH": scripts_root}
        help_res = subprocess.run(
            [sys.executable, "-m", "swarmctl.supervisor", "--help"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(help_res.stderr, "")

        # 4) Unlock-check-relock race hook
        self.store.add_worker("w1", "initial task")
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

        rc = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.05,
            tick_sec=0.02,
            turn_timeout_sec=0.1,
            kill_grace_sec=0.05,
            adapter_factory=factory,
        )
        self.assertEqual(rc, 0)

        self.store.post_message("w-self", "@w-self note to self", token=w_self["worker_token"])
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

        w_self_row = self.store.get_worker("w-self")
        assert w_self_row is not None
        self.assertEqual(w_self_row["turn_count"], 1)
        self.assertEqual(w_self_row["state"], "waiting")

        w_to_row = self.store.get_worker("w-timeout")
        assert w_to_row is not None
        self.assertEqual(w_to_row["state"], "stopped")
        self.assertIsNone(w_to_row["pid"])
        self.assertEqual(w_to_row["turn_count"], 1)
        self.assertIn("Turn exceeded timeout", w_to_row["last_error"])

        w_max_row = self.store.get_worker("w-max")
        assert w_max_row is not None
        self.assertEqual(w_max_row["state"], "stopped")
        self.assertIsNone(w_max_row["pid"])
        self.assertEqual(w_max_row["turn_count"], 2)
        self.assertIn("Reached max_turns (2)", w_max_row["last_error"])

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

    def test_regressions_pgid_nonleader_external_killed_and_poll_before_timeout(self) -> None:
        # H1: When proc is None and PID is a live non-leader process in our own PGID (so killpg(pid, 0)
        # raises ProcessLookupError while kill(pid, 0) succeeds), _is_pgid_alive returns False (no livelock).
        non_leader = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            self.assertNotEqual(os.getpgid(non_leader.pid), non_leader.pid)
            self.assertFalse(_is_pgid_alive(non_leader.pid, None))
            dead, _ = _reap_pgid_step(non_leader.pid, None, None, time.monotonic(), 0.1)
            self.assertTrue(dead)
        finally:
            non_leader.terminate()
            non_leader.wait(timeout=5.0)

        # M4 & M5:
        # - w-fast exits 0 immediately even with turn_timeout_sec=0.001, and because proc.poll() is checked
        #   before timeout when tick runs, it completes cleanly (state='waiting') rather than timing out.
        # - w-ext-killed is marked 'killed' externally while active, and supervisor reaps it & exits cleanly.
        self.store.init_swarm("default", str(self.root), max_concurrent=4)
        self.store.add_worker("w-fast", "fast worker")
        self.store.add_worker("w-ext-killed", "externally killed worker")

        ext_flag = self.root / "ext_started"
        stub = self._make_stub(
            "stub_reg.py",
            f"import json, os, sys, time\n"
            f"from pathlib import Path\n"
            f"_ = sys.stdin.read()\n"
            f"agent = os.environ['SWARMCTL_AGENT']\n"
            f"if agent == 'w-ext-killed':\n"
            f"    Path({str(ext_flag)!r}).write_text('1', encoding='utf-8')\n"
            f"    time.sleep(30)\n"
            f"print(json.dumps({{'session_id': f'sid-{{agent}}', 'result': 'ok'}}))\n",
        )
        factory = lambda r: ClaudeAdapter(binary=str(stub))

        def ext_killer() -> None:
            s2 = SwarmStore(self.db_path)
            try:
                deadline = time.monotonic() + 5.0
                while not ext_flag.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                # Directly mark killed (skipping killing) to test M4 Step 3 external killed cleanup
                s2.mark_killed("w-ext-killed")
            finally:
                s2.close()

        t = threading.Thread(target=ext_killer)
        t.start()
        rc = run_supervisor_loop(
            self.swarm_dir,
            idle_timeout_sec=0.05,
            tick_sec=0.05,
            turn_timeout_sec=0.04,
            kill_grace_sec=0.02,
            adapter_factory=factory,
        )
        t.join(timeout=5.0)
        self.assertEqual(rc, 0)

        w_fast = self.store.get_worker("w-fast")
        w_ext = self.store.get_worker("w-ext-killed")
        assert w_fast is not None and w_ext is not None
        self.assertEqual(w_fast["state"], "waiting")
        self.assertEqual(w_fast["turn_count"], 1)
        self.assertEqual(w_ext["state"], "killed")


if __name__ == "__main__":
    unittest.main()
