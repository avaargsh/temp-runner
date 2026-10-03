#!/usr/bin/env bash
set -euo pipefail

base=${1:?baseline directory required}
candidate=${2:?candidate directory required}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

diff -ru "$base" "$candidate" >"$work/diff.txt" || true
reasons=()

hit() {
  local reason=$1 pattern=$2
  if grep -Eq -- "$pattern" "$work/diff.txt"; then
    reasons+=("$reason")
  fi
}

# A deliberately stays in the "existing tools + small glue" class: textual
# diff plus narrow high-signal checks. It does not build a cross-domain graph.
hit "risky-rbac-verb-added" '^\+[^+].*verbs:.*(delete|create|update|patch|impersonate|escalate|bind|\*)'
hit "resource-scope-widened" '^-[^-].*resourceNames:'
hit "approval-predicate-removed" '^-[^-].*(input\.approved|input\.approval)'
hit "mcp-read-only-removed" '^-[^-].*--read-only'
hit "workload-serviceaccount-changed" '^\+[^+].*serviceAccountName:'
hit "binding-subject-name-changed" '^\+[^+].*subjects:.*name:'
hit "sensitive-mcp-path-added" '^\+[^+].*(/etc|/var/run/secrets|/root)'

if ((${#reasons[@]})); then
  printf 'DETECTED\n'
  printf '%s\n' "${reasons[@]}"
  exit 10
fi
printf 'CLEAR\n'
