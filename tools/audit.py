#!/usr/bin/env python3
"""Run a deterministic, non-blocking cross-repository audit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]

try:
    from tools.validate import validate_signal
    from tools.workspace import load_manifest
except ModuleNotFoundError:  # pragma: no cover - exercised by direct CLI use
    sys.path.insert(0, str(ROOT))
    from tools.validate import validate_signal
    from tools.workspace import load_manifest


class AuditError(ValueError):
    """Audit inputs cannot be interpreted safely."""


EXPECTED_CONTRACT = "normalized-research-signal/v1"
EXPECTED_BOUNDARIES = {
    "manifest": "tests/test_validate.py",
    "workspace": "tests/test_workspace.py",
    "snapshot": "tests/test_snapshot.py",
    "signal-contract": "tests/test_signal_contract.py",
    "adapters": "tests/test_adapter_self_model.py",
    "consumer": "tests/test_consumer_contract.py",
    "trace": "tests/test_trace.py",
    "scheduler": "tests/test_scheduler.py",
    "runtime": "tests/test_runtime_recovery.py",
    "quality-gates": "tests/test_quality_gates.py",
    "dispatcher": "tests/test_dispatcher.py",
    "status": "tests/test_status.py",
    "project-sync": "tests/test_project_sync.py",
    "knowledge-profiles": "tests/test_knowledge_profiles.py",
    "async-auditor": "tests/test_async_auditor.py",
    "drive-adapter": "tests/test_drive_adapter.py",
    "issue-router": "tests/test_issue_router.py",
    "retrieval": "tests/test_retrieval.py",
    "improvement-loop": "tests/test_improvement_loop.py",
    "interaction-e2e": "tests/test_interaction_e2e.py",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _error(detail: str, remediation: str) -> AuditError:
    return AuditError(f"audit: {detail}; remediation: {remediation}")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise _error("timestamp must be a string", "use an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error(f"invalid timestamp {value!r}", "repair the source timestamp") from exc
    if parsed.tzinfo is None:
        raise _error("timestamp must include timezone", "include Z or an explicit UTC offset")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _generated_at(*sources: object) -> str:
    parsed = [_parse_timestamp(value) for value in sources if value is not None]
    if not parsed:
        return "1970-01-01T00:00:00Z"
    return max(parsed).isoformat().replace("+00:00", "Z")


def _finding(code: str, subject: str, observed: object, remediation: str, severity: str = "warning") -> dict:
    return {
        "code": code,
        "severity": severity,
        "subject": subject,
        "observed": observed,
        "remediation": remediation,
    }


def _manifest_by_id(manifest: Mapping[str, object]) -> dict[str, dict]:
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list):
        raise _error("manifest.repositories must be a list", "repair config/repositories.yaml")
    result = {}
    for repository in repositories:
        if not isinstance(repository, dict) or not isinstance(repository.get("id"), str):
            raise _error("manifest repository must declare an ID", "repair config/repositories.yaml")
        result[repository["id"]] = repository
    return result


def _audit_pins(manifest: Mapping[str, object], snapshot: Mapping[str, object], findings: list[dict]) -> None:
    manifest_by_id = _manifest_by_id(manifest)
    snapshot_repositories = snapshot.get("repositories", [])
    snapshot_by_id = {repo.get("id"): repo for repo in snapshot_repositories if isinstance(repo, dict)}
    for repository_id in sorted(manifest_by_id):
        repository = manifest_by_id[repository_id]
        observed_commit = repository.get("observed_commit")
        snapshot_repository = snapshot_by_id.get(repository_id)
        if not isinstance(observed_commit, str) or SHA40.fullmatch(observed_commit) is None:
            findings.append(_finding("stale-pin", repository_id, observed_commit, "record a complete pinned source commit"))
        elif snapshot_repository is None or snapshot_repository.get("manifest_observed_commit") != observed_commit:
            findings.append(
                _finding(
                    "stale-pin",
                    repository_id,
                    {"manifest": observed_commit, "snapshot": (snapshot_repository or {}).get("manifest_observed_commit")},
                    "regenerate the snapshot after reviewing the manifest pin",
                )
            )
    current_contracts = {}
    for repository_id, repository in manifest_by_id.items():
        contract_key = "export_contract" if "export_contract" in repository else "import_contract"
        contract = repository.get(contract_key)
        current_contracts[repository_id] = contract
        if contract != EXPECTED_CONTRACT:
            findings.append(
                _finding(
                    "schema-drift",
                    repository_id,
                    {"field": contract_key, "value": contract},
                    f"restore the declared boundary contract {EXPECTED_CONTRACT}",
                    "error",
                )
            )
    for repository in snapshot_repositories:
        if not isinstance(repository, dict):
            continue
        contract = repository.get("contract", {})
        if contract.get("version") != EXPECTED_CONTRACT:
            findings.append(
                _finding(
                    "schema-drift",
                    str(repository.get("id")),
                    {"snapshot_contract": contract.get("version")},
                    f"regenerate the snapshot from the {EXPECTED_CONTRACT} manifest",
                    "error",
                )
            )


def _audit_signals(
    signals: list[dict],
    requirements: list[dict],
    manifest: Mapping[str, object],
    reference_time: datetime,
    findings: list[dict],
) -> None:
    known_repositories = set(_manifest_by_id(manifest))
    seen: set[str] = set()
    linked: set[str] = set()
    for requirement in requirements:
        for signal_id in requirement.get("signal_ids", []) if isinstance(requirement, dict) else []:
            if isinstance(signal_id, str):
                linked.add(signal_id)
    for index, signal in enumerate(signals):
        signal_id = signal.get("signal_id") if isinstance(signal, dict) else None
        subject = str(signal_id or f"signals[{index}]")
        if signal_id in seen:
            findings.append(_finding("duplicate", subject, "signal_id appears more than once", "retain one source signal per stable ID"))
        if isinstance(signal_id, str):
            seen.add(signal_id)
        errors = validate_signal(signal, f"audit:signal:{subject}") if isinstance(signal, dict) else ["signal is not an object"]
        if errors:
            findings.append(_finding("schema-drift", subject, errors, "repair the signal at its owning repository boundary", "error"))
        if not isinstance(signal, dict):
            continue
        source = signal.get("source", {})
        repository = source.get("repository")
        if repository not in known_repositories:
            findings.append(_finding("stale-pin", subject, {"source_repository": repository}, "use a manifest repository ID and source commit"))
        freshness = signal.get("freshness", {})
        if freshness.get("status") == "stale":
            findings.append(_finding("freshness", subject, freshness, "revalidate before using the signal; preserve stale status"))
        else:
            revalidate_at = freshness.get("revalidate_at")
            if revalidate_at:
                try:
                    if _parse_timestamp(revalidate_at) < reference_time:
                        findings.append(_finding("freshness", subject, {"revalidate_at": revalidate_at}, "mark the signal stale and retain a revalidation constraint"))
                except AuditError as exc:
                    findings.append(_finding("freshness", subject, str(exc), "repair freshness timestamps at the owner boundary", "error"))
        self_domain = signal.get("domain", {}).get("self_model") if isinstance(signal.get("domain"), dict) else None
        if isinstance(self_domain, dict) and self_domain.get("export_permitted") is not True:
            findings.append(_finding("consent", subject, {"export_permitted": self_domain.get("export_permitted")}, "do not export until consent scope explicitly permits it", "error"))
        forbidden_keys = {"PRIVATE_RAW", "RESTRICTED", "credential", "direct_identifier", "raw_voice_body", "raw_audio"}
        present = sorted(key for key in forbidden_keys if key in signal)
        if present:
            findings.append(_finding("forbidden-data", subject, present, "remove forbidden data before crossing the parent boundary", "error"))
    signal_ids = {signal.get("signal_id") for signal in signals if isinstance(signal, dict)}
    for orphan in sorted(signal_ids - linked, key=str):
        findings.append(_finding("orphan", str(orphan), "signal is not linked from a portfolio requirement", "link it to a requirement or remove the generated record"))
    for missing in sorted(linked - signal_ids, key=str):
        findings.append(_finding("orphan", str(missing), "requirement references an unknown signal", "repair the portfolio reference or export the missing signal"))


def _audit_queue(tasks: list[dict], findings: list[dict]) -> None:
    seen: set[str] = set()
    for task in tasks:
        task_id = task.get("id") if isinstance(task, dict) else None
        if task_id in seen:
            findings.append(_finding("duplicate", str(task_id), "task ID appears more than once", "retain one queue item per stable ID"))
        if isinstance(task_id, str):
            seen.add(task_id)
        if isinstance(task, dict) and task.get("status") not in {"BACKLOG", "READY", "IN_PROGRESS", "DONE", "BLOCKED"}:
            findings.append(_finding("schema-drift", str(task_id), {"status": task.get("status")}, "repair the queue state", "error"))


def build_audit(
    manifest: dict,
    snapshot: dict,
    queue: dict,
    state: dict,
    signals: list[dict],
    requirements: list[dict],
    tested_boundaries: Mapping[str, bool],
) -> dict:
    """Return findings without changing any input and without blocking execution."""
    findings: list[dict] = []
    _audit_pins(manifest, snapshot, findings)
    reference_time = _parse_timestamp(_generated_at(snapshot.get("captured_at"), queue.get("updated_at"), state.get("updated_at")))
    _audit_signals(signals, requirements, manifest, reference_time, findings)
    _audit_queue(queue.get("tasks", []), findings)
    for boundary in sorted(EXPECTED_BOUNDARIES):
        if not tested_boundaries.get(boundary, False):
            findings.append(_finding("untested-boundary", boundary, EXPECTED_BOUNDARIES[boundary], "add or restore the boundary test before claiming coverage"))
    findings.sort(key=lambda finding: (finding["code"], finding["subject"], json.dumps(finding["observed"], ensure_ascii=False, sort_keys=True)))
    return {
        "version": 1,
        "generated_at": _generated_at(snapshot.get("captured_at"), queue.get("updated_at"), state.get("updated_at")),
        "blocking": False,
        "status": "CLEAN" if not findings else "FINDINGS",
        "summary": {"finding_count": len(findings), "error_count": sum(item["severity"] == "error" for item in findings)},
        "findings": findings,
    }


def render_markdown(audit: dict) -> str:
    lines = [
        "# Cross-repository audit",
        "",
        f"- Generated at: `{audit['generated_at']}`",
        f"- Status: **{audit['status']}**",
        f"- Blocking: `{str(audit['blocking']).lower()}`",
        f"- Findings: `{audit['summary']['finding_count']}` (errors: `{audit['summary']['error_count']}`)",
        "",
        "| Code | Severity | Subject | Observed | Remediation |",
        "| --- | --- | --- | --- | --- |",
    ]
    if audit["findings"]:
        for finding in audit["findings"]:
            observed = json.dumps(finding["observed"], ensure_ascii=False, sort_keys=True).replace("|", "\\|")
            lines.append(f"| {finding['code']} | {finding['severity']} | {finding['subject']} | `{observed}` | {finding['remediation']} |")
    else:
        lines.append("| none | - | - | - | no findings |")
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_signals_and_requirements() -> tuple[list[dict], list[dict]]:
    fixture_root = ROOT / "tests/fixtures/portfolio"
    fixture_base = ROOT / "tests/fixtures"
    with (fixture_root / "portfolio.json").open(encoding="utf-8") as handle:
        portfolio = json.load(handle)
    signals: list[dict] = []
    for relative in portfolio.get("signal_files", []):
        path = (fixture_root / relative).resolve()
        try:
            path.relative_to(fixture_base.resolve())
        except ValueError as exc:
            raise _error(f"signal fixture escapes fixture root: {relative!r}", "use a fixture below tests/fixtures") from exc
        with path.open(encoding="utf-8") as handle:
            signals.append(json.load(handle))
    return signals, portfolio.get("requirements", [])


def _inputs() -> tuple[dict, dict, dict, dict, list[dict], list[dict], dict[str, bool]]:
    manifest = load_manifest()
    with (ROOT / "data/snapshot.json").open(encoding="utf-8") as handle:
        snapshot = json.load(handle)
    with (ROOT / "execution/task-queue.yaml").open(encoding="utf-8") as handle:
        queue = yaml.safe_load(handle)
    with (ROOT / "execution/state.yaml").open(encoding="utf-8") as handle:
        state = yaml.safe_load(handle)
    signals, requirements = _load_signals_and_requirements()
    tested = {boundary: (ROOT / path).is_file() for boundary, path in EXPECTED_BOUNDARIES.items()}
    return manifest, snapshot, queue, state, signals, requirements, tested


def run_audit(output_dir: Path, check: bool) -> dict:
    manifest, snapshot, queue, state, signals, requirements, tested = _inputs()
    audit = build_audit(manifest, snapshot, queue, state, signals, requirements, tested)
    markdown = render_markdown(audit)
    json_content = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path = output_dir / "audit.json"
    markdown_path = output_dir / "audit.md"
    if check:
        second = build_audit(*_inputs())
        if audit != second or markdown != render_markdown(second):
            raise _error("audit generation is not deterministic", "sort findings and remove wall-clock values")
        if not json_path.is_file() or not markdown_path.is_file():
            raise _error("audit output is missing", "run audit without --check to materialize outputs")
        if json_path.read_text(encoding="utf-8") != json_content or markdown_path.read_text(encoding="utf-8") != markdown:
            raise _error("audit output is stale", "rerun audit without --check")
        return {"command": "audit", "changed": False, "status": audit["status"], "finding_count": audit["summary"]["finding_count"]}
    _write_atomic(json_path, json_content)
    _write_atomic(markdown_path, markdown)
    return {"command": "audit", "changed": True, "status": audit["status"], "finding_count": audit["summary"]["finding_count"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a non-blocking cross-repository audit")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--offline-fixture", action="store_true", help="audit the local synthetic fixture inputs")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    try:
        result = run_audit(args.output_dir.resolve(), args.check)
    except (OSError, AuditError, ValueError, KeyError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
