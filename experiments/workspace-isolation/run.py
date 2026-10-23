#!/usr/bin/env python3
"""Disposable Git-worktree isolation smoke test; stdlib only."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({result.returncode}):\n{result.stdout}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/workspace-isolation")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "git-worktree-isolation-smoke",
        "checks": {},
        "timings_seconds": {},
        "cleanup": {"attempted": False, "passed": False},
    }

    with tempfile.TemporaryDirectory(prefix="workspace-isolation-") as temp:
        root = Path(temp)
        repo = root / "source"
        repo.mkdir()
        run_git(repo, "init", "-q", "-b", "main")
        run_git(repo, "config", "user.name", "workspace-isolation-test")
        run_git(repo, "config", "user.email", "workspace-isolation@example.invalid")
        (repo / "README.md").write_text("baseline\n", encoding="utf-8")
        (repo / "shared.txt").write_text("base\n", encoding="utf-8")
        run_git(repo, "add", "README.md", "shared.txt")
        run_git(repo, "commit", "-q", "-m", "baseline")
        base_sha = run_git(repo, "rev-parse", "HEAD").stdout.strip()
        evidence["base_commit_sha"] = base_sha
        evidence["git_version"] = run_git(repo, "--version").stdout.strip()

        work_a = root / "workspace-a"
        work_b = root / "workspace-b"
        t0 = time.monotonic()
        run_git(repo, "worktree", "add", "-q", "-b", "agent-a", str(work_a), base_sha)
        run_git(repo, "worktree", "add", "-q", "-b", "agent-b", str(work_b), base_sha)
        evidence["timings_seconds"]["create_two_worktrees"] = round(time.monotonic() - t0, 6)

        (work_a / "only-a.txt").write_text("agent A\n", encoding="utf-8")
        (work_b / "only-b.txt").write_text("agent B\n", encoding="utf-8")
        isolation_passed = not (work_b / "only-a.txt").exists() and not (work_a / "only-b.txt").exists()
        evidence["checks"]["uncommitted_changes_are_not_visible_across_worktrees"] = {
            "passed": isolation_passed,
            "workspace_a_only_file_visible_in_b": (work_b / "only-a.txt").exists(),
            "workspace_b_only_file_visible_in_a": (work_a / "only-b.txt").exists(),
        }
        if not isolation_passed:
            raise AssertionError("worktree write isolation check failed")

        (work_a / "shared.txt").write_text("change from agent A\n", encoding="utf-8")
        (work_b / "shared.txt").write_text("change from agent B\n", encoding="utf-8")
        for workspace, message in ((work_a, "agent A changes"), (work_b, "agent B changes")):
            run_git(workspace, "add", "only-a.txt" if workspace == work_a else "only-b.txt", "shared.txt")
            run_git(workspace, "commit", "-q", "-m", message)

        sha_a = run_git(work_a, "rev-parse", "HEAD").stdout.strip()
        sha_b = run_git(work_b, "rev-parse", "HEAD").stdout.strip()
        t0 = time.monotonic()
        merge = run_git(repo, "merge-tree", "--write-tree", sha_a, sha_b, check=False)
        evidence["timings_seconds"]["same_file_conflict_detection"] = round(time.monotonic() - t0, 6)
        conflict_detected = merge.returncode != 0 and "CONFLICT" in merge.stdout
        evidence["checks"]["same_file_conflict_is_detected"] = {
            "passed": conflict_detected,
            "merge_tree_exit_code": merge.returncode,
            "conflict_output": merge.stdout[-4000:],
            "agent_a_commit_sha": sha_a,
            "agent_b_commit_sha": sha_b,
        }
        if not conflict_detected:
            raise AssertionError("same-file conflict was not detected")

        # Verify cleanup is scoped to the disposable experiment repository.
        evidence["cleanup"]["attempted"] = True
        run_git(repo, "worktree", "remove", "--force", str(work_a))
        run_git(repo, "worktree", "remove", "--force", str(work_b))
        run_git(repo, "worktree", "prune")
        evidence["cleanup"]["passed"] = not work_a.exists() and not work_b.exists()
        evidence["cleanup"]["source_repo_preserved"] = (repo / ".git").exists() and (repo / "README.md").exists()
        if not evidence["cleanup"]["passed"] or not evidence["cleanup"]["source_repo_preserved"]:
            raise AssertionError("workspace cleanup boundary check failed")

    evidence["timings_seconds"]["total"] = round(time.monotonic() - started, 6)
    evidence["result"] = "passed" if all(
        item.get("passed") for item in evidence["checks"].values()
    ) and evidence["cleanup"]["passed"] and evidence["cleanup"]["source_repo_preserved"] else "failed"
    (out / "summary.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.txt").write_text(
        "\n".join([
            f"result={evidence['result']}",
            f"base_commit_sha={evidence['base_commit_sha']}",
            f"git_version={evidence['git_version']}",
            *(f"{name}={'PASS' if check['passed'] else 'FAIL'}" for name, check in evidence["checks"].items()),
            f"cleanup={'PASS' if evidence['cleanup']['passed'] and evidence['cleanup']['source_repo_preserved'] else 'FAIL'}",
        ]) + "\n",
        encoding="utf-8",
    )
    print((out / "summary.txt").read_text(encoding="utf-8"), end="")
    return 0 if evidence["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
