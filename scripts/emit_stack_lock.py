from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = {
    "agentic-aiops": "aiops_ref",
    "agent-decision-lab": "decision_ref",
    "cloud-agent-runtime": "runtime_ref",
    "agent-control-plane": "control_plane_ref",
}


def load_lock(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1:
        raise SystemExit("unsupported stack-lock schema_version")
    repositories = data.get("repositories")
    if not isinstance(repositories, dict):
        raise SystemExit("stack-lock repositories must be an object")

    for name, output_name in _REQUIRED.items():
        entry = repositories.get(name)
        if not isinstance(entry, dict):
            raise SystemExit(f"missing stack-lock repository: {name}")
        expected_repo = f"avaargsh/{name}"
        if entry.get("repository") != expected_repo:
            raise SystemExit(
                f"{name} repository mismatch: {entry.get('repository')!r}"
            )
        sha = entry.get("sha")
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise SystemExit(f"{name} sha must be 40 lowercase hex characters")
        entry["output_name"] = output_name
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default="stack-lock.json")
    parser.add_argument("--github-output")
    args = parser.parse_args()

    data = load_lock(Path(args.lock))
    lines = []
    for name in _REQUIRED:
        entry = data["repositories"][name]
        lines.append(f"{entry['output_name']}={entry['sha']}")

    if args.github_output:
        with Path(args.github_output).open("a") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
