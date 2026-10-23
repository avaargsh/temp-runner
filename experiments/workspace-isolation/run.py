#!/usr/bin/env python3
"""Disposable Git-worktree conflict/isolation smoke test; stdlib only.

This is an experiment harness, not a production workspace manager. Git worktrees
provide directory/write separation, not process or container security isolation.
"""

from __future__ import annotations

import argparse
import json
import os
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


def record_check(evidence: dict[str, Any], name: str, passed: bool, **details: Any) -> None:
    evidence["checks"][name] = {"passed": bool(passed), **details}
    if not passed:
        raise AssertionError(f"check failed: {name}; details={details}")


def commit_file(repo: Path, path: str, content: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    run_git(repo, "add", "--", path)
    run_git(repo, "commit", "-q", "-m", message)
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def merge_tree(repo: Path, left: str, right: str) -> subprocess.CompletedProcess[str]:
    return run_git(repo, "merge-tree", "--write-tree", left, right, check=False)


def has_conflict(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode != 0 and "CONFLICT" in result.stdout


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
        (repo / "delete-me.txt").write_text("base delete target\n", encoding="utf-8")
        run_git(repo, "add", "README.md", "shared.txt", "delete-me.txt")
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
        record_check(
            evidence,
            "uncommitted_changes_are_not_visible_across_worktrees",
            not (work_b / "only-a.txt").exists() and not (work_a / "only-b.txt").exists(),
            workspace_a_file_visible_in_b=(work_b / "only-a.txt").exists(),
            workspace_b_file_visible_in_a=(work_a / "only-b.txt").exists(),
        )

        # Same-file edits must conflict; neither side is silently selected.
        (work_a / "shared.txt").write_text("change from agent A\n", encoding="utf-8")
        (work_b / "shared.txt").write_text("change from agent B\n", encoding="utf-8")
        sha_a = commit_file(work_a, "only-a.txt", "agent A\n", "agent A add")
        # Commit shared.txt together with A's new file.
        run_git(work_a, "add", "shared.txt")
        run_git(work_a, "commit", "-q", "--amend", "--no-edit")
        sha_a = run_git(work_a, "rev-parse", "HEAD").stdout.strip()
        run_git(work_b, "add", "only-b.txt", "shared.txt")
        run_git(work_b, "commit", "-q", "-m", "agent B changes")
        sha_b = run_git(work_b, "rev-parse", "HEAD").stdout.strip()
        t0 = time.monotonic()
        same_file = merge_tree(repo, sha_a, sha_b)
        evidence["timings_seconds"]["same_file_conflict_detection"] = round(time.monotonic() - t0, 6)
        record_check(
            evidence,
            "same_file_conflict_is_detected",
            has_conflict(same_file),
            merge_tree_exit_code=same_file.returncode,
            conflict_output=same_file.stdout[-3000:],
            agent_a_commit_sha=sha_a,
            agent_b_commit_sha=sha_b,
        )

        # Non-overlapping file additions should merge cleanly.
        clean_a = root / "clean-a"
        clean_b = root / "clean-b"
        run_git(repo, "worktree", "add", "-q", "-b", "clean-a", str(clean_a), base_sha)
        run_git(repo, "worktree", "add", "-q", "-b", "clean-b", str(clean_b), base_sha)
        sha_clean_a = commit_file(clean_a, "left.txt", "left\n", "left addition")
        sha_clean_b = commit_file(clean_b, "right.txt", "right\n", "right addition")
        clean_merge = merge_tree(repo, sha_clean_a, sha_clean_b)
        record_check(
            evidence,
            "non_overlapping_additions_merge_cleanly",
            clean_merge.returncode == 0,
            merge_tree_exit_code=clean_merge.returncode,
            output=clean_merge.stdout[-2000:],
        )

        # Delete/modify must be surfaced as a conflict.
        delete_branch = root / "delete-branch"
        modify_branch = root / "modify-branch"
        run_git(repo, "worktree", "add", "-q", "-b", "delete-branch", str(delete_branch), base_sha)
        run_git(repo, "worktree", "add", "-q", "-b", "modify-branch", str(modify_branch), base_sha)
        (delete_branch / "delete-me.txt").unlink()
        run_git(delete_branch, "add", "-u", "--", "delete-me.txt")
        run_git(delete_branch, "commit", "-q", "-m", "delete target")
        delete_sha = run_git(delete_branch, "rev-parse", "HEAD").stdout.strip()
        modify_sha = commit_file(modify_branch, "delete-me.txt", "modified by peer\n", "modify target")
        delete_modify = merge_tree(repo, delete_sha, modify_sha)
        record_check(
            evidence,
            "delete_modify_conflict_is_detected",
            has_conflict(delete_modify),
            merge_tree_exit_code=delete_modify.returncode,
            conflict_output=delete_modify.stdout[-3000:],
        )

        # Add/add to the same path must be surfaced as a conflict.
        add_a = root / "add-a"
        add_b = root / "add-b"
        run_git(repo, "worktree", "add", "-q", "-b", "add-a", str(add_a), base_sha)
        run_git(repo, "worktree", "add", "-q", "-b", "add-b", str(add_b), base_sha)
        add_sha_a = commit_file(add_a, "same-new-path.txt", "from A\n", "A adds path")
        add_sha_b = commit_file(add_b, "same-new-path.txt", "from B\n", "B adds path")
        add_add = merge_tree(repo, add_sha_a, add_sha_b)
        record_check(
            evidence,
            "add_add_conflict_is_detected",
            has_conflict(add_add),
            merge_tree_exit_code=add_add.returncode,
            conflict_output=add_add.stdout[-3000:],
        )

        # Simulate a validated target advancing. A ChangeSet bound to the
        # previous target must be rejected rather than applied without recheck.
        target_before = run_git(repo, "rev-parse", "main").stdout.strip()
        run_git(repo, "checkout", "-q", "main")
        drift_file = repo / "target-advanced.txt"
        drift_file.write_text("target moved\n", encoding="utf-8")
        run_git(repo, "add", "--", "target-advanced.txt")
        run_git(repo, "commit", "-q", "-m", "advance target")
        target_after = run_git(repo, "rev-parse", "main").stdout.strip()
        stale_validation_rejected = target_before != target_after
        record_check(
            evidence,
            "target_sha_drift_is_detectable",
            stale_validation_rejected,
            validated_target_sha=target_before,
            current_target_sha=target_after,
            note="Harness verifies SHA drift detection only; production adoption guard is not implemented here.",
        )

        # Verify cleanup is scoped to the disposable experiment repository.
        evidence["cleanup"]["attempted"] = True
        for workspace in (work_a, work_b, clean_a, clean_b, delete_branch, modify_branch, add_a, add_b):
            run_git(repo, "worktree", "remove", "--force", str(workspace))
        run_git(repo, "worktree", "prune")
        all_worktrees_removed = all(
            not workspace.exists()
            for workspace in (work_a, work_b, clean_a, clean_b, delete_branch, modify_branch, add_a, add_b)
        )
        source_repo_preserved = (repo / ".git").exists() and (repo / "README.md").exists()
        evidence["cleanup"]["passed"] = all_worktrees_removed
        evidence["cleanup"]["source_repo_preserved"] = source_repo_preserved
        if not all_worktrees_removed or not source_repo_preserved:
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
