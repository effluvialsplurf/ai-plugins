"""UNIX CLI subcommands, worker-role auth guardrails, and output formatting (`ADR-5`, `BR-5`, `BR-7`, `INV-7`, `INV-8`)."""
from __future__ import annotations

import argparse, fcntl, json, os, signal, subprocess, sys, time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import RUNNER_TEMPLATES, TurnRequest, _validate_cli_arg, get_adapter
from .store import SwarmStore, _public_worker, validate_ident
from .supervisor import _is_pid_alive, _signal_pgid, ensure_supervisor, run_supervisor_loop
from .worktree import WorkspaceManager

CLAUDE_MODELS: tuple[str, ...] = ("sonnet", "opus", "haiku")
CLAUDE_MODELS_ALL: tuple[str, ...] = ("sonnet", "opus", "haiku", "claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5")
_BATCH_LIMIT, _KILL_POLL_SEC, _KILL_GRACE_SEC = 200, 0.05, 3.0
_WORKER_ENV_KEYS = ("SWARMCTL_WORKER_TOKEN", "SWARMCTL_ROLE", "SWARMCTL_AGENT")


def resolve_repo_root(repo: str | None = None, cwd: Path | None = None) -> Path:
    base_cwd = (cwd or Path.cwd()).resolve()
    if repo is not None:
        p = Path(repo).expanduser().resolve()
        if not p.is_dir():
            raise FileNotFoundError(f"Repository directory does not exist: {repo}")
        return p
    if base_cwd.is_dir():
        git = lambda *a: subprocess.run(["git", *a], cwd=str(base_cwd), capture_output=True, text=True)
        bare, c_res = git("rev-parse", "--is-bare-repository"), git("rev-parse", "--git-common-dir")
        if bare.returncode == 0 and c_res.returncode == 0:
            raw_c = Path(c_res.stdout.strip())
            common = (raw_c if raw_c.is_absolute() else (base_cwd / raw_c)).resolve()
            if bare.stdout.strip().lower() != "true" and common.name == ".git":
                return common.parent
        top = git("rev-parse", "--show-toplevel")
        if top.returncode == 0 and top.stdout.strip():
            return Path(top.stdout.strip()).resolve()
    return base_cwd


def resolve_swarm_dir(repo_root: Path, swarm_id: str) -> Path:
    validate_ident(swarm_id, "swarm")
    return repo_root.resolve() / ".swarm" / swarm_id


def _open_existing_store(swarm_dir: Path) -> SwarmStore:
    db_path = swarm_dir / "board.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"Swarm store not initialized at {db_path} (run `swarmctl init` first)")
    return SwarmStore(db_path)


def _is_worker_mode(env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return e.get("SWARMCTL_ROLE") == "worker" or bool(e.get("SWARMCTL_WORKER_TOKEN"))


def _safe_ensure_supervisor(swarm_dir: Path, **kwargs: Any) -> int | None:
    saved = {k: os.environ.pop(k) for k in _WORKER_ENV_KEYS if k in os.environ}
    try:
        return ensure_supervisor(swarm_dir, **kwargs)
    finally:
        os.environ.update(saved)


def _drain_since(store: SwarmStore, since: int, limit: int = _BATCH_LIMIT) -> tuple[list[dict[str, Any]], int]:
    cursor, msgs, head = int(since), [], int(since)
    while True:
        res = store.read_board(since=cursor, limit=limit)
        batch, head = res["messages"], int(res["head_seq"])
        msgs.extend(batch)
        if len(batch) < limit:
            return msgs, head
        cursor = int(batch[-1]["seq"])


def _verify_pid_worker_token(pid: int, expected_token: str) -> bool:
    try:
        return f"SWARMCTL_WORKER_TOKEN={expected_token}".encode("utf-8") in Path(f"/proc/{pid}/environ").read_bytes().split(b"\x00")
    except OSError:
        return False


def _emit(data: Any, as_json: bool, human_fn: Any = None) -> None:
    print(json.dumps(data), flush=True) if (as_json or human_fn is None) else human_fn(data)


def _add_sub(sub: Any, name: str, *specs: tuple[Any, ...], **kwargs: Any) -> argparse.ArgumentParser:
    p = sub.add_parser(name, **kwargs)
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, dest="json_sub")
    for flags, opts in specs:
        p.add_argument(*(flags if isinstance(flags, tuple) else (flags,)), **opts)
    return p


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="swarmctl", description="Minimalist local multi-agent swarm CLI")
    for fl, kw in (("--swarm", {"default": None}), ("--repo", {"default": None}),
                   ("--json", {"action": "store_true", "default": False, "dest": "json_global"})):
        p.add_argument(fl, **kw)  # type: ignore[arg-type]
    sub = p.add_subparsers(dest="subcommand", required=True)
    _add_sub(sub, "init", ("--title", {"default": ""}), ("--runner", {"default": "claude"}), ("--model", {"default": ""}),
             ("--max-concurrent", {"type": int, "default": 4}), ("--max-turns", {"type": int, "default": 25}))
    _add_sub(sub, "add", ("name", {}), ("--brief", {"required": True}), ("--workspace", {"choices": ["inherit", "share"], "default": "inherit"}),
             ("--model", {"default": None}), ("--runner", {"default": None}), ("--fork", {"default": None}),
             ("--unsafe", {"action": "store_true", "default": False}), ("--no-wake", {"action": "store_true", "default": False}))
    _add_sub(sub, "status")
    _add_sub(sub, "models", ("--all", {"action": "store_true", "default": False, "dest": "all_models"}))
    _add_sub(sub, "model", ("name", {}), ("model", {}))
    _add_sub(sub, "kill", ("name", {}), ("--force", {"action": "store_true", "default": False}), ("--timeout", {"type": float, "default": 10.0}))
    _add_sub(sub, "title", ("title", {}))
    _add_sub(sub, "post", ("--as", {"default": None, "dest": "sender"}), ("--token", {"default": None}),
             ("--no-wake", {"action": "store_true", "default": False}), ("text", {}))
    _add_sub(sub, "read", ("--since", {"type": int, "default": None}), ("--limit", {"type": int, "default": 20}),
             ("--seqs", {"default": None}), ("--status", {"action": "store_true", "default": False}))
    p_wait = _add_sub(sub, "wait", ("--for", {"required": True, "dest": "for_name"}), ("--since", {"type": int, "required": True}),
                      ("--timeout", {"type": float, "default": 45.0}), ("--poll-sec", {"type": float, "default": 0.2}))
    m_grp = p_wait.add_mutually_exclusive_group()
    m_grp.add_argument("--mentions-only", action="store_true", dest="mentions_only", default=True)
    m_grp.add_argument("--no-mentions-only", action="store_false", dest="mentions_only")
    _add_sub(sub, "tail", ("--since", {"type": int, "default": None}), ("--follow", {"action": "store_true", "default": False}),
             ("--poll-sec", {"type": float, "default": 0.2}))
    _add_sub(sub, "supervise", ("--daemon", {"action": "store_true", "default": False}), ("--idle-timeout", {"type": float, "default": 60.0}),
             ("--tick-sec", {"type": float, "default": 0.25}), ("--turn-timeout", {"type": float, "default": 900.0}),
             ("--kill-grace", {"type": float, "default": 3.0}))
    _add_sub(sub, "mcp", ("--agent", {"default": None}), ("--role", {"choices": ["coordinator", "worker"], "default": None}))
    return p


def _handle_kill(store: SwarmStore, swarm_dir: Path, name: str, force: bool, timeout: float) -> dict[str, Any]:
    if timeout < 0:
        raise ValueError("--timeout must be >= 0")
    repo_root, wm = Path(store.get_meta()["repo_root"]).resolve(), WorkspaceManager()
    w = store.get_worker(name)
    if w is None:
        raise ValueError(f"Unknown worker: {name!r}")
    wt_path = Path(w["workspace_path"])
    if w["state"] == "killed":
        if force and w["workspace_mode"] == "share":
            wm.remove(repo_root, wt_path, w["branch_name"], "share", force=True)
            return _public_worker(w)
        raise ValueError(f"Worker {name!r} is already killed")
    if w["workspace_mode"] == "share" and not force and (wt_path.exists() or wt_path.is_symlink()):
        is_clean, dirty_out = wm.verify_clean(wt_path)
        if not is_clean:
            raise RuntimeError(f"Refusing to kill worker {name!r} with dirty worktree {wt_path} (merge changes or pass --force):\n{dirty_out}")
    swarm_dir.mkdir(parents=True, exist_ok=True)
    lock_f = open(swarm_dir / "supervisor.lock", "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlocked = True
        except BlockingIOError:
            unlocked = False
        if not unlocked:
            store.mark_killing(name)
            _safe_ensure_supervisor(swarm_dir)
            deadline = time.monotonic() + timeout
            while True:
                curr = store.get_worker(name)
                if curr is not None and curr["state"] == "killed":
                    if force and curr["workspace_mode"] == "share":
                        wm.remove(repo_root, Path(curr["workspace_path"]), curr["branch_name"], "share", force=True)
                    return _public_worker(curr)
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Timed out waiting {timeout}s for supervisor to kill worker {name!r}")
                time.sleep(_KILL_POLL_SEC)
        w_curr = store.get_worker(name)
        if w_curr is None:
            raise ValueError(f"Unknown worker: {name!r}")
        if w_curr["state"] != "killed":
            store.mark_killing(name)
        pid = int(w_curr["pid"] or 0)
        if pid > 0 and _is_pid_alive(pid):
            if not _verify_pid_worker_token(pid, str(w_curr["worker_token"])):
                raise RuntimeError(f"Refusing to signal PID {pid} for worker {name!r}: worker token mismatch")
            _signal_pgid(pid, None, signal.SIGTERM)
            g_deadline = time.monotonic() + _KILL_GRACE_SEC
            while _is_pid_alive(pid) and time.monotonic() < g_deadline:
                time.sleep(_KILL_POLL_SEC)
            if _is_pid_alive(pid):
                _signal_pgid(pid, None, signal.SIGKILL)
        if w_curr["workspace_mode"] == "share":
            wm.remove(repo_root, Path(w_curr["workspace_path"]), w_curr["branch_name"], "share", force=force)
        return store.mark_killed(name)
    finally:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_f.close()


def _dispatch(args: argparse.Namespace) -> int:
    cmd = str(args.subcommand)
    as_json = bool(args.json_global or getattr(args, "json_sub", False))
    swarm_id = args.swarm if args.swarm is not None else (os.environ.get("SWARMCTL_SWARM") or "default")
    validate_ident(swarm_id, "swarm")
    worker_mode = _is_worker_mode()
    if worker_mode and cmd in ("init", "add", "model", "kill", "title", "supervise"):
        raise PermissionError(f"Worker role cannot execute `swarmctl {cmd}`")

    if cmd == "models":
        if args.repo is not None:
            resolve_repo_root(args.repo)
        runners = {"claude": {"guardrails": ["readonly", "edit", "unsafe"]},
                   **{k: {"guardrails": [m for m, f in t["permission_flags"].items() if f is not None]} for k, t in RUNNER_TEMPLATES.items()}}
        data = {"default_runner": "claude", "claude_models": list(CLAUDE_MODELS_ALL if args.all_models else CLAUDE_MODELS), "runners": runners}
        _emit(data, as_json, lambda d: print(
            f"default_runner: {d['default_runner']}\nclaude_models: {', '.join(d['claude_models'])}\n"
            + "\n".join(f"runner {k}: {', '.join(v['guardrails'])}" for k, v in d["runners"].items()), flush=True))
        return 0

    repo_root = resolve_repo_root(args.repo)
    swarm_dir = resolve_swarm_dir(repo_root, swarm_id)

    if cmd == "mcp":
        role, agent = args.role, args.agent
        if worker_mode:
            if role == "coordinator":
                raise PermissionError("Worker role cannot start MCP server with --role coordinator")
            role, agent = "worker", (agent or os.environ.get("SWARMCTL_AGENT") or "")
            if not agent and os.environ.get("SWARMCTL_WORKER_TOKEN") and (swarm_dir / "board.db").is_file():
                with _open_existing_store(swarm_dir) as st:
                    agent = st.verify_worker_token(os.environ["SWARMCTL_WORKER_TOKEN"])
        else:
            role = role or "coordinator"
            agent = agent or ("coordinator" if role == "coordinator" else (os.environ.get("SWARMCTL_AGENT") or ""))
        try:
            from .mcp_server import serve_stdio  # type: ignore[import-not-found]
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError("MCP server is not available yet") from exc
        return int(serve_stdio(swarm_dir=swarm_dir, role=role, agent=agent) or 0)

    if cmd == "init":
        get_adapter(args.runner)
        if args.model:
            _validate_cli_arg(args.model, "model")
        with SwarmStore(swarm_dir / "board.db") as store:
            meta = store.init_swarm(swarm_id, str(repo_root), title=args.title, default_runner=args.runner,
                                    default_model=args.model, max_concurrent=args.max_concurrent, max_turns=args.max_turns)
        _emit(meta, as_json, lambda m: print(f"Initialized swarm {m['swarm_id']!r} at {swarm_dir}", flush=True))
        return 0

    with _open_existing_store(swarm_dir) as store:
        if cmd == "title":
            _emit(store.set_title(args.title), as_json, lambda m: print(f"Swarm {m['swarm_id']}: {m['title']}", flush=True))
            return 0
        if cmd == "status":
            _emit(store.read_board(status=True), as_json, lambda d: print(
                f"Swarm: {d['swarm_id']} (head_seq={d['head_seq']}) {d['title']}\n"
                + "\n".join(f"  {w['name']}: {w['state']} ({w['runner']} {w['model']})" for w in d["workers"]), flush=True))
            return 0
        if cmd == "model":
            _emit(store.switch_model(args.name, _validate_cli_arg(args.model, "model")), as_json,
                  lambda w: print(f"Worker {w['name']} model -> {w['model']}", flush=True))
            return 0
        if cmd == "add":
            validate_ident(args.name, "worker")
            if not isinstance(args.brief, str) or not args.brief.strip():
                raise ValueError("Worker brief must be non-empty")
            meta = store.get_meta()
            resolved_runner = args.runner or str(meta["default_runner"])
            resolved_model = str(meta["default_model"]) if args.model is None else _validate_cli_arg(args.model, "model")
            if resolved_model:
                _validate_cli_arg(resolved_model, "model")
            perm_mode = "unsafe" if args.unsafe else ("readonly" if args.workspace == "inherit" else "edit")
            get_adapter(resolved_runner).build_command(TurnRequest(
                swarm_id=swarm_id, worker_name=args.name, worker_token="dry-run-token", runner=resolved_runner,
                model=resolved_model, workspace_path=str(repo_root), permission_mode=perm_mode, session_id="",
                fork_session_id="", transcript_seed="", prompt_delta="", delivered_max_seq=0))
            wm = WorkspaceManager()
            wt_path, branch = wm.create(repo_root, swarm_dir, args.name, args.workspace, swarm_id=swarm_id)
            try:
                raw_w = store.add_worker(args.name, args.brief, runner=resolved_runner, model=resolved_model,
                                         workspace_mode=args.workspace, workspace_path=str(wt_path),
                                         branch_name=branch, permission_mode=perm_mode, fork_from=args.fork)
            except BaseException:
                if args.workspace == "share":
                    wm.remove(repo_root, wt_path, branch, "share", force=True)
                raise
            if not args.no_wake:
                _safe_ensure_supervisor(swarm_dir)
            _emit({**_public_worker(raw_w), "brief_seq": int(raw_w["brief_seq"])}, as_json,
                  lambda w: print(f"Added worker {w['name']} ({w['workspace_mode']}, brief #{w['brief_seq']})", flush=True))
            return 0
        if cmd == "kill":
            _emit(_handle_kill(store, swarm_dir, args.name, bool(args.force), float(args.timeout)),
                  as_json, lambda w: print(f"Killed worker {w['name']}", flush=True))
            return 0
        if cmd == "post":
            token = (args.token or os.environ.get("SWARMCTL_WORKER_TOKEN") or "") if worker_mode else (args.token or "")
            if worker_mode and not token:
                raise PermissionError("Worker mode requires SWARMCTL_WORKER_TOKEN or --token")
            if token:
                owner = store.verify_worker_token(token)
                env_agent = (os.environ.get("SWARMCTL_AGENT") or owner) if worker_mode else owner
                sender = args.sender or env_agent
                if sender != owner or env_agent != owner:
                    raise PermissionError(f"Worker token belongs to {owner!r}, cannot post as {sender!r}")
                msg = store.post_message(sender, args.text, token=token)
            else:
                msg = store.post_message(args.sender or "coordinator", args.text)
            if not worker_mode and not args.no_wake:
                _safe_ensure_supervisor(swarm_dir)
            _emit(msg, as_json, lambda m: print(f"[#{m['seq']}] {m['sender']}: {m['body']}", flush=True))
            return 0
        if cmd == "read":
            seq_list: list[int] | None = None
            if args.seqs is not None:
                parts = [s.strip() for s in str(args.seqs).split(",")]
                if not parts or any(not p or not p.isdigit() for p in parts):
                    raise ValueError(f"Invalid --seqs comma-separated integers: {args.seqs!r}")
                seq_list = [int(p) for p in parts]
            res = store.read_board(since=args.since, limit=args.limit, seqs=seq_list, status=bool(args.status))
            if args.status:
                _emit(res, as_json, lambda d: print(f"Swarm: {d['swarm_id']} (head_seq={d['head_seq']}) {d['title']}\n" + "\n".join(f"  {w['name']}: {w['state']}" for w in d["workers"]), flush=True))
            else:
                _emit(res, as_json, lambda d: print("\n".join(f"[#{m['seq']}] {m['sender']}: {m['body']}" for m in d["messages"]), flush=True) if d["messages"] else None)
            return 0
        if cmd == "wait":
            for_name = str(args.for_name).strip()
            if not for_name or args.timeout < 0 or args.poll_sec <= 0:
                raise ValueError("--for must be non-empty, --timeout >= 0, and --poll-sec > 0")
            deadline = time.monotonic() + float(args.timeout)
            while True:
                msgs, head = _drain_since(store, args.since)
                if any(m["sender"] != for_name and (not args.mentions_only or for_name in m["mentions"] or "all" in m["mentions"]) for m in msgs):
                    _emit({"messages": msgs, "timed_out": False, "head_seq": head}, as_json,
                          lambda d: print("\n".join(f"[#{m['seq']}] {m['sender']}: {m['body']}" for m in d["messages"]), flush=True))
                    return 0
                if time.monotonic() >= deadline:
                    _emit({"messages": [], "timed_out": True, "head_seq": head}, as_json, lambda _: None)
                    return 0
                time.sleep(min(float(args.poll_sec), max(0.0, deadline - time.monotonic())))
        if cmd == "tail":
            if args.poll_sec <= 0:
                raise ValueError("--poll-sec must be > 0")
            p_msg = (lambda m: print(json.dumps(m), flush=True)) if as_json else (lambda m: print(f"[#{m['seq']}] {m['sender']}: {m['body']}", flush=True))
            if args.since is None:
                init_res = store.read_board(limit=20)
                init_msgs, cursor = init_res["messages"], int(init_res["head_seq"])
            else:
                init_msgs, cursor = _drain_since(store, args.since)
            for m in init_msgs:
                p_msg(m)
            if not args.follow:
                return 0
            try:
                while True:
                    time.sleep(float(args.poll_sec))
                    new_msgs, new_head = _drain_since(store, cursor)
                    for m in new_msgs:
                        p_msg(m)
                    cursor = max(cursor, new_head)
            except KeyboardInterrupt:
                return 0
        if cmd == "supervise":
            store.get_meta()
            kw = dict(idle_timeout_sec=args.idle_timeout, tick_sec=args.tick_sec,
                      turn_timeout_sec=args.turn_timeout, kill_grace_sec=args.kill_grace)
            if args.daemon:
                pid = _safe_ensure_supervisor(swarm_dir, **kw)
                _emit({"pid": pid, "already_running": pid is None}, as_json,
                      lambda d: print(f"Supervisor PID: {d['pid']} (already_running={d['already_running']})", flush=True))
                return 0
            try:
                return run_supervisor_loop(swarm_dir, **kw)
            except KeyboardInterrupt:
                return 0
    raise ValueError(f"Unknown subcommand: {cmd!r}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _dispatch(build_parser().parse_args(list(argv) if argv is not None else None))
    except (ValueError, PermissionError, RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
