from __future__ import annotations

import ast
import io
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarmctl import SwarmStore  # noqa: E402
from swarmctl import mcp_server  # noqa: E402
from swarmctl.adapters import RUNNER_TEMPLATES  # noqa: E402
from swarmctl.mcp_server import serve_stdio  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
LAUNCHER = SCRIPTS / "bin" / "swarmctl"


def git_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo),
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    return repo


def make_env(tmp: Path, **extra: str) -> dict[str, str]:
    fakebin = tmp / "fakebin"
    fakebin.mkdir(exist_ok=True)
    stub = fakebin / "claude"
    if not stub.exists():
        stub.write_text('#!/bin/sh\necho \'{"session_id":"sid-stub","result":"ok"}\'\nexit 0\n')
        stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SWARMCTL_")}
    env.update(HOME=str(tmp), PATH=f"{fakebin}{os.pathsep}{env.get('PATH', '')}")
    env.update(extra)
    return env


def kill_stray(tmp: Path) -> None:
    me = os.getpid()
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if str(tmp) in cmd:
            try:
                os.kill(int(p.name), signal.SIGKILL)
            except OSError:
                pass


def req(i: int, method: str, params: dict | None = None) -> dict:
    d: dict = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        d["params"] = params
    return d


def call(i: int, name: str, args: dict | None = None) -> dict:
    return req(i, "tools/call", {"name": name, "arguments": args or {}})


def run_direct(swarm_dir: Path, lines, role: str = "coordinator", agent: str | None = None, env: dict | None = None) -> list[dict]:
    """Run serve_stdio on injected streams; `lines` items are dicts or raw strings (or a generator)."""
    def gen():
        for item in lines:
            yield (item if isinstance(item, str) else json.dumps(item)) + "\n"
    out = io.StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=False):
        for k in list(os.environ):
            if k.startswith("SWARMCTL_") and k not in (env or {}):
                del os.environ[k]
        rc = serve_stdio(swarm_dir, agent, role, stdin=gen(), stdout=out)
    assert rc == 0
    return [json.loads(x) for x in out.getvalue().splitlines()]


def payload(resp: dict):
    return json.loads(resp["result"]["content"][0]["text"])


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name).resolve()
        self.repo = git_repo(self.tmp)
        self.sdir = self.repo / ".swarm" / "default"
        self.procs: list[subprocess.Popen] = []
        self.wake = mock.patch.object(mcp_server, "ensure_supervisor", return_value=None)
        self.wake_mock = self.wake.start()

    def tearDown(self) -> None:
        self.wake.stop()
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)
            for s in (p.stdin, p.stdout, p.stderr):
                if s:
                    s.close()
        kill_stray(self.tmp)
        self._td.cleanup()

    def init_store(self) -> None:
        with SwarmStore(self.sdir / "board.db") as st:
            st.init_swarm("default", str(self.repo))


class TestMcpSubprocessCUJ5(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.wake.stop()  # real supervisor wake, but with fake claude on PATH
        self.wake = mock.patch.object(mcp_server, "ensure_supervisor", return_value=None)
        self.env = make_env(self.tmp)

    def spawn(self, *args: str, env: dict | None = None) -> subprocess.Popen:
        p = subprocess.Popen([sys.executable, str(LAUNCHER), "--repo", str(self.repo), *args], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env or self.env)
        self.procs.append(p)
        return p

    def rpc(self, p: subprocess.Popen, obj: dict) -> dict:
        p.stdin.write(json.dumps(obj) + "\n")
        p.stdin.flush()
        timer = threading.Timer(15, p.kill)
        timer.start()
        try:
            line = p.stdout.readline()
        finally:
            timer.cancel()
        self.assertTrue(line, "no response line")
        self.lines.append(line)
        return json.loads(line)

    def test_initialize_ping_list_and_no_output_for_notification(self) -> None:
        self.lines: list[str] = []
        p = self.spawn("mcp")
        r = self.rpc(p, req(1, "initialize", {"protocolVersion": "2025-03-26"}))
        self.assertEqual(r["result"]["serverInfo"]["name"], "swarmctl")
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        self.assertEqual(self.rpc(p, req(2, "ping"))["result"], {})  # next line is ping => notification emitted nothing
        tools = self.rpc(p, req(3, "tools/list"))["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"swarm", "post_message", "read_board", "swarm_wait"})
        for t in tools:
            self.assertIs(t["inputSchema"]["additionalProperties"], False)
        p.stdin.close()
        self.assertEqual(p.wait(timeout=10), 0)

    def test_full_tool_flow_envelopes(self) -> None:
        self.lines = []
        p = self.spawn("mcp")
        def tool(i, name, args):
            r = self.rpc(p, call(i, name, args))
            self.assertEqual(r["jsonrpc"], "2.0")
            self.assertEqual(r["result"]["content"][0]["type"], "text")
            self.assertIs(r["result"]["isError"], False, r)
            return payload(r)
        self.assertEqual(tool(1, "swarm", {"action": "models"})["default_runner"], "claude")
        self.assertEqual(tool(2, "swarm", {"action": "title", "title": "T"})["title"], "T")
        w = tool(3, "swarm", {"action": "add", "name": "w1", "brief": "do thing"})
        self.assertEqual(w["name"], "w1")
        self.assertNotIn("worker_token", w)
        st = tool(4, "swarm", {"action": "status"})
        self.assertEqual([x["name"] for x in st["workers"]], ["w1"])
        # let the stub-backed worker finish its turn so `model` is permitted
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if tool(5, "swarm", {"action": "status"})["workers"][0]["state"] in ("waiting", "stopped"):
                break
            time.sleep(0.1)
        self.assertEqual(tool(6, "swarm", {"action": "model", "name": "w1", "model": "opus"})["model"], "opus")
        posted = tool(7, "post_message", {"text": "hello @w1"})
        self.assertEqual(posted["sender"], "coordinator")
        board = tool(8, "read_board", {})
        self.assertGreaterEqual(len(board["messages"]), 2)
        head = board["head_seq"]
        # swarm_wait wake <= 500ms after a mention is posted by another process
        done: dict = {}
        def poster() -> None:
            time.sleep(0.2)
            subprocess.run([sys.executable, str(LAUNCHER), "--repo", str(self.repo), "post", "--as", "human",
                            "--no-wake", "@coordinator hi"], env=self.env, check=True, capture_output=True, timeout=30)
            done["t"] = time.monotonic()
        th = threading.Thread(target=poster)
        th.start()
        res = tool(9, "swarm_wait", {"since": head, "timeout_sec": 20})
        t_resp = time.monotonic()
        th.join()
        self.assertFalse(res["timed_out"])
        self.assertLess(t_resp - done["t"], 0.7)
        killed = tool(10, "swarm", {"action": "kill", "name": "w1"})
        self.assertEqual(killed["state"], "killed")
        for line in self.lines:
            self.assertEqual(json.loads(line)["jsonrpc"], "2.0")
            self.assertNotIn("worker_token", line)
        p.stdin.close()
        self.assertEqual(p.wait(timeout=10), 0)

    def test_stdout_not_polluted_by_children(self) -> None:
        self.lines = []
        p = self.spawn("mcp")
        r = self.rpc(p, call(1, "swarm", {"action": "add", "name": "w2", "brief": "x", "workspace": "share"}))
        self.assertIs(r["result"]["isError"], False, r)
        p.stdin.close()
        out = p.stdout.read()
        self.assertEqual(p.wait(timeout=10), 0)
        for line in out.splitlines():
            json.loads(line)


class TestMcpProtocolEdge5(_Base):
    def one(self, obj, **kw) -> dict:
        return run_direct(self.sdir, [obj], **kw)[0]

    def test_parse_error_32700(self) -> None:
        r = self.one("{not json")
        self.assertEqual((r["error"]["code"], r["id"]), (-32700, None))

    def test_invalid_request_32600_variants(self) -> None:
        cases = ["[1]", '"x"', '{"jsonrpc":"1.0","id":1,"method":"ping"}', '{"jsonrpc":"2.0","id":1}',
                 '{"jsonrpc":"2.0","id":null,"method":"ping"}', '{"jsonrpc":"2.0","id":true,"method":"ping"}',
                 '{"jsonrpc":"2.0","id":[],"method":"ping"}', '{"jsonrpc":"2.0","id":1,"method":5}']
        out = run_direct(self.sdir, cases)
        self.assertEqual([o["error"]["code"] for o in out], [-32600] * len(cases))
        self.assertIsNone(out[4]["id"])
        self.assertEqual(out[3]["id"], 1)

    def test_unknown_method_32601(self) -> None:
        self.assertEqual(self.one(req(1, "nope"))["error"]["code"], -32601)

    def test_inbound_response_ignored(self) -> None:
        out = run_direct(self.sdir, [{"jsonrpc": "2.0", "id": 9, "result": {}}, {"jsonrpc": "2.0", "id": 9, "error": {"code": 1, "message": "x"}},
                                     "", "   ", req(1, "ping")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 1)

    def test_unknown_tool_and_unknown_arg_32602(self) -> None:
        out = run_direct(self.sdir, [call(1, "bogus"), call(2, "read_board", {"nope": 1}), call(3, "swarm", {"action": "zzz"}),
                                     req(4, "tools/call", {"name": 5}), req(5, "tools/call", {"name": "swarm", "arguments": []})])
        self.assertEqual([o["error"]["code"] for o in out], [-32602] * 5)

    def test_bool_as_int_32602(self) -> None:
        out = run_direct(self.sdir, [call(1, "read_board", {"limit": True}), call(2, "swarm_wait", {"since": True}),
                                     call(3, "swarm_wait", {"since": 0, "timeout_sec": True}), call(4, "read_board", {"since": -1})])
        self.assertEqual([o["error"]["code"] for o in out], [-32602] * 4)

    def test_model_on_working_and_killed_32602(self) -> None:
        self.init_store()
        with SwarmStore(self.sdir / "board.db") as st:
            st.add_worker("a", "go")
            st.add_worker("b", "go")
        db = sqlite3.connect(self.sdir / "board.db")
        db.execute("UPDATE workers SET state='working' WHERE name='a'")
        db.execute("UPDATE workers SET state='killed' WHERE name='b'")
        db.commit()
        db.close()
        out = run_direct(self.sdir, [call(1, "swarm", {"action": "model", "name": "a", "model": "opus"}),
                                     call(2, "swarm", {"action": "model", "name": "b", "model": "opus"}),
                                     call(3, "swarm", {"action": "model", "name": "ghost", "model": "opus"})])
        self.assertEqual([o["error"]["code"] for o in out], [-32602] * 3)

    def test_swarm_wait_timeout_absent_db(self) -> None:
        r = self.one(call(1, "swarm_wait", {"since": 7, "timeout_sec": 0.2}))
        self.assertEqual(payload(r), {"messages": [], "timed_out": True, "head_seq": 7})
        self.assertFalse((self.repo / ".swarm").exists())

    def test_absent_db_status_and_read_do_not_create_swarm_dir(self) -> None:
        out = run_direct(self.sdir, [call(1, "swarm", {"action": "status"}), call(2, "read_board", {}), call(3, "read_board", {"status": True}),
                                     call(4, "swarm", {"action": "kill", "name": "x"})])
        self.assertEqual(payload(out[0]), {"swarm_id": "default", "title": "", "head_seq": 0, "workers": []})
        self.assertEqual(payload(out[1]), {"messages": [], "head_seq": 0})
        self.assertEqual(payload(out[2])["workers"], [])
        self.assertEqual(out[3]["error"]["code"], -32602)
        self.assertFalse((self.repo / ".swarm").exists())

    def test_models_never_touches_disk(self) -> None:
        r = self.one(call(1, "swarm", {"action": "models"}))
        self.assertIn("claude", payload(r)["runners"])
        self.assertFalse((self.repo / ".swarm").exists())

    def test_initialize_version_negotiation(self) -> None:
        out = run_direct(self.sdir, [req(1, "initialize", {"protocolVersion": "2025-03-26"}),
                                     req(2, "initialize", {"protocolVersion": "1999-01-01"}), req(3, "initialize")])
        self.assertEqual([o["result"]["protocolVersion"] for o in out], ["2025-03-26", "2024-11-05", "2024-11-05"])


class TestMcpWorkerRoleEdge6(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.init_store()
        with SwarmStore(self.sdir / "board.db") as st:
            st.add_worker("w1", "work")
            self.token = st.get_worker("w1")["worker_token"]
        self.wenv = {"SWARMCTL_WORKER_TOKEN": self.token}

    def worker(self, lines, **kw):
        return run_direct(self.sdir, lines, role="worker", agent="w1", env=self.wenv, **kw)

    def test_worker_tools_list_only_post_and_read(self) -> None:
        tools = self.worker([req(1, "tools/list")])[0]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["post_message", "read_board"])

    def test_worker_swarm_and_wait_and_status_and_spoof_32600(self) -> None:
        out = self.worker([call(1, "swarm", {"action": "status"}), call(2, "swarm_wait", {"since": 0}),
                           call(3, "read_board", {"status": True}), call(4, "post_message", {"text": "x", "sender": "coordinator"}),
                           call(5, "nonexistent")])
        self.assertEqual([o["error"]["code"] for o in out], [-32600, -32600, -32600, -32600, -32602])

    def test_worker_post_attributed_and_no_wake(self) -> None:
        out = self.worker([call(1, "post_message", {"text": "@coordinator done"}), call(2, "post_message", {"text": "again", "sender": "w1"})])
        self.assertEqual([payload(o)["sender"] for o in out], ["w1", "w1"])
        self.wake_mock.assert_not_called()

    def test_revoked_token_32600(self) -> None:
        def lines():
            yield call(1, "read_board", {})
            with SwarmStore(self.sdir / "board.db") as st:
                st.mark_killing("w1")
                st.mark_killed("w1")
            yield call(2, "read_board", {})
            yield call(3, "post_message", {"text": "x"})
        out = self.worker(lines())
        self.assertIs(out[0]["result"]["isError"], False)
        self.assertEqual([o["error"]["code"] for o in out[1:]], [-32600, -32600])

    def test_worker_env_forbids_coordinator_role(self) -> None:
        with self.assertRaises(PermissionError):
            run_direct(self.sdir, [], role="coordinator", env=self.wenv)
        with self.assertRaises(PermissionError):
            run_direct(self.sdir, [], role="coordinator", env={"SWARMCTL_ROLE": "worker"})

    def test_worker_requires_existing_db_and_token(self) -> None:
        with self.assertRaises(PermissionError):
            run_direct(self.sdir, [], role="worker", agent="w1")
        empty = self.tmp / "other" / ".swarm" / "default"
        with self.assertRaises(FileNotFoundError):
            run_direct(empty, [], role="worker", agent="w1", env=self.wenv)
        self.assertFalse(empty.exists())
        with self.assertRaises(PermissionError):
            run_direct(self.sdir, [], role="worker", env={"SWARMCTL_WORKER_TOKEN": "bogus"})

    def test_agent_mismatch_permission_error(self) -> None:
        with self.assertRaises(PermissionError):
            run_direct(self.sdir, [], role="worker", agent="other", env=self.wenv)
        with self.assertRaises(PermissionError):
            run_direct(self.sdir, [], role="worker", agent="w1", env={**self.wenv, "SWARMCTL_AGENT": "other"})
        with self.assertRaises(PermissionError):
            run_direct(self.sdir, [], role="coordinator", agent="w1")  # collides with existing worker

    def test_bad_swarm_dir_valueerror(self) -> None:
        with self.assertRaises(ValueError):
            run_direct(self.tmp / "not-swarm" / "default", [])
        with self.assertRaises(ValueError):
            run_direct(self.repo / ".swarm" / "bad id!", [])
        with self.assertRaises(ValueError):
            run_direct(self.sdir, [], role="admin")

    def test_worker_subprocess_cli_mcp(self) -> None:
        env = make_env(self.tmp, SWARMCTL_WORKER_TOKEN=self.token, SWARMCTL_ROLE="worker", SWARMCTL_AGENT="w1")
        p = subprocess.Popen([sys.executable, str(LAUNCHER), "--repo", str(self.repo), "mcp"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.procs.append(p)
        out, _ = p.communicate(json.dumps(req(1, "tools/list")) + "\n" + json.dumps(call(2, "swarm", {"action": "status"})) + "\n", timeout=30)
        lines = [json.loads(x) for x in out.splitlines()]
        self.assertEqual([t["name"] for t in lines[0]["result"]["tools"]], ["post_message", "read_board"])
        self.assertEqual(lines[1]["error"]["code"], -32600)

    def test_unmapped_template_mode_without_unsafe_32600(self) -> None:
        runner = next((k for k, t in RUNNER_TEMPLATES.items() if t["permission_flags"]["readonly"] is None), None)
        if runner is None:
            self.skipTest("no runner with unmapped readonly mode")
        with mock.patch.dict(os.environ, {"SWARMCTL_CUSTOM_CMD": "echo hi"}):
            out = run_direct(self.sdir, [call(1, "swarm", {"action": "add", "name": "w9", "brief": "b", "runner": runner, "workspace": "inherit"})])
        self.assertEqual(out[0]["error"]["code"], -32600)
        with SwarmStore(self.sdir / "board.db") as st:
            self.assertIsNone(st.get_worker("w9"))

    def test_deny_unsafe_env_32600(self) -> None:
        out = run_direct(self.sdir, [call(1, "swarm", {"action": "add", "name": "w8", "brief": "b", "unsafe": True})],
                         env={"SWARMCTL_DENY_UNSAFE": "1"})
        self.assertEqual(out[0]["error"]["code"], -32600)

    def test_kill_dirty_share_isError_unless_force(self) -> None:
        out = run_direct(self.sdir, [call(1, "swarm", {"action": "add", "name": "sh", "brief": "b", "workspace": "share"})])
        w = payload(out[0])
        wt = Path(w["workspace_path"])
        self.assertTrue(wt.is_dir())
        (wt / "dirty.txt").write_text("x")
        out = run_direct(self.sdir, [call(1, "swarm", {"action": "kill", "name": "sh"})])
        self.assertIs(out[0]["result"]["isError"], True)
        self.assertIn("error", payload(out[0]))
        self.assertTrue(wt.exists())
        out = run_direct(self.sdir, [call(1, "swarm", {"action": "kill", "name": "sh", "force": True})])
        self.assertIs(out[0]["result"]["isError"], False, out)
        self.assertEqual(payload(out[0])["state"], "killed")
        self.assertFalse(wt.exists())


class TestMcpParity(_Base):
    def cli_models(self, *extra: str) -> dict:
        r = subprocess.run([sys.executable, str(LAUNCHER), "--repo", str(self.repo), "--json", "models", *extra],
                           capture_output=True, text=True, timeout=30, env=make_env(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_models_parity_with_cli(self) -> None:
        out = run_direct(self.sdir, [call(1, "swarm", {"action": "models"}), call(2, "swarm", {"action": "models", "all": True})])
        self.assertEqual(payload(out[0]), self.cli_models())
        self.assertEqual(payload(out[1]), self.cli_models("--all"))

    def test_no_cli_import_in_mcp_server(self) -> None:
        tree = ast.parse(Path(mcp_server.__file__).read_text())
        allowed_rel = {"store", "worktree", "adapters", "supervisor"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertIn(a.name.split(".")[0], sys.stdlib_module_names, a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.module is None:
                        self.assertEqual({a.name for a in node.names}, {"__version__"})
                    else:
                        self.assertIn(node.module, allowed_rel)
                else:
                    self.assertIn((node.module or "").split(".")[0], sys.stdlib_module_names)



REPO_ROOT = Path(__file__).resolve().parents[4]


class TestPackagingCUJ6(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.skills = self.tmp / "skills"
        self.launcher = REPO_ROOT / "claude/swarmctl/scripts/bin/swarmctl"
        self.skill_src = REPO_ROOT / "claude/swarmctl/skills/swarmctl"

    def run_install(self, *args):
        env = {**os.environ, "HOME": str(self.home)}
        return subprocess.run(["bash", "install.sh", *args], cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True, timeout=60)

    def assert_home_clean(self):
        for d in (".claude", ".gemini"):
            self.assertFalse((self.home / d).exists(), d)

    # --- static packaging ---
    def test_plugin_json(self):
        import swarmctl
        data = json.loads((REPO_ROOT / "claude/swarmctl/.claude-plugin/plugin.json").read_text())
        self.assertEqual(data["name"], "swarmctl")
        self.assertEqual(data["version"], swarmctl.__version__)
        srv = data["mcpServers"]["swarmctl"]
        self.assertEqual(srv["command"], "${CLAUDE_PLUGIN_ROOT}/scripts/bin/swarmctl")
        self.assertEqual(srv["args"], ["mcp"])
        self.assertTrue(self.launcher.is_file())
        self.assertTrue(os.access(self.launcher, os.X_OK))

    def test_marketplace_json(self):
        data = json.loads((REPO_ROOT / ".claude-plugin/marketplace.json").read_text())
        by_name = {p["name"]: p for p in data["plugins"]}
        self.assertEqual(by_name["swarmctl"]["source"], "./claude/swarmctl")
        self.assertEqual(by_name["swarmctl"]["category"], "development")
        for n in ("deep-review", "build-loop", "egm-runbook"):
            self.assertEqual(by_name[n]["source"], f"./claude/{n}")

    def test_skill_frontmatter(self):
        text = (self.skill_src / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---"))
        head = text.split("---", 2)[1]
        self.assertIn("name: swarmctl", head)
        desc = [l for l in head.splitlines() if l.startswith("description:")]
        self.assertTrue(desc and desc[0][len("description:"):].strip())

    def test_gitignore_and_portability(self):
        lines = (REPO_ROOT / ".gitignore").read_text().splitlines()
        self.assertIn(".swarm/", lines)
        self.assertIn("swarmctl", (REPO_ROOT / "docs/PORTABILITY.md").read_text())

    # --- hermetic installer ---
    def test_status_default_runs(self):
        r = self.run_install("--status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("swarmctl", r.stdout)
        self.assert_home_clean()

    def test_skills_only_swarmctl(self):
        r = self.run_install("--skills", str(self.skills), "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        link = self.skills / "swarmctl"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), self.skill_src.resolve())
        self.assertIn("swarmctl mcp", r.stdout)

    def test_bin_dir_only(self):
        r = self.run_install("--bin-dir", str(self.bin), "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        link = self.bin / "swarmctl"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), self.launcher.resolve())
        out = subprocess.run([str(link), "models", "--json"], capture_output=True,
                             text=True, timeout=30, env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(json.loads(out.stdout)["default_runner"], "claude")
        self.assert_home_clean()
        r2 = self.run_install("--bin-dir", str(self.bin), "--only", "swarmctl")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("already linked", r2.stdout)

    def test_bin_dir_backs_up_foreign_symlink_and_file(self):
        self.bin.mkdir()
        dst = self.bin / "swarmctl"
        backups = self.home / ".cache/ai-plugins-backups"
        dst.symlink_to("/bin/true")
        r = self.run_install("--bin-dir", str(self.bin), "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(dst.resolve(), self.launcher.resolve())
        self.assertEqual(len(list(backups.glob("swarmctl.bak.*"))), 1)
        for b in backups.glob("swarmctl.bak.*"):
            b.unlink()
        dst.unlink()
        dst.write_text("#!/bin/sh\n")
        r = self.run_install("--bin-dir", str(self.bin), "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(dst.is_symlink())
        self.assertEqual(dst.resolve(), self.launcher.resolve())
        self.assertEqual(len(list(backups.glob("swarmctl.bak.*"))), 1)

    def test_bin_dir_copy_mode_still_symlinks(self):
        r = self.run_install("--copy", "--bin-dir", str(self.bin), "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.bin / "swarmctl").is_symlink())

    def test_skills_plus_bin_dir_no_double_link(self):
        r = self.run_install("--skills", str(self.skills), "--bin-dir", str(self.bin),
                             "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.skills / "swarmctl").is_symlink())
        self.assertTrue((self.bin / "swarmctl").is_symlink())
        self.assertEqual(r.stdout.count("Bin: linked"), 1)

    def test_bin_dir_no_match_exit_1(self):
        r = self.run_install("--bin-dir", str(self.bin), "--only", "nonexistent")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no binaries matched", r.stderr)

    def test_bin_dir_bad_values(self):
        for args in (["--bin-dir"], ["--bin-dir="], ["--bin-dir", "-x"]):
            r = self.run_install(*args)
            self.assertEqual(r.returncode, 1, args)

    def test_uninstall_clean(self):
        flags = ["--skills", str(self.skills), "--bin-dir", str(self.bin), "--only", "swarmctl"]
        self.assertEqual(self.run_install(*flags).returncode, 0)
        r = self.run_install(*flags, "--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.skills / "swarmctl").exists())
        self.assertFalse((self.bin / "swarmctl").is_symlink())
        # foreign file is left alone
        (self.bin / "swarmctl").write_text("keep")
        r = self.run_install("--bin-dir", str(self.bin), "--only", "swarmctl", "--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.bin / "swarmctl").read_text(), "keep")

    def test_status_bin_dir(self):
        args = ("--bin-dir", str(self.bin), "--only", "swarmctl")
        r = self.run_install(*args, "--status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[missing]", r.stdout)
        self.assertFalse(self.bin.exists())
        self.assertEqual(self.run_install(*args).returncode, 0)
        r = self.run_install(*args, "--status")
        self.assertIn("[linked]", r.stdout)

    def test_bin_dir_does_not_touch_antigravity(self):
        r = self.run_install("--bin-dir", str(self.bin), "--only", "swarmctl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_home_clean()


if __name__ == "__main__":
    unittest.main()
