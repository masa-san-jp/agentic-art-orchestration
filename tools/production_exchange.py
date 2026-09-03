#!/usr/bin/env python3
"""Run the parent-owned, reference-only Research/Production exchange."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/production-exchange-evidence.schema.json"
E2E_SCHEMA_PATH = ROOT / "schemas/production-exchange-e2e.schema.json"
E2E_OUTPUT_PATH = ROOT / "data/production-exchange.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
SAFE_COMMAND_PATTERN = re.compile(r"^[^;|&`\r\n]+$")
FORBIDDEN_TEXT = re.compile(r"(?i)(PRIVATE_RAW|RESTRICTED|credential|signed[_ -]?url|raw[_ -]?asset)")
STAGE_CONTRACTS = {None, "production-handoff/v1", "production-result/v1", "research-signal-export/v1"}


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
        "research_feedback_applied",
        "viewer_record_appended",
        "viewer_replay_idempotent",
        "viewer_contract_validated",
        "viewer_signal_exported",
        "research_signal_exported",
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
        if stage.get("contract_version") not in STAGE_CONTRACTS:
            errors.append(f"{source}.stages[{index}].contract_version: unsupported child contract; remediation: preserve the owning child contract version")
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


def validate_exchange_e2e(data: dict[str, Any], source: str = "production-exchange-e2e") -> list[str]:
    """Validate the parent-owned E2E summary without retaining child payloads."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{source}: E2E report must be an object; remediation: preserve the sanitized E2E envelope"]
    required = {"contract_version", "run_id", "network", "status", "normal_exchange", "scenarios", "acceptance", "remote_operations", "child_mutations"}
    errors.extend(
        f"{source}: missing required field {field!r}; remediation: preserve the E2E terminal-state summary"
        for field in sorted(required - set(data))
    )
    if data.get("contract_version") != "production-exchange-e2e/v1":
        errors.append(f"{source}.contract_version: unsupported contract; remediation: use production-exchange-e2e/v1")
    if data.get("network") != "disabled":
        errors.append(f"{source}.network: must be disabled; remediation: run only the networkless E2E")
    if data.get("status") != "PASSED":
        errors.append(f"{source}.status: E2E qualification did not pass; remediation: preserve each failure terminal state")
    if data.get("remote_operations") != [] or data.get("child_mutations") != []:
        errors.append(f"{source}: remote or child mutation was recorded; remediation: keep E2E read-only")
    normal = data.get("normal_exchange")
    if not isinstance(normal, dict):
        errors.append(f"{source}.normal_exchange: must be an object; remediation: record the clean exchange summary")
    else:
        if normal.get("status") != "PASSED":
            errors.append(f"{source}.normal_exchange.status: clean exchange did not pass; remediation: fix the clean path")
        if not isinstance(normal.get("evidence_sha256"), str) or not HASH_PATTERN.fullmatch(normal["evidence_sha256"]):
            errors.append(f"{source}.normal_exchange.evidence_sha256: malformed hash; remediation: retain only a summary hash")
        if not isinstance(normal.get("stage_count"), int) or normal["stage_count"] < 1:
            errors.append(f"{source}.normal_exchange.stage_count: must be positive; remediation: record observed stages")
        if "NOT_RUN" not in normal.get("result_statuses", []) and "EXTERNAL_VALIDATION_REQUIRED" not in normal.get("result_statuses", []):
            errors.append(f"{source}.normal_exchange.result_statuses: unperformed work was not preserved; remediation: keep NOT_RUN or EXTERNAL_VALIDATION_REQUIRED")
        if normal.get("external_validation_required") is not True:
            errors.append(f"{source}.normal_exchange.external_validation_required: must be true; remediation: preserve unperformed external validation")
        if normal.get("research_result_dry_run") is not True:
            errors.append(f"{source}.normal_exchange.research_result_dry_run: must be true; remediation: do not apply into the child repo")
    scenarios = data.get("scenarios")
    expected = {"clean", "tamper", "stale", "incompatible", "dirty-source", "replay"}
    if not isinstance(scenarios, list):
        errors.append(f"{source}.scenarios: must be a list; remediation: record every required terminal case")
        scenarios = []
    scenario_ids = {item.get("scenario_id") for item in scenarios if isinstance(item, dict)}
    if len(scenarios) != len(expected) or scenario_ids != expected:
        errors.append(f"{source}.scenarios: expected terminal cases are {sorted(expected)}; remediation: preserve all E2E cases")
    required_cases = {
        "clean": ("PASSED", "COMPLETE"),
        "tamper": ("FAILED", "FAILED"),
        "stale": ("BLOCKED", "BLOCKED"),
        "incompatible": ("FAILED", "FAILED"),
        "dirty-source": ("BLOCKED", "BLOCKED"),
        "replay": ("PASSED", "REPLAYED"),
    }
    for item in scenarios:
        if not isinstance(item, dict):
            errors.append(f"{source}.scenarios: every case must be an object; remediation: record status and terminal_status")
            continue
        scenario_id = item.get("scenario_id")
        if scenario_id in required_cases:
            expected_status, expected_terminal = required_cases[scenario_id]
            if item.get("status") != expected_status or item.get("terminal_status") != expected_terminal:
                errors.append(f"{source}.scenarios[{scenario_id}]: unexpected terminal state; remediation: preserve fail-closed status")
            if not isinstance(item.get("reason_code"), str) or not re.fullmatch(r"[A-Z0-9_:-]+", item["reason_code"]):
                errors.append(f"{source}.scenarios[{scenario_id}].reason_code: required sanitized reason; remediation: do not retain child error text")
    acceptance = data.get("acceptance")
    required_acceptance = {
        "clean_exchange",
        "external_validation_unperformed",
        "research_result_dry_run",
        "research_feedback_applied",
        "viewer_record_appended",
        "viewer_replay_idempotent",
        "viewer_contract_validated",
        "viewer_signal_exported",
        "research_signal_exported",
        "tamper_terminal",
        "stale_terminal",
        "incompatible_terminal",
        "dirty_source_terminal",
        "replay_idempotent",
        "no_child_mutation",
        "no_remote_mutation",
    }
    if not isinstance(acceptance, dict):
        errors.append(f"{source}.acceptance: must be an object; remediation: record all E2E assertions")
    else:
        for field in sorted(required_acceptance):
            if acceptance.get(field) is not True:
                errors.append(f"{source}.acceptance.{field}: must be true; remediation: prove the terminal-state invariant")
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
    cloned = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-local",
            "--no-checkout",
            str(source),
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if cloned.returncode != 0:
        raise ExchangeError("manifest-pinned child archive is unavailable")
    checked_out = subprocess.run(
        ["git", "-C", str(target), "checkout", "--quiet", "--detach", commit],
        capture_output=True,
        text=True,
        check=False,
    )
    if checked_out.returncode != 0:
        raise ExchangeError("manifest-pinned child commit is unavailable")
    head = _git(target, "rev-parse", "HEAD")
    clean = _git(target, "status", "--porcelain", "--untracked-files=all")
    if head.returncode != 0 or head.stdout.strip() != commit or clean.stdout.strip():
        raise ExchangeError("manifest-pinned child clone is not an exact clean commit")


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


def _text_output(value: str) -> str:
    if not value:
        raise ValueError("child output is empty")
    return value


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


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _run_directory(output_root: Path, run_id: str) -> Path:
    return output_root / re.sub(r"[^A-Za-z0-9._-]+", "-", run_id)


def _result_statuses(result_path: Path) -> tuple[list[str], bool]:
    result = _load_yaml(result_path)
    statuses = {
        item.get("result")
        for item in result.get("test_results", [])
        if isinstance(item, dict) and isinstance(item.get("result"), str)
    }
    required = any(
        isinstance(item, dict) and item.get("external_validation_status") == "REQUIRED"
        for item in result.get("test_results", [])
    )
    if required:
        statuses.add("EXTERNAL_VALIDATION_REQUIRED")
    return sorted(statuses), required


def _manifest_hashes(bundle: Path, entrypoint: str) -> tuple[str, str]:
    manifest = _load_yaml(bundle / "manifest.yaml")
    integrity = manifest.get("integrity") if isinstance(manifest.get("integrity"), dict) else {}
    file_set_hash = integrity.get("file_set_sha256")
    entry_hash = next(
        (
            item.get("sha256")
            for item in manifest.get("files", [])
            if isinstance(item, dict) and item.get("path") == entrypoint
        ),
    )
    if not isinstance(file_set_hash, str) or not HASH_PATTERN.fullmatch(file_set_hash):
        raise ExchangeError("E2E bundle file-set hash is missing")
    if not isinstance(entry_hash, str) or not HASH_PATTERN.fullmatch(entry_hash):
        raise ExchangeError("E2E bundle entry hash is missing")
    return file_set_hash, entry_hash


def _validate_exchange_run_artifacts(run_dir: Path, evidence: dict[str, Any]) -> list[str]:
    """Check evidence hashes against Git-external bundle manifests."""
    errors: list[str] = []
    try:
        handoff_file_set, handoff_entry = _manifest_hashes(run_dir / "handoff", "production-handoff.yaml")
        result_file_set, result_entry = _manifest_hashes(run_dir / "result", "production-result.yaml")
    except (OSError, KeyError, TypeError, ExchangeError) as exc:
        return [f"exchange run artifacts unavailable: {type(exc).__name__}"]
    expected = {
        "research-handoff": handoff_file_set,
        "production-receipt": handoff_entry,
        "production-result": result_file_set,
        "research-result-dry-run": result_entry,
    }
    for stage in evidence.get("stages", []):
        if stage.get("stage_id") in expected and stage.get("semantic_hash") != expected[stage["stage_id"]]:
            errors.append(f"{stage['stage_id']}: semantic hash mismatch")
    return errors


def _scenario(scenario_id: str, status: str, terminal_status: str, reason_code: str) -> dict[str, str]:
    return {
        "scenario_id": scenario_id,
        "status": status,
        "terminal_status": terminal_status,
        "reason_code": reason_code,
    }


def run_exchange_e2e(
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
    child_python: str | None = None,
) -> dict[str, Any]:
    """Execute the clean exchange and qualify sanitized terminal-state scenarios."""
    clean_run_id = f"{run_id}:clean"
    clean = run_exchange(
        manifest,
        workspace_root,
        output_root,
        run_id=clean_run_id,
        generated_at=generated_at,
        research_project_slug=research_project_slug,
        production_project_slug=production_project_slug,
        handoff_id=handoff_id,
        result_id=result_id,
        child_python=child_python,
    )
    clean_dir = _run_directory(output_root, clean_run_id)
    result_statuses, external_validation_required = _result_statuses(clean_dir / "result" / "production-result.yaml")
    clean_bytes = (clean_dir / "exchange-evidence.json").read_bytes()

    tampered = copy.deepcopy(clean)
    tampered["stages"][0]["semantic_hash"] = "sha256:" + "0" * 64
    if not validate_exchange_evidence(tampered) == []:
        raise ExchangeError("tamper scenario did not preserve a structurally valid envelope")
    if not _validate_exchange_run_artifacts(clean_dir, tampered):
        raise ExchangeError("tamper scenario did not fail closed")

    stale_manifest = copy.deepcopy(manifest)
    _repo(stale_manifest, "agentic-art-research")["observed_commit"] = "0" * 40
    try:
        run_exchange(stale_manifest, workspace_root, output_root, run_id=f"{run_id}:stale", generated_at=generated_at)
    except ExchangeError:
        stale_terminal = _scenario("stale", "BLOCKED", "BLOCKED", "SOURCE_STALE")
    else:
        raise ExchangeError("stale source scenario did not block")

    incompatible = copy.deepcopy(clean)
    incompatible["stages"][0]["contract_version"] = "production-handoff/v99"
    if not validate_exchange_evidence(incompatible):
        raise ExchangeError("incompatible schema scenario did not fail closed")

    research = _repo(manifest, "agentic-art-research")
    research_source = (workspace_root / str(research["path"])).resolve()
    with tempfile.TemporaryDirectory(prefix="aap-exchange-dirty-") as dirty_parent:
        dirty_root = Path(dirty_parent) / "research"
        cloned = subprocess.run(
            ["git", "clone", "--no-local", "--quiet", str(research_source), str(dirty_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if cloned.returncode != 0:
            raise ExchangeError("dirty source scenario could not prepare an external clone")
        (dirty_root / ".e2e-dirty-marker").write_text("synthetic dirty source\n", encoding="utf-8")
        try:
            _verify_source(dirty_root, str(research["observed_commit"]))
        except ExchangeError:
            dirty_terminal = _scenario("dirty-source", "BLOCKED", "BLOCKED", "SOURCE_DIRTY")
        else:
            raise ExchangeError("dirty source scenario did not block")

    replay = run_exchange(
        manifest,
        workspace_root,
        output_root,
        run_id=clean_run_id,
        generated_at=generated_at,
        research_project_slug=research_project_slug,
        production_project_slug=production_project_slug,
        handoff_id=handoff_id,
        result_id=result_id,
        child_python=child_python,
    )
    if clean_bytes != (clean_dir / "exchange-evidence.json").read_bytes() or replay != clean:
        raise ExchangeError("replay scenario changed an existing exchange result")

    report = {
        "contract_version": "production-exchange-e2e/v1",
        "run_id": run_id,
        "network": "disabled",
        "status": "PASSED",
        "normal_exchange": {
            "status": clean["status"],
            "evidence_sha256": "sha256:" + hashlib.sha256(clean_bytes).hexdigest(),
            "stage_count": len(clean["stages"]),
            "result_statuses": result_statuses,
            "external_validation_required": external_validation_required or "NOT_RUN" in result_statuses,
            "research_result_dry_run": clean["acceptance"]["research_result_dry_run"],
        },
        "scenarios": [
            _scenario("clean", "PASSED", "COMPLETE", "CLEAN_EXCHANGE"),
            _scenario("tamper", "FAILED", "FAILED", "TAMPER_DETECTED"),
            stale_terminal,
            _scenario("incompatible", "FAILED", "FAILED", "UNSUPPORTED_CONTRACT"),
            dirty_terminal,
            _scenario("replay", "PASSED", "REPLAYED", "REPLAY_IDEMPOTENT"),
        ],
        "acceptance": {
            "clean_exchange": True,
            "external_validation_unperformed": True,
            "research_result_dry_run": True,
            "research_feedback_applied": clean["acceptance"]["research_feedback_applied"],
            "viewer_record_appended": clean["acceptance"]["viewer_record_appended"],
            "viewer_replay_idempotent": clean["acceptance"]["viewer_replay_idempotent"],
            "viewer_contract_validated": clean["acceptance"]["viewer_contract_validated"],
            "viewer_signal_exported": clean["acceptance"]["viewer_signal_exported"],
            "research_signal_exported": clean["acceptance"]["research_signal_exported"],
            "tamper_terminal": True,
            "stale_terminal": True,
            "incompatible_terminal": True,
            "dirty_source_terminal": True,
            "replay_idempotent": True,
            "no_child_mutation": clean["child_mutations"] == [],
            "no_remote_mutation": clean["remote_operations"] == [],
        },
        "remote_operations": [],
        "child_mutations": [],
    }
    errors = validate_exchange_e2e(report)
    if errors:
        raise ExchangeError("generated E2E report is invalid: " + " | ".join(errors[:5]))
    return report


def _prepare_research_fixture(
    work_root: Path,
    protocol_root: Path,
    slug: str,
    generated_at: str,
    *,
    result_id: str,
    theme: Mapping[str, Any] | None = None,
    project_title: str | None = None,
) -> None:
    project = work_root / "projects" / slug
    fixture = protocol_root / "tests" / "fixtures" / "harmony"
    manifest_path = project / "manifest.yaml"
    # The fixture is copied under a fresh canonical project ID for each
    # batch item.  Rewrite only the fixture's project-reference IDs; the
    # child repository remains an immutable source checkout and the full
    # fixture stays in the Git-external exchange staging area.
    source_project_id = "project/harmony-study"
    target_project_id = f"project/{slug}"
    for path in project.rglob("*"):
        if not path.is_file():
            continue
        try:
            rendered = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ExchangeError(f"cannot normalize research fixture: {path.name}") from exc
        if source_project_id in rendered:
            path.write_text(rendered.replace(source_project_id, target_project_id), encoding="utf-8")
    manifest = _load_yaml(manifest_path)
    manifest["workflow_mode"] = "PRODUCTION_HANDOFF"
    project_meta = manifest.setdefault("project", {})
    project_meta.update({"status": "COMPLETE_WITH_GAPS", "version": "0.1.0", "updated_at": generated_at})
    if project_title:
        project_meta["title"] = project_title
    manifest.setdefault("entry_points", {}).update({
        "production_hypotheses": "04_decisions/production-hypotheses.yaml",
        "hypothesis_comparison": "04_decisions/hypothesis-comparison.yaml",
        "prototype_plans": "05_production/prototype-plans.yaml",
        "production_handoff": "05_production/production-handoff.yaml",
        "production_change_requests": "06_governance/production-change-requests.yaml",
        "production_feedback_imports": "07_runtime/production-feedback-imports.jsonl",
    })
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    hypothesis_path = protocol_root / "tests" / "fixtures" / "schema-valid" / "production-hypothesis.json"
    prototype_path = protocol_root / "tests" / "fixtures" / "schema-valid" / "prototype-plan.json"
    hypothesis = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    hypothesis["single_hypothesis_rationale"] = "Only one fixture candidate preserves the adopted perceptual decision without weakening the intended experience."
    for uncertainty in hypothesis.get("uncertainties", []):
        if isinstance(uncertainty, dict):
            uncertainty["external_validation_reason"] = "Record the required synthetic validation evidence before production completion."
    prototype = json.loads(prototype_path.read_text(encoding="utf-8"))
    for task in prototype.get("tasks", []):
        if isinstance(task, dict):
            # Batch qualification exercises the read-only planning path.  The
            # source fixture intentionally omits this optional classification,
            # which would otherwise conservatively create physical approval
            # requirements for a plan-only batch.
            task["effect_type"] = "READ_ONLY"
    (project / "04_decisions" / "production-hypotheses.yaml").write_text(yaml.safe_dump({"hypotheses": [hypothesis]}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (project / "04_decisions" / "hypothesis-comparison.yaml").write_text(yaml.safe_dump({"comparisons": []}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (project / "05_production" / "prototype-plans.yaml").write_text(yaml.safe_dump({"prototype_plans": [prototype]}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    acceptance_path = project / "05_production" / "acceptance-tests.yaml"
    acceptance = _load_yaml(acceptance_path)
    acceptance_tests = acceptance.get("acceptance_tests")
    if not isinstance(acceptance_tests, list):
        raise ExchangeError("research fixture acceptance-tests.yaml has no acceptance_tests list")
    viewer_response = {
        "source_kind": "measured",
        "requirement_id": "RQ001",
        "presentation_mode": "gallery",
        "requirement_tags": ["clarity", "spatial"],
        "sample_size": 3,
        "outcome_counts": {"pass": 2, "fail": 1, "unknown": 0},
        "evidence_refs": [f"production-result:{result_id}#AT001"],
        "certainty": "medium",
        "consent_scope": "aggregate-only",
    }
    target_test = next((item for item in acceptance_tests if isinstance(item, dict) and item.get("id") == "AT001"), None)
    if target_test is None:
        raise ExchangeError("research fixture does not declare acceptance test AT001")
    target_test["viewer_response"] = viewer_response
    acceptance_path.write_text(yaml.safe_dump(acceptance, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (project / "05_production" / "reference-categories.yaml").write_text(
        yaml.safe_dump(
            {
                "categories": {
                    "DC001": ["CONCEPT"],
                    "IN001": ["VISUAL", "METHOD"],
                    "EV001": ["CONCEPT", "VISUAL", "METHOD"],
                    "EV002": ["CONCEPT", "VISUAL", "METHOD"],
                }
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    if theme is not None:
        if not isinstance(theme, Mapping):
            raise ExchangeError("theme must be a metadata-only mapping")
        brief_path = project / "05_production" / "production-brief.yaml"
        brief = _load_yaml(brief_path)
        for key in ("completion_image", "theme", "message", "concept", "research_summary"):
            if key in theme:
                brief[key] = copy.deepcopy(theme[key])
        brief_path.write_text(yaml.safe_dump(brief, sort_keys=False, allow_unicode=True), encoding="utf-8")
        visual_language = theme.get("visual_language")
        if visual_language is not None:
            if not isinstance(visual_language, Mapping):
                raise ExchangeError("theme.visual_language must be a metadata-only mapping")
            visual_path = project / "05_production" / "visual-language.yaml"
            visual_path.write_text(yaml.safe_dump(copy.deepcopy(dict(visual_language)), sort_keys=False, allow_unicode=True), encoding="utf-8")
        direction = project / "05_production" / "creative-direction.md"
        if direction.is_file() and project_title:
            direction.write_text(direction.read_text(encoding="utf-8").replace("Harmony Study", project_title), encoding="utf-8")


def run_exchange(
    manifest: dict[str, Any],
    workspace_root: Path,
    output_root: Path,
    *,
    run_id: str,
    generated_at: str,
    research_project_slug: str = "harmony-study",
    production_project_slug: str = "production-smoke",
    research_project_title: str = "Harmony Study",
    theme: Mapping[str, Any] | None = None,
    handoff_id: str = "HO001",
    result_id: str = "PR001",
    child_python: str | None = None,
    research_output_root: Path | None = None,
    production_output_root: Path | None = None,
) -> dict[str, Any]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ExchangeError("run_id is not stable")
    if output_root.resolve() == ROOT or ROOT in output_root.resolve().parents:
        raise ExchangeError("exchange output root must be Git-external")
    research = _repo(manifest, "agentic-art-research")
    production = _repo(manifest, "agentic-art-production")
    viewer = _repo(manifest, "viewer-response-notes")
    research_source = (workspace_root / str(research["path"])).resolve()
    production_source = (workspace_root / str(production["path"])).resolve()
    viewer_source = (workspace_root / str(viewer["path"])).resolve()
    _verify_source(research_source, str(research["observed_commit"]))
    _verify_source(production_source, str(production["observed_commit"]))
    _verify_source(viewer_source, str(viewer["observed_commit"]))
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
    viewer_commit = str(viewer["observed_commit"])
    child_python = child_python or sys.executable
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
            "research_feedback_applied": False,
            "viewer_record_appended": False,
            "viewer_replay_idempotent": False,
            "viewer_contract_validated": False,
            "viewer_signal_exported": False,
            "research_signal_exported": False,
            "child_schema_not_copied": True,
            "adjacent_worktree_not_read": True,
            "external_effects_not_run": True,
        },
        "privacy": {"raw_bundle_stored": False, "raw_asset_body_stored": False, "sensitive_data_stored": False, "opaque_paths_only": True},
    }
    try:
        with tempfile.TemporaryDirectory(prefix="aap-exchange-", dir=run_dir) as temporary:
            temp_root = Path(temporary)
            research_protocol = temp_root / "research-protocol"
            research_work = temp_root / "research-work"
            production_root = temp_root / "production"
            viewer_root = temp_root / "viewer"
            _extract_commit(research_source, research_commit, research_protocol)
            _extract_commit(production_source, production_commit, production_root)
            _extract_commit(viewer_source, viewer_commit, viewer_root)
            research_work.mkdir()
            # Research's isolated work-root contract still needs the
            # protocol-owned config/schema snapshots for validation and the
            # read-only result preview.  They stay in this disposable child
            # staging area and never enter the parent repository or bundles.
            for name in ("config", "schemas"):
                shutil.copytree(research_protocol / name, research_work / name)
            research_project = f"project/{research_project_slug}"
            research_bundle = run_dir / "handoff"
            production_output = run_dir / "production-output"
            production_bundle = run_dir / "result"
            research_project_path = research_work / "projects" / research_project_slug
            _run_command(
                [child_python, "tools/new_project.py", research_project_slug, "--title", research_project_title, "--creator-id", "creator/fixture", "--work-root", str(research_work), "--protocol-root", str(research_protocol)],
                cwd=research_protocol,
                stage_id="research-project",
                display=_display("python3 tools/new_project.py PROJECT_SLUG --title HARMONY_STUDY --creator-id CREATOR --work-root RESEARCH_WORK --protocol-root RESEARCH_PROTOCOL"),
            )
            fixture = research_protocol / "tests" / "fixtures" / "harmony"
            for source in sorted(fixture.rglob("*")):
                relative = source.relative_to(fixture)
                if source.is_dir() or relative in {Path("metadata.yaml"), Path("manifest.yaml")}:
                    continue
                destination = research_project_path / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            _prepare_research_fixture(research_work, research_protocol, research_project_slug, generated_at, result_id=result_id, theme=theme, project_title=research_project_title)
            _run_command(
                [child_python, "tools/build_handoff.py", research_project, "--work-root", str(research_work), "--protocol-root", str(research_protocol), "--generated-at", generated_at, "--research-commit", research_commit, "--handoff-id", handoff_id, "--revision", "1"],
                cwd=research_protocol,
                stage_id="research-handoff-build",
                display=_display("python3 tools/build_handoff.py RESEARCH_PROJECT --work-root RESEARCH_WORK --protocol-root RESEARCH_PROTOCOL --generated-at FIXED_TIME --research-commit RESEARCH_COMMIT --handoff-id HANDOFF_ID --revision 1"),
            )
            _run_command(
                [child_python, "tools/export_handoff.py", research_project, "--work-root", str(research_work), "--protocol-root", str(research_protocol), "--output", str(research_bundle)],
                cwd=research_protocol,
                stage_id="research-handoff",
                display=_display("python3 tools/export_handoff.py RESEARCH_PROJECT --work-root RESEARCH_WORK --protocol-root RESEARCH_PROTOCOL --output HANDOFF_OUTPUT"),
            )
            handoff_bundle_id, handoff_file_set_hash, handoff_entry_hash = _bundle_metadata(research_bundle, "production-handoff.yaml")
            stages.append(_stage("research-handoff", "agentic-art-research", research_commit, "python3 tools/export_handoff.py RESEARCH_PROJECT --root RESEARCH_ROOT --output HANDOFF_OUTPUT", "production-handoff/v1", handoff_file_set_hash, "PASSED", "HANDOFF_EXPORTED", _locator(run_id, "handoff")))
            base["acceptance"]["research_handoff_exported"] = True
            _run_command(
                [child_python, "tools/new_production.py", production_project_slug, "--handoff", str(research_bundle), "--output-root", str(production_output), "--format", "json"],
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
                _run_command([child_python, *args], cwd=production_root, stage_id=stage_id, display=display)
                stages.append(_stage(stage_id, "agentic-art-production", production_commit, display, None, None, "PASSED", "PREPARED", _locator(run_id, "production/project")))
            result_id_value = _run_command(
                [child_python, "tools/build_result.py", "--project-root", str(production_project), "--result-id", result_id, "--generated-at", generated_at, "--target-state", "BLOCKED", "--production-commit", production_commit, "--format", "json"],
                cwd=production_root,
                stage_id="production-result-build",
                display="python3 tools/build_result.py --project-root PRODUCTION_PROJECT --result-id RESULT_ID --generated-at FIXED_TIME --target-state BLOCKED --production-commit PRODUCTION_COMMIT --format json",
                parser=_json_output,
            )
            stages.append(_stage("production-result-build", "agentic-art-production", production_commit, "python3 tools/build_result.py --project-root PRODUCTION_PROJECT --result-id RESULT_ID --generated-at FIXED_TIME --target-state BLOCKED --production-commit PRODUCTION_COMMIT --format json", "production-result/v1", f"sha256:{result_id_value.get('content_sha256', '').split(':')[-1]}" if isinstance(result_id_value.get("content_sha256"), str) and HASH_PATTERN.fullmatch(result_id_value["content_sha256"]) else None, "PASSED", "PREPARED", _locator(run_id, "production/project/result")))
            result_summary = _run_command(
                [child_python, "tools/export_result.py", "--project-root", str(production_project), "--output", str(production_bundle), "--format", "json"],
                cwd=production_root,
                stage_id="production-result",
                display="python3 tools/export_result.py --project-root PRODUCTION_PROJECT --output RESULT_OUTPUT --format json",
                parser=_json_output,
            )
            result_bundle_id, result_file_set_hash, result_entry_hash = _bundle_metadata(production_bundle, "production-result.yaml")
            stages.append(_stage("production-result", "agentic-art-production", production_commit, "python3 tools/export_result.py --project-root PRODUCTION_PROJECT --output RESULT_OUTPUT --format json", "production-result/v1", result_file_set_hash, "PASSED", "RESULT_EXPORTED", _locator(run_id, "result")))
            base["acceptance"]["production_result_exported"] = True
            dry_run = _run_command(
                [child_python, "tools/import_production_result.py", str(production_bundle / "production-result.yaml"), "--dry-run", "--root", str(research_work), "--viewer-root", str(viewer_root)],
                cwd=research_protocol,
                stage_id="research-result-dry-run",
                display="python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --dry-run --root RESEARCH_WORK --viewer-root VIEWER_ROOT",
                parser=_json_output,
            )
            if dry_run.get("status") != "DRY_RUN":
                raise StageFailure("research-result-dry-run", "RESEARCH_DRY_RUN_NOT_TERMINAL")
            stages.append(_stage("research-result-dry-run", "agentic-art-research", research_commit, "python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --dry-run --root RESEARCH_ROOT --viewer-root VIEWER_ROOT", "production-result/v1", result_entry_hash, "PASSED", "RESULT_DRY_RUN", _locator(run_id, "research/result-dry-run")))
            base["acceptance"]["research_result_dry_run"] = True
            applied = _run_command(
                [child_python, "tools/import_production_result.py", str(production_bundle / "production-result.yaml"), "--apply", "--root", str(research_work), "--viewer-root", str(viewer_root)],
                cwd=research_protocol,
                stage_id="research-feedback-apply",
                display="python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --apply --root RESEARCH_WORK --viewer-root VIEWER_ROOT",
                parser=_json_output,
            )
            if applied.get("status") != "APPLIED" or applied.get("viewer_records_added") != 1:
                raise StageFailure("research-feedback-apply", "VIEWER_RECORD_NOT_APPENDED")
            stages.append(_stage("research-feedback-apply", "agentic-art-research", research_commit, "python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --apply --root RESEARCH_ROOT --viewer-root VIEWER_ROOT", "production-result/v1", result_entry_hash, "PASSED", "FEEDBACK_APPLIED", _locator(run_id, "research/feedback-apply")))
            base["acceptance"]["research_feedback_applied"] = True
            base["acceptance"]["viewer_record_appended"] = True
            replay_apply = _run_command(
                [child_python, "tools/import_production_result.py", str(production_bundle / "production-result.yaml"), "--apply", "--root", str(research_work), "--viewer-root", str(viewer_root)],
                cwd=research_protocol,
                stage_id="research-feedback-replay",
                display="python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --apply --root RESEARCH_WORK --viewer-root VIEWER_ROOT",
                parser=_json_output,
            )
            if replay_apply.get("status") != "ALREADY_APPLIED" or replay_apply.get("viewer_records_added") != 0:
                raise StageFailure("research-feedback-replay", "VIEWER_REPLAY_NOT_IDEMPOTENT")
            stages.append(_stage("research-feedback-replay", "agentic-art-research", research_commit, "python3 tools/import_production_result.py RESULT_OUTPUT/production-result.yaml --apply --root RESEARCH_ROOT --viewer-root VIEWER_ROOT", "production-result/v1", result_entry_hash, "PASSED", "REPLAYED", _locator(run_id, "research/feedback-replay")))
            base["acceptance"]["viewer_replay_idempotent"] = True
            viewer_records_path = viewer_root / "records" / "viewer-response-records.jsonl"
            _run_command(
                [child_python, "tools/validate.py", "--check"],
                cwd=viewer_root,
                stage_id="viewer-validation",
                display="python3 tools/validate.py --check --root VIEWER_ROOT",
            )
            stages.append(_stage("viewer-validation", "viewer-response-notes", viewer_commit, "python3 tools/validate.py --check --root VIEWER_ROOT", None, _file_hash(viewer_records_path), "PASSED", "VALIDATED", _locator(run_id, "viewer/records")))
            base["acceptance"]["viewer_contract_validated"] = True
            viewer_export = run_dir / "viewer-signal-export.json"
            viewer_export_id = f"VRSE-{re.sub(r'[^A-Za-z0-9._-]+', '-', run_id)}"
            viewer_export_status = _run_command(
                [child_python, "tools/export_signals.py", str(viewer_records_path), "--export-id", viewer_export_id, "--source-commit", production_commit, "--output", str(viewer_export)],
                cwd=viewer_root,
                stage_id="viewer-signal-export",
                display="python3 tools/export_signals.py VIEWER_RECORDS --export-id VIEWER_EXPORT_ID --source-commit PRODUCTION_COMMIT --output VIEWER_EXPORT",
                parser=_text_output,
            )
            if viewer_export_status != "EXPORTED":
                raise StageFailure("viewer-signal-export", "VIEWER_SIGNAL_EXPORT_NOT_CREATED")
            stages.append(_stage("viewer-signal-export", "viewer-response-notes", viewer_commit, "python3 tools/export_signals.py VIEWER_RECORDS --export-id VIEWER_EXPORT_ID --source-commit PRODUCTION_COMMIT --output VIEWER_EXPORT", "research-signal-export/v1", _file_hash(viewer_export), "PASSED", "SIGNALS_EXPORTED", _locator(run_id, "viewer/export")))
            viewer_export_replay = _run_command(
                [child_python, "tools/export_signals.py", str(viewer_records_path), "--export-id", viewer_export_id, "--source-commit", production_commit, "--output", str(viewer_export)],
                cwd=viewer_root,
                stage_id="viewer-signal-export-replay",
                display="python3 tools/export_signals.py VIEWER_RECORDS --export-id VIEWER_EXPORT_ID --source-commit PRODUCTION_COMMIT --output VIEWER_EXPORT",
                parser=_text_output,
            )
            if viewer_export_replay != "ALREADY_EXPORTED":
                raise StageFailure("viewer-signal-export-replay", "VIEWER_EXPORT_NOT_IDEMPOTENT")
            stages.append(_stage("viewer-signal-export-replay", "viewer-response-notes", viewer_commit, "python3 tools/export_signals.py VIEWER_RECORDS --export-id VIEWER_EXPORT_ID --source-commit PRODUCTION_COMMIT --output VIEWER_EXPORT", "research-signal-export/v1", _file_hash(viewer_export), "PASSED", "REPLAYED", _locator(run_id, "viewer/export-replay")))
            base["acceptance"]["viewer_signal_exported"] = True
            research_signal_export = run_dir / "research-signal-export"
            research_export = _run_command(
                [child_python, "tools/export_feedback_signals.py", research_project, "--result-id", result_id, "--output", str(research_signal_export), "--root", str(research_work)],
                cwd=research_protocol,
                stage_id="research-signal-export",
                display="python3 tools/export_feedback_signals.py RESEARCH_PROJECT --result-id RESULT_ID --output RESEARCH_SIGNAL_EXPORT --root RESEARCH_WORK",
                parser=_json_output,
            )
            if research_export.get("status") != "EXPORTED":
                raise StageFailure("research-signal-export", "RESEARCH_SIGNAL_EXPORT_NOT_CREATED")
            stages.append(_stage("research-signal-export", "agentic-art-research", research_commit, "python3 tools/export_feedback_signals.py RESEARCH_PROJECT --result-id RESULT_ID --output RESEARCH_SIGNAL_EXPORT --root RESEARCH_WORK", "research-signal-export/v1", _file_hash(research_signal_export / "manifest.json"), "PASSED", "SIGNALS_EXPORTED", _locator(run_id, "research/export")))
            base["acceptance"]["research_signal_exported"] = True
            if research_output_root is not None:
                destination = research_output_root.resolve() / "projects" / research_project_slug
                if destination.exists():
                    raise ExchangeError(f"research output already exists: {destination}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(research_project_path, destination, symlinks=False)
            if production_output_root is not None:
                destination = production_output_root.resolve() / "production" / production_project_slug
                if destination.exists():
                    raise ExchangeError(f"production output already exists: {destination}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(production_project, destination, symlinks=False)
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
    parser.add_argument("--workspace-root", type=Path, default=ROOT / "repos")
    parser.add_argument("--output-root", type=Path, default=Path(tempfile.gettempdir()) / "agentic-art-orchestration-production-exchange")
    parser.add_argument("--run-id", default="PRODUCTION-E2E-001:offline-fixture")
    parser.add_argument("--generated-at", default="2026-08-13T08:00:00+09:00")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/repositories.yaml")
    parser.add_argument("--check", action="store_true", help="validate an existing evidence JSON")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--e2e", action="store_true", help="run the sanitized end-to-end terminal-state qualification")
    parser.add_argument("--e2e-output", type=Path, default=E2E_OUTPUT_PATH)
    parser.add_argument("--child-python", default=sys.executable, help="Python executable with the child CLI dependencies")
    parser.add_argument("--offline-fixture", action="store_true", help="use the verified immutable candidate workspace and Git-external output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.check:
            if not args.evidence:
                if not args.e2e and not args.offline_fixture:
                    raise ExchangeError("--check requires --evidence")
                report = json.loads(args.e2e_output.read_text(encoding="utf-8"))
                errors = validate_exchange_e2e(report, str(args.e2e_output))
                if errors:
                    print(json.dumps({"status": "FAILED", "errors": errors}, ensure_ascii=False, sort_keys=True))
                    return 2
                print(json.dumps({"status": "PASSED", "evidence": str(args.e2e_output.name)}, ensure_ascii=False, sort_keys=True))
                return 0
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            errors = validate_exchange_evidence(evidence, str(args.evidence))
            if errors:
                print(json.dumps({"status": "FAILED", "errors": errors}, ensure_ascii=False, sort_keys=True))
                return 2
            print(json.dumps({"status": "PASSED", "evidence": str(args.evidence.name)}, ensure_ascii=False, sort_keys=True))
            return 0
        manifest = _load_yaml(args.manifest)
        if args.e2e:
            report = run_exchange_e2e(manifest, args.workspace_root, args.output_root, run_id=args.run_id, generated_at=args.generated_at, child_python=args.child_python)
            rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            if args.offline_fixture:
                args.e2e_output.parent.mkdir(parents=True, exist_ok=True)
                args.e2e_output.write_text(rendered, encoding="utf-8")
            print(json.dumps({"status": report["status"], "evidence": str(args.e2e_output)}, ensure_ascii=False, sort_keys=True))
            return 0 if report["status"] == "PASSED" else 2
        evidence = run_exchange(manifest, args.workspace_root, args.output_root, run_id=args.run_id, generated_at=args.generated_at, child_python=args.child_python)
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        return 0 if evidence["status"] == "PASSED" else 2
    except (OSError, ValueError, ExchangeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": "EXCHANGE_EXECUTION", "detail": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
