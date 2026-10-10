#!/usr/bin/env bash
# Pure jq falsification: no cluster, no privileged operations.
set -euo pipefail
cd "$(dirname "$0")/.."
dir="$(mktemp -d)"
trap 'rm -rf "$dir"' EXIT
cat > "$dir/podgroup.json" <<'JSON'
{
  "apiVersion": "scheduling.volcano.sh/v1beta1",
  "kind": "PodGroup",
  "metadata": {
    "name": "stageb-proof-job-job-uid",
    "namespace": "stageb-proof-123",
    "uid": "pg-uid",
    "resourceVersion": "41",
    "ownerReferences": [{
      "apiVersion": "batch.volcano.sh/v1alpha1",
      "kind": "Job",
      "name": "stageb-proof-job",
      "uid": "job-uid",
      "controller": true
    }]
  },
  "spec": {"queue": "default", "minMember": 1},
  "status": {
    "phase": "Running",
    "running": 1,
    "conditions": [{"type": "Scheduled", "status": "True"}]
  }
}
JSON
cp "$dir/podgroup.json" "$dir/second.json"
check() {
  local want="$1" reason="$2"
  jq -n --slurpfile first "$dir/podgroup.json" \
        --slurpfile second "$dir/second.json" \
        --arg job_uid job-uid --arg group_name stageb-proof-job-job-uid \
        --arg namespace stageb-proof-123 \
        -f scripts/volcano-scheduler-signal.jq > "$dir/result.json"
  jq -e --arg want "$want" --arg reason "$reason" '
    .signal_status == $want and .signal_reason == $reason and
    .quota_applied == "UNPROVEN" and .execution_ownership == "UNPROVEN" and
    .production_promotion == "FORBIDDEN"
  ' "$dir/result.json" >/dev/null || {
    cat "$dir/result.json" >&2
    return 1
  }
}
check OBSERVED PinnedPodGroupScheduledStatusCorroborated

jq '.status.conditions = []' "$dir/podgroup.json" > "$dir/second.json"
check UNPROVEN PodGroupReadbackDrift
jq '.status.conditions = []' "$dir/podgroup.json" > "$dir/podgroup-missing.json"
cp "$dir/podgroup-missing.json" "$dir/second.json"
mv "$dir/podgroup-missing.json" "$dir/podgroup.json"
check UNPROVEN ScheduledConditionUnproven

# Restore original model. Conflicting unschedulable True must not be positive.
jq '.status.conditions = [{"type":"Scheduled","status":"True"},{"type":"Unschedulable","status":"True"}]' \
  "$dir/podgroup.json" > "$dir/mutated.json"
cp "$dir/mutated.json" "$dir/podgroup.json"
cp "$dir/mutated.json" "$dir/second.json"
check UNPROVEN ConflictingUnschedulableCondition

# Same-name PodGroup new UID between reads is drift, not a positive signal.
jq '.metadata.uid = "recreated-pg"' "$dir/podgroup.json" > "$dir/second.json"
check UNPROVEN PodGroupReadbackDrift

# A stale or foreign Controller Job UID is not scheduler evidence.
jq '.metadata.ownerReferences[0].uid = "foreign-job"' "$dir/podgroup.json" > "$dir/mutated.json"
cp "$dir/mutated.json" "$dir/podgroup.json"
cp "$dir/mutated.json" "$dir/second.json"
check UNPROVEN PodGroupOwnershipUnproven

# Inqueue is not the same as Running/admitted.
jq '.metadata.ownerReferences[0].uid = "job-uid" | .status.phase = "Inqueue"' \
  "$dir/podgroup.json" > "$dir/mutated.json"
cp "$dir/mutated.json" "$dir/podgroup.json"
cp "$dir/mutated.json" "$dir/second.json"
check UNPROVEN PodGroupNotRunning
echo 'STAGE B scheduler-status offline negatives: PASS'
