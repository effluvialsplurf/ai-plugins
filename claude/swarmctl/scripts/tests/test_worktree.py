from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarmctl import WorkspaceManager


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


class TestWorkspaceManager(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        _git(self.repo, "init")
        (self.repo / "README.md").write_text("# test repo\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-m", "initial commit")
        self.swarm_dir = self.repo / ".swarm" / "default"
        self.mgr = WorkspaceManager()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_inherit_create_and_remove_noop(self) -> None:
        path, branch = self.mgr.create(self.repo, self.swarm_dir, "w1", "inherit")
        self.assertEqual(path, self.repo.resolve())
        self.assertEqual(branch, "")
        self.mgr.remove(self.repo, path, branch, "inherit")
        self.assertTrue((self.repo / "README.md").exists())

    def test_share_create_branch_and_clean_remove(self) -> None:
        wt_path, branch = self.mgr.create(self.repo, self.swarm_dir, "w2", "share")
        self.assertEqual(wt_path, (self.swarm_dir / "worktrees" / "w2").resolve())
        self.assertEqual(branch, "swarm/default/w2")
        self.assertTrue((wt_path / "README.md").exists())

        clean, status = self.mgr.verify_clean(wt_path)
        self.assertTrue(clean)
        self.assertEqual(status, "")

        # Pre-existing dir or branch refused
        with self.assertRaises(RuntimeError):
            self.mgr.create(self.repo, self.swarm_dir, "w2", "share")

        # Clean remove deletes worktree dir and merged branch
        self.mgr.remove(self.repo, wt_path, branch, "share", force=False)
        self.assertFalse(wt_path.exists())
        ref_check = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(ref_check.returncode, 0)

    def test_dirty_worktree_refused_without_force_and_removed_with_force(self) -> None:
        wt_path, branch = self.mgr.create(self.repo, self.swarm_dir, "w2", "share")
        (wt_path / "untracked.txt").write_text("dirty\n", encoding="utf-8")

        clean, status = self.mgr.verify_clean(wt_path)
        self.assertFalse(clean)
        self.assertIn("untracked.txt", status)

        with self.assertRaises(RuntimeError) as ctx:
            self.mgr.remove(self.repo, wt_path, branch, "share", force=False)
        self.assertIn("--force", str(ctx.exception))
        self.assertTrue(wt_path.exists())

        self.mgr.remove(self.repo, wt_path, branch, "share", force=True)
        self.assertFalse(wt_path.exists())

    def test_unmerged_commits_preserved_on_non_force_remove(self) -> None:
        wt_path, branch = self.mgr.create(self.repo, self.swarm_dir, "w2", "share")
        (wt_path / "feature.py").write_text("x = 1\n", encoding="utf-8")
        _git(wt_path, "add", "feature.py")
        _git(wt_path, "commit", "-m", "worker feature")

        self.mgr.remove(self.repo, wt_path, branch, "share", force=False)
        self.assertFalse(wt_path.exists())

        # Branch with unmerged commit must be preserved when force=False
        ref_check = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertEqual(ref_check.returncode, 0)

        # Pre-existing branch blocks recreating same worker until branch is cleaned or force-removed
        with self.assertRaises(RuntimeError):
            self.mgr.create(self.repo, self.swarm_dir, "w2", "share")

        # Force remove cleans up the remaining unmerged branch
        self.mgr.remove(self.repo, wt_path, branch, "share", force=True)
        ref_after = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(ref_after.returncode, 0)

    def test_prune_all_unborn_head_and_invalid_ident_guards(self) -> None:
        wt_path, _ = self.mgr.create(self.repo, self.swarm_dir, "w3", "share")
        shutil.rmtree(wt_path)
        pruned = self.mgr.prune_all(self.repo, "default")
        self.assertEqual(pruned, 1)
        self.assertEqual(self.mgr.prune_all(self.repo, "default"), 0)

        # Unborn HEAD repo rejected for share mode
        unborn = Path(self.tmp.name) / "unborn"
        unborn.mkdir()
        _git(unborn, "init")
        with self.assertRaises(RuntimeError):
            self.mgr.create(unborn, unborn / ".swarm" / "default", "w1", "share")

        # Fail-closed validation checks
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, self.repo / ".swarm" / "../evil", "w1", "share", swarm_id="../evil")
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, self.swarm_dir, "coordinator", "share")
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, self.swarm_dir, "w1", "branch")
        with self.assertRaises(ValueError):
            self.mgr.remove(self.repo, self.repo, "", "branch")
        with self.assertRaises(ValueError):
            self.mgr.prune_all(self.repo, "../evil")


if __name__ == "__main__":
    unittest.main()
