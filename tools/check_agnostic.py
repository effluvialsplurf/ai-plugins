#!/usr/bin/env python3
"""INV-2 / INV-8 grep gate: plugin text and manifests stay harness-agnostic outside adapter paths.

Usage: check_agnostic.py [repo_root]. Prints one problem per line; exit 1 when any are found.
"""
import json
import re
import sys
from pathlib import Path

# Model-family words, provider model IDs, .gemini install paths and plugin-root/data variables. Deliberately NOT bare
# "claude"/"codex": Claude-first plugins legitimately name their harness and the codex CLI. Narrower than
# tools/test_agnostic_skills.py (SLICE-5, core lean-runbook skills), which also bans those two words.
# INV-9 (no version probes) is enforced for the core skills by SLICE-5's test, not here; build-loop is out of its scope.
FORBIDDEN = re.compile(
    r"\.gemini\b|PLUGIN_(?:ROOT|DATA)|claude-(?:\d|opus|sonnet|haiku|fable|sub)|gpt-\w|\bo[1-9]\b|"
    r"\b(?:gemini|opus|sonnet|haiku|fable|gpt)\b", re.I)
# swarmctl's job is to drive runner CLIs, so it may name them; IDs, paths and variables are still banned there.
RUNNER_OK = {"swarmctl": re.compile(r"\b(?:gemini|gpt)\b", re.I)}
ALLOWED = re.compile(r"(?:^|/)references/(?:harness|version)-[^/]*\.md$")  # adapter paths
# Antigravity hooks.json is scanned; Claude-only hooks/hooks.json and .claude-plugin manifests are not text-scanned
# (swarmctl's mcpServers legitimately uses ${CLAUDE_PLUGIN_ROOT}); manifests get the key check below instead.
TEXT_GLOBS = ("skills/**/*.md", "agents/*.md", "templates/*.md", "rules/*.md", "hooks.json")
BAD_KEYS = ("dependencies", "allowCrossMarketplaceDependenciesOn")


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def scan(root: Path) -> list:
    root = Path(root)
    rel = lambda p: p.relative_to(root).as_posix()
    bad = []
    for plugin in sorted((root / "plugins").glob("*")):
        for pattern in TEXT_GLOBS:
            for f in sorted(plugin.glob(pattern)):
                if ALLOWED.search(rel(f)):
                    continue
                text = f.read_text()
                for n, line in enumerate(text.splitlines(), 1):
                    for m in FORBIDDEN.finditer(line):
                        ok = RUNNER_OK.get(plugin.name)
                        if ok and ok.fullmatch(m.group(0)) and not re.match(r"\.gemini|gpt-", line[m.start():], re.I):
                            continue
                        bad.append(f"{rel(f)}:{n}: forbidden {m.group(0)!r} outside adapter paths")
        for f in sorted(plugin.glob("agents/*.md")):
            fm = re.match(r"---\n(.*?\n)?---", f.read_text(), re.S)
            models = re.findall(r"^model:\s*(.*?)\s*$", fm.group(1) or "", re.M) if fm else []
            if not models or re.sub(r"\s+#.*$", "", models[-1]).strip("\"'") != "inherit":
                bad.append(f"{rel(f)}: agent must declare 'model: inherit'")
    manifests = [*root.glob("plugins/*/.claude-plugin/plugin.json"), *root.glob("plugins/*/plugin.json"),
                 root / ".claude-plugin/marketplace.json"]
    for f in manifests:
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            bad.append(f"{rel(f)}: manifest is not valid JSON")
            continue
        if not isinstance(data, dict):
            bad.append(f"{rel(f)}: manifest must be a JSON object")
        bad += [f"{rel(f)}: manifest key {k!r} is forbidden" for k in sorted(set(_keys(data)) & set(BAD_KEYS))]
    return bad


def main(argv) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    problems = scan(root)
    if problems:
        print("\n".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
