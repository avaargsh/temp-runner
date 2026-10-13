"""Fail-closed attestation for immutable Golden E2E source checkouts.

Records *observations*, not signing/provenance claims. Always writes a bounded
artifact before returning failure for a missing checkout or mismatched SHA.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from emit_stack_lock import _REQUIRED, load_lock


def verify_checkout_lock(lock_path: Path, workspace: Path, output: Path) -> bool:
    lock = load_lock(lock_path)
    rows: list[dict[str, object]] = []
    for name in _REQUIRED:
        entry = lock["repositories"][name]
        checkout = workspace / name
        observed: str | None = None
        reason = "MISSING_CHECKOUT"
        # Avoid walking upward to the runner repository if the child checkout
        # is missing or not itself a Git worktree.
        if (checkout / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "-C", str(checkout), "rev-parse", "--verify", "HEAD^{commit}"],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                if result.returncode == 0:
                    candidate = result.stdout.strip()
                    if len(candidate) == 40 and all(c in "0123456789abcdef" for c in candidate):
                        observed = candidate
                        reason = "MATCH" if observed == entry["sha"] else "SHA_MISMATCH"
                    else:
                        reason = "INVALID_OBSERVED_SHA"
                else:
                    reason = "GIT_OBSERVATION_FAILED"
            except (OSError, subprocess.TimeoutExpired):
                reason = "GIT_OBSERVATION_FAILED"
        rows.append({
            "repository": entry["repository"],
            "locked_sha": entry["sha"],
            "observed_sha": observed,
            "matches": reason == "MATCH",
            "reason": reason,
        })

    report = {
        "schema_version": 1,
        "kind": "LockedSourceCheckoutObservation",
        "sources": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return all(row["matches"] for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("stack-lock.json"))
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/source-checkouts.json"))
    args = parser.parse_args()
    if not verify_checkout_lock(args.lock, args.workspace, args.output):
        raise SystemExit("locked source checkout verification FAILED; see source-checkouts.json")
    print("all four source checkouts match immutable locked SHAs")


if __name__ == "__main__":
    main()
