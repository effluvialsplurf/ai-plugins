from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarmctl import SwarmStore, parse_mentions, validate_ident


class TestSwarmStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / ".swarm" / "default" / "board.db"
        self.store = SwarmStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_validate_ident_and_parse_mentions(self) -> None:
        self.assertEqual(validate_ident("default", "swarm"), "default")
        self.assertEqual(validate_ident("s_1-a", "swarm"), "s_1-a")
        self.assertEqual(validate_ident("worker-1", "worker"), "worker-1")

        for bad_swarm in ["", "../evil", "UPPER", "-start", "_start", "a" * 33, "bad/id", "default\n", "s1\r\n"]:
            with self.assertRaises(ValueError, msg=f"expected failure for {bad_swarm!r}"):
                validate_ident(bad_swarm, "swarm")

        for bad_worker in [
            "", "../evil", "UPPER", "-w", "a" * 25, "all", "coordinator", "system",
            "w1\n", "coordinator\n", "all\n", "system\n",
        ]:
            with self.assertRaises(ValueError, msg=f"expected failure for {bad_worker!r}"):
                validate_ident(bad_worker, "worker")

        with self.assertRaises(ValueError):
            validate_ident("valid", "unknown_kind")

        mentions = parse_mentions("hi @worker-1, email user@example.com, @all and @worker-1 again (@UPPER ignored)")
        self.assertEqual(mentions, ["worker-1", "all"])

    def test_init_add_worker_and_read_board_modes(self) -> None:
        with self.assertRaises(RuntimeError):
            self.store.get_meta()

        with self.assertRaises(ValueError):
            self.store.init_swarm("default", str(self.root), max_concurrent=0)
        with self.assertRaises(ValueError):
            self.store.init_swarm("default", str(self.root), max_turns=0)

        meta = self.store.init_swarm("default", str(self.root), title="Test Swarm")
        self.assertEqual(meta["swarm_id"], "default")
        self.assertEqual(meta["title"], "Test Swarm")

        # Idempotent re-init on same swarm_id updates title/default_model
        meta2 = self.store.init_swarm("default", str(self.root), title="", default_model="sonnet")
        self.assertEqual(meta2["title"], "Test Swarm")
        self.assertEqual(meta2["default_model"], "sonnet")

        with self.assertRaises(ValueError):
            self.store.init_swarm("other", str(self.root))

        updated = self.store.set_title("Renamed Swarm")
        self.assertEqual(updated["title"], "Renamed Swarm")

        w1 = self.store.add_worker("w1", "do task")
        self.assertEqual(w1["name"], "w1")
        self.assertEqual(w1["state"], "waiting")
        self.assertEqual(w1["permission_mode"], "readonly")
        self.assertEqual(w1["workspace_mode"], "inherit")
        self.assertEqual(w1["workspace_path"], str(self.root))
        self.assertEqual(w1["brief_seq"], 1)
        self.assertTrue(w1["worker_token"])

        # share mode requires non-empty workspace_path; invalid sender or duplicate worker rolls back cleanly
        with self.assertRaises(ValueError):
            self.store.add_worker("w-share", "share task", workspace_mode="share", workspace_path="")
        with self.assertRaises(ValueError):
            self.store.add_worker("w-bad-sender", "task", sender="w-bad-sender")
        with self.assertRaises(ValueError):
            self.store.add_worker("w-bad-fork", "task", fork_from="nonexistent")
        with self.assertRaises(ValueError):
            self.store.add_worker("w1", "duplicate active worker")
        self.assertEqual(len(self.store.list_workers()), 1)
        self.assertEqual(self.store.read_board()["head_seq"], 1)

        p2 = self.store.post_message("coordinator", "@w1 follow up")
        p3 = self.store.post_message("human", "general note @all")
        self.assertEqual((p2["seq"], p3["seq"]), (2, 3))

        # Default read_board: newest limit in ascending seq order
        res_all = self.store.read_board(limit=2)
        self.assertEqual(res_all["head_seq"], 3)
        self.assertEqual([m["seq"] for m in res_all["messages"]], [2, 3])
        self.assertEqual(res_all["messages"][0]["mentions"], ["w1"])

        # since mode: oldest after since
        res_since = self.store.read_board(since=1, limit=1)
        self.assertEqual([m["seq"] for m in res_since["messages"]], [2])

        # seqs mode: accepts both lists and single-pass generators/iterators
        res_seqs = self.store.read_board(seqs=(s for s in [3, 1, 99]), since=2, limit=1)
        self.assertEqual([m["seq"] for m in res_seqs["messages"]], [1, 3])

        # status mode: never exposes worker_token
        res_status = self.store.read_board(status=True)
        self.assertEqual(res_status["swarm_id"], "default")
        self.assertEqual(res_status["title"], "Renamed Swarm")
        self.assertEqual(res_status["head_seq"], 3)
        self.assertEqual(len(res_status["workers"]), 1)
        self.assertNotIn("worker_token", res_status["workers"][0])
        self.assertNotIn("worker_token", self.store.list_workers()[0])

    def test_concurrent_16_threads_wal_writes_and_clean_close(self) -> None:
        self.store.init_swarm("default", str(self.root))
        w1 = self.store.add_worker("w1", "initial brief")
        token = w1["worker_token"]

        errors: list[Exception] = []
        barrier = threading.Barrier(16)

        def worker_fn(idx: int) -> None:
            try:
                barrier.wait(timeout=5.0)
                for j in range(5):
                    if idx % 2 == 0:
                        self.store.post_message("coordinator", f"coord-{idx}-{j} @w1")
                    else:
                        self.store.post_message("w1", f"w1-{idx}-{j} @coordinator", token=token)
                    snap = self.store.read_board(limit=5)
                    for m in snap["messages"]:
                        if m["seq"] > snap["head_seq"]:
                            raise AssertionError(f"Snapshot inversion: seq {m['seq']} > head {snap['head_seq']}")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker_fn, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        self.assertEqual(errors, [])
        board = self.store.read_board(since=0, limit=200)
        self.assertEqual(board["head_seq"], 81)
        self.assertEqual([m["seq"] for m in board["messages"]], list(range(1, 82)))

        # Verify all worker-thread connections were tracked and close cleanly from main thread (H1)
        tracked_conns = list(self.store._conns)
        self.assertGreaterEqual(len(tracked_conns), 17)
        self.store.close()
        for c in tracked_conns:
            with self.assertRaises(sqlite3.ProgrammingError):
                c.execute("SELECT 1")

    def test_token_auth_and_anti_spoofing(self) -> None:
        self.store.init_swarm("default", str(self.root))
        w1 = self.store.add_worker("w1", "task 1")
        w2 = self.store.add_worker("w2", "task 2")

        msg = self.store.post_message("w1", "hello @coordinator", token=w1["worker_token"])
        self.assertEqual(msg["sender"], "w1")

        with self.assertRaises(PermissionError):
            self.store.post_message("w2", "spoof w2", token=w1["worker_token"])
        with self.assertRaises(PermissionError):
            self.store.post_message("coordinator", "spoof coord", token=w1["worker_token"])
        with self.assertRaises(PermissionError):
            self.store.post_message("w1", "bad token", token="invalid-token")
        with self.assertRaises(PermissionError):
            self.store.post_message("w1", "no token", token=None)
        with self.assertRaises(ValueError):
            self.store.post_message("stranger", "hello", token=None)
        with self.assertRaises(ValueError):
            self.store.post_message("coordinator", "   ")

        k_ing = self.store.mark_killing("w2")
        k_ed = self.store.mark_killed("w2")
        self.assertNotIn("worker_token", k_ing)
        self.assertNotIn("worker_token", k_ed)
        with self.assertRaises(PermissionError):
            self.store.post_message("w2", "ghost post", token=w2["worker_token"])

    def test_claim_runnable_and_mid_turn_delivery(self) -> None:
        self.store.init_swarm("default", str(self.root), max_concurrent=1, max_turns=2)
        w1 = self.store.add_worker("w1", "brief 1")

        claimed = self.store.claim_runnable_workers()
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["name"], "w1")
        self.assertEqual(claimed[0]["state"], "working")
        self.assertEqual(claimed[0]["delivered_max_seq"], 1)

        w2 = self.store.add_worker("w2", "brief 2")
        self.assertEqual(self.store.claim_runnable_workers(), [])

        # Mid-turn message #3 arrives for w1 while w1 is working on delivered_max_seq=1
        self.store.post_message("coordinator", "@w1 mid-turn update")
        self.store.post_message("w1", "@all @w1 my interim note", token=w1["worker_token"])

        done1 = self.store.complete_turn("w1", delivered_max_seq=1, session_id="sess-1")
        self.assertNotIn("worker_token", done1)
        self.assertEqual(done1["state"], "waiting")
        self.assertEqual(done1["last_seen_seq"], 1)
        self.assertEqual(done1["turn_count"], 1)
        self.assertEqual(done1["session_id"], "sess-1")

        delta = self.store.get_unread_delta("w1", up_to_seq=3)
        self.assertEqual([m["seq"] for m in delta], [2, 3])

        claimed2 = self.store.claim_runnable_workers()
        self.assertEqual([w["name"] for w in claimed2], ["w2"])
        self.assertEqual(claimed2[0]["delivered_max_seq"], 4)

        # Transitioning w2 to killing still counts against max_concurrent=1
        self.store.mark_killing("w2")
        self.assertEqual(self.store.claim_runnable_workers(), [])
        self.store.mark_killed("w2")

        # Now slot is free -> w1 claims up to seq 4
        claimed3 = self.store.claim_runnable_workers()
        self.assertEqual([w["name"] for w in claimed3], ["w1"])
        self.assertEqual(claimed3[0]["delivered_max_seq"], 4)
        self.store.complete_turn("w1", delivered_max_seq=4)

        # w1 now has turn_count == 2 == max_turns; new mention #5 must not claim w1
        self.store.post_message("coordinator", "@w1 after max turns")
        self.assertEqual(self.store.claim_runnable_workers(), [])

    def test_lifecycle_guards_and_hybrid_fork(self) -> None:
        self.store.init_swarm("default", str(self.root))
        parent = self.store.add_worker("parent", "investigate auth")
        self.store.set_worker_pid("parent", 12345)
        self.assertEqual(self.store.get_worker("parent")["pid"], 12345)

        c = self.store.claim_runnable_workers()
        self.assertEqual(len(c), 1)
        self.store.complete_turn("parent", delivered_max_seq=c[0]["delivered_max_seq"], session_id="claude-sid-99")

        # Same-CWD claude fork -> sets fork_session_id, empty transcript_seed
        child_same = self.store.add_worker("child-same", "continue auth", fork_from="parent")
        self.assertEqual(child_same["fork_session_id"], "claude-sid-99")
        self.assertEqual(child_same["transcript_seed"], "")

        c_child = self.store.claim_runnable_workers(limit=1)
        self.assertEqual(c_child[0]["name"], "child-same")
        after_turn = self.store.complete_turn("child-same", delivered_max_seq=c_child[0]["delivered_max_seq"])
        self.assertEqual(after_turn["fork_session_id"], "")

        # Cross-CWD fork + oversized multibyte message -> UTF-8 safe transcript_seed <= 4096B, cleared after turn 1
        big_body = "@parent " + ("é" * 3000)
        self.store.post_message("coordinator", big_body)
        other_dir = self.root / "worktree-child"
        other_dir.mkdir()
        child_cross = self.store.add_worker(
            "child-cross",
            "verify auth",
            workspace_mode="share",
            workspace_path=str(other_dir),
            fork_from="parent",
        )
        self.assertEqual(child_cross["fork_session_id"], "")
        seed_bytes = child_cross["transcript_seed"].encode("utf-8")
        self.assertGreater(len(seed_bytes), 0)
        self.assertLessEqual(len(seed_bytes), 4096)
        self.assertIn("=== Initial Brief ===", child_cross["transcript_seed"])
        self.assertEqual(self.store.get_transcript_seed("parent", max_bytes=-5), "")

        # Coordinator fork also populates transcript_seed; unknown fork_from fails
        child_coord = self.store.add_worker("child-coord", "help coord", fork_from="coordinator")
        self.assertTrue(child_coord["transcript_seed"].startswith("=== Initial Brief ==="))
        with self.assertRaises(ValueError):
            self.store.add_worker("child-bad", "bad fork", fork_from="missing-worker")

        # Claim and complete turn 1 on child-cross -> clears transcript_seed
        claimed_cross = [w for w in self.store.claim_runnable_workers() if w["name"] == "child-cross"][0]
        done_cross = self.store.complete_turn("child-cross", delivered_max_seq=claimed_cross["delivered_max_seq"])
        self.assertEqual(done_cross["transcript_seed"], "")

        # Complete child-coord turn too so board is idle
        for w in list(self.store.list_workers()):
            if w["state"] == "working":
                self.store.complete_turn(w["name"], delivered_max_seq=99)

        # mark_stopped halts without crash-looping, then wakes on a newer post (INV-4)
        self.store.post_message("coordinator", "@child-same trigger crash turn")
        crashing = self.store.claim_runnable_workers()[0]
        self.assertEqual(crashing["name"], "child-same")
        stopped = self.store.mark_stopped("child-same", delivered_max_seq=crashing["delivered_max_seq"], error="boom")
        self.assertNotIn("worker_token", stopped)
        self.assertEqual(stopped["state"], "stopped")
        self.assertEqual(self.store.claim_runnable_workers(), [])

        # Newer post wakes stopped worker
        self.store.post_message("coordinator", "@child-same retry after fix")
        rewoken = self.store.claim_runnable_workers()
        self.assertEqual([w["name"] for w in rewoken], ["child-same"])

        # switch_model state guards (waiting/stopped allowed; working/killing/killed or empty model rejected)
        with self.assertRaises(ValueError):
            self.store.switch_model("child-same", "haiku")
        self.store.mark_stopped("child-same", delivered_max_seq=rewoken[0]["delivered_max_seq"], error="stop2")
        sw = self.store.switch_model("child-same", "sonnet")
        self.assertNotIn("worker_token", sw)
        self.assertEqual(sw["model"], "sonnet")
        with self.assertRaises(ValueError):
            self.store.switch_model("child-same", "   ")

        self.store.mark_killing("child-same")
        with self.assertRaises(ValueError):
            self.store.switch_model("child-same", "opus")
        self.assertEqual(self.store.complete_turn("child-same", delivered_max_seq=99)["state"], "killing")
        self.assertEqual(self.store.mark_stopped("child-same", delivered_max_seq=99, error="term")["state"], "killing")
        self.store.mark_killed("child-same")
        with self.assertRaises(ValueError):
            self.store.switch_model("child-same", "opus")
        with self.assertRaises(ValueError):
            self.store.mark_killing("child-same")


if __name__ == "__main__":
    unittest.main()
