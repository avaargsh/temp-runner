# Agent Stack configuration inventory

This file is the cross-repository source of truth for environment-variable naming.

## GitHub repository secrets to configure today

| Repository | Secret | Status |
| --- | --- | --- |
| `avaargsh/temp-runner` | `AGENT_STACK_GITHUB_TOKEN` | Optional while every locked source repo is public; required only if a locked repo becomes private. |
| `avaargsh/agentic-aiops` | `AGENT_STACK_GITHUB_TOKEN` | **Required to enable** `four-repo-acceptance`; without it that job is skipped. |
| `avaargsh/agent-decision-lab` | `HF_TOKEN` | Optional; only needed for gated/private Hugging Face models. |
| `avaargsh/cloud-agent-runtime` | none | No repository secret currently consumed. |
| `avaargsh/agent-control-plane` | none | No repository secret currently consumed by its workflows. |

For the current public repository visibility, the Golden E2E does not require a custom repository token. If a locked source repo becomes private, configure `AGENT_STACK_GITHUB_TOKEN` with read-only **Contents** access to that repo; metadata read is implicit. Do not grant write/admin permissions just for cross-repo checkout.

## Secrets and credentials

| Variable | Required | Scope | Notes |
| --- | --- | --- | --- |
| `AGENT_STACK_GITHUB_TOKEN` | CI only when a referenced repo is private | GitHub Actions | Canonical replacement for `GOLDEN_STACK_REPO_TOKEN` and `CONTROL_PLANE_TOKEN`. Prefer a fine-grained PAT or GitHub App token with read-only Contents access to the required private repos. |
| `HF_TOKEN` | Only for gated/private Hugging Face checkpoints | model benchmark | Standard Hugging Face variable; do not introduce an Agent-specific alias. |
| `KUBECONFIG` | Only outside environments where kubectl already has credentials | Kubernetes | Standard kubeconfig path. Prefer workload identity/OIDC in production rather than storing kubeconfig contents in repository secrets. |
| `AGENT_STACK_TEMPORAL_DB_PASSWORD` | Shared/non-ephemeral demo DB only | local compose | Local ephemeral compose may use a disposable default; shared environments must override it. |

## Non-secret runtime configuration

| Variable | Default / source | Used by |
| --- | --- | --- |
| `TEMPORAL_ADDRESS` | `127.0.0.1:7233` / `localhost:7233` | runtime worker, AIOps, control-plane smoke |
| `TEMPORAL_NAMESPACE` | `default` | runtime worker |
| `TEMPORAL_TASK_QUEUE` | `agent-runs` | runtime worker, AIOps |
| `DECISION_GATEWAY_URL` | `http://127.0.0.1:8080` | AIOps |
| `DECISION_HOST` | `0.0.0.0` | Decision Gateway server |
| `DECISION_PORT` | `8080` | Decision Gateway server |
| `DECISION_MODE` | `demo` | Decision Gateway server |
| `PROMETHEUS_URL` | `http://127.0.0.1:19090` | AIOps |
| `KUBERNETES_API` | `http://127.0.0.1:18001` in demo | AIOps read path |
| `KUBE_CONTEXT` | explicit for live control-plane smoke | Control Plane |
| `KUBE_NAMESPACE` | explicit for live control-plane smoke | Control Plane |
| `AGENT_RELEASE_NAME` | release-specific | AIOps evidence |
| `AGENT_STACK_LIVE_SMOKE` | unset | Control Plane integration opt-in |
| `AGENT_STACK_TEMPORAL_DB_USER` | `temporal` | local compose |
| `TEMPORAL_VERSION` | `1.27.2` | local compose image selection |
| `RUN_ID` | scenario-specific default | AIOps demo/acceptance scripts |
| `SESSION_ID` | `golden-demo` | AIOps acceptance script |
| `PROM_PORT` | `19090` | local live demo helper |
| `API_PORT` | `18001` | local live demo helper |

## Derived values — do not configure as long-lived credentials

`AGENT_AUTHORITY_DIGEST` is produced by deployment-time authority admission. It should be passed into the incident execution for that admitted release, not copied into a permanent secret store.

Exact incident `approval_id`, `evidence_digest`, operation IDs and replay digests are runtime evidence identities, not operator-managed environment variables.

## Legacy names

The Control Plane temporarily accepts `ACP_KUBE_CONTEXT`, `ACP_KUBE_NAMESPACE`, `ACP_TEMPORAL_ADDRESS` and `ACP_LIVE_SMOKE` as compatibility aliases. New automation should only use the canonical names above.

The old CI secret names `GOLDEN_STACK_REPO_TOKEN` and `CONTROL_PLANE_TOKEN` are retired by the current credential-normalization changes.

## Workflow-local values

The Decision Lab model benchmark maps workflow inputs into `MODEL`, `CALIBRATION` and `TEST_DATASET`. These are job-local values, not repository secrets and do not need to be configured globally.

GitHub-provided variables such as `GITHUB_SHA`, `GITHUB_RUN_ID`, `RUNNER_OS` and `RUNNER_ARCH` are platform-owned and are intentionally excluded from the operator configuration surface.


## Immutable source lock

`stack-lock.json` is the release-facing source of truth for the four source
repositories used by `golden-e2e`. Normal PR, push, scheduled, and manually
dispatched runs all consume the exact 40-character commit SHAs in that file.

Updating a source component for Golden Stack acceptance therefore requires a
reviewable lock-file change. A mutable branch name such as `main` is not a
release input.
