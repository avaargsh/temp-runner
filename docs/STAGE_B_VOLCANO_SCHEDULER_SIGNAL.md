# Volcano v1.15.3 Scheduler Status Receipt — Stage B

**Scope:** CPU-only, disposable kind; evidence research. Kueue remains the sole registered production provider. This receipt does not authorize enabling Volcano.

## Source facts pinned to `d2dd7024f4af3070f9d99d68a78973893908a743`

- `PodGroup.status.phase=Running` means `spec.minMember` Pods have reached Running, rather than proving a particular Queue quota generation was applied. [Source](https://github.com/volcano-sh/volcano/blob/d2dd7024f4af3070f9d99d68a78973893908a743/staging/src/volcano.sh/apis/pkg/apis/scheduling/v1beta1/types.go#L43-L57)
- `PodGroup.status.conditions[].type=Scheduled` is an explicit scheduler-state type. `Unschedulable` is also part of that vocabulary; conflicting positive statuses must never be silently promoted. [Source](https://github.com/volcano-sh/volcano/blob/d2dd7024f4af3070f9d99d68a78973893908a743/staging/src/volcano.sh/apis/pkg/apis/scheduling/v1beta1/types.go#L62-L102)
- The Job controller searches for the latest true condition and does not interpret every nonempty condition as Scheduled. [Source](https://github.com/volcano-sh/volcano/blob/d2dd7024f4af3070f9d99d68a78973893908a743/pkg/controllers/job/job_controller_actions.go#L991-L1009)

## Implemented evidence contract

`scripts/volcano-scheduler-signal.sh` works **only** on the isolated `kind-stageb-volcano` cluster and `stageb-proof-<run_id>` namespace established by the existing `temp-runner` contract. It reads the same named PodGroup twice, saves both raw JSON objects, and applies the versioned `volcano-scheduler-signal.jq` evaluator.

`signal_status=OBSERVED` requires the same nonempty UID/RV and identical observed status across two reads, matching PodGroup GVK/name/namespace, Controller OwnerReference to the exact Job UID, `phase=Running`, `running >= minMember`, **exactly one** `Scheduled=True` condition, and no `Unschedulable=True`. Otherwise the observation is `UNPROVEN`. Both states are valid **data collection** results: the test fails only when collection/structural contracts are broken; it does not invent a scheduled condition when the deployed scheduler omits one.

This is a **bounded scheduler status signal, not an admission authorization, quota-generation attestation, or claim of hardware GPU execution.** The artifact unconditionally records `quota_applied=UNPROVEN`, `execution_ownership=UNPROVEN`, `gpu_hardware=UNPROVEN`, and `production_promotion=FORBIDDEN`.

Offline adversarial fixtures check missing/contradictory conditions, `Inqueue`, changed resourceVersion, recreated UID and foreign Controller UID. Real kind receipts include two API GET responses plus a sha256 digest.

## Promotion criteria

Do not alter `gpu-compute-platform`'s `Ready`, `QuotaApplied`, provider registry, or placement based only on this receipt. Stronger promotion requires independently demonstrated scheduler quota version observation, failure-mode falsification and eventually controlled real-GPU evidence. The currently pinned upstream scheduler status does **not** expose a Queue quota applied-generation acknowledgment.
