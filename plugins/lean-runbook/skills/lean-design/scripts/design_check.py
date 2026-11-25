#!/usr/bin/env python3
"""lean-design: stage tracker, read-time budget & canonical ID traceability validator.

Replaces EGM's sprawling artifact lifecycle with a strict 3-document suite under
docs/designs/<slug>/:
  - design.md     (BR-*, RISK-*, ADR-*)
  - tech-plan.md  (INV-*, references BR-*/RISK-*/ADR-*)
  - spec.md       (SLICE-*, CUJ-*, maps 100% of BR-*/RISK-*/INV-* for lean-runbook)

CLI subcommands:
  init <slug> [--mode greenfield|redesign] [--complex] [--out <dir>] [--force] [--cwd <repo>]
  status [<slug>] [--cwd <repo>]
  done <brief|draft|review|resolve|drift> <slug> [--cwd <repo>]
  check <suite_dir_or_slug> [--complex] [--strict] [--json] [--cwd <repo>]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGES = ("brief", "draft", "review", "resolve", "drift")
SUITE_FILES = ("design.md", "tech-plan.md", "spec.md")

# Read-time model: 200 words/min deep technical reading + diagram/table absorption
WORDS_PER_MINUTE = 200.0
MIN_PER_DIAGRAM = 0.5
MIN_PER_TABLE = 0.25

# Budget tiers
BUDGETS = {
    "standard": {
        "per_doc_words": {"design.md": 1400, "tech-plan.md": 1400, "spec.md": 1200},
        "total_words_target": 4000,
        "total_words_hard": 4400,
        "read_min_target": 20.0,
        "read_min_hard": 24.0,
    },
    "complex": {
        "per_doc_words": {"design.md": 3600, "tech-plan.md": 3600, "spec.md": 3300},
        "total_words_target": 10500,
        "total_words_hard": 11500,
        "read_min_target": 55.0,
        "read_min_hard": 60.0,
    },
}

MAX_CODE_BLOCK_WARN_LINES = 25
MAX_CODE_BLOCK_HARD_LINES = 40
MAX_SLICE_COMMITS = 3
MAX_SLICE_LOC = 600

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = SCRIPT_DIR.parent / "templates"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sanitize_slug(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", raw.strip()).strip("-").lower()


def data_root() -> Path:
    env = os.environ.get("LEAN_DESIGN_DATA")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "lean-design"


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


def repo_state_dir(repo: Path) -> Path:
    h = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:16]
    return data_root() / "repos" / h


def state_path_for(repo: Path, slug: str) -> Path:
    return repo_state_dir(repo) / f"{sanitize_slug(slug)}.json"


def load_state(repo: Path, slug: str) -> dict[str, Any] | None:
    p = state_path_for(repo, slug)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_state(repo: Path, slug: str, state: dict[str, Any]) -> None:
    p = state_path_for(repo, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".design-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def list_states(repo: Path) -> list[dict[str, Any]]:
    d = repo_state_dir(repo)
    if not d.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(st, dict) and st.get("slug"):
                found.append(st)
        except Exception:
            continue
    return found


def current_stage(state: dict[str, Any]) -> tuple[int, str]:
    done = set(state.get("done", []))
    for idx, st in enumerate(STAGES, 1):
        if st not in done:
            return idx, st
    return len(STAGES), "done"


def next_guidance(state: dict[str, Any]) -> str:
    _, st = current_stage(state)
    slug = state.get("slug", "<slug>")
    out_dir = state.get("out_dir", f"docs/designs/{slug}")
    tier_flag = " --complex" if state.get("complex") else ""
    return {
        "brief": f"Run Stage 1 Elephant Interrogation and lock rulings in .loop/designs/{slug}/brief.md, then run `done brief {slug}`.",
        "draft": f"Draft design.md, tech-plan.md, and spec.md in {out_dir}/ via native swarm drafter, verify with `check {out_dir}{tier_flag}`, then run `done draft {slug}`.",
        "review": f"Run Stage 3 3-lens cross-vendor Goldfish review (clarity + opposite-vendor architect + handoff), consolidate into .loop/designs/{slug}/goldfish-report.md, then run `done review {slug}`.",
        "resolve": f"Resolve blockers/tradeoffs with user, compress to budget, run `check {out_dir}{tier_flag} --strict`, set Status: Approved, then run `done resolve {slug}`.",
        "drift": f"Design approved and ready for lean-runbook ({out_dir}/spec.md). After build, optionally run Stage 5 Drift Report and `done drift {slug}`.",
        "done": f"Design suite '{slug}' (including post-build drift report) is complete.",
    }.get(st, "")


def format_status(state: dict[str, Any]) -> str:
    idx, st = current_stage(state)
    tier = "complex (<=60m)" if state.get("complex") else "standard (15-20m)"
    return "\n".join([
        f"lean-design: {state['slug']} | mode={state.get('mode', 'greenfield')} | tier={tier} | Stage {idx}/{len(STAGES)} ({st})",
        f"Suite: {state.get('out_dir', 'docs/designs/' + state['slug'])}",
        f"Done: {', '.join(state.get('done', [])) or 'none'}",
        f"Next: {next_guidance(state)}",
    ])


# ---------------- Markdown Analysis & Validation ----------------

@dataclass
class DocStats:
    name: str
    path: Path
    words: int
    lines: int
    diagrams: int
    tables: int
    read_minutes: float
    large_code_blocks: list[tuple[int, str, int]] = field(default_factory=list)  # (start_line, lang, line_count)
    paragraphs: list[tuple[int, str, set[str]]] = field(default_factory=list)  # (line_no, snippet, norm_tokens)
    placeholders: list[str] = field(default_factory=list)
    status: str = ""


def _normalize_tokens(text: str) -> set[str]:
    cleaned = re.sub(r"`[^`]+`", " ", text)
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned.lower())
    return {t for t in cleaned.split() if len(t) > 2}


def analyze_markdown(path: Path) -> DocStats:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    in_fence = False
    fence_lang = ""
    fence_start = 0
    fence_lines = 0
    diagrams = 0
    tables = 0
    in_table = False
    word_count = 0
    large_code_blocks: list[tuple[int, str, int]] = []
    paragraphs: list[tuple[int, str, set[str]]] = []
    para_buf: list[str] = []
    para_start = 0
    status = ""

    def flush_para() -> None:
        nonlocal para_buf, para_start
        if not para_buf:
            return
        text = " ".join(para_buf).strip()
        words = re.findall(r"[A-Za-z0-9_'-]+", text)
        if len(words) >= 25:
            tokens = _normalize_tokens(text)
            if len(tokens) >= 12:
                snippet = text[:90] + ("..." if len(text) > 90 else "")
                paragraphs.append((para_start, snippet, tokens))
        para_buf = []
        para_start = 0

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()

        if not in_fence:
            m_status = re.match(r"^-\s+\*\*Status:\*\*\s*(.+)$", stripped)
            if m_status and not status:
                status = m_status.group(1).strip()

        m_fence = re.match(r"^(`{3,}|~{3,})\s*([A-Za-z0-9_-]*)", stripped)
        if m_fence:
            flush_para()
            in_table = False
            if not in_fence:
                in_fence = True
                fence_lang = (m_fence.group(2) or "").lower()
                fence_start = lineno
                fence_lines = 0
                if fence_lang == "mermaid":
                    diagrams += 1
            else:
                if fence_lang != "mermaid" and fence_lines > MAX_CODE_BLOCK_WARN_LINES:
                    large_code_blocks.append((fence_start, fence_lang or "plain", fence_lines))
                in_fence = False
                fence_lang = ""
                fence_lines = 0
            continue

        if in_fence:
            fence_lines += 1
            if fence_lang != "mermaid":
                word_count += len(re.findall(r"[A-Za-z0-9_'-]+", line))
            continue

        # Table separator line (|---|---|) does not add words
        if re.match(r"^\|?[\s:-]+\|[\s|:-]+$", stripped):
            continue

        is_table_row = stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2
        if is_table_row:
            flush_para()
            if not in_table:
                tables += 1
                in_table = True
            word_count += len(re.findall(r"[A-Za-z0-9_'-]+", stripped))
            continue
        else:
            in_table = False

        if not stripped:
            flush_para()
            continue

        # Headings, blockquotes, list items count words but don't join prose paragraphs
        word_count += len(re.findall(r"[A-Za-z0-9_'-]+", stripped))
        if stripped.startswith(("#", ">", "-", "*", "+")) or re.match(r"^\d+\.\s", stripped):
            flush_para()
        else:
            if not para_buf:
                para_start = lineno
            para_buf.append(stripped)

    flush_para()

    # Detect unfilled angle-bracket template placeholders outside code blocks
    no_code = re.sub(r"```.*?```", "", raw, flags=re.DOTALL)
    placeholders = sorted(set(re.findall(r"<(?:Project|slug|YYYY-MM-DD|Component|Sub |Entity|slice-slug|Rejected|input plan|e\.g\.,)[^>]*>", no_code)))

    read_minutes = round(
        (word_count / WORDS_PER_MINUTE) + (diagrams * MIN_PER_DIAGRAM) + (tables * MIN_PER_TABLE),
        1,
    )
    return DocStats(
        name=path.name,
        path=path,
        words=word_count,
        lines=len(lines),
        diagrams=diagrams,
        tables=tables,
        read_minutes=read_minutes,
        large_code_blocks=large_code_blocks,
        paragraphs=paragraphs,
        placeholders=placeholders,
        status=status,
    )


def extract_ids(text: str, prefix: str) -> set[str]:
    return set(re.findall(rf"\b{prefix}-\d+\b", text))


def find_oversized_slices(spec_text: str) -> list[str]:
    issues: list[str] = []
    for lineno, line in enumerate(spec_text.splitlines(), 1):
        if "SLICE-" not in line:
            continue
        m_slice = re.search(r"\b(SLICE-\d+)\b", line)
        sid = m_slice.group(1) if m_slice else f"line {lineno}"
        for m_c in re.finditer(r"\b(\d+)\s*(?:c\b|commits?\b)", line, flags=re.IGNORECASE):
            commits = int(m_c.group(1))
            if commits > MAX_SLICE_COMMITS:
                issues.append(f"{sid} (line {lineno}) estimates {commits} commits (max {MAX_SLICE_COMMITS} for lean-runbook)")
        for m_loc in re.finditer(r"~?\b(\d+)\s*LOC\b", line, flags=re.IGNORECASE):
            loc = int(m_loc.group(1))
            if loc > MAX_SLICE_LOC:
                issues.append(f"{sid} (line {lineno}) estimates {loc} LOC (max {MAX_SLICE_LOC} for lean-runbook)")
    return issues


def find_duplicate_paragraphs(docs: list[DocStats]) -> list[str]:
    dups: list[str] = []
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            d1, d2 = docs[i], docs[j]
            for l1, snip1, t1 in d1.paragraphs:
                for l2, _, t2 in d2.paragraphs:
                    union = len(t1 | t2)
                    if union == 0:
                        continue
                    sim = len(t1 & t2) / union
                    if sim >= 0.75:
                        dups.append(
                            f"Duplicate prose ({int(sim * 100)}% overlap) between "
                            f"{d1.name}:L{l1} and {d2.name}:L{l2} (\"{snip1}\") — cite by ID instead."
                        )
    return dups


def run_check(suite_dir: Path, is_complex: bool, strict: bool) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    missing = [f for f in SUITE_FILES if not (suite_dir / f).is_file()]
    if missing:
        errors.append(f"Missing required suite file(s) in {suite_dir}: {', '.join(missing)}")
        return {
            "ok": False,
            "suite_dir": str(suite_dir),
            "tier": "complex" if is_complex else "standard",
            "docs": [],
            "total_words": 0,
            "total_lines": 0,
            "total_read_minutes": 0.0,
            "traceability": {},
            "errors": errors,
            "warnings": warnings,
        }

    stats = [analyze_markdown(suite_dir / f) for f in SUITE_FILES]
    texts = {f: (suite_dir / f).read_text(encoding="utf-8") for f in SUITE_FILES}
    tier_name = "complex" if is_complex else "standard"
    budget = BUDGETS[tier_name]

    total_words = sum(d.words for d in stats)
    total_lines = sum(d.lines for d in stats)
    total_read_min = round(sum(d.read_minutes for d in stats), 1)

    # 1. Per-doc & total read-time / word budgets
    for d in stats:
        doc_cap = budget["per_doc_words"][d.name]
        if d.words > int(doc_cap * 1.15):
            errors.append(f"{d.name} is {d.words} words (hard cap ~{int(doc_cap * 1.15)}w for {tier_name} tier; target <= {doc_cap}w).")
        elif d.words > doc_cap:
            warnings.append(f"{d.name} is {d.words} words (target <= {doc_cap}w for {tier_name} tier).")

    if total_words > budget["total_words_hard"]:
        hint = " Pass --complex only for sweeping platform rearchitectures." if not is_complex else " Suite exceeds the 60-minute absolute ceiling — compress or split scope."
        errors.append(f"Total suite word count is {total_words} words (hard max {budget['total_words_hard']}w for {tier_name} tier).{hint}")
    elif total_words > budget["total_words_target"]:
        warnings.append(f"Total suite word count is {total_words} words (target <= {budget['total_words_target']}w for {tier_name} tier).")

    if total_read_min > budget["read_min_hard"]:
        errors.append(f"Estimated total read time is {total_read_min} min (hard max {budget['read_min_hard']} min for {tier_name} tier).")
    elif total_read_min > budget["read_min_target"]:
        warnings.append(f"Estimated total read time is {total_read_min} min (target <= {budget['read_min_target']} min for {tier_name} tier).")

    # 2. Anti-bloat: large non-diagram code blocks & cross-doc prose duplication
    for d in stats:
        for start_line, lang, nlines in d.large_code_blocks:
            msg = f"{d.name}:L{start_line} has a {nlines}-line `{lang}` code block (keep contracts <= {MAX_CODE_BLOCK_WARN_LINES} lines; no pasted implementations)."
            if nlines > MAX_CODE_BLOCK_HARD_LINES or strict:
                errors.append(msg)
            else:
                warnings.append(msg)

    for dup in find_duplicate_paragraphs(stats):
        if strict:
            errors.append(dup)
        else:
            warnings.append(dup)

    # 3. Canonical ID Traceability
    br_defined = extract_ids(texts["design.md"], "BR")
    risk_defined = extract_ids(texts["design.md"], "RISK")
    adr_defined = extract_ids(texts["design.md"], "ADR")
    inv_defined = extract_ids(texts["tech-plan.md"], "INV")
    slice_defined = extract_ids(texts["spec.md"], "SLICE")

    br_in_spec = extract_ids(texts["spec.md"], "BR")
    risk_in_tech = extract_ids(texts["tech-plan.md"], "RISK")
    risk_in_spec = extract_ids(texts["spec.md"], "RISK")
    inv_in_spec = extract_ids(texts["spec.md"], "INV")

    if not br_defined:
        errors.append("design.md defines zero Business Requirements (`BR-1`, `BR-2`, ...).")
    if not inv_defined:
        warnings.append("tech-plan.md defines zero System Invariants (`INV-1`, ...).")

    missing_br = sorted(br_defined - br_in_spec)
    if missing_br:
        errors.append(f"Unmapped Business Requirements in spec.md: {', '.join(missing_br)}")

    dangling_br = sorted(br_in_spec - br_defined)
    if dangling_br:
        warnings.append(f"spec.md cites undefined BR IDs (not in design.md): {', '.join(dangling_br)}")

    if risk_defined:
        missing_risk_tech = sorted(risk_defined - risk_in_tech)
        if missing_risk_tech:
            errors.append(f"Risks from design.md not verified in tech-plan.md: {', '.join(missing_risk_tech)}")
        missing_risk_spec = sorted(risk_defined - risk_in_spec)
        if missing_risk_spec:
            errors.append(f"Risks from design.md not mapped to tests/slices in spec.md: {', '.join(missing_risk_spec)}")

    missing_inv = sorted(inv_defined - inv_in_spec)
    if missing_inv:
        errors.append(f"System Invariants from tech-plan.md not mapped in spec.md: {', '.join(missing_inv)}")

    dangling_inv = sorted(inv_in_spec - inv_defined)
    if dangling_inv:
        warnings.append(f"spec.md cites undefined INV IDs (not in tech-plan.md): {', '.join(dangling_inv)}")

    # 4. lean-runbook Slice sizing hygiene
    is_single_slice = bool(re.search(r"Recommended\s+`?lean-runbook`?\s+Mode:\*\*\s*`?Single Slice`?", texts["spec.md"], re.IGNORECASE))
    if not slice_defined and not is_single_slice:
        errors.append("spec.md defines zero `SLICE-*` entries (and is not marked Single Slice).")

    for issue in find_oversized_slices(texts["spec.md"]):
        errors.append(f"Oversized slice in spec.md: {issue}")

    # 5. Strict signoff readiness checks
    if strict:
        for d in stats:
            if d.placeholders:
                errors.append(f"{d.name} still contains template placeholders: {', '.join(d.placeholders[:4])}")
            if "draft" in d.status.lower() and "|" in d.status:
                warnings.append(f"{d.name} Status header is still unset ('{d.status}').")

    ok = len(errors) == 0 and (not strict or len(warnings) == 0)
    return {
        "ok": ok,
        "suite_dir": str(suite_dir),
        "tier": tier_name,
        "docs": [
            {
                "name": d.name,
                "words": d.words,
                "lines": d.lines,
                "diagrams": d.diagrams,
                "tables": d.tables,
                "read_minutes": d.read_minutes,
            }
            for d in stats
        ],
        "total_words": total_words,
        "total_lines": total_lines,
        "total_read_minutes": total_read_min,
        "traceability": {
            "br_defined": len(br_defined),
            "br_mapped": len(br_defined & br_in_spec),
            "risk_defined": len(risk_defined),
            "risk_verified_tech": len(risk_defined & risk_in_tech),
            "risk_mapped_spec": len(risk_defined & risk_in_spec),
            "adr_defined": len(adr_defined),
            "inv_defined": len(inv_defined),
            "inv_mapped": len(inv_defined & inv_in_spec),
            "slices": len(slice_defined),
        },
        "errors": errors,
        "warnings": warnings,
    }


def format_check_report(res: dict[str, Any]) -> str:
    status = "PASS" if res["ok"] else "FAIL"
    tier_label = "complex (<=60m cap)" if res["tier"] == "complex" else "standard (15-20m target)"
    lines = [
        f"lean-design check: {status} | tier={tier_label} | {res['suite_dir']}",
        f"Total: {res['total_words']} words | {res['total_lines']} lines | ~{res['total_read_minutes']} min read",
    ]
    for d in res["docs"]:
        lines.append(
            f"  - {d['name']:13s} {d['words']:5d} words | {d['lines']:4d} lines | "
            f"{d['diagrams']} diag, {d['tables']} tbl | ~{d['read_minutes']} min"
        )
    tr = res.get("traceability") or {}
    if tr:
        lines.append(
            f"Traceability: BR {tr['br_mapped']}/{tr['br_defined']} | "
            f"RISK tech {tr['risk_verified_tech']}/{tr['risk_defined']} spec {tr['risk_mapped_spec']}/{tr['risk_defined']} | "
            f"INV {tr['inv_mapped']}/{tr['inv_defined']} | ADR {tr['adr_defined']} | SLICE {tr['slices']}"
        )
    for w in res["warnings"]:
        lines.append(f"  WARN:  {w}")
    for e in res["errors"]:
        lines.append(f"  ERROR: {e}")
    return "\n".join(lines)


# ---------------- CLI Subcommands ----------------

def _render_template(template_name: str, slug: str, mode: str, is_complex: bool) -> str:
    text = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    text = text.replace("<slug>", slug).replace("<YYYY-MM-DD>", today_iso())
    text = text.replace("`greenfield` | `redesign`", f"`{mode}`")
    if template_name == "brief.md":
        tier_str = "`complex` (≤60 min, ≤10,500 words)" if is_complex else "`standard` (15–20 min, ≤4,000 words)"
        text = text.replace(
            "`standard` (15–20 min, ≤4,000 words) | `complex` (≤60 min, ≤10,500 words)",
            tier_str,
        )
    if mode == "greenfield" and template_name == "design.md":
        # Remove the optional Legacy Risk Audit section so greenfield drafts stay minimal
        text = re.sub(
            r"\n## 4\. Legacy / Input Risk Elimination Matrix.*?(?=\n## 5\.)",
            "\n",
            text,
            flags=re.DOTALL,
        )
        text = text.replace("## 5. Target Architecture", "## 4. Target Architecture")
        text = text.replace("## 6. Key Architectural Decisions (ADRs)", "## 5. Key Architectural Decisions (ADRs)")
        text = text.replace("## 7. Rejected Alternatives (1 Line Each)", "## 6. Rejected Alternatives (1 Line Each)")
    if mode == "greenfield" and template_name == "tech-plan.md":
        text = re.sub(
            r"\n## 4\. Risk Elimination Verification.*?(?=\n## 5\.)",
            "\n",
            text,
            flags=re.DOTALL,
        )
        text = text.replace("## 5. Migration, Cutover & Rollback Strategy", "## 4. Deployment & Rollback Strategy")
        text = text.replace("## 6. Cross-Cutting Budgets (Non-Trivial Items Only)", "## 5. Cross-Cutting Budgets (Non-Trivial Items Only)")
    return text


def cmd_init(args: list[str], cwd: str | None) -> int:
    mode = "greenfield"
    is_complex = False
    force = False
    out_override = ""
    pos: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1].lower()
            i += 2
        elif a.startswith("--mode="):
            mode = a.split("=", 1)[1].lower()
            i += 1
        elif a == "--complex":
            is_complex = True
            i += 1
        elif a == "--force":
            force = True
            i += 1
        elif a == "--out" and i + 1 < len(args):
            out_override = args[i + 1]
            i += 2
        elif a.startswith("--out="):
            out_override = a.split("=", 1)[1]
            i += 1
        elif a.startswith("--"):
            i += 1
        else:
            pos.append(a)
            i += 1

    if not pos:
        print("Usage: design_check.py init <slug> [--mode greenfield|redesign] [--complex] [--out <dir>] [--force]", file=sys.stderr)
        return 2
    if mode not in ("greenfield", "redesign"):
        print(f"Invalid --mode '{mode}'. Choose 'greenfield' or 'redesign'.", file=sys.stderr)
        return 2

    slug = sanitize_slug(pos[0])
    repo = repo_root_for(cwd)
    out_dir = Path(out_override) if out_override else (repo / "docs" / "designs" / slug)
    if not out_dir.is_absolute():
        out_dir = repo / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    for fname in SUITE_FILES:
        dst = out_dir / fname
        if force or not dst.exists():
            dst.write_text(_render_template(fname, slug, mode, is_complex), encoding="utf-8")
            created.append(fname)

    brief_dir = repo / ".loop" / "designs" / slug
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_path = brief_dir / "brief.md"
    if force or not brief_path.exists():
        brief_path.write_text(_render_template("brief.md", slug, mode, is_complex), encoding="utf-8")

    try:
        rel_out = str(out_dir.resolve().relative_to(repo.resolve())).replace("\\", "/")
    except Exception:
        rel_out = str(out_dir)

    state = {
        "slug": slug,
        "repo": str(repo),
        "mode": mode,
        "complex": is_complex,
        "out_dir": rel_out,
        "done": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    save_state(repo, slug, state)
    print(format_status(state))
    if created:
        print(f"Scaffolded: {', '.join(created)} in {rel_out}/ (plus .loop/designs/{slug}/brief.md)")
    return 0


def cmd_status(args: list[str], cwd: str | None) -> int:
    repo = repo_root_for(cwd)
    if args:
        slug = sanitize_slug(args[0])
        st = load_state(repo, slug)
        if not st:
            print(f"lean-design: no design suite '{slug}' tracked for this repo.")
            return 1
        print(format_status(st))
        return 0

    states = list_states(repo)
    if not states:
        print("lean-design: no tracked design suites in this repo.")
        return 0
    for idx, st in enumerate(states):
        if idx:
            print()
        print(format_status(st))
    return 0


def cmd_done(args: list[str], cwd: str | None) -> int:
    if len(args) < 2:
        print(f"Usage: design_check.py done <{'|'.join(STAGES)}> <slug>", file=sys.stderr)
        return 2
    stage = args[0].lower()
    if stage not in STAGES:
        print(f"Unknown stage '{stage}'. Choose from: {', '.join(STAGES)}", file=sys.stderr)
        return 2
    slug = sanitize_slug(args[1])
    repo = repo_root_for(cwd)
    st = load_state(repo, slug)
    if not st:
        st = {
            "slug": slug,
            "repo": str(repo),
            "mode": "greenfield",
            "complex": False,
            "out_dir": f"docs/designs/{slug}",
            "done": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
    done = st.setdefault("done", [])
    if stage not in done:
        done.append(stage)
    st["updated_at"] = now_iso()
    save_state(repo, slug, st)
    print(format_status(st))
    return 0


def cmd_check(args: list[str], cwd: str | None) -> int:
    is_complex: bool | None = None
    strict = False
    as_json = False
    pos: list[str] = []
    for a in args:
        if a == "--complex":
            is_complex = True
        elif a == "--standard":
            is_complex = False
        elif a == "--strict":
            strict = True
        elif a == "--json":
            as_json = True
        elif not a.startswith("--"):
            pos.append(a)

    if not pos:
        print("Usage: design_check.py check <suite_dir_or_slug> [--complex] [--strict] [--json]", file=sys.stderr)
        return 2

    repo = repo_root_for(cwd)
    raw_target = pos[0]
    candidate = Path(raw_target)
    if not candidate.is_absolute():
        candidate = (Path(cwd or os.getcwd()) / candidate).resolve()
    if not candidate.is_dir():
        alt = repo / "docs" / "designs" / sanitize_slug(raw_target)
        if alt.is_dir():
            candidate = alt

    if is_complex is None:
        st = load_state(repo, candidate.name)
        is_complex = bool(st.get("complex")) if st else False

    res = run_check(candidate, is_complex=is_complex, strict=strict)
    if as_json:
        print(json.dumps(res, indent=2))
    else:
        print(format_check_report(res))
    return 0 if res["ok"] else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
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

    if not cleaned:
        print(__doc__)
        return 0

    cmd, rest = cleaned[0], cleaned[1:]
    if cmd == "init":
        return cmd_init(rest, cwd)
    if cmd == "status":
        return cmd_status(rest, cwd)
    if cmd == "done":
        return cmd_done(rest, cwd)
    if cmd == "check":
        return cmd_check(rest, cwd)
    print(f"Unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
