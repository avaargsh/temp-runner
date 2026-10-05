from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIFF = ROOT / "authority_diff_cli.py"
ADMISSION = ROOT / "admission_input.py"


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        baseline = root / "baseline"
        candidate = root / "candidate"
        baseline.mkdir()
        candidate.mkdir()

        (baseline / "runtime.json").write_text(
            json.dumps({
                "runs": [{
                    "run_id": "run-1",
                    "sandbox_binding": {
                        "sandbox_ref": "k8s://default/deployment/worker"
                    },
                }]
            }),
            encoding="utf-8",
        )
        (candidate / "runtime.json").write_text(
            (baseline / "runtime.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (baseline / "mcp.json").write_text(
            json.dumps({
                "mcpServers": {
                    "kubernetes": {
                        "command": "kubectl-mcp",
                        "args": ["--read-only"],
                    }
                }
            }),
            encoding="utf-8",
        )
        (candidate / "mcp.json").write_text(
            json.dumps({
                "mcpServers": {
                    "kubernetes": {
                        "command": "kubectl-mcp",
                        "args": [],
                    }
                }
            }),
            encoding="utf-8",
        )

        diff_path = root / "diff.json"
        diff_sha = root / "diff.sha256"
        subprocess.run(
            [
                sys.executable,
                str(DIFF),
                str(baseline),
                str(candidate),
                "--output",
                str(diff_path),
                "--sha-output",
                str(diff_sha),
            ],
            check=True,
        )
        diff = json.loads(diff_path.read_text(encoding="utf-8"))

        output = root / "admission-input.json"
        output_sha = root / "admission-input.sha256"
        subprocess.run(
            [
                sys.executable,
                str(ADMISSION),
                str(diff_path),
                "--sha-file",
                str(diff_sha),
                "--expected-baseline-digest",
                diff["baseline"]["tree_digest"],
                "--expected-candidate-digest",
                diff["candidate"]["tree_digest"],
                "--output",
                str(output),
                "--sha-output",
                str(output_sha),
            ],
            check=True,
        )

        admitted = json.loads(output.read_text(encoding="utf-8"))
        assert admitted["kind"] == "AuthorityDiffAdmissionInput"
        assert admitted["mode"] == "read-only"
        assert admitted["authority_diff_artifact_digest"] == diff["content_digest"]
        assert admitted["detected"] is True
        assert admitted["signals"]
        encoded = json.dumps(admitted, sort_keys=True).upper()
        assert '"ADMIT"' not in encoded
        assert '"DENY"' not in encoded
        assert '"PROMOTE"' not in encoded

        bad = subprocess.run(
            [
                sys.executable,
                str(ADMISSION),
                str(diff_path),
                "--sha-file",
                str(diff_sha),
                "--expected-baseline-digest",
                "sha256:" + "0" * 64,
                "--expected-candidate-digest",
                diff["candidate"]["tree_digest"],
                "--output",
                str(root / "bad.json"),
            ],
            text=True,
            capture_output=True,
        )
        assert bad.returncode != 0
        assert "baseline fact digest mismatch" in (bad.stdout + bad.stderr)

    print("read-only authority admission input smoke: PASS")


if __name__ == "__main__":
    main()
