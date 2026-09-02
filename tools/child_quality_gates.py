#!/usr/bin/env python3
"""Run child quality gates from immutable manifest-pinned commit archives."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from tools.quality_gates import _gate_result, _run_gate
    from tools.validate import (
        ROOT,
        load_yaml,
        validate_child_quality_gates,
        validate_manifest,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.quality_gates import _gate_result, _run_gate
    from tools.validate import ROOT, load_yaml, validate_child_quality_gates, validate_manifest


DEFAULT_MANIFEST = ROOT / "config/repositories.yaml"
DEFAULT_WORKSPACE_ROOT = ROOT / "repos"
DEFAULT_OUTPUT = ROOT / "data/child-quality-gates.json"

# Gates run from a fresh archive; allow the slowest measured child suite to finish.
DEFAULT_GATE_TIMEOUT_SECONDS = 300

_REQUIREMENT_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*))(?:\[[^\]]+\])?"
    r"\s*(?:(?P<operator>>=|==)\s*(?P<version>[0-9]+(?:\.[0-9]+)*))?(?:\s*,.*)?$"
)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _workspace_state(root: Path, observed_commit: str) -> tuple[str, str | None]:
    if not root.is_dir():
        return "MISSING", None
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        return "UNKNOWN", None
    workspace_commit = head.stdout.strip()
    dirty = _git(root, "status", "--porcelain").stdout.strip()
    if dirty:
        state = "DIRTY"
    elif workspace_commit == observed_commit:
        state = "MATCHED"
    else:
        state = "STALE"
    return state, workspace_commit


def _not_run(command: str, error: str) -> dict:
    return _gate_result(command, "NOT_RUN", None, 0, error=error)


def _installed_version(package_name: str) -> str | None:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _installed_version_in_python(package_name: str, python_executable: str | None) -> str | None:
    """Read a dependency version from a selected child interpreter."""
    if python_executable is None:
        return _installed_version(package_name)
    probe = (
        "import importlib.metadata, sys; "
        "print(importlib.metadata.version(sys.argv[1]))"
    )
    completed = subprocess.run(
        [python_executable, "-c", probe, package_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    version = completed.stdout.strip()
    return version or None


def _version_numbers(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value))


def _meets_lower_bound(installed: str, lower: str) -> bool:
    installed_numbers = _version_numbers(installed)
    lower_numbers = _version_numbers(lower)
    if not installed_numbers or not lower_numbers:
        return False
    width = max(len(installed_numbers), len(lower_numbers))
    return installed_numbers + (0,) * (width - len(installed_numbers)) >= lower_numbers + (0,) * (width - len(lower_numbers))


def _matches_exact_version(installed: str, expected: str) -> bool:
    installed_numbers = _version_numbers(installed)
    expected_numbers = _version_numbers(expected)
    if not installed_numbers or not expected_numbers:
        return False
    width = max(len(installed_numbers), len(expected_numbers))
    return installed_numbers + (0,) * (width - len(installed_numbers)) == expected_numbers + (0,) * (width - len(expected_numbers))


def _requirements_preflight(
    archive_root: Path,
    repository_path: str,
    python_executable: str | None = None,
) -> tuple[str | None, str | None]:
    """Return an unsatisfied detail and remediation for a child archive, if any.

    This intentionally implements only the parent contract's small requirement
    subset: distribution names with an optional numeric ``>=`` lower bound or
    numeric ``==`` exact version. Environment markers and additional bounds are
    ignored; dependency resolution and installation remain outside this runner.
    """
    requirements_path = archive_root / "requirements.txt"
    if not requirements_path.exists():
        return None, None
    if not requirements_path.is_file():
        return "requirements.txt is not a regular file", f"pip install --user -r {repository_path}/requirements.txt"
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return f"requirements.txt could not be read: {exc}", f"pip install --user -r {repository_path}/requirements.txt"

    for line_number, raw_line in enumerate(lines, start=1):
        requirement = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
        if not requirement:
            continue
        match = _REQUIREMENT_PATTERN.fullmatch(requirement)
        if match is None:
            detail = f"unsupported requirement syntax on line {line_number}: {requirement!r}"
            return detail, f"pip install --user -r {repository_path}/requirements.txt"
        package_name = match.group("name")
        operator = match.group("operator")
        required_version = match.group("version")
        installed = _installed_version_in_python(package_name, python_executable)
        if installed is None:
            return f"{package_name} is not installed", f"pip install --user -r {repository_path}/requirements.txt"
        if operator == ">=" and required_version is not None and not _meets_lower_bound(installed, required_version):
            return (
                f"{package_name} version {installed!r} is below required >= {required_version}",
                f"pip install --user -r {repository_path}/requirements.txt",
            )
        if operator == "==" and required_version is not None and not _matches_exact_version(installed, required_version):
            return (
                f"{package_name} version {installed!r} does not equal required == {required_version}",
                f"pip install --user -r {repository_path}/requirements.txt",
            )
    return None, None


def _resolve_python_environment(
    repository_id: str,
    python_root: Path | None,
) -> tuple[str | None, str]:
    """Resolve an optional pre-provisioned interpreter without installing anything."""
    if python_root is None:
        return None, "shared-runner"
    candidates = (
        python_root / repository_id / "bin" / "python",
        python_root / repository_id / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate), "per-child"
    return None, "per-child"


def _environment_remediation(repository_id: str) -> str:
    return (
        "provision the child requirements in "
        f"<child-environment-root>/{repository_id}/bin/python and rerun; "
        "the runner does not install dependencies"
    )


def _extract_archive(root: Path, commit: str, target: Path) -> str | None:
    """Materialize an immutable disposable checkout with its Git history intact.

    A plain ``git archive`` is sufficient for most commands, but it removes the
    history that child repositories use to prove entity provenance and clean
    snapshots.  A local no-link clone keeps that history while ensuring every
    command runs outside the user's child checkout.  The target is disposable
    and is always detached at the exact observed commit.
    """
    clone = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-local",
            "--no-checkout",
            str(root),
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if clone.returncode != 0:
        detail = clone.stderr.strip() or "git clone returned non-zero"
        return f"observed commit archive unavailable: {detail}; remediation: fetch or pin the observed immutable commit"
    checkout = subprocess.run(
        ["git", "-C", str(target), "checkout", "--quiet", "--detach", commit],
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout.returncode != 0:
        detail = checkout.stderr.strip() or "git checkout returned non-zero"
        return f"observed commit checkout unavailable: {detail}; remediation: fetch or pin the observed immutable commit"
    state = _git(target, "status", "--porcelain", "--untracked-files=all")
    if state.returncode != 0 or state.stdout.strip():
        return "observed immutable checkout is not clean; remediation: reject the child checkout before execution"
    head = _git(target, "rev-parse", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != commit:
        return "observed immutable checkout does not match the requested commit; remediation: reject the child checkout before execution"
    return None


def _validate_gate_manifest(manifest: dict) -> list[str]:
    """Validate the subset of the parent manifest needed by this runner."""
    errors: list[str] = []
    repositories = manifest.get("repositories") if isinstance(manifest, dict) else None
    if not isinstance(repositories, list) or not repositories:
        return ["manifest.repositories must be a non-empty list; remediation: declare child repositories in config/repositories.yaml"]
    seen: set[str] = set()
    for index, repository in enumerate(repositories):
        prefix = f"manifest.repositories[{index}]"
        if not isinstance(repository, dict):
            errors.append(f"{prefix} must be an object; remediation: preserve the repository manifest shape")
            continue
        repository_id = repository.get("id")
        if not isinstance(repository_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", repository_id):
            errors.append(f"{prefix}.id is invalid; remediation: use a stable kebab-case repository ID")
        elif repository_id in seen:
            errors.append(f"{prefix}.id duplicates {repository_id!r}; remediation: use one manifest entry per child repository")
        else:
            seen.add(repository_id)
        repository_path = repository.get("path")
        if (
            not isinstance(repository_path, str)
            or not repository_path
            or Path(repository_path).is_absolute()
            or ".." in Path(repository_path).parts
        ):
            errors.append(f"{prefix}.path is invalid; remediation: declare a relative child checkout path")
        observed_commit = repository.get("observed_commit")
        if not isinstance(observed_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", observed_commit):
            errors.append(f"{prefix}.observed_commit is not a 40-character commit; remediation: pin an immutable observed commit")
        commands = repository.get("quality_gates")
        if not isinstance(commands, list) or not commands or any(not isinstance(command, str) or not command.strip() for command in commands):
            errors.append(f"{prefix}.quality_gates is invalid; remediation: declare one or more executable quality gate commands")
    return errors


def _run_repository(
    repository: dict,
    workspace_root: Path,
    timeout_seconds: int,
    python_root: Path | None = None,
) -> dict:
    repository_id = repository["id"]
    observed_commit = repository["observed_commit"]
    root = workspace_root / repository["path"]
    python_executable, environment_mode = _resolve_python_environment(repository_id, python_root)
    workspace_state, workspace_commit = _workspace_state(root, observed_commit)
    commands = repository["quality_gates"]
    quality_gate_hash = sha256_hex(commands)
    if not root.is_dir() or workspace_commit is None:
        error = "child workspace is missing or not a Git checkout; remediation: initialize the workspace before running immutable gates"
        return {
            "repository": repository_id,
            "observed_commit": observed_commit,
            "workspace_commit": workspace_commit,
            "workspace_state": workspace_state,
            "execution_mode": "NOT_RUN",
            "environment_mode": environment_mode,
            "quality_gate_hash": quality_gate_hash,
            "status": "BLOCKED",
            "gates": [_not_run(command, error) for command in commands],
        }
    with tempfile.TemporaryDirectory(prefix=f"child-gate-{repository_id}-") as temporary:
        target = Path(temporary)
        archive_error = _extract_archive(root, observed_commit, target)
        if archive_error:
            return {
                "repository": repository_id,
                "observed_commit": observed_commit,
                "workspace_commit": workspace_commit,
                "workspace_state": workspace_state,
                "execution_mode": "NOT_RUN",
                "environment_mode": environment_mode,
                "quality_gate_hash": quality_gate_hash,
                "status": "BLOCKED",
                "gates": [_not_run(command, archive_error) for command in commands],
            }
        if python_root is not None and python_executable is None:
            error = (
                f"per-child Python environment is unavailable for {repository_id}; "
                f"remediation: {_environment_remediation(repository_id)}"
            )
            return {
                "repository": repository_id,
                "observed_commit": observed_commit,
                "workspace_commit": workspace_commit,
                "workspace_state": workspace_state,
                "execution_mode": "NOT_RUN",
                "environment_mode": environment_mode,
                "quality_gate_hash": quality_gate_hash,
                "status": "ENV_UNSATISFIED",
                "remediation": _environment_remediation(repository_id),
                "gates": [_not_run(command, error) for command in commands],
            }
        preflight_error, remediation = _requirements_preflight(
            target,
            repository["path"],
            python_executable,
        )
        if preflight_error:
            error = (
                f"child dependency preflight is unsatisfied: {preflight_error}; "
                f"remediation: {remediation}"
            )
            return {
                "repository": repository_id,
                "observed_commit": observed_commit,
                "workspace_commit": workspace_commit,
                "workspace_state": workspace_state,
                "execution_mode": "NOT_RUN",
                "environment_mode": environment_mode,
                "quality_gate_hash": quality_gate_hash,
                "status": "ENV_UNSATISFIED",
                "remediation": remediation,
                "gates": [_not_run(command, error) for command in commands],
            }
        gates = [
            _run_gate(command, target, timeout_seconds, python_executable)
            for command in commands
        ]
        return {
            "repository": repository_id,
            "observed_commit": observed_commit,
            "workspace_commit": workspace_commit,
            "workspace_state": workspace_state,
            "execution_mode": "immutable-archive",
            "environment_mode": environment_mode,
            "quality_gate_hash": quality_gate_hash,
            "status": "FAILED" if any(gate["status"] == "FAILED" for gate in gates) else "PASSED",
            "gates": gates,
        }


def run_child_quality_gates(
    manifest: dict,
    workspace_root: Path,
    timeout_seconds: int = DEFAULT_GATE_TIMEOUT_SECONDS,
    run_id: str = "v12-child-gates",
    python_root: Path | None = None,
) -> dict:
    """Execute every manifest gate from its exact archive and selected environment."""
    manifest_errors = _validate_gate_manifest(manifest)
    if manifest_errors:
        raise ValueError("\n".join(manifest_errors))
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive; remediation: use a finite positive timeout")
    results = [
        _run_repository(repository, workspace_root, timeout_seconds, python_root)
        for repository in sorted(manifest["repositories"], key=lambda item: item["id"])
    ]
    report = {
        "contract_version": "child-quality-gates/v1",
        "run_id": run_id,
        "manifest_hash": sha256_hex(manifest),
        "repository_count": len(results),
        "results": results,
    }
    errors = validate_child_quality_gates(report, "child-quality-gates")
    if errors:
        raise ValueError("\n".join(errors))
    return report


def _render(data: dict) -> bytes:
    return (canonical_json(data) + "\n").encode("utf-8")


def _deterministic_view(value: object) -> object:
    """Remove runtime-only measurements before comparing generated evidence."""
    if isinstance(value, dict):
        return {
            key: _deterministic_view(item)
            for key, item in value.items()
            if key != "duration_ms"
        }
    if isinstance(value, list):
        return [_deterministic_view(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run manifest child gates from immutable observed commits")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--timeout", type=int, default=DEFAULT_GATE_TIMEOUT_SECONDS)
    parser.add_argument("--run-id", default="v12-child-gates")
    parser.add_argument(
        "--python-root",
        type=Path,
        help="optional root of pre-provisioned per-child environments; no installation is performed",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="compare generated bytes without writing")
    args = parser.parse_args()
    try:
        manifest = load_yaml(args.manifest)
        manifest_errors = validate_manifest(manifest, str(args.manifest))
        if manifest_errors:
            raise ValueError("\n".join(manifest_errors))
        python_root = args.python_root
        if python_root is not None and not python_root.is_absolute():
            python_root = Path.cwd() / python_root
        report = run_child_quality_gates(
            manifest,
            args.workspace_root,
            args.timeout,
            args.run_id,
            python_root,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = _render(report)
    if args.check:
        try:
            observed = args.output.read_bytes()
        except OSError as exc:
            print(f"ERROR: {args.output}: {exc}; remediation: generate child gate evidence first", file=sys.stderr)
            return 1
        try:
            observed_data = json.loads(observed)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"ERROR: {args.output}: stored child gate evidence is not valid JSON: {exc}; remediation: regenerate immutable gate evidence", file=sys.stderr)
            return 1
        if _deterministic_view(observed_data) != _deterministic_view(report):
            print(f"ERROR: {args.output}: generated child gate evidence differs beyond runtime-only duration; remediation: regenerate immutable gate evidence", file=sys.stderr)
            return 1
        changed = False
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        changed = args.output.exists() and args.output.read_bytes() == rendered
        if not changed:
            args.output.write_bytes(rendered)
    statuses = {result["status"] for result in report["results"]}
    overall_status = "FAILED" if statuses & {"FAILED", "ENV_UNSATISFIED"} else "BLOCKED" if "BLOCKED" in statuses else "PASSED"
    print(json.dumps({"changed": not changed if not args.check else False, "command": "child-quality-gates", "repository_count": report["repository_count"], "status": overall_status}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
