"""No external dependencies, network access, or real personal data required."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import run


class DelegationBoundaryProbeTests(unittest.TestCase):
    def test_fixture_matrix(self) -> None:
        report = run.build_report()
        self.assertGreaterEqual(report["summary"]["total"], 15)
        self.assertEqual(report["summary"]["passed"], report["summary"]["total"])
        self.assertEqual([x["case"] for x in report["cases"] if x["decision"] == "ALLOW"], ["scoped_availability"])
        self.assertEqual(report["cases"][0]["projection_fields"], ["free_slots"])
        self.assertNotIn("secret-do-not-release", json.dumps(report))

    def test_projection_releases_only_requested_fields(self) -> None:
        valid = run.fixtures()[0]
        result = run.evaluate(valid["request"], valid["grant"], valid["resource"], authenticated_principal=valid["principal"], now=valid["now"])
        self.assertEqual(result["decision"], "ALLOW")
        self.assertEqual(result["projection"], {"free_slots": ["10:00", "11:00"]})

    def test_artifact_bytes_and_digest_are_deterministic(self) -> None:
        one = run.build_report()
        two = run.build_report()
        self.assertEqual(run.canonical(one), run.canonical(two))
        run.verify(one, one["content_digest"])
        modified = copy.deepcopy(one)
        modified["cases"][0]["decision"] = "BLOCK"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            run.verify(modified, one["content_digest"])
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            run.verify(one, "sha256:" + "0" * 64)

    def test_cli_roundtrip_and_tamper_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            artifact_path = Path(d) / "probe.json"
            sha = Path(d) / "probe.json.sha256"
            command = [sys.executable, str(Path(run.__file__)), "--out", str(artifact_path)]
            subprocess.run(command, check=True, capture_output=True)
            subprocess.run([sys.executable, str(Path(run.__file__)), "--verify", str(artifact_path), "--sha-file", str(sha)], check=True, capture_output=True)
            original = artifact_path.read_bytes()
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(artifact_path.read_bytes(), original)
            artifact = json.loads(original)
            artifact["cases"][0]["projection_fields"].append("private_notes")
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            bad = subprocess.run([sys.executable, str(Path(run.__file__)), "--verify", str(artifact_path), "--sha-file", str(sha)], capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("digest mismatch", bad.stderr)


if __name__ == "__main__":
    unittest.main()
