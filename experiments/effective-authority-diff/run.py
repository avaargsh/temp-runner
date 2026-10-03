from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

from read_only_diff import build_profile, diff_profiles


ROOT = Path(__file__).resolve().parent


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def materialize(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_a(base: Path, candidate: Path) -> tuple[bool, list[str]]:
    proc = subprocess.run(
        ["bash", str(ROOT / "glue_a.sh"), str(base), str(candidate)],
        text=True,
        capture_output=True,
    )
    if proc.returncode not in {0, 10}:
        raise RuntimeError(f"A failed: rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode == 10, lines[1:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "cases.yaml"))
    parser.add_argument("--source-lock", default="authority-diff-lock.json")
    parser.add_argument("--out", default="artifacts/effective-authority-diff")
    args = parser.parse_args()

    suite = yaml.safe_load(Path(args.cases).read_text())
    if suite.get("schema_version") != 1:
        raise SystemExit("unsupported cases schema_version")
    cases = suite.get("cases") or []
    if len(cases) != 10:
        raise SystemExit(f"expected exactly 10 cases, got {len(cases)}")

    source_lock = json.loads(Path(args.source_lock).read_text())
    results = []
    for case in cases:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base = tmp_path / "baseline"
            cand = tmp_path / "candidate"
            base.mkdir()
            cand.mkdir()
            materialize(base, case["baseline"])
            materialize(cand, case["candidate"])
            a_detected, a_reasons = run_a(base, cand)

        before = build_profile(case["baseline"])
        after = build_profile(case["candidate"])
        b = diff_profiles(before, after)
        expected_dangerous = case["expected"] == "dangerous"
        if b["detected"] != expected_dangerous:
            raise SystemExit(
                f"B parser disagrees with seeded expectation for {case['id']}: "
                f"expected={case['expected']} got={b['detected']} signals={b['signals']}"
            )
        results.append({
            "id": case["id"],
            "expected": case["expected"],
            "note": case.get("note"),
            "baseline_digest": digest(case["baseline"]),
            "candidate_digest": digest(case["candidate"]),
            "A": {"detected": a_detected, "reasons": a_reasons},
            "B": b,
        })

    dangerous = [r for r in results if r["expected"] == "dangerous"]
    benign = [r for r in results if r["expected"] == "benign"]
    a_tp = sum(r["A"]["detected"] for r in dangerous)
    a_fp = sum(r["A"]["detected"] for r in benign)
    b_tp = sum(r["B"]["detected"] for r in dangerous)
    b_fp = sum(r["B"]["detected"] for r in benign)
    a_recall = a_tp / len(dangerous)
    threshold = 0.80

    decision = (
        "KILL_EFFECTIVE_AUTHORITY_DIFF"
        if a_recall >= threshold
        else "CONTINUE_MINIMAL_READ_ONLY_DIFF"
    )
    payload = {
        "schema_version": 1,
        "experiment": "effective-authority-diff-kill-test",
        "method": {
            "A": "<=200 LOC shell glue over textual config diff; no cross-domain graph",
            "B": "read-only parser over Kubernetes RBAC/workload, Rego approval predicate, MCP config, and Run/SandboxBinding identity",
            "dangerous_recall_kill_threshold": threshold,
            "decision_rule": "kill if A detects >=80% of seeded dangerous changes",
        },
        "source_lock": source_lock,
        "case_manifest_digest": digest(suite),
        "summary": {
            "cases": len(results),
            "dangerous_cases": len(dangerous),
            "benign_controls": len(benign),
            "A_true_positive": a_tp,
            "A_false_positive": a_fp,
            "A_dangerous_recall": a_recall,
            "B_true_positive": b_tp,
            "B_false_positive": b_fp,
            "B_dangerous_recall": b_tp / len(dangerous),
            "decision": decision,
        },
        "cases": results,
    }
    payload["content_digest"] = digest(payload)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "result.json"
    result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out / "result.sha256").write_text(payload["content_digest"] + "\n")
    (out / "summary.txt").write_text(
        f"A={a_tp}/{len(dangerous)} dangerous ({a_recall:.0%}), false_positive={a_fp}/{len(benign)}\n"
        f"B={b_tp}/{len(dangerous)} dangerous ({b_tp / len(dangerous):.0%}), false_positive={b_fp}/{len(benign)}\n"
        f"decision={decision}\n"
        f"content_digest={payload['content_digest']}\n"
    )
    print((out / "summary.txt").read_text(), end="")


if __name__ == "__main__":
    main()
