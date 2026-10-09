#!/usr/bin/env bash
# Real disposable kind + Volcano v1.15.3 falsification. CPU only.
# Never infer production admission, GPU operation ownership, or release approval.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
out="$repo_root/artifacts/gpu-stage-b"
mkdir -p "$out"
gpu_sha="$(jq -r '.gpu_compute_platform.sha' gpu-stage-b-lock.json)"
volcano_sha="$(jq -r '.volcano.sha' gpu-stage-b-lock.json)"
chart_blob="$(jq -r '.volcano.queue_crd_blob_sha' gpu-stage-b-lock.json)"
test "$(git -C workspace/gpu rev-parse HEAD)" = "$gpu_sha"
test "$(git -C workspace/volcano rev-parse HEAD)" = "$volcano_sha"
chart="workspace/volcano/installer/helm/chart/volcano/crd/bases/scheduling.volcano.sh_queues.yaml"
test "$(git -C workspace/volcano hash-object "installer/helm/chart/volcano/crd/bases/scheduling.volcano.sh_queues.yaml")" = "$chart_blob"
test "$(kubectl config current-context)" = "kind-stageb-volcano"
kind get clusters | grep -Fx stageb-volcano

# The immutable schema digest was independently reviewed from the
# *previous* live v1.15.3 kind run #37918163882, not computed from the
# cluster currently under test. This test never self-blesses observed drift.
expected_digest="$(jq -r '.volcano.queue_crd_spec_sha256' gpu-stage-b-lock.json)"
[[ "$expected_digest" =~ ^[0-9a-f]{64}$ ]]
kubectl create --dry-run=client -f "$chart" -o json \
  | jq -Se '.spec | if has("conversion") then . else . + {"conversion":{"strategy":"None"}} end' \
  > "$out/pinned-source-queue-crd-spec.json"
sha256sum "$out/pinned-source-queue-crd-spec.json" > "$out/pinned-source-queue-crd-spec.sha256"
kubectl get crd queues.scheduling.volcano.sh -o json \
  | jq -Se '.spec' > "$out/live-queue-crd-spec.json"
sha256sum "$out/live-queue-crd-spec.json" > "$out/live-queue-crd-spec.sha256"
# Only the explicitly reviewed Kubernetes server-added conversion default is
# normalized; any other difference from the pinned chart or locked digest
# remains an unconditional failure BEFORE creating a Queue.
source_digest="$(sha256sum "$out/pinned-source-queue-crd-spec.json")"
source_digest="${source_digest%% *}"
live_digest="$(sha256sum "$out/live-queue-crd-spec.json")"
live_digest="${live_digest%% *}"
if [[ "$source_digest" != "$expected_digest" ||
      "$live_digest" != "$expected_digest" ]] ||
   ! cmp -s "$out/pinned-source-queue-crd-spec.json" "$out/live-queue-crd-spec.json"; then
  diff -u "$out/pinned-source-queue-crd-spec.json" "$out/live-queue-crd-spec.json" \
    > "$out/queue-crd-diff.txt" || true
  echo 'BLOCKED: installed CRD differs from independently locked persisted v1.15.3 schema' >&2
  exit 1
fi
mkdir -p "$out/queue-cas"
(
  cd workspace/gpu
  STAGE_B_EXPECTED_SHA="$gpu_sha" \
  STAGE_B_KIND_CONTEXT="kind-stageb-volcano" \
  STAGE_B_KIND_MUTATION_ACK=1 \
  STAGE_B_EXPECTED_QUEUE_CRD_SPEC_SHA256="$expected_digest" \
  STAGE_B_VOLCANO_API_EVIDENCE_DIR="$out/queue-cas" \
  bash scripts/e2e/volcano-queue-apiserver-contract.sh
) 2>&1 | tee "$out/queue-cas-result.log"
# Queue test must verify independent cleanup and never claim scheduler quota.
grep -Fx $'cleanup_observed_not_found\tPASS' "$out/queue-cas/gates.tsv"
grep -Fx $'quota_applied\tUNPROVEN' "$out/queue-cas/gates.tsv"

# CPU-only Job + controller-created Pod and PodGroup in an isolated namespace.
# Strictly bound to an ephemeral kind cluster, never a user/production context.
ns="stageb-proof-${GITHUB_RUN_ID:?}"
job="stageb-proof-job"
kubectl create namespace "$ns" -o json > "$out/namespace-created.json"
namespace_uid="$(jq -r '.metadata.uid' "$out/namespace-created.json")"
test -n "$namespace_uid" && test "$namespace_uid" != null
cleanup() {
  if [[ -z "${namespace_uid:-}" ]]; then return 0; fi
  kubectl get namespace "$ns" -o json > "$out/namespace-precleanup.json" 2>/dev/null || return 0
  if ! jq -e --arg uid "$namespace_uid" '.metadata.uid == $uid and .metadata.resourceVersion != null' "$out/namespace-precleanup.json" >/dev/null; then
    echo 'BLOCKED: namespace UID changed; refusing name-based delete' >&2
    return 1
  fi
  jq '{apiVersion:"meta.k8s.io/v1",kind:"DeleteOptions",preconditions:{uid:.metadata.uid,resourceVersion:.metadata.resourceVersion}}' \
    "$out/namespace-precleanup.json" > "$out/namespace-delete-options.json"
  kubectl delete --raw "/api/v1/namespaces/$ns" -f "$out/namespace-delete-options.json" > "$out/namespace-delete.json" || return 1
  kubectl wait --for=delete "namespace/$ns" --timeout=180s > "$out/namespace-cleanup-wait.txt" || return 1
}
trap cleanup EXIT

cat > "$out/probe-job.yaml" <<YAML
apiVersion: batch.volcano.sh/v1alpha1
kind: Job
metadata:
  name: $job
  namespace: $ns
spec:
  schedulerName: volcano
  queue: default
  minAvailable: 1
  tasks:
    - replicas: 1
      name: workload
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: sleeper
              image: busybox:1.36
              imagePullPolicy: IfNotPresent
              command: ["sh","-c","sleep 300"]
              resources:
                requests: {cpu: 50m, memory: 32Mi}
YAML
kubectl apply -f "$out/probe-job.yaml"
# Real scheduler/controller acceptance is a separate positive criterion.
kubectl -n "$ns" wait --for=jsonpath='{.status.state.phase}'=Running \
  "jobs.batch.volcano.sh/$job" --timeout=220s
kubectl -n "$ns" wait --for=condition=Ready \
  pods -l "volcano.sh/job-name=$job" --timeout=220s
kubectl -n "$ns" get "jobs.batch.volcano.sh/$job" -o json > "$out/job.json"
kubectl -n "$ns" get pods -l "volcano.sh/job-name=$job" -o json > "$out/pods.json"
jq -e '.items | length == 1' "$out/pods.json" >/dev/null
jq '.items[0]' "$out/pods.json" > "$out/pod.json"
job_uid="$(jq -r '.metadata.uid' "$out/job.json")"
pod_uid="$(jq -r '.metadata.uid' "$out/pod.json")"
test -n "$job_uid" && test -n "$pod_uid"
pg="$job-$job_uid"
kubectl -n "$ns" get podgroups.scheduling.volcano.sh "$pg" -o json > "$out/podgroup.json"
jq -e --arg uid "$job_uid" --arg ns "$ns" --arg job "$job" --arg pg "$pg" '
  .apiVersion == "v1" and .kind == "Pod" and
  .metadata.namespace == $ns and (.metadata.uid | length > 0) and
  (.metadata.resourceVersion | length > 0) and
  .metadata.labels["volcano.sh/job-name"] == $job and
  .metadata.labels["volcano.sh/job-namespace"] == $ns and
  .metadata.labels["volcano.sh/task-spec"] == "workload" and
  .metadata.labels["volcano.sh/task-index"] == "0" and
  .metadata.annotations["scheduling.k8s.io/group-name"] == $pg and
  any(.metadata.ownerReferences[]; .uid == $uid and .kind == "Job" and
      .apiVersion == "batch.volcano.sh/v1alpha1" and .controller == true) and
  .spec.schedulerName == "volcano" and (.spec.nodeName | length > 0) and
  .status.phase == "Running" and
  any(.status.conditions[]; .type == "Ready" and .status == "True")
' "$out/pod.json" >/dev/null
jq -e --arg pg "$pg" '
  .kind == "PodGroup" and .metadata.name == $pg and
  (.metadata.uid | length > 0) and
  (.metadata.resourceVersion | length > 0) and
  .spec.minMember == 1 and .status.phase == "Running"
' "$out/podgroup.json" >/dev/null

# Run the actual new Go observer against this real, UID-bound Kubernetes
# Job/PodGroup BEFORE our trap deletes the ephemeral namespace. This test has
# no write verbs and refuses all non-disposable cluster contexts.
(
  cd workspace/gpu
  STAGE_B_LIVE_PODGROUP_CONTEXT="kind-stageb-volcano" \
  STAGE_B_LIVE_PODGROUP_NAMESPACE="$ns" \
    go test ./internal/provider/volcano -run '^TestVolcanoLivePodGroupLinkReadOnly
printf 'gpu_sha\t%s\nvolcano_sha\t%s\nqueue_cas\tPASS\npodgroup_controller_evidence\tPASS\ngpu_hardware\tUNPROVEN\nquota_applied\tUNPROVEN\n' \
 "$gpu_sha" "$volcano_sha" > "$out/live-result.tsv"
sha256sum "$out/"*.json > "$out/live-receipts.sha256"
echo "STAGE B LIVE KIND PROOF: PASS (CPU-only; production promotion unproven)"
 -count=1 -v
) 2>&1 | tee "$out/live-podgroup-go-observer.log"
grep -Fq -- '--- PASS: TestVolcanoLivePodGroupLinkReadOnly' "$out/live-podgroup-go-observer.log"
grep -Fq 'LIVE_READ_ONLY_PODGROUP_LINK=PASS' "$out/live-podgroup-go-observer.log"
# No hardware GPU, no digest+cosign production claim, no quota-applied leap.
printf 'gpu_sha\t%s\nvolcano_sha\t%s\nqueue_cas\tPASS\npodgroup_controller_evidence\tPASS\ngpu_hardware\tUNPROVEN\nquota_applied\tUNPROVEN\n' \
 "$gpu_sha" "$volcano_sha" > "$out/live-result.tsv"
sha256sum "$out/"*.json > "$out/live-receipts.sha256"
echo "STAGE B LIVE KIND PROOF: PASS (CPU-only; production promotion unproven)"
