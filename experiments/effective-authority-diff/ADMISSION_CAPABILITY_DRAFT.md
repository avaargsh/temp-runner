# Effective Authority Diff — admission capability interface draft

Status: **read-only experiment**. The artifact-binding interface now has an executable validator, but it still does not add runtime enforcement, a new desired-state API, Binding DAG semantics, EvalGate behavior, or a StateTransition execution path.

## Purpose

Expose the proven read-only diff as an optional **deployment-time admission capability**. The analyzer does not admit or deny a deployment. It freezes baseline/candidate facts, computes reachable-outcome drift, emits one content-addressed artifact, and returns its reference to the existing admission layer.

```text
baseline facts ─┐
                ├─ freeze ─> authority-diff (read-only) ─> EffectiveAuthorityDiff artifact
candidate facts ┘                                      │
                                                       └─ sha256
                                                            │
                                                            v
                                             existing deployment admission
                                             consumes artifact only
```

## Provider interface

A future adapter should be no larger than this semantic interface:

```python
class AuthorityDiffCapability(Protocol):
    def compare(
        self,
        *,
        baseline: FactSnapshotRef,
        candidate: FactSnapshotRef,
    ) -> ArtifactRef:
        ...
```

`FactSnapshotRef` is internal plumbing over already-existing fact sources. It must not require operators to author a new authority graph or duplicate Kubernetes / MCP / runtime configuration.

The current CLI is the reference behavior:

```bash
authority-diff BASELINE_DIR CANDIDATE_DIR \
  --output effective-authority-diff.json \
  --sha-output effective-authority-diff.json.sha256
```

## Artifact contract

The artifact is immutable and content-addressed. Minimum fields:

```text
schema_version
kind = EffectiveAuthorityDiff
mode = read-only
semantics = [
  OUTCOME_EXPANSION,
  AUTHORITY_CONCENTRATION,
  AUTHORITY_REPLICATION
]

baseline.tree_digest
baseline.files[].{path, sha256, size}
baseline.reachable_outcomes

candidate.tree_digest
candidate.files[].{path, sha256, size}
candidate.reachable_outcomes

diff.detected
diff.signals[]
content_digest
```

The analyzer reports facts only:

- **OUTCOME_EXPANSION** — a candidate can reach an outcome not reachable from the baseline.
- **AUTHORITY_CONCENTRATION** — the outcome remains reachable with a smaller minimal principal coalition.
- **AUTHORITY_REPLICATION** — a new minimal principal coalition becomes an alternative holder of an existing outcome.

It must not emit `ADMIT`, `DENY`, `PROMOTE`, remediation actions, or runtime policy mutations.

## Artifact binding at admission

The deployment-time admission request may attach only an artifact reference and digest:

```text
authorityDiffArtifactRef
authorityDiffArtifactDigest
baselineFactDigest
candidateFactDigest
```

These are internal admission inputs, not a new user-authored CRD contract.

Admission verifies:

1. the artifact digest matches its bytes;
2. baseline/candidate fact digests match the deployment review inputs;
3. the artifact was produced from immutable source revisions;
4. policy evaluates only the frozen artifact;
5. no live source re-read occurs after the review starts.

The organization-specific admission policy remains outside the analyzer. For example, one installation may require review for any `AUTHORITY_REPLICATION`, while another may tolerate a bounded `OUTCOME_EXPANSION`. That policy is deliberately not encoded in the CLI.

## Integration boundary

Allowed:

```text
AgentRelease / deployment review
        |
        +--> freeze existing facts
        +--> AuthorityDiffCapability.compare(...)
        +--> bind ArtifactRef + digest
        +--> existing admission policy consumes signals
```

Not allowed:

```text
authority-diff -> provider side effect
authority-diff -> runtime authorization
authority-diff -> Binding DAG
authority-diff -> EvalGate
authority-diff -> StateTransition
authority-diff -> new mandatory operator schema
```

## Promotion gate for this capability

Before moving this interface out of `temp-runner`, require one additional validation set from repositories/configurations not used to shape the parser. If the read-only CLI loses its material advantage over <=200 LOC existing-tool glue, retire the capability rather than hardening it into the Control Plane.

Current evidence from the two committed rounds:

```text
Round 1: A 5/8 (62.5%), B 8/8 (100%), benign FP 0/2 vs 0/2
Round 2: A 4/8 (50.0%), B 8/8 (100%), benign FP 0/2 vs 0/2
Decision: DRAFT_ADMISSION_CAPABILITY
```


## Executable experiment

`admission_input.py` now verifies the frozen diff bytes and their trusted
digest, requires exact baseline/candidate fact digests from the deployment
review, and emits a second content-addressed
`AuthorityDiffAdmissionInput` artifact.

The output deliberately contains signals but **no ADMIT / DENY / PROMOTE
decision**. The smoke test also proves a mismatched baseline digest fails closed.

This remains inside `temp-runner`. Promotion still requires an independent
third validation set as described above.
