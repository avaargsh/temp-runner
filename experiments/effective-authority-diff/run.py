from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "authority_diff_cli.py"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_suite(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


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


def run_b(base: Path, candidate: Path, artifact: Path) -> dict[str, Any]:
    sha_path = artifact.with_suffix(artifact.suffix + ".sha256")
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            str(base),
            str(candidate),
            "--output",
            str(artifact),
            "--sha-output",
            str(sha_path),
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"B CLI failed: rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    recorded = sha_path.read_text(encoding="utf-8").strip()
    if payload.get("content_digest") != recorded:
        raise RuntimeError(f"B artifact digest mismatch: {artifact}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "cases.yaml"))
    parser.add_argument("--source-lock", default="authority-diff-lock.json")
    parser.add_argument("--out", default="artifacts/effective-authority-diff")
    parser.add_argument("--round", choices=("1", "2"), default="1")
    parser.add_argument("--min-advantage", type=float, default=0.20)
    args = parser.parse_args()

    suite_path = Path(args.cases)
    suite = load_suite(suite_path)
    if suite.get("schema_version") != 1:
        raise SystemExit("unsupported cases schema_version")
    cases = suite.get("cases") or []
    if len(cases) != 10:
        raise SystemExit(f"expected exactly 10 cases, got {len(cases)}")

    source_lock = json.loads(Path(args.source_lock).read_text())
    out = Path(args.out)
    case_artifact_dir = out / "cases"
    case_artifact_dir.mkdir(parents=True, exist_ok=True)

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
            b_artifact = run_b(
                base,
                cand,
                case_artifact_dir / f"{case['id']}.authority-diff.json",
            )

        b = b_artifact["diff"]
        expected_dangerous = case["expected"] == "dangerous"
        if b["detected"] != expected_dangerous:
            raise SystemExit(
                f"B CLI disagrees with seeded expectation for {case['id']}: "
                f"expected={case['expected']} got={b['detected']} signals={b['signals']}"
            )
        results.append({
            "id": case["id"],
            "expected": case["expected"],
            "note": case.get("note"),
            "source": case.get("source", []),
            "baseline_digest": b_artifact["baseline"]["tree_digest"],
            "candidate_digest": b_artifact["candidate"]["tree_digest"],
            "A": {"detected": a_detected, "reasons": a_reasons},
            "B": {
                "detected": b["detected"],
                "signals": b["signals"],
                "artifact_digest": b_artifact["content_digest"],
            },
        })

    dangerous = [r for r in results if r["expected"] == "dangerous"]
    benign = [r for r in results if r["expected"] == "benign"]
    a_tp = sum(r["A"]["detected"] for r in dangerous)
    a_fp = sum(r["A"]["detected"] for r in benign)
    b_tp = sum(r["B"]["detected"] for r in dangerous)
    b_fp = sum(r["B"]["detected"] for r in benign)
    a_recall = a_tp / len(dangerous)
    b_recall = b_tp / len(dangerous)

    if args.round == "1":
        threshold = 0.80
        decision = (
            "KILL_EFFECTIVE_AUTHORITY_DIFF"
            if a_recall >= threshold
            else "CONTINUE_MINIMAL_READ_ONLY_DIFF"
        )
        decision_rule = "kill if A detects >=80% of seeded dangerous changes"
    else:
        clearly_better = (
            b_recall >= 0.80
            and (b_recall - a_recall) >= args.min_advantage
            and b_fp <= a_fp
        )
        decision = (
            "DRAFT_ADMISSION_CAPABILITY"
            if clearly_better
            else "END_EFFECTIVE_AUTHORITY_DIFF"
        )
        decision_rule = (
            f"draft only if B recall >=80%, beats A by >={args.min_advantage:.0%}, "
            "and has no more benign false positives"
        )

    payload = {
        "schema_version": 1,
        "experiment": f"effective-authority-diff-kill-test-round-{args.round}",
        "method": {
            "A": "<=200 LOC shell glue over ordinary config diff; no cross-domain graph",
            "B": "authority-diff CLI: read-only facts -> reachable outcomes/minimal principal coalitions -> frozen JSON+SHA",
            "decision_rule": decision_rule,
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
            "B_dangerous_recall": b_recall,
            "recall_advantage": b_recall - a_recall,
            "decision": decision,
        },
        "cases": results,
    }
    payload["content_digest"] = digest(payload)

    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "result.json"
    result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out / "result.sha256").write_text(payload["content_digest"] + "\n")
    (out / "summary.txt").write_text(
        f"A={a_tp}/{len(dangerous)} dangerous ({a_recall:.0%}), false_positive={a_fp}/{len(benign)}\n"
        f"B={b_tp}/{len(dangerous)} dangerous ({b_recall:.0%}), false_positive={b_fp}/{len(benign)}\n"
        f"recall_advantage={b_recall - a_recall:.0%}\n"
        f"decision={decision}\n"
        f"content_digest={payload['content_digest']}\n"
    )
    print((out / "summary.txt").read_text(), end="")


if __name__ == "__main__":
    main()
