#!/usr/bin/env python3
"""Materialize manifest-pinned child repositories without mutating sources."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


SHA40 = re.compile(r"^[0-9a-f]{40}$")


class PinnedWorkspaceError(RuntimeError):
    """A manifest-pinned workspace could not be materialized safely."""

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
        raise PinnedWorkspaceError(
            f"{repository_id}: could not clone the source checkout; remediation: provide a Git checkout containing the observed pin"
        )
    checkout = _git(destination, "checkout", "--detach", "--quiet", observed_commit)
    if checkout.returncode != 0:
        raise PinnedWorkspaceError(
            f"{repository_id}: could not materialize the observed pin; remediation: fetch the immutable commit without changing the source checkout"
        )
    head = _git(destination, "rev-parse", "HEAD")
    dirty = _git(destination, "status", "--porcelain", "--untracked-files=all")
    if head.stdout.strip() != observed_commit or dirty.stdout.strip():
        raise PinnedWorkspaceError(
            f"{repository_id}: materialized workspace failed its clean pin check; remediation: discard the temporary workspace and retry"
        )


def materialize_pinned_workspace(
    manifest: dict[str, Any],
    source_root: Path,
    destination_root: Path,
) -> list[dict[str, Any]]:
    """Clone each child source and detach it at its manifest observed commit.

    Source checkout state is observed but never changed. The returned records
    retain source drift and exact observed/materialized commits as metadata.
    """
    repositories = manifest.get("repositories") if isinstance(manifest, dict) else None
    if not isinstance(repositories, list) or not repositories:
        raise PinnedWorkspaceError("manifest has no repositories; remediation: provide a validated repository manifest")
    source_root = source_root.resolve()
    destination_root = destination_root.resolve()
    if source_root == destination_root or source_root in destination_root.parents:
        raise PinnedWorkspaceError("source and pinned workspace overlap; remediation: use a separate temporary destination")
    if destination_root.exists() and any(destination_root.iterdir()):
        raise PinnedWorkspaceError("pinned workspace destination is not empty; remediation: use a fresh temporary destination")
    destination_root.mkdir(parents=True, exist_ok=True)
    findings = _failure_findings(manifest, source_root)
    failures = [item for item in findings if item.get("materialized_state") != "MATCHED"]
    if failures:
        raise PinnedWorkspaceError(
            "manifest-pinned workspace is unavailable; remediation: restore each observed commit in the source checkout",
            findings,
        )
    for repository, finding in zip(sorted(repositories, key=lambda item: str(item.get("id", ""))), findings):
        source = source_root / str(repository["path"])
        destination = destination_root / str(repository["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            _clone_at_pin(source, destination, str(repository["observed_commit"]), str(repository["id"]))
        except PinnedWorkspaceError as exc:
            finding["materialized_state"] = "FAILED"
            finding["reason"] = str(exc)
            raise PinnedWorkspaceError(str(exc), findings) from exc
    return findings
