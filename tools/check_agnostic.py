#!/usr/bin/env python3
"""INV-2 / INV-8 grep gate: plugin text and manifests stay harness-agnostic outside adapter paths.

Usage: check_agnostic.py [repo_root]. Prints one problem per line; exit 1 when any are found.
"""
import json
import re
import sys
from pathlib import Path

# ~/.gemini, ${CLAUDE_PLUGIN_ROOT}, or a provider model ID (same families as tools/test_agnostic_skills.py).
FORBIDDEN = re.compile(r"~/\.gemini|\$\{CLAUDE_PLUGIN_ROOT\}|gemini-\d|gemini-[a-z]+-|claude-(?:opus|sonnet|haiku)|gpt-\d", re.I)
ALLOWED = re.compile(r"(?:^|/)references/(?:harness|version)-[^/]*\.md$")  # adapter paths
TEXT_GLOBS = ("skills/**/*.md", "agents/*.md", "templates/*.md", "rules/*.md")
BAD_KEYS = ("dependencies", "allowCrossMarketplaceDependenciesOn")


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
                        bad.append(f"{rel(f)}:{n}: forbidden {m.group(0)!r} outside adapter paths")
        for f in sorted(plugin.glob("agents/*.md")):
            if not re.search(r"\A---\n(?:.*\n)*?model:\s*inherit\s*\n(?:.*\n)*?---", f.read_text()):
                bad.append(f"{rel(f)}: agent must declare 'model: inherit'")
    manifests = [*root.glob("plugins/*/.claude-plugin/plugin.json"), *root.glob("plugins/*/plugin.json"),
                 root / ".claude-plugin/marketplace.json"]
    for f in manifests:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue  # gate.sh reports invalid JSON
        bad += [f"{rel(f)}: manifest key {k!r} is forbidden" for k in BAD_KEYS if isinstance(data, dict) and k in data]
    return bad


def main(argv) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    problems = scan(root)
    if problems:
        print("\n".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
