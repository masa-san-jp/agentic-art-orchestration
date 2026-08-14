#!/usr/bin/env python3
"""Materialize a Git-external workspace with every child at its manifest pin.

    python3 tools/pinned_workspace.py --output /tmp/pinned

Reads `config/repositories.yaml` and clones each declared repository, then checks
out its `observed_commit`. `tools/production_exchange.py` requires HEAD to equal
that commit exactly, so this is the only supported way to run the exchange
against the real children instead of the offline fixture mirror.

Authentication comes from `CHILD_REPOS_TOKEN` (a read-only fine-grained token).
The token is injected per invocation and never written to disk or logged.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/repositories.yaml"
COMMIT_LENGTH = 40


class WorkspaceError(RuntimeError):
    """A child repository could not be materialized at its pinned commit."""


def _run(args: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        # stderr can contain the tokenized remote; report the operation only.
        raise WorkspaceError(f"git {args[1]} failed for {cwd or args[-1]}")


def _authenticated(url: str, token: str | None) -> str:
    if not token or not url.startswith("https://github.com/"):
        return url
    return url.replace("https://", f"https://x-access-token:{token}@", 1)


def materialize(output: Path, token: str | None) -> list[tuple[str, str]]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    materialized: list[tuple[str, str]] = []
    for repository in manifest["repositories"]:
        commit = repository["observed_commit"]
        if not isinstance(commit, str) or len(commit) != COMMIT_LENGTH:
            raise WorkspaceError(f"{repository['id']} has no 40-character observed_commit")
        destination = output / repository["path"]
        if destination.exists():
            raise WorkspaceError(f"{destination} already exists; use an empty output directory")
        _run(["git", "clone", "--quiet", _authenticated(repository["url"], token), str(destination)])
        _run(["git", "checkout", "--quiet", commit], cwd=destination)
        # Drop the tokenized remote so no later command can leak it.
        _run(["git", "remote", "set-url", "origin", repository["url"]], cwd=destination)
        materialized.append((repository["id"], commit))
    return materialized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="empty directory outside this repository")
    args = parser.parse_args(argv)
    try:
        materialized = materialize(args.output, os.environ.get("CHILD_REPOS_TOKEN"))
    except (WorkspaceError, OSError, yaml.YAMLError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    for identifier, commit in materialized:
        print(f"{identifier} {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
