"""SQLite WAL message board and roster store (`ADR-1`, `ADR-6`, `BR-1`, `BR-2`, `BR-8`)."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hmac, json, re, secrets, sqlite3, threading
from pathlib import Path
from typing import Any, Iterator

SWARM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
WORKER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
MENTION_RE = re.compile(r"(?<![A-Za-z0-9_.-])@([a-z0-9][a-z0-9_-]{0,23})(?![A-Za-z0-9_-])")
RESERVED_WORKER_NAMES = frozenset({"all", "coordinator", "system"})
UNAUTH_SENDERS = frozenset({"coordinator", "system", "human"})
VALID_STATES = frozenset({"waiting", "working", "killing", "stopped", "killed"})
VALID_WORKSPACE_MODES = frozenset({"inherit", "share"})
VALID_PERMISSION_MODES = frozenset({"readonly", "edit", "unsafe"})
MAX_SEED_BYTES = 4096

_SCHEMA_STMTS = (
    """CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id = 1), swarm_id TEXT NOT NULL,
      title TEXT DEFAULT '', repo_root TEXT NOT NULL, default_runner TEXT DEFAULT 'claude',
      default_model TEXT DEFAULT '', max_concurrent INTEGER DEFAULT 4, max_turns INTEGER DEFAULT 25)""",
    """CREATE TABLE IF NOT EXISTS workers (name TEXT PRIMARY KEY, runner TEXT NOT NULL, model TEXT DEFAULT '',
      state TEXT NOT NULL CHECK(state IN ('waiting','working','killing','stopped','killed')),
      workspace_mode TEXT NOT NULL CHECK(workspace_mode IN ('inherit','share')),
      workspace_path TEXT NOT NULL, branch_name TEXT DEFAULT '',
      permission_mode TEXT NOT NULL CHECK(permission_mode IN ('readonly','edit','unsafe')),
      session_id TEXT DEFAULT '', fork_session_id TEXT DEFAULT '', transcript_seed TEXT DEFAULT '',
      worker_token TEXT NOT NULL, last_seen_seq INTEGER DEFAULT 0, turn_count INTEGER DEFAULT 0,
      pid INTEGER, last_error TEXT DEFAULT '', updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS messages (seq INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL,
      body TEXT NOT NULL, mentions_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_ident(value: str, kind: str) -> str:
    if isinstance(value, str):
        if kind == "swarm" and SWARM_ID_RE.match(value):
            return value
        if kind == "worker" and WORKER_NAME_RE.match(value) and value not in RESERVED_WORKER_NAMES:
            return value
    raise ValueError(f"Invalid {kind} identifier: {value!r}")


def parse_mentions(body: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in MENTION_RE.finditer(body))) if isinstance(body, str) else []


def _msg_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {"seq": int(row["seq"]), "sender": str(row["sender"]), "body": str(row["body"]),
            "mentions": list(json.loads(row["mentions_json"])), "created_at": str(row["created_at"])}


class SwarmStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local, self._lock, self._conns = threading.local(), threading.Lock(), []
        with self._write_tx() as conn:
            for stmt in _SCHEMA_STMTS:
                conn.execute(stmt)

    def _conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            for p in ("PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=5000", "PRAGMA foreign_keys=ON"):
                conn.execute(p)
            self._local.conn = conn
            with self._lock:
                self._conns.append(conn)
        return conn

    @contextmanager
    def _write_tx(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn()
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        with self._lock:
            conns, self._conns = list(self._conns), []
        self._local = threading.local()
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> SwarmStore: return self
    def __exit__(self, *exc: Any) -> None: self.close()

    def init_swarm(self, swarm_id: str, repo_root: str, title: str = "", default_runner: str = "claude",
                   default_model: str = "", max_concurrent: int = 4, max_turns: int = 25) -> dict[str, Any]:
        validate_ident(swarm_id, "swarm")
        if max_concurrent < 1 or max_turns < 1:
            raise ValueError("max_concurrent and max_turns must be >= 1")
        with self._write_tx() as conn:
            row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
            if row is not None:
                if row["swarm_id"] != swarm_id:
                    raise ValueError(f"Store already initialized for swarm {row['swarm_id']!r}")
                conn.execute("UPDATE meta SET title = ?, default_model = ? WHERE id = 1",
                             (title or row["title"], default_model or row["default_model"]))
            else:
                conn.execute("INSERT INTO meta (id, swarm_id, title, repo_root, default_runner, default_model, max_concurrent, max_turns) VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
                             (swarm_id, title, repo_root, default_runner, default_model, max_concurrent, max_turns))
            return self.get_meta()

    def get_meta(self) -> dict[str, Any]:
        row = self._conn().execute("SELECT * FROM meta WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("Swarm is not initialized")
        return dict(row)

    def set_title(self, title: str) -> dict[str, Any]:
        with self._write_tx() as conn:
            self.get_meta()
            conn.execute("UPDATE meta SET title = ? WHERE id = 1", (title,))
            return self.get_meta()

    def add_worker(self, name: str, brief: str, *, runner: str | None = None, model: str | None = None,
                   workspace_mode: str = "inherit", workspace_path: str = "", branch_name: str = "",
                   permission_mode: str | None = None, fork_from: str | None = None, sender: str = "coordinator") -> dict[str, Any]:
        validate_ident(name, "worker")
        if not isinstance(brief, str) or not brief.strip():
            raise ValueError("Worker brief must be non-empty")
        if workspace_mode not in VALID_WORKSPACE_MODES:
            raise ValueError(f"Invalid workspace_mode: {workspace_mode!r}")
        resolved_perm = permission_mode or ("readonly" if workspace_mode == "inherit" else "edit")
        if resolved_perm not in VALID_PERMISSION_MODES:
            raise ValueError(f"Invalid permission_mode: {resolved_perm!r}")
        with self._write_tx() as conn:
            meta = self.get_meta()
            existing = conn.execute("SELECT state FROM workers WHERE name = ?", (name,)).fetchone()
            if existing is not None and existing["state"] != "killed":
                raise ValueError(f"Worker {name!r} already exists in state {existing['state']!r}")
            resolved_runner, resolved_path = runner or meta["default_runner"], workspace_path or meta["repo_root"]
            resolved_model = meta["default_model"] if model is None else model
            fork_session_id, transcript_seed = "", ""
            if fork_from is not None:
                if fork_from == "coordinator":
                    transcript_seed = self.get_transcript_seed("coordinator", max_bytes=MAX_SEED_BYTES)
                else:
                    parent = self._require_worker_row(conn, fork_from)
                    same_cwd = Path(resolved_path).resolve() == Path(parent["workspace_path"]).resolve()
                    if resolved_runner == "claude" and parent["runner"] == "claude" and same_cwd and parent["session_id"]:
                        fork_session_id = str(parent["session_id"])
                    else:
                        transcript_seed = self.get_transcript_seed(fork_from, max_bytes=MAX_SEED_BYTES)
            now = _now_iso()
            conn.execute(
                """INSERT OR REPLACE INTO workers (name, runner, model, state, workspace_mode, workspace_path,
                  branch_name, permission_mode, session_id, fork_session_id, transcript_seed, worker_token,
                  last_seen_seq, turn_count, pid, last_error, updated_at)
                VALUES (?, ?, ?, 'waiting', ?, ?, ?, ?, '', ?, ?, ?, 0, 0, NULL, '', ?)""",
                (name, resolved_runner, resolved_model, workspace_mode, resolved_path, branch_name,
                 resolved_perm, fork_session_id, transcript_seed, secrets.token_urlsafe(24), now),
            )
            body = brief if name in parse_mentions(brief) else f"@{name} {brief}"
            cur = conn.execute("INSERT INTO messages (sender, body, mentions_json, created_at) VALUES (?, ?, ?, ?)",
                               (sender, body, json.dumps(parse_mentions(body)), now))
            return {**dict(self._require_worker_row(conn, name)), "brief_seq": int(cur.lastrowid)}

    def get_worker(self, name: str) -> dict[str, Any] | None:
        row = self._conn().execute("SELECT * FROM workers WHERE name = ?", (name,)).fetchone()
        return dict(row) if row is not None else None

    def list_workers(self, include_killed: bool = True) -> list[dict[str, Any]]:
        clause = "" if include_killed else " WHERE state != 'killed'"
        rows = self._conn().execute(f"SELECT * FROM workers{clause} ORDER BY name ASC").fetchall()
        return [{k: v for k, v in dict(r).items() if k != "worker_token"} for r in rows]

    def verify_worker_token(self, token: str, expected_name: str | None = None) -> str:
        if not isinstance(token, str) or not token:
            raise PermissionError("Missing or empty worker token")
        matched_name, matched_state = None, None
        for row in self._conn().execute("SELECT name, state, worker_token FROM workers").fetchall():
            if hmac.compare_digest(str(row["worker_token"]), token):
                matched_name, matched_state = str(row["name"]), str(row["state"])
        if matched_name is None or matched_state == "killed" or (expected_name is not None and matched_name != expected_name):
            raise PermissionError("Invalid, revoked, or mismatched worker token")
        return matched_name

    def post_message(self, sender: str, body: str, token: str | None = None) -> dict[str, Any]:
        if not isinstance(body, str) or not body.strip():
            raise ValueError("Message body must be non-empty")
        if token is not None:
            self.verify_worker_token(token, expected_name=sender)
        elif self._conn().execute("SELECT 1 FROM workers WHERE name = ?", (sender,)).fetchone() is not None:
            raise PermissionError(f"Worker sender {sender!r} requires a valid worker token")
        elif sender not in UNAUTH_SENDERS:
            raise ValueError(f"Unauthenticated sender {sender!r} not in {sorted(UNAUTH_SENDERS)}")
        with self._write_tx() as conn:
            cur = conn.execute("INSERT INTO messages (sender, body, mentions_json, created_at) VALUES (?, ?, ?, ?)",
                               (sender, body, json.dumps(parse_mentions(body)), _now_iso()))
            return _msg_from_row(conn.execute("SELECT * FROM messages WHERE seq = ?", (cur.lastrowid,)).fetchone())

    def read_board(self, since: int | None = None, limit: int = 20, seqs: list[int] | None = None, status: bool = False) -> dict[str, Any]:
        conn = self._conn()
        head_seq = int(conn.execute("SELECT COALESCE(MAX(seq), 0) FROM messages").fetchone()[0])
        if status:
            meta = self.get_meta()
            return {"swarm_id": meta["swarm_id"], "title": meta["title"], "head_seq": head_seq, "workers": self.list_workers(True)}
        if seqs is not None:
            rows = conn.execute(f"SELECT * FROM messages WHERE seq IN ({','.join('?' for _ in seqs)}) ORDER BY seq ASC",
                                [int(s) for s in seqs]).fetchall() if seqs else []
        elif since is not None:
            rows = conn.execute("SELECT * FROM messages WHERE seq > ? ORDER BY seq ASC LIMIT ?", (int(since), max(0, int(limit)))).fetchall()
        else:
            rows = list(reversed(conn.execute("SELECT * FROM messages ORDER BY seq DESC LIMIT ?", (max(0, int(limit)),)).fetchall()))
        return {"messages": [_msg_from_row(r) for r in rows], "head_seq": head_seq}

    def claim_runnable_workers(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._write_tx() as conn:
            meta = self.get_meta()
            active = int(conn.execute("SELECT COUNT(*) FROM workers WHERE state IN ('working', 'killing')").fetchone()[0])
            slots = max(0, int(meta["max_concurrent"]) - active)
            if limit is not None:
                slots = min(slots, max(0, int(limit)))
            if slots == 0:
                return []
            head_seq = int(conn.execute("SELECT COALESCE(MAX(seq), 0) FROM messages").fetchone()[0])
            rows = conn.execute(
                """SELECT w.name, MIN(m.seq) AS first_unread_seq FROM workers w
                JOIN messages m ON m.seq > w.last_seen_seq AND m.sender != w.name
                WHERE w.state IN ('waiting', 'stopped') AND w.turn_count < ?
                  AND EXISTS (SELECT 1 FROM json_each(m.mentions_json) j WHERE j.value = w.name OR j.value = 'all')
                GROUP BY w.name ORDER BY first_unread_seq ASC, w.name ASC LIMIT ?""",
                (int(meta["max_turns"]), slots),
            ).fetchall()
            now, claimed = _now_iso(), []
            for r in rows:
                conn.execute("UPDATE workers SET state = 'working', last_error = '', updated_at = ? WHERE name = ?", (now, r["name"]))
                claimed.append({**dict(self._require_worker_row(conn, r["name"])), "delivered_max_seq": head_seq})
            return claimed

    def _require_worker_row(self, conn: sqlite3.Connection, name: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM workers WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown worker: {name!r}")
        return row

    def set_worker_pid(self, name: str, pid: int | None) -> None:
        with self._write_tx() as conn:
            self._require_worker_row(conn, name)
            conn.execute("UPDATE workers SET pid = ?, updated_at = ? WHERE name = ?", (pid, _now_iso(), name))

    def complete_turn(self, name: str, delivered_max_seq: int, session_id: str = "") -> dict[str, Any]:
        with self._write_tx() as conn:
            row = self._require_worker_row(conn, name)
            new_state = row["state"] if row["state"] in ("killing", "killed") else "waiting"
            new_seq = max(int(row["last_seen_seq"]), int(delivered_max_seq))
            conn.execute("UPDATE workers SET state = ?, pid = NULL, turn_count = turn_count + 1, last_seen_seq = ?, session_id = ?, fork_session_id = '', transcript_seed = '', updated_at = ? WHERE name = ?",
                         (new_state, new_seq, session_id or row["session_id"], _now_iso(), name))
            return dict(self._require_worker_row(conn, name))

    def switch_model(self, name: str, model: str) -> dict[str, Any]:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Model name must be non-empty")
        with self._write_tx() as conn:
            row = self._require_worker_row(conn, name)
            if row["state"] not in ("waiting", "stopped"):
                raise ValueError(f"Cannot switch model while worker {name!r} is in state {row['state']!r}")
            conn.execute("UPDATE workers SET model = ?, updated_at = ? WHERE name = ?", (model.strip(), _now_iso(), name))
            return dict(self._require_worker_row(conn, name))

    def mark_killing(self, name: str) -> dict[str, Any]:
        with self._write_tx() as conn:
            row = self._require_worker_row(conn, name)
            if row["state"] == "killed":
                raise ValueError(f"Worker {name!r} is already killed")
            conn.execute("UPDATE workers SET state = 'killing', updated_at = ? WHERE name = ?", (_now_iso(), name))
            return dict(self._require_worker_row(conn, name))

    def mark_killed(self, name: str) -> dict[str, Any]:
        with self._write_tx() as conn:
            self._require_worker_row(conn, name)
            conn.execute("UPDATE workers SET state = 'killed', pid = NULL, updated_at = ? WHERE name = ?", (_now_iso(), name))
            return dict(self._require_worker_row(conn, name))

    def mark_stopped(self, name: str, delivered_max_seq: int, error: str = "") -> dict[str, Any]:
        with self._write_tx() as conn:
            row = self._require_worker_row(conn, name)
            new_state = row["state"] if row["state"] in ("killing", "killed") else "stopped"
            new_seq = max(int(row["last_seen_seq"]), int(delivered_max_seq))
            conn.execute("UPDATE workers SET state = ?, pid = NULL, turn_count = turn_count + 1, last_seen_seq = ?, last_error = ?, updated_at = ? WHERE name = ?",
                         (new_state, new_seq, error, _now_iso(), name))
            return dict(self._require_worker_row(conn, name))

    def get_unread_delta(self, name: str, up_to_seq: int | None = None) -> list[dict[str, Any]]:
        worker = self.get_worker(name)
        if worker is None:
            raise ValueError(f"Unknown worker: {name!r}")
        last_seen = int(worker["last_seen_seq"])
        sql = "SELECT * FROM messages WHERE seq > ?" + (" AND seq <= ? ORDER BY seq ASC" if up_to_seq is not None else " ORDER BY seq ASC")
        params = (last_seen, int(up_to_seq)) if up_to_seq is not None else (last_seen,)
        return [_msg_from_row(r) for r in self._conn().execute(sql, params).fetchall()]

    def get_transcript_seed(self, name: str, max_bytes: int = MAX_SEED_BYTES) -> str:
        if name != "coordinator" and self.get_worker(name) is None:
            raise ValueError(f"Unknown worker for transcript seed: {name!r}")
        all_msgs = [_msg_from_row(r) for r in self._conn().execute("SELECT * FROM messages ORDER BY seq ASC").fetchall()]
        if name == "coordinator":
            brief, recent = (all_msgs[0]["body"] if all_msgs else ""), all_msgs[-10:]
        else:
            brief = next((m["body"] for m in all_msgs if name in m["mentions"]), "")
            recent = [m for m in all_msgs if m["sender"] == name or name in m["mentions"] or "all" in m["mentions"]][-10:]
        lines = [f"=== Initial Brief ===\n{brief}\n=== Recent Messages ===\n"] + [
            f"[{m['sender']} (#{m['seq']})]: {m['body']}\n" for m in recent
        ]
        return "".join(lines).encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
