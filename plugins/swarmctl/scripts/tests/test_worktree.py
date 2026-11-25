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

        # Modified tracked file preserves leading space in porcelain XY column (N3)
        (wt_path / "README.md").write_text("# modified\n", encoding="utf-8")
        clean_mod, status_mod = self.mgr.verify_clean(wt_path)
        self.assertFalse(clean_mod)
        self.assertTrue(status_mod.startswith(" M README.md"))

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

        ref_check = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertEqual(ref_check.returncode, 0)

        with self.assertRaises(RuntimeError):
            self.mgr.create(self.repo, self.swarm_dir, "w2", "share")

        self.mgr.remove(self.repo, wt_path, branch, "share", force=True)
        ref_after = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(ref_after.returncode, 0)

    def test_security_guards_verify_clean_and_prune_all(self) -> None:
        # 1. B1: remove(force=True) refuses repo_root, outside paths, symlinks, and non-swarm branches
        with self.assertRaises(ValueError):
            self.mgr.remove(self.repo, self.repo, "swarm/default/w1", "share", force=True)
        self.assertTrue((self.repo / "README.md").exists())

        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        with self.assertRaises(ValueError):
            self.mgr.remove(self.repo, outside, "swarm/default/w1", "share", force=True)
        self.assertTrue(outside.exists())

        valid_wt_slot = self.swarm_dir / "worktrees" / "w-sym"
        valid_wt_slot.parent.mkdir(parents=True, exist_ok=True)
        valid_wt_slot.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.mgr.remove(self.repo, valid_wt_slot, "swarm/default/w-sym", "share", force=True)
        valid_wt_slot.unlink()

        valid_wt_path = self.swarm_dir / "worktrees" / "w1"
        for bad_branch in ["main", "master", "-D", "swarm/../evil/w1", "swarm/default/coordinator"]:
            with self.assertRaises(ValueError, msg=f"expected failure for branch {bad_branch!r}"):
                self.mgr.remove(self.repo, valid_wt_path, bad_branch, "share", force=True)

        # 2. H2: create refuses ../ traversal even when swarm_id=None, outside swarm_dir, and dangling symlinks
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, self.repo / ".swarm" / "../evil", "w1", "share")
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, outside / "default", "w1", "share")

        dangling_wt = self.swarm_dir / "worktrees" / "w-dangling"
        dangling_wt.symlink_to(self.repo / "nonexistent-target")
        with self.assertRaises(RuntimeError):
            self.mgr.create(self.repo, self.swarm_dir, "w-dangling", "share")
        dangling_wt.unlink()

        # 3. H3: verify_clean rejects file paths and gitignored non-worktree directories inside repo_root
        with self.assertRaises(RuntimeError):
            self.mgr.verify_clean(self.repo / "README.md")
        (self.repo / ".gitignore").write_text(".swarm/\n", encoding="utf-8")
        fake_wt = self.swarm_dir / "worktrees" / "fake"
        fake_wt.mkdir(parents=True, exist_ok=True)
        (fake_wt / "uncommitted.txt").write_text("secret\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.mgr.verify_clean(fake_wt)

        # 4. M3: prune_all prunes stale git worktree registrations + empty dirs, preserves non-empty dirs & symlinks
        wt_path, _ = self.mgr.create(self.repo, self.swarm_dir, "w3", "share")
        shutil.rmtree(wt_path)
        empty_stale = self.swarm_dir / "worktrees" / "empty-stale"
        empty_stale.mkdir(parents=True, exist_ok=True)
        sym_dir = self.swarm_dir / "worktrees" / "sym-dir"
        sym_dir.symlink_to(outside)

        pruned = self.mgr.prune_all(self.repo, "default")
        self.assertEqual(pruned, 2)  # 1 git worktree registration (w3) + 1 empty dir (empty-stale)
        self.assertFalse(empty_stale.exists())
        self.assertTrue((fake_wt / "uncommitted.txt").exists())  # non-empty dir preserved!
        self.assertTrue(sym_dir.is_symlink())  # symlink preserved!
        sym_dir.unlink()
        shutil.rmtree(fake_wt)
        self.assertEqual(self.mgr.prune_all(self.repo, "default"), 0)

        # Non-git repo_root rejected by prune_all
        with self.assertRaises(RuntimeError):
            self.mgr.prune_all(outside, "default")

        # 5. Unborn HEAD repo rejected for share mode
        unborn = Path(self.tmp.name) / "unborn"
        unborn.mkdir()
        _git(unborn, "init")
        with self.assertRaises(RuntimeError):
            self.mgr.create(unborn, unborn / ".swarm" / "default", "w1", "share")

        # 6. Invalid identifiers fail closed
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, self.swarm_dir, "coordinator", "share")
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, self.swarm_dir, "w1\n", "share")
        with self.assertRaises(ValueError):
            self.mgr.create(self.repo, self.swarm_dir, "w1", "branch")
        with self.assertRaises(ValueError):
            self.mgr.remove(self.repo, self.repo, "", "branch")
        with self.assertRaises(ValueError):
            self.mgr.prune_all(self.repo, "../evil")


if __name__ == "__main__":
    unittest.main()
