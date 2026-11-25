"""NDJSON stdio MCP server (JSON-RPC 2.0) with coordinator/worker role isolation (`CUJ-5`, `INV-7`, `INV-8`)."""
from __future__ import annotations

import fcntl
import io
import json
import math
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NamedTuple

from . import __version__
from .adapters import RUNNER_TEMPLATES, TurnRequest, _validate_cli_arg, get_adapter
from .store import SwarmStore, _public_worker, validate_ident
from .supervisor import _has_pending_work, _is_pid_alive, _signal_pgid, ensure_supervisor
from .worktree import WorkspaceManager

CLAUDE_MODELS = ("sonnet", "opus", "haiku")
CLAUDE_MODELS_ALL = ("sonnet", "opus", "haiku", "claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5")
_PROTOCOLS = ("2025-03-26", "2024-11-05")
_BATCH_LIMIT, _POLL_SEC, _KILL_POLL_SEC, _KILL_GRACE_SEC = 200, 0.1, 0.05, 3.0
_WORKER_ENV_KEYS = ("SWARMCTL_WORKER_TOKEN", "SWARMCTL_ROLE", "SWARMCTL_AGENT")
_E_PARSE, _E_REQ, _E_METHOD, _E_PARAMS, _E_INTERNAL = -32700, -32600, -32601, -32602, -32603
_ACTIONS = ("status", "models", "add", "model", "kill", "title")
_WORKER_TOOLS = ("post_message", "read_board")
_ALL_TOOLS = ("swarm", "post_message", "read_board", "swarm_wait")


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class _Ctx(NamedTuple):
    swarm_dir: Path
    swarm_id: str
    repo_root: Path
    role: str
    agent: str
    token: str | None


# ---------------------------------------------------------------- arg helpers
def _finite_float(val: Any, name: str, *, lo: float = 0.0, hi: float | None = None) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"{name} must be a number")
    f = float(val)
    if not math.isfinite(f) or f < lo or (hi is not None and f > hi):
        rng = f">= {lo}" if hi is None else f"in [{lo}, {hi}]"
        raise ValueError(f"{name} must be a finite number {rng}")
    return f


def _int_arg(val: Any, name: str, *, lo: int = 0) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{name} must be an integer")
    if val < lo:
        raise ValueError(f"{name} must be >= {lo}")
    return val


def _bool_arg(val: Any, name: str) -> bool:
    if not isinstance(val, bool):
        raise ValueError(f"{name} must be a boolean")
    return val


def _str_arg(val: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(val, str) or (not allow_empty and not val.strip()):
        raise ValueError(f"{name} must be a {'' if allow_empty else 'non-empty '}string")
    return val


def _check_keys(args: dict, allowed: set[str], required: set[str]) -> None:
    unknown = set(args) - allowed
    if unknown:
        raise ValueError(f"Unknown argument(s): {sorted(unknown)}")
    missing = required - set(args)
    if missing:
        raise ValueError(f"Missing required argument(s): {sorted(missing)}")


# ------------------------------------------------------------- identity/paths
def _resolve_swarm_dir(swarm_dir: Any) -> tuple[Path, str, Path]:
    raw = Path(swarm_dir)
    if raw.parent.name != ".swarm":
        raise ValueError(f"swarm_dir must be <repo>/.swarm/<id>, got {str(raw)!r}")
    validate_ident(raw.name, "swarm")
    return raw, raw.name, raw.parent.parent.resolve()


def _resolve_identity(raw_dir: Path, agent_name: str | None, role: str) -> tuple[str, str, str | None]:
    if role not in ("coordinator", "worker"):
        raise ValueError(f"Invalid role: {role!r}")
    worker_env = os.environ.get("SWARMCTL_ROLE") == "worker" or bool(os.environ.get("SWARMCTL_WORKER_TOKEN"))
    if worker_env and role == "coordinator":
        raise PermissionError("Worker role cannot start MCP server with role coordinator")
    db = raw_dir / "board.db"
    if role == "worker" or worker_env:
        token = os.environ.get("SWARMCTL_WORKER_TOKEN") or ""
        if not token:
            raise PermissionError("Worker mode requires SWARMCTL_WORKER_TOKEN for MCP server")
        if not db.is_file():
            raise FileNotFoundError(f"Swarm store not initialized at {db}")
        with SwarmStore(db) as st:
            owner = st.verify_worker_token(token)
        env_agent = os.environ.get("SWARMCTL_AGENT")
        if (agent_name and agent_name != owner) or (env_agent and env_agent != owner):
            raise PermissionError(f"Worker token belongs to {owner!r}, cannot start MCP as {agent_name or env_agent!r}")
        return "worker", owner, token
    agent = agent_name or "coordinator"
    if agent != "coordinator":
        validate_ident(agent, "worker")
        if db.is_file():
            with SwarmStore(db) as st:
                if st.get_worker(agent) is not None:
                    raise PermissionError(f"Coordinator agent name {agent!r} collides with an existing worker")
    return "coordinator", agent, None


def _wake(swarm_dir: Path) -> None:
    saved = {k: os.environ.pop(k) for k in _WORKER_ENV_KEYS if k in os.environ}
    try:
        ensure_supervisor(swarm_dir)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"warning: failed to wake supervisor: {exc}", file=sys.stderr)
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


def _verify_pid_worker_token(pid: int, token: str) -> bool:
    try:
        return f"SWARMCTL_WORKER_TOKEN={token}".encode("utf-8") in Path(f"/proc/{pid}/environ").read_bytes().split(b"\x00")
    except OSError:
        return False


def _models_payload(all_models: bool) -> dict[str, Any]:
    return {
        "default_runner": "claude",
        "claude_models": list(CLAUDE_MODELS_ALL if all_models else CLAUDE_MODELS),
        "runners": {"claude": {"guardrails": ["readonly", "edit", "unsafe"]},
                    **{k: {"guardrails": [m for m, f in t["permission_flags"].items() if f is not None]}
                       for k, t in RUNNER_TEMPLATES.items()}},
    }


# --------------------------------------------------------------------- schema
def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_S, _B = {"type": "string"}, {"type": "boolean"}
_I0 = {"type": "integer", "minimum": 0}
_TOOLS: dict[str, dict[str, Any]] = {
    "swarm": {
        "name": "swarm",
        "description": "Manage the swarm (coordinator only): status, models, add, model, kill, title.",
        "inputSchema": _obj({
            "action": {"type": "string", "enum": list(_ACTIONS)}, "name": _S, "brief": _S, "model": _S, "runner": _S,
            "fork": _S, "title": _S, "workspace": {"type": "string", "enum": ["inherit", "share"]},
            "all": _B, "unsafe": _B, "force": _B, "timeout_sec": {"type": "number", "minimum": 0},
        }, ["action"]),
    },
    "post_message": {
        "name": "post_message", "description": "Post a message to the shared board (use @name or @all to mention).",
        "inputSchema": _obj({"text": _S, "sender": _S}, ["text"]),
    },
    "read_board": {
        "name": "read_board", "description": "Read messages from the shared board (or swarm status, coordinator only).",
        "inputSchema": _obj({"since": _I0, "limit": _I0, "seqs": {"type": "array", "items": _I0}, "status": _B}, []),
    },
    "swarm_wait": {
        "name": "swarm_wait", "description": "Block until a message mentioning the agent arrives or timeout (coordinator only).",
        "inputSchema": _obj({"since": _I0, "mentions_only": _B, "for_agent": _S,
                             "timeout_sec": {"type": "number", "minimum": 0, "maximum": 300}}, ["since"]),
    },
}


def _tools_for(role: str) -> list[dict[str, Any]]:
    names = _ALL_TOOLS if role == "coordinator" else _WORKER_TOOLS
    return [_TOOLS[n] for n in names]


# ------------------------------------------------------------------ store use
def _open(ctx: _Ctx, create: bool = False) -> SwarmStore | None:
    db = ctx.swarm_dir / "board.db"
    if create:
        with SwarmStore(db) as st:
            st.init_swarm(ctx.swarm_id, str(ctx.repo_root))
        return SwarmStore(db)
    return SwarmStore(db) if db.is_file() else None


def _kill_worker(ctx: _Ctx, store: SwarmStore, name: str, force: bool, timeout: float) -> dict[str, Any]:
    swarm_dir, wm = ctx.swarm_dir, WorkspaceManager()
    repo_root = Path(store.get_meta()["repo_root"]).resolve()
    w = store.get_worker(name)
    if w is None:
        raise ValueError(f"Unknown worker: {name!r}")
    wt_path = Path(w["workspace_path"])
    if w["state"] == "killed" and not (force and w["workspace_mode"] == "share"):
        raise ValueError(f"Worker {name!r} is already killed")
    if w["workspace_mode"] == "share" and not force and (wt_path.exists() or wt_path.is_symlink()):
        clean, out = wm.verify_clean(wt_path)
        if not clean:
            raise RuntimeError(f"Refusing to kill worker {name!r} with dirty worktree {wt_path} (merge changes or pass force):\n{out}")
    swarm_dir.mkdir(parents=True, exist_ok=True)
    lock_f = open(swarm_dir / "supervisor.lock", "a+", encoding="utf-8")
    holds_lock, should_wake = False, False
    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            holds_lock = True
        except BlockingIOError:
            pass
        if not holds_lock:
            if w["state"] != "killed":
                store.mark_killing(name)
                _wake(swarm_dir)
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
        wc = store.get_worker(name)
        if wc is None:
            raise ValueError(f"Unknown worker: {name!r}")
        cwt = Path(wc["workspace_path"])
        if wc["state"] == "killed":
            if force and wc["workspace_mode"] == "share":
                wm.remove(repo_root, cwt, wc["branch_name"], "share", force=True)
                should_wake = True
                return _public_worker(wc)
            raise ValueError(f"Worker {name!r} is already killed")
        if wc["workspace_mode"] == "share" and not force and (cwt.exists() or cwt.is_symlink()):
            clean, out = wm.verify_clean(cwt)
            if not clean:
                raise RuntimeError(f"Refusing to kill worker {name!r} with dirty worktree {cwt} (merge changes or pass force):\n{out}")
        pid, tok = int(wc["pid"] or 0), str(wc["worker_token"])
        if pid > 0 and _is_pid_alive(pid) and not _verify_pid_worker_token(pid, tok):
            raise RuntimeError(f"Refusing to signal PID {pid} for worker {name!r}: worker token mismatch")
        should_wake = True
        store.mark_killing(name)
        if pid > 0 and _is_pid_alive(pid):
            _signal_pgid(pid, None, signal.SIGTERM)
            g = time.monotonic() + _KILL_GRACE_SEC
            while _is_pid_alive(pid) and time.monotonic() < g:
                time.sleep(_KILL_POLL_SEC)
            if _is_pid_alive(pid):
                if not _verify_pid_worker_token(pid, tok):
                    raise RuntimeError(f"Refusing to SIGKILL PID {pid} for worker {name!r}: worker token mismatch")
                _signal_pgid(pid, None, signal.SIGKILL)
                k = time.monotonic() + 0.5
                while _is_pid_alive(pid) and time.monotonic() < k:
                    time.sleep(_KILL_POLL_SEC)
                if _is_pid_alive(pid):
                    raise RuntimeError(f"Worker {name!r} PID {pid} did not terminate after SIGKILL")
        if wc["workspace_mode"] == "share":
            wm.remove(repo_root, cwt, wc["branch_name"], "share", force=force)
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
                    _wake(swarm_dir)
            except (OSError, RuntimeError, sqlite3.Error) as exc:
                print(f"warning: post-kill supervisor check failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------- tool bodies
def _t_swarm(ctx: _Ctx, a: dict[str, Any]) -> Any:
    _check_keys(a, {"action", "name", "brief", "model", "runner", "fork", "title", "workspace", "all", "unsafe", "force", "timeout_sec"}, {"action"})
    action = _str_arg(a["action"], "action")
    if action not in _ACTIONS:
        raise ValueError(f"Invalid action: {action!r}")
    if action == "models":
        return _models_payload(_bool_arg(a.get("all", False), "all"))
    if action == "status":
        st = _open(ctx)
        if st is None:
            return {"swarm_id": ctx.swarm_id, "title": "", "head_seq": 0, "workers": []}
        with st:
            return st.read_board(status=True)
    if action == "title":
        title = _str_arg(a.get("title"), "title", allow_empty=True) if "title" in a else _str_arg(None, "title")
        st = _open(ctx, create=True)
        with st:  # type: ignore[union-attr]
            return st.set_title(title)
    if action in ("model", "kill"):
        name = _str_arg(a.get("name"), "name")
        model = _validate_cli_arg(a.get("model"), "model") if action == "model" else None
        timeout = _finite_float(a.get("timeout_sec", 10.0), "timeout_sec", lo=0.0) if action == "kill" else 0.0
        force = _bool_arg(a.get("force", False), "force") if action == "kill" else False
        st = _open(ctx)
        if st is None:
            raise ValueError(f"Unknown worker: {name!r}")
        with st:
            if action == "model":
                return st.switch_model(name, model)  # type: ignore[arg-type]
            return _kill_worker(ctx, st, name, force, timeout)
    # add
    name = validate_ident(_str_arg(a.get("name"), "name"), "worker")
    brief = _str_arg(a.get("brief"), "brief")
    workspace = a.get("workspace", "inherit")
    if workspace not in ("inherit", "share"):
        raise ValueError(f"Invalid workspace: {workspace!r}")
    unsafe = _bool_arg(a.get("unsafe", False), "unsafe")
    fork = _str_arg(a["fork"], "fork") if a.get("fork") is not None else None
    if unsafe and os.environ.get("SWARMCTL_DENY_UNSAFE") == "1":
        raise PermissionError("unsafe workers are denied by SWARMCTL_DENY_UNSAFE=1")
    st = _open(ctx, create=True)
    with st:  # type: ignore[union-attr]
        existing = st.get_worker(name)
        if existing is not None and existing["state"] != "killed":
            raise ValueError(f"Worker {name!r} already exists in state {existing['state']!r}")
        meta = st.get_meta()
        runner = _str_arg(a["runner"], "runner") if a.get("runner") is not None else str(meta["default_runner"])
        model = str(meta["default_model"]) if a.get("model") is None else (
            _validate_cli_arg(a["model"], "model") if a["model"] != "" else "")
        perm = "unsafe" if unsafe else ("readonly" if workspace == "inherit" else "edit")
        get_adapter(runner).build_command(TurnRequest(
            swarm_id=ctx.swarm_id, worker_name=name, worker_token="dry-run-token", runner=runner,
            model=model, workspace_path=str(ctx.repo_root), permission_mode=perm, session_id="",
            fork_session_id="", transcript_seed="", prompt_delta="", delivered_max_seq=0))
        wm = WorkspaceManager()
        wt_path, branch = wm.create(ctx.repo_root, ctx.swarm_dir, name, workspace, swarm_id=ctx.swarm_id)
        try:
            raw = st.add_worker(name, brief, runner=runner, model=model, workspace_mode=workspace,
                                workspace_path=str(wt_path), branch_name=branch, permission_mode=perm, fork_from=fork)
        except Exception:
            if workspace == "share":
                try:
                    wm.remove(ctx.repo_root, wt_path, branch, "share", force=True)
                except Exception:
                    pass
            raise
        out = {**_public_worker(raw), "brief_seq": int(raw["brief_seq"])}
    _wake(ctx.swarm_dir)
    return out


def _t_post(ctx: _Ctx, a: dict[str, Any]) -> Any:
    _check_keys(a, {"text", "sender"}, {"text"})
    text = _str_arg(a["text"], "text")
    if ctx.role == "worker":
        sender = a.get("sender")
        if sender is not None and sender != ctx.agent:
            raise PermissionError(f"Worker {ctx.agent!r} cannot post as {sender!r}")
        with SwarmStore(ctx.swarm_dir / "board.db") as st:
            return st.post_message(ctx.agent, text, token=ctx.token)
    sender = _str_arg(a["sender"], "sender") if a.get("sender") is not None else ctx.agent
    if not sender.strip():
        raise ValueError("sender must be non-empty")
    st = _open(ctx, create=True)
    with st:  # type: ignore[union-attr]
        if st.get_worker(sender) is not None:
            raise PermissionError(f"Sender {sender!r} is an existing worker name")
        msg = st.post_message(sender, text)
    _wake(ctx.swarm_dir)
    return msg


def _t_read(ctx: _Ctx, a: dict[str, Any]) -> Any:
    _check_keys(a, {"since", "limit", "seqs", "status"}, set())
    since = _int_arg(a["since"], "since") if a.get("since") is not None else None
    limit = _int_arg(a["limit"], "limit") if "limit" in a else 20
    seqs = None
    if a.get("seqs") is not None:
        if not isinstance(a["seqs"], list):
            raise ValueError("seqs must be an array of integers")
        seqs = [_int_arg(s, "seqs[]") for s in a["seqs"]]
    status = _bool_arg(a.get("status", False), "status")
    if ctx.role == "worker" and status:
        raise PermissionError("Worker role cannot read swarm status")
    st = _open(ctx)
    if st is None:
        return {"swarm_id": ctx.swarm_id, "title": "", "head_seq": 0, "workers": []} if status else {"messages": [], "head_seq": 0}
    with st:
        return st.read_board(since=since, limit=limit, seqs=seqs, status=status)


def _t_wait(ctx: _Ctx, a: dict[str, Any]) -> Any:
    _check_keys(a, {"since", "mentions_only", "for_agent", "timeout_sec"}, {"since"})
    since = _int_arg(a["since"], "since")
    mentions_only = _bool_arg(a.get("mentions_only", True), "mentions_only")
    for_agent = _str_arg(a["for_agent"], "for_agent").strip() if a.get("for_agent") is not None else ctx.agent
    if not for_agent or for_agent.startswith("@"):
        raise ValueError("for_agent must be a non-empty name without leading '@'")
    timeout = _finite_float(a.get("timeout_sec", 45.0), "timeout_sec", lo=0.0, hi=300.0)
    deadline = time.monotonic() + timeout
    cursor, head, all_msgs = since, since, []
    db = ctx.swarm_dir / "board.db"
    while True:
        if db.is_file():
            try:
                with SwarmStore(db) as st:
                    batch, head = _drain_since(st, cursor)
                if batch:
                    all_msgs.extend(batch)
                    cursor = int(batch[-1]["seq"])
            except (sqlite3.OperationalError, RuntimeError):
                pass
        if any(m["sender"] != for_agent and (not mentions_only or for_agent in m["mentions"] or "all" in m["mentions"]) for m in all_msgs):
            return {"messages": all_msgs, "timed_out": False, "head_seq": head}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"messages": [], "timed_out": True, "head_seq": head}
        time.sleep(min(_POLL_SEC, remaining))


_HANDLERS = {"swarm": _t_swarm, "post_message": _t_post, "read_board": _t_read, "swarm_wait": _t_wait}
_COORD_ONLY = {"swarm", "swarm_wait"}


# -------------------------------------------------------------------- dispatch
def _valid_id(v: Any) -> bool:
    return isinstance(v, str) or (isinstance(v, int) and not isinstance(v, bool))


def _err(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _call_tool(ctx: _Ctx, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise _RpcError(_E_PARAMS, "params must be an object")
    name, args = params.get("name"), params.get("arguments", {})
    if not isinstance(name, str):
        raise _RpcError(_E_PARAMS, "name must be a string")
    if not isinstance(args, dict):
        raise _RpcError(_E_PARAMS, "arguments must be an object")
    if name not in _HANDLERS:
        raise _RpcError(_E_PARAMS, f"Unknown tool: {name!r}")
    try:
        if ctx.role == "worker":
            if name in _COORD_ONLY:
                raise PermissionError(f"Worker role cannot call {name!r}")
            with SwarmStore(ctx.swarm_dir / "board.db") as st:
                st.verify_worker_token(ctx.token or "", expected_name=ctx.agent)
        res = _HANDLERS[name](ctx, args)
        return {"content": [{"type": "text", "text": json.dumps(res, allow_nan=False)}], "isError": False}
    except PermissionError as exc:
        raise _RpcError(_E_REQ, str(exc))
    except (ValueError, TypeError) as exc:
        raise _RpcError(_E_PARAMS, str(exc))
    except (RuntimeError, OSError, sqlite3.Error) as exc:  # FileNotFoundError is an OSError
        return {"content": [{"type": "text", "text": json.dumps({"error": str(exc)})}], "isError": True}


def _handle(ctx: _Ctx, msg: Any) -> dict[str, Any] | None:
    if isinstance(msg, dict) and "id" in msg and "method" not in msg and ("result" in msg or "error" in msg):
        return None
    rid = msg.get("id") if isinstance(msg, dict) and _valid_id(msg.get("id")) else None
    if (not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str)
            or ("id" in msg and not _valid_id(msg["id"]))):
        return _err(rid, _E_REQ, "Invalid Request")
    if "id" not in msg:
        return None
    method, params = msg["method"], msg.get("params")
    try:
        if method == "initialize":
            req = params.get("protocolVersion") if isinstance(params, dict) else None
            result: Any = {"protocolVersion": req if req in _PROTOCOLS else "2024-11-05", "capabilities": {"tools": {}},
                           "serverInfo": {"name": "swarmctl", "version": __version__}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": _tools_for(ctx.role)}
        elif method == "tools/call":
            result = _call_tool(ctx, params)
        else:
            return _err(rid, _E_METHOD, f"Method not found: {method}")
    except _RpcError as exc:
        return _err(rid, exc.code, exc.message)
    except Exception as exc:  # never crash the loop
        return _err(rid, _E_INTERNAL, f"Internal error: {exc}")
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def serve_stdio(swarm_dir: Path | str, agent_name: str | None = None, role: str = "coordinator", *,
                stdin: Any = None, stdout: Any = None) -> int:
    raw_dir, swarm_id, repo_root = _resolve_swarm_dir(swarm_dir)
    eff_role, agent, token = _resolve_identity(raw_dir, agent_name, role)
    ctx = _Ctx(raw_dir, swarm_id, repo_root, eff_role, agent, token)
    proto_fd: int | None = None
    if stdout is None:
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        proto_fd = os.dup(1)
        os.set_inheritable(proto_fd, False)
        os.dup2(2, 1)
        out: Any = os.fdopen(proto_fd, "w", encoding="utf-8", buffering=1, closefd=False)
    else:
        out = stdout
    inp = stdin if stdin is not None else io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="\n")

    def emit(obj: dict[str, Any]) -> None:
        out.write(json.dumps(obj, allow_nan=False, separators=(",", ":")) + "\n")
        out.flush()

    try:
        for line in inp:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                emit(_err(None, _E_PARSE, "Parse error"))
                continue
            resp = _handle(ctx, msg)
            if resp is not None:
                emit(resp)
        return 0
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    finally:
        if proto_fd is not None:
            try:
                out.flush()
            except (OSError, ValueError):
                pass
            os.dup2(proto_fd, 1)
            os.close(proto_fd)
