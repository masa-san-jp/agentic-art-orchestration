#!/usr/bin/env python3
"""Run the parent-owned, reference-only Research/Production exchange."""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/production-exchange-evidence.schema.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
SAFE_COMMAND_PATTERN = re.compile(r"^[^;|&`\r\n]+$")
FORBIDDEN_TEXT = re.compile(r"(?i)(PRIVATE_RAW|RESTRICTED|credential|signed[_ -]?url|raw[_ -]?asset)")


class ExchangeError(RuntimeError):
    """The exchange cannot proceed without violating an immutable boundary."""


class StageFailure(ExchangeError):
    def __init__(self, stage_id: str, reason_code: str):
        super().__init__(reason_code)
        self.stage_id = stage_id
        self.reason_code = reason_code


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ExchangeError(f"cannot read exchange metadata: {path.name}") from exc
    if not isinstance(value, dict):
        raise ExchangeError(f"exchange metadata is not an object: {path.name}")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_strings(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _validate_strings(child)
    elif isinstance(value, list):
        for child in value:
            _validate_strings(child)
    elif isinstance(value, str) and FORBIDDEN_TEXT.search(value):
        raise ExchangeError("exchange metadata contains a forbidden data marker")


def validate_exchange_evidence(data: dict[str, Any], source: str = "production-exchange") -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{source}: evidence must be an object; remediation: preserve the parent exchange evidence envelope"]
    required = {"contract_version", "run_id", "mode", "status", "stages", "remote_operations", "child_mutations", "acceptance", "privacy"}
    missing = sorted(required - set(data))
    errors.extend(f"{source}: missing required field {field!r}; remediation: preserve the parent exchange evidence envelope" for field in missing)
    if data.get("contract_version") != "production-exchange-evidence/v1":
        errors.append(f"{source}.contract_version: unsupported contract; remediation: use production-exchange-evidence/v1")
    if data.get("mode") != "immutable-networkless":
        errors.append(f"{source}.mode: exchange must be immutable-networkless; remediation: use immutable child archives")
    if data.get("remote_operations") != [] or data.get("child_mutations") != []:
        errors.append(f"{source}: remote or child mutation was recorded; remediation: keep this orchestrator read-only")
    acceptance = data.get("acceptance")
    required_acceptance = {
        "research_handoff_exported",
        "production_handoff_accepted",
        "production_result_exported",
        "research_result_dry_run",
        "child_schema_not_copied",
        "adjacent_worktree_not_read",
        "external_effects_not_run",
    }
    if not isinstance(acceptance, dict):
        errors.append(f"{source}.acceptance: must be an object; remediation: record all exchange boundary assertions")
    else:
        for field in sorted(required_acceptance):
            if acceptance.get(field) is not True:
                errors.append(f"{source}.acceptance.{field}: must be true; remediation: prove the exchange boundary explicitly")
    privacy = data.get("privacy")
    if not isinstance(privacy, dict):
        errors.append(f"{source}.privacy: must be an object; remediation: record privacy boundary assertions")
    else:
        for field in ("raw_bundle_stored", "raw_asset_body_stored", "sensitive_data_stored"):
            if privacy.get(field) is not False:
                errors.append(f"{source}.privacy.{field}: must be false; remediation: retain only reference metadata")
        if privacy.get("opaque_paths_only") is not True:
            errors.append(f"{source}.privacy.opaque_paths_only: must be true; remediation: retain only opaque locators")
    if not isinstance(data.get("stages"), list) or not data.get("stages"):
        errors.append(f"{source}.stages: must be a non-empty list; remediation: record each exchange stage")
    for index, stage in enumerate(data.get("stages", [])):
        if not isinstance(stage, dict):
            errors.append(f"{source}.stages[{index}]: must be an object; remediation: record stage metadata")
            continue
        stage_required = {"stage_id", "owner_repository", "source_commit", "command", "contract_version", "semantic_hash", "status", "terminal_status", "output_locator"}
        errors.extend(f"{source}.stages[{index}]: missing required field {field!r}; remediation: preserve stage provenance" for field in sorted(stage_required - set(stage)))
        if not isinstance(stage.get("source_commit"), str) or not SHA_PATTERN.fullmatch(stage.get("source_commit", "")):
            errors.append(f"{source}.stages[{index}].source_commit: must be a 40-character SHA; remediation: preserve immutable child provenance")
        if not isinstance(stage.get("output_locator"), str) or not stage.get("output_locator", "").startswith(f"run://{data.get('run_id', '')}/"):
            errors.append(f"{source}.stages[{index}].output_locator: must be scoped to run_id; remediation: use an opaque run locator")
        semantic_hash = stage.get("semantic_hash")
        if semantic_hash is not None and (not isinstance(semantic_hash, str) or not HASH_PATTERN.fullmatch(semantic_hash)):
            errors.append(f"{source}.stages[{index}].semantic_hash: malformed SHA-256; remediation: retain only bundle semantic hashes")
    try:
        _validate_strings(data)
    except ExchangeError as exc:
        errors.append(f"{source}: {exc}; remediation: retain metadata and opaque locators only")
    if isinstance(data, dict):
        stage_ids = [stage.get("stage_id") for stage in data.get("stages", []) if isinstance(stage, dict)]
        if len(stage_ids) != len(set(stage_ids)):
            errors.append(f"{source}.stages: duplicate stage_id; remediation: retain one terminal observation per stage")
        for index, stage in enumerate(data.get("stages", [])):
            if not isinstance(stage, dict):
                continue
            command = stage.get("command")
            if isinstance(command, str) and not SAFE_COMMAND_PATTERN.fullmatch(command):
                errors.append(f"{source}.stages[{index}].command contains shell control syntax; remediation: use an argument-list subprocess")
            if stage.get("status") == "PASSED" and stage.get("terminal_status") == "NOT_RUN":
                errors.append(f"{source}.stages[{index}] passed without a terminal status; remediation: record the observed child transition")
    return errors


def _manifest_entry(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in manifest.get("files", []):
        if isinstance(entry, dict) and entry.get("path") == name:
            return entry
    raise ExchangeError(f"child bundle manifest has no {name} entry")


def _bundle_metadata(bundle: Path, expected_entrypoint: str) -> tuple[str, str, str]:
    manifest = _load_yaml(bundle / "manifest.yaml")
    if manifest.get("entrypoint") != expected_entrypoint:
        raise ExchangeError("bundle entrypoint does not match the owned exchange contract")
    integrity = manifest.get("integrity") if isinstance(manifest.get("integrity"), dict) else {}
    file_set_hash = integrity.get("file_set_sha256")
    if not isinstance(file_set_hash, str) or not HASH_PATTERN.fullmatch(file_set_hash):
        raise ExchangeError("bundle file-set hash is missing or malformed")
    entry = _manifest_entry(manifest, expected_entrypoint)
    entry_hash = entry.get("sha256")
    if not isinstance(entry_hash, str) or not HASH_PATTERN.fullmatch(entry_hash):
        raise ExchangeError("bundle entry hash is missing or malformed")
    return str(manifest.get("bundle_id", "")), file_set_hash, entry_hash


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _extract_commit(source: Path, commit: str, target: Path) -> None:
    if not SHA_PATTERN.fullmatch(commit):
        raise ExchangeError("manifest exchange commit is not immutable")
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", commit], capture_output=True, check=False)
    if archive.returncode != 0:
        raise ExchangeError("manifest-pinned child archive is unavailable")
    target.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            for member in bundle.getmembers():
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ExchangeError("child archive contains an unsafe path")
            bundle.extractall(target)
    except (OSError, tarfile.TarError) as exc:
        raise ExchangeError("child archive extraction failed") from exc


def _verify_source(root: Path, commit: str) -> None:
    head = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    if head.returncode != 0 or head.stdout.strip() != commit:
        raise ExchangeError("child workspace does not match the manifest immutable commit")
    if dirty.stdout.strip():
        raise ExchangeError("child workspace is dirty; adjacent working trees are not accepted")


def _make_clean_fixture_checkout(root: Path, commit: str) -> None:
    init = subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], capture_output=True, text=True, check=False)
    if init.returncode != 0:
        raise ExchangeError("could not initialize the Git-external fixture checkout")
    for args in (("config", "user.email", "orchestrator@example.invalid"), ("config", "user.name", "Orchestration Fixture")):
        configured = _git(root, *args)
        if configured.returncode != 0:
            raise ExchangeError("could not configure the Git-external fixture checkout")
    staged = _git(root, "add", "--all")
    if staged.returncode != 0:
        raise ExchangeError("could not stage the Git-external fixture checkout")
    committed = _git(root, "commit", "-q", "-m", f"fixture {commit}")
    if committed.returncode != 0:
        raise ExchangeError("could not commit the Git-external fixture checkout")


def _commit_fixture_changes(root: Path, message: str) -> None:
    staged = _git(root, "add", "--all")
    if staged.returncode != 0:
        raise ExchangeError("could not stage generated fixture records")
    committed = _git(root, "commit", "-q", "-m", message)
    if committed.returncode != 0:
        raise ExchangeError("could not commit generated fixture records")


def _repo(manifest: dict[str, Any], repository_id: str) -> dict[str, Any]:
    for item in manifest.get("repositories", []):
        if isinstance(item, dict) and item.get("id") == repository_id:
            return item
    raise ExchangeError(f"manifest repository is missing: {repository_id}")


def _locator(run_id: str, suffix: str) -> str:
    return f"run://{run_id}/{suffix}"


def _display(command: str) -> str:
    return command


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    stage_id: str,
    display: str,
    timeout_seconds: int = 120,
    parser: Callable[[str], Any] | None = None,
) -> Any:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout_seconds)
    if completed.returncode != 0:
        raise StageFailure(stage_id, "CHILD_COMMAND_FAILED")
    if parser is None:
        return None
    try:
        return parser(completed.stdout.strip())
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise StageFailure(stage_id, "CHILD_OUTPUT_INVALID") from exc


def _json_output(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("child output is not an object")
    return parsed


def _stage(stage_id: str, repository: str, commit: str, command: str, contract: str | None, semantic_hash: str | None, status: str, terminal: str, locator: str, reason: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "stage_id": stage_id,
        "owner_repository": repository,
        "source_commit": commit,
        "command": command,
        "contract_version": contract,
        "semantic_hash": semantic_hash,
        "status": status,
        "terminal_status": terminal,
        "output_locator": locator,
    }
    if reason:
        value["reason_code"] = reason
    return value


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _prepare_research_fixture(root: Path, slug: str, generated_at: str) -> None:
    project = root / "projects" / slug
    fixture = root / "tests" / "fixtures" / "harmony"
    manifest_path = project / "manifest.yaml"
    manifest = _load_yaml(manifest_path)
    manifest["workflow_mode"] = "PRODUCTION_HANDOFF"
    project_meta = manifest.setdefault("project", {})
    project_meta.update({"status": "COMPLETE_WITH_GAPS", "version": "0.1.0", "updated_at": generated_at})
    manifest.setdefault("entry_points", {}).update({
        "production_hypotheses": "04_decisions/production-hypotheses.yaml",
        "hypothesis_comparison": "04_decisions/hypothesis-comparison.yaml",
        "prototype_plans": "05_production/prototype-plans.yaml",
        "production_handoff": "05_production/production-handoff.yaml",
        "production_change_requests": "06_governance/production-change-requests.yaml",
        "production_feedback_imports": "07_runtime/production-feedback-imports.jsonl",
    })
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    hypothesis_path = root / "tests" / "fixtures" / "schema-valid" / "production-hypothesis.json"
    prototype_path = root / "tests" / "fixtures" / "schema-valid" / "prototype-plan.json"
    hypothesis = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    hypothesis["single_hypothesis_rationale"] = "Only one fixture candidate preserves the adopted perceptual decision without weakening the intended experience."
    prototype = json.loads(prototype_path.read_text(encoding="utf-8"))
    (project / "04_decisions" / "production-hypotheses.yaml").write_text(yaml.safe_dump({"hypotheses": [hypothesis]}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (project / "04_decisions" / "hypothesis-comparison.yaml").write_text(yaml.safe_dump({"comparisons": []}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (project / "05_production" / "prototype-plans.yaml").write_text(yaml.safe_dump({"prototype_plans": [prototype]}, sort_keys=False, allow_unicode=True), encoding="utf-8")


def run_exchange(
    manifest: dict[str, Any],
    workspace_root: Path,
    output_root: Path,
    *,
    run_id: str,
    generated_at: str,
    research_project_slug: str = "harmony-study",
    production_project_slug: str = "production-smoke",
    handoff_id: str = "HO001",
    result_id: str = "PR001",
) -> dict[str, Any]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ExchangeError("run_id is not stable")
    if output_root.resolve() == ROOT or ROOT in output_root.resolve().parents:
        raise ExchangeError("exchange output root must be Git-external")
    research = _repo(manifest, "agentic-art-research")
    production = _repo(manifest, "agentic-art-production")
    research_source = (workspace_root / str(research["path"])).resolve()
    production_source = (workspace_root / str(production["path"])).resolve()
    _verify_source(research_source, str(research["observed_commit"]))
    _verify_source(production_source, str(production["observed_commit"]))
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / re.sub(r"[^A-Za-z0-9._-]+", "-", run_id)
    existing_evidence = run_dir / "exchange-evidence.json"
    if existing_evidence.is_file():
        try:
            previous = json.loads(existing_evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExchangeError("existing exchange evidence is unreadable; use a new run_id") from exc
        if validate_exchange_evidence(previous):
            raise ExchangeError("existing exchange evidence is invalid; use a new run_id")
        if previous.get("run_id") != run_id:
            raise ExchangeError("existing exchange evidence belongs to another run_id")
        return previous
    run_dir.mkdir()
    stages: list[dict[str, Any]] = []
    research_commit = str(research["observed_commit"])
    production_commit = str(production["observed_commit"])
    evidence_path = run_dir / "exchange-evidence.json"
    base = {
        "contract_version": "production-exchange-evidence/v1",
        "run_id": run_id,
        "mode": "immutable-networkless",
        "status": "FAILED",
        "stages": stages,
        "remote_operations": [],
        "child_mutations": [],
        "acceptance": {
            "research_handoff_exported": False,
            "production_handoff_accepted": False,
            "production_result_exported": False,
            "research_result_dry_run": False,
            "child_schema_not_copied": True,
            "adjacent_worktree_not_read": True,
            "external_effects_not_run": True,
        },
        "privacy": {"raw_bundle_stored": False, "raw_asset_body_stored": False, "sensitive_data_stored": False, "opaque_paths_only": True},
    }
    try:
        with tempfile.TemporaryDirectory(prefix="aap-exchange-", dir=run_dir) as temporary:
            temp_root = Path(temporary)
            research_root = temp_root / "research"
            production_root = temp_root / "production"
            _extract_commit(research_source, research_commit, research_root)
            _extract_commit(production_source, production_commit, production_root)
            research_project = f"project/{research_project_slug}"
            research_bundle = run_dir / "handoff"
            production_output = run_dir / "production-output"
            production_bundle = run_dir / "result"
            research_project_path = research_root / "projects" / research_project_slug
            _run_command(
                [sys.executable, "tools/new_project.py", research_project_slug, "--title", "Harmony Study", "--creator-id", "creator/fixture", "--root", str(research_root)],
                cwd=research_root,
                stage_id="research-project",
                display=_display("python3 tools/new_project.py PROJECT_SLUG --title HARMONY_STUDY --creator-id CREATOR --root RESEARCH_ROOT"),
            )
            fixture = research_root / "tests" / "fixtures" / "harmony"
            for source in sorted(fixture.rglob("*")):
                relative = source.relative_to(fixture)
                if source.is_dir() or relative in {Path("metadata.yaml"), Path("manifest.yaml")}:
                    continue
                destination = research_project_path / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            _prepare_research_fixture(research_root, research_project_slug, generated_at)
            _make_clean_fixture_checkout(research_root, research_commit)
            _run_command(
                [sys.executable, "tools/build_handoff.py", research_project, "--root", str(research_root), "--generated-at", generated_at, "--research-commit", research_commit, "--handoff-id", handoff_id, "--revision", "1"],
                cwd=research_root,
                stage_id="research-handoff-build",
                display=_display("python3 tools/build_handoff.py RESEARCH_PROJECT --root RESEARCH_ROOT --generated-at FIXED_TIME --research-commit RESEARCH_COMMIT --handoff-id HANDOFF_ID --revision 1"),
            )
            _commit_fixture_changes(research_root, "generated handoff fixture")
            _run_command(
                [sys.executable, "tools/export_handoff.py", research_project, "--root", str(research_root), "--output", str(research_bundle)],
                cwd=research_root,
                stage_id="research-handoff",
                display=_display("python3 tools/export_handoff.py RESEARCH_PROJECT --root RESEARCH_ROOT --output HANDOFF_OUTPUT"),
            )
            handoff_bundle_id, handoff_file_set_hash, handoff_entry_hash = _bundle_metadata(research_bundle, "production-handoff.yaml")
            stages.append(_stage("research-handoff", "agentic-art-research", research_commit, "python3 tools/export_handoff.py RESEARCH_PROJECT --root RESEARCH_ROOT --output HANDOFF_OUTPUT", "production-handoff/v1", handoff_file_set_hash, "PASSED", "HANDOFF_EXPORTED", _locator(run_id, "handoff")))
            base["acceptance"]["research_handoff_exported"] = True
            _run_command(
                [sys.executable, "tools/new_production.py", production_project_slug, "--handoff", str(research_bundle), "--output-root", str(production_output), "--format", "json"],
                cwd=production_root,
                stage_id="production-receipt",
                display=_display("python3 tools/new_production.py PRODUCTION_SLUG --handoff HANDOFF_OUTPUT --output-root PRODUCTION_OUTPUT --format json"),
            )
            production_project = production_output / "production" / production_project_slug
            stages.append(_stage("production-receipt", "agentic-art-production", production_commit, "python3 tools/new_production.py PRODUCTION_SLUG --handoff HANDOFF_OUTPUT --output-root PRODUCTION_OUTPUT --format json", "production-handoff/v1", handoff_entry_hash, "PASSED", "HANDOFF_ACCEPTED", _locator(run_id, "production/project")))
            base["acceptance"]["production_handoff_accepted"] = True
            for stage_id, args, display in (
                ("production-plan", ["tools/build_plan.py", "--project-root", str(production_project), "--format", "json"], "python3 tools/build_plan.py --project-root PRODUCTION_PROJECT --format json"),
                ("production-prototype", ["tools/build_prototype.py", "--project-root", str(production_project), "--format", "json"], "python3 tools/build_prototype.py --project-root PRODUCTION_PROJECT --format json"),
                ("production-runtime", ["tools/run_execution.py", "--project-root", str(production_project), "init", "--format", "json"], "python3 tools/run_execution.py --project-root PRODUCTION_PROJECT init --format json"),
            ):
                _run_command([sys.executable, *args], cwd=production_root, stage_id=stage_id, display=display)
                stages.append(_stage(stage_id, "agentic-art-production", production_commit, display, None, None, "PASSED", "PREPARED", _locator(run_id, "production/project")))
            result_id_value = _run_command(
                [sys.executable, "tools/build_result.py", "--project-root", str(production_project), "--result-id", result_id, "--generated-at", generated_at, "--production-commit", production_commit, "--format", "json"],
                cwd=production_root,
                stage_id="production-result-build",
                display="python3 tools/build_result.py --project-root PRODUCTION_PROJECT --result-id RESULT_ID --generated-at FIXED_TIME --production-commit PRODUCTION_COMMIT --format json",
                parser=_json_output,
            )
            stages.append(_stage("production-result-build", "agentic-art-production", production_commit, "python3 tools/build_result.py --project-root PRODUCTION_PROJECT --result-id RESULT_ID --generated-at FIXED_TIME --production-commit PRODUCTION_COMMIT --format json", "production-result/v1", f"sha256:{result_id_value.get('content_sha256', '').split(':')[-1]}" if isinstance(result_id_value.get("content_sha256"), str) and HASH_PATTERN.fullmatch(result_id_value["content_sha256"]) else None, "PASSED", "PREPARED", _locator(run_id, "production/project/result")))
            result_summary = _run_command(
                [sys.executable, "tools/export_result.py", "--project-root", str(production_project), "--output", str(production_bundle), "--format", "json"],
                cwd=production_root,
                stage_id="production-result",
                display="python3 tools/export_result.py --project-root PRODUCTION_PROJECT --output RESULT_OUTPUT --format json",
                parser=_json_output,
            )
            result_bundle_id, result_file_set_hash, result_entry_hash = _bundle_metadata(production_bundle, "production-result.yaml")
            stages.append(_stage("production-result", "agentic-art-production", production_commit, "python3 tools/export_result.py --project-root PRODUCTION_PROJECT --output RESULT_OUTPUT --format json", "production-result/v1", result_file_set_hash, "PASSED", "RESULT_EXPORTED", _locator(run_id, "result")))
            base["acceptance"]["production_result_exported"] = True
            dry_run = _run_command(
                [sys.executable, "tools/import_production_result.py", str(production_bundle / "production-result.yaml"), "--dry-run", "--root", str(research_root)],
                cwd=research_root,
                stage_id="research-result-dry-run",
                display="python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --dry-run --root RESEARCH_ROOT",
                parser=_json_output,
            )
            if dry_run.get("status") != "DRY_RUN":
                raise StageFailure("research-result-dry-run", "RESEARCH_DRY_RUN_NOT_TERMINAL")
            stages.append(_stage("research-result-dry-run", "agentic-art-research", research_commit, "python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --dry-run --root RESEARCH_ROOT", "production-result/v1", result_entry_hash, "PASSED", "RESULT_DRY_RUN", _locator(run_id, "research/result-dry-run")))
            base["acceptance"]["research_result_dry_run"] = True
            base["status"] = "PASSED"
    except StageFailure as exc:
        stages.append(_stage(exc.stage_id, "agentic-art-research" if exc.stage_id.startswith("research") else "agentic-art-production", research_commit if exc.stage_id.startswith("research") else production_commit, f"stage:{exc.stage_id}", None, None, "FAILED", "NOT_RUN", _locator(run_id, "failed"), exc.reason_code))
    except (OSError, subprocess.SubprocessError, ExchangeError) as exc:
        base["status"] = "BLOCKED"
        stages.append(_stage("preflight", "agentic-art-orchestration", "0" * 40, "parent preflight", None, None, "BLOCKED", "NOT_RUN", _locator(run_id, "blocked"), "PREFLIGHT_BLOCKED"))
    evidence = base
    errors = validate_exchange_evidence(evidence)
    if errors:
        raise ExchangeError("generated exchange evidence is invalid: " + " | ".join(errors[:5]))
    _write_evidence(evidence_path, evidence)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/repositories.yaml")
    parser.add_argument("--check", action="store_true", help="validate an existing evidence JSON")
    parser.add_argument("--evidence", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.check:
            if not args.evidence:
                raise ExchangeError("--check requires --evidence")
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            errors = validate_exchange_evidence(evidence, str(args.evidence))
            if errors:
                print(json.dumps({"status": "FAILED", "errors": errors}, ensure_ascii=False, sort_keys=True))
                return 2
            print(json.dumps({"status": "PASSED", "evidence": str(args.evidence.name)}, ensure_ascii=False, sort_keys=True))
            return 0
        manifest = _load_yaml(args.manifest)
        evidence = run_exchange(manifest, args.workspace_root, args.output_root, run_id=args.run_id, generated_at=args.generated_at)
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        return 0 if evidence["status"] == "PASSED" else 2
    except (OSError, ValueError, ExchangeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": "EXCHANGE_EXECUTION", "detail": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
