"""Git worktree workspace manager (`ADR-6`, `BR-4`, `BR-8`, `INV-6`, `INV-8`)."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from .store import VALID_WORKSPACE_MODES, validate_ident


def _run_git(cwd: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    if not cwd.is_dir():
        raise RuntimeError(f"Git working directory is not a valid directory: {cwd}")
    res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return res


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_swarm_branch(branch: str) -> None:
    if not isinstance(branch, str) or branch.startswith("-"):
        raise ValueError(f"Invalid worktree branch name: {branch!r}")
    parts = branch.split("/")
    if len(parts) != 3 or parts[0] != "swarm":
        raise ValueError(f"Worktree branch must match 'swarm/<swarm_id>/<worker>': {branch!r}")
    validate_ident(parts[1], "swarm")
    validate_ident(parts[2], "worker")


def _validate_share_wt_path(repo_path: Path, raw_path: Path) -> Path:
    if raw_path.is_symlink() or ".." in raw_path.parts:
        raise ValueError(f"Refusing symlink or parent-traversal worktree path: {raw_path}")
    wt_path = raw_path.resolve()
    swarm_root = (repo_path / ".swarm").resolve()
    if wt_path == repo_path or not _is_within(wt_path, swarm_root) or wt_path.parent.name != "worktrees":
        raise ValueError(f"Worktree path {wt_path} must reside under {swarm_root}/<swarm_id>/worktrees/<worker>")
    validate_ident(wt_path.parent.parent.name, "swarm")
    validate_ident(wt_path.name, "worker")
    if wt_path != (swarm_root / wt_path.parent.parent.name / "worktrees" / wt_path.name).resolve():
        raise ValueError(f"Worktree path {wt_path} does not match canonical .swarm/<id>/worktrees/<name> layout")
    return wt_path


def _registered_swarm_worktrees(repo_path: Path, wt_base: Path) -> set[str]:
    res = _run_git(repo_path, ["worktree", "list", "--porcelain"], check=True)
    base_resolved = wt_base.resolve()
    found: set[str] = set()
    for line in res.stdout.splitlines():
        if line.startswith("worktree "):
            p = Path(line[len("worktree "):].strip()).resolve()
            if p != base_resolved and _is_within(p, base_resolved):
                found.add(str(p))
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
        raw_swarm_dir = Path(swarm_dir)
        if ".." in raw_swarm_dir.parts or raw_swarm_dir.is_symlink():
            raise ValueError(f"Invalid swarm_dir (symlink or traversal refused): {swarm_dir!r}")
        sid = swarm_id if swarm_id is not None else raw_swarm_dir.name
        validate_ident(sid, "swarm")
        validate_ident(name, "worker")
        if mode not in VALID_WORKSPACE_MODES:
            raise ValueError(f"Invalid workspace mode: {mode!r}")

        repo_path = Path(repo_root).resolve()
        if mode == "inherit":
            return (repo_path, "")

        swarm_path = raw_swarm_dir.resolve()
        expected_swarm_path = (repo_path / ".swarm" / sid).resolve()
        if swarm_path != expected_swarm_path:
            raise ValueError(f"swarm_dir {swarm_path} must resolve to {expected_swarm_path}")

        head = _run_git(repo_path, ["rev-parse", "--verify", "HEAD"], check=False)
        if head.returncode != 0:
            raise RuntimeError(f"Repository {repo_path} does not have a valid HEAD commit for git worktree")

        wt_path = swarm_path / "worktrees" / name
        branch = f"swarm/{sid}/{name}"
        if wt_path.exists() or wt_path.is_symlink():
            raise RuntimeError(f"Worktree path already exists: {wt_path}")
        ref_check = _run_git(repo_path, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
        if ref_check.returncode == 0:
            raise RuntimeError(f"Worktree branch already exists: {branch}")

        wt_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(repo_path, ["worktree", "add", "-b", branch, str(wt_path), "HEAD"], check=True)
        return (wt_path.resolve(), branch)

    def verify_clean(self, path: Path | str) -> tuple[bool, str]:
        raw_path = Path(path)
        if raw_path.is_symlink() or not raw_path.is_dir():
            raise RuntimeError(f"Worktree path is not a valid directory: {path}")
        wt_path = raw_path.resolve()
        top = _run_git(wt_path, ["rev-parse", "--show-toplevel"], check=True)
        if Path(top.stdout.strip()).resolve() != wt_path:
            raise RuntimeError(f"Path {wt_path} is not a standalone git worktree root")
        res = _run_git(wt_path, ["status", "--porcelain"], check=True)
        output = res.stdout.rstrip("\r\n")
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
        wt_path = _validate_share_wt_path(repo_path, Path(path))
        if branch:
            _validate_swarm_branch(branch)

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
            _run_git(repo_path, ["branch", flag, "--", branch], check=False)

    def prune_all(self, repo_root: Path | str, swarm_id: str) -> int:
        validate_ident(swarm_id, "swarm")
        repo_path = Path(repo_root).resolve()
        _run_git(repo_path, ["rev-parse", "--git-dir"], check=True)
        wt_base = repo_path / ".swarm" / swarm_id / "worktrees"
        before = _registered_swarm_worktrees(repo_path, wt_base)
        _run_git(repo_path, ["worktree", "prune"], check=True)
        after = _registered_swarm_worktrees(repo_path, wt_base)
        pruned = max(0, len(before - after))
        if wt_base.is_dir() and not wt_base.is_symlink():
            for child in wt_base.iterdir():
                if not child.is_symlink() and child.is_dir() and not (child / ".git").exists() and not any(child.iterdir()):
                    child.rmdir()
                    pruned += 1
        return pruned
