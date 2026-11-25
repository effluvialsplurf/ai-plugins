"""Git worktree workspace manager (`ADR-6`, `BR-4`, `BR-8`, `INV-6`, `INV-8`)."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from .store import VALID_WORKSPACE_MODES, validate_ident


def _run_git(cwd: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    if not cwd.exists():
        raise RuntimeError(f"Git working directory does not exist: {cwd}")
    res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return res


def _registered_swarm_worktrees(repo_path: Path, wt_base: Path) -> set[str]:
    res = _run_git(repo_path, ["worktree", "list", "--porcelain"], check=False)
    if res.returncode != 0:
        return set()
    prefix = str(wt_base.resolve()) + "/"
    found: set[str] = set()
    for line in res.stdout.splitlines():
        if line.startswith("worktree "):
            p = str(Path(line[len("worktree "):].strip()).resolve())
            if p.startswith(prefix):
                found.add(p)
    return found


class WorkspaceManager:
    def create(
        self,
        repo_root: Path | str,
        swarm_dir: Path | str,
        name: str,
        mode: str,
        swarm_id: str | None = None,
    ) -> tuple[Path, str]:
        repo_path = Path(repo_root).resolve()
        swarm_path = Path(swarm_dir).resolve()
        sid = swarm_id if swarm_id is not None else swarm_path.name
        validate_ident(sid, "swarm")
        validate_ident(name, "worker")
        if mode not in VALID_WORKSPACE_MODES:
            raise ValueError(f"Invalid workspace mode: {mode!r}")
        if mode == "inherit":
            return (repo_path, "")

        head = _run_git(repo_path, ["rev-parse", "--verify", "HEAD"], check=False)
        if head.returncode != 0:
            raise RuntimeError(f"Repository {repo_path} does not have a valid HEAD commit for git worktree")

        wt_path = swarm_path / "worktrees" / name
        branch = f"swarm/{sid}/{name}"
        if wt_path.exists():
            raise RuntimeError(f"Worktree path already exists: {wt_path}")
        ref_check = _run_git(repo_path, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
        if ref_check.returncode == 0:
            raise RuntimeError(f"Worktree branch already exists: {branch}")

        wt_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(repo_path, ["worktree", "add", "-b", branch, str(wt_path), "HEAD"], check=True)
        return (wt_path.resolve(), branch)

    def verify_clean(self, path: Path | str) -> tuple[bool, str]:
        wt_path = Path(path).resolve()
        res = _run_git(wt_path, ["status", "--porcelain"], check=True)
        output = res.stdout.strip()
        return (output == "", output)

    def remove(
        self,
        repo_root: Path | str,
        path: Path | str,
        branch: str,
        mode: str,
        force: bool = False,
    ) -> None:
        if mode not in VALID_WORKSPACE_MODES:
            raise ValueError(f"Invalid workspace mode: {mode!r}")
        if mode == "inherit":
            return

        repo_path = Path(repo_root).resolve()
        wt_path = Path(path).resolve()
        if wt_path.exists():
            if not force:
                is_clean, dirty_out = self.verify_clean(wt_path)
                if not is_clean:
                    raise RuntimeError(
                        f"Refusing to remove dirty worktree {wt_path} (pass --force to override):\n{dirty_out}"
                    )
            rm_args = ["worktree", "remove", *(["--force"] if force else []), str(wt_path)]
            rm_res = _run_git(repo_path, rm_args, check=False)
            if rm_res.returncode != 0:
                if force and wt_path.exists():
                    shutil.rmtree(wt_path)
                else:
                    err = (rm_res.stderr or rm_res.stdout or "").strip()
                    raise RuntimeError(f"Failed to remove worktree {wt_path}: {err}")

        _run_git(repo_path, ["worktree", "prune"], check=False)
        if branch:
            flag = "-D" if force else "-d"
            _run_git(repo_path, ["branch", flag, branch], check=False)

    def prune_all(self, repo_root: Path | str, swarm_id: str) -> int:
        validate_ident(swarm_id, "swarm")
        repo_path = Path(repo_root).resolve()
        wt_base = repo_path / ".swarm" / swarm_id / "worktrees"
        before = _registered_swarm_worktrees(repo_path, wt_base)
        _run_git(repo_path, ["worktree", "prune"], check=False)
        after = _registered_swarm_worktrees(repo_path, wt_base)
        pruned = max(0, len(before - after))
        if wt_base.is_dir():
            for child in wt_base.iterdir():
                if child.is_dir() and not (child / ".git").exists():
                    shutil.rmtree(child, ignore_errors=True)
                    pruned += 1
        return pruned
