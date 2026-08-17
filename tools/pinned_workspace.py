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
import urllib.error
import urllib.request
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/repositories.yaml"
COMMIT_LENGTH = 40


class WorkspaceError(RuntimeError):
    """A child repository could not be materialized at its pinned commit."""


def _redacted(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


def _run(args: list[str], cwd: Path | None = None, token: str | None = None) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = _redacted(result.stderr.strip(), token) or "no stderr"
        raise WorkspaceError(f"git {args[1]} failed for {cwd or args[-1]}: {detail}")


def _authenticated(url: str, token: str | None) -> str:
    if not token or not url.startswith("https://github.com/"):
        return url
    return url.replace("https://", f"https://x-access-token:{token}@", 1)


def _api_visibility(full_name: str, token: str) -> str:
    """Ask GitHub directly whether this credential can see the repository.

    A failed clone cannot tell a missing permission apart from a remote URL the
    server reads differently, so the report states which one it is.
    """
    def status(path: str) -> int | str:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{full_name}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except OSError:
            return "unreachable"

    # Selecting the repository grants metadata, which answers the first call. Cloning
    # needs the Contents permission, which is a separate grant and answers the second.
    metadata = status("")
    contents = status("/contents/")
    if metadata == 200 and contents != 200:
        return f"repository selected, but Contents permission missing (metadata {metadata}, contents {contents})"
    return f"metadata {metadata}, contents {contents}"


def _unreachable(manifest: dict, token: str | None) -> list[str]:
    """Name every repository the credential cannot read, not just the first one.

    Only runs when a token is supplied. Without one the caller is relying on an
    ambient credential helper, and probing every remote would put the network in
    the path of offline callers.
    """
    if not token:
        return []
    denied = []
    for repository in manifest["repositories"]:
        probe = subprocess.run(
            ["git", "ls-remote", "--exit-code", "-h", _authenticated(repository["url"], token)],
            capture_output=True, text=True,
        )
        if probe.returncode != 0:
            denied.append(f"{repository['full_name']} ({_api_visibility(repository['full_name'], token)})")
    return denied


def materialize(output: Path, token: str | None) -> list[tuple[str, str]]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    denied = _unreachable(manifest, token)
    if denied:
        raise WorkspaceError(
            "the credential cannot read: " + ", ".join(denied)
            + " — grant the token Contents:Read-only on every manifest repository"
        )
    output.mkdir(parents=True, exist_ok=True)
    materialized: list[tuple[str, str]] = []
    for repository in manifest["repositories"]:
        commit = repository["observed_commit"]
        if not isinstance(commit, str) or len(commit) != COMMIT_LENGTH:
            raise WorkspaceError(f"{repository['id']} has no 40-character observed_commit")
        destination = output / repository["path"]
        if destination.exists():
            raise WorkspaceError(f"{destination} already exists; use an empty output directory")
        _run(["git", "clone", "--quiet", _authenticated(repository["url"], token), str(destination)], token=token)
        _run(["git", "checkout", "--quiet", commit], cwd=destination, token=token)
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
