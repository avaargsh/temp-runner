"""Synthetic negative controls for immutable checkout attestation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_checked_out_sources import verify_checkout_lock  # noqa: E402


NAMES = ("agentic-aiops", "agent-decision-lab", "cloud-agent-runtime", "agent-control-plane")


class CheckoutAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.expected: dict[str, str] = {}
        for name in NAMES:
            repo = self.workspace / name
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repo), "-c", "user.email=ci@example.invalid",
                 "-c", "user.name=CI", "commit", "--allow-empty", "-qm", "seed"],
                check=True, capture_output=True,
            )
            self.expected[name] = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
            ).strip()
        self.lock_path = self.root / "stack-lock.json"
        self.output = self.root / "artifacts" / "source-checkouts.json"
        self.write_lock()

    def write_lock(self) -> None:
        self.lock_path.write_text(json.dumps({
            "schema_version": 1,
            "repositories": {
                name: {"repository": f"avaargsh/{name}", "sha": self.expected[name]}
                for name in NAMES
            },
        }), encoding="utf-8")

    def observe(self) -> tuple[bool, dict]:
        status = verify_checkout_lock(self.lock_path, self.workspace, self.output)
        return status, json.loads(self.output.read_text(encoding="utf-8"))

    def test_all_exact_commits_match(self) -> None:
        status, evidence = self.observe()
        self.assertTrue(status)
        self.assertEqual(len(evidence["sources"]), 4)
        self.assertTrue(all(row["matches"] and row["reason"] == "MATCH"
                            for row in evidence["sources"]))

    def test_drifted_lock_is_blocked_with_evidence(self) -> None:
        self.expected["agent-control-plane"] = "0" * 40
        self.write_lock()
        status, evidence = self.observe()
        self.assertFalse(status)
        row = next(x for x in evidence["sources"]
                   if x["repository"] == "avaargsh/agent-control-plane")
        self.assertEqual(row["reason"], "SHA_MISMATCH")
        self.assertNotEqual(row["observed_sha"], row["locked_sha"])

    def test_missing_checkout_is_blocked_and_recorded(self) -> None:
        (self.workspace / "cloud-agent-runtime" / ".git").rename(
            self.workspace / "cloud-agent-runtime" / ".git.disabled"
        )
        status, evidence = self.observe()
        self.assertFalse(status)
        row = next(x for x in evidence["sources"]
                   if x["repository"] == "avaargsh/cloud-agent-runtime")
        self.assertEqual(row["reason"], "MISSING_CHECKOUT")
        self.assertIsNone(row["observed_sha"])


if __name__ == "__main__":
    unittest.main()
