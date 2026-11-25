"""UNIX CLI subcommands, worker-role auth guardrails, and output formatting (`ADR-5`, `BR-5`, `BR-7`, `INV-7`, `INV-8`)."""
from __future__ import annotations

import argparse, fcntl, json, math, os, re, signal, sqlite3, subprocess, sys, time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import RUNNER_TEMPLATES, TurnRequest, _validate_cli_arg, get_adapter
from .store import SwarmStore, _public_worker, validate_ident
from .supervisor import _has_pending_work, _is_pid_alive, _signal_pgid, ensure_supervisor, run_supervisor_loop
from .worktree import WorkspaceManager

CLAUDE_MODELS: tuple[str, ...] = ("sonnet", "opus", "haiku")
CLAUDE_MODELS_ALL: tuple[str, ...] = ("sonnet", "opus", "haiku", "claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5")
_BATCH_LIMIT, _KILL_POLL_SEC, _KILL_GRACE_SEC = 200, 0.05, 3.0
_WORKER_ENV_KEYS = ("SWARMCTL_WORKER_TOKEN", "SWARMCTL_ROLE", "SWARMCTL_AGENT")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]")


def _sanitize_human(text: Any) -> str:
    s = _ANSI_RE.sub("", str(text)).replace("\r\n", "\n").replace("\r", "\n")
    return _CTRL_RE.sub(" ", s).replace("\n", "\n  ")


def _finite_float(val: Any, flag: str, *, min_val: float = 0.0, strict_gt: bool = False) -> float:
    f = float(val)
    if not math.isfinite(f) or (f <= min_val if strict_gt else f < min_val):
        op = ">" if strict_gt else ">="
        raise ValueError(f"{flag} must be a finite number {op} {min_val}")
    return f


def resolve_repo_root(repo: str | None = None, cwd: Path | None = None) -> Path:
    base_cwd = (cwd or Path.cwd()).resolve()
    if repo is not None:
        p = Path(repo).expanduser().resolve()
        if not p.is_dir():
            raise FileNotFoundError(f"Repository directory does not exist: {repo}")
        return p
    parts = base_cwd.parts
    for i in range(len(parts) - 3, 0, -1):
        if parts[i] == ".swarm" and parts[i + 2] == "worktrees":
            return Path(*parts[:i]).resolve()
    if base_cwd.is_dir():
        try:
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
        except FileNotFoundError:
            pass
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


def _wake_supervisor_best_effort(swarm_dir: Path) -> None:
    try:
        _safe_ensure_supervisor(swarm_dir)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"warning: failed to wake supervisor: {exc}", file=sys.stderr)


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
    p = sub.add_parser(name, allow_abbrev=False, **kwargs)
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, dest="json_sub")
    for flags, opts in specs:
        p.add_argument(*(flags if isinstance(flags, tuple) else (flags,)), **opts)
    return p


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="swarmctl", description="Minimalist local multi-agent swarm CLI", allow_abbrev=False)
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
    _finite_float(timeout, "--timeout", min_val=0.0)
    repo_root, wm = Path(store.get_meta()["repo_root"]).resolve(), WorkspaceManager()
    w = store.get_worker(name)
    if w is None:
        raise ValueError(f"Unknown worker: {name!r}")
    wt_path = Path(w["workspace_path"])
    if w["state"] == "killed" and not (force and w["workspace_mode"] == "share"):
        raise ValueError(f"Worker {name!r} is already killed")
    if w["workspace_mode"] == "share" and not force and (wt_path.exists() or wt_path.is_symlink()):
        is_clean, dirty_out = wm.verify_clean(wt_path)
        if not is_clean:
            raise RuntimeError(f"Refusing to kill worker {name!r} with dirty worktree {wt_path} (merge changes or pass --force):\n{dirty_out}")
    swarm_dir.mkdir(parents=True, exist_ok=True)
    lock_f = open(swarm_dir / "supervisor.lock", "a+", encoding="utf-8")
    holds_lock, should_wake = False, False
    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            holds_lock = True
        except BlockingIOError:
            holds_lock = False
        if not holds_lock:
            if w["state"] != "killed":
                store.mark_killing(name)
                _wake_supervisor_best_effort(swarm_dir)
            deadline = time.monotonic() + timeout
            while True:
                curr = store.get_worker(name)
                if curr is not None and curr["state"] == "killed":
                    if force and curr["workspace_mode"] == "share":
                        wm.remove(repo_root, Path(curr["workspace_path"]), curr["branch_name"], "share", force=True)
                    return _public_worker(curr)
                try:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    holds_lock = True
                    break
                except BlockingIOError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Timed out waiting {timeout}s for supervisor to kill worker {name!r}")
                time.sleep(_KILL_POLL_SEC)
        w_curr = store.get_worker(name)
        if w_curr is None:
            raise ValueError(f"Unknown worker: {name!r}")
        curr_wt = Path(w_curr["workspace_path"])
        if w_curr["state"] == "killed":
            if force and w_curr["workspace_mode"] == "share":
                wm.remove(repo_root, curr_wt, w_curr["branch_name"], "share", force=True)
                should_wake = True
                return _public_worker(w_curr)
            raise ValueError(f"Worker {name!r} is already killed")
        if w_curr["workspace_mode"] == "share" and not force and (curr_wt.exists() or curr_wt.is_symlink()):
            is_clean, dirty_out = wm.verify_clean(curr_wt)
            if not is_clean:
                raise RuntimeError(f"Refusing to kill worker {name!r} with dirty worktree {curr_wt} (merge changes or pass --force):\n{dirty_out}")
        pid = int(w_curr["pid"] or 0)
        tok = str(w_curr["worker_token"])
        if pid > 0 and _is_pid_alive(pid) and not _verify_pid_worker_token(pid, tok):
            raise RuntimeError(f"Refusing to signal PID {pid} for worker {name!r}: worker token mismatch")
        should_wake = True
        store.mark_killing(name)
        if pid > 0 and _is_pid_alive(pid):
            _signal_pgid(pid, None, signal.SIGTERM)
            g_deadline = time.monotonic() + _KILL_GRACE_SEC
            while _is_pid_alive(pid) and time.monotonic() < g_deadline:
                time.sleep(_KILL_POLL_SEC)
            if _is_pid_alive(pid):
                if not _verify_pid_worker_token(pid, tok):
                    raise RuntimeError(f"Refusing to SIGKILL PID {pid} for worker {name!r}: worker token mismatch")
                _signal_pgid(pid, None, signal.SIGKILL)
                k_deadline = time.monotonic() + 0.5
                while _is_pid_alive(pid) and time.monotonic() < k_deadline:
                    time.sleep(_KILL_POLL_SEC)
                if _is_pid_alive(pid):
                    raise RuntimeError(f"Worker {name!r} PID {pid} did not terminate after SIGKILL")
        if w_curr["workspace_mode"] == "share":
            wm.remove(repo_root, curr_wt, w_curr["branch_name"], "share", force=force)
        return store.mark_killed(name)
    finally:
        if holds_lock:
            try:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        lock_f.close()
        if holds_lock and should_wake:
            try:
                if _has_pending_work(store):
                    _wake_supervisor_best_effort(swarm_dir)
            except (OSError, RuntimeError, sqlite3.Error) as exc:
                print(f"warning: post-kill supervisor check failed: {exc}", file=sys.stderr)


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
            token = os.environ.get("SWARMCTL_WORKER_TOKEN") or ""
            if not token:
                raise PermissionError("Worker mode requires SWARMCTL_WORKER_TOKEN for MCP server")
            with _open_existing_store(swarm_dir) as st:
                owner = st.verify_worker_token(token)
            env_agent = os.environ.get("SWARMCTL_AGENT") or owner
            if (agent is not None and agent != owner) or env_agent != owner:
                raise PermissionError(f"Worker token belongs to {owner!r}, cannot start MCP as {agent or env_agent!r}")
            role, agent = "worker", owner
        else:
            role = role or "coordinator"
            agent = agent or ("coordinator" if role == "coordinator" else (os.environ.get("SWARMCTL_AGENT") or ""))
        try:
            from .mcp_server import serve_stdio  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            if exc.name in ("swarmctl.mcp_server", "mcp_server"):
                raise RuntimeError("MCP server is not available yet") from exc
            raise
        return int(serve_stdio(swarm_dir, agent_name=agent, role=role) or 0)

    if cmd == "init":
        if args.max_concurrent < 1 or args.max_turns < 1:
            raise ValueError("max_concurrent and max_turns must be >= 1")
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
            _emit(store.set_title(args.title), as_json, lambda m: print(f"Swarm {m['swarm_id']}: {_sanitize_human(m['title'])}", flush=True))
            return 0
        if cmd == "status":
            _emit(store.read_board(status=True), as_json, lambda d: print(
                f"Swarm: {d['swarm_id']} (head_seq={d['head_seq']}) {_sanitize_human(d['title'])}\n"
                + "\n".join(f"  {w['name']}: {w['state']} ({w['runner']} {_sanitize_human(w['model'])})"
                            + (f" error={_sanitize_human(w['last_error'])}" if w.get("last_error") else "") for w in d["workers"]), flush=True))
            return 0
        if cmd == "model":
            _emit(store.switch_model(args.name, _validate_cli_arg(args.model, "model")), as_json,
                  lambda w: print(f"Worker {w['name']} model -> {_sanitize_human(w['model'])}", flush=True))
            return 0
        if cmd == "add":
            validate_ident(args.name, "worker")
            if not isinstance(args.brief, str) or not args.brief.strip():
                raise ValueError("Worker brief must be non-empty")
            existing = store.get_worker(args.name)
            if existing is not None and existing["state"] != "killed":
                raise ValueError(f"Worker {args.name!r} already exists in state {existing['state']!r}")
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
            created_wt = args.workspace == "share"
            try:
                raw_w = store.add_worker(args.name, args.brief, runner=resolved_runner, model=resolved_model,
                                         workspace_mode=args.workspace, workspace_path=str(wt_path),
                                         branch_name=branch, permission_mode=perm_mode, fork_from=args.fork)
            except Exception:
                if created_wt:
                    try:
                        wm.remove(repo_root, wt_path, branch, "share", force=True)
                    except Exception:
                        pass
                raise
            _emit({**_public_worker(raw_w), "brief_seq": int(raw_w["brief_seq"])}, as_json,
                  lambda w: print(f"Added worker {w['name']} ({w['workspace_mode']}, brief #{w['brief_seq']})", flush=True))
            if not args.no_wake:
                _wake_supervisor_best_effort(swarm_dir)
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
            _emit(msg, as_json, lambda m: print(f"[#{m['seq']}] {_sanitize_human(m['sender'])}: {_sanitize_human(m['body'])}", flush=True))
            if not worker_mode and not args.no_wake:
                _wake_supervisor_best_effort(swarm_dir)
            return 0
        if cmd == "read":
            if args.limit < 0:
                raise ValueError("--limit must be >= 0")
            seq_list: list[int] | None = None
            if args.seqs is not None:
                parts = [s.strip() for s in str(args.seqs).split(",")]
                if not parts or any(not p or not p.isdigit() for p in parts):
                    raise ValueError(f"Invalid --seqs comma-separated integers: {args.seqs!r}")
                seq_list = [int(p) for p in parts]
            res = store.read_board(since=args.since, limit=args.limit, seqs=seq_list, status=bool(args.status))
            if args.status:
                _emit(res, as_json, lambda d: print(f"Swarm: {d['swarm_id']} (head_seq={d['head_seq']}) {_sanitize_human(d['title'])}\n" + "\n".join(f"  {w['name']}: {w['state']}" for w in d["workers"]), flush=True))
            else:
                _emit(res, as_json, lambda d: print("\n".join(f"[#{m['seq']}] {_sanitize_human(m['sender'])}: {_sanitize_human(m['body'])}" for m in d["messages"]), flush=True) if d["messages"] else None)
            return 0
        if cmd == "wait":
            for_name = str(args.for_name).strip()
            if not for_name or for_name.startswith("@"):
                raise ValueError("--for must be a valid non-empty agent name without leading '@'")
            timeout = _finite_float(args.timeout, "--timeout", min_val=0.0)
            poll_sec = _finite_float(args.poll_sec, "--poll-sec", min_val=0.0, strict_gt=True)
            deadline = time.monotonic() + timeout
            cursor, all_msgs = int(args.since), []
            while True:
                batch, head = _drain_since(store, cursor)
                if batch:
                    all_msgs.extend(batch)
                    cursor = int(batch[-1]["seq"])
                if any(m["sender"] != for_name and (not args.mentions_only or for_name in m["mentions"] or "all" in m["mentions"]) for m in all_msgs):
                    _emit({"messages": all_msgs, "timed_out": False, "head_seq": head}, as_json,
                          lambda d: print("\n".join(f"[#{m['seq']}] {_sanitize_human(m['sender'])}: {_sanitize_human(m['body'])}" for m in d["messages"]), flush=True))
                    return 0
                if time.monotonic() >= deadline:
                    _emit({"messages": [], "timed_out": True, "head_seq": head}, as_json, lambda _: None)
                    return 0
                time.sleep(min(poll_sec, max(0.0, deadline - time.monotonic())))
        if cmd == "tail":
            poll_sec = _finite_float(args.poll_sec, "--poll-sec", min_val=0.0, strict_gt=True)
            p_msg = (lambda m: print(json.dumps(m), flush=True)) if as_json else (lambda m: print(f"[#{m['seq']}] {_sanitize_human(m['sender'])}: {_sanitize_human(m['body'])}", flush=True))
            try:
                if args.since is None:
                    init_res = store.read_board(limit=20)
                    init_msgs = init_res["messages"]
                    cursor = int(init_msgs[-1]["seq"]) if init_msgs else int(init_res["head_seq"])
                else:
                    init_msgs, _ = _drain_since(store, args.since)
                    cursor = int(init_msgs[-1]["seq"]) if init_msgs else int(args.since)
                for m in init_msgs:
                    p_msg(m)
                if not args.follow:
                    return 0
                while True:
                    time.sleep(poll_sec)
                    new_msgs, _ = _drain_since(store, cursor)
                    for m in new_msgs:
                        p_msg(m)
                    if new_msgs:
                        cursor = int(new_msgs[-1]["seq"])
            except KeyboardInterrupt:
                return 0
        if cmd == "supervise":
            store.get_meta()
            kw = dict(
                idle_timeout_sec=_finite_float(args.idle_timeout, "--idle-timeout", min_val=0.0),
                tick_sec=_finite_float(args.tick_sec, "--tick-sec", min_val=0.0, strict_gt=True),
                turn_timeout_sec=_finite_float(args.turn_timeout, "--turn-timeout", min_val=0.0, strict_gt=True),
                kill_grace_sec=_finite_float(args.kill_grace, "--kill-grace", min_val=0.0),
            )
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
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass
        return 0
    except (ValueError, PermissionError, RuntimeError, FileNotFoundError, ImportError, sqlite3.Error, OverflowError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
