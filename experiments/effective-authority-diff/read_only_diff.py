from __future__ import annotations

import json
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class Profile:
    coalitions: Mapping[str, tuple[tuple[str, ...], ...]]


def _namespace(obj: Mapping[str, Any]) -> str:
    return str(obj.get("metadata", {}).get("namespace") or "default")


def _load_k8s(files: Mapping[str, str]) -> tuple[dict[str, str], dict[str, set[str]]]:
    workloads: dict[str, str] = {}
    roles: dict[tuple[str, str, str], set[str]] = {}
    bindings: list[tuple[str, str, str, list[Mapping[str, Any]]]] = []

    for path, text in files.items():
        if not path.endswith((".yaml", ".yml")):
            continue
        try:
            docs = list(yaml.safe_load_all(text or ""))
        except yaml.YAMLError:
            continue
        for obj in docs:
            if not isinstance(obj, dict):
                continue
            kind = str(obj.get("kind") or "")
            ns = _namespace(obj)
            name = str(obj.get("metadata", {}).get("name") or "")
            if kind == "Deployment":
                sa = (
                    obj.get("spec", {})
                    .get("template", {})
                    .get("spec", {})
                    .get("serviceAccountName", "default")
                )
                workloads[f"k8s://{ns}/deployment/{name}"] = f"sa:{ns}/{sa}"
            elif kind in {"Role", "ClusterRole"}:
                key = (kind, ns if kind == "Role" else "*", name)
                outcomes: set[str] = set()
                for rule in obj.get("rules", []) or []:
                    resources = rule.get("resources", []) or []
                    verbs = rule.get("verbs", []) or []
                    names = rule.get("resourceNames") or ["*"]
                    for resource in resources:
                        for verb in verbs:
                            action = "read" if verb in {"get", "list", "watch"} else str(verb)
                            for scope in names:
                                outcomes.add(f"k8s.{action}.{resource}:{scope}")
                roles[key] = outcomes
            elif kind in {"RoleBinding", "ClusterRoleBinding"}:
                ref = obj.get("roleRef", {}) or {}
                ref_kind = str(ref.get("kind") or "")
                ref_name = str(ref.get("name") or "")
                ref_ns = ns if ref_kind == "Role" else "*"
                bindings.append((ref_kind, ref_ns, ref_name, obj.get("subjects", []) or []))

    grants: dict[str, set[str]] = defaultdict(set)
    for ref_kind, ref_ns, ref_name, subjects in bindings:
        role_outcomes = roles.get((ref_kind, ref_ns, ref_name), set())
        for subject in subjects:
            if subject.get("kind") != "ServiceAccount":
                continue
            sns = str(subject.get("namespace") or (ref_ns if ref_ns != "*" else "default"))
            sname = str(subject.get("name") or "")
            grants[f"sa:{sns}/{sname}"].update(role_outcomes)
    return workloads, grants


def _load_runs(files: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path, text in files.items():
        if not path.endswith(".json") or "runtime" not in path:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        runs = data.get("runs", []) if isinstance(data, dict) else []
        for run in runs:
            run_id = str(run.get("run_id") or "")
            binding = run.get("sandbox_binding") or {}
            sandbox_ref = str(binding.get("sandbox_ref") or "")
            if run_id and sandbox_ref:
                result[run_id] = sandbox_ref
    return result


def _server_outcomes(name: str, cfg: Mapping[str, Any]) -> set[str]:
    outcomes: set[str] = set()
    command = str(cfg.get("command") or "")
    args = [str(x) for x in (cfg.get("args") or [])]
    env = cfg.get("env") or {}
    env_values = (
        [str(k) for k in env] + [str(v) for v in env.values()]
        if isinstance(env, dict)
        else []
    )
    joined = " ".join([name, command, *args, *env_values]).lower()

    if "kubernetes" in joined or "kubectl" in joined:
        if "--read-only" in args:
            outcomes.add("mcp.kubernetes.read:*")
        else:
            outcomes.add("mcp.kubernetes.write:*")

    if any(path in joined for path in ("/etc", "/var/run/secrets", "/root")):
        outcomes.add("host.read.sensitive:*")

    enabled_tools = [str(x) for x in (cfg.get("enabled_tools") or cfg.get("enabledTools") or [])]
    if "agent-context" in joined:
        for tool in enabled_tools:
            if tool.startswith(("get_", "list_", "read_")):
                outcomes.add(f"mcp.agent-context.read:{tool}")
            else:
                outcomes.add(f"mcp.agent-context.write:{tool}")
    return outcomes


def _mcp_outcomes(text: str, suffix: str) -> set[str]:
    if not text:
        return set()
    try:
        if suffix == ".toml":
            data = tomllib.loads(text)
            servers = data.get("mcp_servers", {}) if isinstance(data, dict) else {}
        else:
            data = json.loads(text)
            servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, tomllib.TOMLDecodeError):
        return set()

    outcomes: set[str] = set()
    for name, cfg in servers.items():
        if isinstance(cfg, dict):
            outcomes.update(_server_outcomes(str(name), cfg))
    return outcomes


def _mcp_for_run(files: Mapping[str, str], run_id: str) -> set[str]:
    outcomes: set[str] = set()
    exact = (f"mcp.{run_id}.json", f"mcp.{run_id}.toml")
    found_specific = False
    for name in exact:
        if name in files:
            found_specific = True
            outcomes.update(_mcp_outcomes(files[name], "." + name.rsplit(".", 1)[-1]))
    if found_specific:
        return outcomes
    for name in ("mcp.json", "mcp.toml"):
        if name in files:
            outcomes.update(_mcp_outcomes(files[name], "." + name.rsplit(".", 1)[-1]))
    return outcomes


def _approval_required(files: Mapping[str, str]) -> bool:
    rego = "\n".join(
        text for path, text in sorted(files.items()) if path.endswith(".rego")
    )
    return bool(re.search(r"input\.(approved|approval)\s*(==\s*true)?", rego))


def _writeish(outcome: str) -> bool:
    return outcome.startswith((
        "k8s.delete.", "k8s.create.", "k8s.update.", "k8s.patch.",
        "k8s.impersonate.", "k8s.escalate.", "k8s.bind.",
        "mcp.kubernetes.write:", "mcp.agent-context.write:", "composite.",
    ))


def build_profile(files: Mapping[str, str]) -> Profile:
    workloads, grants = _load_k8s(files)
    runs = _load_runs(files)
    require_approval = _approval_required(files)
    by_outcome: dict[str, set[tuple[str, ...]]] = defaultdict(set)

    for run_id, sandbox_ref in runs.items():
        caps: set[str] = set()
        sa = workloads.get(sandbox_ref)
        if sa:
            caps.update(grants.get(sa, set()))
        caps.update(_mcp_for_run(files, run_id))

        if any(x.startswith("k8s.read.secrets:") for x in caps) and any(
            x.startswith("k8s.patch.deployments:") for x in caps
        ):
            caps.add("composite.secret_to_deployment:*")
        if "host.read.sensitive:*" in caps and any(
            x.startswith("k8s.patch.deployments:") for x in caps
        ):
            caps.add("composite.host_secret_to_deployment:*")
        if any(x.startswith("mcp.agent-context.write:") for x in caps) and any(
            x.startswith("k8s.patch.deployments:") for x in caps
        ):
            caps.add("composite.shared_context_to_deployment:*")

        for outcome in caps:
            coalition = (f"run:{run_id}",)
            if require_approval and _writeish(outcome):
                coalition = tuple(sorted((*coalition, "reviewer:approval")))
            by_outcome[outcome].add(coalition)

    frozen = {
        outcome: tuple(sorted(coalitions))
        for outcome, coalitions in sorted(by_outcome.items())
    }
    return Profile(coalitions=frozen)


def _split(outcome: str) -> tuple[str, str]:
    head, _, scope = outcome.partition(":")
    return head, scope or "*"


def _covers(before: str, after: str) -> bool:
    bh, bs = _split(before)
    ah, after_scope = _split(after)
    return bh == ah and (bs == "*" or bs == after_scope)


def diff_profiles(before: Profile, after: Profile) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    for outcome, after_coalitions in after.coalitions.items():
        covering = [
            (name, cols)
            for name, cols in before.coalitions.items()
            if _covers(name, outcome)
        ]
        if not covering:
            signals.append({"type": "OUTCOME_EXPANSION", "outcome": outcome})
            continue

        before_cols = set().union(*(set(cols) for _, cols in covering))
        before_min = min(len(c) for c in before_cols)
        after_min = min(len(c) for c in after_coalitions)
        if after_min < before_min:
            signals.append({
                "type": "AUTHORITY_CONCENTRATION",
                "outcome": outcome,
                "before_min_principals": before_min,
                "after_min_principals": after_min,
            })
            continue

        retained = any(c in after_coalitions for c in before_cols)
        added_minimal = [
            c for c in after_coalitions
            if len(c) == after_min and c not in before_cols
        ]
        if retained and added_minimal:
            signals.append({
                "type": "AUTHORITY_REPLICATION",
                "outcome": outcome,
                "added_coalitions": [list(c) for c in added_minimal],
            })

    return {
        "detected": bool(signals),
        "signals": signals,
        "before": {k: [list(c) for c in v] for k, v in before.coalitions.items()},
        "after": {k: [list(c) for c in v] for k, v in after.coalitions.items()},
    }
