"""Synthetic, read-only cross-principal delegation boundary falsification probe.

This is an experiment: it is not an authorization service, signing scheme,
identity provider, or enforcement point. All principals, grants, and data are
synthetic, with externally authenticated facts assumed by the test fixture.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NOW = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def block(reason: str) -> dict[str, Any]:
    return {"decision": "BLOCK", "reason": reason, "projection": {}}


def _names(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x for x in value) and len(set(value)) == len(value)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def evaluate(
    request: dict[str, Any],
    grant: dict[str, Any] | None,
    resource: dict[str, Any],
    *,
    authenticated_principal: str,
    now: datetime,
) -> dict[str, Any]:
    """Evaluate fixed, trusted facts; return only a narrowly projected result.

    An actual deployment must authenticate the principal and verify the grant,
    revocation, membership and consumption data at an atomic execution fence.
    """
    request_keys = {
        "request_id", "requester", "grant_id", "resource_id", "operation",
        "purpose", "audience", "requested_fields", "expected_authority_generation",
    }
    grant_keys = {
        "grant_id", "issuer", "grantee", "resource_id", "operation", "purpose",
        "audience", "fields", "authority_generation", "expires_at",
    }
    resource_keys = {
        "owner", "resource_id", "authority_generation", "audience_members",
        "revoked_grants", "consumed_grants", "data_fields",
    }
    if not isinstance(request, dict) or set(request) != request_keys:
        return block("INVALID_REQUEST")
    if grant is None:
        return block("NO_GRANT")
    if not isinstance(grant, dict) or set(grant) != grant_keys:
        return block("INVALID_GRANT")
    if not isinstance(resource, dict) or set(resource) != resource_keys:
        return block("INVALID_RESOURCE_FACTS")
    if not isinstance(authenticated_principal, str) or not authenticated_principal:
        return block("UNAUTHENTICATED")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return block("INVALID_CLOCK")
    text_keys = ("request_id", "requester", "grant_id", "resource_id", "operation", "purpose", "audience")
    if any(not isinstance(request.get(k), str) or not request[k] for k in text_keys):
        return block("INVALID_REQUEST")
    grant_text_keys = ("grant_id", "issuer", "grantee", "resource_id", "operation", "purpose", "audience")
    if any(not isinstance(grant.get(k), str) or not grant[k] for k in grant_text_keys):
        return block("INVALID_GRANT")
    if not _names(request["requested_fields"]) or not _names(grant["fields"]):
        return block("INVALID_FIELDS")
    versions = (request["expected_authority_generation"], grant["authority_generation"], resource["authority_generation"])
    if any(type(v) is not int or v < 1 for v in versions):
        return block("INVALID_GENERATION")
    if not isinstance(resource["owner"], str) or not resource["owner"]:
        return block("INVALID_RESOURCE_FACTS")
    if not isinstance(resource["resource_id"], str) or not resource["resource_id"]:
        return block("INVALID_RESOURCE_FACTS")
    if any(not isinstance(resource[k], list) or any(not isinstance(x, str) for x in resource[k]) for k in ("audience_members", "revoked_grants", "consumed_grants")):
        return block("INVALID_RESOURCE_FACTS")
    if not isinstance(resource["data_fields"], dict) or any(not isinstance(k, str) for k in resource["data_fields"]):
        return block("INVALID_RESOURCE_FACTS")
    expiry = _timestamp(grant["expires_at"])
    if expiry is None:
        return block("INVALID_EXPIRY")
    if request["requester"] != authenticated_principal:
        return block("REQUESTER_NOT_AUTHENTICATED_PRINCIPAL")
    if grant["grantee"] != authenticated_principal:
        return block("WRONG_GRANTEE")
    if grant["issuer"] != resource["owner"]:
        return block("WRONG_OWNER")
    if request["grant_id"] != grant["grant_id"]:
        return block("GRANT_ID_MISMATCH")
    if grant["grant_id"] in resource["revoked_grants"]:
        return block("GRANT_REVOKED")
    if grant["grant_id"] in resource["consumed_grants"]:
        return block("GRANT_REPLAY")
    if not (request["expected_authority_generation"] == grant["authority_generation"] == resource["authority_generation"]):
        return block("STALE_AUTHORITY")
    if now >= expiry:
        return block("GRANT_EXPIRED")
    if request["resource_id"] != grant["resource_id"] or grant["resource_id"] != resource["resource_id"]:
        return block("RESOURCE_MISMATCH")
    if request["operation"] != grant["operation"]:
        return block("OPERATION_MISMATCH")
    if request["purpose"] != grant["purpose"]:
        return block("PURPOSE_MISMATCH")
    if request["audience"] != grant["audience"]:
        return block("AUDIENCE_MISMATCH")
    if authenticated_principal not in resource["audience_members"]:
        return block("REQUESTER_NOT_IN_AUDIENCE")
    if resource["owner"] not in resource["audience_members"]:
        return block("OWNER_NOT_IN_AUDIENCE")
    if not set(request["requested_fields"]).issubset(grant["fields"]):
        return block("FIELD_SCOPE_EXCEEDED")
    if not set(request["requested_fields"]).issubset(resource["data_fields"]):
        return block("FIELD_MISSING")
    projection = {name: resource["data_fields"][name] for name in request["requested_fields"]}
    return {"decision": "ALLOW", "reason": "BOUND_GRANT", "projection": projection}


def fixtures() -> list[dict[str, Any]]:
    """Frozen synthetic fixture matrix. Every counterexample must fail closed."""
    request = {
        "request_id": "req-meeting-01", "requester": "agent:alice", "grant_id": "grant-01",
        "resource_id": "calendar:bob", "operation": "availability.query",
        "purpose": "schedule_meeting", "audience": "group:planning",
        "requested_fields": ["free_slots"], "expected_authority_generation": 3,
    }
    grant = {
        "grant_id": "grant-01", "issuer": "user:bob", "grantee": "agent:alice",
        "resource_id": "calendar:bob", "operation": "availability.query",
        "purpose": "schedule_meeting", "audience": "group:planning",
        "fields": ["free_slots"], "authority_generation": 3,
        "expires_at": "2026-10-07T00:05:00+00:00",
    }
    resource = {
        "owner": "user:bob", "resource_id": "calendar:bob", "authority_generation": 3,
        "audience_members": ["user:bob", "agent:alice"],
        "revoked_grants": [], "consumed_grants": [],
        "data_fields": {"free_slots": ["10:00", "11:00"], "private_notes": "secret-do-not-release"},
    }
    cases: list[dict[str, Any]] = []

    def case(name: str, reason: str, *, req: dict | None = None, auth: dict | None = None, facts: dict | None = None, principal: str = "agent:alice", at: datetime = NOW) -> None:
        cases.append({"name": name, "expected_reason": reason, "request": copy.deepcopy(request if req is None else req), "grant": copy.deepcopy(grant if auth is None else auth), "resource": copy.deepcopy(resource if facts is None else facts), "principal": principal, "now": at})

    def changed(base: dict, **updates: Any) -> dict:
        return {**base, **updates}

    case("scoped_availability", "BOUND_GRANT")
    case("no_grant", "NO_GRANT")
    cases[-1]["grant"] = None
    case("principal_spoof", "REQUESTER_NOT_AUTHENTICATED_PRINCIPAL", principal="agent:eve")
    case("grantee_mismatch", "WRONG_GRANTEE", auth=changed(grant, grantee="agent:eve"))
    case("issuer_not_owner", "WRONG_OWNER", auth=changed(grant, issuer="user:eve"))
    case("wrong_grant", "GRANT_ID_MISMATCH", req=changed(request, grant_id="grant-old"))
    case("revoked", "GRANT_REVOKED", facts=changed(resource, revoked_grants=["grant-01"]))
    case("replay", "GRANT_REPLAY", facts=changed(resource, consumed_grants=["grant-01"]))
    case("stale_generation", "STALE_AUTHORITY", facts=changed(resource, authority_generation=4))
    case("expired", "GRANT_EXPIRED", at=datetime(2026, 10, 7, 0, 5, tzinfo=timezone.utc))
    case("wrong_resource", "RESOURCE_MISMATCH", req=changed(request, resource_id="calendar:eve"))
    case("operation_escalation", "OPERATION_MISMATCH", req=changed(request, operation="calendar.write"))
    case("purpose_drift", "PURPOSE_MISMATCH", req=changed(request, purpose="marketing"))
    case("audience_changed", "AUDIENCE_MISMATCH", req=changed(request, audience="group:public"))
    case("member_removed", "REQUESTER_NOT_IN_AUDIENCE", facts=changed(resource, audience_members=["user:bob"]))
    case("owner_left_group", "OWNER_NOT_IN_AUDIENCE", facts=changed(resource, audience_members=["agent:alice"]))
    case("private_field", "FIELD_SCOPE_EXCEEDED", req=changed(request, requested_fields=["free_slots", "private_notes"]))
    case("unknown_field", "FIELD_MISSING", req=changed(request, requested_fields=["unknown"]), auth=changed(grant, fields=["unknown"]))
    case("invalid_expiry", "INVALID_EXPIRY", auth=changed(grant, expires_at="tomorrow"))
    case("invalid_fields", "INVALID_FIELDS", req=changed(request, requested_fields=["free_slots", "free_slots"]))
    case("unknown_request_property", "INVALID_REQUEST", req=changed(request, execute_anyway=True))
    return cases


def build_report() -> dict[str, Any]:
    outcome = []
    for entry in fixtures():
        result = evaluate(entry["request"], entry["grant"], entry["resource"], authenticated_principal=entry["principal"], now=entry["now"])
        expected = entry["expected_reason"]
        passed = result["reason"] == expected and (result["decision"] == "ALLOW") == (expected == "BOUND_GRANT")
        # Keep synthetic private data out of the artifact, even for the positive case.
        outcome.append({"case": entry["name"], "expected_reason": expected, "actual_reason": result["reason"], "decision": result["decision"], "projection_fields": sorted(result["projection"]), "passed": passed})
    artifact = {
        "schema_version": 1, "kind": "CrossPrincipalDelegationProbe",
        "mode": "read-only", "fixture_time": NOW.isoformat(),
        "limitations": "synthetic facts only; no trusted identity/grant/atomic replay enforcement",
        "summary": {"passed": sum(int(x["passed"]) for x in outcome), "total": len(outcome)},
        "cases": outcome,
    }
    artifact["content_digest"] = sha256(artifact)
    return artifact


def verify(artifact: dict[str, Any], trusted_digest: str) -> None:
    if artifact.get("kind") != "CrossPrincipalDelegationProbe" or artifact.get("schema_version") != 1 or artifact.get("mode") != "read-only":
        raise ValueError("unsupported delegation probe artifact")
    body = dict(artifact)
    embedded = body.pop("content_digest", None)
    if embedded != trusted_digest or sha256(body) != trusted_digest:
        raise ValueError("delegation artifact digest mismatch")
    cases = artifact.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("empty delegation probe")
    if artifact.get("summary") != {"passed": len(cases), "total": len(cases)} or any(x.get("passed") is not True for x in cases):
        raise ValueError("delegation probe did not pass all cases")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("artifacts/delegation-boundary/probe.json"))
    parser.add_argument("--verify", type=Path, help="Verify an existing probe instead of generating one")
    parser.add_argument("--sha-file", type=Path, help="Trusted digest file for --verify; bind this digest outside the artifact in production")
    args = parser.parse_args()
    if args.verify:
        if args.sha_file is None:
            parser.error("--verify requires --sha-file")
        digest = args.sha_file.read_text(encoding="utf-8").strip()
        artifact = json.loads(args.verify.read_text(encoding="utf-8"))
        verify(artifact, digest)
        print(f"delegation probe verified: {artifact['summary']['total']} cases")
    else:
        artifact = build_report()
        verify(artifact, artifact["content_digest"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        args.out.with_suffix(args.out.suffix + ".sha256").write_text(artifact["content_digest"] + "\n", encoding="utf-8")
        print(f"delegation probe: {artifact['summary']['passed']}/{artifact['summary']['total']} PASS; {artifact['content_digest']}")


if __name__ == "__main__":
    main()
