from __future__ import annotations

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

        for bad_swarm in ["", "../evil", "UPPER", "-start", "_start", "a" * 33, "bad/id"]:
            with self.assertRaises(ValueError, msg=f"expected failure for {bad_swarm!r}"):
                validate_ident(bad_swarm, "swarm")

        for bad_worker in ["", "../evil", "UPPER", "-w", "a" * 25, "all", "coordinator", "system"]:
            with self.assertRaises(ValueError, msg=f"expected failure for {bad_worker!r}"):
                validate_ident(bad_worker, "worker")

        with self.assertRaises(ValueError):
            validate_ident("valid", "unknown_kind")

        mentions = parse_mentions("hi @worker-1, email user@example.com, @all and @worker-1 again (@UPPER ignored)")
        self.assertEqual(mentions, ["worker-1", "all"])

    def test_init_add_worker_and_read_board_modes(self) -> None:
        with self.assertRaises(RuntimeError):
            self.store.get_meta()

        meta = self.store.init_swarm("default", str(self.root), title="Test Swarm")
        self.assertEqual(meta["swarm_id"], "default")
        self.assertEqual(meta["title"], "Test Swarm")

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

        with self.assertRaises(ValueError):
            self.store.add_worker("w1", "duplicate active worker")

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

        # seqs mode: exact matches ascending, ignoring missing
        res_seqs = self.store.read_board(seqs=[3, 1, 99], since=2, limit=1)
        self.assertEqual([m["seq"] for m in res_seqs["messages"]], [1, 3])

        # status mode: never exposes worker_token
        res_status = self.store.read_board(status=True)
        self.assertEqual(res_status["swarm_id"], "default")
        self.assertEqual(res_status["title"], "Renamed Swarm")
        self.assertEqual(res_status["head_seq"], 3)
        self.assertEqual(len(res_status["workers"]), 1)
        self.assertNotIn("worker_token", res_status["workers"][0])
        self.assertNotIn("worker_token", self.store.list_workers()[0])

    def test_concurrent_16_threads_wal_writes(self) -> None:
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

    def test_token_auth_and_anti_spoofing(self) -> None:
        self.store.init_swarm("default", str(self.root))
        w1 = self.store.add_worker("w1", "task 1")
        w2 = self.store.add_worker("w2", "task 2")

        # Valid worker token posting as self
        msg = self.store.post_message("w1", "hello @coordinator", token=w1["worker_token"])
        self.assertEqual(msg["sender"], "w1")

        # Spoofing another worker or coordinator with w1's token
        with self.assertRaises(PermissionError):
            self.store.post_message("w2", "spoof w2", token=w1["worker_token"])
        with self.assertRaises(PermissionError):
            self.store.post_message("coordinator", "spoof coord", token=w1["worker_token"])
        with self.assertRaises(PermissionError):
            self.store.post_message("w1", "bad token", token="invalid-token")

        # Unauthenticated call trying to impersonate registered worker
        with self.assertRaises(PermissionError):
            self.store.post_message("w1", "no token", token=None)

        # Unauthenticated call with unknown sender
        with self.assertRaises(ValueError):
            self.store.post_message("stranger", "hello", token=None)

        # Empty body rejected
        with self.assertRaises(ValueError):
            self.store.post_message("coordinator", "   ")

        # Killed worker token rejected
        self.store.mark_killing("w2")
        self.store.mark_killed("w2")
        with self.assertRaises(PermissionError):
            self.store.post_message("w2", "ghost post", token=w2["worker_token"])

    def test_claim_runnable_and_mid_turn_delivery(self) -> None:
        self.store.init_swarm("default", str(self.root), max_concurrent=1, max_turns=2)
        w1 = self.store.add_worker("w1", "brief 1")

        # Claim 1: triggered by brief #1
        claimed = self.store.claim_runnable_workers()
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["name"], "w1")
        self.assertEqual(claimed[0]["state"], "working")
        self.assertEqual(claimed[0]["delivered_max_seq"], 1)

        # While w1 is working, add w2 -> max_concurrent=1 blocks claiming w2
        w2 = self.store.add_worker("w2", "brief 2")
        self.assertEqual(self.store.claim_runnable_workers(), [])

        # Mid-turn message #3 arrives for w1 while w1 is working on delivered_max_seq=1
        self.store.post_message("coordinator", "@w1 mid-turn update")
        # w1 also posts @all and @w1 (#4) during its turn
        self.store.post_message("w1", "@all @w1 my interim note", token=w1["worker_token"])

        # Complete w1's first turn with delivered_max_seq=1
        done1 = self.store.complete_turn("w1", delivered_max_seq=1, session_id="sess-1")
        self.assertEqual(done1["state"], "waiting")
        self.assertEqual(done1["last_seen_seq"], 1)
        self.assertEqual(done1["turn_count"], 1)
        self.assertEqual(done1["session_id"], "sess-1")

        # Unread delta for w1 up to seq 3 includes #2 and #3
        delta = self.store.get_unread_delta("w1", up_to_seq=3)
        self.assertEqual([m["seq"] for m in delta], [2, 3])

        # Next claim: w2 has oldest unread mention (#2), w1 has #3; max_concurrent=1 claims w2 first
        claimed2 = self.store.claim_runnable_workers()
        self.assertEqual([w["name"] for w in claimed2], ["w2"])
        self.assertEqual(claimed2[0]["delivered_max_seq"], 4)
        self.store.complete_turn("w2", delivered_max_seq=claimed2[0]["delivered_max_seq"])

        # w2 posts @all (#5) -> should NOT wake w2 itself, only w1 (which also has #3)
        self.store.post_message("w2", "@all status from w2", token=w2["worker_token"])
        claimed3 = self.store.claim_runnable_workers()
        self.assertEqual([w["name"] for w in claimed3], ["w1"])
        self.assertEqual(claimed3[0]["delivered_max_seq"], 5)
        self.store.complete_turn("w1", delivered_max_seq=5)

        # w1 now has turn_count == 2 == max_turns; new mention #6 must not claim w1
        self.store.post_message("coordinator", "@w1 after max turns")
        self.assertEqual(self.store.claim_runnable_workers(), [])

    def test_lifecycle_guards_and_hybrid_fork(self) -> None:
        self.store.init_swarm("default", str(self.root))
        parent = self.store.add_worker("parent", "investigate auth")
        self.store.set_worker_pid("parent", 12345)
        self.assertEqual(self.store.get_worker("parent")["pid"], 12345)

        # Claim and complete turn 1 on parent so it gets session_id
        c = self.store.claim_runnable_workers()
        self.assertEqual(len(c), 1)
        self.store.complete_turn("parent", delivered_max_seq=c[0]["delivered_max_seq"], session_id="claude-sid-99")

        # Same-CWD claude fork -> sets fork_session_id, empty transcript_seed
        child_same = self.store.add_worker("child-same", "continue auth", fork_from="parent")
        self.assertEqual(child_same["fork_session_id"], "claude-sid-99")
        self.assertEqual(child_same["transcript_seed"], "")

        # Complete turn 1 on child-same -> clears fork_session_id
        c_child = self.store.claim_runnable_workers(limit=1)
        self.assertEqual(c_child[0]["name"], "child-same")
        after_turn = self.store.complete_turn("child-same", delivered_max_seq=c_child[0]["delivered_max_seq"])
        self.assertEqual(after_turn["fork_session_id"], "")

        # Cross-CWD or non-claude fork + oversized multibyte message -> UTF-8 safe transcript_seed <= 4096B
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

        # Coordinator fork also populates transcript_seed; unknown fork_from fails
        child_coord = self.store.add_worker("child-coord", "help coord", fork_from="coordinator")
        self.assertTrue(child_coord["transcript_seed"].startswith("=== Initial Brief ==="))
        with self.assertRaises(ValueError):
            self.store.add_worker("child-bad", "bad fork", fork_from="missing-worker")

        # switch_model allowed in waiting/stopped, rejected in working/killing/killed
        self.assertEqual(self.store.switch_model("child-same", "opus")["model"], "opus")
        self.store.mark_stopped("child-same", delivered_max_seq=after_turn["last_seen_seq"], error="boom")
        self.assertEqual(self.store.get_worker("child-same")["state"], "stopped")
        self.assertEqual(self.store.switch_model("child-same", "sonnet")["model"], "sonnet")

        # Claim child-cross so it is working -> switch_model fails
        self.store.claim_runnable_workers()
        with self.assertRaises(ValueError):
            self.store.switch_model("child-cross", "haiku")

        # mark_killing while working -> complete_turn & mark_stopped preserve killing
        self.store.mark_killing("child-cross")
        self.assertEqual(self.store.complete_turn("child-cross", delivered_max_seq=99)["state"], "killing")
        self.assertEqual(self.store.mark_stopped("child-cross", delivered_max_seq=99, error="term")["state"], "killing")
        self.store.mark_killed("child-cross")
        with self.assertRaises(ValueError):
            self.store.mark_killing("child-cross")


if __name__ == "__main__":
    unittest.main()
