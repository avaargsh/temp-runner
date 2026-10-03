from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = {
    "agent-control-plane": "control_plane_ref",
    "cloud-agent-runtime": "runtime_ref",
    "agentic-aiops": "aiops_ref",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default="authority-diff-lock.json")
    parser.add_argument("--github-output")
    args = parser.parse_args()
    data = json.loads(Path(args.lock).read_text())
    if data.get("schema_version") != 1:
        raise SystemExit("unsupported authority-diff-lock schema_version")
    repos = data.get("repositories") or {}
    lines = []
    for name, output_name in _REQUIRED.items():
        entry = repos.get(name) or {}
        if entry.get("repository") != f"avaargsh/{name}":
            raise SystemExit(f"repository mismatch for {name}")
        sha = entry.get("sha")
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise SystemExit(f"invalid sha for {name}")
        lines.append(f"{output_name}={sha}")
    if args.github_output:
        with Path(args.github_output).open("a") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
