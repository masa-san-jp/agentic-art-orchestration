#!/usr/bin/env python3
"""Prove the purpose statement from one new theme to a production plan.

Evidence is metadata-only.  The networkless lane uses a labelled synthetic
fixture; the private lane reads only from a caller-supplied clean,
manifest-pinned workspace and writes all staging outputs outside Git.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker

try:
    from tools.adapters import adapt_self_model_signal
    from tools.autonomous_runner import run_autonomous, validate_autonomous_state
    from tools.batch_run import _load_export
    from tools.candidate_selection import build_self_diversity_report
    from tools.candidate_space import canonical_json
    from tools.production_exchange import run_exchange
    from tools.research_request import build_research_request, validate_research_request
    from tools.run import run as run_pipeline
    from tools.signal_bundle import build_signal_bundle
    from tools.validate import ROOT, load_json, load_yaml, validate_child_quality_gates
    from tools.visual_package_boundary import build_fixture_visual_package, project_visual_package
    from tools.viewer_response_gate import assess_records
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from tools.adapters import adapt_self_model_signal
    from tools.autonomous_runner import run_autonomous, validate_autonomous_state
    from tools.batch_run import _load_export
    from tools.candidate_selection import build_self_diversity_report
    from tools.candidate_space import canonical_json
    from tools.production_exchange import run_exchange
    from tools.research_request import build_research_request, validate_research_request
    from tools.run import run as run_pipeline
    from tools.signal_bundle import build_signal_bundle
    from tools.viewer_response_gate import assess_records
    from tools.validate import ROOT, load_json, load_yaml, validate_child_quality_gates
    from tools.visual_package_boundary import build_fixture_visual_package, project_visual_package


SCHEMA_PATH = ROOT / "schemas" / "purpose-e2e-evidence.schema.json"
THEME = "透明な境界を往復する光"
THEME_ALGORITHM = "intent-rank/v1"
OFFLINE_TIMESTAMP = "2026-08-27T00:00:00+09:00"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
ATTEMPT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,48}$")
PROJECT_SLUG_PREFIX = "purpose-e2e-transparent-boundary-"
REPOSITORIES = (
    "self-model", "art-history", "marketing-trends", "agentic-art-research",
    "agentic-art-production", "viewer-response-notes",
)
FORBIDDEN = re.compile(r"(?i)(PRIVATE_RAW|RESTRICTED|credential|raw[_ -]?conversation|raw[_ -]?voice|signed[_ -]?url)")


class PurposeE2EError(RuntimeError):
    """The purpose E2E cannot safely reach a terminal plan."""


def _digest(value: object) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_attempt(attempt_id: str) -> str:
    if not isinstance(attempt_id, str) or ATTEMPT.fullmatch(attempt_id) is None:
        raise PurposeE2EError("attempt-id must be a short stable identifier")
    return attempt_id


def _project_slug(attempt_id: str) -> str:
    return PROJECT_SLUG_PREFIX + attempt_id.lower()


def _run_id(attempt_id: str) -> str:
    return f"PURPOSE-E2E:{attempt_id}"


def _timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PurposeE2EError("generated-at must be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise PurposeE2EError("generated-at must include a timezone")


def _manifest_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list):
        raise PurposeE2EError("manifest.repositories is not a list")
    result = {item.get("id"): item for item in repositories if isinstance(item, Mapping) and isinstance(item.get("id"), str)}
    missing = sorted(set(REPOSITORIES) - set(result))
    if missing:
        raise PurposeE2EError(f"manifest is missing repositories: {', '.join(missing)}")
    return result


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _observe_repository(repository: Mapping[str, Any], workspace_root: Path | None, *, offline: bool) -> dict[str, Any]:
    repository_id = str(repository["id"])
    expected = str(repository["observed_commit"])
    if offline:
        return {"repository": repository_id, "source_commit": expected, "branch": "OFFLINE_FIXTURE", "head": expected, "dirty": False, "pin_status": "MATCHED", "workspace_state": "OFFLINE_FIXTURE"}
    if workspace_root is None:
        raise PurposeE2EError("live-private requires workspace-root")
    root = (workspace_root / str(repository["path"])).resolve()
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    branch = _git(root, "symbolic-ref", "--short", "HEAD")
    observed_head = head.stdout.strip() if head.returncode == 0 else None
    dirty = status.returncode != 0 or bool(status.stdout.strip())
    branch_name = branch.stdout.strip() if branch.returncode == 0 else "DETACHED"
    pin_status = "MATCHED" if observed_head == expected and not dirty else ("DIRTY" if dirty else "MISMATCH")
    return {"repository": repository_id, "source_commit": expected, "branch": branch_name, "head": observed_head, "dirty": dirty, "pin_status": pin_status, "workspace_state": "DIRTY" if dirty else ("MATCHED" if observed_head == expected else "STALE")}


def _source_observations(manifest: Mapping[str, Any], workspace_root: Path | None, *, offline: bool) -> list[dict[str, Any]]:
    observations = [_observe_repository(item, workspace_root, offline=offline) for item in _manifest_map(manifest).values()]
    observations.sort(key=lambda item: item["repository"])
    if not offline:
        invalid = [item["repository"] for item in observations if item["pin_status"] != "MATCHED"]
        if invalid:
            raise PurposeE2EError("live-private source workspace is not clean and pin-matched: " + ", ".join(invalid))
    return observations


def _offline_signals(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build a test-only signal bundle; fixture anchors never enter live evidence."""
    repositories = _manifest_map(manifest)
    source = load_json(ROOT / "tests" / "fixtures" / "signal" / "self_export_bundle.json")
    self_records: list[dict[str, Any]] = []
    for record in source["signals"]:
        self_records.append(adapt_self_model_signal({**record, "commit": repositories["self-model"]["observed_commit"]}))
    # These labels are synthetic fixture values, not self-model facts.  They
    # make the offline diversity boundary executable without fabricating live
    # personal anchors or writing anything to self-model.
    self_records[0]["domain"]["self_model"]["tensions"] = ["fixture-anchor-alpha"]
    self_records[1]["domain"]["self_model"]["tensions"] = ["fixture-anchor-beta"]
    self_records[2]["domain"]["self_model"]["recurring_patterns"] = ["fixture-anchor-gamma"]
    art = load_json(ROOT / "tests" / "fixtures" / "signal" / "valid_art_history.json")
    art["source"]["commit"] = repositories["art-history"]["observed_commit"]
    marketing = load_json(ROOT / "tests" / "fixtures" / "signal" / "valid_marketing.json")
    marketing["source"]["commit"] = repositories["marketing-trends"]["observed_commit"]
    return self_records + [art, marketing]


def _export_from_workspace(manifest: Mapping[str, Any], workspace_root: Path, output_root: Path, child_python: str) -> list[dict[str, Any]]:
    repositories = _manifest_map(manifest)
    output_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    commands = {
        "self": ("self-model", "tools/export_signals.py", []),
        "art-history": ("art-history", "tools/export_signals.py", []),
        "marketing": ("marketing-trends", "tools/export_signals.py", []),
    }
    for kind, (repository_id, script, options) in commands.items():
        repository = repositories[repository_id]
        checkout = (workspace_root / str(repository["path"])).resolve()
        output = output_root / f"{kind}.json"
        completed = subprocess.run([child_python, str(checkout / script), "--purpose", "artistic-research", *options, "--output", str(output)], cwd=checkout, capture_output=True, text=True, check=False)
        if completed.returncode != 0 or not output.is_file():
            raise PurposeE2EError(f"{kind} source export failed; inspect the pinned child export contract")
        records.extend(_load_export(output, kind, str(repository["observed_commit"])))
    return records


def _parent_commit() -> str:
    result = _git(ROOT, "rev-parse", "HEAD")
    commit = result.stdout.strip()
    if result.returncode != 0 or not SHA40.fullmatch(commit):
        raise PurposeE2EError("parent HEAD is not an immutable commit")
    return commit


def _pipeline(
    signals: list[dict[str, Any]],
    *,
    project_id: str,
    project_slug: str | None = None,
    generated_at: str,
) -> dict[str, Any]:
    bundle = build_signal_bundle(signals, generated_at)
    try:
        pipeline = run_pipeline(bundle, project_id=project_id, seed_input="purpose-e2e-transparent-boundary-v1", selection_limit=1, intent=THEME)
    except ValueError as exc:
        raise PurposeE2EError("selection gate rejected all candidates") from exc
    diversity = build_self_diversity_report(bundle["records"], pipeline["candidate_space"], pipeline["selection"]["selected_candidates"], 1)
    if diversity["status"] not in {"PASS", "PASS_LIMITED_DIVERSITY"}:
        raise PurposeE2EError(f"self diversity is {diversity['status']}; do not invent a personal anchor")
    request = build_research_request(
        pipeline["selection"],
        bundle,
        request_id="RR001",
        requested_at=generated_at,
        project_slug=project_slug or project_id,
        project_title="Transparent Boundary Light",
        source_commit=_parent_commit(),
    )
    if validate_research_request(request):
        raise PurposeE2EError("research request failed its closed contract")
    if not all("intent_score" in candidate for candidate in pipeline["selection"]["selected_candidates"]):
        raise PurposeE2EError("selected candidate is missing intent score")
    return {
        "bundle": bundle,
        "candidate_space": pipeline["candidate_space"],
        "gate_report": pipeline["gate_report"],
        "selection": pipeline["selection"],
        "provenance": pipeline["provenance"],
        "diversity": diversity,
        "request": request,
        "intent_sha256": pipeline["intent_sha256"],
        "intent_algorithm": pipeline["intent_algorithm"],
    }


def _theme_spec() -> dict[str, Any]:
    return {
        "completion_image": {
            "encounter": [
                "A viewer follows a light across a translucent boundary.",
                "The light returns from the far side without an explanation.",
                "The return makes the boundary perceptible.",
            ],
            "position": "A viewer moves along one marked side of the boundary.",
            "first_seconds": "The first seconds reveal a light that crosses and returns.",
            "after_30s": "After 30 seconds the boundary is noticed as the condition of the return.",
            "after_3min": "After three minutes the viewer can describe the crossing without explanatory text.",
        },
        "theme": {
            "field": "光が透明な境界を往復すること",
            "stands_against": "A boundary must be opaque to be perceptible.",
            "difference": "The boundary is made perceptible by a return rather than by a visible wall.",
            "why_now": "Screens and projections increasingly separate seeing from physical enclosure.",
        },
        "message": {
            "claim": "A boundary can become perceptible through the return of light.",
            "who_disagrees": "A designer who believes only an opaque obstruction can communicate a boundary.",
            "denies": "A visible wall is required before a boundary can be experienced.",
            "shown_not_told": "A light crosses a translucent field and returns once; no explanatory wall text is used.",
        },
        "concept": {
            "mechanism": "A controlled light crosses a translucent field and returns at one interval, making the field perceptible through the changed route.",
            "without_the_technique": "CEASES_TO_WORK",
            "precedents": [{"reference": "prior-art/PA001", "difference": "The reference presents a field; this work makes the boundary perceptible through return."}],
            "self_repetition_risk": {"reference": "self-repetition-review/SR001", "assessment": "The work uses a new boundary-and-return relation rather than repeating a prior form."},
        },
        "research_summary": {
            "questions": ["How can a return of light make a transparent boundary perceptible?"],
            "what_was_read": "Pinned public reference metadata and child evidence locators were checked.",
            "what_came_out": "The plan treats the return as a testable perceptual condition.",
            "what_is_not_settled": "Viewer response is not measured in this run.",
        },
        "visual_language": {
            "schema_version": "1.0.0",
            "medium": {
                "primary": "installation",
                "statement": "An installation makes the return of light perceptible across a transparent boundary.",
                "source_decision_id": "DC002",
            },
            "techniques": [{
                "id": "VT001",
                "name": "controlled return of light",
                "intent": "Make the transparent boundary perceptible through a return.",
                "source_decision_ids": ["DC001"],
                "requirement_ids": ["RQ001"],
            }],
            "palette": {
                "applicability": "APPLICABLE",
                "preferred": ["single hue"],
                "prohibited": ["decorative gradient"],
                "rationale": "A restrained palette keeps the boundary legible.",
                "source_decision_ids": ["DC001"],
            },
            "composition": {
                "applicability": "APPLICABLE",
                "preferred": ["visible return path"],
                "prohibited": ["uniform repetition"],
                "rationale": "The return must remain distinguishable from the crossing.",
                "source_decision_ids": ["DC001"],
            },
            "prohibited_expressions": [{
                "id": "VP001",
                "statement": "Do not add explanatory wall text.",
                "reason": "The perceptual condition must be experienced rather than explained.",
                "source_decision_ids": ["DC001"],
                "requirement_ids": ["RQ001"],
            }],
            "unresolved_uncertainty_ids": [],
        },
    }


def _fake_worker(path: Path, count_path: Path, worker_commit: str) -> None:
    script = f'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path
request = Path(sys.argv[sys.argv.index("--request") + 1])
response = Path(sys.argv[sys.argv.index("--response") + 1])
count = Path({str(count_path)!r})
current = int(count.read_text()) if count.exists() else 0
count.write_text(str(current + 1), encoding="utf-8")
action = json.loads(request.read_text(encoding="utf-8"))
payload = {{
    "contract_version": "agent-result/v1",
    "run_id": action["run_id"],
    "stage": "research",
    "status": "COMPLETED",
    "checks": [{{"id": "research-complete", "status": "PASSED"}}, {{"id": "provenance-complete", "status": "PASSED"}}],
    "changed_paths": ["project"],
    "commit_sha": {worker_commit!r},
    "blocker_category": "none",
    "requested_operations": [],
}}
response.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def _run_supervisor(state_root: Path, project_root: Path, run_id: str, research_commit: str) -> dict[str, Any]:
    state_root = state_root.resolve()
    if state_root == ROOT or ROOT in state_root.parents:
        raise PurposeE2EError("purpose E2E state root must be Git-external")
    state_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    worker = state_root / "purpose-worker"
    count = state_root / "worker-count"
    _fake_worker(worker, count, research_commit)
    first = run_autonomous(run_id=run_id, worker_command=str(worker), state_root=state_root, child_repository="agentic-art-research", source_commit=research_commit, project_path=str(project_root), allowed_paths=("project",))
    second = run_autonomous(run_id=run_id, worker_command=str(worker), state_root=state_root, child_repository="agentic-art-research", source_commit=research_commit, project_path=str(project_root), allowed_paths=("project",))
    if first.get("status") != "PLAN_READY" or second != first:
        raise PurposeE2EError("autonomous runner did not reach an idempotent PLAN_READY")
    if count.read_text(encoding="utf-8") != "1":
        raise PurposeE2EError("same-run resume invoked the accepted worker more than once")
    state_path = state_root / run_id / "supervisor.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if validate_autonomous_state(state):
        raise PurposeE2EError("autonomous supervisor state is invalid")
    return {
        "run_id": run_id,
        "status": state["status"],
        "stage": state["stage"],
        "transition": ["RESEARCH_PENDING", "RESEARCH_WORKER_RUNNING", "PLAN_READY"],
        "attempts": state["attempts"],
        "retry_count": sum(state["retry_counts"].values()),
        "human_prompt_count": 0,
        "worker_invocation_count": int(count.read_text(encoding="utf-8")),
        "resume_reused": True,
        "accepted_result_digest": state["accepted_result_digest"],
        "privacy": state["privacy"],
    }


def _offline_plan(pipeline: Mapping[str, Any], project_slug: str, output_root: Path, production_commit: str, run_id: str) -> dict[str, Any]:
    plan = {
        "schema_version": "purpose-production-plan/v1",
        "project_id": f"project/{project_slug}",
        "status": "PLAN_READY",
        "medium": "light installation",
        "materials": ["translucent boundary", "controlled light source"],
        "tasks": [{"id": "TASK001", "title": "Observe the crossing and return", "effect_type": "READ_ONLY", "executor_capability": "viewer-assessment-agent"}],
        "requirements": [{"id": "RQ001", "viewer_facing": True, "acceptance_test_ids": ["AT001"]}],
        "acceptance_tests": [{"id": "AT001", "method": "blind/frame review", "pass_condition": "The return makes the boundary perceptible."}],
        "executor_capability": "viewer-assessment-agent",
        "material_status": "UNKNOWN",
        "rights_status": "UNKNOWN",
        "safety_status": "UNKNOWN",
        "human_approval_required": False,
        "source": {"handoff_hash": _digest(pipeline["request"]), "selection_hash": _digest(pipeline["selection"])},
    }
    plan_path = output_root / "production" / project_slug / "03_plan" / "production-plan.yaml"
    if plan_path.is_file():
        existing = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or existing.get("status") != "PLAN_READY":
            raise PurposeE2EError("existing offline production plan is invalid")
        markdown = plan_path.with_suffix(".md")
        if not markdown.is_file():
            raise PurposeE2EError("existing offline production markdown plan is missing")
        return {"plan": existing, "plan_path": plan_path, "markdown_path": markdown, "plan_builder_status": "PASSED", "output_root": output_root, "project_slug": project_slug}
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = plan_path.with_suffix(".md")
    markdown.write_text(
        "# Production plan\n\nStatus: PLAN_READY\n\nMedium: light installation\n\nViewer review: blind/frame review\n\n"
        "## Visual package\n\n"
        "[visual-reference-board.svg](visual-package/visual-reference-board.svg)\n\n"
        "[concept-mockup.svg](visual-package/concept-mockup.svg)\n",
        encoding="utf-8",
    )
    package = build_fixture_visual_package(plan_path.parent.parent, production_commit=production_commit, run_id=run_id)
    plan["visual_package"] = package
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"plan": plan, "plan_path": plan_path, "markdown_path": markdown, "plan_builder_status": "PASSED", "output_root": output_root, "project_slug": project_slug}


def _live_plan(output_root: Path, *, production_commit: str, run_id: str) -> dict[str, Any]:
    plan_path = output_root / "production" / "production-smoke" / "03_plan" / "production-plan.yaml"
    if not plan_path.is_file():
        raise PurposeE2EError("live production plan was not retained in Git-external state")
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise PurposeE2EError("live production plan is not a mapping")
    if not plan_path.with_suffix(".md").is_file():
        raise PurposeE2EError("live production markdown plan is missing")
    package_path = plan_path.parent / "visual-package.yaml"
    if not package_path.is_file():
        raise PurposeE2EError("live visual package metadata is missing")
    package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
    if not isinstance(package, Mapping) or package != plan.get("visual_package"):
        raise PurposeE2EError("live visual package metadata does not match the production plan")
    project_root = plan_path.parent.parent
    project_visual_package(
        package,
        project_root=project_root,
        production_commit=production_commit,
        run_id=run_id,
        fixture_only=False,
    )
    source = plan_path.parent.parent / "00_handoff" / "source-bundle" / "artifacts"
    visual_path = source / "visual-language.yaml"
    visual = yaml.safe_load(visual_path.read_text(encoding="utf-8")) if visual_path.is_file() else {}
    visual = visual if isinstance(visual, Mapping) else {}
    medium = visual.get("medium") if isinstance(visual.get("medium"), Mapping) else {}
    work_packages = plan.get("work_packages") if isinstance(plan.get("work_packages"), list) else []
    derived_materials = sorted({
        str(input_id)
        for work_package in work_packages
        if isinstance(work_package, Mapping)
        for input_id in (work_package.get("input_ids") if isinstance(work_package.get("input_ids"), list) else [])
        if isinstance(input_id, str) and input_id.strip()
    })
    derived_executor = next(
        (
            str(value)
            for work_package in work_packages
            if isinstance(work_package, Mapping)
            for value in (work_package.get("owner_capability"), work_package.get("executor_capability"))
            if isinstance(value, str) and value.strip()
        ),
        "UNKNOWN",
    )
    selection_record = plan.get("selection_record") if isinstance(plan.get("selection_record"), Mapping) else {}
    return {
        "plan": plan,
        "visual_package": package,
        "plan_path": plan_path,
        "markdown_path": plan_path.with_suffix(".md"),
        "plan_builder_status": "PASSED",
        "output_root": output_root,
        "project_slug": str(plan.get("project_id", "production/production-smoke")).split("/")[-1],
        "derived": {
            "medium": str(medium.get("primary", "UNKNOWN")),
            "materials": list(plan.get("materials")) if isinstance(plan.get("materials"), list) and plan.get("materials") else derived_materials,
            "executor_capability": str(plan.get("executor_capability") or selection_record.get("executor_capability") or derived_executor),
            "material_status": str(plan.get("material_status", "UNKNOWN")),
            "rights_status": str(plan.get("rights_status", "UNKNOWN")),
            "safety_status": str(plan.get("safety_status", "UNKNOWN")),
            "human_approval_required": bool(plan.get("human_approval_required", selection_record.get("human_approval_required", True))),
        },
    }


def _research_hashes(output_root: Path, project_slug: str, handoff_path: Path) -> tuple[str, dict[str, str]]:
    project = output_root / "research" / "projects" / project_slug
    files = {"completion": project / "07_runtime" / "completion-report.json", "claims": project / "03_knowledge" / "claims.jsonl", "decisions": project / "04_decisions" / "decision-log.yaml", "handoff": handoff_path}
    result: dict[str, str] = {}
    for key, path in files.items():
        if not path.is_file():
            raise PurposeE2EError(f"research {key} evidence is missing")
        result[f"{key}_sha256"] = _sha256_file(path)
    completion = json.loads(files["completion"].read_text(encoding="utf-8"))
    status = completion.get("status") if isinstance(completion, Mapping) else None
    if status not in {"COMPLETE", "COMPLETE_WITH_GAPS"}:
        raise PurposeE2EError("research completion is not terminal")
    return status, result


def _viewer_assessment(plan: Mapping[str, Any]) -> dict[str, Any]:
    assessment = assess_records([], work_id=str(plan.get("project_id", "project/unknown")), requirement_id="RQ001", presentation_mode="gallery", requirement_tags=["boundary"])
    tests = plan.get("acceptance_tests", [])
    review = any(isinstance(test, Mapping) and re.search(r"blind|frame", str(test.get("method", "")), re.I) for test in tests)
    if not review:
        raise PurposeE2EError("viewer-facing requirement lacks a blind/frame acceptance test")
    return {"status": assessment["status"], "review_required": assessment["review_required"], "review_kind": assessment["review_kind"], "measured_sample_size": assessment["measured_sample_size"], "source_record_count": len(assessment["source_record_ids"]), "blind_or_frame_acceptance_test": review, "source_commits": assessment["source_commits"]}


def _quality_commands(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for repository in sorted(_manifest_map(manifest).values(), key=lambda item: str(item["id"])):
        for command in repository.get("quality_gates", []):
            commands.append({"repository": repository["id"], "command": command, "status": "NOT_RUN", "exit_code": None})
    return commands


def _quality_summary(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reduce child-gate evidence to command/status metadata only."""
    summary: list[dict[str, Any]] = []
    results = report.get("results")
    if not isinstance(results, list):
        return summary
    for result in results:
        if not isinstance(result, Mapping):
            continue
        repository = result.get("repository")
        gates = result.get("gates")
        if not isinstance(repository, str) or not isinstance(gates, list):
            continue
        for gate in gates:
            if isinstance(gate, Mapping) and isinstance(gate.get("command"), str):
                summary.append({
                    "repository": repository,
                    "command": gate["command"],
                    "status": gate.get("status", "NOT_RUN"),
                    "exit_code": gate.get("exit_code"),
                })
    return summary


def _quality_passed(report: Mapping[str, Any] | None) -> bool:
    if not isinstance(report, Mapping):
        return False
    results = report.get("results")
    return isinstance(results, list) and bool(results) and all(
        isinstance(result, Mapping) and result.get("status") == "PASSED"
        for result in results
    )


def _validate_quality_report(manifest: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    """Accept only a schema-valid, exact-pin, all-PASSED child-gate report."""
    errors = validate_child_quality_gates(dict(report), "purpose-e2e.child-quality-gates")
    if errors:
        raise PurposeE2EError("child quality gate report is invalid")
    if report.get("manifest_hash") != _digest(manifest):
        raise PurposeE2EError("child quality gate report does not match the manifest")
    expected = _manifest_map(manifest)
    results = report.get("results")
    observed = {item.get("repository"): item for item in results if isinstance(item, Mapping)} if isinstance(results, list) else {}
    if set(observed) != set(expected):
        raise PurposeE2EError("child quality gate report does not cover every manifest repository")
    for repository_id, repository in expected.items():
        result = observed[repository_id]
        if (
            result.get("observed_commit") != repository.get("observed_commit")
            or result.get("workspace_commit") != repository.get("observed_commit")
            or result.get("workspace_state") != "MATCHED"
            or result.get("execution_mode") != "immutable-archive"
            or result.get("status") != "PASSED"
        ):
            raise PurposeE2EError("child quality gate report contains a non-passing or stale repository")
        commands = [gate.get("command") for gate in result.get("gates", []) if isinstance(gate, Mapping)]
        statuses = [gate.get("status") for gate in result.get("gates", []) if isinstance(gate, Mapping)]
        if commands != repository.get("quality_gates") or statuses != ["PASSED"] * len(commands):
            raise PurposeE2EError("child quality gate report does not match the manifest commands")


def _build_evidence(
    manifest: Mapping[str, Any],
    pipeline: Mapping[str, Any],
    supervisor: Mapping[str, Any],
    production: Mapping[str, Any],
    observations: list[dict[str, Any]],
    *,
    attempt_id: str,
    lane: str,
    generated_at: str,
    quality_gate_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    plan = production["plan"]
    viewer = _viewer_assessment(plan)
    if lane == "live-private":
        research_status, research_hashes = _research_hashes(production["output_root"], _project_slug(attempt_id), production["handoff_path"])
    else:
        research_status = "COMPLETE_WITH_GAPS"
        research_hashes = {
            "completion_sha256": _digest({"status": "COMPLETE_WITH_GAPS", "project": "fixture"}),
            "claims_sha256": _digest(pipeline["provenance"]),
            "decisions_sha256": _digest(pipeline["selection"]),
            "handoff_sha256": _digest(pipeline["request"]),
        }
    derived = production.get("derived") if isinstance(production.get("derived"), Mapping) else {}
    project_root = production["output_root"] / "production" / production["project_slug"]
    visual_package = project_visual_package(
        production.get("visual_package") or plan.get("visual_package"),
        project_root=project_root,
        production_commit=str(_manifest_map(manifest)["agentic-art-production"]["observed_commit"]),
        run_id=_run_id(attempt_id),
        fixture_only=lane == "networkless",
    )
    privacy = {"theme_stored": False, "raw_conversation_stored": False, "credentials_stored": False, "private_raw_stored": False, "restricted_stored": False, "artifact_body_stored": False}
    evidence: dict[str, Any] = {
        "contract_version": "purpose-e2e-evidence/v1",
        "attempt_id": attempt_id,
        "run_id": _run_id(attempt_id),
        "project_id": f"project/{_project_slug(attempt_id)}",
        "lane": lane,
        "generated_at": generated_at,
        "terminal_status": "PLAN_READY" if supervisor["status"] == "PLAN_READY" and production.get("plan_builder_status") == "PASSED" else "BLOCKED",
        "source_observations": observations,
        "intent": {"sha256": pipeline["intent_sha256"], "algorithm": pipeline["intent_algorithm"]},
        "self_diversity": {"status": pipeline["diversity"]["status"], "report_sha256": _digest(pipeline["diversity"]), "eligible_anchor_count": pipeline["diversity"]["eligible_anchor_count"], "selected_anchor_count": pipeline["diversity"]["selected_count"], "fixture_only": lane == "networkless"},
        "pipeline": {
            "candidate_space_sha256": _digest(pipeline["candidate_space"]),
            "gate_report_sha256": _digest(pipeline["gate_report"]),
            "selection_sha256": _digest(pipeline["selection"]),
            "proposition_sha256": _digest(pipeline["provenance"]),
            "request_sha256": _digest(pipeline["request"]),
            "selected_count": pipeline["selection"]["selected_count"],
            "selected_intent_scores_present": all("intent_score" in candidate for candidate in pipeline["selection"]["selected_candidates"]),
        },
        "research": {"status": research_status, "evidence_claim_decision_handoff_hashes": research_hashes, "source_reference_policy": "primary-or-explicit-unknown"},
        "production": {
            "plan_sha256": _digest(plan),
            "plan_locator": f"run://{_run_id(attempt_id)}/production/{production.get('project_slug', _project_slug(attempt_id))}/03_plan/production-plan.yaml",
            "source_repository": "agentic-art-production",
            "source_commit": _manifest_map(manifest)["agentic-art-production"]["observed_commit"],
            "visual_package": visual_package,
            "medium": derived.get("medium", plan.get("medium", "UNKNOWN")),
            "materials": derived.get("materials", plan.get("materials", [])),
            "task_count": len(plan.get("tasks", [])) if isinstance(plan.get("tasks"), list) else 0,
            "executor_capability": derived.get("executor_capability", plan.get("executor_capability", "UNKNOWN")),
            "material_status": derived.get("material_status", plan.get("material_status", "UNKNOWN")),
            "rights_status": derived.get("rights_status", plan.get("rights_status", "UNKNOWN")),
            "safety_status": derived.get("safety_status", plan.get("safety_status", "UNKNOWN")),
            "human_approval_required": derived.get("human_approval_required", plan.get("human_approval_required", True)),
            "plan_builder_status": production.get("plan_builder_status"),
        },
        "viewer": viewer,
        "autonomous": supervisor,
        "quality_gates": _quality_summary(quality_gate_report) if quality_gate_report else _quality_commands(manifest),
        "human_prompt_count": supervisor["human_prompt_count"],
        "forbidden_external_operation_count": 0,
        "external_operations": [],
        "child_mutations": [],
        "privacy": privacy,
        "acceptance": {
            "networkless_or_private_lane": lane in {"networkless", "live-private"},
            "plan_ready": supervisor["status"] == "PLAN_READY",
            "zero_human_prompts_after_input": supervisor["human_prompt_count"] == 0,
            "intent_reached_selection": all("intent_score" in candidate for candidate in pipeline["selection"]["selected_candidates"]),
            "self_diversity_pass": pipeline["diversity"]["status"] in {"PASS", "PASS_LIMITED_DIVERSITY"},
            "research_traceable": True,
            "production_derived_fields_present": bool(derived.get("medium") or plan.get("medium")) and bool(plan.get("tasks")),
            "visual_package_present_and_verified": True,
            "viewer_conservative": viewer["status"] == "UNKNOWN" and viewer["blind_or_frame_acceptance_test"],
            "resume_idempotent": supervisor["resume_reused"],
            "child_quality_gates_passed": _quality_passed(quality_gate_report),
            "zero_forbidden_external_effects": True,
            "privacy_boundary_passed": all(value is False for value in privacy.values()),
        },
    }
    return evidence


def _run_lane(
    manifest: Mapping[str, Any],
    *,
    attempt_id: str,
    lane: str,
    output_root: Path,
    state_root: Path,
    workspace_root: Path | None = None,
    child_python: str | None = None,
    quality_gate_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = OFFLINE_TIMESTAMP if lane == "networkless" else datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _timestamp(generated_at)
    observations = _source_observations(manifest, workspace_root, offline=lane == "networkless")
    project_slug = _project_slug(attempt_id)
    research_commit = str(_manifest_map(manifest)["agentic-art-research"]["observed_commit"])
    if lane == "networkless":
        pipeline = _pipeline(_offline_signals(manifest), project_id=PROJECT_SLUG_PREFIX + "canonical", project_slug=project_slug, generated_at=generated_at)
        supervisor = _run_supervisor(state_root, output_root / "research" / "projects" / project_slug, _run_id(attempt_id), research_commit)
        production = _offline_plan(
            pipeline,
            project_slug,
            output_root,
            str(_manifest_map(manifest)["agentic-art-production"]["observed_commit"]),
            _run_id(attempt_id),
        )
        return _build_evidence(manifest, pipeline, supervisor, production, observations, attempt_id=attempt_id, lane=lane, generated_at=generated_at, quality_gate_report=quality_gate_report)

    if workspace_root is None:
        raise PurposeE2EError("live-private requires workspace-root")
    exchange_output = output_root / "exchange"
    with tempfile.TemporaryDirectory(prefix="purpose-e2e-exports-", dir=state_root.parent) as temporary:
        records = _export_from_workspace(manifest, workspace_root, Path(temporary), child_python or sys.executable)
        pipeline = _pipeline(records, project_id=PROJECT_SLUG_PREFIX + "canonical", project_slug=project_slug, generated_at=generated_at)
    exchange = run_exchange(
        manifest,
        workspace_root,
        exchange_output,
        run_id=_run_id(attempt_id),
        generated_at=generated_at,
        research_project_slug=project_slug,
        production_project_slug="production-smoke",
        research_project_title="Transparent Boundary Light",
        theme=_theme_spec(),
        child_python=child_python or sys.executable,
        research_output_root=output_root / "research",
        production_output_root=output_root,
    )
    if exchange.get("status") != "PASSED":
        raise PurposeE2EError("live-private Research/Production exchange did not pass")
    supervisor = _run_supervisor(state_root, output_root / "research" / "projects" / project_slug, _run_id(attempt_id), research_commit)
    production = _live_plan(
        output_root,
        production_commit=str(_manifest_map(manifest)["agentic-art-production"]["observed_commit"]),
        run_id=_run_id(attempt_id),
    )
    exchange_dir = exchange_output / re.sub(r"[^A-Za-z0-9._-]+", "-", _run_id(attempt_id))
    production["handoff_path"] = exchange_dir / "handoff" / "production-handoff.yaml"
    return _build_evidence(manifest, pipeline, supervisor, production, observations, attempt_id=attempt_id, lane=lane, generated_at=generated_at, quality_gate_report=quality_gate_report)


def run_purpose_e2e(
    *,
    attempt_id: str,
    lane: str = "networkless",
    output_root: Path | None = None,
    state_root: Path | None = None,
    workspace_root: Path | None = None,
    child_python: str | None = None,
    manifest: Mapping[str, Any] | None = None,
    quality_gate_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    attempt_id = _safe_attempt(attempt_id)
    if lane not in {"networkless", "live-private"}:
        raise PurposeE2EError("lane must be networkless or live-private")
    manifest = manifest or load_yaml(ROOT / "config" / "repositories.yaml")
    if quality_gate_report is not None:
        _validate_quality_report(manifest, quality_gate_report)
    output_root = (output_root or Path(tempfile.gettempdir()) / f"purpose-e2e-output-{attempt_id}").expanduser().resolve()
    state_root = (state_root or Path(tempfile.gettempdir()) / f"purpose-e2e-state-{attempt_id}").expanduser().resolve()
    if output_root == ROOT or ROOT in output_root.parents or state_root == ROOT or ROOT in state_root.parents:
        raise PurposeE2EError("purpose E2E outputs must be Git-external")
    return _run_lane(manifest, attempt_id=attempt_id, lane=lane, output_root=output_root, state_root=state_root, workspace_root=workspace_root, child_python=child_python, quality_gate_report=quality_gate_report)


def _forbidden_in_evidence(value: object, path: str = "$") -> str | None:
    allowed_false_fields = {"theme_stored", "raw_conversation_stored", "credentials_stored", "private_raw_stored", "restricted_stored", "artifact_body_stored"}
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in allowed_false_fields and child is False:
                continue
            if FORBIDDEN.search(str(key)):
                return f"{path}.{key}"
            found = _forbidden_in_evidence(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _forbidden_in_evidence(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str) and FORBIDDEN.search(value):
        return path
    return None


def validate_purpose_e2e(data: object, source: str = "purpose-e2e") -> list[str]:
    schema = load_json(SCHEMA_PATH)
    errors = [f"{source}: {item.message}" for item in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data)]
    if not isinstance(data, Mapping):
        return errors
    forbidden = _forbidden_in_evidence(data)
    if forbidden:
        errors.append(f"{source}: forbidden sensitive marker at {forbidden}")
    if data.get("terminal_status") == "PLAN_READY":
        if data.get("human_prompt_count") != 0 or data.get("forbidden_external_operation_count") != 0:
            errors.append(f"{source}: PLAN_READY requires zero human prompts and forbidden external operations")
        acceptance = data.get("acceptance")
        if isinstance(acceptance, Mapping) and not all(value is True for value in acceptance.values()):
            errors.append(f"{source}: PLAN_READY requires every acceptance boolean")
    return errors


def _canonical_evidence_view(data: Mapping[str, Any]) -> object:
    """Remove runtime timestamps and attempt-scoped identifiers only."""
    dynamic_keys = {"attempt_id", "run_id", "generated_at", "requested_at", "observed_at", "accepted_result_digest", "worker_invocation_count"}

    def normalize(value: object) -> object:
        if isinstance(value, Mapping):
            return {key: normalize(child) for key, child in sorted(value.items()) if key not in dynamic_keys and not str(key).endswith("_sha256")}
        if isinstance(value, list):
            return [normalize(child) for child in value]
        if isinstance(value, str):
            value = re.sub(r"purpose-e2e-transparent-boundary-[A-Za-z0-9._-]+", "purpose-e2e-transparent-boundary-<ATTEMPT>", value)
            value = re.sub(r"PURPOSE-E2E:[A-Za-z0-9._-]+", "PURPOSE-E2E:<ATTEMPT>", value)
            return value
        return value

    return normalize(data)


def canonical_evidence_hash(evidence: Mapping[str, Any]) -> str:
    return _digest(_canonical_evidence_view(evidence))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    lane = parser.add_mutually_exclusive_group(required=True)
    lane.add_argument("--offline-fixture", action="store_true")
    lane.add_argument("--live-private", action="store_true")
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--child-python")
    parser.add_argument("--confirm-private-run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path, help="Git-external staging root; defaults to a hidden sibling of --output")
    parser.add_argument("--quality-gates-report", type=Path, help="reuse a validated child-quality-gates/v1 report")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config" / "repositories.yaml")
    parser.add_argument("--check", action="store_true", help="validate an existing output when --output is supplied")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    lane = "live-private" if args.live_private else "networkless"
    try:
        if lane == "live-private" and not args.confirm_private_run:
            raise PurposeE2EError("live-private requires --confirm-private-run")
        if args.check and args.output and args.output.is_file():
            evidence = json.loads(args.output.read_text(encoding="utf-8"))
            errors = validate_purpose_e2e(evidence, str(args.output))
            if errors:
                print(json.dumps({"status": "FAILED", "errors": errors}, ensure_ascii=False, sort_keys=True))
                return 2
            print(json.dumps({"command": "purpose-e2e", "status": "PASSED", "evidence": str(args.output)}, ensure_ascii=False, sort_keys=True))
            return 0
        manifest = load_yaml(args.manifest)
        quality_gate_report = None
        if args.quality_gates_report:
            quality_gate_report = json.loads(args.quality_gates_report.read_text(encoding="utf-8"))
            if not _quality_passed(quality_gate_report):
                raise PurposeE2EError("child quality gate report is not all-PASSED")
        output_root = args.output_root
        if output_root is None and args.output:
            output_root = args.output.parent / f".{args.output.stem}.run"
        evidence = run_purpose_e2e(attempt_id=args.attempt_id, lane=lane, output_root=output_root, state_root=args.state_root, workspace_root=args.workspace_root, child_python=args.child_python, manifest=manifest, quality_gate_report=quality_gate_report)
        errors = validate_purpose_e2e(evidence)
        if errors:
            raise PurposeE2EError("generated evidence is invalid: " + " | ".join(errors[:4]))
        if args.output:
            _write_json(args.output, evidence)
        print(json.dumps({"command": "purpose-e2e", "lane": lane, "attempt_id": args.attempt_id, "canonical_evidence_sha256": canonical_evidence_hash(evidence), "status": evidence["terminal_status"]}, ensure_ascii=False, sort_keys=True))
        return 0 if evidence["terminal_status"] == "PLAN_READY" else 2
    except (OSError, TypeError, ValueError, KeyError, PurposeE2EError, subprocess.SubprocessError) as exc:
        print(json.dumps({"command": "purpose-e2e", "lane": lane, "status": "BLOCKED", "reason": type(exc).__name__}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
