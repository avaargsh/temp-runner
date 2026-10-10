#!/usr/bin/env bash
# Experimental read-only scheduler-status receipt for pinned Volcano v1.15.3.
# Must run only inside the existing isolated kind-stageb-volcano fixture.
# No scheduling, GPU, quota, or production-ready claims may be inferred.
set -euo pipefail
[[ "$#" -eq 4 ]] || { echo "usage: bash $0 <namespace> <podgroup-name> <job-uid> <artifacts-dir>" >&2; exit 2; }
ns="$1"
name="$2"
job_uid="$3"
out="$4"
[[ "$(kubectl config current-context)" == "kind-stageb-volcano" ]] || {
  echo "BLOCKED: cluster context not disposable kind-stageb-volcano" >&2; exit 1;
}
kind get clusters | grep -Fxq stageb-volcano
[[ "$ns" =~ ^stageb-proof-[0-9]+$ && "$name" == "stageb-proof-job-$job_uid" && -n "$job_uid" ]] || {
  echo "BLOCKED: non-disposable or ambiguous Job/PodGroup identity" >&2; exit 1;
}
mkdir -p "$out"
kubectl --request-timeout=20s -n "$ns" get podgroups.scheduling.volcano.sh "$name" -o json > "$out/scheduler-pg-first.json"
kubectl --request-timeout=20s -n "$ns" get podgroups.scheduling.volcano.sh "$name" -o json > "$out/scheduler-pg-second.json"
jq -n \
  --slurpfile first "$out/scheduler-pg-first.json" \
  --slurpfile second "$out/scheduler-pg-second.json" \
  --arg job_uid "$job_uid" --arg group_name "$name" --arg namespace "$ns" \
  -f scripts/volcano-scheduler-signal.jq \
  > "$out/scheduler-signal.json"
jq -e '
  .contract == "stage-b-volcano-scheduler-signal/v1" and
  (.signal_status == "OBSERVED" or .signal_status == "UNPROVEN") and
  .quota_applied == "UNPROVEN" and .gpu_hardware == "UNPROVEN" and
  .execution_ownership == "UNPROVEN" and .production_promotion == "FORBIDDEN"
' "$out/scheduler-signal.json" >/dev/null
sha256sum "$out/scheduler-pg-first.json" "$out/scheduler-pg-second.json" "$out/scheduler-signal.json" \
  > "$out/scheduler-signal-receipt.sha256"
printf 'STAGE B scheduler-status observed=%s reason=%s (quota UNPROVEN, no promotion)\n' \
  "$(jq -r '.signal_status' "$out/scheduler-signal.json")" \
  "$(jq -r '.signal_reason' "$out/scheduler-signal.json")"
