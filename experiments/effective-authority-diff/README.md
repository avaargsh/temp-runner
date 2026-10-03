# Effective Authority Diff kill test

This directory is an experiment, not product code. It asks one narrow question:

> Does a read-only, cross-source reachable-outcome diff find important deployment-time authority changes that a small amount of ordinary config-diff glue misses?

## Scope

Only these ideas are borrowed from the source projects:

- `agent-control-plane`: the authority inventory / grant shape and content-addressed frozen-evidence style;
- `cloud-agent-runtime`: canonical `Run` plus `SandboxBinding.sandbox_ref` identity as principal/workload graph input;
- AuthorityLens (arXiv:2609.32378): outcomes are measured through minimal sufficient principal coalitions; adding a delegated/spawned principal can replicate authority rather than separate it.

Explicitly out of scope: Binding DAG, EvalGate, StateTransition, execution, admission mutation, runtime enforcement, and any new user-authored authority schema.

## A vs B

**A** is `glue_a.sh`: under 200 LOC of shell using textual diff/grep checks for obvious RBAC, approval, MCP, workload identity, and sensitive-path changes. It intentionally does not construct a cross-domain graph.

**B** is `read_only_diff.py`: a read-only parser over facts that already exist in the deployment/runtime surface:

- Kubernetes Deployment service accounts, Role/ClusterRole, RoleBinding/ClusterRoleBinding;
- Rego approval predicates;
- MCP client/server configuration;
- `Run.run_id` and `SandboxBinding.sandbox_ref` snapshots.

It derives outcome -> minimal-principal-coalition profiles and reports only three kinds of authority drift:

1. `OUTCOME_EXPANSION` — a new reachable outcome;
2. `AUTHORITY_CONCENTRATION` — the outcome remains reachable but needs fewer principals;
3. `AUTHORITY_REPLICATION` — an additional principal becomes an alternative minimal holder of existing authority.

The 10-case suite contains 8 seeded dangerous changes and 2 benign controls. The kill rule is intentionally simple and pre-committed:

- if A detects **>=80%** of dangerous cases, stop Effective Authority Diff work;
- otherwise B has demonstrated incremental signal and only then is a minimal standalone CLI worth discussing.

Benign false positives are recorded separately so a detector cannot look good merely by flagging every change.

## Reproduce

```bash
python -m pip install pyyaml
python experiments/effective-authority-diff/run.py
cat artifacts/effective-authority-diff/summary.txt
```

The runner writes `result.json`, `result.sha256`, and `summary.txt`. `result.json` contains frozen baseline/candidate digests and the exact pinned source SHAs from `authority-diff-lock.json`.
