#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MANIFEST_PATH = ROOT / "config/repositories.yaml"
MANIFEST_SCHEMA_PATH = ROOT / "schemas/repository-manifest.schema.json"
SIGNAL_SCHEMA_PATH = ROOT / "schemas/normalized-research-signal.schema.json"
SIGNAL_EXPORT_SCHEMA_PATH = ROOT / "schemas/research-signal-export.schema.json"
WORKITEM_SCHEMA_PATH = ROOT / "schemas/work-item.schema.json"
EXTERNAL_ARTIFACT_SCHEMA_PATH = ROOT / "schemas/external-artifact.schema.json"
INTERACTION_SCHEMA_PATH = ROOT / "schemas/interaction-event.schema.json"
FEEDBACK_SCHEMA_PATH = ROOT / "schemas/feedback-signal.schema.json"
ASYNC_AUDIT_SCHEMA_PATH = ROOT / "schemas/async-audit.schema.json"
ISSUE_ROUTING_SCHEMA_PATH = ROOT / "schemas/issue-routing.schema.json"
ISSUE_DELIVERY_SCHEMA_PATH = ROOT / "schemas/github-issue-delivery.schema.json"
ISSUE_DELIVERY_POLICY_PATH = ROOT / "config/issue-delivery-policy.yaml"
RETRIEVAL_REQUEST_SCHEMA_PATH = ROOT / "schemas/retrieval-request.schema.json"
RETRIEVAL_INDEX_SCHEMA_PATH = ROOT / "schemas/retrieval-index.schema.json"
RETRIEVAL_RESULT_SCHEMA_PATH = ROOT / "schemas/retrieval-result.schema.json"
IMPROVEMENT_LOOP_SCHEMA_PATH = ROOT / "schemas/improvement-loop.schema.json"
INTERACTION_E2E_SCHEMA_PATH = ROOT / "schemas/interaction-e2e.schema.json"
AGENT_UI_SCHEMA_PATH = ROOT / "schemas/agent-ui-result.schema.json"
INITIAL_OPERATIONS_E2E_SCHEMA_PATH = ROOT / "schemas/initial-operations-e2e.schema.json"
INSPIRATION_SCHEMA_PATH = ROOT / "schemas/inspiration-input.schema.json"
V12_BOUNDARY_SCHEMA_PATH = ROOT / "schemas/research-execution-boundary.schema.json"
V12_BOUNDARY_CONFIG_PATH = ROOT / "config/research-execution-boundary.yaml"
TRANSFORMATION_RULE_SCHEMA_PATH = ROOT / "schemas/transformation-rule.schema.json"
TRANSFORMATION_RULE_CONFIG_PATH = ROOT / "config/transformation-rules.yaml"
CANDIDATE_SCHEMA_PATH = ROOT / "schemas/research-candidate.schema.json"
CANDIDATE_GATES_SCHEMA_PATH = ROOT / "schemas/research-candidate-gates.schema.json"
SELECTION_SCHEMA_PATH = ROOT / "schemas/research-selection.schema.json"
SELECTION_V2_SCHEMA_PATH = ROOT / "schemas/research-selection-v2.schema.json"
SELF_DIVERSITY_SCHEMA_PATH = ROOT / "schemas/self-diversity-report.schema.json"
CHILD_QUALITY_GATES_SCHEMA_PATH = ROOT / "schemas/child-quality-gates.schema.json"
PIN_ADOPTION_SCHEMA_PATH = ROOT / "schemas/pin-adoption-report.schema.json"
RESEARCH_PROVENANCE_SCHEMA_PATH = ROOT / "schemas/research-provenance.schema.json"
V12_E2E_SCHEMA_PATH = ROOT / "schemas/v12-e2e.schema.json"
PROJECT_STATUS_SCHEMA_PATH = ROOT / "schemas/project-status.schema.json"
PRODUCTION_EXCHANGE_SCHEMA_PATH = ROOT / "schemas/production-exchange-evidence.schema.json"
PRODUCTION_EXCHANGE_E2E_SCHEMA_PATH = ROOT / "schemas/production-exchange-e2e.schema.json"
STARTUP_POLICY_PATH = ROOT / "config/startup-policy.yaml"
STARTUP_REPORT_SCHEMA_PATH = ROOT / "schemas/startup-report.schema.json"
DRIVE_LIVE_SCHEMA_PATH = ROOT / "schemas/drive-live-evidence.schema.json"
GITHUB_SANDBOX_LIVE_SCHEMA_PATH = ROOT / "schemas/github-sandbox-live-evidence.schema.json"
GITHUB_SANDBOX_LIVE_POLICY_PATH = ROOT / "config/github-sandbox-live-policy.yaml"
DRIVE_LIVE_POLICY_PATH = ROOT / "config/drive-live-policy.yaml"
HUMAN_GATES_PATH = ROOT / "config/human-gates.yaml"
AGENT_ACTION_SCHEMA_PATH = ROOT / "schemas/agent-action.schema.json"
AGENT_RESULT_SCHEMA_PATH = ROOT / "schemas/agent-result.schema.json"
AUTONOMOUS_RUN_SCHEMA_PATH = ROOT / "schemas/autonomous-run.schema.json"
BATCH_REPORT_EVENT_SCHEMA_PATH = ROOT / "schemas/batch-report-event.schema.json"
OUTPUT_DESTINATIONS_SCHEMA_PATH = ROOT / "schemas/output-destinations.schema.json"
DESTINATION_RESOLUTION_SCHEMA_PATH = ROOT / "schemas/destination-resolution.schema.json"
OUTPUT_DESTINATIONS_EXAMPLE_PATH = ROOT / "config/output-destinations.example.yaml"
INSTANCE_PROFILE_SCHEMA_PATH = ROOT / "schemas/instance-profile.schema.json"
INSTANCE_RESOLUTION_SCHEMA_PATH = ROOT / "schemas/instance-resolution.schema.json"
WORKSPACE_BOOTSTRAP_SCHEMA_PATH = ROOT / "schemas/workspace-bootstrap.schema.json"
PUBLIC_PROJECT_LAYOUT_SCHEMA_PATH = ROOT / "schemas/public-project-layout.schema.json"
PUBLIC_PROJECTION_REQUEST_SCHEMA_PATH = ROOT / "schemas/public-projection-request.schema.json"
PUBLIC_PROJECTION_APPROVAL_SCHEMA_PATH = ROOT / "schemas/public-projection-approval.schema.json"
PUBLIC_PROJECTION_RESULT_SCHEMA_PATH = ROOT / "schemas/public-projection-result.schema.json"
PUBLIC_PROJECTION_FIXTURE_ROOT = ROOT / "tests/fixtures/public-projection"
KNOWLEDGE_OWNER_REGISTRY_PATH = ROOT / "config/knowledge-owners.yaml"
KNOWLEDGE_CONTRACT_PATHS = [
    ROOT / "schemas/artifact-record.schema.json",
    ROOT / "schemas/knowledge-write-receipt.schema.json",
    ROOT / "schemas/reuse-trace.schema.json",
]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
DATE_TIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "PLANS.md",
    "config/repositories.yaml",
    "config/orchestration.yaml",
    "schemas/repository-manifest.schema.json",
    "schemas/normalized-research-signal.schema.json",
    "schemas/normalized-research-signal-bundle.schema.json",
    "schemas/research-signal-export.schema.json",
    "schemas/work-item.schema.json",
    "schemas/external-artifact.schema.json",
    "schemas/interaction-event.schema.json",
    "schemas/feedback-signal.schema.json",
    "schemas/async-audit.schema.json",
    "schemas/issue-routing.schema.json",
    "config/issue-delivery-policy.yaml",
    "schemas/github-issue-delivery.schema.json",
    "tools/github_issue_adapter.py",
    "schemas/retrieval-request.schema.json",
    "schemas/retrieval-index.schema.json",
    "schemas/retrieval-result.schema.json",
    "schemas/improvement-loop.schema.json",
    "schemas/interaction-e2e.schema.json",
    "schemas/agent-ui-result.schema.json",
    "schemas/initial-operations-e2e.schema.json",
    "schemas/inspiration-input.schema.json",
    "schemas/research-execution-boundary.schema.json",
    "config/research-execution-boundary.yaml",
    "tools/v12_boundary.py",
    "schemas/transformation-rule.schema.json",
    "config/transformation-rules.yaml",
    "tools/transformation_rules.py",
    "tools/export_signal.py",
    "schemas/research-candidate.schema.json",
    "tools/candidate_space.py",
    "tools/signal_bundle.py",
    "tools/input_pipeline.py",
    "tools/run.py",
    "config/human-gates.yaml",
    "schemas/pr-triage-report.schema.json",
    "tools/pr_triage.py",
    "schemas/agent-action.schema.json",
    "schemas/agent-result.schema.json",
    "schemas/autonomous-run.schema.json",
    "tools/autonomous_runner.py",
    "schemas/batch-report-event.schema.json",
    "schemas/batch-run.schema.json",
    "schemas/output-destinations.schema.json",
    "schemas/instance-profile.schema.json",
    "schemas/instance-resolution.schema.json",
    "schemas/destination-resolution.schema.json",
    "schemas/workspace-bootstrap.schema.json",
    "schemas/public-project-layout.schema.json",
    "schemas/public-projection-request.schema.json",
    "schemas/public-projection-approval.schema.json",
    "schemas/public-projection-result.schema.json",
    "tools/public_projection.py",
    "tools/knowledge_cycle.py",
    "config/knowledge-owners.yaml",
    "schemas/artifact-record.schema.json",
    "schemas/knowledge-write-receipt.schema.json",
    "schemas/reuse-trace.schema.json",
    "knowledge/README.md",
    "tools/batch_status.py",
    "tools/batch_run.py",
    "tools/output_destinations.py",
    "tools/instance_profiles.py",
    "tools/inspiration.py",
    "tools/research_request.py",
    "tools/research_start.py",
    "tools/qualify_pin_update.py",
    "tools/qualify_pin_update.py",
    "schemas/research-candidate-gates.schema.json",
    "tools/candidate_gates.py",
    "schemas/research-selection.schema.json",
    "schemas/research-selection-v2.schema.json",
    "tools/candidate_selection.py",
    "schemas/self-diversity-report.schema.json",
    "schemas/child-quality-gates.schema.json",
    "tools/child_quality_gates.py",
    "tools/pinned_workspace.py",
    "schemas/pin-adoption-report.schema.json",
    "tools/pin_adopt.py",
    "schemas/research-provenance.schema.json",
    "tools/proposition_provenance.py",
    "schemas/v12-e2e.schema.json",
    "schemas/project-status.schema.json",
    "tools/project_status.py",
    "schemas/production-exchange-evidence.schema.json",
    "schemas/production-exchange-e2e.schema.json",
    "schemas/purpose-e2e-evidence.schema.json",
    "schemas/viewer-response-assessment.schema.json",
    "tools/production_exchange.py",
    "tools/purpose_e2e.py",
    "tools/v12_e2e.py",
    "tools/startup.py",
    "config/startup-policy.yaml",
    "schemas/startup-report.schema.json",
    "config/drive-live-policy.yaml",
    "schemas/drive-live-evidence.schema.json",
    "tools/drive_live_bridge.py",
    "tools/drive_live_check.py",
    "config/github-sandbox-live-policy.yaml",
    "schemas/github-sandbox-live-evidence.schema.json",
    "tools/github_sandbox_live_check.py",
    "tools/viewer_response_gate.py",
    "tools/agent_ui.py",
    "tools/initial_operations_e2e.py",
    "execution/task-queue.yaml",
    "execution/state.yaml",
    "execution/handoff.md",
    "docs/20260811-agentic-art-orchestration-system-design-specification.md",
    "docs/20260811-agentic-art-orchestration-repository-execution-plan.md",
    "docs/cross-repository-contract.md",
    "docs/interaction-improvement-runbook.md",
    "docs/purpose-e2e-runbook.md",
    "docs/agent-ui-runbook.md",
    "docs/input-pipeline-runbook.md",
    ".github/ISSUE_TEMPLATE/decision.yml",
]
STATUSES = {"BACKLOG", "READY", "IN_PROGRESS", "BLOCKED", "DONE"}
ROLES = {"input-kb", "consumer-runtime", "control-plane-extension"}
CONTRACTS = {"normalized-research-signal/v1"}
EXCHANGE_CONTRACTS = {"production-handoff/v1", "production-result/v1"}
CORE_REPOSITORY_IDS = {
    "self-model",
    "art-history",
    "marketing-trends",
    "agentic-art-research",
}
REQUIRED_PROFILE_FORBIDDEN_DATA = {
    "PRIVATE_RAW",
    "RESTRICTED",
    "credential",
    "direct_identifier",
}
COMMAND_FORBIDDEN_TOKENS = ("\x00", "\r", "\n", ";", "&&", "||", "|", ">", "<", "`")
GITHUB_ISSUE_URL = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/[1-9][0-9]*$"
)
AGENT_TERMINALS = {"COMMIT_READY", "DRAFT_PR_READY", "EVIDENCE_READY"}
ISSUE_SSO_TASK_IDS = {
    "GAP-DAG-001",
    "V14-SANDBOX-ATTEMPT-001",
    "V14-CHILD-PREFLIGHT-001",
    "V14-PIN-RELEASE-CHECK-001",
    "V14-OBSERVATION-PROVENANCE-001",
    "V14-RECONCILE-001",
    "PROJECT-STATUS-001",
    "PURPOSE-NAMING-001",
    "PURPOSE-INSPIRATION-001",
    "PURPOSE-SELF-EXPORT-SOURCE-001",
    "SELF-EXPORT-E2E-001",
    "PURPOSE-SELF-DIVERSITY-001",
    "PURPOSE-INTENT-RANK-001",
    "PURPOSE-RESEARCH-KNOWLEDGE-001",
    "PURPOSE-RESEARCH-DECISIONS-001",
    "PURPOSE-RESEARCH-VISUAL-001",
    "PURPOSE-PRODUCTION-OBSERVATION-001",
    "PURPOSE-PRODUCTION-REVISION-001",
    "PURPOSE-RESEARCH-FEEDBACK-001",
    "PURPOSE-VIEWER-RESPONSE-001",
    "PURPOSE-AUTONOMOUS-RUNNER-001",
    "PURPOSE-BATCH-STATUS-001",
    "PURPOSE-BATCH-100-001",
    "PURPOSE-E2E-001",
}
STARTUP_STEPS = [
    "validate_parent_configuration",
    "observe_remote_heads",
    "guard_pinned_workspaces",
    "select_qualified_snapshot",
    "materialize_snapshot",
    "collect_status",
    "run_audit",
    "run_security",
    "decide_capabilities",
]
STARTUP_CAPABILITIES = [
    "qualified_knowledge_read",
    "evidence_trace_read",
    "feedback_capture",
    "audit_observation",
    "drive_create",
    "github_issue_create",
    "child_repository_mutation",
    "drive_update_delete_share",
    "github_issue_update_close_delete_comment_label",
    "branch_commit_pull_request_merge_release",
]
STARTUP_OUTCOMES = {"READY", "READY_WITH_FINDINGS", "BLOCKED"}
STARTUP_FORBIDDEN_FIELDS = {
    "token",
    "access_token",
    "credential_value",
    "raw_remote_response",
    "raw_conversation",
    "conversation_body",
    "drive_body",
    "direct_identifier",
    "PRIVATE_RAW",
    "RESTRICTED",
}


def load_yaml(path: Path):
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: YAML parse failed: {exc}") from exc


def load_json(path: Path):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: JSON parse failed: {exc}") from exc


def _type_matches(value, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_type_matches(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _schema_errors(value, schema: dict, path: str = "$", root_schema: dict | None = None) -> list[str]:
    """Validate the repository schemas' small JSON Schema subset without a dependency."""
    root_schema = root_schema or schema
    errors: list[str] = []

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            return [f"{path}: unsupported schema reference {ref!r}"]
        definition = root_schema.get("$defs", {}).get(ref.removeprefix("#/$defs/"))
        if definition is None:
            return [f"{path}: schema reference {ref!r} is undefined"]
        return _schema_errors(value, definition, path, root_schema)

    expected_type = schema.get("type")
    if expected_type and not _type_matches(value, expected_type):
        return [f"{path}: expected type {expected_type}, got {type(value).__name__}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}")

    if isinstance(value, dict):
        minimum = schema.get("minProperties")
        if minimum is not None and len(value) < minimum:
            errors.append(f"{path}: requires at least {minimum} properties")
        maximum = schema.get("maxProperties")
        if maximum is not None and len(value) > maximum:
            errors.append(f"{path}: allows at most {maximum} properties")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: required; add the manifest field")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: unknown field; remove it or add it to the schema")
        elif isinstance(schema.get("additionalProperties"), dict):
            additional_schema = schema["additionalProperties"]
            for key, item in value.items():
                if key not in properties:
                    errors.extend(_schema_errors(item, additional_schema, f"{path}.{key}", root_schema))
        for key, property_schema in properties.items():
            if key in value:
                errors.extend(_schema_errors(value[key], property_schema, f"{path}.{key}", root_schema))

    if isinstance(value, list):
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < minimum:
            errors.append(f"{path}: requires at least {minimum} items")
        if schema.get("uniqueItems"):
            for index, item in enumerate(value):
                if item in value[:index]:
                    errors.append(f"{path}[{index}]: must be unique")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, item_schema, f"{path}[{index}]", root_schema))

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            errors.append(f"{path}: must not be empty")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            errors.append(f"{path}: value {value!r} does not match required pattern")
        if schema.get("format") == "date-time" and DATE_TIME.fullmatch(value) is None:
            errors.append(f"{path}: must be an ISO-8601 date-time")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: must be at least {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: must be at most {maximum}")

    alternatives = schema.get("oneOf", [])
    if alternatives:
        matches = [
            branch for branch in alternatives
            if not _schema_errors(value, branch, path, root_schema)
        ]
        if len(matches) != 1:
            errors.append(
                f"{path}: must satisfy exactly one schema alternative"
            )
    return errors


def validate_autonomous_contract(
    human_gates: dict,
    action_schema: dict | None = None,
    result_schema: dict | None = None,
    run_schema: dict | None = None,
    source: str = "autonomous-runner",
) -> list[str]:
    """Keep the worker boundary versioned, closed, and human-gated."""
    errors: list[str] = []
    expected_operations = [
        "merge",
        "release",
        "public_share",
        "consent_expansion",
        "destructive_git",
        "external_cost_over_declared_budget",
        "physical_action",
    ]
    if not isinstance(human_gates, dict):
        return [f"{source}: human gate policy must be an object; remediation: restore config/human-gates.yaml"]
    if human_gates.get("contract_version") != "human-gates/v1":
        errors.append(f"{source}: unsupported human gate policy version; remediation: use human-gates/v1")
    if human_gates.get("human_operations") != expected_operations:
        errors.append(f"{source}: human operation vocabulary is incomplete or reordered; remediation: preserve the seven fixed human gates")
    if human_gates.get("default_status") != "BLOCKED_HUMAN":
        errors.append(f"{source}: default human gate status is unsafe; remediation: use BLOCKED_HUMAN")
    if human_gates.get("worker_may_request") is not True or human_gates.get("execution_policy") != "never_execute_requested_human_operation":
        errors.append(f"{source}: worker human-operation policy is unsafe; remediation: never execute requested human operations")
    schemas = (
        ("agent-action/v1", action_schema, "agent action"),
        ("agent-result/v1", result_schema, "agent result"),
        ("autonomous-run/v1", run_schema, "autonomous run"),
    )
    for version, schema, label in schemas:
        if not isinstance(schema, dict) or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{source}: {label} schema must be Draft 2020-12; remediation: restore the closed versioned schema")
        if isinstance(schema, dict):
            if schema.get("additionalProperties") is not False:
                errors.append(f"{source}: {label} schema must reject unknown fields; remediation: set additionalProperties to false")
            if not any(property_schema.get("const") == version for property_schema in [schema.get("properties", {}).get("contract_version", {})] if isinstance(property_schema, dict)):
                errors.append(f"{source}: {label} schema has the wrong contract version; remediation: preserve {version}")
    return errors


def validate_batch_report_contract(
    event_schema: dict | None = None,
    source: str = "schemas/batch-report-event.schema.json",
) -> list[str]:
    """Keep batch events closed, metadata-only, and append-only compatible."""
    event_schema = event_schema if event_schema is not None else load_json(BATCH_REPORT_EVENT_SCHEMA_PATH)
    errors: list[str] = []
    if not isinstance(event_schema, dict):
        return [f"{source}: batch report event schema must be an object; remediation: restore the v1 schema"]
    if event_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append(f"{source}: batch report event schema must be Draft 2020-12; remediation: preserve the closed v1 contract")
    if event_schema.get("additionalProperties") is not False:
        errors.append(f"{source}: batch report event schema must reject unknown fields; remediation: set additionalProperties to false")
    version = event_schema.get("properties", {}).get("contract_version", {})
    if not isinstance(version, dict) or version.get("const") != "batch-report-event/v1":
        errors.append(f"{source}: batch report event schema has the wrong contract version; remediation: preserve batch-report-event/v1")
    expected_required = {
        "contract_version", "event_id", "run_id", "event_type", "project_id",
        "repository", "source_commit", "observed_at", "attempt",
        "duration_seconds", "token_count",
    }
    if set(event_schema.get("required", [])) != expected_required:
        errors.append(f"{source}: batch report event required fields are incomplete or expanded; remediation: keep the metadata envelope minimal")
    event_types = event_schema.get("properties", {}).get("event_type", {}).get("enum")
    if event_types != ["STARTED", "COMPLETED", "FAILED", "RETRY", "DURATION", "TOKENS"]:
        errors.append(f"{source}: event type vocabulary is unsafe; remediation: preserve the fixed append-only event types")
    return errors


def validate_output_destinations_contract(
    config_schema: dict | None = None,
    resolution_schema: dict | None = None,
    example: dict | None = None,
    source: str = "output-destinations",
) -> list[str]:
    """Keep destination profiles and resolution evidence closed and versioned."""
    config_schema = config_schema if config_schema is not None else load_json(OUTPUT_DESTINATIONS_SCHEMA_PATH)
    resolution_schema = resolution_schema if resolution_schema is not None else load_json(DESTINATION_RESOLUTION_SCHEMA_PATH)
    errors: list[str] = []
    draft = "https://json-schema.org/draft/2020-12/schema"
    for schema, label, version in (
        (config_schema, "output destination", "output-destinations/v1"),
        (resolution_schema, "destination resolution", "destination-resolution/v1"),
    ):
        if not isinstance(schema, dict) or schema.get("$schema") != draft:
            errors.append(f"{source}: {label} schema must be Draft 2020-12; remediation: restore the closed versioned schema")
            continue
        if schema.get("additionalProperties") is not False:
            errors.append(f"{source}: {label} schema must reject unknown fields; remediation: set additionalProperties to false")
        contract = schema.get("properties", {}).get("contract_version", {})
        if not isinstance(contract, dict) or contract.get("const") != version:
            errors.append(f"{source}: {label} schema has the wrong contract version; remediation: preserve#ЌёУKh‘йм¶»§q«^tЩK€€ћЬ]KћЪЩ^_H\ИH›ЬљY[€]ИЬ€Щ[њЪ]]™H]Y]љY[‹€њ™]Z[€љ]XЮK\ШY™Hљ[™[™ИY]Y]H[™Ь\]YH™Y™\™[Щ\ИЫ›H‹€
B€
B€ШШ[ЉЪ[€ћЬ]KћЪЩ^_HЉB€[Y€\Ъ[њЭ[ЩJ[YK\Э
N‚€›Ь€[™^Ъ[[€[ќ[Y\]J[YJN‚€ШШ[ЉЪ[€ћЬ]VЮЪ[™^WHЉB‚€ШШ[Љ]JB€Y€]K™Щ]
›[™HЉHOHђTЦSђЧРUQUЋ‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK›[™H]\Э™HTЦSђЧРUQU‹љЩY\]Y]ЫЬљИЫ€H[™\[™[ќ\Ю[Ъ›Ы›Э\И[™HЉB€
B€Y€]K™Щ]
љ[ќ\XЭ[Ы—Ш›ШЪЪ[™ИЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы—Ш›ШЪЪ[™И]\Э™H[ЩH‹›™]™\€ШZ]›Ь€]Y]Ь™YXЭЬљ[™И[€H[ќ\XЭ[Ы€™\]Y\Э]ЉB€
B€Y€]K™Щ]
ќ\Щ\—Ш\ќYXЭЬЫXЮHЉHOH”‘PQУУ“H€Ь€]K™Щ]
\ќYXЭЫЬ\][ЫњИЉHOHЧN‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKќ\Щ\€\ќYXЭИ]\Э™H™XY[Ы›HЪ]›ИЬ\][ЫњИ‹Ь™X]H›И\]KЩ[]HЬ\][Ы€›Ь€\Щ\€\ќYXЭИЉB€
B‚€Ы\ЪЭH]K™Щ]
њЫЭ\ЩWЬЫ\ЪЭЉB€ЫЭ\ЩWШЫЫ[Z]О€XЭЬЭ‹Э—HHЯB€Ы›ЭЫ€HЪЫ›ЭЫ—Ь™\ЬЪ]ЬћWЪYК
HИYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€џB€Y€\Ъ[њЭ[ЩJЫ\ЪЭXЭ
N‚€™\ЬЪ]ЬљY\ИHЫ\ЪЭ™Щ]
њ™\ЬЪ]ЬљY\ИЉB€Y€\Ъ[њЭ[ЩJ™\ЬЪ]ЬљY\Л\Э
N‚€›Ь€[™^™\ЬЪ]ЬћH[€[ќ[Y\]J™\ЬЪ]ЬљY\КN‚€Y€›Э\Ъ[њЭ[ЩJ™\ЬЪ]ЬћKXЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћWЪYH™\ЬЪ]ЬћK™Щ]
њ™\ЬЪ]ЬћHЉB€ЫЫ[Z]H™\ЬЪ]ЬћK™Щ]
њЫЭ\ЩWШЫЫ[Z]ЉB€Y€™\ЬЪ]ЬћWЪY[€ЫЭ\ЩWШЫЫ[Z]О‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€њЫЭ\ЩWЬЫ\ЪЭњ™\ЬЪ]ЬљY\ЦЮЪ[™^WH\XШ]\ИЬ™\ЬЪ]ЬћWЪY\џH‹€њ™XЫЬ™Ы™H[[]]X›HЫЫ[Z]\€™\ЬЪ]ЬћH‹€
B€
B€Y€\Ъ[њЭ[ЩJ™\ЬЪ]ЬћWЪYЭЉN‚€ЫЭ\ЩWШЫЫ[Z]ЦЬ™\ЬЪ]ЬћWЪYHHЫЫ[Z]€Y€™\ЬЪ]ЬћWЪY›Э[€Ы›ЭЫЋ‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€њЫЭ\ЩHЫ\ЪЭ™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћWЪY\џH\И›ЭXЫ\™Y‹€ќ\ЩHX[љY™\Э™\ЬЪ]ЬћHQИ‹€
B€
B€\™[ќШЫЫ[Z]HЫ\ЪЭ™Щ]
њ\™[ќШЫЫ[Z]ЉB€Y€\Ъ[њЭ[ЩJ\™[ќШЫЫ[Z]ЭЉN‚€ЫЭ\ЩWШЫЫ[Z]ЦИYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€—HH\™[ќШЫЫ[Z]‚€X\ЩHH]K™Щ]
›X\ЩHЉB€Y€\Ъ[њЭ[ЩJX\ЩKXЭ
N‚€Y€X\ЩK™Щ]
›[™HЉHOHђTЦSђЧРUQU€Ь€X\ЩK™Щ]
њЭ]\ИЉHOHљ[Ћ‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€›X\ЩH]\Э™H[Ы€TЦSђЧРUQU‹€XЬ]Z\™HH[™\[™[ќ]Y][™HX\ЩH™Y›Ь™H[Z][™И›ЬЬШ[И‹€
B€
B€Y€X\ЩK™Щ]
›ЭЫ™\€ЉHOHќ[\ЬЪYЫ™YЋ‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[]Y]X\ЩHШ[››Э™H[\ЬЪYЫ™Y‹њ™XЫЬ™HЫЬљЩ\€ЭЫ™\€[™^XЭ][Ы€QЉB€
B‚€Ш]\О€XЭЬЭ‹Э—HHЯB€]X[]WЩШ]\ИH]K™Щ]
њ]X[]WЩШ]\ИЉB€Y€\Ъ[њЭ[ЩJ]X[]WЩШ]\Л\Э
N‚€›Ь€[™^Ш]H[€[ќ[Y\]J]X[]WЩШ]\КN‚€Y€›Э\Ъ[њЭ[ЩJШ]KXЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћHHШ]K™Щ]
њ™\ЬЪ]ЬћHЉB€Э]\ИHШ]K™Щ]
њЭ]\ИЉB€Y€™\ЬЪ]ЬћH[€Ш]\О‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ]X[]WЩШ]\ЦЮЪ[™^WH\XШ]\ИЬ™\ЬЪ]ЬћH\џH‹њ™XЫЬ™Ы™HШ]H™\Э[\€™\ЬЪ]ЬћHЉB€
B€Y€\Ъ[њЭ[ЩJ™\ЬЪ]ЬћKЭЉN‚€Ш]\ЦЬ™\ЬЪ]ЬћWHHЭ]\В€Y€™\ЬЪ]ЬћH›Э[€ЫЭ\ЩWШЫЫ[Z]О‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ]X[]HШ]H[Y\И[љЫ›ЭЫ€™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћH\џH‹ќ\ЩHH™\ЬЪ]ЬћH[€HЫЭ\ЩHЫ\ЪЭЉB€
B€Y€Ш]K™Щ]
›ШњЩ\ќ™YШЫЫ[Z]ЉHOHЫЭ\ЩWШЫЫ[Z]Л™Щ]
™\ЬЪ]ЬћJN‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€њ]X[]HШ]H›Ь€Ь™\ЬЪ]ЬћH\џH\И›ЭYYИ]ИЫЭ\ЩHЫЫ[Z]‹€њќ[€Ь€™XЫЬ™HШ]HYШZ[њЭH]Y]Y[[]]X›HЫЫ[Z]‹€
B€
B‚€›ЬЬШ[ИH]K™Щ]
њ›ЬЬШ[ИЉB€›ЬЬШ[ЪYО€Щ]ЬЭ—HHЩ]

B€Y\XШ][Ы—ЪЩ^\О€Щ]ЬЭ—HHЩ]

B€]Y]Ъ\ЪH]K™Щ]
]Y]ЫШњЩ\ќ][Ы€‹ЯJK™Щ]
]Y]Ъ\ЪЉHY€\Ъ[њЭ[ЩJ]K™Щ]
]Y]ЫШњЩ\ќ][Ы€ЉKXЭ
H[ЩH›Ы™B€Y€\Ъ[њЭ[ЩJ›ЬЬШ[Л\Э
N‚€›Ь€[™^›ЬЬШ[[€[ќ[Y\]J›ЬЬШ[КN‚€Y€›Э\Ъ[њЭ[ЩJ›ЬЬШ[XЭ
N‚€ЫЫќ[ќYB€›ЬЬШ[ЪYH›ЬЬШ[™Щ]
њ›ЬЬШ[ЪYЉB€Щ^HH›ЬЬШ[™Щ]
™Y\XШ][Ы—ЪЩ^HЉB€Y€›ЬЬШ[ЪY[€›ЬЬШ[ЪYО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[ЦЮЪ[™^WH\XШ]\И›ЬЬШ[ЪYЬ›ЬЬШ[ЪY\џH‹њ™\Щ\ќ™HЫ™H›ЬЬШ[\€ЭX›HQЉJB€Y€Щ^H[€Y\XШ][Ы—ЪЩ^\О‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[ЦЮЪ[™^WH\XШ]\ИY\XШ][Ы—ЪЩ^HЪЩ^H\џH‹њЭ\™\ЬИ\XШ]H\ЬЭYHЬ€YќT€›ЬЬШ[ИЉJB€Y€\Ъ[њЭ[ЩJ›ЬЬШ[ЪYЭЉN‚€›ЬЬШ[ЪYЛY
›ЬЬШ[ЪY
B€Y€\Ъ[њЭ[ЩJЩ^KЭЉN‚€Y\XШ][Ы—ЪЩ^\ЛY
Щ^JB€™\ЬЪ]ЬћHH›ЬЬШ[™Щ]
њ™\ЬЪ]ЬћHЉB€Y€™\ЬЪ]ЬћH›Э[€ЫЭ\ЩWШЫЫ[Z]О‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џH\™Щ]И[љЫ›ЭЫ€™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћH\џH‹њ›Э]HИHЫЭ\ЩHЫ\ЪЭ™\ЬЪ]ЬћHЬ€H\™[ќЉJB€ЫЫќ[ќYB€Y€›ЬЬШ[™Щ]
њЫЭ\ЩWШЫЫ[Z]ЉHOHЫЭ\ЩWШЫЫ[Z]ЦЬ™\ЬЪ]ЬћWN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џHЫЭ\ЩHЫЫ[Z]Щ\И›ЭX]ЪЫ\ЪЭ‹њ™X\ЩHH›ЬЬШ[Ы€HШњЩ\ќ™YЫЫ[Z]ЉJB€Ш]WЬЭ]\ИH›ЬЬШ[™Щ]
њ]X[]WЩШ]WЬЭ]\ИЉB€Y€Ш]WЬЭ]\ИOHШ]\Л™Щ]
™\ЬЪ]ЬћJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џHШ]HЭ]\И\И›ЭH™XЫЬ™Y™\ЬЪ]ЬћHШ]H‹™И›Эћ\\ЬИHZ\ЬЪ[™ИЬ€Z[Y]X[]HШ]HЉJB€Y€›ЬЬШ[™Щ]
љЪ[™ЉHOH‘ђQ•Ф€€[™Ш]WЬЭ]\ИOH”TФСQЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џH\ИHYќ€Ъ]Э]H\ЬЩYШ]H‹љЩY\]\ИHљXYЩH\ЬЭYH[ќ[HШ]H\ЬЩ\ИЉJB€Y€›ЬЬШ[™Щ]
љЪ[™ЉHOH‘ђQ•Ф€€[™›ЬЬШ[™Щ]
њЭ]\ИЉHOH”‘PQHЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џHYќ€[€\И›Э‘PQH‹›XZЩHHШ]YYќ[€^XЪ]H‘PQHЉJB€љ[™[™ИH›ЬЬШ[™Щ]
™љ[™[™ИЉB€Y€\Ъ[њЭ[ЩJљ[™[™ЛXЭ
H[™љ[™[™Л™Щ]
]Y]Ъ\ЪЉHOH]Y]Ъ\Ъ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џH\И›ЭXЩXX›HИ\И]Y]‹њ™]Z[€HЫЭ\ЩH]Y]\Ъ[€XXЪ›ЬЬШ[ЉJB€Y€›ЬЬШ[™Щ]
љ[X[—ЩШ]HЉH\И›ЭќYN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џH]\Э™]Z[€H[X[€Ш]H‹™И›ЭY\™ЩHЬ€™[X\ЩH]]ЫX]XШ[HЉJB€Y€›ЬЬШ[™Щ]
\ќYXЭЫЬ\][ЫњИЉHOHЧN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›ЬЬШ[Ь›ЬЬШ[ЪY\џH]]]\ИH\Щ\€\ќYXЭ‹љЩY\\Щ\€\ќYXЭЬ\][ЫњИ[\HЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЪ\ЬЭYWЬ›Э][™К]N€XЭЫЭ\ЩN€Э€Hљ\ЬЭYK\›Э][™ИЉHO€\ЭЬЭ—N‚€€€•[Y]H]]Ьљ]KX\ЩY™YYXЪИ›Э]\ИЪ]Э]Ь™X][™И™[[ЭH\ЬЭY\Л€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉTФХQWФ“ХUS‘ЧФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH™YYXЪИ›Э][™ИљY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ‚€›ЬљY[—ЩљY[ИHВ€ЫЫќ™\њШ][Ы€‹€ќ[њШЬљ\‹€њ›Ы\‹€›Y\ЬШYЩH‹€њ]ЧЭ^‹€њ]ЧШЫЫќ™\њШ][Ы€‹€ќ\Щ\—Э^‹€\ЬЪ\Э[ќЭ^‹€›ЩH‹€ЫЫќ[ќ‹€”’UђUWФђUИ‹€”‘TХ’PХQ‹€Ь™Y[ќX[‹€™\™XЭЪY[ќYљY\€‹€B‚€Y€ШШ[Љ[YK]€Э€H‰ЉHO€›Ы™N‚€Y€\Ъ[њЭ[ЩJ[YKXЭ
N‚€›Ь€Щ^KЪ[[€[YKљ][\К
N‚€Y€ЭЉЩ^JK›ЭЩ\Љ
H[€Ъ][K›ЭЩ\Љ
H›Ь€][H[€›ЬљY[—ЩљY[ЯN‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€ћЬ]KћЪЩ^_H\ИH›ЬљY[€]ИЬ€Щ[њЪ]]™H›Э][™ИљY[‹€њ™]Z[€Э[[X\ћHЫЩ\И[™Ь\]YH]љY[ЩH™Y™\™[Щ\ИЫ›H‹€
B€
B€ШШ[ЉЪ[€ћЬ]KћЪЩ^_HЉB€[Y€\Ъ[њЭ[ЩJ[YK\Э
N‚€›Ь€[™^Ъ[[€[ќ[Y\]J[YJN‚€ШШ[ЉЪ[€ћЬ]VЮЪ[™^WHЉB‚€ШШ[Љ]JB€Y€]K™Щ]
›[™HЉHOH‘‘QQђPТЧФ“ХUS‘ИЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK›[™H]\Э™H‘QQђPТЧФ“ХUS‘И‹љЩY\›Э][™ИЫ€H™YYXЪИ[™HЉJB€Y€]K™Щ]
љ[ќ\XЭ[Ы—Ш›ШЪЪ[™ИЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы—Ш›ШЪЪ[™И]\Э™H[ЩH‹™И›ЭXZЩHH\Щ\€ШZ]›Ь€\ЬЭYH›Э][™ИЉJB€Y€]K™Щ]
ќ\Щ\—Ш\ќYXЭЬЫXЮHЉHOH”‘PQУУ“H€Ь€]K™Щ]
љ\ЬЭYWЫЬ\][ЫњИЉHOHЧN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњ›Э][™И]\Э›Э]]]H\Щ\€\ќYXЭИЬ€Ь™X]H™[[ЭH\ЬЭY\И‹њ™]\›€Y]Y]K[Ы›H\ЬЭYHШ[™Y]\ИЉJB‚€Ы›ЭЫ€HЪЫ›ЭЫ—Ь™\ЬЪ]ЬћWЪYК
HИYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€џB€\™[ќHYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€‚€™YYXЪЧЪYИH]K™Щ]
љ[њ]Щ™YYXЪЧЪYИЉB€›Э]\ИH]K™Щ]
њ›Э]\ИЉB€›Э]WЪYО€Щ]ЬЭ—HHЩ]

B€Y€\Ъ[њЭ[ЩJ›Э]\Л\Э
N‚€›Ь€[™^›Э]H[€[ќ[Y\]J›Э]\КN‚€Y€›Э\Ъ[њЭ[ЩJ›Э]KXЭ
N‚€ЫЫќ[ќYB€™YYXЪЧЪYH›Э]K™Щ]
™™YYXЪЧЪYЉB€Y€™YYXЪЧЪY[€›Э]WЪYО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]\ЦЮЪ[™^WH\XШ]\И™YYXЪЧЪYЩ™YYXЪЧЪY\џH‹њ›Э]HXXЪ™YYXЪИЪYЫ[ЫЩHЉJB€Y€\Ъ[њЭ[ЩJ™YYXЪЧЪYЭЉN‚€›Э]WЪYЛY
™YYXЪЧЪY
B€\™Щ]H›Э]K™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬћHЉB€\™Щ]Ь›ЫHH›Э]K™Щ]
ќ\™Щ]Ь›ЫHЉB€Y€\Ъ[њЭ[ЩJ\™Щ]ЭЉH[™\™Щ]›Э[€Ы›ЭЫЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]HЩ™YYXЪЧЪY\џH\™Щ]И[љЫ›ЭЫ€™\ЬЪ]ЬћHЭ\™Щ]\џH‹ќ\ЩHHX[љY™\Э™\ЬЪ]ЬћHЬ€H\™[ќЉJB€Y€\™Щ]Ь›ЫHOH”T‘S•€[™\™Щ]OH\™[ќ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]HЩ™YYXЪЧЪY\џHX\љЬИH›Ы‹\\™[ќ\™Щ]\ИT‘S•‹њ›Э]HЬЪ\Э][Ы€[™V™YYXЪИИH\™[ќЉJB€Y€\™Щ]Ь›ЫHOHђТS€[™
\™Щ]\И›Ы™HЬ€\™Щ]OH\™[ќ
N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]HЩ™YYXЪЧЪY\џHX\љЬИH\™[ќ\ИТS‹њ›Э]HЫXZ[€™YYXЪИИ]ИЭЫљ[™ИЪ[ЉJB€Ш[™Y]\ИH›Э]K™Щ]
Ш[™Y]WЬ™\ЬЪ]ЬљY\ИЉB€Y€\Ъ[њЭ[ЩJШ[™Y]\Л\Э
N‚€›Ь€Ш[™Y]H[€Ш[™Y]\О‚€Y€Ш[™Y]H›Э[€Ы›ЭЫЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]HЩ™YYXЪЧЪY\џH\И[љЫ›ЭЫ€Ш[™Y]HШШ[™Y]H\џH‹ќ\ЩHX[љY™\Э™\ЬЪ]ЬћHQИЉJB€[™™\™[ЩHH›Э]K™Щ]
љ[™™\™[ЩHЉB€Ъ[™H›Э]K™Щ]
љЪ[™ЉB€Y€\Ъ[њЭ[ЩJ[™™\™[ЩKXЭ
N‚€Y€Ъ[™[€Иљ[™™\њ™YЩњљXЭ[Ы€‹љ[™™\њ™YЫ™YYџN‚€Y€[™™\™[ЩK™Щ]
љ\ЧЪ[™™\њ™YЉH\И›ЭќYHЬ€[™™\™[ЩK™Щ]
љ\Э\Ъ\ЧЬЭ]\ИЉHOHќ[ЫЫ™љ\›YYЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€љ[™™\њ™Y›Э]HЩ™YYXЪЧЪY\џHЬЭ]И[ЫЫ™љ\›YY\Э\Ъ\И‹љЩY\[™™\™[ЩHЩ\\]Hњ›ЫH\Щ\€ќ]ЉJB€[Y€[™™\™[ЩK™Щ]
љ\ЧЪ[™™\њ™YЉH\И›Э[ЩHЬ€[™™\™[ЩK™Щ]
љ\Э\Ъ\ЧЬЭ]\ИЉHOH››ЭX\XШX›HЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™^XЪ]›Э]HЩ™YYXЪЧЪY\џHШ\њљY\И[™™\™[ЩHЭ]H‹›X\љИ^XЪ]™YYXЪИ\И›ЭX\XШX›H›Ь€[™™\™[ЩHЉJB€Э]\ИH›Э]K™Щ]
њ›Э][™ЧЬЭ]\ИЉB€Ш[™Y]HH›Э]K™Щ]
љ\ЬЭYWШШ[™Y]HЉB€Y€Э]\И[€И”“ХUQ‹•’PQСHџH[™›Э\Ъ[њЭ[ЩJШ[™Y]KXЭ
N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]HЩ™YYXЪЧЪY\џHXЪЬИHY]Y]K[Ы›H\ЬЭYHШ[™Y]H‹њ™]Z[€HљXYЩXX›HШ[™Y]HЪ]Э]Ь™X][™И]™[[Э[HЉJB€Y€Э]\И[€Иђ“РТСQ‹‘TPРUWФХT‘TФСQџH[™Ш[™Y]H\И›Э›Ы™N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]HЩ™YYXЪЧЪY\џH\ИHШ[™Y]HYќ\€ЬЭ]\ЯH‹њЭ\™\ЬИЬ€›ШЪИHШ[™Y]HЪ]Э]ЪYHY™™XЭИЉJB€Y€\Ъ[њЭ[ЩJШ[™Y]KXЭ
N‚€Y€Ш[™Y]K™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬћHЉHOH\™Щ]‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€’\ЬЭYHШ[™Y]H›Ь€Щ™YYXЪЧЪY\џHЩ\И›ЭX]Ъ›Э]H\™Щ]‹љЩY\\™Щ]]]Ьљ]HЫЫњЪ\Э[ќЉJB€Y€™YYXЪЧЪY›Э[€Ш[™Y]K™Щ]
њЫЭ\ЩWЩ™YYXЪЧЪYИ‹ЧJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€’\ЬЭYHШ[™Y]H›Ь€Щ™YYXЪЧЪY\џHЬЭ]ИЫЭ\ЩH™Y™\™[ЩH‹њ™]Z[€H™YYXЪИQ[€HШ[™Y]HЉJB€Y€Ш[™Y]K™Щ]
љ[X[—ЩШ]HЉH\И›ЭќYHЬ€Ш[™Y]K™Щ]
њЪYWЩY™™XЭЉHOH““У‘HЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€’\ЬЭYHШ[™Y]H›Ь€Щ™YYXЪЧЪY\џHћ\\ЬЩ\ИH[X[‹Ы›Л\ЪYKYY™™XЭ›Э[™\ћH‹Ь™X]H›И™[[ЭH\ЬЭYH]]ЫX]XШ[HЉJB€Y€Э]\ИOH”“ХUQ€[™Ш[™Y]K™Щ]
Ь™X][Ы—Ь\›Z]YЉH\И›ЭќYN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ›Э]YШ[™Y]H›Ь€Щ™YYXЪЧЪY\џH\И›ЭX\љЩY\›Z]Y‹љЩY\^XЪ]ЫЫњЩ[ќ[™›Э][™ИЭ]H[YЫ™YЉJB€Y€Э]\ИOH•’PQСH€[™Ш[™Y]K™Щ]
Ь™X][Ы—Ь\›Z]YЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€ќљXYЩHШ[™Y]H›Ь€Щ™YYXЪЧЪY\џH\ИX\љЩYЬ™X]X›H‹љЩY\[Щ\ќZ[€›Э][™И[€љXYЩHЉJB€Y€\Ъ[њЭ[ЩJ™YYXЪЧЪYЛ\Э
H[™Щ]
™YYXЪЧЪYКHOH›Э]WЪYО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[њ]Щ™YYXЪЧЪYИ[™›Э]\ИИ›ЭЫЭ™\€HШ[YH™YYXЪИ‹њ™]Z[€Ы™HXЩXX›H›Э]H›Ь€]™\ћH[њ]ЪYЫ[ЉJB‚€Э\™\ЬЪ[ЫњИH]K™Щ]
™\XШ]WЬЭ\™\ЬЪ[ЫњИЉB€ЩY[—ЬЭ\™\ЬЪ[ЫњО€Щ]Э\VЫШљ™XЭШљ™XЭWHHЩ]

B€Y€\Ъ[њЭ[ЩJЭ\™\ЬЪ[ЫњЛ\Э
N‚€›Ь€Э\™\ЬЪ[Ы€[€Э\™\ЬЪ[ЫњО‚€Y€›Э\Ъ[њЭ[ЩJЭ\™\ЬЪ[Ы‹XЭ
N‚€ЫЫќ[ќYB€Z\€H
Э\™\ЬЪ[Ы‹™Щ]
љ\ЬЭYWЪЩ^HЉKЭ\™\ЬЪ[Ы‹™Щ]
њЭ\™\ЬЩYЩ™YYXЪЧЪYЉJB€Y€Z\€[€ЩY[—ЬЭ\™\ЬЪ[ЫњО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™\XШ]HЭ\™\ЬЪ[Ы€ЬZ\€\џH\X\њИЪXЩH‹њ™XЫЬ™Ы™HЭ\™\ЬЪ[Ы€\€™YYXЪИ[™\ЬЭYHЩ^HЉJB€ЩY[—ЬЭ\™\ЬЪ[ЫњЛY
Z\ЉB€Y€Э\™\ЬЪ[Ы‹™Щ]
Ш[›ЫљXШ[Щ™YYXЪЧЪYЉH›Э[€›Э]WЪYИЬ€Э\™\ЬЪ[Ы‹™Щ]
њЭ\™\ЬЩYЩ™YYXЪЧЪYЉH›Э[€›Э]WЪYО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK™\XШ]HЭ\™\ЬЪ[Ы€™Y™\™[Щ\И[€[љЫ›ЭЫ€™YYXЪИQ‹њ™]Z[€HШ[›ЫљXШ[[™Э\™\ЬЩY›Э]H™XЫЬ™ИЉJB€™]\›€\њ›ЬњВ‚‚™Y€ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]N€Шљ™XЭЫЭ\ЩN€ЭЉHO€\ЭЬЭ—N‚€\њ›ЬњО€\ЭЬЭ—HHЧB€›ЬљY[—ЩљY[ИHВ€ЫЫќ™\њШ][Ы€‹€ќ[њШЬљ\‹€њ›Ы\‹€›Y\ЬШYЩH‹€њ]ЧЭ^‹€њ]ЧЬ]Y\ћH‹€њ]Y\ћH‹€њ]Y\Э[Ы€‹€ќ\Щ\—Э^‹€\ЬЪ\Э[ќЭ^‹€њЭ][Y[ќ‹€›ЩH‹€ЫЫќ[ќ‹€”’UђUWФђUИ‹€”‘TХ’PХQ‹€Ь™Y[ќX[‹€™\™XЭЪY[ќYљY\€‹€B€›ЬљY[—ЫЭЩ\€HЩљY[›ЭЩ\Љ
H›Ь€љY[[€›ЬљY[—ЩљY[ЯB‚€Y€ШШ[Љ[YN€Шљ™XЭ]€Э€H‰ЉHO€›Ы™N‚€Y€\Ъ[њЭ[ЩJ[YKXЭ
N‚€›Ь€Щ^KЪ[[€[YKљ][\К
N‚€Y€ЭЉЩ^JK›ЭЩ\Љ
H[€›ЬљY[—ЫЭЩ\Ћ‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€ћЬ]KћЪЩ^_H\ИH›ЬљY[€]ИЬ€Щ[њЪ]]™H™]љY][љY[‹€њЭЬ™HЭќXЭ\™YШ\Xљ[]HЫЩ\И[™Ь\]YH]љY[ЩHШШ]ЬњИЫ›H‹€
B€
B€ШШ[ЉЪ[€ћЬ]KћЪЩ^_HЉB€[Y€\Ъ[њЭ[ЩJ[YK\Э
N‚€›Ь€[™^Ъ[[€[ќ[Y\]J[YJN‚€ШШ[ЉЪ[€ћЬ]VЮЪ[™^WHЉB‚€ШШ[Љ]JB€™]\›€\њ›ЬњВ‚‚™Y€Ь™]љY][ЫX[љY™\ЭЪ[™^
X[љY™\Э€XЭ›Ы™HH›Ы™JHO€XЭЬЭ‹XЭN‚€ШYYHX[љY™\ЭY€X[љY™\Э\И›Э›Ы™H[ЩHШYЮX[[
PS’Q‘TХФU
B€™\ЬЪ]ЬљY\ИHШYY™Щ]
њ™\ЬЪ]ЬљY\ИЉHY€\Ъ[њЭ[ЩJШYYXЭ
H[ЩH›Ы™B€™]\›€В€™\ЬЪ]ЬћK™Щ]
љYЉN€™\ЬЪ]ЬћB€›Ь€™\ЬЪ]ЬћH[€™\ЬЪ]ЬљY\ИЬ€ЧB€Y€\Ъ[њЭ[ЩJ™\ЬЪ]ЬћKXЭ
H[™\Ъ[њЭ[ЩJ™\ЬЪ]ЬћK™Щ]
љYЉKЭЉB€B‚‚™Y€ЬШY™WЬ™]љY][ЫШШ]ЬЉ[YN€Шљ™XЭ
HO€›ЫЫ‚€™]\›€
€Ъ\ЧЬШY™WЬ™[]]™WЬ]
[YJB€[™\Ъ[њЭ[ЩJ[YKЭЉB€[™Ћ‹ЛИ€›Э[€[YB€[™[
Ъ\XЭ\€›Э[€[YH›Ь€Ъ\XЭ\€[€
€‹—€‹—€ЉJB€
B‚‚™Y€[Y]WЬ™]љY][Ь™\]Y\Э
€]N€XЭ€ЫЭ\ЩN€Э€Hњ™]љY][\™\]Y\Э‹€X[љY™\Э€XЭ›Ы™HH›Ы™KЉHO€\ЭЬЭ—N‚€€€•[Y]HHЭќXЭ\™Y™\]Y\ЭЪ]Э]™]Z[љ[™И]ИЫЫќ™\њШ][Ы[ЫЬ™[™Л€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉ‘U’QUђSФ‘TUQTХФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH™]љY][™\]Y\ЭљY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ€Ы›ЭЫ€HЩ]
Ь™]љY][ЫX[љY™\ЭЪ[™^
X[љY™\Э
JB€™Y™\њ™YH]K™Щ]
њ™Y™\њ™YЬ™\ЬЪ]ЬљY\ИЉB€Y€\Ъ[њЭ[ЩJ™Y™\њ™Y\Э
N‚€›Ь€™\ЬЪ]ЬћH[€™Y™\њ™Y‚€Y€™\ЬЪ]ЬћH›Э[€Ы›ЭЫЋ‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€њ™Y™\њ™Y™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћH\џH\И›ЭXЫ\™Y‹€ќ\ЩHH™\ЬЪ]ЬћHQњ›ЫHЫЫ™љYЛЬ™\ЬЪ]ЬљY\ЛћX[[‹€
B€
B€љ]XЮHH]K™Щ]
њљ]XЮHЉB€Y€\Ъ[њЭ[ЩJљ]XЮKXЭ
N‚€Y€љ]XЮK™Щ]
њ]ЧЬ]Y\ћWЬЭЬ™YЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€њљ]XЮKњ]ЧЬ]Y\ћWЬЭЬ™Y]\Э™H[ЩH‹€™\љ]™HШ\Xљ[]HЫЩ\И[њЪY[ќH[™И›Э\њЪ\Э]И]Y\ћH^‹€
B€
B€Y€љ]XЮK™Щ]
™\™XЭЪY[ќYљY\њЧЬЭЬ™YЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€њљ]XЮK™\™XЭЪY[ќYљY\њЧЬЭЬ™Y]\Э™H[ЩH‹€њ™[[Э™H\™XЭY[ќYљY\њИњ›ЫHH™]љY][[ќ™[ЬH‹€
B€
B€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЬ™]љY][Ъ[™^
]N€XЭX[љY™\Э€XЭ›Ы™HH›Ы™KЫЭ\ЩN€Э€Hњ™]љY][Z[™^ЉHO€\ЭЬЭ—N‚€€€•[Y]HY\\‹\›ЭљYY]љY[ЩHY]Y]HYШZ[њЭ[[]]X›HX[љY™\Э[њЛ€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉ‘U’QUђSТS‘VФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH™]љY][[™^љY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ€™\ЬЪ]ЬљY\ИHЬ™]љY][ЫX[љY™\ЭЪ[™^
X[љY™\Э
B€ЩY[—Щ]љY[ЩN€Щ]ЬЭ—HHЩ]

B€[ќљY\ИH]K™Щ]
™[ќљY\ИЉB€Y€›Э\Ъ[њЭ[ЩJ[ќљY\Л\Э
N‚€™]\›€\њ›ЬњВ€›Ь€[™^[ќћH[€[ќ[Y\]J[ќљY\КN‚€Y€›Э\Ъ[њЭ[ЩJ[ќћKXЭ
N‚€ЫЫќ[ќYB€™Yљ^H€ћЬЫЭ\Щ_N€[ќљY\ЦЮЪ[™^WH‚€]љY[ЩWЪYH[ќћK™Щ]
™]љY[ЩWЪYЉB€Y€]љY[ЩWЪY[€ЩY[—Щ]љY[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™[ќљY\ЦЮЪ[™^WH\XШ]\И]љY[ЩWЪYЩ]љY[ЩWЪY\џH‹њ™]Z[€Ы™H[[]]X›H]љY[ЩH[ќћH\€QЉJB€Y€\Ъ[њЭ[ЩJ]љY[ЩWЪYЭЉN‚€ЩY[—Щ]љY[ЩKY
]љY[ЩWЪY
B€™\ЬЪ]ЬћWЪYH[ќћK™Щ]
њ™\ЬЪ]ЬћHЉB€™\ЬЪ]ЬћHH™\ЬЪ]ЬљY\Л™Щ]
™\ЬЪ]ЬћWЪY
B€Y€™\ЬЪ]ЬћH\И›Ы™N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™[ќљY\ЦЮЪ[™^WH[Y\И[љЫ›ЭЫ€™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћWЪY\џH‹ќ\ЩHH™\ЬЪ]ЬћHXЫ\™Y[€HX[љY™\ЭЉJB€ЫЫќ[ќYB€ШњЩ\ќ™YШЫЫ[Z]H™\ЬЪ]ЬћK™Щ]
›ШњЩ\ќ™YШЫЫ[Z]ЉB€Y€[ќћK™Щ]
њЫЭ\ЩWШЫЫ[Z]ЉHOHШњЩ\ќ™YШЫЫ[Z]‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€™[ќљY\ЦЮЪ[™^WHЫЭ\ЩWШЫЫ[Z]\И›ЭHX[љY™\ЭШњЩ\ќ™YЫЫ[Z]‹€њ™Yњ™\ЪHY\\€[™^њ›ЫHH[[]]X›H™\ЬЪ]ЬћHЫ\ЪЭ‹€
B€
B€Y€›ЭЬШY™WЬ™]љY][ЫШШ]ЬЉ[ќћK™Щ]
›ШШ]Ь€ЉJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™[ќљY\ЦЮЪ[™^WK›ШШ]Ь€\И[њШY™H‹ќ\ЩHH™\ЬЪ]ЬћK[ШШ[Ь€Ь\]YH™[]]™HШШ]Ь€ЉJB€›Щљ[HH™\ЬЪ]ЬћK™Щ]
љЫ›ЭЫYЩWЬ›Щљ[H‹ЯJB€]љY[ЩWЬќ[\ИH›Щљ[K™Щ]
™]љY[ЩWЬќ[\И‹ЯJHY€\Ъ[њЭ[ЩJ›Щљ[KXЭ
H[ЩHЯB€[ЭЩYЪЪ[™ИH]љY[ЩWЬќ[\Л™Щ]
[ЭЩYЪЪ[™И‹ЧJHY€\Ъ[њЭ[ЩJ]љY[ЩWЬќ[\ЛXЭ
H[ЩHЧB€Y€[ќћK™Щ]
™]љY[ЩWЪЪ[™ЉH›Э[€[ЭЩYЪЪ[™О‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€™[ќљY\ЦЮЪ[™^WK™]љY[ЩWЪЪ[™\ИЭ]ЪYHH™\ЬЪ]ЬћH›Щљ[H‹€њ™]Z[€HЪ[™\ЬЪ]ЬћH]љY[ЩHЫXЮH]H\™[ќ›Э[™\ћH‹€
B€
B€њ™\Ъ™\ЬЧЬќ[\ИH›Щљ[K™Щ]
™њ™\Ъ™\ЬЧЬќ[\И‹ЯJHY€\Ъ[њЭ[ЩJ›Щљ[KXЭ
H[ЩHЯB€[ЭЩYЬЭ]\Щ\ИHњ™\Ъ™\ЬЧЬќ[\Л™Щ]
[ЭЩYЬЭ]\Щ\И‹ЧJHY€\Ъ[њЭ[ЩJњ™\Ъ™\ЬЧЬќ[\ЛXЭ
H[ЩHЧB€Y€[ќћK™Щ]
™њ™\Ъ™\ЬЧЬЭ]\ИЉH›Э[€[ЭЩYЬЭ]\Щ\О‚€\њ›ЬњЛ\[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉ€ЫЭ\ЩK€€™[ќљY\ЦЮЪ[™^WK™њ™\Ъ™\ЬЧЬЭ]\И\ИЭ]ЪYHH™\ЬЪ]ЬћH›Щљ[H‹€њ™\Щ\ќ™HЭ[HЬ€[љЫ›ЭЫ€Э]H[™›ЫЭИHЪ[њ™\Ъ™\ЬИЫXЮH‹€
B€
B€Ш\Xљ[]WШЫЩ\ИH[ќћK™Щ]
Ш\Xљ[]WШЫЩ\ИЉB€Y€\Ъ[њЭ[ЩJШ\Xљ[]WШЫЩ\Л\Э
H[™[ЉШ\Xљ[]WШЫЩ\КHOH[ЉЩ]
Ш\Xљ[]WШЫЩ\КJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™[ќљY\ЦЮЪ[™^WKШ\Xљ[]WШЫЩ\И\™H\XШ]Y‹™XЫ\™HXXЪ™]љY][Ш\Xљ[]HЫЩHЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЬ™]љY][Ь™\Э[
€]N€XЭ€X[љY™\Э€XЭ›Ы™HH›Ы™K€™\]Y\Э€XЭ›Ы™HH›Ы™K€ЫЭ\ЩN€Э€Hњ™]љY][\™\Э[‹ЉHO€\ЭЬЭ—N‚€€€•[Y]HЩ[XЭY™\ЬЪ]ЬљY\И[™]љY[ЩH›Э™[[ЩH[€H™]љY][™\Э[€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉ‘U’QUђSФ‘TХSФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH™]љY][™\Э[љY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ€™\ЬЪ]ЬљY\ИHЬ™]љY][ЫX[љY™\ЭЪ[™^
X[љY™\Э
B€Ы›ЭЫ€HЩ]
™\ЬЪ]ЬљY\КB€™\]Y\ЭYHЩ]
]K™Щ]
Ш\Xљ[]WШЫЩ\И‹ЧJJHY€\Ъ[њЭ[ЩJ]K™Щ]
Ш\Xљ[]WШЫЩ\ИЉK\Э
H[ЩHЩ]

B€Щ[XЭYH]K™Щ]
њЩ[XЭYЬ™\ЬЪ]ЬљY\ИЉB€Щ[XЭYШћWЪY€XЭЬЭ‹XЭHHЯB€Y€\Ъ[њЭ[ЩJЩ[XЭY\Э
N‚€›Ь€[™^™XЫЬ™[€[ќ[Y\]JЩ[XЭY
N‚€Y€›Э\Ъ[њЭ[ЩJ™XЫЬ™XЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћWЪYH™XЫЬ™™Щ]
њ™\ЬЪ]ЬћHЉB€Y€™\ЬЪ]ЬћWЪY[€Щ[XЭYШћWЪY‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њЩ[XЭYЬ™\ЬЪ]ЬљY\ЦЮЪ[™^WH\XШ]\ИЬ™\ЬЪ]ЬћWЪY\џH‹њЩ[XЭXXЪ™\ЬЪ]ЬћHЫЩHЉJB€Y€\Ъ[њЭ[ЩJ™\ЬЪ]ЬћWЪYЭЉN‚€Щ[XЭYШћWЪYЬ™\ЬЪ]ЬћWЪYHH™XЫЬ™€™\ЬЪ]ЬћHH™\ЬЪ]ЬљY\Л™Щ]
™\ЬЪ]ЬћWЪY
B€Y€™\ЬЪ]ЬћH\И›Ы™N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њЩ[XЭY™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћWЪY\џH\И[љЫ›ЭЫ€‹ќ\ЩHH™\ЬЪ]ЬћHXЫ\™Y[€HX[љY™\ЭЉJB€ЫЫќ[ќYB€Y€™XЫЬ™™Щ]
њЫЭ\ЩWШЫЫ[Z]ЉHOH™\ЬЪ]ЬћK™Щ]
›ШњЩ\ќ™YШЫЫ[Z]ЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њЩ[XЭY™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћWЪY\џH\И›ЭYYИ]ИШњЩ\ќ™YЫЫ[Z]‹њ™]\›€H[[]]X›HЫЭ\ЩHЫЫ[Z]\ЩY›Ь€™]љY][ЉJB€X]ЪYH™XЫЬ™™Щ]
›X]ЪYШШ\Xљ[]WШЫЩ\ИЉB€Y€\Ъ[њЭ[ЩJX]ЪY\Э
H[™›ЭЩ]
X]ЪY
Kљ\ЬЭXњЩ]
™\]Y\ЭY
N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њЩ[XЭY™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћWЪY\џH™\ЬќИ[€[њ™\]Y\ЭYШ\Xљ[]H‹љЩY\Щ[XЭ[Ы€]љY[ЩHYYИHЭќXЭ\™Y™\]Y\ЭЉJB€]љY[ЩHH]K™Щ]
™]љY[ЩHЉB€ЩY[—Щ]љY[ЩN€Щ]ЬЭ—HHЩ]

B€Y€\Ъ[њЭ[ЩJ]љY[ЩK\Э
N‚€›Ь€[™^™XЫЬ™[€[ќ[Y\]J]љY[ЩJN‚€Y€›Э\Ъ[њЭ[ЩJ™XЫЬ™XЭ
N‚€ЫЫќ[ќYB€]љY[ЩWЪYH™XЫЬ™™Щ]
™]љY[ЩWЪYЉB€Y€]љY[ЩWЪY[€ЩY[—Щ]љY[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™]љY[ЩVЮЪ[™^WH\XШ]\И]љY[ЩWЪYЩ]љY[ЩWЪY\џH‹њ™]\›€XXЪ]љY[ЩH™Y™\™[ЩHЫЩHЉJB€Y€\Ъ[њЭ[ЩJ]љY[ЩWЪYЭЉN‚€ЩY[—Щ]љY[ЩKY
]љY[ЩWЪY
B€™\ЬЪ]ЬћWЪYH™XЫЬ™™Щ]
њ™\ЬЪ]ЬћHЉB€Y€™\ЬЪ]ЬћWЪY›Э[€Щ[XЭYШћWЪY‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™]љY[ЩVЮЪ[™^WH\ИЭ]ЪYHЩ[XЭY™\ЬЪ]ЬљY\И‹њ™]\›€]љY[ЩHЫ›Hњ›ЫHHZ[љ[][HЩ[XЭYЩ]ЉJB€ЫЫќ[ќYB€™\ЬЪ]ЬћHH™\ЬЪ]ЬљY\Л™Щ]
™\ЬЪ]ЬћWЪY
B€Y€™\ЬЪ]ЬћH\И›Э›Ы™H[™™XЫЬ™™Щ]
њЫЭ\ЩWШЫЫ[Z]ЉHOH™\ЬЪ]ЬћK™Щ]
›ШњЩ\ќ™YШЫЫ[Z]ЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™]љY[ЩVЮЪ[™^WHЫЭ\ЩWШЫЫ[Z]Щ\И›ЭX]Ъ]И™\ЬЪ]ЬћH[€‹њ™\Щ\ќ™H[[]]X›H]љY[ЩH›Э™[[ЩHЉJB€Y€›ЭЬШY™WЬ™]љY][ЫШШ]ЬЉ™XЫЬ™™Щ]
›ШШ]Ь€ЉJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™]љY[ЩVЮЪ[™^WK›ШШ]Ь€\И[њШY™H‹њ™]\›€H™\ЬЪ]ЬћK[ШШ[Ь€Ь\]YH™[]]™HШШ]Ь€ЉJB€›Щљ[HH™\ЬЪ]ЬћK™Щ]
љЫ›ЭЫYЩWЬ›Щљ[H‹ЯJHY€™\ЬЪ]ЬћH[ЩHЯB€]љY[ЩWЬќ[\ИH›Щљ[K™Щ]
™]љY[ЩWЬќ[\И‹ЯJHY€\Ъ[њЭ[ЩJ›Щљ[KXЭ
H[ЩHЯB€Y€™XЫЬ™™Щ]
™]љY[ЩWЪЪ[™ЉH›Э[€]љY[ЩWЬќ[\Л™Щ]
[ЭЩYЪЪ[™И‹ЧJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™]љY[ЩVЮЪ[™^WHљ[Ы]\И]И™\ЬЪ]ЬћH]љY[ЩHЫXЮH‹њ™]Z[€HЪ[™\ЬЪ]ЬћH]љY[ЩHќ[HЉJB€њ™\Ъ™\ЬЧЬќ[\ИH›Щљ[K™Щ]
™њ™\Ъ™\ЬЧЬќ[\И‹ЯJHY€\Ъ[њЭ[ЩJ›Щљ[KXЭ
H[ЩHЯB€Y€™XЫЬ™™Щ]
™њ™\Ъ™\ЬЧЬЭ]\ИЉH›Э[€њ™\Ъ™\ЬЧЬќ[\Л™Щ]
[ЭЩYЬЭ]\Щ\И‹ЧJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™]љY[ЩVЮЪ[™^WHљ[Ы]\И]И™\ЬЪ]ЬћHњ™\Ъ™\ЬИЫXЮH‹њ™\Щ\ќ™HHЫЭ\ЩHњ™\Ъ™\ЬИЭ]HЉJB€X]ЪYH™XЫЬ™™Щ]
›X]ЪYШШ\Xљ[]WШЫЩ\ИЉB€Y€\Ъ[њЭ[ЩJX]ЪY\Э
H[™›ЭЩ]
X]ЪY
Kљ\ЬЭXњЩ]
™\]Y\ЭY
N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™]љY[ЩVЮЪ[™^WH™\ЬќИ[€[њ™\]Y\ЭYШ\Xљ[]H‹љЩY\]љY[ЩHYYИHЭќXЭ\™Y™\]Y\ЭЉJB€Y€]K™Щ]
њЭ]\ИЉHOH““ЧУPUТ€[™
Щ[XЭYШћWЪYЬ€ЩY[—Щ]љY[ЩJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK““ЧУPUТ™\Э[ЫЫќZ[њИЩ[XЭY™\ЬЪ]ЬљY\ИЬ€]љY[ЩH‹ќ\ЩHУУTUWХТUСРTИЪ[€\ќX[]љY[ЩH^\ЭИЉJB€Y€™\]Y\Э\И›Э›Ы™N‚€Y€]K™Щ]
њ™\]Y\ЭЬ™Y€ЉHOH™\]Y\Э™Щ]
њ™\]Y\ЭЪYЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњ™\]Y\ЭЬ™Y€Щ\И›ЭX]ЪH™]љY][™\]Y\Э‹њ™]Z[€H™\]Y\ЭQ›Ь€XЩXXљ[]HЉJB€Y€]K™Щ]
љ[ќ[ќШЫЩHЉHOH™\]Y\Э™Щ]
љ[ќ[ќШЫЩHЉHЬ€]K™Щ]
Ш\Xљ[]WШЫЩ\ИЉHOH™\]Y\Э™Щ]
Ш\Xљ[]WШЫЩ\ИЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњ™\Э[™\]Y\ЭљY[ИИ›ЭX]ЪH™]љY][™\]Y\Э‹њ™\Щ\ќ™HЭќXЭ\™Y™\]Y\Э[ќ[ќ[™Ш\Xљ[]HЫЩ\ИЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЪ[\›Э™[Y[ќЫЫЬ
€]N€XЭ€X[љY™\Э€XЭ›Ы™HH›Ы™K€ЫЭ\ЩN€Э€Hљ[\›Э™[Y[ќ[ЫЬ‹ЉHO€\ЭЬЭ—N‚€€€•[Y]H™\Э[XX›H[\›Э™[Y[ќЭ]ЫЫY\ИЪ]Э]\›Z][™И™[[ЭHЪYHY™™XЭЛ€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉST“Х‘SQS•УУФФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH[\›Э™[Y[ќЫЬљY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ‚€™\ЬЪ]ЬљY\ИHЬ™]љY][ЫX[љY™\ЭЪ[™^
X[љY™\Э
B€Ы›ЭЫ€HЩ]
™\ЬЪ]ЬљY\КHИYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€џB€Y€]K™Щ]
›[™HЉHOHђUUУ“УSХTЧТST“Х‘SQS•Ћ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK›[™H]\Э™HUUУ“УSХTЧТST“Х‘SQS•‹љЩY\[\›Э™[Y[ќЫЬљИЫ€]И[™\[™[ќXЪЬЭYЩH[™HЉJB€Y€]K™Щ]
љ[ќ\XЭ[Ы—Ш›ШЪЪ[™ИЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы—Ш›ШЪЪ[™И]\Э™H[ЩH‹›™]™\€[^HHњ›ЫќЭYЩH™\ЬЫњЩH›Ь€[\›Э™[Y[ќЫЬљИЉJB€Y€]K™Щ]
ќ\Щ\—Ш\ќYXЭЬЫXЮHЉHOH”‘PQУУ“H€Ь€]K™Щ]
њ™[[ЭWЫЬ\][ЫњИЉHOHЧN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[\›Э™[Y[ќ]\Э›Э]]]H\Щ\€\ќYXЭИЬ€\™›Ь›H™[[ЭHЬ\][ЫњИ‹њ™]\›€H[X[‹YШ]YY]Y]K[Ы›HYќ[€ЉJB‚€[њ]Ъ\ЬЭYWЪЩ^\ИH]K™Щ]
љ[њ]Ъ\ЬЭYWЪЩ^\ИЉB€[њ]ЪЩ^\ИHЩ]
[њ]Ъ\ЬЭYWЪЩ^\КHY€\Ъ[њЭ[ЩJ[њ]Ъ\ЬЭYWЪЩ^\Л\Э
H[ЩHЩ]

B€Э]ЫЫY\ИH]K™Щ]
›Э]ЫЫY\ИЉB€Э]ЫЫYWШћWЪЩ^N€XЭЬЭ‹XЭHHЯB€[—ЪYО€Щ]ЬЭ—HHЩ]

B€^XЭYЬ[—ЪYО€Щ]ЬЭ—HHЩ]

B€›Ь€[™^Э]ЫЫYH[€[ќ[Y\]JЭ]ЫЫY\ИY€\Ъ[њЭ[ЩJЭ]ЫЫY\Л\Э
H[ЩHЧJN‚€Y€›Э\Ъ[њЭ[ЩJЭ]ЫЫYKXЭ
N‚€ЫЫќ[ќYB€\ЬЭYWЪЩ^HHЭ]ЫЫYK™Щ]
љ\ЬЭYWЪЩ^HЉB€Y€\ЬЭYWЪЩ^H[€Э]ЫЫYWШћWЪЩ^N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫY\ЦЮЪ[™^WH\XШ]\И\ЬЭYWЪЩ^HЪ\ЬЭYWЪЩ^H\џH‹њЩ[XЭXXЪШ[›ЫљXШ[\ЬЭYHЫЩHЉJB€Y€\Ъ[њЭ[ЩJ\ЬЭYWЪЩ^KЭЉN‚€Э]ЫЫYWШћWЪЩ^VЪ\ЬЭYWЪЩ^WHHЭ]ЫЫYB€Y€\Ъ[њЭ[ЩJ\ЬЭYWЪЩ^KЭЉH[™\ЬЭYWЪЩ^H›Э[€[њ]ЪЩ^\О‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\И›Э[€[њ]Ъ\ЬЭYWЪЩ^\И‹њ™]Z[€H\ЬЭYH›Э][™ИXЩHЉJB€\™Щ]HЭ]ЫЫYK™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬћHЉB€™\ЬЪ]ЬћHH™\ЬЪ]ЬљY\Л™Щ]
\™Щ]
HY€\Ъ[њЭ[ЩJ\™Щ]ЭЉH[ЩH›Ы™B€Y€\™Щ]\И›Э›Ы™H[™\™Щ]›Э[€Ы›ЭЫЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\™Щ]И[љЫ›ЭЫ€™\ЬЪ]ЬћHЭ\™Щ]\џH‹њ›Э]HЫ›HИHX[љY™\Э™\ЬЪ]ЬћHЬ€H\™[ќЉJB€™\ЬЪ]ЬћHH›Ы™B€\ЩWШЫЫ[Z]HЭ]ЫЫYK™Щ]
\ЩWШЫЫ[Z]ЉB€Y€™\ЬЪ]ЬћH\И›Э›Ы™H[™\ЩWШЫЫ[Z]OH™\ЬЪ]ЬћK™Щ]
›ШњЩ\ќ™YШЫЫ[Z]ЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\И›ЭYYИH\™Щ]ШњЩ\ќ™YЫЫ[Z]‹њ™X\ЩHH[\›Э™[Y[ќ[€Ы€H[[]]X›HЫЭ\ЩHЫЫ[Z]ЉJB€Y€\™Щ]\И›Ы™H[™\ЩWШЫЫ[Z]\И›Э›Ы™N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\ИHЫЫ[Z]Ъ]Э]H\™Щ]™\ЬЪ]ЬћH‹љЩY\[њ™\ЫЫ™YљXYЩHY]Y]H[›Э[™ЉJB‚€Ъ[™ЩYЬ]ИHЭ]ЫЫYK™Щ]
Ъ[™ЩYЬ]ИЉB€Y€\Ъ[њЭ[ЩJЪ[™ЩYЬ]Л\Э
H[™™\ЬЪ]ЬћH\И›Э›Ы™N‚€›Щљ[HH™\ЬЪ]ЬћK™Щ]
љЫ›ЭЫYЩWЬ›Щљ[H‹ЯJHY€\Ъ[њЭ[ЩJ™\ЬЪ]ЬћKXЭ
H[ЩHЯB€Ьљ]WЬШЫЬHH›Щљ[K™Щ]
ќЬљ]WЬШЫЬH‹ЯJHY€\Ъ[њЭ[ЩJ›Щљ[KXЭ
H[ЩHЯB€[ЭЩYЬШЫЬHHЬљ]WЬШЫЬK™Щ]
[ЭЩYЬ]И‹ЧJHY€\Ъ[њЭ[ЩJЬљ]WЬШЫЬKXЭ
H[ЩHЧB€Y€\™Щ]OHYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€Ћ‚€[ЭЩYЬШЫЬHHИ™ШЬИ‹™^XЭ][Ы€‹њШЪ[X\И‹ќЫЫИ‹ќ\ЭИ‹ЫЫ™љYИ—B€›Ь€][€Ъ[™ЩYЬ]О‚€Y€›ЭЪ\ЧЬШY™WЬ™[]]™WЬ]
]
N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\И[€[њШY™HЪ[™ЩY]‹›[Z][\[Y[ќ][Ы€ШЫЬHИШY™H™[]]™H]ИЉJB€[Y€›Э[ћJ]OH›ЫЭЬ€]њЭ\ќЭЪ]
€ћЬ›ЫЭKИЉH›Ь€›ЫЭ[€[ЭЩYЬШЫЬJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џHЪ[™Щ\ИH]Э]ЪYHЬљ]WЬШЫЬH‹њ™\ЬXЭH\™Щ]Ы›ЭЫYЩH›Щљ[HЬљ]HШЫЬHЉJB‚€ЫЬљЧЪ][HHЭ]ЫЫYK™Щ]
ќЫЬљЧЪ][HЉB€Y€\Ъ[њЭ[ЩJЫЬљЧЪ][KXЭ
N‚€Y€ЫЬљЧЪ][K™Щ]
›ЭЫ™\—Ь™\ЬЪ]ЬћHЉHOH\™Щ]‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€ќЫЬљИ][H›Ь€Ъ\ЬЭYWЪЩ^H\џH\ИHY™™\™[ќЭЫ™\€‹љЩY\ШЪY[\€[™\ЬЭYH]]Ьљ]H[YЫ™YЉJB€Y€ЫЬљЧЪ][K™Щ]
њЫЭ\ЩWШЫЫ[Z]ЉHOH\ЩWШЫЫ[Z]‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€ќЫЬљИ][H›Ь€Ъ\ЬЭYWЪЩ^H\џH\И›ЭYYИHЭ]ЫЫYHЫЫ[Z]‹њ™]Z[€Ы™H[[]]X›H\ЩHЫЫ[Z]XЬ›ЬЬИќ[ќ[YHЪXЪЬЪ[ќИЉJB€Y€ЫЬљЧЪ][K™Щ]
њШЪY[\—ЬЭ]\ИЉHOH”СSPХQЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€ќЫЬљИ][H›Ь€Ъ\ЬЭYWЪЩ^H\џHШ\И›ЭШЪY[\‹\Щ[XЭY‹™И›Э›ЩЬ™\ЬИ[€^ЫYYЫЬљИ][HЉJB‚€YќHЭ]ЫЫYK™Щ]
™YќЬ—Ь[€ЉB€[]™\ћHHЭ]ЫЫYK™Щ]
™[]™\ћWЬЭ]\ИЉB€Y€[]™\ћHOH‘ђQ•Ф—Ф‘PQHЋ‚€Y€Э]ЫЫYK™Щ]
љ[\[Y[ќ][Ы—ЬЭ]\ИЉHOH”TФСQ€Ь€Э]ЫЫYK™Щ]
ќ\ЭЬЭ]\ИЉHOH”TФСQ€Ь€Э]ЫЫYK™Щ]
њ]X[]WЩШ]WЬЭ]\ИЉHOH”TФСQЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™Yќ[€›Ь€Ъ\ЬЭYWЪЩ^H\џHXЪЬИ[\[Y[ќ][Ы‹Э\ЭЩШ]H]љY[ЩH‹љЩY\Z[YЬ€Z\ЬЪ[™И]љY[ЩHЭ]Щ€Yќ€[›љ[™ИЉJB€Y€›Э\Ъ[њЭ[ЩJYќXЭ
N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™Yќ[€›Ь€Ъ\ЬЭYWЪЩ^H\џH\ИZ\ЬЪ[™И‹™[Z]H[X[‹YШ]Y[€Ы›HYќ\€[ЪXЪЬИ\ЬИЉJB€[Y€Yќ\И›Э›Ы™N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€››Ы‹\™XYHЭ]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\ИHYќ€[€‹љЩY\љXYЩH[™›ШЪЩYЫЬљИЪ]Э]HYќ[€ЉJB€Y€\Ъ[њЭ[ЩJYќXЭ
N‚€[—ЪYHYќ™Щ]
њ[—ЪYЉB€Y€[—ЪY[€[—ЪYО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™Yќ[€Ь[—ЪY\џH\И\XШ]Y‹™[Z]Ы™H[€\€Ш[›ЫљXШ[\ЬЭYHЉJB€Y€\Ъ[њЭ[ЩJ[—ЪYЭЉN‚€[—ЪYЛY
[—ЪY
B€^XЭYЬ[—ЪYЛY
[—ЪY
B€Y€Yќ™Щ]
љ\ЬЭYWЪЩ^HЉHOH\ЬЭYWЪЩ^HЬ€Yќ™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬћHЉHOH\™Щ]‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™Yќ[€›Ь€Ъ\ЬЭYWЪЩ^H\џHЬЭ]И\ЬЭYH]]Ьљ]H‹љЩY\[€[™Э]ЫЫYH\™Щ]ИY[ќXШ[ЉJB€Y€Yќ™Щ]
\ЩWШЫЫ[Z]ЉHOH\ЩWШЫЫ[Z]Ь€Yќ™Щ]
Ъ[™ЩYЬ]ИЉHOHЪ[™ЩYЬ]О‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™Yќ[€›Ь€Ъ\ЬЭYWЪЩ^H\џHЬЭ]ИЫЭ\ЩHЬ€]ШЫЬH‹њ™\Щ\ќ™HHЪXЪЬЪ[ќY[\[Y[ќ][Ы€ШЫЬHЉJB€Y€Yќ™Щ]
њ]X[]WЩШ]WЬЭ]\ИЉHOH”TФСQ€Ь€Yќ™Щ]
љ[X[—ЩШ]HЉH\И›ЭќYHЬ€Yќ™Щ]
›Y\™ЩWЬ\›Z]YЉH\И›Э[ЩHЬ€Yќ™Щ]
њ™[X\ЩWЬ\›Z]YЉH\И›Э[ЩHЬ€Yќ™Щ]
њЪYWЩY™™XЭЉHOH““У‘HЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€™Yќ[€›Ь€Ъ\ЬЭYWЪЩ^H\џHћ\\ЬЩ\ИH[X[€Ь€ЪYKYY™™XЭШ]H‹™И›ЭY\™ЩK™[X\ЩKЬ€Ь™X]HH™[[ЭH€]]ЫX]XШ[HЉJB‚€ЪXЪЬЪ[ќИHЭ]ЫЫYK™Щ]
ЪXЪЬЪ[ќИЉB€Y€\Ъ[њЭ[ЩJЪXЪЬЪ[ќЛ\Э
N‚€ЪXЪЬЪ[ќЪЩ^\О€Щ]ЬЭ—HHЩ]

B€ЪXЪЬЪ[ќЬЭ\О€Щ]ЬЭ—HHЩ]

B€›Ь€ЪXЪЬЪ[ќ[€ЪXЪЬЪ[ќО‚€Y€›Э\Ъ[њЭ[ЩJЪXЪЬЪ[ќXЭ
N‚€ЫЫќ[ќYB€Щ^HHЪXЪЬЪ[ќ™Щ]
љY[\Э[ЮWЪЩ^HЉB€Э\HЪXЪЬЪ[ќ™Щ]
њЭ\ЉB€Y€Щ^H[€ЪXЪЬЪ[ќЪЩ^\О‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\XШ]\ИЪXЪЬЪ[ќY[\Э[ЮHЩ^H‹њ™\Э[YHHШ[YHЪXЪЬЪ[ќ[њЭXYЩ€\XШ][™ИЪYHY™™XЭИЉJB€Y€Э\[€ЪXЪЬЪ[ќЬЭ\О‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€›Э]ЫЫYHЪ\ЬЭYWЪЩ^H\џH\XШ]\ИЪXЪЬЪ[ќЭ\ЬЭ\\џH‹њ™XЫЬ™Ы™H\›Z[[ШњЩ\ќ][Ы€\€[\›Э™[Y[ќЭ\ЉJB€Y€\Ъ[њЭ[ЩJЩ^KЭЉN‚€ЪXЪЬЪ[ќЪЩ^\ЛY
Щ^JB€Y€\Ъ[њЭ[ЩJЭ\ЭЉN‚€ЪXЪЬЪ[ќЬЭ\ЛY
Э\
B€Y€[њ]ЪЩ^\И[™›Э[њ]ЪЩ^\Лљ\ЬЭ\\њЩ]
Э]ЫЫYWШћWЪЩ^JN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK›Э]ЫЫY\ИИ›Э]™HHX]Ъ[™И[њ]\ЬЭYHЩ^H‹њ™]Z[€Ы™HЭ]ЫЫYH›Ь€XXЪШ[›ЫљXШ[[њ]Ш[™Y]HЉJB‚€[њИH]K™Щ]
™YќЬ—Ь[њИЉB€XЭX[Ь[—ЪYИHЬ[‹™Щ]
њ[—ЪYЉH›Ь€[€[€[њИY€\Ъ[њЭ[ЩJ[‹XЭ
_HY€\Ъ[њЭ[ЩJ[њЛ\Э
H[ЩHЩ]

B€Y€XЭX[Ь[—ЪYИOH^XЭYЬ[—ЪYО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKќЬ[]™[YќЬ—Ь[њИИ›ЭX]ЪЭ]ЫЫYH[њИ‹љЩY\H[€[™^]\›Z[љ\ЭXИ[™XЩXX›HЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЪ[ќ\XЭ[Ы—ЩL™J€]N€XЭ€X[љY™\Э€XЭ›Ы™HH›Ы™K€ЫЭ\ЩN€Э€Hљ[ќ\XЭ[Ы‹YL™H‹ЉHO€\ЭЬЭ—N‚€€€•[Y]HH™]ЫЬљЫ\ЬИњ›ЫќЭYЩKШXЪЬЭYЩH[ќYЬ][Ы€›ЫЩ‹€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉS•TђPХSУ—СL‘WФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH[ќ\XЭ[Ы€L‘HљY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ€™\ЬЪ]ЬљY\ИHЬ™]љY][ЫX[љY™\ЭЪ[™^
X[љY™\Э
B€Ы›ЭЫ€HЩ]
™\ЬЪ]ЬљY\КB€Ы\ЪЭО€XЭЬЭ‹Э—HHЯB€™]љY][H]K™Щ]
њ™]љY][‹ЯJB€Y€\Ъ[њЭ[ЩJ™]љY][XЭ
N‚€›Ь€[™^Ы\ЪЭ[€[ќ[Y\]J™]љY][™Щ]
њЫЭ\ЩWЬЫ\ЪЭИ‹ЧJJN‚€Y€›Э\Ъ[њЭ[ЩJЫ\ЪЭXЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћHHЫ\ЪЭ™Щ]
њ™\ЬЪ]ЬћHЉB€ЫЫ[Z]HЫ\ЪЭ™Щ]
ЫЫ[Z]ЉB€Y€™\ЬЪ]ЬћH[€Ы\ЪЭО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ™]љY][ЫЭ\ЩHЫ\ЪЭ\XШ]\ИЬ™\ЬЪ]ЬћH\џH‹њ™XЫЬ™Ы™H[[]]X›HЫ\ЪЭ\€™\ЬЪ]ЬћHЉJB€Y€™\ЬЪ]ЬћH›Э[€Ы›ЭЫЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ™]љY][ЫЭ\ЩHЫ\ЪЭ[Y\И[љЫ›ЭЫ€™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћH\џH‹ќ\ЩHX[љY™\Э™\ЬЪ]ЬћHQИЉJB€Y€\Ъ[њЭ[ЩJ™\ЬЪ]ЬћKЭЉN‚€Ы\ЪЭЦЬ™\ЬЪ]ЬћWHHЫЫ[Z]€Y€™\ЬЪ]ЬћH[€™\ЬЪ]ЬљY\И[™ЫЫ[Z]OH™\ЬЪ]ЬљY\ЦЬ™\ЬЪ]ЬћWK™Щ]
›ШњЩ\ќ™YШЫЫ[Z]ЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ™]љY][ЫЭ\ЩHЫ\ЪЭЬ™\ЬЪ]ЬћH\џH\И›Э[›™YИHX[љY™\ЭЫЫ[Z]‹њ™\Щ\ќ™HH[[]]X›H[њ]Ы\ЪЭЉJB€\ќYXЭH]K™Щ]
\ќYXЭ‹ЯJB€\ќYXЭЬЫ\ЪЭИH\ќYXЭ™Щ]
њЫЭ\ЩWЬЫ\ЪЭИ‹ЧJHY€\Ъ[њЭ[ЩJ\ќYXЭXЭ
H[ЩHЧB€›Ь€Ы\ЪЭ[€\ќYXЭЬЫ\ЪЭО‚€Y€›Э\Ъ[њЭ[ЩJЫ\ЪЭXЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћHHЫ\ЪЭ™Щ]
њ™\ЬЪ]ЬћHЉB€ЫЫ[Z]HЫ\ЪЭ™Щ]
ЫЫ[Z]ЉB€Y€™\ЬЪ]ЬћH›Э[€Ы\ЪЭИЬ€Ы\ЪЭЛ™Щ]
™\ЬЪ]ЬћJHOHЫЫ[Z]‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€\ќYXЭЫ\ЪЭЬ™\ЬЪ]ЬћH\џHЩ\И›ЭX]Ъ™]љY][›Э™[[ЩH‹Ш\њћHHШ[YH™\ЬЪ]ЬћPЫЫ[Z][ќИH\ќYXЭ[ќ™[ЬHЉJB€Y€\Ъ[њЭ[ЩJ\ќYXЭXЭ
N‚€Y€\ќYXЭ™Щ]
\ќYXЭЪYЉH›Э[€]K™Щ]
љ[ќ\XЭ[Ы€‹ЯJK™Щ]
\ќYXЭЬ™YњИ‹ЧJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK\ќYXЭ\И›Э™Y™\™[ЩYћHH[ќ\XЭ[Ы€Э]ЫЫYH‹њ™]Z[€H[[]]X›H\ќYXЭ™Y™\™[ЩH[€H^\љY[ЩH]™[ќЉJB€]љY[ЩWЬ™YњИH\ќYXЭ™Щ]
™]љY[ЩWЬ™YњИ‹ЧJB€™]љY][Щ]љY[ЩHHЩ]
™]љY][™Щ]
™]љY[ЩWЪYИ‹ЧJJHY€\Ъ[њЭ[ЩJ™]љY][XЭ
H[ЩHЩ]

B€Y€›ЭЩ]
]љY[ЩWЬ™YњКKљ\ЬЭXњЩ]
™]љY][Щ]љY[ЩJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK\ќYXЭ]љY[ЩH\И›Э™\Щ[ќ[€™]љY][Э]]‹њ™\Щ\ќ™H]љY[ЩH[™XYЩHњ›ЫH™]љY][И\ќYXЭЉJB€[ќ\XЭ[Ы€H]K™Щ]
љ[ќ\XЭ[Ы€‹ЯJB€Y€\Ъ[њЭ[ЩJ[ќ\XЭ[Ы‹XЭ
N‚€Y€Щ]
[ќ\XЭ[Ы‹™Щ]
\ќYXЭЬ™YњИ‹ЧJJHOHШ\ќYXЭ™Щ]
\ќYXЭЪYЉ_N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы€\ќYXЭ™Y™\™[Щ\И\™H[ЫЫњЪ\Э[ќ‹њ™XЫЬ™^XЭHHЬ™X]Y[[]]X›H\ќYXЭЉJB€Y€[ќ\XЭ[Ы‹™Щ]
њ]ЧШЫЫќ™\њШ][Ы—ЬЭЬ™YЉH\И›Э[ЩHЬ€[ќ\XЭ[Ы‹™Щ]
™\™XЭЪY[ќYљY\њЧЬЭЬ™YЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы€љ]XЮH›Э[™\ћH\И›ЭЫЬЩY‹љЩY\]ИЫЫќ™\њШ][Ы€[™\™XЭY[ќYљY\њИЭ]ЪYHЪ]ЉJB€™YYXЪИH]K™Щ]
™™YYXЪИ‹ЯJB€Y€\Ъ[њЭ[ЩJ™YYXЪЛXЭ
H[™™YYXЪЛ™Щ]
њ›Ы[ЭYЭЧЭ\Щ\—ЩXЭЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK™™YYXЪИШ\И›Ы[ЭYИ\Щ\€XЭ‹љЩY\[™™\њ™Y™YYXЪИ\И[€[ЫЫ™љ\›YY\Э\Ъ\ИЉJB€›Э][™ИH]K™Щ]
њ›Э][™И‹ЯJB€Y€\Ъ[њЭ[ЩJ›Э][™ЛXЭ
H[™›Э][™Л™Щ]
љ\ЬЭYWЫЬ\][ЫњИЉHOHЧN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы€L‘H][\YH™[[ЭH\ЬЭYHЬ\][Ы€‹љЩY\\ЬЭYH›Э][™ИY]Y]K[Ы›H[ќ[H[X[€Ш]HЉJB€[\›Э™[Y[ќH]K™Щ]
љ[\›Э™[Y[ќ‹ЯJB€Y€\Ъ[њЭ[ЩJ[\›Э™[Y[ќXЭ
H[™[\›Э™[Y[ќ™Щ]
њ™[[ЭWЫЬ\][ЫњИЉHOHЧN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы€L‘H][\YH™[[ЭH[\›Э™[Y[ќЬ\][Ы€‹љЩY\Yќ€[›љ[™ИY]Y]K[Ы›HЉJB€]Y]H]K™Щ]
]Y]‹ЯJB€Y€\Ъ[њЭ[ЩJ]Y]XЭ
H[™
]Y]™Щ]
›[™HЉHOHђTЦSђЧРUQU€Ь€]Y]™Щ]
љ[ќ\XЭ[Ы—Ш›ШЪЪ[™ИЉH\И›Э[ЩHЬ€]Y]™Щ]
\ќYXЭЫЬ\][ЫњИЉHOHЧJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK]Y]\И›Э[™\[™[ќ[™™XY[Ы›H‹њќ[€]Y]Ы€]ИЭЫ€›Ы‹X›ШЪЪ[™И[™HЉJB€XШЩ\[ЩHH]K™Щ]
XШЩ\[ЩH‹ЯJB€Y€\Ъ[њЭ[ЩJXШЩ\[ЩKXЭ
H[™[ћJ[YH\И›ЭќYH›Ь€[YH[€XШЩ\[ЩKќ[Y\К
JN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[ќ\XЭ[Ы€L‘HXШЩ\[ЩH\И[ЫЫ\]H‹њ™\Щ\ќ™H]™\ћHњ›ЫќЭYЩKШXЪЬЭYЩHШY™]H[ќ\љX[ќЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WШYЩ[ќЭZWЬ™\Э[
]N€XЭЫЭ\ЩN€Э€HYЩ[ќ]ZHЉHO€\ЭЬЭ—N‚€€€•[Y]HHЫЬЩYY]Y]H[ќ™[ЬH[Z]YћHH[љ]X[RHЫЫ[X[™€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉQСS•ХRWФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭHYЩ[ќRH™\Э[љY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ€Э\ќ\H]K™Щ]
њЭ\ќ\‹ЯJB€Y€\Ъ[њЭ[ЩJЭ\ќ\XЭ
H[™Э\ќ\™Щ]
њЭ]\ИЉHOH]K™Щ]
њЭ]\ИЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKYЩ[ќRHЭ]\ИЩ\И›ЭX]ЪЭ\ќ\Э]\И‹™И›Э^ЬЩHШ\Xљ[]Y\И™^[Ы™HЭ\ќ\XЪ\Ъ[Ы€ЉJB€[њЭЩ\€H]K™Щ]
[њЭЩ\€‹ЯJB€ЫЭ\Щ\ИH[њЭЩ\‹™Щ]
њЫЭ\Щ\И‹ЧJHY€\Ъ[њЭ[ЩJ[њЭЩ\‹XЭ
H[ЩHЧB€Ы›ЭЫ€HЪЫ›ЭЫ—Ь™\ЬЪ]ЬћWЪYК
HИYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€џB€ЩY[Ћ€Щ]ЬЭ—HHЩ]

B€Y€\Ъ[њЭ[ЩJЫЭ\Щ\Л\Э
N‚€›Ь€[™^ЫЭ\ЩWЪ][H[€[ќ[Y\]JЫЭ\Щ\КN‚€Y€›Э\Ъ[њЭ[ЩJЫЭ\ЩWЪ][KXЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћHHЫЭ\ЩWЪ][K™Щ]
њ™\ЬЪ]ЬћHЉB€ЫЫ[Z]HЫЭ\ЩWЪ][K™Щ]
ЫЫ[Z]ЉB€Y€™\ЬЪ]ЬћH[€ЩY[Ћ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€[њЭЩ\‹њЫЭ\Щ\ЦЮЪ[™^WH\XШ]\ИЬ™\ЬЪ]ЬћH\џH‹™[Z]Ы™H™\ЬЪ]ЬћPЫЫ[Z]ЫЭ\ЩH™XЫЬ™ЉJB€Y€™\ЬЪ]ЬћH›Э[€Ы›ЭЫЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€[њЭЩ\‹њЫЭ\Щ\ЦЮЪ[™^WH[Y\И[љЫ›ЭЫ€™\ЬЪ]ЬћH‹ќ\ЩHЫ›HX[љY™\Э™\ЬЪ]ЬћHQИЉJB€ЩY[‹Y
™\ЬЪ]ЬћJB€Y€ЫЭ\ЩWЪ][K™Щ]
њ™\ЬЪ]ЬћWШ]ШЫЫ[Z]ЉHOH€ћЬ™\ЬЪ]Ьћ_PШЫЫ[Z]HЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€[њЭЩ\‹њЫЭ\Щ\ЦЮЪ[™^WH™\ЬЪ]ЬћPЫЫ[Z]\И[ЫЫњЪ\Э[ќ‹њ™[™\€H[[]]X›HЫЭ\ЩHЫЫ[Z]^XЪ]HЉJB€\ќYXЭH]K™Щ]
\ќYXЭ‹ЯJB€Y€\Ъ[њЭ[ЩJ\ќYXЭXЭ
H[™\ќYXЭ™Щ]
њ™\]Y\ЭYЉH\И[ЩN‚€Y€[ћJ\ќYXЭ™Щ]
љY[
H\И›Э›Ы™H›Ь€љY[[€
\ќYXЭЪY‹њ›ЭљY\—Щљ[WЪY‹ЫЫќ[ќЪ\ЪЉJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK››Э\™\]Y\ЭY\ќYXЭЫЫќZ[њИH›ЭљY\€™Y™\™[ЩH‹љЩY\XњЩ[ќЭ]]Иќ[ЉJB€™YYXЪИH]K™Щ]
™™YYXЪИ‹ЯJB€Y€\Ъ[њЭ[ЩJ™YYXЪЛXЭ
H[™›ЭЩ]
™YYXЪЛ™Щ]
љ[™™\њ™YЪYИ‹ЧJJKљ\Щ\Ъ›Ъ[ќ
Щ]
™YYXЪЛ™Щ]
™^XЪ]ЪYИ‹ЧJJJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK™™YYXЪИ\И›Э^XЪ][™[™™\њ™Y‹њ™\Щ\ќ™HH\Э[Э[Ы€™]ЩY[€ШњЩ\ќ™Y™\]Y\Э[™\Э\Ъ\ИЉJB€љ]XЮHH]K™Щ]
њљ]XЮH‹ЯJB€Y€\Ъ[њЭ[ЩJљ]XЮKXЭ
H[™[ћJљ]XЮK™Щ]
љY[
H\И›Э[ЩH›Ь€љY[[€
њ]ЧЬ]Y\ћWЬЭЬ™Y‹њ]ЧШЫЫќ™\њШ][Ы—ЬЭЬ™Y‹™љ]™WШЫЫќ[ќЬЭЬ™Y‹Ь™Y[ќX[ЧЬЭЬ™Y‹™\™XЭЪY[ќYљY\њЧЬЭЬ™YЉJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKYЩ[ќRHљ]XЮH›Э[™\ћH\ИЬ[€‹њЭЬ™HЫ›HЭќXЭ\™YY]Y]H[™Ь\]YH™Y™\™[Щ\ИЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЪ[њЬ\][ЫЉ]N€XЭЫЭ\ЩN€Э€Hљ[њЬ\][Ы‹Z[њ]ЉHO€\ЭЬЭ—N‚€€€•[Y]HHЫЩK[Ы›H[њЬ\][Ы€Ш\\™H[™]ИЬ[Ы[Щ][Y[ќ€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉS”ФTђUSУ—ФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH[њЬ\][Ы€[њ]љY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ‚€›Э™[[ЩHH]K™Щ]
њ›Э™[[ЩHЉB€Y€\Ъ[њЭ[ЩJ›Э™[[ЩKXЭ
N‚€Ы\ЪЭИH›Э™[[ЩK™Щ]
њ™]љY][ЬЫЭ\ЩWЬЫ\ЪЭИЉB€Y€\Ъ[њЭ[ЩJЫ\ЪЭЛ\Э
N‚€™\ЬЪ]ЬљY\ИHЪ][K™Щ]
њ™\ЬЪ]ЬћHЉH›Ь€][H[€Ы\ЪЭИY€\Ъ[њЭ[ЩJ][KXЭ
WB€Y€[Љ™\ЬЪ]ЬљY\КHOH[ЉЩ]
™\ЬЪ]ЬљY\КJN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњ™]љY][ЫЭ\ЩHЫ\ЪЭИ]\Э™H[љ\]YH‹њ™]Z[€Ы™H[[]]X›HЫЫ[Z]\€™\ЬЪ]ЬћHЉJB€\[[™WЬЫ\ЪЭИH›Э™[[ЩK™Щ]
њ\[[™WЬЫЭ\ЩWЬЫ\ЪЭИЉB€Y€]K™Щ]
њ\ЩHЉHOH”СUQ€[™\Ъ[њЭ[ЩJ\[[™WЬЫ\ЪЭЛ\Э
H[™›Э\[[™WЬЫ\ЪЭО‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњЩ]Y[њЬ\][Ы€XЪЬИ\[[™HЫЭ\ЩHЫ\ЪЭИ‹њЩ]HЫ›HYќ\€HШ[™Y]H\[[™H\Иќ[€ЉJB€Y€]K™Щ]
њ\ЩHЉHOH”СUQ€[™›Э›Э™[[ЩK™Щ]
Ш[™Y]WЪ[њ]Ь™YњИЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњЩ]Y[њЬ\][Ы€XЪЬИШ[™Y]H[њ]™Y™\™[Щ\И‹њ™]Z[€HЩ[XЭYШ[™Y]H›Э™[[ЩHЪ]Э]ЫЬZ[™ИЪYЫ[ЫЫќ[ќЉJB‚€\ЩHH]K™Щ]
њ\ЩHЉB€Щ][Y[ќH]K™Щ]
њЩ][Y[ќЉB€ЫЫњЩ[ќH]K™Щ]
ЫЫњЩ[ќЉB€Y€\ЩHOHђРTT‘Q€[™Щ][Y[ќ\И›Э›Ы™N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKђРTT‘Q[њЬ\][Ы€]\Э›ЭЫЫќZ[€Щ][Y[ќ‹њќ[€H^XЪ]Щ][Y[ќЭ\Yќ\€Ш[™Y]HЩ[™\][Ы€ЉJB€Y€\ЩHOH”СUQЋ‚€Y€›Э\Ъ[њЭ[ЩJЩ][Y[ќXЭ
HЬ€Щ][Y[ќ™Щ]
њЭ]\ИЉHOH”СUQЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK”СUQ[њЬ\][Ы€XЪЬИHЩ]Y™\Э[‹њ™]Z[€Ш[™Y]H\[[™H\Ъ\И[™Щ[XЭYШ[™Y]HQИЉJB€Y€›Э\Ъ[њЭ[ЩJЫЫњЩ[ќXЭ
HЬ€ЫЫњЩ[ќ™Щ]
њЩ][Y[ќШЫЫ™љ\›YYЉH\И›ЭќYN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњЩ][Y[ќЫЫњЩ[ќ\И›ЭЫЫ™љ\›YY‹њЩ]HЫ›HЪ][€HШ\\™YЫЫњЩ[ќШЫЬHЉJB€Y€\Ъ[њЭ[ЩJЫЫњЩ[ќXЭ
H[™ЫЫњЩ[ќ™Щ]
њ›Щљ[WЭ\]WЬ\›Z]YЉH\И›Э[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњ›Щљ[WЭ\]WЬ\›Z]Y]\Э™H[ЩH‹™И›Э›Ы[ЭH[€[њЬ\][Ы€[ќИH\Щ\€›Щљ[HXЭЉJB€љ]XЮHH]K™Щ]
њљ]XЮHЉB€Y€\Ъ[њЭ[ЩJљ]XЮKXЭ
N‚€›Ь€љY[[€
њ]ЧЪ[њЬ\][Ы—ЬЭЬ™Y‹њ]ЧШЫЫќ™\њШ][Ы—ЬЭЬ™Y‹™\™XЭЪY[ќYљY\њЧЬЭЬ™YЉN‚€Y€љ]XЮK™Щ]
љY[
H\И›Э[ЩN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њљ]XЮKћЩљY[H]\Э™H[ЩH‹њ™]Z[€Ы›HЫЩ\Л\Ъ\Л[™Ь\]YH›Э™[[ЩH™Y™\™[Щ\ИЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЪ[љ]X[ЫЬ\][ЫњЧЩL™J]N€XЭЫЭ\ЩN€Э€Hљ[љ]X[[Ь\][ЫњЛYL™HЉHO€\ЭЬЭ—N‚€€€•[Y]HHЫЬЩY™]ЫЬљЫ\ЬИ[љ]X[Ь\][ЫњИ]љY[ЩH[ќ™[ЬK€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉS’UPSУФTђUSУ”ЧСL‘WФРТSPWФU
B€\њ›ЬњЛ™^[™
€Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭH[љ]X[Ь\][ЫњИL‘HљY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€\њ›ЬњЛ™^[™
ЬШШ[—Щ›ЬљY[—Ь™]љY][ЩљY[К]KЫЭ\ЩJJB€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ€Э\ќ\H]K™Щ]
њЭ\ќ\‹ЯJB€Y€\Ъ[њЭ[ЩJЭ\ќ\XЭ
H[™Э\ќ\™Щ]
›Ь™\™YЬЭ\ШЫЭ[ќЉHOHN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKњЭ\ќ\™Y›YЪ\И[ЫЫ\]H‹њќ[€[љ[™H™XY[Ы›HЭ\ќ\Э\ИЉJB€™]љY][H]K™Щ]
њ™]љY][‹ЯJB€Y€\Ъ[њЭ[ЩJ™]љY][XЭ
N‚€›Ь€[™^ЫЭ\ЩWЪ][H[€[ќ[Y\]J™]љY][™Щ]
њЫЭ\Щ\И‹ЧJJN‚€Y€›Э\Ъ[њЭ[ЩJЫЭ\ЩWЪ][KXЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћWШ]ШЫЫ[Z]HЫЭ\ЩWЪ][K™Щ]
њ™\ЬЪ]ЬћWШ]ШЫЫ[Z]‹€ЉB€™\ЬЪ]ЬћHHЫЭ\ЩWЪ][K™Щ]
њ™\ЬЪ]ЬћHЉB€Y€™\ЬЪ]ЬћH›Э[€™\ЬЪ]ЬћWШ]ШЫЫ[Z]Ь€ђ€›Э[€™\ЬЪ]ЬћWШ]ШЫЫ[Z]‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK€њ™]љY][њЫЭ\Щ\ЦЮЪ[™^WHXЪЬИ™\ЬЪ]ЬћPЫЫ[Z]‹њ™]Z[€[[]]X›HЫЭ\ЩH›Э™[[ЩH[€H[њЭЩ\€ЉJB€љ]™HH]K™Щ]
™љ]™H‹ЯJB€Y€\Ъ[њЭ[ЩJљ]™KXЭ
H[™љ]™K™Щ]
›Ь\][Ы—ЬЩ\]Y[ЩHЉHOHИ”‘PQ‹ђФ‘PUH‹”‘PQ‹”‘PQ‹”‘PQ—N‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK‘љ]™HЬ\][Ы€Щ\]Y[ЩH\И›ЭЬ™X]KЬ™XYЬ™\^K[Ы›H‹љЩY\™\^H\ИHX\љЩ\€ЩX\Ъ[™™XYXXЪИЪ]Э]HЩXЫЫ™Ф‘PUHЉJB€\ЬЭYHH]K™Щ]
љ\ЬЭYH‹ЯJB€Y€\Ъ[њЭ[ЩJ\ЬЭYKXЭ
N‚€Y€\ЬЭYK™Щ]
Ь™X]H‹ЯJK™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬћHЉHOH\ЬЭYK™Щ]
њ™]\ЩH‹ЯJK™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬћHЉN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK’\ЬЭYHФ‘PUKФ‘UTСH\™Щ]ИY™™\€‹њ™]\ЩHHШ[YH]]Ьљ]]]™HY\XШ][Ы€\™Щ]ЉJB€Y€]K™Щ]
›™]ЫЬљИЉHOH™\ШX›Y€Ь€]K™Щ]
њ™[[ЭWЫЬ\][ЫњИЉHOHЧN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[љ]X[Ь\][ЫњИL‘H\И™[[ЭHЬ\][ЫњИ‹љЩY\H]X[YљXШ][Ы€]™]ЫЬљЫ\ЬИ[™\ЩHHЩ\\]HЬZ[€]™HШ]HЉJB€]™WЩШ]HH]K™Щ]
›]™WЩШ]H‹ЯJB€Y€\Ъ[њЭ[ЩJ]™WЩШ]KXЭ
H[™]™WЩШ]K™Щ]
њЭ]\ИЉHOH““ХФ‘TUQTХQЋ‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩK›]™HШ]HШ\И[\XЪ]H^XЭ]Y‹њ™\]Z\™H[€^XЪ]Ш[™›Ю[™[X[€ЫЫ™љ\›X][Ы€™Y›Ь™H]™HЬ\][ЫњИЉJB€XШЩ\[ЩHH]K™Щ]
XШЩ\[ЩH‹ЯJB€Y€\Ъ[њЭ[ЩJXШЩ\[ЩKXЭ
H[™[ћJ[YH\И›ЭќYH›Ь€[YH[€XШЩ\[ЩKќ[Y\К
JN‚€\њ›ЬњЛ\[™
Ъ[ќ\XЭ[Ы—Щ\њ›ЬЉЫЭ\ЩKљ[љ]X[Ь\][ЫњИL‘HXШЩ\[ЩH\И[ЫЫ\]H‹њ™\Щ\ќ™H]™\ћHЭ\ќ\›Э™[[ЩKY[\Э[ЮK[™љ]XЮH[ќ\љX[ќЉJB€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЭЫЬљЧЪ][J]N€XЭЫЭ\ЩN€Э€HќЫЬљЛZ][HЉHO€\ЭЬЭ—N‚€€€•[Y]HH™\Э[XX›HЬ›ЬЬЛ\™\ЬЪ]ЬћHЫЬљИ][H[™]ИШY™]Hќ[\Л€€€‚€\њ›ЬњО€\ЭЬЭ—HHЧB€ШЪ[XHHШYЪњЫЫЉУФ’ТUSWФРТSPWФU
B€\њ›ЬњЛ™^[™
€ЬЪYЫ[Щ\њ›ЬЉЫЭ\ЩKШЪ[XWЩ\њ›Ь‹ЫЬњ™XЭHЫЬљИ][HљY[ЉB€›Ь€ШЪ[XWЩ\њ›Ь€[€ЬШЪ[XWЩ\њ›ЬњК]KШЪ[XJB€
B€Y€›Э\Ъ[њЭ[ЩJ]KXЭ
N‚€™]\›€\њ›ЬњВ‚€X[љY™\ЭHШYЮX[[
PS’Q‘TХФU
B€™\ЬЪ]ЬљY\ИHX[љY™\Э™Щ]
њ™\ЬЪ]ЬљY\И‹ЧJHY€\Ъ[њЭ[ЩJX[љY™\ЭXЭ
H[ЩHЧB€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\ИHВ€™\Л™Щ]
љYЉH›Ь€™\И[€™\ЬЪ]ЬљY\ИY€\Ъ[њЭ[ЩJ™\ЛXЭ
B€B€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\ЛY
YЩ[ќXЛX\ќ[ЬЪ\Э][Ы€ЉB€ЭЫ™\€H]K™Щ]
›ЭЫ™\—Ь™\ЬЪ]ЬћHЉB€\™Щ]ИH]K™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬљY\ИЉB€Y€ЭЫ™\€›Э[€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\О‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€€›ЭЫ™\—Ь™\ЬЪ]ЬћHЫЭЫ™\€\џH\И›ЭXЫ\™Y‹€ќ\ЩHH™\ЬЪ]ЬћHQњ›ЫHЫЫ™љYЛЬ™\ЬЪ]ЬљY\ЛћX[[‹€
B€
B€Y€\Ъ[њЭ[ЩJ\™Щ]Л\Э
N‚€›Ь€[™^™\ЬЪ]ЬћH[€[ќ[Y\]J\™Щ]КN‚€Y€™\ЬЪ]ЬћH›Э[€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\О‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€€ќ\™Щ]Ь™\ЬЪ]ЬљY\ЦЮЪ[™^WHЬ™\ЬЪ]ЬћH\џH\И›ЭXЫ\™Y‹€ќ\ЩHЫ›HX[љY™\Э™\ЬЪ]ЬћHQИ‹€
B€
B€Y€ЭЫ™\€›Э[€\™Щ]О‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€›ЭЫ™\—Ь™\ЬЪ]ЬћH]\Э™H[ЫYY[€\™Щ]Ь™\ЬЪ]ЬљY\И‹€›XZЩHHЭЫ™\€[€^XЪ]\™Щ]Щ€HЫЬљИ][H‹€
B€
B‚€[ЭЩYЬ]ИH]K™Щ]
[ЭЩYЬ]ИЉB€Y€\Ъ[њЭ[ЩJ[ЭЩYЬ]Л\Э
N‚€Y€[Љ[ЭЩYЬ]КHOH[ЉЩ]
[ЭЩYЬ]КJN‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€[ЭЩYЬ]И]\Э™H[љ\]YH‹€™XЫ\™HXXЪЬљ]X›H]ЫЩH‹€
B€
B€›Ь€[™^][€[ќ[Y\]J[ЭЩYЬ]КN‚€Y€›ЭЪ\ЧЬШY™WЬ™[]]™WЬ]
]
N‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€€[ЭЩYЬ]ЦЮЪ[™^WH\И›ЭHШY™H™[]]™H]‹€њ™[[Э™HXњЫЫ]H]И[™€Ь€‹€ЩYЫY[ќИ‹€
B€
B‚€\[™[ЪY\ИH]K™Щ]
™\[™ЧЫЫ€ЉB€Y€\Ъ[њЭ[ЩJ\[™[ЪY\Л\Э
N‚€Y€[Љ\[™[ЪY\КHOH[ЉЩ]
\[™[ЪY\КJN‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€™\[™ЧЫЫ€]\Э™H[љ\]YH‹€™XЫ\™HXXЪ\[™[ЮHЫЩH‹€
B€
B€Y€]K™Щ]
љYЉH[€\[™[ЪY\О‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€ќЫЬљИ][HШ[››Э\[™Ы€]Щ[€‹€њ™[[Э™HHЩ[€\[™[ЮH[™ЩY\H\ЪИQИXЮXЫXИ‹€
B€
B‚€ЪXЪЬИH]K™Щ]
ЪXЪЬИЉB€Y€\Ъ[њЭ[ЩJЪXЪЬЛ\Э
N‚€›Ь€[™^ЪXЪИ[€[ќ[Y\]JЪXЪЬКN‚€Y€›Э\Ъ[њЭ[ЩJЪXЪЛXЭ
N‚€ЫЫќ[ќYB€™\ЬЪ]ЬћHHЪXЪЛ™Щ]
њ™\ЬЪ]ЬћHЉB€Y€™\ЬЪ]ЬћH›Э[€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\О‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€€ЪXЪЬЦЮЪ[™^WKњ™\ЬЪ]ЬћHЬ™\ЬЪ]ЬћH\џH\И›ЭXЫ\™Y‹€њќ[€XXЪЪXЪИ[€HX[љY™\Э™\ЬЪ]ЬћH‹€
B€
B€ЫЫ[X[™HЪXЪЛ™Щ]
ЫЫ[X[™ЉB€Y€\Ъ[њЭ[ЩJЫЫ[X[™ЭЉH[™[ћJЪЩ[€[€ЫЫ[X[™›Ь€ЪЩ[€[€УУSPS‘С“Фђ’QS—ХТСS”КN‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€€ЪXЪЬЦЮЪ[™^WKЫЫ[X[™ЫЫќZ[њИЪ[ЫЫќ›ЫЮ[ќ^‹€њЬ]ЪXЪЬИ[ќИЩ\\]HШY™HЫЫ[X[™И‹€
B€
B‚€][\ИH]K™Щ]
][\ИЉB€Y€\Ъ[њЭ[ЩJ][\ЛXЭ
N‚€\ЩYH][\Л™Щ]
ќ\ЩYЉB€X^[][HH][\Л™Щ]
›X^ЉB€Y€\Ъ[њЭ[ЩJ\ЩY[ќ
H[™\Ъ[њЭ[ЩJX^[][K[ќ
H[™\ЩY€X^[][N‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€][\Лќ\ЩYШ[››Э^ЩYY][\Л›X^‹€њ™XЫЬ™HXЭX[™]ћHЫЭ[ќЪ][€HXЫ\™Y™]ћHќYЩ]‹€
B€
B€ЫЫ™љYИHШYЮX[[
“УХИЫЫ™љYЛЫЬЪ\Э][Ы‹ћX[[ЉB€ЫЫ™љYЭ\™YЫX^HЫЫ™љYЛ™Щ]
™^XЭ][Ы€‹ЯJK™Щ]
›X^Ш][\ИЉB€Y€\Ъ[њЭ[ЩJX^[][K[ќ
H[™\Ъ[њЭ[ЩJЫЫ™љYЭ\™YЫX^[ќ
H[™X^[][H€ЫЫ™љYЭ\™YЫX^‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€€][\Л›X^ЫX^[][_H^ЩYYИЫЫ™љYЭ\™YX^Ш][\ИШЫЫ™љYЭ\™YЫX^H‹€ќ\ЩHH™\ЬЪ]ЬћH™]ћHќYЩ]Ь€\]HЫXЮH^XЪ]H‹€
B€
B‚€X\ЩHH]K™Щ]
›X\ЩHЉB€\›Z[[ЬЭ]HH]K™Щ]
ќ\›Z[[ЬЭ]HЉB€Y€\Ъ[њЭ[ЩJX\ЩKXЭ
N‚€Y€X\ЩK™Щ]
њЭ]\ИЉHOH]Z[X›H€[™X\ЩK™Щ]
›ЭЫ™\€ЉHOHќ[\ЬЪYЫ™YЋ‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€]Z[X›HX\ЩH]\Э]™HЭЫ™\€	Э[\ЬЪYЫ™Y	И‹€ЫX\€HX\ЩHЭЫ™\€™Y›Ь™H™]\›љ[™ИH][HИH]Y]YH‹€
B€
B€Y€X\ЩK™Щ]
њЭ]\ИЉHOHљ[€[™X\ЩK™Щ]
›ЭЫ™\€ЉHOHќ[\ЬЪYЫ™YЋ‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€љ[X\ЩH]\ЭY[ќYћH]ИЭЫ™\€‹€њ™XЫЬ™HXЭ]™HЫЬљЩ\€ЭЫ™\€[™^\ћH‹€
B€
B€Y€\›Z[[ЬЭ]H[€И”‘PQH‹ђђPТУСИџH[™X\ЩK™Щ]
њЭ]\ИЉHOHљ[Ћ‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€њ]Y]YYЫЬљИ][HШ[››Э™]Z[€H[X\ЩH‹€њ™[X\ЩHHX\ЩH™Y›Ь™H™]\›љ[™ИИђPТУСИЬ€‘PQH‹€
B€
B‚€]љY[ЩHH]K™Щ]
™]љY[ЩHЉB€Y€\›Z[[ЬЭ]HOH‘У‘H€[™\Ъ[њЭ[ЩJ]љY[ЩKXЭ
N‚€Y€›Э]љY[ЩK™Щ]
ќ\ЭИЉN‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€‘У‘HЫЬљИ][H™\]Z\™\И\Э]љY[ЩH‹€њ™XЫЬ™HШњЩ\ќ™Y\ЭЫЫ[X[™И™Y›Ь™HX\љЪ[™ИУ‘H‹€
B€
B€Y€›Э]љY[ЩK™Щ]
ЫЫ[Z]ИЉN‚€\њ›ЬњЛ\[™
€ЬЪYЫ[Щ\њ›ЬЉ€ЫЭ\ЩK€‘У‘HЫЬљИ][H™\]Z\™\ИЫЫ[Z]]љY[ЩH‹€њ™XЫЬ™H™\ЬЪ]ЬћHЫЫ[Z]ТHЬ€ЩY\H][H›Ы‹]\›Z[[‹€
B€
B€™]\›€\њ›ЬњВ‚‚™Y€[Y]WЬ™\ЬЪ]ЬљY\К\њ›ЬњО€\ЭЬЭ—KX[љY™\ЭЬ]€]HPS’Q‘TХФU
HO€›Ы™N‚€]HHШYЮX[[
X[љY™\ЭЬ]
B€\њ›ЬњЛ™^[™
[Y]WЫX[љY™\Э
]KЬЫЭ\ЩWЫX™[
X[љY™\ЭЬ]
JJB‚‚™Y€[Y]WЭ\ЪЬК\њ›ЬњО€\ЭЬЭ—K]Y]YWЬ]€]›Ы™HH›Ы™JHO€›Ы™N‚€]Y]YWЬ]H]Y]YWЬ]Ь€“УХИ™^XЭ][Ы‹Э\ЪЛ\]Y]YKћX[[‚€]HHШYЮX[[
]Y]YWЬ]
B€\ЪЬИH]K™Щ]
ќ\ЪЬИ‹ЧJHY€\Ъ[њЭ[ЩJ]KXЭ
H[ЩHЧB€YИHЭ\ЪЛ™Щ]
љYЉH›Ь€\ЪИ[€\ЪЬЧB€Y€[ЉYКHOH[ЉЩ]
YКJN‚€\њ›ЬњЛ\[™
€ћЬ]Y]YWЬ]N€\ЪИQИ]\Э™H[љ\]YHЉB€ћWЪYHЭ\ЪЛ™Щ]
љYЉN€\ЪИ›Ь€\ЪИ[€\ЪЬЯB€X[љY™\ЭHШYЮX[[
PS’Q‘TХФU
B€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\ИHВ€™\Л™Щ]
љYЉN€™\Л™Щ]
™ќ[Ы[YHЉB€›Ь€™\И[€X[љY™\Э™Щ]
њ™\ЬЪ]ЬљY\И‹ЧJB€Y€\Ъ[њЭ[ЩJ™\ЛXЭ
B€B€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\ЦИYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€—HH›X\ШK\Ш[‹ZњШYЩ[ќXЛX\ќ[ЬЪ\Э][Ы€‚€Y€[ћJЭЉ\ЪЛ™Щ]
љY‹€ЉJKњЭ\ќЭЪ]
ђPRЛHЉH›Ь€\ЪИ[€\ЪЬКHЬ€
]Y]YWЬ]OH“УХИ™^XЭ][Ы‹Э\ЪЛ\]Y]YKћX[[€[™
“УХИЫЫ™љYЛШXZЛ]\ЪЛ\›Ъ™XЭ[Ы‹љњЫЫ€ЉKљ\ЧЩљ[J
JN‚€њ›ЫHЫЫЛљ\ЬЭYWЪ[ќZЩH[\ЬќXZЧЬ›Ъ™XЭ[Ы‹[Y]WШXZЧЬ›Ъ™XЭ[Ы‚€\њ›ЬњЛ™^[™
[Y]WШXZЧЬ›Ъ™XЭ[ЫЉ“УХ]JJB€ћN‚€›Ь€›Ъ™XЭ[Ы€[€XZЧЬ›Ъ™XЭ[ЫЉ“УХ
VИќ\ЪЬИ—N‚€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\ЦЬ›Ъ™XЭ[Ы–И›ЭЫ™\€—WHH›X\ШK\Ш[‹ZњИ€
И›Ъ™XЭ[Ы–И›ЭЫ™\€—B€^Щ\[YQ\њ›Ь€\И^О‚€\њ›ЬњЛ\[™
ЭЉ^КJB€›Ь€\ЪИ[€\ЪЬО‚€\ЪЧЪYH\ЪЛ™Щ]
љY‹ЏZ\ЬЪ[™П€ЉB€›Ь€љY[[€
›Z[\ЭЫ™H‹ќ]H‹њЭ]\И‹™\[™ЧЫЫ€‹XШЩ\[ЩH‹ЪXЪЬИЉN‚€Y€љY[›Э[€\ЪО‚€\њ›ЬњЛ\[™
€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKћЩљY[H\И™\]Z\™YЉB€Y€\ЪЛ™Щ]
њЭ]\ИЉH›Э[€ХUTСTО‚€\њ›ЬњЛ\[™
€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKњЭ]\И\И[љЫ›ЭЫ€ЉB€\ЬЭYWЩљY[ИH
љ\ЬЭYWЬЬЫЭ‹ќ\™Щ]Ь™\ЬЪ]ЬљY\И‹YЩ[ќЭ\›Z[[ЉB€\ЧЪ\ЬЭYWЩљY[ИHЩљY[[€\ЪИ›Ь€љY[[€\ЬЭYWЩљY[ЧB€Y€\ЪЧЪY[€TФХQWФФУЧХTТЧТQИ[™›Э[
\ЧЪ\ЬЭYWЩљY[КN‚€Z\ЬЪ[™ИHЩљY[›Ь€љY[[€\ЬЭYWЩљY[ИY€љY[›Э[€\ЪЧB€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYHZ\ЬЪ[™И\ЬЭYHФУХљY[
КHЫZ\ЬЪ[™ЯNИ‚€Y\ЬЭYWЬЬЫЭ\™Щ]Ь™\ЬЪ]ЬљY\Л[™YЩ[ќЭ\›Z[[‚€
B€[Y€[ћJ\ЧЪ\ЬЭYWЩљY[КH[™›Э[
\ЧЪ\ЬЭYWЩљY[КN‚€Z\ЬЪ[™ИHЩљY[›Ь€љY[[€\ЬЭYWЩљY[ИY€љY[›Э[€\ЪЧB€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYH\И[ЫЫ\]H\ЬЭYHФУХЫЫќXЭИ‚€€›Z\ЬЪ[™ИЫZ\ЬЪ[™ЯH‚€
B€Y€[
\ЧЪ\ЬЭYWЩљY[КN‚€\ЬЭYWЭ\›H\ЪЛ™Щ]
љ\ЬЭYWЬЬЫЭЉB€X]ЪHТUP—ТTФХQWХT“™ќ[X]Ъ
\ЬЭYWЭ\›
HY€\Ъ[њЭ[ЩJ\ЬЭYWЭ\›ЭЉH[ЩH›Ы™B€Y€X]Ъ\И›Ы™N‚€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKљ\ЬЭYWЬЬЫЭ\И›ЭHШ[›ЫљXШ[Ъ]X€\ЬЭYHT“И‚€ќ\ЩHО‹ЛЩЪ]X‹ЫЫKПЭЫ™\Џ‹П™\П‹Ъ\ЬЭY\ЛПќ[X™\Џ€‚€
B€\™Щ]ИH\ЪЛ™Щ]
ќ\™Щ]Ь™\ЬЪ]ЬљY\ИЉB€Y€›Э\Ъ[њЭ[ЩJ\™Щ]Л\Э
HЬ€›Э\™Щ]О‚€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKќ\™Щ]Ь™\ЬЪ]ЬљY\И]\Э™HH›Ы‹Y[\H\ЭИ‚€™XЫ\™HHЭЫљ[™ИX[љY™\Э™\ЬЪ]ЬћH‚€
B€[ЩN‚€Y€[Љ\™Щ]КHOH[ЉЩ]
\™Щ]КJN‚€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKќ\™Щ]Ь™\ЬЪ]ЬљY\И]\Э™H[љ\]YNИ‚€њ™[[Э™H\XШ]H™\ЬЪ]ЬћHQИ‚€
B€[љЫ›ЭЫ€HЬ™\И›Ь€™\И[€\™Щ]ИY€™\И›Э[€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\ЧB€Y€[љЫ›ЭЫЋ‚€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKќ\™Щ]Ь™\ЬЪ]ЬљY\И\И[љЫ›ЭЫ€™\ЬЪ]ЬћHQИЭ[љЫ›ЭЫџNИ‚€ќ\ЩH™\ЬЪ]ЬљY\ЛћX[[QИ‚€
B€Y€X]Ъ\И›Э›Ы™N‚€\™Щ]Щќ[Ы[Y\ИHВ€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\ЦЬ™\ЧH›Ь€™\И[€\™Щ]ИY€™\И[€Ы›ЭЫ—Ь™\ЬЪ]ЬљY\В€B€Y€X]Ъ™Ь›Э\
JH›Э[€\™Щ]Щќ[Ы[Y\О‚€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKљ\ЬЭYWЬЬЫЭ]]Ьљ]HЫX]Ъ™Ь›Э\
JH\џH‚€љ\ИЭ]ЪYH\™Щ]Ь™\ЬЪ]ЬљY\ОИЪ[ќИH]]Ьљ]]]™H™\ЬЪ]ЬћH\ЬЭYH‚€
B€Y€\ЪЛ™Щ]
YЩ[ќЭ\›Z[[ЉH›Э[€QСS•ХT“RSђSО‚€\њ›ЬњЛ\[™
€€ћЬ]Y]YWЬ]N€Э\ЪЧЪYKYЩ[ќЭ\›Z[[\И[љЫ›ЭЫЋИ‚€€ќ\ЩHЫ™HЩ€ЬЫЬќY
QСS•ХT“RSђSК_H‚€
B€\ИH\ЪЛ™Щ]
™\[™ЧЫЫ€‹ЧJB€›Ь€\[€\О‚€Y€\›Э[€ћWЪY‚€\њ›ЬњЛ\[™
€ћЬ]Y]YWЬ]N€Э\ЪЧЪYH\[™ИЫ€Z\ЬЪ[™ИЩ\HЉB€Y€\ЪЛ™Щ]
њЭ]\ИЉHOH”‘PQHЋ‚€[ЫЫ\]HHЩ\›Ь€\[€\ИY€ћWЪY™Щ]
\ЯJK™Щ]
њЭ]\ИЉHOH‘У‘H—B€Y€[ЫЫ\]N‚€\њ›ЬњЛ\[™
€ћЬ]Y]YWЬ]N€Э\ЪЧЪYH‘PQHЪ][ЫЫ\]HЪ[ЫЫ\]_HЉB‚€љ\Ъ][™О€Щ]ЬЭ—HHЩ]

B€љ\Ъ]Y€Щ]ЬЭ—HHЩ]

B‚€Y€љ\Ъ]
\ЪЧЪY€Э‹ЪZ[Ћ€\ЭЬЭ—JHO€›Ы™N‚€Y€\ЪЧЪY[€љ\Ъ][™О‚€\њ›ЬњЛ\[™
€ћЬ]Y]YWЬ]N€ЮXЫHЙИO€	Лљ›Ъ[ЉЪZ[€
ИЭ\ЪЧЪYJ_HЉB€™]\›‚€Y€\ЪЧЪY[€љ\Ъ]YЬ€\ЪЧЪY›Э[€ћWЪY‚€™]\›‚€љ\Ъ][™ЛY
\ЪЧЪY
B€›Ь€\[€ћWЪYЭ\ЪЧЪYK™Щ]
™\[™ЧЫЫ€‹ЧJN‚€љ\Ъ]
\ЪZ[€
ИЭ\ЪЧЪYJB€љ\Ъ][™Лњ™[[Э™J\ЪЧЪY
B€љ\Ъ]YY
\ЪЧЪY
B‚€›Ь€\ЪЧЪY[€ћWЪY‚€љ\Ъ]
\ЪЧЪYЧJB‚‚™Y€[Y]JX[љY™\ЭЬ]€]HPS’Q‘TХФU
HO€\ЭЬЭ—N‚€\њ›ЬњО€\ЭЬЭ—HHЧB€›Ь€™[[€‘TURT‘QС’STО‚€Y€›Э
“УХИ™[
Kљ\ЧЩљ[J
N‚€\њ›ЬњЛ\[™
€ћЬ™[N€™\]Z\™Yљ[H\ИZ\ЬЪ[™ИЉB€Y€\њ›ЬњО‚€™]\›€\њ›ЬњВ€ћN‚€[Y]WЬ™\ЬЪ]ЬљY\К\њ›ЬњЛX[љY™\ЭЬ]
B€[Y]WЭ\ЪЬК\њ›ЬњКB€\њ›ЬњЛ™^[™
€[Y]WЬ™\ЩX\ЪЩ^XЭ][Ы—Ш›Э[™\ћJ€ШYЮX[[
ЊL—Р“ХS‘T–WРУУ‘’QЧФU
K€ЬЫЭ\ЩWЫX™[
ЊL—Р“ХS‘T–WРУУ‘’QЧФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЭ[њЩ›Ь›X][Ы—Ьќ[WЬ™YЪ\ЭћJ€ШYЮX[[
ђS”С“Ф“PUSУ—Ф•SWРУУ‘’QЧФU
K€ЬЫЭ\ЩWЫX™[
ђS”С“Ф“PUSУ—Ф•SWРУУ‘’QЧФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЬЭ\ќ\ШЫЫќXЭ
€ШYЮX[[
ХT•TФУPЦWФU
K€ШYЪњЫЫЉХT•TФ‘TФ•ФРТSPWФU
K€ЬЫЭ\ЩWЫX™[
ХT•TФУPЦWФU
K€ЬЫЭ\ЩWЫX™[
ХT•TФ‘TФ•ФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЪ\ЬЭYWЩ[]™\ћWШЫЫќXЭ
€ШYЮX[[
TФХQWСSU‘T–WФУPЦWФU
K€ШYЪњЫЫЉTФХQWСSU‘T–WФРТSPWФU
K€ШYЮX[[
X[љY™\ЭЬ]
K€ЬЫЭ\ЩWЫX™[
TФХQWСSU‘T–WФУPЦWФU
K€ЬЫЭ\ЩWЫX™[
TФХQWСSU‘T–WФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЩљ]™WЫ]™WШЫЫќXЭ
€ШYЮX[[
’U‘WУU‘WФУPЦWФU
K€ШYЪњЫЫЉ’U‘WУU‘WФРТSPWФU
K€ЬЫЭ\ЩWЫX™[
’U‘WУU‘WФУPЦWФU
K€ЬЫЭ\ЩWЫX™[
’U‘WУU‘WФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЩЪ]X—ЬШ[™›ЮЫ]™WШЫЫќXЭ
€ШYЮX[[
ТUP—ФРS‘“ЦУU‘WФУPЦWФU
K€ШYЪњЫЫЉТUP—ФРS‘“ЦУU‘WФРТSPWФU
K€ШYЮX[[
X[љY™\ЭЬ]
K€ЬЫЭ\ЩWЫX™[
ТUP—ФРS‘“ЦУU‘WФУPЦWФU
K€ЬЫЭ\ЩWЫX™[
ТUP—ФРS‘“ЦУU‘WФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WШ]]Ы›Ы[Э\ЧШЫЫќXЭ
€ШYЮX[[
SPS—СРUTЧФU
K€ШYЪњЫЫЉQСS•РPХSУ—ФРТSPWФU
K€ШYЪњЫЫЉQСS•Ф‘TХSФРТSPWФU
K€ШYЪњЫЫЉUUУ“УSХTЧФ•S—ФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WШ]ЪЬ™\ЬќШЫЫќXЭ
€ШYЪњЫЫЉђUТФ‘TФ•СU‘S•ФРТSPWФU
K€ЬЫЭ\ЩWЫX™[
ђUТФ‘TФ•СU‘S•ФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЫЭ]]Щ\Э[][ЫњЧШЫЫќXЭ
€ШYЪњЫЫЉХUUСTХSђUSУ”ЧФРТSPWФU
K€ШYЪњЫЫЉTХSђUSУ—Ф‘TУУUSУ—ФРТSPWФU
K€ШYЮX[[
ХUUСTХSђUSУ”ЧСVSTWФU
K€ЬЫЭ\ЩWЫX™[
ХUUСTХSђUSУ”ЧФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЭЫЬљЬЬXЩWШ›ЫЭЭ\ШЫЫќXЭ
€ШYЪњЫЫЉУФ’ФФPСWР“УХХђTФРТSPWФU
K€ЬЫЭ\ЩWЫX™[
УФ’ФФPСWР“УХХђTФРТSPWФU
K€
B€
B€\њ›ЬњЛ™^[™
€[Y]WЬX›XЧЬ›Ъ™XЭ[Ы—ШЫЫќXЭ
€ШYЪњЫЫЉP“PЧФ“Т‘PХУVSХUФРТSPWФU
K€ШYЪњЫЫЉP“PЧФ“Т‘PХSУ—Ф‘TUQTХФРТSPWФU
K€ШYЪњЫЫЉP“PЧФ“Т‘PХSУ—РT“ХђSФРТSPWФU
K€ШYЪњЫЫЉP“PЧФ“Т‘PХSУ—Ф‘TХSФРТSPWФU
K€ЬЫЭ\ЩWЫX™[
P“PЧФ“Т‘PХSУ—Ф‘TХSФРТSPWФU
K€
B€
B€Э]HHШYЮX[[
“УХИ™^XЭ][Ы‹ЬЭ]KћX[[ЉB€\њ›ЬњЛ™^[™
[Y]WЩ^XЭ][Ы—ЬЭ]JЭ]KЬЫЭ\ЩWЫX™[
“УХИ™^XЭ][Ы‹ЬЭ]KћX[[ЉJJB€\њ›ЬњЛ™^[™
[Y]WЪЫ›ЭЫYЩWШЮXЫWШЫЫќXЭК
JB€Y€Э]K™Щ]
›\ЭШЫЫ\]YЭ\ЪИЉH\И›Ы™N‚€\њ›ЬњЛ\[™
™^XЭ][Ы‹ЬЭ]KћX[[€\ЭШЫЫ\]YЭ\ЪИ\И™\]Z\™YЉB€^Щ\[YQ\њ›Ь€\И^О‚€\њ›ЬњЛ\[™
ЭЉ^КJB€™]\›€\њ›ЬњВ‚‚™Y€XZ[Љ
HO€[ќ‚€\њЩ\€H\™Ь\њЩKђ\™Э[Y[ќ\њЩ\Љ\ШЬљ\[ЫЏH•[Y]HЬЪ\Э][Ы€›ЫЭЭ\ЉB€\њЩ\‹YШ\™Э[Y[ќ
‹KXЪXЪИ‹XЭ[ЫЏHњЭЬ™WЭќYH‹[Hќ[Y]HЪ]Э]Ьљ][™ИЉB€\њЩ\‹YШ\™Э[Y[ќ
€‹K[X[љY™\Э‹€\OT]€Y][SPS’Q‘TХФU€[H›X[љY™\ЭPSSИ[Y]H
Y][ИИЫЫ™љYЛЬ™\ЬЪ]ЬљY\ЛћX[[
H‹€
B€\™ЬИH\њЩ\‹њ\њЩWШ\™ЬК
B€X[љY™\ЭЬ]H\™ЬЛ›X[љY™\ЭY€\™ЬЛ›X[љY™\Эљ\ЧШXњЫЫ]J
H[ЩH]ЭЩ

HИ\™ЬЛ›X[љY™\Э€\њ›ЬњИH[Y]JX[љY™\ЭЬ]
B€Y€\њ›ЬњО‚€›Ь€\њ›Ь€[€\њ›ЬњО‚€љ[ќ
€‘T”“ФЋ€Щ\њ›ЬџH‹љ[O\Ю\ЛњЭ\њЉB€™]\›€B€љ[ќ
“ТО€ЬЪ\Э][Ы€›ЫЭЭ\\И[YЉB€™]\›€‚‚љY€ЧЫ[YWЧИOH—ЧЫXZ[—ЧИЋ‚€Z\ЩHЮ\Э[Q^]
XZ[Љ
JB