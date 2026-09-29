# temp-runner

Public disposable integration harness for the Golden Incident reference stack.

This repository owns **experiments, not product code**. It checks out the three source repositories at explicit refs and runs integration/E2E experiments on an ephemeral GitHub-hosted runner.

## Golden Incident stack

- [agentic-aiops](https://github.com/avaargsh/agentic-aiops) — evidence, policy, remediation and verification
- [agent-decision-lab](https://github.com/avaargsh/agent-decision-lab) — Decision Gateway
- [cloud-agent-runtime](https://github.com/avaargsh/cloud-agent-runtime) — Temporal durable Run lifecycle
- [agent-control-plane](https://github.com/avaargsh/agent-control-plane) — Release policy and EvalGate authority

Target acceptance path:

```text
kind -> workload/load -> evidence -> decision -> WAIT_APPROVAL
     -> approval signal -> continue -> scale 2->4 -> verify
     -> Temporal COMPLETE -> replay/evaluation metrics
     -> Agent Control Plane EvalGate -> release promotable
```

## Rules

1. Pin source refs in the workflow when reproducing an experiment.
2. Never copy implementation code from the three source repositories here.
3. Upload logs and state snapshots as Actions artifacts.
4. A green unit test in a source repository is not an E2E claim.
5. Only call Golden Incident E2E verified after this runner observes the complete acceptance path.


## P0 baseline

The P0 baseline is intentionally narrow and frozen:

- source contracts pass;
- a disposable kind cluster boots the Golden Incident stack;
- an unrelated approval is injected first and must leave `checkout-api` at 2 replicas;
- only the exact frozen-action approval may authorize the Kubernetes write;
- `checkout-api` then scales from 2 to 4 ready replicas;
- Prometheus post-action verification passes;
- remediation reaches `VERIFIED` without rollback;
- the canonical Temporal run reaches `phase=succeeded` and `terminal=true`;
- replay/evaluation emits the metric contract consumed by the control plane;
- the Agent Control Plane EvalGate must pass before the run is accepted as release-promotable;
- diagnostics, metrics, and gate evidence are retained as Actions artifacts.

The `golden-e2e` workflow runs on pull requests and pushes to `main`, in addition to manual dispatch. New features must not weaken or bypass this baseline.
