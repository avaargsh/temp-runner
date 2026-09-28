# temp-runner

Public disposable integration harness for the Golden Incident reference stack.

This repository owns **experiments, not product code**. It checks out the three source repositories at explicit refs and runs integration/E2E experiments on an ephemeral GitHub-hosted runner.

## Golden Incident stack

- [agentic-aiops](https://github.com/avaargsh/agentic-aiops) — evidence, policy, remediation and verification
- [agent-decision-lab](https://github.com/avaargsh/agent-decision-lab) — Decision Gateway
- [cloud-agent-runtime](https://github.com/avaargsh/cloud-agent-runtime) — Temporal durable Run lifecycle

Target acceptance path:

```text
kind -> workload/load -> evidence -> decision -> WAIT_APPROVAL
     -> approval signal -> continue -> scale 2->4 -> verify
     -> Temporal COMPLETE -> replay from frozen evidence
```

## Rules

1. Pin source refs in the workflow when reproducing an experiment.
2. Never copy implementation code from the three source repositories here.
3. Upload logs and state snapshots as Actions artifacts.
4. A green unit test in a source repository is not an E2E claim.
5. Only call Golden Incident E2E verified after this runner observes the complete acceptance path.
