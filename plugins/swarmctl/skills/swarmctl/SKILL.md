---
name: swarmctl
description: Use when delegating parallel side-work to background Claude/Codex/OpenCode/Gemini workers through the swarmctl MCP tools or CLI, coordinating them over a shared message board.
---

# swarmctl

A minimal local swarm: spawn background workers, talk to them through a shared board, wait for replies. No API key is needed for the default runner (your Claude subscription CLI).

## MCP tools

| Tool | Purpose |
|---|---|
| `swarm` | Manage workers. `action`: `models` (list runners), `add` (spawn), `status`, `title`, `model`, `kill`. |
| `post_message` | Post to the board; `@worker-name` or `@all` wakes the target. |
| `read_board` | Read messages (`since`, `limit`). |
| `swarm_wait` | Block until a message for you arrives (`since`, `timeout_sec`, default 45s). Returns `timed_out` and `head_seq`. |

## CLI parity

`swarmctl add | status | post | read | wait | kill | models` (plus `swarmctl mcp` to serve stdio MCP). Use `--repo <dir>` to pick the repository; state lives in `<repo>/.swarm/`.

## Runners

Default runner is `claude`. Others: `codex`, `opencode`, `gemini`, `custom`. Run `swarmctl models` (or `swarm action=models`) to see what is available and the default.

## Workspace guardrails

- `inherit`: worker runs read-only in your checkout.
- `share`: worker may edit, inside its own git worktree.
- `unsafe`: explicit opt-in only.
- Killing a `share` worker with uncommitted changes requires `force`.

## Workflow

1. `swarm add` a worker with a clear task and a workspace mode.
2. Continue your own work; `post_message` with `@worker` to steer it.
3. `swarm_wait` for the reply (or `read_board`), then `kill` when done.

## Honest note

Coordinator mode is human-trusted. There is no OS jail: workers run as you, so guardrails are workflow safety, not a security boundary.
