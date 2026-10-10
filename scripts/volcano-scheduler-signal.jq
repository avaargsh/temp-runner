# Volcanosh v1.15.3 PodGroup-status *signal*, not quota/admission proof.
# Input: -n --slurpfile first <first.json> --slurpfile second <second.json>
# --arg job_uid <uid> --arg group_name <name> --arg namespace <ns>
# A source status without explicit Scheduled=True stays UNPROVEN.
($first[0]) as $a |
($second[0]) as $b |
([($b.status.conditions // [])[] | select(.type == "Scheduled")]) as $scheduled |
([($b.status.conditions // [])[] | select(.type == "Unschedulable" and .status == "True")]) as $unschedulable |
(
  ($a.metadata.uid // "") != "" and
  $a.metadata.uid == $b.metadata.uid and
  ($a.metadata.resourceVersion // "") != "" and
  $a.metadata.resourceVersion == $b.metadata.resourceVersion and
  $a.spec == $b.spec and
  $a.status == $b.status
) as $stable |
(
  ($a.apiVersion == "scheduling.volcano.sh/v1beta1") and
  ($b.apiVersion == "scheduling.volcano.sh/v1beta1") and
  $a.kind == "PodGroup" and $b.kind == "PodGroup" and
  $a.metadata.name == $group_name and $b.metadata.name == $group_name and
  $a.metadata.namespace == $namespace and $b.metadata.namespace == $namespace and
  ($b.metadata.deletionTimestamp == null) and
  ([($b.metadata.ownerReferences // [])[] |
    select(.controller == true and .uid == $job_uid and
      .apiVersion == "batch.volcano.sh/v1alpha1" and .kind == "Job" and
      .name == "stageb-proof-job")] | length) == 1
) as $owned |
(
  $stable and $owned and
  $b.status.phase == "Running" and
  (($b.status.running // 0) | type == "number") and
  (($b.status.running // 0) >= ($b.spec.minMember // 1)) and
  ($scheduled | length) == 1 and
  $scheduled[0].status == "True" and
  ($unschedulable | length) == 0
) as $observed |
{
  contract: "stage-b-volcano-scheduler-signal/v1",
  source: "pinned-volcano-1.15.3-podgroup-api-status",
  podgroup: $group_name,
  namespace: $namespace,
  podgroup_uid: ($b.metadata.uid // null),
  podgroup_resource_version: ($b.metadata.resourceVersion // null),
  snapshots_stable: $stable,
  job_controller_identity_match: $owned,
  phase: ($b.status.phase // null),
  running: ($b.status.running // null),
  min_member: ($b.spec.minMember // null),
  scheduled_conditions: $scheduled,
  unschedulable_true_conditions: $unschedulable,
  signal_status: (if $observed then "OBSERVED" else "UNPROVEN" end),
  signal_reason: (
    if not $stable then "PodGroupReadbackDrift"
    elif not $owned then "PodGroupOwnershipUnproven"
    elif $b.status.phase != "Running" then "PodGroupNotRunning"
    elif ($scheduled | length) != 1 or $scheduled[0].status != "True" then "ScheduledConditionUnproven"
    elif ($unschedulable | length) > 0 then "ConflictingUnschedulableCondition"
    elif (($b.status.running // 0) < ($b.spec.minMember // 1)) then "RunningCountUnproven"
    else "PinnedPodGroupScheduledStatusCorroborated"
    end
  ),
  quota_applied: "UNPROVEN",
  execution_ownership: "UNPROVEN",
  gpu_hardware: "UNPROVEN",
  production_promotion: "FORBIDDEN"
}
