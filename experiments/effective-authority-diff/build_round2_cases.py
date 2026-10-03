from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump_docs(*docs: dict[str, Any]) -> str:
    return yaml.safe_dump_all(docs, sort_keys=False)


def runtime(*runs: dict[str, Any]) -> str:
    return json.dumps({"runs": list(runs)}, indent=2) + "\n"


def run(run_id: str, sandbox_ref: str, *, sandbox_id: str = "sb-1", revision: int = 1, **extra: Any) -> dict[str, Any]:
    binding = {
        "provider": "kubernetes",
        "sandbox_id": sandbox_id,
        "sandbox_ref": sandbox_ref,
        "revision": revision,
    }
    binding.update(extra)
    return {
        "run_id": run_id,
        "session_id": "golden-demo",
        "sandbox_binding": binding,
    }


def role(*, resource_names: list[str] | None = None) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "apiGroups": ["apps"],
        "resources": ["deployments"],
        "verbs": ["patch"],
    }
    if resource_names is not None:
        rule["resourceNames"] = resource_names
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": {"name": "checkout-writer", "namespace": "golden-demo"},
        "rules": [rule],
    }


def binding() -> dict[str, Any]:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": "checkout-writer", "namespace": "golden-demo"},
        "subjects": [
            {"kind": "ServiceAccount", "name": "checkout-writer", "namespace": "golden-demo"}
        ],
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": "checkout-writer",
        },
    }


def deployment(documents: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for obj in documents:
        if (
            isinstance(obj, dict)
            and obj.get("kind") == "Deployment"
            and obj.get("metadata", {}).get("name") == name
        ):
            return copy.deepcopy(obj)
    raise SystemExit(f"deployment not found in golden stack: {name}")


def with_service_account(obj: dict[str, Any], name: str) -> dict[str, Any]:
    obj = copy.deepcopy(obj)
    obj["spec"]["template"]["spec"]["serviceAccountName"] = name
    return obj


def with_image(obj: dict[str, Any], image: str) -> dict[str, Any]:
    obj = copy.deepcopy(obj)
    obj["spec"]["template"]["spec"]["containers"][0]["image"] = image
    return obj


def read_source(workspace: Path, lock: dict[str, Any], key: str, path: str) -> tuple[str, dict[str, str]]:
    repo_root = workspace / key
    text = (repo_root / path).read_text(encoding="utf-8")
    entry = lock["repositories"][key]
    return text, {
        "repository": entry["repository"],
        "commit": entry["sha"],
        "path": path,
        "file_digest": sha256_text(text),
    }


def readonly_codex(text: str) -> str:
    keep = {
        "get_work",
        "get_changes_since",
        "get_context_overlay",
        "get_context_changes_since",
    }
    lines = text.splitlines()
    out: list[str] = []
    in_tools = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("enabled_tools") and stripped.endswith("["):
            in_tools = True
            out.append(line)
            continue
        if in_tools:
            if stripped == "]":
                in_tools = False
                out.append(line)
                continue
            quoted = stripped.strip(",").strip('"')
            if quoted in keep:
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--source-lock", default="authority-diff-lock.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    lock = json.loads(Path(args.source_lock).read_text(encoding="utf-8"))

    golden_text, golden_src = read_source(
        workspace, lock, "agentic-aiops", "demo/k8s/golden-stack.yaml"
    )
    codex_text, codex_src = read_source(
        workspace, lock, "agent-control-plane", "examples/cross_agent_context/codex.config.toml"
    )
    claude_text, claude_src = read_source(
        workspace, lock, "agent-control-plane", "examples/cross_agent_context/claude.mcp.json"
    )
    _, runtime_src = read_source(
        workspace, lock, "cloud-agent-runtime", "src/cloud_agent_runtime/models.py"
    )
    _, recovery_src = read_source(
        workspace, lock, "cloud-agent-runtime", "tests/test_sandbox_recovery.py"
    )

    docs = [x for x in yaml.safe_load_all(golden_text) if isinstance(x, dict)]
    checkout_real = deployment(docs, "checkout-api")
    prometheus_real = deployment(docs, "prometheus")
    checkout_writer = with_service_account(checkout_real, "checkout-writer")
    writer_role = role()
    writer_binding = binding()
    checkout_ref = "k8s://golden-demo/deployment/checkout-api"
    prometheus_ref = "k8s://golden-demo/deployment/prometheus"

    claude_sensitive = json.loads(claude_text)
    claude_sensitive["mcpServers"]["agent-context"]["env"]["AGENT_CONTEXT_DB"] = "/etc/agent-context/shared-context.db"
    claude_sensitive_text = json.dumps(claude_sensitive, indent=2) + "\n"

    policy_before = """package agent.authz
default allow := false
allow if {
  input.action == "patch"
  input.approved == true
}
"""
    policy_after = """package agent.authz
default allow := false
allow if {
  input.action == "patch"
}
"""

    sources_common = [golden_src, runtime_src]
    cases = [
        {
            "id": "r2-golden-workload-joins-existing-writer-sa",
            "expected": "dangerous",
            "note": "Real checkout-api Deployment gains a service account that already owns patch authority.",
            "source": sources_common,
            "baseline": {
                "k8s.yaml": dump_docs(checkout_real, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
            },
            "candidate": {
                "k8s.yaml": dump_docs(checkout_writer, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
            },
        },
        {
            "id": "r2-runtime-rebind-joins-writer-workload",
            "expected": "dangerous",
            "note": "Kubernetes facts stay fixed; only Run/SandboxBinding moves from Prometheus to the writer workload.",
            "source": sources_common + [recovery_src],
            "baseline": {
                "k8s.yaml": dump_docs(checkout_writer, prometheus_real, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", prometheus_ref)),
            },
            "candidate": {
                "k8s.yaml": dump_docs(checkout_writer, prometheus_real, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref, revision=2, previous_refs=[prometheus_ref])),
            },
        },
        {
            "id": "r2-codex-enabled-tools-expand",
            "expected": "dangerous",
            "note": "Candidate uses the real Codex MCP config; baseline retains only its explicit read tools.",
            "source": [codex_src, runtime_src],
            "baseline": {
                "runtime.json": runtime(run("run-main", checkout_ref)),
                "mcp.run-main.toml": readonly_codex(codex_text),
            },
            "candidate": {
                "runtime.json": runtime(run("run-main", checkout_ref)),
                "mcp.run-main.toml": codex_text,
            },
        },
        {
            "id": "r2-canonical-run-authority-replication",
            "expected": "dangerous",
            "note": "A second canonical Run receives the same real agent-context MCP authority.",
            "source": [codex_src, runtime_src],
            "baseline": {
                "runtime.json": runtime(run("run-main", checkout_ref)),
                "mcp.run-main.toml": codex_text,
            },
            "candidate": {
                "runtime.json": runtime(
                    run("run-main", checkout_ref),
                    run("run-child", checkout_ref, sandbox_id="sb-2"),
                ),
                "mcp.run-main.toml": codex_text,
                "mcp.run-child.toml": codex_text,
            },
        },
        {
            "id": "r2-approval-coalition-concentration",
            "expected": "dangerous",
            "note": "Writer outcome remains the same while the explicit approval principal disappears.",
            "source": sources_common,
            "baseline": {
                "k8s.yaml": dump_docs(checkout_writer, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
                "policy.rego": policy_before,
            },
            "candidate": {
                "k8s.yaml": dump_docs(checkout_writer, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
                "policy.rego": policy_after,
            },
        },
        {
            "id": "r2-shared-context-plus-k8s-write-composition",
            "expected": "dangerous",
            "note": "Real Codex agent-context tools become co-located with Kubernetes patch authority only through runtime rebinding.",
            "source": [golden_src, codex_src, runtime_src, recovery_src],
            "baseline": {
                "k8s.yaml": dump_docs(checkout_writer, prometheus_real, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", prometheus_ref)),
                "mcp.run-main.toml": codex_text,
            },
            "candidate": {
                "k8s.yaml": dump_docs(checkout_writer, prometheus_real, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref, revision=2, previous_refs=[prometheus_ref])),
                "mcp.run-main.toml": codex_text,
            },
        },
        {
            "id": "r2-real-mcp-sensitive-path-composition",
            "expected": "dangerous",
            "note": "Real Claude MCP config is changed so its shared context DB sits under /etc while the Run owns deployment patch authority.",
            "source": [golden_src, claude_src, runtime_src],
            "baseline": {
                "k8s.yaml": dump_docs(checkout_writer, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
                "mcp.run-main.json": claude_text,
            },
            "candidate": {
                "k8s.yaml": dump_docs(checkout_writer, writer_role, writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
                "mcp.run-main.json": claude_sensitive_text,
            },
        },
        {
            "id": "r2-real-checkout-resource-scope-widen",
            "expected": "dangerous",
            "note": "Role changes from the real checkout-api name to all deployments without changing the workload.",
            "source": sources_common,
            "baseline": {
                "k8s.yaml": dump_docs(checkout_writer, role(resource_names=["checkout-api"]), writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
            },
            "candidate": {
                "k8s.yaml": dump_docs(checkout_writer, role(resource_names=None), writer_binding),
                "runtime.json": runtime(run("run-main", checkout_ref)),
            },
        },
        {
            "id": "r2-recovery-physical-sandbox-rotation-benign",
            "expected": "benign",
            "note": "Matches cloud-agent-runtime recovery semantics: physical sandbox/revision changes but canonical sandbox_ref is stable.",
            "source": [runtime_src, recovery_src],
            "baseline": {
                "runtime.json": runtime(run("run-main", checkout_ref, sandbox_id="physical-a", revision=1)),
            },
            "candidate": {
                "runtime.json": runtime(
                    run(
                        "run-main",
                        checkout_ref,
                        sandbox_id="physical-b",
                        revision=2,
                        previous_refs=["sandbox://physical-a"],
                    )
                ),
            },
        },
        {
            "id": "r2-golden-image-only-change-benign",
            "expected": "benign",
            "note": "Real checkout-api manifest changes image identity only; authority-bearing workload identity is unchanged.",
            "source": [golden_src, runtime_src],
            "baseline": {
                "k8s.yaml": dump_docs(checkout_real),
                "runtime.json": runtime(run("run-main", checkout_ref)),
            },
            "candidate": {
                "k8s.yaml": dump_docs(with_image(checkout_real, "python:3.12.12-slim")),
                "runtime.json": runtime(run("run-main", checkout_ref)),
            },
        },
    ]

    suite = {
        "schema_version": 1,
        "round": 2,
        "construction": "derived deterministically from pinned real repository files",
        "cases": cases,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(suite, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
