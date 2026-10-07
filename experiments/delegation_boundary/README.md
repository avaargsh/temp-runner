# Cross-principal delegation: read-only boundary probe

**Status:** falsification experiment. This is not a production authorization or identity system.

## Hypothesis

A personal Agent A should only learn the minimum information another user's Agent B
was explicitly authorized to disclose. A group-chat invitation, a plausible natural-
language instruction, or a new agent handoff must not silently expand that grant.

The project does **not** introduce a new Agent platform, memory service, A2A wire
protocol, MCP annotation, admission product, runtime policy engine, or side-effect path.
It is intentionally isolated from the frozen `agent-control-plane` v0.1 contract.

## Fixed synthetic scenario

- Bob owns `calendar:bob`, which contains `free_slots` **and** `private_notes`.
- Bob grants Alice's Agent `availability.query` for `schedule_meeting`.
- The scope is `free_slots` only, visible to `group:planning`, expires after five minutes,
  and is bound to authority generation 3.
- The caller principal is supplied separately from the request fields to model the
  *external* authenticated session, not to trust the request's `requester` claim.
- The evaluation result may project only `free_slots`. Serialized CI artifacts
  contain *field names and test results*, not the synthetic private payload.

## Falsification matrix

`run.py` tests 21 cases: 1 allowed, 20 blocked, including:

- missing grant; caller spoofing; wrong grantee or issuing owner; wrong grant ID;
- revoked and consumed grants, stale authority generation and expiry;
- wrong resource, operation, purpose or audience;
- removal of requester/owner from the audience;
- excess fields, missing fields, malformed expiry or field list, and unknown request keys.

All denied paths return an empty projection. The permitted path must release exactly
`free_slots`, never `private_notes`.

## Reproduce (Python 3.11+, standard library only)

```bash
python -m unittest discover -s experiments/delegation_boundary -p 'test_*.py' -v

python experiments/delegation_boundary/run.py \
  --out artifacts/delegation-boundary/probe.json

python experiments/delegation_boundary/run.py \
  --verify artifacts/delegation-boundary/probe.json \
  --sha-file artifacts/delegation-boundary/probe.json.sha256
```

CI runs Python 3.11 and 3.12, independently verifies the canonical SHA-256
artifact and uploads the synthetic probe. The tests also change artifact bytes
without changing the trusted digest and require verification to fail.

The digest only establishes **byte integrity relative to a trusted digest**.
The adjacent SHA file is *not* a signature, a trusted provenance channel or
an independent execution/ownership proof.

## Explicit limitations / do not promote

The fixture provides asserted facts. This experiment **does not prove**:

1. principal authentication or grant authenticity;
2. an authoritative, freshness-checked group membership source;
3. atomic consume-once semantics, revocation ordering, or crash/takeover fencing;
4. external API enforcement, credential isolation, sensitive-data propagation;
5. provider observation or operation ownership;
6. the existence of a commercial standalone delegation product.

**Promotion gate:** only consider a provider-neutral delegation binding after
a real user workflow supplies a concrete need, an authenticated owner-side
enforcement point and independently verified denial of stale/replayed grants.
Until then, the result stays in `temp-runner` as a self-contained, read-only
contract falsification suite; no new interface is merged into the control plane.

Related work:
- `agent-control-plane/docs/CROSS_AGENT_CONTEXT.md`: same-work-item handoff,
  owner fencing and the *different* work-context identity problem.
- `agent-control-plane/docs/V0.1_FREEZE.md`: frozen exact-plan execution boundary.
- `temp-runner/experiments/effective-authority-diff/`: separate deploy-time
  capability experiment; this probe neither upgrades its product status nor
  derives runtime authority from its diff signals.
