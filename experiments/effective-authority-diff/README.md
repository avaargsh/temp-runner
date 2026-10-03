# Effective Authority Diff kill test

This directory is an experiment, not product code. It asks one narrow question:

> Does a read-only, cross-source reachable-outcome diff find important deployment-time authority changes that a small amount of ordinary config-diff glue misses?

## Scope

Only these ideas are borrowed from the source projects:

- `agent-control-plane`: authority inventory/grant shape and content-addressed frozen-evidence style;
- `cloud-agent-runtime`: canonical `Run` plus `SandboxBinding.sandbox_ref` identity as principal/workload graph input;
- AuthorityLens (arXiv:2609.32378): outcomes are measured through minimal sufficient principal coalitions; adding a delegated/spawned principal can replicate authority rather than separate it.

Explicitly out of scope: Binding DAG, EvalGate, StateTransition, execution, admission mutation, runtime enforcement, and any new mandatory user-authored authority schema.

## CLI

The B implementation is now a standalone read-only CLI:

```bash
python experiments/effective-authority-diff/authority_diff_cli.py \
  BASELINE_DIR CANDIDATE_DIR \
  --output effective-authority-diff.json \
  --sha-output effective-authority-diff.json.sha256
```

Input is only existing facts. The CLI emits one frozen JSON artifact plus its SHA-256 digest and reports exactly three semantic changes:

1. `OUTCOME_EXPANSION`
2. `AUTHORITY_CONCENTRATION`
3. `AUTHORITY_REPLICATION`

The kill-test runner invokes this CLI for every case; it no longer calls the parser library directly.

## A vs B

**A** is `glue_a.sh`: under 200 LOC of shell using ordinary textual/config checks and no cross-domain reachability graph.

**B** is the CLI above, reading existing Kubernetes workload/RBAC, Rego approval predicates, MCP JSON/TOML configuration, and Run/SandboxBinding identity.

### Round 1

Synthetic seeded suite, retained as the regression baseline:

```text
A: 5/8 dangerous = 62.5%, benign FP 0/2
B: 8/8 dangerous = 100%,  benign FP 0/2
decision: CONTINUE_MINIMAL_READ_ONLY_DIFF
```

### Round 2

Round 2 is generated deterministically in CI from exact pinned source files:

- `agentic-aiops/demo/k8s/golden-stack.yaml`
- `agent-control-plane/examples/cross_agent_context/codex.config.toml`
- `agent-control-plane/examples/cross_agent_context/claude.mcp.json`
- `cloud-agent-runtime/src/cloud_agent_runtime/models.py`
- `cloud-agent-runtime/tests/test_sandbox_recovery.py`

Every generated case records repository, commit SHA, source path, and source-file digest.

The pre-committed “clearly better” rule is:

```text
B dangerous recall >= 80%
AND B recall - A recall >= 20 percentage points
AND B benign false positives <= A benign false positives
```

Current CI result:

```text
A: 4/8 dangerous = 50%,  benign FP 0/2
B: 8/8 dangerous = 100%, benign FP 0/2
advantage: +50 percentage points
decision: DRAFT_ADMISSION_CAPABILITY
```

The resulting interface draft is in [ADMISSION_CAPABILITY_DRAFT.md](ADMISSION_CAPABILITY_DRAFT.md). It remains read-only and artifact-bound; the analyzer itself never emits an admit/deny decision.

## Reproduce

Round 1:

```bash
python -m pip install pyyaml
python experiments/effective-authority-diff/run.py \
  --round 1 \
  --out artifacts/effective-authority-diff/round-1
```

Round 2 requires the exact repositories in `authority-diff-lock.json` checked out under `workspace/`:

```bash
python experiments/effective-authority-diff/build_round2_cases.py \
  --workspace workspace \
  --source-lock authority-diff-lock.json \
  --output artifacts/effective-authority-diff/round-2-cases.json

python experiments/effective-authority-diff/run.py \
  --round 2 \
  --cases artifacts/effective-authority-diff/round-2-cases.json \
  --out artifacts/effective-authority-diff/round-2
```

The workflow uploads the case manifests, per-case CLI artifacts, their SHA files, aggregate `result.json`, and `result.sha256`.
