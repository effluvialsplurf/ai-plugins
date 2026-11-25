#!/usr/bin/env python3
"""lean-runbook: 5-stage workflow tracker & dual-protocol (Claude Code / Antigravity) hook gate.

Stages:
  1. spec      Compact EGM Spec (docs/specs/<slug>.md, <=300 lines)
  2. goldfish  2-Pass Parallel Goldfish Gate + human resolution [GATE OPENS HERE]
  3. plan      Single Compact Contract Plan (.loop/<slug>/plan.md, <=300 lines, <=3 commits)
  4. build     Python-orchestrated TDD build loop + 1-line quiet gate
  5. review    Fresh Adversarial Whole-Branch Diff Review + PR & finish

CLI subcommands:
  start <slug> [--epic <epic-slug>] [--force] [--cwd <repo>]
  status [--all | --epic <epic-slug>] [--cwd <repo>]
  done <stage> [--reason "..."] [--cwd <repo>]
  skip gate --reason "..." [--cwd <repo>]
  finish [--cwd <repo>]

Hook modes (payload JSON on stdin, decision JSON on stdout; unparseable input fails open):
  hook <session-start|pre-tool-use> [--harness auto|claude|antigravity]
  pre-commit   (exit 1 when staged code files meet a closed gate; fails closed)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

STAGES = ("spec", "goldfish", "plan", "build", "review")
GATE_STAGES = {"spec", "goldfish"}
LINE_BUDGET = 300
LINE_GRACE = 20  # warn / force_ask above 320 lines

CODE_EXTENSIONS = {
    ".gd", ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".rs", ".go", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
    ".cs", ".java", ".kt", ".swift", ".rb", ".php", ".lua",
    ".sh", ".bash", ".zsh", ".ps1", ".sql", ".zig", ".nim",
    ".tscn", ".tres", ".gdshader", ".glsl", ".wgsl", ".tf", ".hcl", ".ipynb",
}
CODE_BASENAMES = {"Makefile", "Dockerfile", "Jenkinsfile", "CMakeLists.txt"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_root() -> Path:
    env = os.environ.get("LEAN_RUNBOOK_DATA")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "lean-runbook"


def repo_root_for(cwd: str | None) -> Path:
    base = Path(cwd or os.getcwd()).resolve()
    try:
        out = subprocess.check_output(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return base


def state_path_for(repo: Path) -> Path:
    h = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:16]
    return data_root() / "repos" / h / "state.json"


def load_state(repo: Path) -> dict[str, Any] | None:
    p = state_path_for(repo)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_state(repo: Path, state: dict[str, Any]) -> None:
    p = state_path_for(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def current_stage(state: dict[str, Any]) -> tuple[int, str]:
    done = set(state.get("done", []))
    for idx, st in enumerate(STAGES, 1):
        if st not in done:
            return idx, st
    return len(STAGES), "done"


def gate_is_closed(state: dict[str, Any]) -> bool:
    if not state.get("active", True):
        return False
    if state.get("gate_open"):
        return False
    done = set(state.get("done", []))
    return "goldfish" not in done


def next_guidance(state: dict[str, Any]) -> str:
    _, st = current_stage(state)
    slug = state.get("slug", "<slug>")
    return {
        "spec": f"Write compact EGM spec at docs/specs/{slug}.md (<=300 lines), then mark spec done.",
        "goldfish": f"Run 2-pass parallel Goldfish review via native `swarm` (Flash + Argon/Claude) or workflows/goldfish_gate.py on docs/specs/{slug}.md, resolve findings with user, then run `done goldfish` to open the code gate.",
        "plan": f"Draft single <=300-line contract plan at .loop/{slug}/plan.md (<=3 commits, read-only Argon/Claude planner, no scratch dry-runs).",
        "build": f"Implement via native `swarm` builder (Claude Sonnet / Argon) + optional workflows/build_loop.py (build_model='inherit', skip_critic=True) with quiet test gate. Never use /teamwork.",
        "review": f"Run fresh cross-family adversarial whole-branch diff review via native `swarm` critic (opposite flagship pool) + fix pass, then run `finish`.",
        "done": f"Feature {slug} is complete. Run `finish` to clear active state.",
    }.get(st, "")


def format_status(state: dict[str, Any]) -> str:
    idx, st = current_stage(state)
    gate = "CLOSED (no code edits)" if gate_is_closed(state) else "OPEN"
    epic_tag = f" [epic: {state['epic']}]" if state.get("epic") else ""
    lines = [
        f"lean-runbook: {state['slug']}{epic_tag} | Stage {idx}/{len(STAGES)} ({st}) | Gate: {gate}",
        f"Spec: docs/specs/{state['slug']}.md | Plan: .loop/{state['slug']}/plan.md",
        f"Done: {', '.join(state.get('done', [])) or 'none'}",
        f"Next: {next_guidance(state)}",
    ]
    if state.get("overrides"):
        lines.append(f"Overrides: {len(state['overrides'])} recorded")
    return "\n".join(lines)


def sanitize_slug(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", raw.strip()).strip("-").lower()


def iter_active_states(epic_filter: str | None = None) -> list[dict[str, Any]]:
    repos_dir = data_root() / "repos"
    if not repos_dir.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for p in sorted(repos_dir.glob("*/state.json")):
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not st or not st.get("active"):
            continue
        if epic_filter and st.get("epic") != epic_filter:
            continue
        found.append(st)
    found.sort(key=lambda s: (s.get("epic") or "", s.get("slug") or "", s.get("repo") or ""))
    return found


# ---------------- CLI Commands ----------------

def cmd_start(args: list[str], cwd: str | None) -> int:
    force = False
    epic = ""
    pos: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--force":
            force = True
            i += 1
        elif args[i] == "--epic" and i + 1 < len(args):
            epic = sanitize_slug(args[i + 1])
            i += 2
        elif args[i].startswith("--epic="):
            epic = sanitize_slug(args[i].split("=", 1)[1])
            i += 1
        elif args[i].startswith("--"):
            i += 1
        else:
            pos.append(args[i])
            i += 1
    if not pos:
        print("Usage: runbook.py start <slug> [--epic <epic-slug>] [--force]", file=sys.stderr)
        return 2
    slug = sanitize_slug(pos[0])
    repo = repo_root_for(cwd)
    existing = load_state(repo)
    if existing and existing.get("active") and not force:
        print(
            f"Feature '{existing['slug']}' is already active for {repo}. "
            f"Use `finish` first or pass `--force` to reset.",
            file=sys.stderr,
        )
        return 1
    overrides = existing.get("overrides", []) if existing else []
    state: dict[str, Any] = {
        "slug": slug,
        "repo": str(repo),
        "active": True,
        "gate_open": False,
        "done": [],
        "overrides": overrides,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if epic:
        state["epic"] = epic
    save_state(repo, state)
    print(format_status(state))
    return 0


def cmd_status(args: list[str], cwd: str | None) -> int:
    show_all = False
    epic_filter = ""
    i = 0
    while i < len(args):
        if args[i] == "--all":
            show_all = True
            i += 1
        elif args[i] == "--epic" and i + 1 < len(args):
            epic_filter = sanitize_slug(args[i + 1])
            show_all = True
            i += 2
        elif args[i].startswith("--epic="):
            epic_filter = sanitize_slug(args[i].split("=", 1)[1])
            show_all = True
            i += 1
        else:
            i += 1

    if show_all:
        states = iter_active_states(epic_filter or None)
        if not states:
            label = f" for epic '{epic_filter}'" if epic_filter else ""
            print(f"lean-runbook: no active slices{label}.")
            return 0
        header = f"lean-runbook active slices ({len(states)})"
        if epic_filter:
            header += f" [epic: {epic_filter}]"
        lines = [header]
        for st in states:
            idx, stage = current_stage(st)
            gate = "CLOSED" if gate_is_closed(st) else "OPEN"
            ep = f" [epic: {st['epic']}]" if st.get("epic") else ""
            lines.append(
                f"- {st['slug']}{ep} | Stage {idx}/{len(STAGES)} ({stage}) | Gate: {gate} | {st.get('repo', '?')}"
            )
        print("\n".join(lines))
        return 0

    repo = repo_root_for(cwd)
    state = load_state(repo)
    if not state or not state.get("active"):
        print("lean-runbook: no active feature in this repo.")
        return 0
    # Auto-detect spec file existence for Stage 1 convenience
    spec_file = repo / "docs" / "specs" / f"{state['slug']}.md"
    if spec_file.is_file() and "spec" not in state.get("done", []):
        state.setdefault("done", []).append("spec")
        state["updated_at"] = now_iso()
        save_state(repo, state)
    print(format_status(state))
    return 0


def cmd_done(args: list[str], cwd: str | None) -> int:
    reason = ""
    pos: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--reason" and i + 1 < len(args):
            reason = args[i + 1]
            i += 2
        elif args[i].startswith("--reason="):
            reason = args[i].split("=", 1)[1]
            i += 1
        elif args[i].startswith("--"):
            i += 1
        else:
            pos.append(args[i])
            i += 1
    if not pos:
        print(f"Usage: runbook.py done <{'|'.join(STAGES)}> [--reason '...']", file=sys.stderr)
        return 2
    stage = pos[0].lower()
    if stage.isdigit() and 1 <= int(stage) <= len(STAGES):
        stage = STAGES[int(stage) - 1]
    if stage not in STAGES:
        print(f"Unknown stage '{stage}'. Choose from: {', '.join(STAGES)}", file=sys.stderr)
        return 2

    repo = repo_root_for(cwd)
    state = load_state(repo)
    if not state or not state.get("active"):
        print("No active feature. Run `runbook.py start <slug>` first.", file=sys.stderr)
        return 1

    done = state.setdefault("done", [])
    if stage not in done:
        done.append(stage)
    if stage == "goldfish":
        state["gate_open"] = True
        if "spec" not in done:
            done.insert(0, "spec")
    if reason:
        state.setdefault("overrides", []).append(
            {"action": f"done {stage}", "reason": reason, "at": now_iso()}
        )
    state["updated_at"] = now_iso()
    save_state(repo, state)
    print(format_status(state))
    return 0


def cmd_skip(args: list[str], cwd: str | None) -> int:
    reason = ""
    pos: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--reason" and i + 1 < len(args):
            reason = args[i + 1]
            i += 2
        elif args[i].startswith("--reason="):
            reason = args[i].split("=", 1)[1]
            i += 1
        elif args[i].startswith("--"):
            i += 1
        else:
            pos.append(args[i])
            i += 1
    if not pos or pos[0].lower() != "gate":
        print("Usage: runbook.py skip gate --reason '...'", file=sys.stderr)
        return 2
    if not reason.strip():
        print("`skip gate` requires `--reason \"...\"`.", file=sys.stderr)
        return 2
    repo = repo_root_for(cwd)
    state = load_state(repo)
    if not state or not state.get("active"):
        print("No active feature.", file=sys.stderr)
        return 1
    state["gate_open"] = True
    state.setdefault("overrides", []).append(
        {"action": "skip gate", "reason": reason.strip(), "at": now_iso()}
    )
    state["updated_at"] = now_iso()
    save_state(repo, state)
    print(format_status(state))
    return 0


def cmd_finish(cwd: str | None) -> int:
    repo = repo_root_for(cwd)
    state = load_state(repo)
    if not state or not state.get("active"):
        print("lean-runbook: no active feature to finish.")
        return 0
    state["active"] = False
    state["finished_at"] = now_iso()
    state["updated_at"] = now_iso()
    save_state(repo, state)
    print(f"lean-runbook: finished '{state['slug']}'. Gate cleared.")
    return 0


# ---------------- Hook Handlers (pure decisions + protocol adapters) ----------------

def read_hook_stdin() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    return json.loads(raw)


def hook_repo_from_payload(payload: dict[str, Any]) -> Path:
    cwd = payload.get("cwd")
    if not cwd:
        ws = payload.get("workspacePaths") or []
        cwd = ws[0] if ws else os.getcwd()
    return repo_root_for(cwd)


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def is_code_file(path: Path, repo: Path) -> bool:
    if not is_under(path, repo):
        return False
    rel = path.resolve().relative_to(repo.resolve())
    parts = set(rel.parts)
    if parts & {"docs", ".loop", ".agents", ".agent"}:
        return False
    if path.name in CODE_BASENAMES:
        return True
    return path.suffix.lower() in CODE_EXTENSIONS


def is_budgeted_doc(path: Path, repo: Path) -> tuple[bool, str]:
    if not is_under(path, repo):
        return False, ""
    rel = str(path.resolve().relative_to(repo.resolve())).replace("\\", "/")
    if rel.startswith("docs/specs/") and rel.endswith(".md"):
        return True, "Compact EGM Spec"
    if rel.startswith(".loop/") and rel.endswith("/plan.md"):
        return True, "Contract Plan"
    return False, ""


class Decision(NamedTuple):
    kind: str  # allow | ask | deny
    reason: str = ""


ALLOW = Decision("allow")


def nlines(text: Any) -> int:
    return str(text).count("\n") + 1


def decide_write(state: dict[str, Any], path: Any, content: Any, is_edit: bool) -> Decision:
    """content: new text for a write; for an edit, a list of (old, new) string pairs."""
    repo = Path(state.get("repo", "."))
    target = repo / path  # an absolute path replaces repo
    if is_under(target, data_root()):
        return Decision("deny", "lean-runbook state directory is protected. Use the lean-runbook CLI.")
    if gate_is_closed(state) and is_code_file(target, repo):
        return Decision("deny", (
            f"lean-runbook Spec Gate is CLOSED for '{state['slug']}'. Finish Stage 2 (2-Pass Goldfish review on "
            f"docs/specs/{state['slug']}.md) and run `done goldfish` (or `skip gate --reason \"...\"`) "
            f"before editing code file {target.name}."))
    budgeted, kind = is_budgeted_doc(target, repo)
    if not budgeted or not content:
        return ALLOW
    if is_edit:
        try:
            count = nlines(target.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return ALLOW
        count += sum(nlines(new) - nlines(old) for old, new in content)
    else:
        count = nlines(content)
    if count > LINE_BUDGET + LINE_GRACE:
        return Decision("ask", (
            f"lean-runbook Token Guardrail: {kind} ({target.name}) is {count} lines (budget is <= {LINE_BUDGET}). "
            f"Trim prose into tables or split into smaller <=3-commit slices, or approve override."))
    return ALLOW


STATE_DIR = ".cache/lean-runbook"
CLI_RE = re.compile(r"runbook\.py|(?<![\w./-])lean-runbook(?![\w./-])")
OVERRIDE_RE = re.compile(r"\b(skip\s+gate|done\s+(goldfish|2)|start\s+\S+.*--force)\b")


def decide_cmd(state: dict[str, Any], cmd: str) -> Decision:
    plain = re.sub(r"[\"'\\{}]", "", cmd)  # defeat quote/brace evasion such as lean-"runbook"
    for seg in re.split(r"[;&|\n`]|\$\(", plain):
        if any(m in seg for m in (str(data_root()), STATE_DIR, "LEAN_RUNBOOK_DATA")) and not CLI_RE.search(seg.replace(STATE_DIR, "")):
            return Decision("deny", "Direct access to the lean-runbook state directory is blocked. Use the lean-runbook CLI.")
    if CLI_RE.search(plain.replace(STATE_DIR, "")):
        if OVERRIDE_RE.search(plain) or (gate_is_closed(state) and re.search(r"\bfinish\b", plain)):
            return Decision("ask", f"lean-runbook: opening, bypassing, resetting or abandoning the spec gate for '{state['slug']}' needs explicit user approval.")
    return ALLOW


def format_session_start(state: dict[str, Any], script_paths: dict[str, str]) -> str:
    idx, st = current_stage(state)
    gate = "CLOSED" if gate_is_closed(state) else "OPEN"
    epic_tag = f" [epic: {state['epic']}]" if state.get("epic") else ""
    scripts = " ".join(f"{k}={v}" for k, v in script_paths.items())
    return (f"lean-runbook active: {state['slug']}{epic_tag} | Stage {idx}/{len(STAGES)} ({st}) "
            f"| Gate: {gate} | Next: {next_guidance(state)} | Scripts: {scripts}")


def detect_harness(payload: dict[str, Any]) -> str:
    if "tool_input" in payload or "hook_event_name" in payload:
        return "claude"
    return "antigravity" if "toolCall" in payload or "workspacePaths" in payload else "unknown"


def tool_action(harness: str, payload: dict[str, Any]) -> tuple[str, Any, Any, bool]:
    """Normalize a payload to (kind, path-or-cmd, content, is_edit); kind is write|cmd."""
    if harness == "claude":
        name, a = payload.get("tool_name"), payload.get("tool_input") or {}
        if name == "Bash":
            return "cmd", str(a.get("command") or ""), None, False
        path = a.get("file_path") or a.get("notebook_path") or ""
        if name in ("Edit", "MultiEdit"):
            return "write", path, [(e.get("old_string", ""), e.get("new_string", "")) for e in a.get("edits") or [a]], True
        return "write", path, a.get("content"), False
    tc = payload.get("toolCall") or {}
    a = tc.get("args") or {}
    if tc.get("name") == "run_command":
        return "cmd", str(a.get("CommandLine") or a.get("command") or ""), None, False
    path = a.get("Path") or a.get("TargetFile") or a.get("path") or a.get("file_path") or ""
    if "TargetContent" in a or "ReplacementChunks" in a:
        return "write", path, [(c.get("TargetContent", ""), c.get("ReplacementContent", "")) for c in a.get("ReplacementChunks") or [a]], True
    return "write", path, a.get("Content") or a.get("CodeContent"), False


def render(harness: str, d: Decision) -> dict[str, Any]:
    if harness == "claude":
        if d.kind == "allow":
            return {}
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": d.kind, "permissionDecisionReason": d.reason}}
    out = {"decision": "force_ask" if d.kind == "ask" else d.kind}
    return {**out, "reason": d.reason} if d.reason else out


def hook_main(event: str, harness: str) -> int:
    """Fail open: any parse or runtime error prints a neutral allow."""
    try:
        payload = read_hook_stdin()
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        if harness == "auto":
            harness = detect_harness(payload)
        state = load_state(hook_repo_from_payload(payload)) if harness != "unknown" else None
        if not state or not state.get("active"):
            print(json.dumps({"decision": "allow"} if harness == "antigravity" and event == "pre-tool-use" else {}))
        elif event == "session-start":
            here = Path(__file__).resolve()
            msg = format_session_start(state, {"runbook.py": str(here), "design_check.py": str(here.parents[2] / "lean-design/scripts/design_check.py")})
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}} if harness == "claude"
                             else {"injectSteps": [{"systemMessage": {"systemMessage": msg}}]}))
        else:
            kind, target, content, is_edit = tool_action(harness, payload)
            d = decide_cmd(state, target) if kind == "cmd" else decide_write(state, target, content, is_edit) if target else ALLOW
            print(json.dumps(render(harness, d)))
    except Exception:
        print(json.dumps({"decision": "allow"} if harness == "antigravity" and event == "pre-tool-use" else {}))
    return 0


def cmd_pre_commit(cwd: str | None) -> int:
    """Fail closed: block when staged code meets a closed gate, or when staged files cannot be read."""
    try:
        repo = repo_root_for(cwd)
        out = subprocess.check_output(["git", "-C", str(repo), "diff", "--cached", "--name-only", "-z"], stderr=subprocess.DEVNULL, text=True)
        state = load_state(repo)
        code = [f for f in out.split("\0") if f and is_code_file(repo / f, repo)]
        if not code or not state or not state.get("active") or not gate_is_closed(state):
            return 0
        print(f"lean-runbook: Spec Gate is CLOSED for '{state['slug']}'; staged code files: {', '.join(code)}", file=sys.stderr)
    except Exception as e:
        print(f"lean-runbook: pre-commit could not verify staged files ({e}); blocking.", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    # Extract optional --cwd <path>
    cwd = None
    cleaned: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--cwd" and i + 1 < len(argv):
            cwd = argv[i + 1]
            i += 2
        elif argv[i].startswith("--cwd="):
            cwd = argv[i].split("=", 1)[1]
            i += 1
        else:
            cleaned.append(argv[i])
            i += 1

    cmd = cleaned[0]
    rest = cleaned[1:]
    if cmd == "start":
        return cmd_start(rest, cwd)
    if cmd == "status":
        return cmd_status(rest, cwd)
    if cmd == "done":
        return cmd_done(rest, cwd)
    if cmd == "skip":
        return cmd_skip(rest, cwd)
    if cmd == "finish":
        return cmd_finish(cwd)
    if cmd == "pre-commit":
        return cmd_pre_commit(cwd)
    if cmd == "hook" and rest and rest[0] in ("session-start", "pre-tool-use"):
        harness = "auto"
        if "--harness" in rest[1:] and rest.index("--harness") + 1 < len(rest):
            harness = rest[rest.index("--harness") + 1]
        return hook_main(rest[0], harness if harness in ("claude", "antigravity") else "auto")
    print(f"Unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
