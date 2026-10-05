from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SEMANTICS = (
    "OUTCOME_EXPANSION",
    "AUTHORITY_CONCENTRATION",
    "AUTHORITY_REPLICATION",
)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"authority admission artifact violation: {message}")


def load_diff(path: Path, expected_digest: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        fail("unsupported authority diff schema_version")
    if payload.get("kind") != "EffectiveAuthorityDiff":
        fail("artifact kind must be EffectiveAuthorityDiff")
    if payload.get("mode") != "read-only":
        fail("authority diff must remain read-only")
    if tuple(payload.get("semantics") or ()) != SEMANTICS:
        fail("authority diff semantics changed")

    recorded = payload.get("content_digest")
    if recorded != expected_digest:
        fail("trusted digest does not match artifact content_digest")
    unsigned = dict(payload)
    unsigned.pop("content_digest", None)
    if digest(unsigned) != recorded:
        fail("artifact content digest mismatch")

    diff = payload.get("diff")
    if not isinstance(diff, dict):
        fail("diff mapping is required")
    signals = diff.get("signals")
    if not isinstance(signals, list):
        fail("diff.signals must be a list")
    allowed = set(SEMANTICS)
    for signal in signals:
        if not isinstance(signal, dict) or signal.get("type") not in allowed:
            fail(f"unsupported diff signal: {signal!r}")
    if bool(signals) != bool(diff.get("detected")):
        fail("diff.detected must equal whether signals are present")
    return payload


def build_admission_input(
    *,
    artifact: dict[str, Any],
    artifact_ref: str,
    expected_baseline_digest: str,
    expected_candidate_digest: str,
) -> dict[str, Any]:
    baseline = artifact.get("baseline") or {}
    candidate = artifact.get("candidate") or {}
    if baseline.get("tree_digest") != expected_baseline_digest:
        fail("baseline fact digest mismatch")
    if candidate.get("tree_digest") != expected_candidate_digest:
        fail("candidate fact digest mismatch")

    diff = artifact["diff"]
    out = {
        "schema_version": 1,
        "kind": "AuthorityDiffAdmissionInput",
        "mode": "read-only",
        "authority_diff_artifact_ref": artifact_ref,
        "authority_diff_artifact_digest": artifact["content_digest"],
        "baseline_fact_digest": expected_baseline_digest,
        "candidate_fact_digest": expected_candidate_digest,
        "detected": bool(diff["detected"]),
        "signals": diff["signals"],
    }
    out["content_digest"] = digest(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a frozen EffectiveAuthorityDiff and emit a read-only "
            "artifact-bound input for an existing admission layer."
        )
    )
    parser.add_argument("artifact")
    parser.add_argument("--sha-file", required=True)
    parser.add_argument("--expected-baseline-digest", required=True)
    parser.add_argument("--expected-candidate-digest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sha-output")
    args = parser.parse_args()

    artifact_path = Path(args.artifact)
    trusted_digest = Path(args.sha_file).read_text(encoding="utf-8").strip()
    if not trusted_digest:
        fail("trusted digest file is empty")

    artifact = load_diff(artifact_path, trusted_digest)
    output = build_admission_input(
        artifact=artifact,
        artifact_ref=artifact_path.as_posix(),
        expected_baseline_digest=args.expected_baseline_digest,
        expected_candidate_digest=args.expected_candidate_digest,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sha_out = Path(args.sha_output) if args.sha_output else out.with_suffix(out.suffix + ".sha256")
    sha_out.write_text(output["content_digest"] + "\n", encoding="utf-8")

    print(json.dumps({
        "artifact_digest": output["authority_diff_artifact_digest"],
        "baseline_fact_digest": output["baseline_fact_digest"],
        "candidate_fact_digest": output["candidate_fact_digest"],
        "detected": output["detected"],
        "signals": len(output["signals"]),
        "content_digest": output["content_digest"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
