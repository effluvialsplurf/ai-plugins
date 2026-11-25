"""Single-instance flock-locked lazy local supervisor (`ADR-3`, `INV-2..6`, `D5..D8`)."""
from __future__ import annotations

import argparse, fcntl, os, signal, subprocess, sys, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .adapters import BaseAdapter, TurnRequest, format_prompt_delta, get_adapter
from .store import SwarmStore
from .worktree import WorkspaceManager


@dataclass
class _ActiveTurn:
    req: TurnRequest
    adapter: BaseAdapter
    proc: subprocess.Popen[bytes]
    started_at: float
    before_turn_count: int
    term_sent_at: float | None = None


def _reap_zombie_pid(pid: int) -> None:
    for target in (-pid, pid):
        try:
            while os.waitpid(target, os.WNOHANG)[0] > 0:
                pass
        except (ChildProcessError, OSError):
            pass


def _proc_stat_fields(pid: int | str) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="ignore")
        rparen = raw.rfind(")")
        return raw[rparen + 1 :].split() if rparen != -1 else None
    except OSError:
        return None


def _is_pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    _reap_zombie_pid(pid)
    fields = _proc_stat_fields(pid)
    if fields and fields[0] == "Z":
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def _pgid_has_only_zombies(pgid: int) -> bool:
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return False
    for entry in proc_dir.iterdir():
        if entry.name.isdigit():
            fields = _proc_stat_fields(entry.name)
            try:
                if fields and len(fields) >= 3 and int(fields[2]) == pgid and fields[0] != "Z":
                    return False
            except ValueError:
                continue
    return True


def _is_pgid_alive(pid: int, proc: subprocess.Popen[bytes] | None) -> bool:
    if proc is not None:
        proc.poll()
    _reap_zombie_pid(pid)
    try:
        os.killpg(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return _is_pid_alive(pid)
    return not (not _is_pid_alive(pid) and _pgid_has_only_zombies(pid))


def _reap_pgid_step(
    pid: int, proc: subprocess.Popen[bytes] | None, term_sent_at: float | None, now: float, kill_grace_sec: float
) -> tuple[bool, float]:
    if not _is_pgid_alive(pid, proc):
        return True, (term_sent_at or now)
    if term_sent_at is None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        term_sent_at = now
    elif now - term_sent_at >= kill_grace_sec:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    return (not _is_pgid_alive(pid, proc)), term_sent_at


def _has_pending_work(store: SwarmStore) -> bool:
    with store._read_tx() as conn:
        meta = conn.execute("SELECT max_turns FROM meta WHERE id = 1").fetchone()
        if meta is None:
            return False
        if int(conn.execute("SELECT COUNT(*) FROM workers WHERE state IN ('working', 'killing')").fetchone()[0]) > 0:
            return True
        row = conn.execute(
            """SELECT 1 FROM workers w
            JOIN messages m ON m.seq > w.last_seen_seq AND m.sender != w.name
            WHERE w.state IN ('waiting', 'stopped') AND w.turn_count < ?
              AND EXISTS (SELECT 1 FROM json_each(m.mentions_json) j WHERE j.value = w.name OR j.value = 'all')
            LIMIT 1""",
            (int(meta["max_turns"]),),
        ).fetchone()
        return row is not None


def ensure_supervisor(
    swarm_dir: Path | str, *, idle_timeout_sec: float = 60.0, tick_sec: float = 0.25,
    turn_timeout_sec: float = 900.0, kill_grace_sec: float = 3.0,
) -> int | None:
    sdir = Path(swarm_dir)
    sdir.mkdir(parents=True, exist_ok=True)
    lock_f = open(sdir / "supervisor.lock", "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
    finally:
        lock_f.close()
    scripts_root = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{scripts_root}{os.pathsep}{existing_pp}" if existing_pp else scripts_root
    cmd = [
        sys.executable, "-m", "swarmctl.supervisor", "--swarm-dir", str(sdir),
        "--idle-timeout", str(idle_timeout_sec), "--tick-sec", str(tick_sec),
        "--turn-timeout", str(turn_timeout_sec), "--kill-grace", str(kill_grace_sec),
    ]
    proc = subprocess.Popen(
        cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )
    proc._child_created = False  # type: ignore[attr-defined]
    return int(proc.pid)


def run_supervisor_loop(
    swarm_dir: Path | str, *, idle_timeout_sec: float = 60.0, tick_sec: float = 0.25,
    turn_timeout_sec: float = 900.0, kill_grace_sec: float = 3.0,
    adapter_factory: Callable[[str], Any] = get_adapter, workspace_manager: WorkspaceManager | None = None,
    max_ticks: int | None = None, on_before_unlock_check: Callable[[], None] | None = None,
) -> int:
    sdir = Path(swarm_dir)
    sdir.mkdir(parents=True, exist_ok=True)
    lock_f = open(sdir / "supervisor.lock", "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        store, wm = SwarmStore(sdir / "board.db"), (workspace_manager or WorkspaceManager())
        active, orphan_killing_term_at = {}, {}
        idle_since, ticks = None, 0
        try:
            while True:
                now, meta = time.monotonic(), store.get_meta()
                workers_by_name = {w["name"]: w for w in store.list_workers(include_killed=False)}

                for name, w in list(workers_by_name.items()):
                    if w["state"] != "killing":
                        continue
                    turn = active.get(name)
                    pid = turn.proc.pid if turn is not None else w["pid"]
                    if pid is not None and int(pid) > 0:
                        t_at = turn.term_sent_at if turn is not None else orphan_killing_term_at.get(name)
                        dead, new_t_at = _reap_pgid_step(int(pid), turn.proc if turn else None, t_at, now, kill_grace_sec)
                        if turn is not None:
                            turn.term_sent_at = new_t_at
                        else:
                            orphan_killing_term_at[name] = new_t_at
                        if not dead:
                            continue
                    if turn is not None:
                        active.pop(name, None)
                        turn.adapter.cleanup_turn(turn.proc)
                    orphan_killing_term_at.pop(name, None)
                    if w["workspace_mode"] == "share":
                        try:
                            wm.remove(meta["repo_root"], w["workspace_path"], w["branch_name"], "share", force=False)
                        except RuntimeError as exc:
                            store.post_message("system", f"[dirty-worktree] worker {name} preserved dirty worktree at {w['workspace_path']}: {exc}")
                    store.mark_killed(name)

                for name, w in list(workers_by_name.items()):
                    if w["state"] == "working" and name not in active and not _is_pid_alive(w["pid"]):
                        store.mark_stopped(name, store.read_board(limit=0)["head_seq"], error=f"Orphan worker PID {w['pid']} died unexpectedly")

                for name, turn in list(active.items()):
                    w_curr = store.get_worker(name)
                    if w_curr is None or w_curr["state"] in ("killing", "killed"):
                        continue
                    if now - turn.started_at >= float(turn.req.timeout_sec):
                        dead, turn.term_sent_at = _reap_pgid_step(turn.proc.pid, turn.proc, turn.term_sent_at, now, kill_grace_sec)
                        if not dead:
                            continue
                        active.pop(name, None)
                        turn.adapter.cleanup_turn(turn.proc)
                        store.mark_stopped(name, turn.req.delivered_max_seq, error=f"Turn exceeded timeout ({turn.req.timeout_sec}s)")
                        store.post_message("system", f"[circuit-breaker] worker {name} halted: turn exceeded timeout ({turn.req.timeout_sec}s)")
                    elif turn.proc.poll() is not None:
                        active.pop(name, None)
                        res = turn.adapter.collect_turn(turn.proc, turn.req, timed_out=False)
                        if res.exit_code == 0:
                            max_turns = int(store.get_meta()["max_turns"])
                            if turn.before_turn_count + 1 >= max_turns:
                                store.mark_stopped(name, turn.req.delivered_max_seq, error=f"Reached max_turns ({max_turns})")
                                store.post_message("system", f"[circuit-breaker] worker {name} halted: reached max_turns ({max_turns})")
                            else:
                                store.complete_turn(name, turn.req.delivered_max_seq, session_id=res.session_id)
                        else:
                            err = (res.error_text.strip() or f"Runner exited with code {res.exit_code}")[:500]
                            store.mark_stopped(name, turn.req.delivered_max_seq, error=err)

                for w in store.claim_runnable_workers():
                    w_name = w["name"]
                    msgs = [m for m in store.get_unread_delta(w_name, up_to_seq=w["delivered_max_seq"]) if m["sender"] != w_name]
                    req = TurnRequest(
                        swarm_id=str(meta["swarm_id"]), worker_name=w_name, worker_token=str(w["worker_token"]),
                        runner=str(w["runner"]), model=str(w["model"]), workspace_path=str(w["workspace_path"]),
                        permission_mode=str(w["permission_mode"]), session_id=str(w["session_id"]),
                        fork_session_id=str(w["fork_session_id"]), transcript_seed=str(w["transcript_seed"]),
                        prompt_delta=format_prompt_delta(w, msgs), delivered_max_seq=int(w["delivered_max_seq"]),
                        timeout_sec=float(turn_timeout_sec),
                    )
                    try:
                        adapter = adapter_factory(req.runner)
                        proc = adapter.start_turn(req)
                        store.set_worker_pid(w_name, proc.pid)
                        active[w_name] = _ActiveTurn(req=req, adapter=adapter, proc=proc, started_at=time.monotonic(), before_turn_count=int(w["turn_count"]))
                    except (PermissionError, ValueError, OSError) as exc:
                        store.mark_stopped(w_name, req.delivered_max_seq, error=str(exc)[:500])

                if not active and not _has_pending_work(store):
                    idle_since = idle_since or now
                    if now - idle_since >= idle_timeout_sec:
                        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
                        if on_before_unlock_check is not None:
                            on_before_unlock_check()
                        if _has_pending_work(store):
                            try:
                                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                return 0
                            idle_since = None
                            continue
                        return 0
                else:
                    idle_since = None

                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    return 0
                time.sleep(tick_sec)
        finally:
            store.close()
    finally:
        lock_f.close()


def _main() -> int:
    p = argparse.ArgumentParser(description="swarmctl lazy local supervisor")
    for flag, kw in [
        ("--swarm-dir", {"required": True}), ("--idle-timeout", {"type": float, "default": 60.0}),
        ("--tick-sec", {"type": float, "default": 0.25}), ("--turn-timeout", {"type": float, "default": 900.0}),
        ("--kill-grace", {"type": float, "default": 3.0}),
    ]:
        p.add_argument(flag, **kw)  # type: ignore[arg-type]
    a = p.parse_args()
    return run_supervisor_loop(
        a.swarm_dir, idle_timeout_sec=a.idle_timeout, tick_sec=a.tick_sec,
        turn_timeout_sec=a.turn_timeout, kill_grace_sec=a.kill_grace,
    )


if __name__ == "__main__":
    sys.exit(_main())
