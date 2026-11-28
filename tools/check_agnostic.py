#!/usr/bin/env python3
"""INV-2 / INV-8 grep gate: plugin text and manifests stay harness-agnostic outside adapter paths.

Usage: check_agnostic.py [repo_root]. Prints one problem per line; exit 1 when any are found.
"""
import json
import re
import sys
from pathlib import Path

# Model-family words, provider model-ID shapes (harness names like Gemini CLI stay legal), .gemini install paths,
# and plugin-root/data variables. Bare "claude"/"codex" stay legal outside core lean-runbook (tested more strictly in
# tools/test_agnostic_skills.py).
FORBIDDEN = re.compile(
    r"\.gemini\b|\b(?:CLAUDE_)?PLUGIN_(?:ROOT|DATA)\b|"
    r"claude-(?:\d|opus|sonnet|haiku|fable|sub|instant)\b|gpt-(?!style\b)\w|gpt\s*\d|"
    r"gemini-(?!cli\b)\w|gemini\s*\d|\bo[134](?:-(?:mini|pro|preview))?\b|"
    r"\b(?:opus|sonnet|haiku|fable)\b|"
    r"\b(?:deepseek-[\w.-]+|qwen[\d.-]*-[\w.-]+|llama-\d[\w.-]*|mistral-[\w.-]+|grok-\d[\w.-]*|kimi-[\w.-]+|codex-mini)\b",
    re.I,
)
GUIDANCE_FORBIDDEN = re.compile(r"\bnative\s+swarm\b|workflows/", re.I)
PROBE_RE = re.compile(r"--version|`\s*(?:which|type)\s+\S|^\s*\$\s*(?:which|type)\s+\S", re.M)
FENCED_PROBE_RE = re.compile(r"^\s*(?:which|type)\s+[a-z0-9._-]+(?:\s|$)", re.M)
COMMAND_V_RE = re.compile(r"\bcommand\s+-v\s+([\w-]+)")
ALLOWED_COMMAND_V = {"lean-runbook": {"swarmctl"}, "build-loop": {"swarmctl", "codex", "kiro-cli"}}
ALLOWED = re.compile(r"^plugins/[^/]+/skills/[^/]+/references/(?:harness|version)-[^/]+\.md$")  # strict adapter paths
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


def _next_guidance_lines(text: str) -> list:
    """Return (lineno, line) pairs inside `def next_guidance(...)`."""
    lines = text.splitlines()
    out = []
    inside = False
    for idx, line in enumerate(lines, 1):
        if re.match(r"^def\s+next_guidance\b", line):
            inside = True
        elif inside and line and not line[0].isspace():
            inside = False
        if inside:
            out.append((idx, line))
    return out


def scan(root: Path) -> list:
    root = Path(root)
    rel = lambda p: p.relative_to(root).as_posix()
    bad = []
    for plugin in sorted((root / "plugins").glob("*")):
        pname = plugin.name
        for pattern in TEXT_GLOBS:
            for f in sorted(plugin.glob(pattern)):
                rpath = rel(f)
                if ALLOWED.match(rpath):
                    continue
                text = f.read_text()
                for n, line in enumerate(text.splitlines(), 1):
                    for m in FORBIDDEN.finditer(line):
                        bad.append(f"{rpath}:{n}: forbidden {m.group(0)!r} outside adapter paths")
                if pattern == "skills/**/*.md":
                    for m in PROBE_RE.finditer(text):
                        bad.append(f"{rpath}: forbidden runtime probe {m.group(0).strip()!r} (INV-9)")
                    for blk in re.findall(r"```(?:bash|sh|shell|zsh)?\n(.*?)```", text, re.S):
                        for m in FENCED_PROBE_RE.finditer(blk):
                            bad.append(f"{rpath}: forbidden runtime probe {m.group(0).strip()!r} (INV-9)")
                    ok_bins = ALLOWED_COMMAND_V.get(pname, {"swarmctl"})
                    for m in COMMAND_V_RE.finditer(text):
                        if m.group(1) not in ok_bins:
                            bad.append(f"{rpath}: forbidden runtime probe 'command -v {m.group(1)}' (INV-9)")
        for f in sorted(plugin.glob("skills/*/scripts/*.py")):
            rpath = rel(f)
            for n, line in _next_guidance_lines(f.read_text()):
                for rx in (FORBIDDEN, GUIDANCE_FORBIDDEN):
                    for m in rx.finditer(line):
                        bad.append(f"{rpath}:{n}: forbidden {m.group(0)!r} in next_guidance()")
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
