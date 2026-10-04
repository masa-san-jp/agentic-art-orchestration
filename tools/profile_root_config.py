#!/usr/bin/env python3
"""Discover an external Self Model profile without exposing its path."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.process_policy import child_environment

ENV = "AGENTIC_ART_PROFILE_ROOT"
SOURCE_ENV = "AGENTIC_ART_PROFILE_ROOT_SOURCE"
REMEDIATION = (
    "オーナーに tools/profile_root_config.py set <絶対パス> --workspace-root <pin済みworkspace> "
    "を本人の機械で1回実行してもらい、同じ run を再開する。"
    "profile root のパスを人に聞かず、会話・Issue・ログに書かない。"
)


class ProfileConfigError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _external(path: Path) -> Path:
    # Inspect lexical ancestors before resolving so symlink aliases cannot
    # turn a repository location into an apparently safe external location.
    if not path.is_absolute() or ".." in path.parts:
        raise ProfileConfigError("PROFILE_ROOT_NOT_ABSOLUTE")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ProfileConfigError("PROFILE_ROOT_SYMLINK")
    if any((part / ".git").exists() for part in (path, *path.parents)):
        raise ProfileConfigError("PROFILE_ROOT_REPOSITORY_OVERLAP")
    probe = path if path.is_dir() else path.parent
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(["git", "-C", str(probe), "rev-parse", "--git-dir"],
                            capture_output=True, text=True, env=child_environment(), timeout=5)
    if result.returncode == 0:
        raise ProfileConfigError("PROFILE_ROOT_REPOSITORY_OVERLAP")
    return path


def config_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    base = env.get("XDG_CONFIG_HOME")
    if not base:
        home = env.get("HOME")
        if not home:
            raise ProfileConfigError("PROFILE_CONFIG_HOME_REQUIRED")
        base = str(Path(home).resolve() / ".config")
    return _external(Path(base) / "agentic-art" / "profile-root")


def _read_config(environment: Mapping[str, str] | None = None) -> Path | None:
    path = config_path(environment)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
            raise ProfileConfigError("PROFILE_CONFIG_PERMISSIONS")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            content = handle.read(65537)
        lines = content.splitlines()
        if len(content) > 65536 or len(lines) != 1 or not lines[0] or "\x00" in content:
            raise ProfileConfigError("PROFILE_CONFIG_INVALID")
        return _external(Path(lines[0]))
    finally:
        if fd != -1:
            os.close(fd)


def discover(argument: Path | None = None, *, environment: Mapping[str, str] | None = None) -> tuple[Path | None, str]:
    """Choose a source; owner exporters remain authoritative for live validation."""
    env = os.environ if environment is None else environment
    if argument is not None:
        return argument, "argument"
    if env.get(ENV):
        # The credential-free entry carries source metadata across HOME isolation.
        source = "user-config" if env.get(SOURCE_ENV) == "user-config" else "env"
        return _external(Path(env[ENV])), source
    root = _read_config(env)
    return root, "user-config" if root is not None else "none"


def validate_owner(root: Path, workspace_root: Path, python: str) -> None:
    root = _external(root)
    from tools.validate import load_yaml
    owner = next(item for item in load_yaml(ROOT / "config/repositories.yaml")["repositories"]
                 if item["id"] == "self-model")
    checkout = workspace_root / owner["path"]
    resolver = checkout / "tools/profile_root.py"
    if not resolver.is_file():
        raise ProfileConfigError("PROFILE_OWNER_RESOLVER_UNAVAILABLE")
    result = subprocess.run([python, str(resolver), "resolve", "--profile-root", str(root), "--json"],
                            cwd=checkout, env=child_environment(), capture_output=True, text=True, timeout=30)
    # Do not echo child stdout/stderr: even validation diagnostics are private.
    try:
        passed = result.returncode == 0 and json.loads(result.stdout).get("status") == "PASS"
    except (ValueError, AttributeError):
        passed = False
    if not passed:
        raise ProfileConfigError("PROFILE_ROOT_INVALID")


def set_config(root: Path, workspace_root: Path, python: str = sys.executable) -> None:
    if "\n" in str(root) or "\r" in str(root) or "\x00" in str(root):
        raise ProfileConfigError("PROFILE_CONFIG_INVALID")
    validate_owner(root, workspace_root, python)
    path = config_path()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _external(path)
    if path.exists():
        _read_config()  # Refuse unsafe existing files instead of replacing them.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(str(root) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _external(path)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def redact(value: object, root: Path | None) -> object:
    """Remove the private path from boundary output, including child diagnostics."""
    if root is None:
        return value
    if isinstance(value, str):
        secrets = {str(root)}
        try:
            secrets.add(str(root.resolve()))
        except (OSError, RuntimeError):
            pass
        secrets.update(json.dumps(secret)[1:-1] for secret in tuple(secrets))
        for secret in secrets:
            value = value.replace(secret, "<profile-root-redacted>")
        return value
    if isinstance(value, dict):
        return {redact(key, root): redact(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, root) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setter = sub.add_parser("set")
    setter.add_argument("root", type=Path)
    setter.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    setter.add_argument("--child-python", default=sys.executable)
    sub.add_parser("show").add_argument("--redacted", action="store_true", help="paths are always redacted")
    sub.add_parser("clear")
    args = parser.parse_args(argv)
    try:
        if args.command == "set":
            set_config(args.root, args.workspace_root, args.child_python)
            report = {"status": "PASSED", "profile_root_source": "user-config"}
        elif args.command == "clear":
            path = config_path()
            if path.exists():
                _read_config()
                path.unlink()
            report = {"status": "PASSED", "profile_root_source": "none"}
        else:
            report = {"status": "PASSED", "profile_root_source": "user-config" if _read_config() else "none"}
    except (ProfileConfigError, OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
        print(json.dumps({"status": "BLOCKED", "stop_reason": "PROFILE_CONFIG_INVALID",
                          "remediation": REMEDIATION}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
