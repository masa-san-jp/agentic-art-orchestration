#!/usr/bin/env python3
"""Materialize a Git-external workspace with every child at its manifest pin.

    python3 tools/pinned_workspace.py --output /tmp/pinned

Reads `config/repositories.yaml` and clones each selected repository, then checks
out its `observed_commit`. By default every declared repository is selected;
callers with a narrower contract can repeat `--repository` to select only the
required children. `tools/production_exchange.py` requires HEAD to equal that
commit exactly, so this is the only supported way to run the exchange against
the real children instead of the offline fixture mirror.

Authentication comes from `CHILD_REPOS_TOKEN` (a read-only fine-grained token).
The token is injected per invocation and never written to disk or logged.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import urllib.error
import urllib.request
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/repositories.yaml"
COMMIT_LENGTH = 40
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class WorkspaceError(RuntimeError):
    """A child repository could not be materialized at its pinned commit."""


def _redacted(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


# actions/checkout leaves an Authorization header in the checked-out repository's
# config. Any git command run from inside that checkout inherits it, and that header
# carries the workflow's own token, which can only read this repository. It silently
# replaces the credential in our remote URL, so every other repository is refused.
NO_INHERITED_AUTH = ["-c", "http.https://github.com/.extraheader="]


def _run(args: list[str], cwd: Path | None = None, token: str | None = None) -> None:
    result = subprocess.run([args[0], *NO_INHERITED_AUTH, *args[1:]], cwd=cwd, capture_output=True, text=True)
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
    """Name every selected repository the credential cannot read, not just the first one.

    Only runs when a token is supplied. Without one the caller is relying on an
    ambient credential helper, and probing every remote would put the network in
    the path of offline callers.
    """
    if not token:
        return []
    denied = []
    for repository in manifest["repositories"]:
        probe = subprocess.run(
            ["git", *NO_INHERITED_AUTH, "ls-remote", "--exit-code", "-h", _authenticated(repository["url"], token)],
            capture_output=True, text=True,
        )
        if probe.returncode != 0:
            denied.append(f"{repository['full_name']} ({_api_visibility(repository['full_name'], token)})")
    return denied


def _selected_repositories(manifest: dict[str, Any], repository_ids: list[str] | None) -> list[dict[str, Any]]:
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise WorkspaceError("manifest has no repositories")
    if repository_ids is None:
        return repositories
    requested = set(repository_ids)
    known = {repository.get("id") for repository in repositories}
    unknown = sorted(requested - known)
    if not requested:
        raise WorkspaceError("--repository requires at least one repository id")
    if unknown:
        raise WorkspaceError("unknown repository id(s): " + ", ".join(unknown))
    return [repository for repository in repositories if repository.get("id") in requested]


def materialize(
    output: Path,
    token: str | None,
    repository_ids: list[str] | None = None,
) -> list[tuple[str, str]]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    selected = _selected_repositories(manifest, repository_ids)
    denied = _unreachable({"repositories": selected}, token)
    if denied:
        raise WorkspaceError(
            "the credential cannot read: " + ", ".join(denied)
            + " — grant the token Contents:Read-only on every selected manifest repository"
        )
    output.mkdir(parents=True, exist_ok=True)
    materialized: list[tuple[str, str]] = []
    for repository in selected:
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


class PinnedWorkspaceError(RuntimeError):
    """A local pinned workspace could not be materialized safely."""

    def __init__(self, message: str, findings: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.findings = findings or []


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _source_observation(root: Path, observed_commit: str, repository_id: str) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    source_head = head.stdout.strip() if head.returncode == 0 else None
    if source_head is None:
        state = "UNAVAILABLE"
    elif dirty.stdout.strip():
        state = "DIRTY"
    elif not branch.stdout.strip():
        state = "DETACHED"
    elif source_head == observed_commit:
        state = "MATCHED"
    else:
        state = "STALE"
    return {
        "repository": repository_id,
        "observed_commit": observed_commit,
        "source_head": source_head,
        "source_state": state,
        "materialized_commit": observed_commit,
        "materialized_state": "MATCHED",
        "source_mutated": False,
    }


def _validate_source(repository: dict[str, Any], source: Path) -> dict[str, Any]:
    repository_id = str(repository.get("id", "unknown"))
    observed_commit = repository.get("observed_commit")
    if not isinstance(observed_commit, str) or not SHA40.fullmatch(observed_commit):
        return {
            "repository": repository_id,
            "observed_commit": observed_commit,
            "source_head": None,
            "source_state": "UNAVAILABLE",
            "materialized_commit": None,
            "materialized_state": "NOT_RUN",
            "source_mutated": False,
            "reason": "observed commit is not a 40-character SHA",
        }
    observation = _source_observation(source, observed_commit, repository_id)
    commit_exists = _git(source, "cat-file", "-e", f"{observed_commit}^{{commit}}")
    if observation["source_state"] == "UNAVAILABLE":
        observation["materialized_state"] = "NOT_RUN"
        observation["reason"] = "source checkout is unavailable or not a Git repository"
    elif commit_exists.returncode != 0:
        observation["materialized_state"] = "NOT_RUN"
        observation["reason"] = "observed commit is unavailable in the source checkout"
    return observation


def _failure_findings(manifest: dict[str, Any], source_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for repository in sorted(manifest.get("repositories", []), key=lambda item: str(item.get("id", ""))):
        repository_id = repository.get("id")
        path = repository.get("path")
        if not isinstance(repository_id, str) or not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
            findings.append({"repository": repository_id, "observed_commit": repository.get("observed_commit"), "source_state": "UNAVAILABLE", "materialized_state": "NOT_RUN", "source_mutated": False, "reason": "manifest child path is unsafe"})
            continue
        findings.append(_validate_source(repository, source_root / path))
    return findings


def _clone_at_pin(source: Path, destination: Path, observed_commit: str, repository_id: str) -> None:
    clone = subprocess.run(
        ["git", "clone", "--no-local", "--no-checkout", "--quiet", str(source), str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if clone.returncode != 0:
        raise PinnedWorkspaceError(f"{repository_id}: could not clone the source checkout")
    checkout = _git(destination, "checkout", "--detach", "--quiet", observed_commit)
    if checkout.returncode != 0:
        raise PinnedWorkspaceError(f"{repository_id}: could not materialize the observed pin")
    head = _git(destination, "rev-parse", "HEAD")
    dirty = _git(destination, "status", "--porcelain", "--untracked-files=all")
    if head.stdout.strip() != observed_commit or dirty.stdout.strip():
        raise PinnedWorkspaceError(f"{repository_id}: materialized workspace failed its clean pin check")


def materialize_pinned_workspace(
    manifest: dict[str, Any],
    source_root: Path,
    destination_root: Path,
) -> list[dict[str, Any]]:
    """Clone local child sources at their exact manifest pins without mutating them."""
    repositories = manifest.get("repositories") if isinstance(manifest, dict) else None
    if not isinstance(repositories, list) or not repositories:
        raise PinnedWorkspaceError("manifest has no repositories")
    source_root = source_root.resolve()
    destination_root = destination_root.resolve()
    if source_root == destination_root or source_root in destination_root.parents:
        raise PinnedWorkspaceError("source and pinned workspace overlap")
    if destination_root.exists() and any(destination_root.iterdir()):
        raise PinnedWorkspaceError("pinned workspace destination is not empty")
    destination_root.mkdir(parents=True, exist_ok=True)
    findings = _failure_findings(manifest, source_root)
    failures = [item for item in findings if item.get("materialized_state") != "MATCHED"]
    if failures:
        detail = "; ".join(
            f"{item.get('repository')}: {item.get('reason', 'observed commit unavailable')}"
            for item in failures
        )
        raise PinnedWorkspaceError(f"manifest-pinned workspace is unavailable: {detail}", findings)
    by_id = {item["repository"]: item for item in findings}
    for repository in sorted(repositories, key=lambda item: str(item.get("id", ""))):
        repository_id = str(repository["id"])
        source = source_root / str(repository["path"])
        destination = destination_root / str(repository["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            _clone_at_pin(source, destination, str(repository["observed_commit"]), repository_id)
        except PinnedWorkspaceError as exc:
            by_id[repository_id]["materialized_state"] = "FAILED"
            by_id[repository_id]["reason"] = str(exc)
            raise PinnedWorkspaceError(str(exc), findings) from exc
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="empty directory outside this repository")
    parser.add_argument(
        "--repository",
        dest="repository_ids",
        action="append",
        metavar="ID",
        help="select one manifest repository; repeat for a scoped workspace (default: all)",
    )
    args = parser.parse_args(argv)
    try:
        materialized = materialize(args.output, os.environ.get("CHILD_REPOS_TOKEN"), args.repository_ids)
    except (WorkspaceError, OSError, yaml.YAMLError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    for identifier, commit in materialized:
        print(f"{identifier} {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
