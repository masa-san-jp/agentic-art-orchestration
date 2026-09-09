#!/usr/bin/env python3
"""Carry a repository-derived theme all the way to a production plan, without asking anyone.

    python3 tools/run.py --workspace-root <実クローン> --profile-root <外部profile>

An explicit --intent may rank candidates, but it is optional. Without it, the
repository snapshot supplies the first gate-passing candidate and its derived
creative question becomes the working theme. Everything after startup runs
without asking: ingest, compose, gate, select, trace, request, accept, hand
over, and build the plan.

One step is not a tool call. Conducting the research means reading, searching,
and writing records, and the agent driving this repository does it. When the
research is not yet done the run returns what is left and how it is judged
done; calling the same entry again with the same run id carries on to the plan.
It waits for the agent, never for a person.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.plan_completion import PlanCompletionError, verify_plan

from tools.output_destinations import (
    DestinationError,
    destinations_profile_selected,
    manifest_child_roots,
    resolve_destinations,
    resolve_run_destination,
    write_resolution_evidence,
)
from tools.repo_local_destinations import ENVIRONMENT as PROJECT_ROOT_ENV, resolve_project_root

DEFAULT_STATE = ROOT / "data/runs"
DEFAULT_RULES_PATH = ROOT / "config/transformation-rules.yaml"
DEFAULT_OUTPUT_PATH = ROOT / "data/run.json"
HUMAN_OPERATIONS = [
    "merge",
    "release",
    "public_share",
    "consent_expansion",
    "destructive_git",
    "external_cost_over_declared_budget",
    "physical_action",
]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HANDOFF_ID_PATTERN = re.compile(r"^HO(\d{3,})$")


class StepFailure(RuntimeError):
    """A mechanical step failed, so the run cannot continue past it."""


class BlockedPrecondition(StepFailure):
    """A safe local precondition is missing; no orchestration step may run."""


def _project_identity(run_id: str, slug: str | None = None, title: str | None = None) -> tuple[str, str]:
    """Derive stable project metadata when the user supplied no naming choice."""
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise StepFailure("run-id must be a stable path-safe identifier")
    if slug is not None and (not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)):
        raise StepFailure("slug must be lowercase hyphenated project metadata")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise StepFailure("title must be non-empty project metadata")
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    base = re.sub(r"[^a-z0-9]+", "-", run_id.lower()).strip("-")[:24] or "plan"
    return slug or f"auto-{base}-{digest}", title or "Repository-derived production proposal"


def _theme_proposal(request_path: Path, *, explicit_intent: bool) -> dict[str, str]:
    """Expose the candidate-derived question without storing conversation text."""
    try:
        request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StepFailure(f"research request cannot be read: {request_path}") from exc
    intent = request.get("intent") if isinstance(request, Mapping) else None
    question = intent.get("creative_question") if isinstance(intent, Mapping) else None
    if not isinstance(question, str) or not question.strip():
        raise StepFailure("research request has no derived creative question")
    return {
        "status": "PROPOSED",
        "mode": "INTENT_RANKED" if explicit_intent else "REPOSITORY_DERIVED",
        "source": "gate-passing-candidate",
        "creative_question": question,
        "request": str(request_path),
    }


def _guard_pinned_workspace(workspace_root: Path) -> dict[str, Any]:
    """Require a clean, fully pinned workspace before reading any child export."""
    from tools.workspace import guard_workspace, load_manifest

    manifest = load_manifest()
    resolved_workspace = workspace_root.resolve()
    guard = guard_workspace(manifest, resolved_workspace, False, resolved_workspace.parent / ".unused-fixture")
    blocked = [repository for repository in guard["repositories"] if repository.get("blocked")]
    if blocked:
        # ``pinned_workspace.py`` intentionally creates detached clones at an
        # exact qualified commit.  They are safe immutable code inputs, but the
        # ordinary user-checkout guard quite correctly rejects detached/upstream
        # states.  Accept only the tool's own marker and recheck every byte that
        # matters; never treat an arbitrary detached checkout as qualified.
        from tools.pinned_workspace import PINNED_WORKSPACE_MARKER

        marker_path = resolved_workspace / PINNED_WORKSPACE_MARKER
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() and not marker_path.is_symlink() else None
        except (OSError, json.JSONDecodeError):
            marker = None
        expected = {
            str(repository["id"]): {"path": str(repository["path"]), "commit": str(repository["observed_commit"])}
            for repository in manifest["repositories"]
        }
        entries = marker.get("repositories") if isinstance(marker, Mapping) else None
        observed = {
            str(item.get("id")): {"path": str(item.get("path")), "commit": str(item.get("commit"))}
            for item in entries
            if isinstance(item, Mapping) and item.get("id") is not None
        } if isinstance(entries, list) else {}
        unique_entries = isinstance(entries, list) and len(entries) == len(observed) == len(expected)
        if (isinstance(marker, Mapping)
                and marker.get("contract_version") == "manifest-pinned-workspace/v1"
                and unique_entries and observed == expected):
            immutable_records: list[dict[str, Any]] = []
            for repository in manifest["repositories"]:
                child = resolved_workspace / str(repository["path"])
                if child.is_symlink() or not child.is_dir():
                    break
                head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=child, capture_output=True, text=True)
                dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=child, capture_output=True, text=True)
                top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=child, capture_output=True, text=True)
                if head.returncode or dirty.returncode or dirty.stdout.strip() or top.returncode or Path(top.stdout.strip()).resolve() != child.resolve() or head.stdout.strip() != str(repository["observed_commit"]):
                    break
                immutable_records.append({
                    "id": repository["id"],
                    "path": str(child),
                    "blocked": False,
                    "guard_status": "PASS",
                    "observed": {"head": head.stdout.strip(), "branch": None, "upstream": None, "dirty": False},
                })
            else:
                return {
                    "status": "PASSED",
                    "repository_count": len(immutable_records),
                    "pin_status": "MATCHED",
                    "mutation": "NONE",
                    "mode": "MANIFEST_PINNED_IMMUTABLE",
                    "repositories": immutable_records,
                }
        first = blocked[0]
        reason = first.get("reasons", [{}])[0]
        raise BlockedPrecondition(
            f"workspace BLOCKED for {first.get('id')}: {reason.get('code', 'unknown')} - "
            f"{reason.get('detail', 'workspace guard failed')}; "
            f"remediation: {reason.get('remediation', 'repair the workspace manually')}"
        )

    manifest_by_id = {repository["id"]: repository for repository in manifest["repositories"]}
    mismatches = []
    for repository in guard["repositories"]:
        repository_id = repository["id"]
        observed_head = repository.get("observed", {}).get("head")
        expected_head = manifest_by_id[repository_id].get("observed_commit")
        if observed_head != expected_head:
            mismatches.append(f"{repository_id} expected {expected_head} got {observed_head}")
    if mismatches:
        raise BlockedPrecondition(
            "workspace BLOCKED: manifest pin mismatch: " + "; ".join(mismatches) +
            "; remediation: materialize and qualify the declared pins manually"
        )
    return {
        "status": "PASSED",
        "repository_count": len(guard["repositories"]),
        "pin_status": "MATCHED",
        "mutation": "NONE",
    }


def _manifest_runtime_roots(workspace_root: Path) -> tuple[Path, Path]:
    """Resolve Research and Production code roots from the manifest once."""
    from tools.workspace import load_manifest

    manifest = load_manifest()
    by_id = {str(item.get("id")): item for item in manifest.get("repositories", []) if isinstance(item, Mapping)}
    missing = [identifier for identifier in ("agentic-art-research", "agentic-art-production") if identifier not in by_id]
    if missing:
        raise BlockedPrecondition(
            "runtime roots BLOCKED: manifest is missing " + ", ".join(missing) +
            "; remediation: restore both consumer-runtime entries before starting a plan"
        )
    roots = tuple(workspace_root / str(by_id[identifier]["path"])
                  for identifier in ("agentic-art-research", "agentic-art-production"))
    return roots[0], roots[1]


def _resume_command(
    *, python: str, run_id: str, workspace_root: Path, state_root: Path,
    research_root: Path | None, production_root: Path | None, research_work_root: Path | None,
    profile_root: Path | None, purpose: str, intent: str | None, slug: str | None,
    title: str | None, offline_fixture: bool,
) -> list[str]:
    """Build the exact same-run invocation for a checkpoint report."""
    command = [python, str(ROOT / "tools/run.py"), "--run-id", run_id,
               "--workspace-root", str(workspace_root), "--state-root", str(state_root)]
    if research_root is not None and production_root is not None:
        command += ["--research-root", str(research_root), "--production-root", str(production_root)]
    if research_work_root is not None:
        command += ["--research-work-root", str(research_work_root)]
    if profile_root is not None and not offline_fixture:
        command += ["--profile-root", str(profile_root)]
    if purpose != "artistic-research":
        command += ["--purpose", purpose]
    if intent is not None:
        command += ["--intent", intent]
    if slug is not None:
        command += ["--slug", slug]
    if title is not None:
        command += ["--title", title]
    if offline_fixture:
        command += ["--offline-fixture"]
    return command


def _can_materialize_qualified_workspace(workspace_root: Path) -> bool:
    """Allow automatic recovery only for missing or clean pin-drifted entries."""
    from tools.workspace import load_manifest

    manifest = load_manifest()
    for repository in manifest["repositories"]:
        path = workspace_root / str(repository["path"])
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_dir():
            return False
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=path, capture_output=True, text=True)
        if status.returncode != 0 or status.stdout.strip():
            return False
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True)
        if head.returncode != 0:
            return False
    return True


def _materialize_qualified_workspace(state_root: Path) -> Path:
    """Create an exact-pin workspace in a new tool-owned sibling directory."""
    from tools.pinned_workspace import PINNED_WORKSPACE_MARKER, materialize

    root = state_root.resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BlockedPrecondition(
            "qualified workspace BLOCKED: run state directory is unavailable; "
            "remediation: choose a writable external state root and retry"
        ) from exc
    destination = root / "pinned-workspace"
    if destination.is_dir() and (destination / PINNED_WORKSPACE_MARKER).is_file():
        return destination
    if destination.exists():
        raise BlockedPrecondition(
            f"qualified workspace BLOCKED: {destination} exists without a valid marker; "
            "remediation: preserve it and choose a new empty state root"
        )
    staging = Path(tempfile.mkdtemp(prefix=".pinned-workspace-", dir=str(root)))
    try:
        materialize(staging, os.environ.get("CHILD_REPOS_TOKEN"))
    except Exception as exc:
        raise BlockedPrecondition(
            "qualified workspace BLOCKED: declared pins could not be materialized; "
            "remediation: inspect read-only remote access and retry with the same run"
        ) from exc
    try:
        os.replace(staging, destination)
    except OSError as exc:
        raise BlockedPrecondition(
            "qualified workspace BLOCKED: recovered workspace could not be installed; "
            "remediation: preserve the staging directory and retry the same run"
        ) from exc
    return destination


def _prepare_runtime_workspace(workspace_root: Path, state_root: Path) -> tuple[dict[str, Any], Path]:
    """Use the requested workspace, or safely recover into a new exact-pin one."""
    try:
        return _guard_pinned_workspace(workspace_root), workspace_root
    except BlockedPrecondition:
        if not _can_materialize_qualified_workspace(workspace_root):
            raise
        recovered = _materialize_qualified_workspace(state_root)
        return _guard_pinned_workspace(recovered), recovered


def _materialize_offline_signals(output: Path) -> dict[str, Any]:
    """Materialize only checked-in synthetic signals for an explicit offline run."""
    from tools.candidate_space import load_fixture
    from tools.validate import load_json
    from tools.workspace import load_manifest

    manifest = load_manifest()
    manifest_by_id = {repository["id"]: repository for repository in manifest["repositories"]}
    snapshot_path = ROOT / "data/snapshot.json"
    if not snapshot_path.is_file():
        raise BlockedPrecondition(
            "offline fixture BLOCKED: qualified snapshot is missing; "
            "remediation: run the documented offline bootstrap first"
        )
    snapshot = load_json(snapshot_path)
    snapshot_by_id = {
        record.get("id"): record
        for record in snapshot.get("repositories", [])
        if isinstance(record, Mapping)
    }
    signals = load_fixture(ROOT / "tests/fixtures/portfolio")
    input_ids = {"self-model", "art-history", "marketing-trends"}
    seen_repositories: set[str] = set()
    for signal in signals:
        source = signal.get("source", {})
        repository_id = source.get("repository")
        if repository_id not in input_ids or repository_id in seen_repositories:
            raise BlockedPrecondition(
                "offline fixture BLOCKED: synthetic input set is incomplete or ambiguous; "
                "remediation: repair the checked-in signal fixture"
            )
        seen_repositories.add(repository_id)
        expected = manifest_by_id[repository_id].get("observed_commit")
        snapshot_pin = snapshot_by_id.get(repository_id, {}).get("manifest_observed_commit")
        if source.get("commit") != expected or snapshot_pin != expected:
            raise BlockedPrecondition(
                f"offline fixture BLOCKED: pin mismatch for {repository_id}; "
                "remediation: regenerate and qualify the fixture against the manifest"
            )
    if seen_repositories != input_ids:
        raise BlockedPrecondition(
            "offline fixture BLOCKED: not all input repositories are represented; "
            "remediation: repair the checked-in signal fixture"
        )

    output.mkdir(parents=True, exist_ok=True)
    signal_files: list[str] = []
    for signal in signals:
        relative = Path(signal["source"]["repository"]) / f"{signal['signal_id'].replace(':', '_')}.json"
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(signal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        signal_files.append(str(relative))
    portfolio = {"version": 1, "signal_files": sorted(signal_files), "requirements": []}
    (output / "portfolio.json").write_text(
        json.dumps(portfolio, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "PASSED",
        "signal_count": len(signals),
        "by_kind": {kind: sum(1 for signal in signals if signal.get("signal_kind") == kind)
                    for kind in sorted({signal.get("signal_kind") for signal in signals})},
        "portfolio": str(output / "portfolio.json"),
        "warnings": [],
        "deferred_boundaries": [],
        "mode": "OFFLINE_FIXTURE",
    }


def _run_tool(args: list[str], python: str) -> dict:
    result = subprocess.run([python, *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
        raise StepFailure(f"{args[0]} failed: {detail[0]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"stdout": result.stdout.strip()}


def _head(root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    except OSError:
        return "0" * 40
    return result.stdout.strip() if result.returncode == 0 else "0" * 40


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise StepFailure(f"production plan cannot be hashed: {path}") from exc
    return digest.hexdigest()


def _production_output_root(state_root: Path) -> Path:
    """Keep production projects stable across run IDs while keeping them external to Git history."""
    return state_root.resolve() / "production"


def _record_production_run(
    state_root: Path,
    run_id: str,
    project_slug: str,
    requested_at: str,
) -> Path:
    """Append one metadata-only run-to-project relation, idempotently."""
    history_path = state_root.resolve() / "production-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    project_id = f"production/{project_slug}"
    expected = {
        "version": 1,
        "run_id": run_id,
        "project_id": project_id,
        "recorded_at": requested_at,
        "status": "MATERIALIZED",
    }
    if history_path.is_file():
        try:
            lines = history_path.read_text(encoding="utf-8").splitlines()
            entries = [json.loads(line) for line in lines if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            raise StepFailure(f"production history cannot be read: {history_path}") from exc
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise StepFailure(f"production history entry is not an object: {history_path}")
            if entry.get("run_id") != run_id:
                continue
            if entry.get("project_id") != project_id or entry.get("status") != "MATERIALIZED":
                raise StepFailure(
                    f"production history maps run {run_id!r} to a different project; "
                    "remediation: inspect the Git-external history before resuming"
                )
            return history_path
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(expected, ensure_ascii=False, sort_keys=True) + "\n")
    return history_path


def _production_acceptance(
    production_repository: Path,
    output_root: Path,
    bundle_path: Path,
    project_slug: str,
    requested_at: str,
    run_id: str,
    python: str,
) -> tuple[dict, str]:
    """Materialize or safely accept a revision into the persistent project path."""
    args = [
        "tools/new_production.py", project_slug,
        "--handoff", str(bundle_path),
        "--output-root", str(output_root),
    ]
    outcome = _run_child(production_repository, args, python, allow_failure=True)
    if outcome.get("status") != "NOT_READY":
        return outcome, "INITIAL_OR_IDEMPOTENT"
    detail = str(outcome.get("detail", ""))
    if "PROJECT_IDEMPOTENCY_MISMATCH" not in detail:
        raise StepFailure(f"tools/new_production.py failed: {detail or 'unknown production acceptance failure'}")
    revision_args = args + [
        "--accept-revision",
        "--occurred-at", requested_at,
        "--actor-kind", "AGENT",
        "--actor-id", "agentic-art-orchestration",
        "--idempotency-key", f"{run_id}/production/{project_slug}",
    ]
    return _run_child(production_repository, revision_args, python), "ACCEPT_REVISION"


def _handoff_arguments(
    research_root: Path,
    project_slug: str,
    requested_at: str,
    research_commit: str,
) -> list[str]:
    """Choose a child-owned handoff identity without changing the child schema."""
    handoff_path = research_root / "projects" / project_slug / "05_production" / "production-handoff.yaml"
    if not handoff_path.is_file():
        return [
            "--generated-at", requested_at,
            "--research-commit", research_commit,
            "--handoff-id", "HO001",
            "--revision", "1",
        ]

    try:
        existing = yaml.safe_load(handoff_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StepFailure(f"existing handoff cannot be read: {handoff_path}") from exc
    if not isinstance(existing, Mapping):
        raise StepFailure(f"existing handoff is not a mapping: {handoff_path}")

    existing_id = existing.get("handoff_id")
    existing_revision = existing.get("revision")
    existing_commit = existing.get("research_commit")
    existing_generated_at = existing.get("generated_at")
    match = HANDOFF_ID_PATTERN.fullmatch(str(existing_id))
    if match is None or type(existing_revision) is not int or existing_revision < 1:
        raise StepFailure(
            f"existing handoff identity is invalid: {handoff_path}; "
            "remediation: repair it with the child repository's handoff tool"
        )
    if not isinstance(existing_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", existing_commit):
        raise StepFailure(
            f"existing handoff source commit is invalid: {handoff_path}; "
            "remediation: repair it with the child repository's handoff tool"
        )
    if not isinstance(existing_generated_at, str) or not existing_generated_at.strip():
        raise StepFailure(
            f"existing handoff generated_at is missing: {handoff_path}; "
            "remediation: repair it with the child repository's handoff tool"
        )

    if existing_commit == research_commit:
        return [
            "--generated-at", existing_generated_at,
            "--research-commit", existing_commit,
            "--handoff-id", str(existing_id),
            "--revision", str(existing_revision),
        ]

    next_number = int(match.group(1)) + 1
    next_id = f"HO{next_number:03d}"
    return [
        "--generated-at", requested_at,
        "--research-commit", research_commit,
        "--handoff-id", next_id,
        "--revision", str(existing_revision + 1),
        "--supersedes", str(existing_id),
    ]


def _run_child(root: Path, args: list[str], python: str, *, allow_conflict: bool = False,
               allow_failure: bool = False) -> dict:
    """Run a child repository's tool. Already-done steps are not failures on a resume."""
    result = subprocess.run([python, *args], cwd=root, capture_output=True, text=True)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        if allow_conflict and ("CONFLICT" in output or "already" in output or "in place" in output):
            return {"status": "ALREADY_DONE", "detail": output.splitlines()[-1:][0] if output else ""}
        if allow_failure:
            return {"status": "NOT_READY", "detail": output.splitlines()[-1:][0] if output else ""}
        raise StepFailure(f"{args[0]} failed: {(output.splitlines() or ['no output'])[-1]}")
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"status": "PASSED", "stdout": output}



def _at_research(
    work: Path,
    run_id: str,
    intent: str | None,
    steps: list[dict],
    research_root: Path,
    slug: str,
    theme_proposal: dict[str, str] | None = None,
    destination_resolution: Mapping[str, object] | None = None,
    resume_command: list[str] | None = None,
) -> dict:
    """The run pauses for the agent, never for a person, and says exactly what is left."""
    report = {
        "run_id": run_id,
        "intent": intent,
        "theme_proposal": theme_proposal or {
            "status": "PROPOSED",
            "mode": "REPOSITORY_DERIVED",
            "source": "gate-passing-candidate",
            "creative_question": "See the derived creative question in the research request.",
            "request": "",
        },
        "status": "RESEARCH_PENDING",
        "completion_status": "INCOMPLETE",
        "plan_status": "NOT_READY",
        "knowledge_status": "PENDING",
        "projection_status": "NOT_RUN",
        "run_status": "INCOMPLETE",
        "steps": steps,
        "next_action": {
            "actor": "agent",
            "project": str(research_root / "projects" / slug),
            "do": [
                "01_planning/research-plan.yaml のタスクを tools/task_runtime.py で進める",
                "02_evidence に証拠を集める。一次情報に当たり、開いて確かめてから引用する",
                "03_knowledge に観察・主張・関係・矛盾を書く",
                "04_decisions に判断・棄却案・不確実性を書く。棄却が無い調査は選んでいない",
                "05_production に要件・受入試験・試作計画・創作指針を書く",
            ],
            "acceptance": "tools/complete.py が COMPLETE を返し、tools/validate.py --root . が通ること",
            "resume": "同じrun-idで、保存されたresume_commandを実行して受け渡しから制作プランまで進む",
            "resume_command": resume_command or [],
            "manual_fallback": "FORBIDDEN: 未完了の研究から手動制作案を正規成果物として作成しない",
        },
        "state": str(work),
    }
    work.mkdir(parents=True, exist_ok=True)
    if destination_resolution is not None:
        report["destination_resolution"] = dict(destination_resolution)
    (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _run_orchestration(intent: str | None, workspace_root: Path, state_root: Path, run_id: str, purpose: str,
        slug: str | None, title: str | None, requested_at: str, python: str,
        research_root: Path | None = None, production_root: Path | None = None,
        limit: int = 1, offline_fixture: bool = False,
        destination_resolution: Mapping[str, object] | None = None,
        internal_output_root: Path | None = None,
        profile_root: Path | None = None, research_work_root: Path | None = None) -> dict:
    """Execute every step the repositories can do alone, in order, and record each one."""
    if (research_root is None) != (production_root is None):
        # Carrying on with one of the two would run a child tool in whatever directory
        # happens to be current, and report a step it did not take.
        raise StepFailure("--research-root and --production-root are given together or not at all")
    if offline_fixture:
        preflight = {
            "status": "PASSED",
            "repository_count": 3,
            "pin_status": "MATCHED",
            "mutation": "NONE",
            "mode": "OFFLINE_FIXTURE",
        }
    else:
        try:
            preflight, workspace_root = _prepare_runtime_workspace(workspace_root, state_root)
        except BlockedPrecondition as exc:
            # Startup failures are part of the resumable run, not an opaque
            # stderr-only result.  Persist only sanitized metadata and the
            # exact same-run command; never fabricate a theme or plan.
            blocked_work = state_root / run_id
            blocked_work.mkdir(parents=True, exist_ok=True)
            blocked_resume = _resume_command(
                python=python, run_id=run_id, workspace_root=workspace_root,
                state_root=state_root, research_root=research_root,
                production_root=production_root, research_work_root=research_work_root,
                profile_root=profile_root, purpose=purpose, intent=intent,
                slug=slug, title=title, offline_fixture=False,
            )
            blocked_report = {
                "run_id": run_id,
                "status": "BLOCKED",
                "completion_status": "INCOMPLETE",
                "plan_status": "NOT_READY",
                "knowledge_status": "NOT_STARTED",
                "projection_status": "NOT_RUN",
                "run_status": "BLOCKED",
                "steps": [{"step": "workspace-preflight", "status": "BLOCKED"}],
                "stop_reason": "STARTUP_PRECONDITION",
                "detail": str(exc),
                "state": str(blocked_work),
                "next_action": {
                    "actor": "agent",
                    "stage": "startup",
                    "acceptance": "workspace-preflight returns PASSED with MATCHED qualified pins",
                    "resume_command": blocked_resume,
                    "manual_fallback": "FORBIDDEN: startup BLOCKED is incomplete; do not substitute a manual production plan",
                },
            }
            (blocked_work / "run.json").write_text(
                json.dumps(blocked_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raise
    if (not offline_fixture and research_root is None and production_root is None
            and workspace_root.is_dir()):
        # Resolve after recovery so child tools use the newly materialized
        # qualified workspace, never the drifted source checkout.
        research_root, production_root = _manifest_runtime_roots(workspace_root)
    if not offline_fixture and profile_root is None:
        raise BlockedPrecondition("PROFILE_ROOT_REQUIRED: pass --profile-root for real self-model exports")
    # Keep native Research project files outside the read-only code checkout.
    # The default is deterministic and run-scoped, so a caller need not invent
    # a second path just to use the standard entrypoint.
    if research_root is not None and research_work_root is None:
        research_work_root = (state_root / "research-work").resolve()
    research_data_root = research_work_root or research_root
    if research_work_root is not None:
        if research_root is None or not research_work_root.is_absolute() or research_work_root.resolve() != research_work_root or research_root.resolve() in research_work_root.parents:
            raise StepFailure("external Research work root must be separate from pinned code")
    work = state_root / run_id
    work.mkdir(parents=True, exist_ok=True)
    if destination_resolution is not None:
        write_resolution_evidence(state_root, run_id, destination_resolution)
    signals = work / "signals"
    steps: list[dict] = []
    project_slug, project_title = _project_identity(run_id, slug, title)
    resume_command = _resume_command(
        python=python, run_id=run_id, workspace_root=workspace_root, state_root=state_root,
        research_root=research_root, production_root=production_root,
        research_work_root=research_work_root, profile_root=profile_root,
        purpose=purpose, intent=intent, slug=slug, title=title,
        offline_fixture=offline_fixture,
    )

    def record(name: str, detail: dict) -> None:
        steps.append({"step": name, **detail})

    record("workspace-preflight", preflight)
    if destination_resolution is not None:
        record("destination-resolution", {"status": "PASSED", "resolution": dict(destination_resolution)})
    if offline_fixture:
        record("ingest", _materialize_offline_signals(signals))
    else:
        record("ingest", _run_tool([
            "tools/ingest_signals.py", "--purpose", purpose,
            "--workspace-root", str(workspace_root), "--output", str(signals),
            "--profile-root", str(profile_root),
        ], python))

    record("candidates", _run_tool([
        "tools/candidate_space.py", "--fixture", str(signals), "--output", str(work / "candidates.json"),
    ], python))

    record("gates", _run_tool([
        "tools/candidate_gates.py", "--candidates", str(work / "candidates.json"),
        "--fixture", str(signals), "--output", str(work / "gates.json"),
    ], python))

    selection_args = [
        "tools/candidate_selection.py", "--candidates", str(work / "candidates.json"),
        "--fixture", str(signals), "--project-id", project_slug, "--limit", str(limit),
        "--output", str(work / "selection.json"),
    ]
    if intent is not None:
        selection_args.extend(["--intent", intent])
    record("selection", _run_tool(selection_args, python))

    record("propositions", _run_tool([
        "tools/proposition_provenance.py", "--selection", str(work / "selection.json"),
        "--candidates", str(work / "candidates.json"), "--gates", str(work / "gates.json"),
        "--fixture", str(signals), "--output", str(work / "propositions.json"),
    ], python))

    request_args = [
        "tools/build_research_request.py", "--propositions", str(work / "propositions.json"),
        "--signals", str(signals), "--title", project_title,
        "--requested-at", requested_at, "--output", str(work / "requests"),
    ]
    if research_root is not None:
        request_args.extend(["--research-root", str(research_root)])
    request_args += ["--all", "--slug", project_slug] if limit > 1 else ["--slug", project_slug]
    record("research-request", _run_tool(request_args, python))

    requests = sorted((work / "requests").glob("RR*.yaml"))
    request = requests[-1]
    theme_proposal = _theme_proposal(request, explicit_intent=intent is not None)

    if research_root is not None and limit > 1:
        # 100件を人が100回叩かないための入口。受理まで進めて、どのプロジェクトが
        # 調査待ちかを並べて返す。研究そのものはここから先の作業で、道具の実行ではない。
        accepted = []
        for path in requests:
            outcome = _run_child(
                research_root,
                ["tools/accept_research_request.py", str(path), "--apply", "--root", str(research_data_root) if research_work_root else ".",
                 "--accepted-at", requested_at],
                python, allow_conflict=True)
            accepted.append({"request": path.name, "status": outcome.get("status"),
                             "project_id": outcome.get("project_id")})
        record("accept-batch", {"status": "PASSED", "accepted_count": len(accepted)})
        report = {
            "run_id": run_id, "intent": intent, "status": "BATCH_AT_RESEARCH", "completion_status": "INCOMPLETE",
            "plan_status": "NOT_READY", "knowledge_status": "PENDING", "projection_status": "NOT_RUN", "run_status": "INCOMPLETE",
            "steps": steps, "accepted": accepted, "state": str(work),
            "next_action": {
                "actor": "agent",
                "do": ["各プロジェクトで tools/next_action.py を回して調査を進める"],
                "acceptance": "各プロジェクトで tools/complete.py が COMPLETE を返すこと",
                "resume_command": resume_command,
                "manual_fallback": "FORBIDDEN: 未完了の研究から手動制作案を正規成果物として作成しない",
            },
        }
        (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report

    if research_root is not None:
        record("accept", _run_child(
            research_root, ["tools/accept_research_request.py", str(request), "--apply", "--root", str(research_data_root) if research_work_root else ".",
                            "--accepted-at", requested_at], python, allow_conflict=True))

        complete = _run_child(research_root, ["tools/complete.py", f"project/{project_slug}", *(["--root", str(research_data_root)] if research_work_root else [])], python, allow_failure=True)
        record("research-complete", complete)
        if str(complete.get("status")) not in {"COMPLETE", "COMPLETE_WITH_GAPS"}:
            # 調査が済んでいない。人を待つのではなく、次に何をするかを返して同じ入口へ戻す。
            return _at_research(
                work, run_id, intent, steps, research_data_root, project_slug, theme_proposal,
                destination_resolution, resume_command,
            )

        handoff_args = _handoff_arguments(
            research_data_root, project_slug, requested_at, _head(research_root)
        )
        roots = ["--work-root", str(research_data_root), "--protocol-root", str(research_root)] if research_work_root else ["--root", "."]
        record("handoff", _run_child(
            research_root, ["tools/build_handoff.py", f"projects/{project_slug}", *roots,
                            *handoff_args], python, allow_conflict=True))
        record("export", _run_child(
            research_root, ["tools/export_handoff.py", f"projects/{project_slug}", *roots,
                            "--output", str(work / "bundle")], python))
        persistent_production_root = (
            internal_output_root.resolve()
            if internal_output_root is not None
            else _production_output_root(state_root)
        )
        production_outcome, acceptance_mode = _production_acceptance(
            production_root,
            persistent_production_root,
            work / "bundle",
            project_slug,
            requested_at,
            run_id,
            python,
        )
        record("accept-production", {
            **production_outcome,
            "mode": acceptance_mode,
            "output_root": str(persistent_production_root),
            "project": f"production/{project_slug}",
        })
        history_path = _record_production_run(state_root, run_id, project_slug, requested_at)
        plan = _run_child(production_root, ["tools/build_plan.py", "--project-root",
                                            str(persistent_production_root / "production" / project_slug)], python)
        record("plan", plan)
        plan_path = persistent_production_root / "production" / project_slug / "03_plan/production-plan.md"
        production_source_commit = _head(production_root)
        try:
            plan_verification = verify_plan(code_root=production_root, code_commit=production_source_commit,
                project_root=plan_path.parent.parent, python=python, research_commit=_head(research_root))
        except (PlanCompletionError, OSError, subprocess.SubprocessError) as exc:
            report = {"run_id": run_id, "status": "AT_PRODUCTION", "plan_status": "PLAN_BUILDING",
                "completion_status": "INCOMPLETE", "knowledge_status": "PENDING", "projection_status": "SKIPPED", "run_status": "RUNNING",
                "steps": steps, "plan": str(plan_path), "stop_reason": type(exc).__name__,
                "next_action": {"actor": "agent", "stage": "production",
                    "project_root": str(plan_path.parent.parent), "code_root": str(production_root),
                    "do": ["Read the pinned Production docs/plan-actionability.md and native validator findings.",
                           "Complete 02_specification/production-method.yaml using the actual handoff, source conditions and explicit unknowns.",
                           "Run the native builder and plan_actionability validator, then resume this same run ID.",
                           "Do not report PLAN_READY or substitute a manual plan while this state remains incomplete."],
                    "resume_command": resume_command,
                    "validation_command": [python, str(production_root / "tools/plan_actionability.py"),
                                           "--project-root", str(plan_path.parent.parent)]}}
            (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return report
        report = {
            "plan_status": "PLAN_READY", "completion_status": "INCOMPLETE", "knowledge_status": "PENDING", "run_status": "INCOMPLETE",
            "projection_status": "SKIPPED", "plan_verification": plan_verification,
            "run_id": run_id, "intent": intent, "status": "PLAN_READY", "steps": steps,
            "generated_at": requested_at,
            "project_slug": project_slug,
            "project_title": project_title,
            "plan": str(plan_path),
            "production_repository": "agentic-art-production",
            "production_root": str(persistent_production_root),
            "production_history": str(history_path),
            "theme_proposal": theme_proposal,
            "state": str(work),
        }
        production_source_commit = _head(production_root)
        if re.fullmatch(r"[0-9a-f]{40}", production_source_commit):
            report["production_source_commit"] = production_source_commit
        if plan_path.is_file():
            report["production_plan_sha256"] = _sha256_file(plan_path)
            from tools.canonical_plan_projection import source_fields
            report.update(source_fields(plan_path, production_root))
        if destination_resolution is not None:
            report["destination_resolution"] = dict(destination_resolution)
            if internal_output_root is None:
                raise StepFailure("destination resolution has no internal output root for public projection preparation")
            from tools.public_projection import build_automatic_plan_authority, project_plan_automatic

            if isinstance(report.get("production_plan_sha256"), str):
                report["automatic_plan_authority"] = build_automatic_plan_authority(
                    producer="tools/run.py",
                    source_status="PLAN_READY",
                    source_id=run_id,
                    source_sha256=report["production_plan_sha256"],
                    destination_resolution=destination_resolution,
                )

            try:
                destination_items = destination_resolution.get("destinations", {})
                public_item = destination_items.get("public_projection_root") if isinstance(destination_items, Mapping) else None
                public_root = public_item.get("path") if isinstance(public_item, Mapping) else None
                report["public_projection"] = project_plan_automatic(
                    report,
                    internal_output_root=internal_output_root,
                    public_projection_root=Path(public_root) if isinstance(public_root, str) else None,
                    state_root=state_root,
                    projection_id=run_id,
                )
            except (OSError, TypeError, ValueError, KeyError) as exc:
                raise StepFailure("automatic public plan projection failed") from exc
        (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report

    # The repositories stop here on their own. Conducting the research is not a
    # missing tool: it is reading, searching, and writing records, which the agent
    # driving this repository does. Say what it is and how it is judged done.
    next_action = {
        "actor": "agent",
        "why": "この先は、証拠を取り、主張を書き、先行作品を調べ、棄却案を残す作業で、"
               "道具の実行ではない。ここから先はエージェントが行う。",
        "do": [
            f"研究リポジトリで `python3 tools/accept_research_request.py {request} --apply --root <research>` を実行し、"
            "プロジェクトを作る",
            "作られたプロジェクトの 01_planning/research-plan.yaml のタスクを順に進める",
            "02_evidence に証拠を集める。03_knowledge に観察・主張・関係・矛盾を書く",
            "04_decisions に判断・棄却案・不確実性を書く",
            "05_production に要件・受入試験・試作計画・創作指針を書く",
        ],
        "acceptance": "研究リポジトリで `python3 tools/complete.py <project>` が COMPLETE を返し、"
                      "`python3 tools/build_handoff.py <project> ...` が通ること",
        "then": "`python3 tools/export_handoff.py` で束を出し、制作リポジトリの `tools/new_production.py` と "
                "`tools/build_plan.py` を実行すると制作プランが出る",
        "request": str(request),
        "resume_command": resume_command,
        "manual_fallback": "FORBIDDEN: AT_EDGE is incomplete; do not create or report a manual production plan",
    }

    report = {
        "run_id": run_id,
        "intent": intent,
        "status": "AT_EDGE",
        "completion_status": "INCOMPLETE",
        "plan_status": "NOT_READY",
        "knowledge_status": "PENDING",
        "projection_status": "NOT_RUN",
        "run_status": "INCOMPLETE",
        "steps": steps,
        "theme_proposal": theme_proposal,
        "next_action": next_action,
        "state": str(work),
    }
    if destination_resolution is not None:
        report["destination_resolution"] = dict(destination_resolution)
    (work / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _run_input_pipeline(
    bundle: dict[str, Any],
    *,
    project_id: str,
    seed_input: str,
    selection_limit: int = 1,
    intent: str | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the synchronous signal pipeline while exposing only an intent digest."""
    from tools.candidate_gates import build_gate_report
    from tools.candidate_selection import INTENT_ALGORITHM, build_selection, intent_sha256, normalize_intent
    from tools.candidate_space import build_candidate_space
    from tools.consumer import import_signals
    from tools.proposition_provenance import build_provenance
    from tools.signal_bundle import validate_signal_bundle
    from tools.validate import load_yaml

    errors = validate_signal_bundle(bundle)
    if errors:
        raise ValueError("\n".join(errors))
    signals = bundle["records"]
    imported = import_signals(signals)
    registry = rules if rules is not None else load_yaml(DEFAULT_RULES_PATH)
    candidate_space = build_candidate_space(signals, registry, "run.candidates")
    gate_report = build_gate_report(candidate_space, signals, registry, "run.gates")
    selection = build_selection(
        candidate_space,
        gate_report,
        project_id,
        seed_input,
        selection_limit,
        "run.selection",
        signals=signals if intent is not None else None,
        intent=intent,
    )
    provenance = build_provenance(selection, candidate_space, gate_report, signals, registry, "run.provenance")
    research_source = next(
        (item for item in bundle.get("source_repositories", [])
         if item.get("repository") == "agentic-art-research"),
        bundle.get("source_repositories", [{}])[0],
    )
    result: dict[str, Any] = {
        "bundle": bundle,
        "consumer_package": imported,
        "candidate_space": candidate_space,
        "gate_report": gate_report,
        "selection": selection,
        "provenance": provenance,
        "execution_status": "RESEARCH_PENDING",
        "next_action": {
            "contract_version": "agent-action/v1",
            "run_id": project_id,
            "stage": "research",
            "child_repository": "agentic-art-research",
            "source_commit": research_source["commit"],
            "project_path": "project",
            "allowed_paths": ["project"],
            "forbidden_operations": HUMAN_OPERATIONS,
            "completion_command": "return agent-result/v1 with all declared checks",
            "resume_command": "resume the same run_id from supervisor.json",
            "requested_operations": [],
            "attempt": 1,
        },
    }
    if intent is not None:
        normalized = normalize_intent(intent, "run.intent")
        result["intent_sha256"] = intent_sha256(normalized)
        result["intent_algorithm"] = INTENT_ALGORITHM
    return result


def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Support both the v1 input pipeline and the full agent orchestration entrypoint."""
    if args and isinstance(args[0], dict):
        return _run_input_pipeline(*args, **kwargs)
    return _run_orchestration(*args, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-context", type=Path, help="external knowledge-cycle-context/v1; advance the same profile/run checkpoint")
    parser.add_argument("--project-root", type=Path, help="explicit agentic-art-project checkout for output-destinations/v2")
    parser.add_argument("--delivery-target", choices=("internal", "project-local", "project-committed"), help="Bind the requested delivery goal to --cycle-context; never silently downgrade")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--seed-input")
    parser.add_argument("--selection-limit", type=int, default=1)
    parser.add_argument("--intent", help="任意。指定しない場合は、pin済み候補からテーマを自動提案する")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id", help="任意。省略時はこの実行の安定IDを生成する")
    parser.add_argument("--slug", help="任意。省略時はrun-idから安定生成する")
    parser.add_argument("--title", help="任意。省略時は自動生成する")
    parser.add_argument("--requested-at", help="任意。省略時は起動時刻を使う")
    parser.add_argument("--purpose", default="artistic-research")
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos",
                        help="clean, manifest-pinned child workspace; it is checked read-only")
    parser.add_argument("--state-root", type=Path,
                        help="Git-external run state directory")
    parser.add_argument("--destinations-file", type=Path,
                        help="explicit external output-destinations/v1 profile")
    parser.add_argument("--research-root", type=Path, help="指定すると調査の受理から制作プランまで進む")
    parser.add_argument("--research-work-root", type=Path, help="external native Research work tree; keep qualified code clean")
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--profile-root", type=Path,
                        help="explicit external Self Model profile root for real signal ingestion")
    parser.add_argument("--offline-fixture", action="store_true",
                        help="use the checked-in synthetic signal fixture; do not read child checkouts")
    parser.add_argument("--limit", type=int, default=1,
                        help="選定する命題の件数。2以上でバッチになる")
    parser.add_argument("--child-python", default=sys.executable)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.cycle_context is not None:
            if args.project_root is not None:
                raise StepFailure("--project-root cannot be combined with --cycle-context; put the v2 resolution in the context")
            if args.state_root is None:
                raise StepFailure("--cycle-context requires --state-root")
            from tools.knowledge_cycle_run import advance, read
            context = read(args.cycle_context)
            if args.delivery_target:
                requested = {'contract_version':'delivery-contract/v1', 'target':args.delivery_target}
                if context.get('delivery_contract', requested) != requested:
                    raise StepFailure('DELIVERY_CONTRACT_CONFLICT')
                context['delivery_contract'] = requested
            report = advance(context, args.state_root)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['run_status'] == 'COMPLETED' else 1
        if args.delivery_target:
            raise StepFailure("--delivery-target requires --cycle-context so profile, owner receipts and destination are verified")
        project_root_selected = args.project_root is not None or PROJECT_ROOT_ENV in os.environ
        if project_root_selected and (args.destinations_file is not None or args.state_root is not None or args.output is not None):
            raise StepFailure("AMBIGUOUS_DESTINATION_MODE: repo-local --project-root cannot be combined with v1 roots/profile")
        run_now = datetime.now(timezone.utc)
        run_id = args.run_id or f"AUTO-PLAN-{run_now.strftime('%Y%m%dT%H%M%SZ')}"
        requested_at = args.requested_at or run_now.isoformat()
        destination_resolution = None
        internal_output_root = None
        if project_root_selected:
            destination_resolution = resolve_project_root(args.project_root, run_id=run_id, project_id=args.project_id)
            destination_roots = destination_resolution["destinations"]
            state_root = Path(destination_roots["state_root"]["path"])
            internal_output_root = Path(destination_roots["internal_output_root"]["path"])
        elif destinations_profile_selected(args.destinations_file):
            from tools.workspace import load_manifest

            direct = {"state_root": args.state_root} if args.state_root is not None else None
            destination_resolution = resolve_destinations(
                args.destinations_file,
                direct=direct,
                repository_root=ROOT,
                child_roots=manifest_child_roots(load_manifest(), args.workspace_root),
                run_id=run_id,
                project_id=args.project_id,
            )
            destination_roots = destination_resolution["destinations"]
            state_root = Path(destination_roots["state_root"]["path"])
            internal_output_root = Path(destination_roots["internal_output_root"]["path"])
        else:
            state_root = args.state_root or DEFAULT_STATE
        if args.bundle is not None:
            if not args.project_id or not args.seed_input:
                parser.error("--bundle requires --project-id and --seed-input")
            from tools.validate import load_yaml

            result = _run_input_pipeline(
                _load_json(args.bundle),
                project_id=args.project_id,
                seed_input=args.seed_input,
                selection_limit=args.selection_limit,
                intent=args.intent,
                rules=load_yaml(args.rules),
            )
            if destination_resolution is not None:
                result["destination_resolution"] = dict(destination_resolution)
            rendered = (canonical_json(result) + "\n").encode("utf-8")
            profile_output = args.output is None and destination_resolution is not None
            output = (
                resolve_run_destination(internal_output_root, "run", args.project_id) / "run.json"
                if profile_output and internal_output_root is not None
                else args.output or DEFAULT_OUTPUT_PATH
            )
            if args.check:
                if output.read_bytes() != rendered:
                    raise ValueError(f"{output}: generated run bytes differ")
                changed = False
            else:
                if profile_output:
                    existing = output.read_bytes() if output.exists() else None
                    if existing is not None and existing != rendered:
                        raise DestinationError("profile-derived bundle output already contains different bytes")
                    output.parent.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                changed = output.exists() and output.read_bytes() == rendered
                if not changed:
                    output.write_bytes(rendered)
            if destination_resolution is not None:
                write_resolution_evidence(state_root, run_id, destination_resolution)
            summary: dict[str, Any] = {
                "changed": False if args.check else not changed,
                "command": "run",
                "selected_count": result["selection"]["selected_count"],
                "status": "PASSED",
            }
            if "intent_sha256" in result:
                summary["intent_algorithm"] = result["intent_algorithm"]
                summary["intent_sha256"] = result["intent_sha256"]
            if destination_resolution is not None:
                summary["destination_resolution"] = dict(destination_resolution)
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0

        report = _run_orchestration(args.intent, args.workspace_root, state_root, run_id,
                                    args.purpose, args.slug, args.title, requested_at, args.child_python,
                                    args.research_root, args.production_root, args.limit, args.offline_fixture,
                                    destination_resolution=destination_resolution,
                                    internal_output_root=internal_output_root,
                                    profile_root=args.profile_root, research_work_root=args.research_work_root)
    except BlockedPrecondition as exc:
        print(json.dumps({"status": "BLOCKED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (StepFailure, OSError, IndexError, TypeError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    projection = report.get("public_projection") if isinstance(report, Mapping) else None
    projection_status = projection.get("status") if isinstance(projection, Mapping) else None
    if projection_status in {"BLOCKED_CONFIGURATION", "BLOCKED_POLICY", "BLOCKED_CONFLICT", "FAILED"}:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
