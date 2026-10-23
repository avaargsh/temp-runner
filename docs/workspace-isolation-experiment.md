# Agent Workspace Isolation Experiment

## Status

Design-only experiment plan. This document does not change the Golden Incident acceptance path, product repositories, or the immutable `stack-lock.json`.

## Goal

Evaluate whether Git worktrees provide sufficient isolation for multiple coding agents working from the same repository baseline, before introducing an OverlayFS-backed workspace or a new runtime dependency.

The desired property is **isolated writes with explicit, conflict-aware adoption**: agents may read the same immutable baseline, but one agent's uncommitted changes must not appear in another agent's workspace, and adopting changes must never silently overwrite concurrent work.

## Initial hypothesis

Start with Git worktrees backed by separate work branches and one recorded base commit SHA per workspace. This is the lowest-complexity baseline. Only evaluate OverlayFS or a sandbox runtime if measurements show a concrete limitation that worktrees cannot meet.

Git worktrees isolate working directories, but they do not by themselves provide process/container security isolation. The experiment must not claim otherwise.

## Scope and non-goals

In scope:

- Workspace lifecycle and metadata.
- Change collection and a reviewable ChangeSet.
- Conflict detection against the target branch/commit.
- Repeatable cleanup and evidence capture.
- Relative performance and storage measurements for large repositories.

Out of scope for this first pass:

- Production Workspace Adapter implementation.
- CubeSandbox, OverlayFS, FUSE, or container runtime integration.
- Agent execution semantics, model orchestration, or authorization policy.
- Changes to the frozen Golden Incident path.

## Proposed workspace record

Every experiment workspace should record:

- `workspace_id` and owner/agent identity used by the harness.
- Repository identity and canonical checkout path.
- Immutable `base_commit_sha`.
- Dedicated branch/worktree path.
- Creation time and lifecycle state.
- Collected ChangeSet identifier and content digest, if present.
- Validation result, adoption target SHA, and cleanup result.

Do not treat a branch name as an immutable baseline. Resolve and record the full commit SHA at creation.

## ChangeSet contract (proposal)

A collected ChangeSet should include:

- `schema_version`, `workspace_id`, `base_commit_sha`, and repository identity.
- A deterministic list of changed paths and operations: add, modify, delete, rename, and copy where Git can establish them.
- Per-file status and content/blob hashes where available.
- Validation evidence and collection timestamp.
- A digest over the canonicalized manifest.

The manifest is evidence, not an instruction to blindly copy arbitrary paths. Adoption must validate paths and re-derive the applicable patch from the recorded base.

## Adoption rules

1. Require the ChangeSet's recorded base SHA and the exact target SHA observed at validation time.
2. Refuse adoption if the target moved after validation; revalidate against the new target.
3. Detect overlapping edits and delete/modify, rename, and add/add conflicts. Never silently prefer the incoming workspace.
4. Apply through a temporary integration worktree or equivalent isolated staging area.
5. Run required checks before producing an adoption commit or patch.
6. Make retries idempotent: identify the ChangeSet and resulting commit, and do not apply the same change twice.
7. Preserve failed patch, conflict, and test evidence without modifying the target.
8. Reject path traversal and unsafe path forms; test symlinks, submodules, ignored files, binary files, and large files explicitly.
9. Cleanup must only remove resources recorded as owned by that workspace; never recursively delete a caller-supplied path without verifying its canonical location and ownership.

## Test matrix

| Case | Setup | Required result |
|---|---|---|
| Independent edits | Two workspaces from the same SHA edit different files | Changes remain invisible across workspaces; both can be collected |
| Same-file edits | Two workspaces modify the same file | Isolation holds; adoption detects conflict or requires explicit resolution |
| Delete/modify | One workspace deletes a file while another modifies it | Conflict is explicit; no silent data loss |
| Add/add | Both workspaces add the same path | Conflict is explicit |
| Rename | Rename in one workspace overlaps an edit in another | Conflict is reported conservatively |
| Baseline drift | Target branch advances after ChangeSet validation | Adoption is rejected and must be revalidated |
| Retry | Adoption request is repeated after success or ambiguous failure | No duplicate application; result is reconcilable |
| Cleanup boundary | Workspace cleanup is requested with stale or malformed metadata | Shared source and other workspaces remain untouched |
| Unsafe paths | Symlink/path traversal and unusual filenames are included | Validation fails closed or safely handles the case |
| Large repository | Many files and large binaries are present | Measure create, collect, validate, adopt, cleanup time and disk usage |

## Evidence to retain

Each run should retain an artifact bundle containing:

- Exact source repository URL and base commit SHA.
- Workspace metadata and the ChangeSet manifest/digest.
- Commands and exit codes for collection, validation, adoption, and cleanup.
- Conflict reports and test output.
- Wall-clock timings and before/after disk usage.
- Harness revision SHA and runtime environment summary.

Do not include secrets, credentials, private source content, or environment dumps in artifacts.

## Decision gates

- **Gate A — semantics:** all isolation, conflict, drift, retry, and cleanup cases pass.
- **Gate B — evidence:** each result is tied to exact source and harness SHAs and can be reproduced from retained artifacts.
- **Gate C — performance:** record a worktree baseline before comparing an OverlayFS prototype on the same repository and workload.
- **Gate D — complexity:** add OverlayFS/CubeSandbox only if measured requirements justify the additional runtime, filesystem, and operational failure modes.

## Suggested implementation order

1. Add a disposable experiment script/workflow without changing the frozen `golden-e2e` workflow.
2. Create two worktrees from the same recorded SHA, each on a distinct branch.
3. Implement deterministic ChangeSet collection and conflict-only dry-run.
4. Add adoption staging, post-apply checks, and safe cleanup.
5. Run the matrix and retain artifacts.
6. Compare OverlayFS only after the Git-worktree baseline is trustworthy.

## References

- [KakuriZai](https://github.com/IPA-CyberLab/IPA-RS-KakuriZai): reference for shared lower layers, per-workspace writable layers, and sandbox lifecycle.
- [Linux OverlayFS documentation](https://www.kernel.org/doc/html/latest/filesystems/overlayfs.html): reference for copy-up and layered filesystem semantics.
- [Git worktree documentation](https://git-scm.com/docs/git-worktree): candidate low-complexity baseline.

