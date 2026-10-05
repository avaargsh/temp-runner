from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from read_only_diff import build_profile, diff_profiles


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _read_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise SystemExit(f"fact directory does not exist: {root}")
    files: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        files[rel] = path.read_text(encoding="utf-8")
    return files


def _freeze_input(files: dict[str, str], profile: Any) -> dict[str, Any]:
    inventory = [
        {
            "path": path,
            "sha256": "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "size": len(content.encode("utf-8")),
        }
        for path, content in sorted(files.items())
    ]
    frozen_profile = {
        outcome: [list(coalition) for coalition in coalitions]
        for outcome, coalitions in profile.coalitions.items()
    }
    return {
        "tree_digest": _digest({path: content for path, content in sorted(files.items())}),
        "files": inventory,
        "reachable_outcomes": frozen_profile,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="authority-diff",
        description="Read-only deployment-time reachable-authority diff",
    )
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--output", required=True)
    parser.add_argument("--sha-output")
    parser.add_argument("--fail-on-drift", action="store_true")
    args = parser.parse_args()

    baseline_files = _read_tree(Path(args.baseline))
    candidate_files = _read_tree(Path(args.candidate))
    before = build_profile(baseline_files)
    after = build_profile(candidate_files)
    diff = diff_profiles(before, after)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "EffectiveAuthorityDiff",
        "mode": "read-only",
        "semantics": [
            "OUTCOME_EXPANSION",
            "AUTHORITY_CONCENTRATION",
            "AUTHORITY_REPLICATION",
        ],
        "baseline": _freeze_input(baseline_files, before),
        "candidate": _freeze_input(candidate_files, after),
        "diff": diff,
    }
    payload["content_digest"] = _digest(payload)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sha_out = Path(args.sha_output) if args.sha_output else out.with_suffix(out.suffix + ".sha256")
    sha_out.write_text(payload["content_digest"] + "\n", encoding="utf-8")
    print(json.dumps({
        "detected": diff["detected"],
        "signals": len(diff["signals"]),
        "content_digest": payload["content_digest"],
        "output": str(out),
    }, sort_keys=True))

    if args.fail_on_drift and diff["detected"]:
        raise SystemExit(10)


if __name__ == "__main__":
    main()
