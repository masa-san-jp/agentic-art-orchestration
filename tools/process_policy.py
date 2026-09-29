"""Process-boundary helpers for production runs.

The production lane may read public repositories, but a child process must not
inherit ambient GitHub write credentials from the agent session.  This module
keeps the observation metadata-only and provides a deterministic environment
for child tools.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Mapping

from tools.pinned_workspace import NO_INHERITED_AUTH


AUTH_ENV_NAMES = ("GH_TOKEN", "GITHUB_TOKEN")
WRITE_SCOPE = re.compile(
    r"(?<![A-Za-z0-9_])(?:repo|public_repo|workflow|write(?::[^\s'\",]+)?|admin(?::[^\s'\",]+)?|push)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
SCOPE_MARKER = re.compile(r"(?:token\s+scopes?|scopes?)\s*[:=]", re.IGNORECASE)


def child_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment with GitHub tokens and Git credential helpers removed.

    ``GIT_CONFIG_COUNT`` is the environment equivalent of passing
    ``-c credential.helper=`` to every Git command a child may launch.  It has
    higher precedence than repository-local configuration while preserving the
    rest of the child process environment.
    """

    environment = dict(os.environ if base is None else base)
    for name in AUTH_ENV_NAMES:
        environment.pop(name, None)
    try:
        config_count = int(environment.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        config_count = 0
    config_count = max(config_count, 0)
    while any(
        key in environment
        for key in (f"GIT_CONFIG_KEY_{config_count}", f"GIT_CONFIG_VALUE_{config_count}")
    ):
        config_count += 1
    entries = (
        ("credential.helper", ""),
        (NO_INHERITED_AUTH[1].split("=", 1)[0], ""),
    )
    for offset, (key, value) in enumerate(entries):
        environment[f"GIT_CONFIG_KEY_{config_count + offset}"] = key
        environment[f"GIT_CONFIG_VALUE_{config_count + offset}"] = value
    environment["GIT_CONFIG_COUNT"] = str(config_count + len(entries))
    return environment


def _run_observation(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def observe_git_write_credentials(*, cwd: Path | None = None) -> str:
    """Classify ambient write-capable credentials without returning their value."""

    if any(os.environ.get(name) for name in AUTH_ENV_NAMES):
        return "present"

    observation_failed = False
    scope_output = ""
    try:
        gh = _run_observation(["gh", "auth", "status", "--hostname", "github.com"], cwd=cwd)
        scope_output = f"{gh.stdout}\n{gh.stderr}"
        if WRITE_SCOPE.search(scope_output):
            return "present"
        gh_has_scope_metadata = bool(SCOPE_MARKER.search(scope_output))
        if gh.returncode != 0 and not gh_has_scope_metadata:
            observation_failed = True
    except (OSError, subprocess.SubprocessError):
        observation_failed = True

    helper_output = ""
    try:
        helper = _run_observation(["git", "config", "--get-all", "credential.helper"], cwd=cwd)
        helper_output = helper.stdout.strip()
        if helper.returncode not in (0, 1):
            observation_failed = True
    except (OSError, subprocess.SubprocessError):
        observation_failed = True

    # A configured helper is not itself proof of a write token: gh can install
    # a helper for a read-only token.  If gh exposed explicit read-only scopes,
    # the helper is safe for this classification; otherwise its capability is
    # unknown and must not be treated as absent.
    if helper_output and not SCOPE_MARKER.search(scope_output):
        return "unknown"
    if observation_failed:
        return "unknown"
    return "absent"
