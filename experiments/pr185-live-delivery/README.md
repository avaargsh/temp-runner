# PR #185 live-delivery disposable experiment

Status: **PREPARED / NOT RUN / NO-GO**

This document is an isolated test plan for `agent-control-plane#185`. It is not evidence that a webhook was registered, delivered, accepted, or recovered. Do not mark any case PASS until the receiver, PostgreSQL Inbox, Temporal History, and read-only GitHub observations have been captured from the same test run.

## Isolation boundary

- Repository: `avaargsh/temp-runner` (disposable experiment repository).
- Use this dedicated PR only as the pull-request event target. Do not reuse PR #12 or #19; they have separate experiment scopes.
- Use an operator-owned, isolated HTTPS staging receiver and a dedicated GitHub App/webhook installation scoped to this repository only.
- Do not register a webhook, expose an endpoint, change DNS, or send live deliveries until the operator explicitly approves the environment and test window.
- Never put tokens, webhook secrets, private keys, raw authorization headers, or unredacted payload secrets in this repository, PR comments, Actions artifacts, or issue comments.

## Required operator-owned inputs

Record identifiers only; never record secret values.

- [ ] Staging hostname and TLS certificate/issuer verified.
- [ ] PostgreSQL 16 instance and disposable database/schema identifier.
- [ ] Temporal namespace and worker deployment identifier.
- [ ] GitHub App/webhook installation identifier and least-privilege permission review.
- [ ] Secret-manager reference for the webhook secret; rotation/revocation owner.
- [ ] Backup completed and restore procedure tested in the isolated environment.
- [ ] Named operator, independent reviewer, rollback owner, and approved test window.
- [ ] Explicit approval to register the webhook and trigger real external deliveries.

## Event correlation

For each case, preserve a single correlation record containing:
- test case ID and UTC time window;
- repository full name, PR number, event type/action, and redacted delivery UUID;
- request-body SHA-256 and HMAC verification result (never the secret or signature key);
- durable PostgreSQL Inbox row ID and dedupe outcome;
- Temporal workflow/run ID and exact History event IDs for the corresponding wake;
- read-only GitHub API observation used to independently verify the PR/check association;
- final Goal/Task/Activity state and audit/outbox record IDs;
- exact receiver/worker commit SHAs and artifact digest.

A digest proves artifact integrity, not signer identity or business correctness. Keep identity/signature verification as a separate assertion.

## Acceptance matrix

| Case | Expected result | Evidence required |
| --- | --- | --- |
| Valid `pull_request` delivery for this PR | One durable Inbox receipt and one correlated workflow wake | HMAC result, Inbox row, Temporal History IDs |
| Explicitly associated `check_run.completed` or `check_suite.completed` | Accepted only for the expected repository/PR/check association | Read-only GitHub observation plus association decision |
| Duplicate delivery UUID, identical body | Idempotent duplicate; no second logical wake/side effect | Original and duplicate receipts plus History comparison |
| Duplicate delivery UUID, conflicting body | Reject/fail closed and emit audit evidence | Conflict decision and audit record |
| Invalid or rotated HMAC | Reject before durable business processing | Redacted rejection record; no accepted Inbox item |
| Wrong repository, PR, check association, owner, or paused/cancelled Goal | Reject or remain safely non-progressing | Decision trace and unchanged scoped state |
| Lost Signal acknowledgement | Retry safely without duplicate logical effect | Retry records, one logical transition |
| Worker SIGKILL and restart after Inbox persistence | Recover from durable state; no lost or duplicate logical transition | Before/after DB snapshots and Temporal History |
| GitHub API outage or inaccessible/truncated History | Fail closed; acceptance remains inconclusive | Error record and explicit NO-GO |
| Revoked/stale approval | Deny; no privileged transition | Denial and audit evidence |

## Run procedure

1. Review and approve the isolated staging identifiers and test window in issue #185.
2. Verify backup/restore and rollback before registering any webhook.
3. Register only the dedicated repository/PR target after explicit approval.
4. Execute one case at a time with unique test IDs; collect evidence before retrying.
5. Inject the documented failures, including worker termination, only in the isolated environment.
6. Independently review correlations across delivery, Inbox, Temporal History, GitHub state, and audit evidence.
7. Publish a redacted evidence bundle with exact code SHAs and artifact digest; record missing cases as NOT RUN, never PASS.
8. Keep issue #185 OPEN / NO-GO until the independent reviewer records a signed decision and all mandatory cases pass.

## Rollback

Disable the test webhook, revoke its dedicated secret/installation credential, close staging ingress, pause the test Goal, stop the test worker if necessary, and preserve PostgreSQL Inbox plus Temporal History for investigation. Do not delete evidence or blindly replay uncertain deliveries.

## Current result

**NOT RUN / NO-GO.** Creating this plan or opening this PR does not trigger a webhook registration and does not satisfy live-delivery acceptance.
