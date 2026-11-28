#!/usr/bin/env python3
"""Unit tests for lean-design design_check.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "design_check.py"


def run_cli(*args: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def write_clean_suite(suite: Path, include_risks: bool = True, extra_words: int = 0) -> None:
    suite.mkdir(parents=True, exist_ok=True)
    risk_section = """
## 4. Legacy / Input Risk Elimination Matrix
| ID | Inherited Risk | Root Cause | Structural Elimination |
|---|---|---|---|
| `RISK-1` | Split-brain writes | Dual mutable stores | Single append-only event log |
""" if include_risks else ""

    filler = ("word " * extra_words).strip()
    (suite / "design.md").write_text(f"""# Design Doc: Sample Platform

- **Slug:** `sample`
- **Status:** Approved
- **Mode:** `{'redesign' if include_risks else 'greenfield'}`

## 1. Executive Summary
Reform the ingestion layer to eliminate split-brain writes and cut p99 latency in half. {filler}

## 3. Business Requirements Registry
| ID | Priority | Requirement | Success Metric |
|---|---|---|---|
| `BR-1` | P0 | Preserve all accepted events without loss | Zero data loss in fault tests |
| `BR-2` | P0 | Deterministic replay of historical streams | Replay hashes match |
{risk_section}
## 5. Target Architecture
```mermaid
flowchart LR
  A["Ingest"] --> B["Event Log"]
```

## 6. Key Architectural Decisions (ADRs)
| ID | Decision | Rationale | Reversibility |
|---|---|---|---|
| `ADR-1` | Single append-only log | Eliminates dual-write races | Moderate |
""", encoding="utf-8")

    tech_risk = """
## 4. Risk Elimination Verification
| Risk ID | Structural Mechanism | Invariant(s) | Proof |
|---|---|---|---|
| `RISK-1` | Single writer log | `INV-1` | Fault injection test |
""" if include_risks else ""

    (suite / "tech-plan.md").write_text(f"""# Technical Plan: Sample Platform

- **Slug:** `sample`
- **Status:** Approved

## 1. Subsystem Boundaries & Ownership
| Subsystem | Path | Public Entrypoint | Implements |
|---|---|---|---|
| LogCore | `src/log/` | `append(event)` | `ADR-1`, `BR-1` |

## 3. System Invariants
| ID | Invariant | Enforced By | Failure Behavior |
|---|---|---|---|
| `INV-1` | Every acknowledged event is fsynced before reply | WAL writer | Fail closed with retryable error |
| `INV-2` | Replay consumes offsets strictly monotonically | Cursor check | Reject out-of-order frame |
{tech_risk}""", encoding="utf-8")

    spec_risk = "| `RISK-1` | `SLICE-1` | `EDGE-1` | Fault test |\n" if include_risks else ""
    (suite / "spec.md").write_text(f"""# Implementation Spec (`lean-runbook` Handoff): Sample Platform

- **Slug:** `sample`
- **Status:** Approved
- **Recommended `lean-runbook` Mode:** `Mini-Series (2-4 slices)`

## 2. Requirement & Invariant Traceability Matrix
| Source ID | Mapped Slice(s) | Acceptance Check ID(s) | Verification |
|---|---|---|---|
| `BR-1` | `SLICE-1` | `CUJ-1` | Unit |
| `BR-2` | `SLICE-2` | `CUJ-2` | Integration |
{spec_risk}| `INV-1` | `SLICE-1` | `EDGE-1` | Fault test |
| `INV-2` | `SLICE-2` | `CUJ-2` | Unit |

## 4. Vertical Slice Roadmap
| ID | Slice Slug | Wave | Depends On | Est. Size | Touched Files | Deliverable | Covers |
|---|---|---|---|---|---|---|---|
| `SLICE-1` | `wal-core` | 1 | none | 2c / ~300 LOC | `src/log/` | Append-only WAL | `BR-1`, `INV-1` |
| `SLICE-2` | `stream-replay` | 2 | `SLICE-1` | 2c / ~350 LOC | `src/replay/` | Deterministic replay | `BR-2`, `INV-2` |

## 5. Acceptance Criteria & Edge Cases
| ID | Slice | Given | When | Then |
|---|---|---|---|---|
| `CUJ-1` | `SLICE-1` | Valid event | Appended | Persisted and acked |
| `EDGE-1` | `SLICE-1` | Disk flush fails | Appended | Returns error without ack |
| `CUJ-2` | `SLICE-2` | Log with 100 events | Replayed twice | Identical digest |
""", encoding="utf-8")


class LeanDesignCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.data = self.root / "data"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env["LEAN_DESIGN_DATA"] = str(self.data)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_init_status_done_lifecycle(self) -> None:
        r = run_cli("init", "platform-reform", "--mode", "redesign", env=self.env, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.repo / "docs/designs/platform-reform/design.md").is_file())
        self.assertTrue((self.repo / "docs/designs/platform-reform/tech-plan.md").is_file())
        self.assertTrue((self.repo / "docs/designs/platform-reform/spec.md").is_file())
        self.assertTrue((self.repo / ".loop/designs/platform-reform/brief.md").is_file())

        r2 = run_cli("done", "brief", "platform-reform", env=self.env, cwd=self.repo)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("Stage 2/5 (draft)", r2.stdout)

        r3 = run_cli("status", "platform-reform", env=self.env, cwd=self.repo)
        self.assertEqual(r3.returncode, 0, r3.stderr)
        self.assertIn("mode=redesign", r3.stdout)

    def test_greenfield_init_omits_legacy_risk_sections(self) -> None:
        r = run_cli("init", "new-svc", "--mode", "greenfield", env=self.env, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        design_txt = (self.repo / "docs/designs/new-svc/design.md").read_text(encoding="utf-8")
        tech_txt = (self.repo / "docs/designs/new-svc/tech-plan.md").read_text(encoding="utf-8")
        self.assertNotIn("Legacy / Input Risk Elimination Matrix", design_txt)
        self.assertNotIn("Risk Elimination Verification", tech_txt)

    def test_clean_suite_passes_strict(self) -> None:
        suite = self.repo / "docs/designs/sample"
        write_clean_suite(suite, include_risks=True)
        r = run_cli("check", str(suite), "--strict", "--json", env=self.env, cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["traceability"]["br_defined"], 2)
        self.assertEqual(payload["traceability"]["br_mapped"], 2)
        self.assertEqual(payload["traceability"]["risk_verified_tech"], 1)
        self.assertEqual(payload["traceability"]["risk_mapped_spec"], 1)
        self.assertEqual(payload["traceability"]["inv_mapped"], 2)
        self.assertLessEqual(payload["total_read_minutes"], 20.0)

    def test_missing_risk_and_br_fails_traceability(self) -> None:
        suite = self.repo / "docs/designs/broken"
        write_clean_suite(suite, include_risks=True)
        # Drop BR-2 and RISK-1 from spec.md
        spec_path = suite / "spec.md"
        txt = spec_path.read_text(encoding="utf-8").replace("BR-2", "BR-1").replace("RISK-1", "OTHER")
        spec_path.write_text(txt, encoding="utf-8")

        r = run_cli("check", str(suite), "--json", env=self.env, cwd=self.repo)
        self.assertEqual(r.returncode, 1)
        payload = json.loads(r.stdout)
        joined = "\n".join(payload["errors"])
        self.assertIn("BR-2", joined)
        self.assertIn("RISK-1", joined)

    def test_oversized_slice_fails(self) -> None:
        suite = self.repo / "docs/designs/bigslice"
        write_clean_suite(suite, include_risks=False)
        spec_path = suite / "spec.md"
        txt = spec_path.read_text(encoding="utf-8").replace("2c / ~300 LOC", "5c / ~1200 LOC")
        spec_path.write_text(txt, encoding="utf-8")

        r = run_cli("check", str(suite), "--json", env=self.env, cwd=self.repo)
        self.assertEqual(r.returncode, 1)
        joined = "\n".join(json.loads(r.stdout)["errors"])
        self.assertIn("5 commits", joined)
        self.assertIn("1200 LOC", joined)

    def test_read_time_budget_standard_vs_complex(self) -> None:
        suite = self.repo / "docs/designs/large"
        write_clean_suite(suite, include_risks=False, extra_words=2800)
        # Fails standard tier (design.md > 1,400w cap & total near ceiling)
        r_std = run_cli("check", str(suite), "--json", env=self.env, cwd=self.repo)
        self.assertEqual(r_std.returncode, 1)
        # Passes complex tier (<=60 min)
        r_cpx = run_cli("check", str(suite), "--complex", "--json", env=self.env, cwd=self.repo)
        self.assertEqual(r_cpx.returncode, 0, r_cpx.stdout)

    def test_duplicate_prose_and_large_code_block_detected(self) -> None:
        suite = self.repo / "docs/designs/bloat"
        write_clean_suite(suite, include_risks=False)
        dup_para = (
            "\n\nThis platform reform eliminates distributed transaction coordination across every "
            "upstream ingestion worker by moving authoritative state ownership into a single "
            "partitioned log with deterministic idempotent replay semantics across all regions.\n"
        )
        for fname in ("design.md", "tech-plan.md"):
            p = suite / fname
            p.write_text(p.read_text(encoding="utf-8") + dup_para, encoding="utf-8")
        # Add a 45-line pasted code block in tech-plan.md
        big_code = "\n```python\n" + "\n".join(f"x_{i} = {i}" for i in range(45)) + "\n```\n"
        (suite / "tech-plan.md").write_text(
            (suite / "tech-plan.md").read_text(encoding="utf-8") + big_code,
            encoding="utf-8",
        )

        r = run_cli("check", str(suite), "--strict", "--json", env=self.env, cwd=self.repo)
        self.assertEqual(r.returncode, 1)
        joined = "\n".join(json.loads(r.stdout)["errors"])
        self.assertIn("Duplicate prose", joined)
        self.assertIn("45-line", joined)


if __name__ == "__main__":
    unittest.main()
