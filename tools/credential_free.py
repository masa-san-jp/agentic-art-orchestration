#!/usr/bin/env python3
"""Launch a production agent or command without inherited GitHub credentials."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from typing import Mapping

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.process_policy import child_environment


SSH_COMMAND = (
    "ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes "
    "-o IdentityFile=/dev/null -o IdentityAgent=none "
    "-o PubkeyAuthentication=no -o PasswordAuthentication=no "
    "-o KbdInteractiveAuthentication=no"
)


def isolated_environment(
    gh_config: Path, git_config: Path, base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Replace inherited Git overrides as well as token/askpass/SSH sources.

    No authentication value is inspected, printed or saved. The files supplied
    here are newly created and empty for each invocation, including concurrent
    invocations sharing a state root.
    """
    environment = dict(os.environ if base is None else base)
    for name in tuple(environment):
        if (
            (name.startswith(("GH_", "GITHUB_")) and "TOKEN" in name)
            or name.startswith("GIT_CONFIG_")
            or name.startswith("GIT_TRACE")
            or name in ("GIT_CONFIG", "GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK", "SSH_AGENT_PID", "GIT_SSH", "GIT_CURL_VERBOSE")
        ):
            environment.pop(name)
    environment = child_environment(environment)
    # Reset generic headers as well as the GitHub-specific NO_INHERITED_AUTH
    # entry supplied by child_environment. Environment config wins over local
    # and global configuration without changing either file.
    count = int(environment["GIT_CONFIG_COUNT"])
    environment[f"GIT_CONFIG_KEY_{count}"] = "http.extraheader"
    environment[f"GIT_CONFIG_VALUE_{count}"] = ""
    environment["GIT_CONFIG_COUNT"] = str(count + 1)
    # URL-specific local headers can be more specific than the GitHub root.
    # Read names only, with global/system/inherited config already excluded;
    # authentication values never leave their original repository config.
    environment.update(GIT_CONFIG_GLOBAL=str(git_config), GIT_CONFIG_NOSYSTEM="1")
    local = subprocess.run(
        ["git", "config", "--local", "--name-only", "--get-regexp",
         r"^http(\..*)?\.(extraheader|cookiefile)$"],
        env={**environment, "LC_ALL": "C"}, capture_output=True, text=True, check=False,
    )
    no_repository = local.returncode == 128 and "--local can only be used inside a git repository" in local.stderr
    if local.returncode not in (0, 1) and not no_repository:
        raise OSError("local auth configuration observation failed")
    for key in sorted(set(local.stdout.splitlines())):
        count = int(environment["GIT_CONFIG_COUNT"])
        environment[f"GIT_CONFIG_KEY_{count}"] = key
        environment[f"GIT_CONFIG_VALUE_{count}"] = ""
        environment["GIT_CONFIG_COUNT"] = str(count + 1)
    environment.update(
        GH_CONFIG_DIR=str(gh_config),
        GIT_CONFIG_GLOBAL=str(git_config),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS=os.devnull,
        SSH_ASKPASS=os.devnull,
        GIT_SSH_COMMAND=SSH_COMMAND,
        GIT_SSH_VARIANT="ssh",
    )
    return environment


def launch(command: list[str], *, state_root: Path) -> int:
    state_root = state_root.expanduser().resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="credential-free-", dir=state_root) as directory:
        root = Path(directory)
        gh_config = root / "gh-credential-free"
        gh_config.mkdir(mode=0o700)
        git_config = root / "git-global"
        git_config.touch(mode=0o600)
        home = root / "home"
        home.mkdir(mode=0o700)
        environment = isolated_environment(gh_config, git_config)
        # libcurl also reads ~/.netrc, outside Git's credential helper/config.
        # Start with a private empty home rather than copying cached credentials.
        environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
        # Inherit stdin/stdout/stderr directly, including annotated hearing
        # answers; never capture or persist the command's output.
        return subprocess.run(
            command, env=environment, check=False,
        ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True,
                        help="external runtime state root for temporary empty auth configuration")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- <agent or command...>")
    args = parser.parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command after -- is required")
    try:
        returncode = launch(command, state_root=args.state_root)
    except FileNotFoundError:
        print("credential-free launch failed: command or state root unavailable", file=sys.stderr)
        return 127
    except OSError:
        print("credential-free launch failed: cannot prepare state or execute command", file=sys.stderr)
        return 126
    if returncode < 0:
        # Preserve termination by signal as well as ordinary exit codes, after
        # the temporary credential-free configuration has been cleaned up.
        signum = -returncode
        if signum not in (signal.SIGKILL, signal.SIGSTOP):
            signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
