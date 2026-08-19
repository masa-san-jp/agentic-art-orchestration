#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/repositories.yaml"
MANIFEST_SCHEMA_PATH = ROOT / "schemas/repository-manifest.schema.json"
SIGNAL_SCHEMA_PATH = ROOT / "schemas/normalized-research-signal.schema.json"
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
V12_BOUNDARY_SCHEMA_PATH = ROOT / "schemas/research-execution-boundary.schema.json"
V12_BOUNDARY_CONFIG_PATH = ROOT / "config/research-execution-boundary.yaml"
TRANSFORMATION_RULE_SCHEMA_PATH = ROOT / "schemas/transformation-rule.schema.json"
TRANSFORMATION_RULE_CONFIG_PATH = ROOT / "config/transformation-rules.yaml"
CANDIDATE_SCHEMA_PATH = ROOT / "schemas/research-candidate.schema.json"
CANDIDATE_GATES_SCHEMA_PATH = ROOT / "schemas/research-candidate-gates.schema.json"
SELECTION_SCHEMA_PATH = ROOT / "schemas/research-selection.schema.json"
CHILD_QUALITY_GATES_SCHEMA_PATH = ROOT / "schemas/child-quality-gates.schema.json"
RESEARCH_PROVENANCE_SCHEMA_PATH = ROOT / "schemas/research-provenance.schema.json"
V12_E2E_SCHEMA_PATH = ROOT / "schemas/v12-e2e.schema.json"
PRODUCTION_EXCHANGE_SCHEMA_PATH = ROOT / "schemas/production-exchange-evidence.schema.json"
PRODUCTION_EXCHANGE_E2E_SCHEMA_PATH = ROOT / "schemas/production-exchange-e2e.schema.json"
STARTUP_POLICY_PATH = ROOT / "config/startup-policy.yaml"
STARTUP_REPORT_SCHEMA_PATH = ROOT / "schemas/startup-report.schema.json"
DRIVE_LIVE_SCHEMA_PATH = ROOT / "schemas/drive-live-evidence.schema.json"
GITHUB_SANDBOX_LIVE_SCHEMA_PATH = ROOT / "schemas/github-sandbox-live-evidence.schema.json"
GITHUB_SANDBOX_LIVE_POLICY_PATH = ROOT / "config/github-sandbox-live-policy.yaml"
DRIVE_LIVE_POLICY_PATH = ROOT / "config/drive-live-policy.yaml"
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
    "schemas/research-execution-boundary.schema.json",
    "config/research-execution-boundary.yaml",
    "tools/v12_boundary.py",
    "schemas/transformation-rule.schema.json",
    "config/transformation-rules.yaml",
    "tools/transformation_rules.py",
    "schemas/research-candidate.schema.json",
    "tools/candidate_space.py",
    "schemas/research-candidate-gates.schema.json",
    "tools/candidate_gates.py",
    "schemas/research-selection.schema.json",
    "tools/candidate_selection.py",
    "schemas/child-quality-gates.schema.json",
    "tools/child_quality_gates.py",
    "schemas/research-provenance.schema.json",
    "tools/proposition_provenance.py",
    "schemas/v12-e2e.schema.json",
    "schemas/production-exchange-evidence.schema.json",
    "schemas/production-exchange-e2e.schema.json",
    "tools/production_exchange.py",
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
    "tools/agent_ui.py",
    "tools/initial_operations_e2e.py",
    "execution/task-queue.yaml",
    "execution/state.yaml",
    "execution/handoff.md",
    "docs/20260811-agentic-art-orchestration-system-design-specification.md",
    "docs/20260811-agentic-art-orchestration-repository-execution-plan.md",
    "docs/interaction-improvement-runbook.md",
    "docs/agent-ui-runbook.md",
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


def _source_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_safe_relative_path(value) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        return False
    parts = value.replace("\\", "/").split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def validate_manifest(data: dict, source: str = "config/repositories.yaml") -> list[str]:
    errors: list[str] = []
    schema = load_json(MANIFEST_SCHEMA_PATH)
    for schema_error in _schema_errors(data, schema):
        errors.append(f"{source}: {schema_error}; remediation: correct the manifest field")

    if not isinstance(data, dict):
        return errors
    repositories = data.get("repositories")
    if not isinstance(repositories, list):
        return errors
    if len(repositories) < len(CORE_REPOSITORY_IDS):
        errors.append(
            f"{source}: expected at least {len(CORE_REPOSITORY_IDS)} repositories; "
            "remediation: retain the four core repositories and append new repositories through the manifest"
        )

    seen: dict[str, set[str]] = {
        "id": set(),
        "path": set(),
        "full_name": set(),
        "authority": set(),
    }
    role_counts: dict[str, int] = {}
    for index, repo in enumerate(repositories):
        prefix = f"{source}: repositories[{index}]"
        if not isinstance(repo, dict):
            continue
        for field in seen:
            value = repo.get(field)
            if isinstance(value, str):
                if value in seen[field]:
                    errors.append(
                        f"{prefix}.{field}: duplicate {field} ownership {value!r}; "
                        "remediation: assign unique repository ownership metadata"
                    )
                seen[field].add(value)

        role = repo.get("role")
        if isinstance(role, str):
            role_counts[role] = role_counts.get(role, 0) + 1
        if role not in ROLES:
            errors.append(
                f"{prefix}.role: unknown role {role!r}; "
                f"remediation: use one of {sorted(ROLES)!r}"
            )

        if not SHA40.fullmatch(str(repo.get("observed_commit", ""))):
            errors.append(
                f"{prefix}.observed_commit: expected lowercase 40-character SHA; "
                "remediation: record the complete immutable source commit"
            )
        if not _is_safe_relative_path(repo.get("path")):
            errors.append(
                f"{prefix}.path: must be a safe relative workspace path; "
                "remediation: remove absolute paths and . or .. segments"
            )
        full_name = repo.get("full_name")
        url = repo.get("url")
        if isinstance(full_name, str) and isinstance(url, str):
            expected_url = f"https://github.com/{full_name}.git"
            if url != expected_url:
                errors.append(
                    f"{prefix}.url: must match full_name as {expected_url!r}; "
                    "remediation: correct the HTTPS GitHub clone URL"
                )
        requirement_ssot = repo.get("requirement_ssot")
        if isinstance(full_name, str) and isinstance(requirement_ssot, str):
            expected_prefix = f"https://github.com/{full_name}/issues/"
            if not requirement_ssot.startswith(expected_prefix):
                errors.append(
                    f"{prefix}.requirement_ssot: must belong to {full_name!r}; "
                    "remediation: point to the authoritative Issue in the same repository"
                )

        contract_fields = [
            field for field in ("export_contract", "import_contract", "exchange_contracts")
            if field in repo
        ]
        if len(contract_fields) == 1:
            contract_field = contract_fields[0]
            contract = repo.get(contract_field)
            if contract_field == "exchange_contracts":
                imports = contract.get("imports", []) if isinstance(contract, dict) else []
                exports = contract.get("exports", []) if isinstance(contract, dict) else []
                unknown = sorted((set(imports) | set(exports)) - EXCHANGE_CONTRACTS)
                if unknown:
                    errors.append(
                        f"{prefix}.exchange_contracts: unknown contracts {unknown!r}; "
                        f"remediation: use only registered exchange contracts {sorted(EXCHANGE_CONTRACTS)!r}"
                    )
                if role != "control-plane-extension":
                    errors.append(
                        f"{prefix}: exchange_contracts require control-plane-extension role; "
                        "remediation: use the bidirectional runtime role for non-signal boundaries"
                    )
                if set(imports) != {"production-handoff/v1"} or set(exports) != {"production-result/v1"}:
                    errors.append(
                        f"{prefix}.exchange_contracts: production runtime must import production-handoff/v1 "
                        "and export production-result/v1; remediation: preserve the Research/Production boundary"
                    )
            elif contract not in CONTRACTS:
                errors.append(
                    f"{prefix}.{contract_field}: unknown contract {contract!r}; "
                    f"remediation: use one of {sorted(CONTRACTS)!r}"
                )
            if role == "input-kb" and contract_field != "export_contract":
                errors.append(
                    f"{prefix}: input-kb must export a contract; "
                    "remediation: use export_contract"
                )
            if role == "consumer-runtime" and contract_field != "import_contract":
                errors.append(
                    f"{prefix}: consumer-runtime must import a contract; "
                    "remediation: use import_contract"
                )

        quality_gates = repo.get("quality_gates")
        if isinstance(quality_gates, list):
            for gate_index, command in enumerate(quality_gates):
                if not isinstance(command, str) or not command.strip():
                    errors.append(
                        f"{prefix}.quality_gates[{gate_index}]: command must be non-empty; "
                        "remediation: declare one executable quality-gate command"
                    )
                elif any(token in command for token in COMMAND_FORBIDDEN_TOKENS):
                    errors.append(
                        f"{prefix}.quality_gates[{gate_index}]: command contains shell control syntax; "
                        "remediation: split it into a separate non-shell quality-gate command"
                    )

        profile = repo.get("knowledge_profile")
        if isinstance(profile, dict):
            known_profile_owners = {
                item.get("id")
                for item in repositories
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            } | {"agentic-art-orchestration"}
            feedback_owner = profile.get("feedback_owner")
            if feedback_owner not in known_profile_owners:
                errors.append(
                    f"{prefix}.knowledge_profile.feedback_owner: unknown repository {feedback_owner!r}; "
                    "remediation: route feedback to a declared repository or the parent control plane"
                )

            forbidden_data = profile.get("forbidden_data")
            if isinstance(forbidden_data, list):
                missing_forbidden = sorted(REQUIRED_PROFILE_FORBIDDEN_DATA - set(forbidden_data))
                if missing_forbidden:
                    errors.append(
                        f"{prefix}.knowledge_profile.forbidden_data: missing baseline classes {missing_forbidden!r}; "
                        "remediation: keep the aggregate privacy and credential boundary explicit"
                    )

            evidence_rules = profile.get("evidence_rules")
            if isinstance(evidence_rules, dict) and evidence_rules.get("requires_locator") is not True:
                errors.append(
                    f"{prefix}.knowledge_profile.evidence_rules.requires_locator: must be true; "
                    "remediation: require an opaque or repository-local evidence locator"
                )

            write_scope = profile.get("write_scope")
            if isinstance(write_scope, dict):
                allowed_paths = write_scope.get("allowed_paths")
                if isinstance(allowed_paths, list):
                    for path_index, path in enumerate(allowed_paths):
                        if not _is_safe_relative_path(path):
                            errors.append(
                                f"{prefix}.knowledge_profile.write_scope.allowed_paths[{path_index}]: unsafe path; "
                                "remediation: use a relative path without ., .., or an absolute prefix"
                            )

            entry_points = profile.get("retrieval_entry_points")
            if isinstance(entry_points, list):
                for point_index, point in enumerate(entry_points):
                    if not isinstance(point, dict):
                        continue
                    kind = point.get("kind")
                    locator = point.get("locator")
                    if kind in {"file", "directory", "command"} and not _is_safe_relative_path(locator):
                        errors.append(
                            f"{prefix}.knowledge_profile.retrieval_entry_points[{point_index}].locator: unsafe local locator; "
                            "remediation: use a safe relative repository path"
                        )

    missing_core = sorted(CORE_REPOSITORY_IDS - seen["id"])
    if missing_core:
        errors.append(
            f"{source}: missing core repository IDs {missing_core!r}; "
            "remediation: preserve the core repositories and add new entries instead of replacing them"
        )
    if role_counts.get("input-kb", 0) < 3 or role_counts.get("consumer-runtime", 0) < 1:
        errors.append(
            f"{source}: role ownership requires at least 3 input-kb and 1 consumer-runtime; "
            "remediation: preserve the core role assignments and declare an explicit role for additions"
        )
    return errors


def _known_input_repository_ids() -> set[str]:
    manifest = load_yaml(MANIFEST_PATH)
    repositories = manifest.get("repositories", []) if isinstance(manifest, dict) else []
    return {
        repo.get("id")
        for repo in repositories
        if isinstance(repo, dict) and repo.get("role") == "input-kb"
    }


def _known_repository_ids() -> set[str]:
    manifest = load_yaml(MANIFEST_PATH)
    repositories = manifest.get("repositories", []) if isinstance(manifest, dict) else []
    return {
        repo.get("id")
        for repo in repositories
        if isinstance(repo, dict) and isinstance(repo.get("id"), str)
    }


def _signal_error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def validate_research_execution_boundary(data: dict, source: str = "research-execution-boundary") -> list[str]:
    """Validate the metadata-only v1.2 worker and authority boundary."""
    errors: list[str] = []
    schema = load_json(V12_BOUNDARY_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the v1.2 boundary field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    def require_exact_set(path: str, value: object, expected: set[str], label: str) -> None:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return
        actual = set(value)
        if actual != expected:
            errors.append(
                _signal_error(
                    source,
                    f"{path} must define {label} exactly; missing={sorted(expected - actual)!r}, unexpected={sorted(actual - expected)!r}",
                    f"use the v1.2 boundary vocabulary for {label}",
                )
            )

    input_contract = data.get("input_contract")
    if isinstance(input_contract, dict):
        require_exact_set(
            "input_contract.accepted_signal_kinds",
            input_contract.get("accepted_signal_kinds"),
            {"self", "art-history", "marketing"},
            "accepted normalized signal kinds",
        )
        require_exact_set(
            "input_contract.required_fields",
            input_contract.get("required_fields"),
            {
                "contract_version",
                "signal_id",
                "signal_kind",
                "source",
                "statement",
                "evidence_refs",
                "certainty",
                "unknowns",
                "constraints",
                "validity",
                "freshness",
                "adapter",
                "generated_at",
            },
            "normalized signal envelope fields",
        )

    source_requirements = data.get("source_requirements")
    if isinstance(source_requirements, dict):
        require_exact_set(
            "source_requirements.required_fields",
            source_requirements.get("required_fields"),
            {"repository", "commit", "entity_ids", "locators"},
            "source provenance fields",
        )

    worker_policy = data.get("worker_policy")
    if isinstance(worker_policy, dict):
        allowed = worker_policy.get("allowed_operations")
        forbidden = worker_policy.get("forbidden_operations")
        require_exact_set(
            "worker_policy.allowed_operations",
            allowed,
            {"retrieve", "normalize", "classify", "match", "execute", "verify"},
            "allowed worker operations",
        )
        require_exact_set(
            "worker_policy.forbidden_operations",
            forbidden,
            {
                "invent",
                "free_form_ideation",
                "open_ended_artistic_synthesis",
                "add_unproven_concept",
                "alter_source_provenance",
                "bypass_gate",
            },
            "forbidden worker operations",
        )
        if isinstance(allowed, list) and isinstance(forbidden, list):
            overlap = sorted(set(allowed) & set(forbidden))
            if overlap:
                errors.append(
                    _signal_error(
                        source,
                        f"worker operation vocabularies overlap: {overlap!r}",
                        "keep allowed execution operations disjoint from forbidden artistic or provenance mutations",
                    )
                )

    child_authority = data.get("child_authority")
    if isinstance(child_authority, dict):
        require_exact_set(
            "child_authority.quality_gate_statuses",
            child_authority.get("quality_gate_statuses"),
            {"NOT_RUN", "PASSED", "FAILED", "BLOCKED"},
            "child quality gate statuses",
        )

    output_policy = data.get("output_policy")
    if isinstance(output_policy, dict):
        require_exact_set(
            "output_policy.required_provenance",
            output_policy.get("required_provenance"),
            {"signal_id", "rule_id", "source_repository", "source_commit", "evidence_locator"},
            "proposition provenance fields",
        )
    return errors


def validate_transformation_rule_registry(data: dict, source: str = "transformation-rules") -> list[str]:
    """Validate finite rule composition without authorizing free-form synthesis."""
    errors: list[str] = []
    schema = load_json(TRANSFORMATION_RULE_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the transformation-rule field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors
    rules = data.get("rules")
    if not isinstance(rules, list):
        return errors

    expected_kinds = {"self", "art-history", "marketing"}
    expected_constraints = {"require_all_inputs", "require_source_provenance", "no_unproven_concepts"}
    expected_rejections = {"missing-required-signal", "unknown-attribute", "missing-provenance", "constraint-failure"}
    allowed_attributes = {
        "self": {"tensions", "recurring_patterns", "seeks", "protects", "avoids", "traits", "states", "contexts"},
        "art-history": {"relations", "canonical_graph_locator", "entity_kind", "time", "geo"},
        "marketing": {"stage", "freshness", "vendor_interest", "counterevidence", "prediction_status"},
    }
    seen_rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        prefix = f"rules[{index}]"
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("rule_id")
        if isinstance(rule_id, str):
            if rule_id in seen_rule_ids:
                errors.append(_signal_error(source, f"duplicate rule_id {rule_id!r}", "give every transformation rule a unique stable ID"))
            seen_rule_ids.add(rule_id)

        required_kinds = rule.get("required_signal_kinds")
        if isinstance(required_kinds, list) and set(required_kinds) != expected_kinds:
            errors.append(
                _signal_error(
                    source,
                    f"{prefix}.required_signal_kinds must include each normalized signal kind exactly",
                    "require self, art-history, and marketing inputs before composing a proposition",
                )
            )

        bindings = rule.get("attribute_bindings")
        if isinstance(bindings, dict):
            for kind, values in bindings.items():
                if kind not in allowed_attributes or not isinstance(values, list):
                    continue
                unknown = sorted(set(values) - allowed_attributes[kind])
                if unknown:
                    errors.append(
                        _signal_error(
                            source,
                            f"{prefix}.attribute_bindings.{kind} contains undeclared attributes {unknown!r}",
                            "bind only attributes exposed by the normalized signal contract",
                        )
                    )

        composition = rule.get("composition")
        if isinstance(composition, dict):
            slots = composition.get("slots")
            if isinstance(slots, dict) and isinstance(bindings, dict):
                for slot_name, slot in slots.items():
                    if not isinstance(slot, dict):
                        continue
                    kind = slot.get("signal_kind")
                    attribute = slot.get("attribute")
                    if kind in allowed_attributes and isinstance(attribute, str):
                        bound = bindings.get(kind, [])
                        if attribute not in bound:
                            errors.append(
                                _signal_error(
                                    source,
                                    f"{prefix}.composition.slots.{slot_name} references unbound attribute {attribute!r}",
                                    "select a declared attribute from the rule binding for that signal kind",
                                )
                            )
                slot_kinds = {
                    slot.get("signal_kind")
                    for slot in slots.values()
                    if isinstance(slot, dict)
                }
                # A rule may add slots beyond the three, so require coverage rather than equality.
                if not expected_kinds <= slot_kinds:
                    errors.append(
                        _signal_error(
                            source,
                            f"{prefix}.composition.slots must cover all signal kinds; observed {sorted(slot_kinds)!r}",
                            "declare one explicit composition slot for self, art-history, and marketing",
                        )
                    )
            template = composition.get("template")
            # The template is no longer a fixed sentence, so the registry checks that
            # every slot it declares is actually spent. An unused slot means the rule
            # binds a signal it never says anything with.
            if isinstance(slots, dict) and isinstance(template, str):
                unused = sorted(name for name in slots if "{" + str(name) + "}" not in template)
                if unused:
                    errors.append(
                        _signal_error(
                            source,
                            f"{prefix}.composition.template does not use declared slots {unused!r}",
                            "reference every declared slot in the template, or remove the slot",
                        )
                    )

        constraints = rule.get("constraints")
        if isinstance(constraints, list) and set(constraints) != expected_constraints:
            errors.append(
                _signal_error(
                    source,
                    f"{prefix}.constraints must preserve the finite safety constraints",
                    "require all inputs, source provenance, and no unproven concepts",
                )
            )
        rejection_reasons = rule.get("rejection_reasons")
        if isinstance(rejection_reasons, list) and set(rejection_reasons) != expected_rejections:
            errors.append(
                _signal_error(
                    source,
                    f"{prefix}.rejection_reasons must preserve deterministic rejection vocabulary",
                    "record missing inputs, unknown attributes, provenance, and constraint failures",
                )
            )
    return errors


def validate_startup_contract(
    policy: dict | None = None,
    report_schema: dict | None = None,
    policy_source: str = "config/startup-policy.yaml",
    schema_source: str = "schemas/startup-report.schema.json",
) -> list[str]:
    """Validate the versioned, privacy-safe startup contract before runtime exists."""
    policy = policy if policy is not None else load_yaml(STARTUP_POLICY_PATH)
    report_schema = report_schema if report_schema is not None else load_json(STARTUP_REPORT_SCHEMA_PATH)
    errors: list[str] = []

    def error(message: str, remediation: str) -> None:
        errors.append(_signal_error(policy_source, message, remediation))

    if not isinstance(policy, dict):
        error("startup policy must be an object", "restore config/startup-policy.yaml as a mapping")
        return errors
    if policy.get("version") != 1:
        error("version must be 1", "set the startup policy version to the supported major contract")
    if policy.get("contract_version") != "orchestration-startup/v1":
        error("contract_version must be orchestration-startup/v1", "keep the startup policy on the v1 contract")
    if policy.get("report_contract_version") != "startup-report/v1":
        error("report_contract_version must be startup-report/v1", "point the policy at the versioned startup report")
    if policy.get("profile") != "initial-operations":
        error("profile must be initial-operations", "use the bounded initial operations profile")
    if policy.get("agent_clients") != ["Codex", "Claude Code"]:
        error("agent_clients must expose exactly Codex and Claude Code", "declare only the supported conversation clients")

    startup = policy.get("startup")
    if not isinstance(startup, dict):
        error("startup must be an object", "declare the startup command, reuse policy, and ordered preflight")
    else:
        if startup.get("command") != "python3 tools/startup.py --check":
            error("startup.command is not the repository startup command", "use python3 tools/startup.py --check")
        reuse = startup.get("reuse")
        if not isinstance(reuse, dict) or reuse.get("same_process") is not True or reuse.get("expiry_minutes") != 60 or reuse.get("new_process_requires_rerun") is not True:
            error("startup reuse policy is unsafe or incomplete", "rerun startup for each new process and expire reports after 60 minutes")
        steps = startup.get("ordered_preflight")
        observed_steps = [step.get("id") for step in steps] if isinstance(steps, list) and all(isinstance(step, dict) for step in steps) else []
        if observed_steps != STARTUP_STEPS:
            error(f"ordered_preflight must be {STARTUP_STEPS!r}", "preserve the startup safety order")
        for step in steps if isinstance(steps, list) else []:
            if not isinstance(step, dict):
                continue
            if step.get("mode") != "read_only":
                error(f"preflight step {step.get('id')!r} is not read-only", "startup preflight must not mutate repositories or external systems")

    remote = policy.get("remote_head_observation")
    if not isinstance(remote, dict):
        error("remote_head_observation must be an object", "declare read-only remote default-branch observation")
    else:
        if remote.get("mode") != "read_only":
            error("remote head observation must be read-only", "observe remote heads without checkout, pull, or pin updates")
        if remote.get("branch_source") != "manifest.default_branch":
            error("remote head branch_source is not manifest.default_branch", "observe each repository's declared default branch")
        if remote.get("compare_targets") != ["observed_commit", "qualified_snapshot"]:
            error("remote head compare_targets are incomplete", "compare observed heads with both the manifest pin and qualified snapshot")
        if remote.get("difference_result") != "update_candidate" or remote.get("unavailable_result") != "observation_unavailable":
            error("remote head non-clean outcomes are not explicit", "record drift and observation outages without normalizing them")
        if remote.get("mutation_operations") != []:
            error("remote head observation declares mutation operations", "keep startup remote observation create-free and checkout-free")

    pinned = policy.get("pinned_workspace")
    if not isinstance(pinned, dict):
        error("pinned_workspace must be an object", "declare the qualified pin source and workspace guard")
    else:
        if pinned.get("pin_source") != "manifest.observed_commit" or pinned.get("use_source") != "qualified_snapshot":
            error("pinned workspace pin sources are inconsistent", "observe the manifest pin but use only the qualified snapshot")
        if pinned.get("guard_checks") != ["dirty", "untracked", "detached", "unpushed", "behind", "diverged", "remote_mismatch"]:
            error("pinned workspace guard checks are incomplete", "block unsafe local workspaces before knowledge use")
        if pinned.get("failure_result") != "BLOCKED" or pinned.get("mutation_operations") != []:
            error("pinned workspace guard does not fail closed", "block unsafe workspaces and perform no recovery mutation")

    outcomes = policy.get("outcomes")
    if not isinstance(outcomes, dict) or set(outcomes) != STARTUP_OUTCOMES:
        error("outcomes must define READY, READY_WITH_FINDINGS, and BLOCKED", "declare all startup terminal states")
    else:
        expected_answers = {
            "READY": "qualified_read_and_approved_create_only",
            "READY_WITH_FINDINGS": "qualified_read_only_with_constraints",
            "BLOCKED": "stop_affected_capabilities",
        }
        for outcome, answer_policy in expected_answers.items():
            if outcomes.get(outcome, {}).get("answer_policy") != answer_policy:
                error(f"outcomes.{outcome}.answer_policy is unsafe", "restrict capabilities according to the startup decision")

    capabilities = policy.get("capabilities")
    capability_map = {
        item.get("id"): item for item in capabilities
    } if isinstance(capabilities, list) and all(isinstance(item, dict) for item in capabilities) else {}
    if list(capability_map) != STARTUP_CAPABILITIES:
        error(f"capabilities must be exactly {STARTUP_CAPABILITIES!r}", "expose only the initial profile capability matrix")
    expected_capabilities = {
        "qualified_knowledge_read": ("read", ["READY", "READY_WITH_FINDINGS"]),
        "evidence_trace_read": ("read", ["READY", "READY_WITH_FINDINGS"]),
        "feedback_capture": ("local_record", ["READY", "READY_WITH_FINDINGS"]),
        "audit_observation": ("read", ["READY", "READY_WITH_FINDINGS"]),
        "drive_create": ("external_create", ["READY"]),
        "github_issue_create": ("external_create", ["READY"]),
        "child_repository_mutation": ("mutation", []),
        "drive_update_delete_share": ("mutation", []),
        "github_issue_update_close_delete_comment_label": ("mutation", []),
        "branch_commit_pull_request_merge_release": ("mutation", []),
    }
    for capability, (expected_class, allowed_outcomes) in expected_capabilities.items():
        item = capability_map.get(capability)
        if not isinstance(item, dict) or item.get("class") != expected_class or item.get("allowed_outcomes") != allowed_outcomes:
            error(f"capabilities.{capability} violates the initial profile matrix", "allow only read and explicitly approved create-only operations")

    boundary = policy.get("data_boundary")
    if not isinstance(boundary, dict):
        error("data_boundary must be an object", "declare report allowlist and forbidden data classes")
    else:
        expected_allowed = {
            "run_id", "generated_at", "parent_commit", "qualified_commit", "remote_observed_commit",
            "observation_timestamp", "drift", "workspace_guard", "finding_code", "capability", "remediation", "issue_candidates",
        }
        if set(boundary.get("report_allowed_fields", [])) != expected_allowed:
            error("data_boundary.report_allowed_fields is not the minimal report allowlist", "store metadata and decisions only")
        if not set(STARTUP_FORBIDDEN_FIELDS).issubset(set(boundary.get("forbidden_fields", []))):
            error("data_boundary.forbidden_fields omits a protected class", "forbid raw conversation, credentials, direct identifiers, and restricted data")
        expected_guards = {
            "raw_conversation_stored": False,
            "credentials_stored": False,
            "raw_remote_response_stored": False,
            "drive_content_stored": False,
            "direct_identifiers_stored": False,
        }
        if boundary.get("boolean_guards") != expected_guards:
            error("data_boundary.boolean_guards must all be false", "prove that startup reports do not retain protected content")

    security = policy.get("security")
    if not isinstance(security, dict) or set(security.get("critical_findings", [])) != {"credential", "PRIVATE_RAW", "RESTRICTED", "consent_violation", "schema_major_mismatch"} or set(security.get("noncritical_findings", [])) != {"remote_update_candidate", "audit_finding", "remote_observation_unavailable"} or security.get("critical_result") != "BLOCKED" or security.get("noncritical_result") != "READY_WITH_FINDINGS":
        error("security severity mapping is incomplete", "map critical/privacy findings to BLOCKED and noncritical findings to READY_WITH_FINDINGS")

    if not isinstance(report_schema, dict):
        errors.append(_signal_error(schema_source, "startup report schema must be an object", "restore schemas/startup-report.schema.json"))
    else:
        if report_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(_signal_error(schema_source, "$schema must be Draft 2020-12", "use the repository schema dialect"))
        if report_schema.get("$id", "").endswith("/schemas/startup-report.schema.json") is False:
            errors.append(_signal_error(schema_source, "$id must identify the startup report schema", "keep the schema ID stable"))
        schema_properties = report_schema.get("properties", {})
        if set(report_schema.get("required", [])) != {
            "contract_version", "run_id", "generated_at", "profile", "agent_client", "status", "parent_commit",
            "ordered_steps", "repositories", "workspace_guard", "findings", "issue_candidates", "capabilities", "remediation", "privacy", "remote_operations",
        }:
            errors.append(_signal_error(schema_source, "required report fields are incomplete or expanded", "keep the report metadata-only and versioned"))
        if report_schema.get("additionalProperties") is not False or not isinstance(schema_properties, dict):
            errors.append(_signal_error(schema_source, "report schema must reject unknown fields", "set additionalProperties to false"))
        for forbidden in STARTUP_FORBIDDEN_FIELDS:
            if forbidden in schema_properties:
                errors.append(_signal_error(schema_source, f"report schema exposes forbidden field {forbidden!r}", "remove protected content from the startup report"))

    return errors


def validate_issue_delivery_contract(
    policy: dict | None = None,
    report_schema: dict | None = None,
    manifest: dict | None = None,
    policy_source: str = "config/issue-delivery-policy.yaml",
    schema_source: str = "schemas/github-issue-delivery.schema.json",
) -> list[str]:
    """Validate the allowlist and create-only GitHub Issue delivery envelope."""
    policy = policy if policy is not None else load_yaml(ISSUE_DELIVERY_POLICY_PATH)
    report_schema = report_schema if report_schema is not None else load_json(ISSUE_DELIVERY_SCHEMA_PATH)
    manifest = manifest if manifest is not None else load_yaml(MANIFEST_PATH)
    errors: list[str] = []

    def error(message: str, remediation: str) -> None:
        errors.append(_signal_error(policy_source, message, remediation))

    if not isinstance(policy, dict):
        error("Issue delivery policy must be an object", "restore config/issue-delivery-policy.yaml as a mapping")
        return errors
    if policy.get("version") != 1 or policy.get("contract_version") != "github-issue-delivery/v1":
        error("Issue delivery policy version is unsupported", "keep the create-only delivery policy on v1")
    if policy.get("parent_repository") != "agentic-art-orchestration":
        error("parent_repository must be the orchestration repository", "keep the authoritative parent explicit")
    if policy.get("allowed_operations") != ["READ", "CREATE"]:
        error("allowed_operations must be exactly READ and CREATE", "do not authorize Issue mutation or implementation")
    forbidden = policy.get("forbidden_operations")
    expected_forbidden = {"UPDATE", "CLOSE", "DELETE", "COMMENT", "LABEL", "IMPLEMENT", "BRANCH", "COMMIT", "PULL_REQUEST", "MERGE", "RELEASE"}
    if not isinstance(forbidden, list) or set(forbidden) != expected_forbidden:
        error("forbidden_operations is incomplete or expanded", "keep Issue delivery create-only and human-gated")
    if policy.get("max_creates_per_deduplication_key") != 1 or policy.get("human_confirmation_required") is not True:
        error("Issue create idempotency or human confirmation is unsafe", "allow at most one create per key and require confirmation")

    manifest_ids = {
        repository.get("id"): repository.get("full_name")
        for repository in manifest.get("repositories", [])
        if isinstance(repository, dict)
    } if isinstance(manifest, dict) else {}
    expected_allowlist = {"agentic-art-orchestration": "masa-san-jp/agentic-art-orchestration", **manifest_ids}
    entries = policy.get("allowlisted_repositories")
    observed_allowlist = {
        entry.get("id"): entry.get("full_name")
        for entry in entries
        if isinstance(entry, dict)
    } if isinstance(entries, list) else {}
    if isinstance(entries, list):
        entry_ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
        entry_full_names = [entry.get("full_name") for entry in entries if isinstance(entry, dict)]
        if len(entry_ids) != len(set(entry_ids)) or len(entry_full_names) != len(set(entry_full_names)):
            error("allowlisted_repositories contains duplicate IDs or full names", "retain one unique authority entry per repository")
    if observed_allowlist != expected_allowlist:
        error("allowlisted_repositories does not match the manifest and parent", "allow only declared authoritative repositories")

    if not isinstance(report_schema, dict):
        errors.append(_signal_error(schema_source, "Issue delivery schema must be an object", "restore schemas/github-issue-delivery.schema.json"))
        return errors
    if report_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or report_schema.get("additionalProperties") is not False:
        errors.append(_signal_error(schema_source, "Issue delivery schema must be closed Draft 2020-12", "reject fields outside the create-only envelope"))
    if set(report_schema.get("required", [])) != {"contract_version", "delivery_run_id", "mode", "generated_at", "status", "records", "remote_operations"}:
        errors.append(_signal_error(schema_source, "Issue delivery required fields are incomplete or expanded", "keep the delivery evidence envelope minimal"))
    properties = report_schema.get("properties", {})
    if properties.get("mode", {}).get("enum") != ["PLAN", "LIVE"]:
        errors.append(_signal_error(schema_source, "Issue delivery mode must expose PLAN and LIVE", "separate networkless planning from explicitly confirmed live delivery"))
    record = report_schema.get("$defs", {}).get("record", {})
    if record.get("properties", {}).get("operation", {}).get("enum") != ["NONE", "READ", "CREATE", "REUSE"]:
        errors.append(_signal_error(schema_source, "Issue record operation vocabulary is unsafe", "allow only read, create, and existing Issue reuse"))
    remote = report_schema.get("$defs", {}).get("remote_operation", {})
    if set(remote.get("properties", {}).get("operation", {}).get("enum", [])) != {"READ", "CREATE", "REUSE"}:
        errors.append(_signal_error(schema_source, "remote operation vocabulary is unsafe", "exclude update, close, delete, comment, and label operations"))
    return errors


def validate_drive_live_contract(
    policy: dict | None = None,
    evidence_schema: dict | None = None,
    policy_source: str = "config/drive-live-policy.yaml",
    schema_source: str = "schemas/drive-live-evidence.schema.json",
) -> list[str]:
    """Validate the approved-folder, create/read-only Drive live boundary."""
    policy = policy if policy is not None else load_yaml(DRIVE_LIVE_POLICY_PATH)
    evidence_schema = evidence_schema if evidence_schema is not None else load_json(DRIVE_LIVE_SCHEMA_PATH)
    errors: list[str] = []

    def error(source: str, message: str, remediation: str) -> None:
        errors.append(_signal_error(source, message, remediation))

    if not isinstance(policy, dict):
        error(policy_source, "Drive live policy must be an object", "restore the provider-neutral create/read policy")
        return errors
    if policy.get("version") != 1 or policy.get("contract_version") != "drive-live/v1":
        error(policy_source, "Drive live policy version is unsupported", "keep the Drive live boundary on v1")
    if policy.get("provider") != "google-drive":
        error(policy_source, "Drive live provider must be google-drive", "keep the external artifact provider explicit")
    approved_folder = policy.get("approved_folder")
    if not isinstance(approved_folder, dict):
        error(policy_source, "approved_folder must be an object", "require an explicit approved folder ID or environment variable")
    else:
        env_name = approved_folder.get("id_env_var")
        fixture_id = approved_folder.get("fixture_id")
        if not isinstance(env_name, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", env_name) is None:
            error(policy_source, "approved_folder.id_env_var is invalid", "use an uppercase environment variable name")
        if not isinstance(fixture_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", fixture_id) is None:
            error(policy_source, "approved_folder.fixture_id is invalid", "use a stable offline fixture folder ID")
        credential_env_name = policy.get("credential_env_var")
        if not isinstance(credential_env_name, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", credential_env_name) is None:
            error(policy_source, "credential_env_var is invalid", "use an uppercase environment variable and keep the credential outside Git")
    credential_env = policy.get("credential_env_var")
    if not isinstance(credential_env, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", credential_env) is None:
        error(policy_source, "credential_env_var is invalid", "use an uppercase environment variable name and never commit its value")
    if policy.get("allowed_operations") != ["READ", "CREATE"]:
        error(policy_source, "allowed_operations must be exactly READ and CREATE", "exclude all Drive mutation beyond append-only CREATE")
    expected_forbidden = {"UPDATE", "OVERWRITE", "DELETE", "MOVE", "SHARE", "PERMISSION"}
    forbidden = policy.get("forbidden_operations")
    if not isinstance(forbidden, list) or set(forbidden) != expected_forbidden:
        error(policy_source, "forbidden_operations is incomplete or expanded", "retain the append-only Drive boundary")
    if policy.get("human_confirmation_required") is not True:
        error(policy_source, "human_confirmation_required must be true", "require explicit approval for live external CREATE")
    if policy.get("content_in_repository") is not False:
        error(policy_source, "content_in_repository must be false", "keep artifact bodies outside Git")
    if policy.get("response_loss_policy") != "search_by_idempotency_then_read_back":
        error(policy_source, "response_loss_policy is unsafe", "search by stable key before retrying a CREATE")

    if not isinstance(evidence_schema, dict):
        error(schema_source, "Drive live evidence schema must be an object", "restore schemas/drive-live-evidence.schema.json")
        return errors
    if evidence_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or evidence_schema.get("additionalProperties") is not False:
        error(schema_source, "Drive live evidence schema must be closed Draft 2020-12", "reject fields outside the metadata evidence envelope")
    expected_required = {"contract_version", "run_id", "mode", "status", "operation", "provider", "approved_folder_id_hash", "idempotency_key_hash", "content_hash", "artifact", "remote_operations"}
    if set(evidence_schema.get("required", [])) != expected_required:
        error(schema_source, "Drive live evidence required fields are incomplete or expanded", "keep the evidence envelope minimal and deterministic")
    properties = evidence_schema.get("properties", {})
    if properties.get("mode", {}).get("enum") != ["PLAN", "LIVE"]:
        error(schema_source, "Drive live mode must expose PLAN and LIVE", "separate offline planning from explicit live execution")
    remote = evidence_schema.get("$defs", {}).get("remote_operation", {})
    if set(remote.get("properties", {}).get("operation", {}).get("enum", [])) != {"READ", "CREATE"}:
        error(schema_source, "remote operation vocabulary is unsafe", "exclude update, overwrite, delete, move, share, and permission operations")
    return errors


def validate_github_sandbox_live_contract(
    policy: dict | None = None,
    evidence_schema: dict | None = None,
    manifest: dict | None = None,
    policy_source: str = "config/github-sandbox-live-policy.yaml",
    schema_source: str = "schemas/github-sandbox-live-evidence.schema.json",
) -> list[str]:
    """Validate the separately designated GitHub sandbox create-only lane."""
    policy = policy if policy is not None else load_yaml(GITHUB_SANDBOX_LIVE_POLICY_PATH)
    evidence_schema = evidence_schema if evidence_schema is not None else load_json(GITHUB_SANDBOX_LIVE_SCHEMA_PATH)
    manifest = manifest if manifest is not None else load_yaml(MANIFEST_PATH)
    errors: list[str] = []

    def error(source: str, message: str, remediation: str) -> None:
        errors.append(_signal_error(source, message, remediation))

    if not isinstance(policy, dict):
        error(policy_source, "GitHub sandbox live policy must be an object", "restore the dedicated create-only policy")
        return errors
    if policy.get("version") != 1 or policy.get("contract_version") != "github-sandbox-live/v1":
        error(policy_source, "GitHub sandbox live policy version is unsupported", "keep the dedicated sandbox lane on v1")
    if policy.get("provider") != "github":
        error(policy_source, "GitHub sandbox provider must be github", "keep the external Issue provider explicit")
    approved = policy.get("approved_repository")
    if not isinstance(approved, dict):
        error(policy_source, "approved_repository must be an object", "require an explicit repository environment variable and fixture ID")
    else:
        env_name = approved.get("id_env_var")
        fixture_id = approved.get("fixture_id")
        if not isinstance(env_name, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", env_name) is None:
            error(policy_source, "approved_repository.id_env_var is invalid", "use an uppercase environment variable name")
        if not isinstance(fixture_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", fixture_id) is None:
            error(policy_source, "approved_repository.fixture_id is invalid", "use a stable offline fixture ID")
    token_env_vars = policy.get("token_env_vars")
    if token_env_vars != ["GITHUB_TOKEN", "GH_TOKEN"]:
        error(policy_source, "token_env_vars must be GITHUB_TOKEN then GH_TOKEN", "accept credentials only from repo-external GitHub token variables")
    if policy.get("allowed_operations") != ["READ", "CREATE"]:
        error(policy_source, "allowed_operations must be exactly READ and CREATE", "exclude all Issue mutation beyond one append-only CREATE")
    expected_forbidden = {"UPDATE", "CLOSE", "DELETE", "COMMENT", "LABEL", "IMPLEMENT", "BRANCH", "COMMIT", "PULL_REQUEST", "MERGE", "RELEASE"}
    if set(policy.get("forbidden_operations", [])) != expected_forbidden:
        error(policy_source, "forbidden_operations is incomplete or expanded", "retain the create-only sandbox boundary")
    if policy.get("max_creates_per_idempotency_key") != 1 or policy.get("human_confirmation_required") is not True:
        error(policy_source, "sandbox create idempotency or human confirmation is unsafe", "allow one create per key and require explicit confirmation")
    if policy.get("existing_issue_mutation") is not False or policy.get("production_repositories_must_be_rejected") is not True:
        error(policy_source, "sandbox isolation flags are unsafe", "reject production repositories and never mutate existing Issues")
    retry = policy.get("post_create_search")
    if not isinstance(retry, dict):
        error(policy_source, "post_create_search must be an object", "bound eventual-consistency retries in the policy")
    else:
        if not isinstance(retry.get("max_attempts"), int) or not 1 <= retry["max_attempts"] <= 10:
            error(policy_source, "post_create_search.max_attempts is unsafe", "use a finite retry bound between 1 and 10")
        if not isinstance(retry.get("initial_delay_seconds"), (int, float)) or not 0 <= retry["initial_delay_seconds"] <= 60:
            error(policy_source, "post_create_search.initial_delay_seconds is unsafe", "use a non-negative bounded delay")
        if not isinstance(retry.get("backoff_multiplier"), (int, float)) or not 1 <= retry["backoff_multiplier"] <= 4:
            error(policy_source, "post_create_search.backoff_multiplier is unsafe", "use a finite multiplier between 1 and 4")
        if not isinstance(retry.get("max_delay_seconds"), (int, float)) or not 0 <= retry["max_delay_seconds"] <= 120:
            error(policy_source, "post_create_search.max_delay_seconds is unsafe", "use a bounded maximum delay")
        if isinstance(retry.get("initial_delay_seconds"), (int, float)) and isinstance(retry.get("max_delay_seconds"), (int, float)) and retry["initial_delay_seconds"] > retry["max_delay_seconds"]:
            error(policy_source, "post_create_search initial delay exceeds maximum", "keep the retry schedule monotonic")

    declared = {
        item.get("full_name")
        for item in manifest.get("repositories", [])
        if isinstance(item, dict) and isinstance(item.get("full_name"), str)
    } | {"masa-san-jp/agentic-art-orchestration"}
    if isinstance(approved, dict) and approved.get("fixture_id") in declared:
        error(policy_source, "fixture sandbox identifier overlaps a declared repository", "keep the fixture and production authorities separate")

    if not isinstance(evidence_schema, dict):
        error(schema_source, "GitHub sandbox evidence schema must be an object", "restore the closed metadata-only evidence schema")
        return errors
    if evidence_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or evidence_schema.get("additionalProperties") is not False:
        error(schema_source, "GitHub sandbox evidence schema must be closed Draft 2020-12", "reject fields outside the metadata-only envelope")
    expected_required = {"contract_version", "run_id", "mode", "status", "operation", "provider", "repository_id_hash", "idempotency_key_hash", "issue_id_hash", "remote_operations"}
    if set(evidence_schema.get("required", [])) != expected_required:
        error(schema_source, "GitHub sandbox evidence required fields are incomplete or expanded", "keep the evidence envelope minimal")
    properties = evidence_schema.get("properties", {})
    if properties.get("mode", {}).get("enum") != ["PLAN", "LIVE"]:
        error(schema_source, "GitHub sandbox mode must expose PLAN and LIVE", "separate planning from explicit live execution")
    remote = evidence_schema.get("$defs", {}).get("remote_operation", {})
    if set(remote.get("properties", {}).get("operation", {}).get("enum", [])) != {"READ", "CREATE", "REUSE"}:
        error(schema_source, "GitHub sandbox remote operation vocabulary is unsafe", "allow only search, create, and reuse")
    return errors


def validate_candidate_space(data: dict, source: str = "candidate-space") -> list[str]:
    """Validate candidate references and require every composition slot to be traceable."""
    errors: list[str] = []
    schema = load_json(CANDIDATE_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the research-candidate field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return errors
    if data.get("candidate_count") != len(candidates):
        errors.append(
            _signal_error(
                source,
                "candidate_count does not equal the number of candidates",
                "recompute the count from the complete deterministic candidate list",
            )
        )
    seen_candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        candidate_id = candidate.get("candidate_id")
        if candidate_id in seen_candidate_ids:
            errors.append(
                _signal_error(
                    source,
                    f"candidates[{index}] duplicates candidate_id {candidate_id!r}",
                    "retain one candidate per stable rule and signal combination",
                )
            )
        if isinstance(candidate_id, str):
            seen_candidate_ids.add(candidate_id)

        inputs = candidate.get("inputs")
        input_refs: dict[tuple[str, str, str], dict] = {}
        if isinstance(inputs, dict):
            for kind, refs in inputs.items():
                if not isinstance(refs, list):
                    continue
                for ref_index, ref in enumerate(refs):
                    if not isinstance(ref, dict):
                        continue
                    key = (kind, ref.get("signal_id"), ref.get("attribute"))
                    if key in input_refs:
                        errors.append(
                            _signal_error(
                                source,
                                f"candidates[{index}].inputs.{kind}[{ref_index}] duplicates signal/attribute reference",
                                "retain one provenance reference per selected signal attribute",
                            )
                        )
                    input_refs[key] = ref
                    if ref.get("signal_kind") != kind:
                        errors.append(
                            _signal_error(
                                source,
                                f"candidates[{index}].inputs.{kind}[{ref_index}] signal_kind is inconsistent",
                                "keep the input bucket aligned with the normalized signal kind",
                            )
                        )

        composition = candidate.get("composition")
        if isinstance(composition, dict):
            for slot_name, slot in composition.items():
                if not isinstance(slot, dict):
                    continue
                key = (slot.get("signal_kind"), slot.get("signal_id"), slot.get("attribute"))
                if key not in input_refs:
                    errors.append(
                        _signal_error(
                            source,
                            f"candidates[{index}].composition.{slot_name} is not traceable to inputs",
                            "reference a declared input signal and attribute in the same candidate",
                        )
                    )
                if isinstance(slot.get("signal_id"), str) and not any(
                    isinstance(ref, dict) and ref.get("signal_id") == slot["signal_id"]
                    for ref in input_refs.values()
                ):
                    errors.append(
                        _signal_error(
                            source,
                            f"candidates[{index}].composition.{slot_name} lost its signal ID",
                            "preserve the selected normalized signal ID through composition",
                        )
                    )
    return errors


def validate_candidate_gates(data: dict, source: str = "candidate-gates") -> list[str]:
    """Validate six explicit gate outcomes and their fail-closed status semantics."""
    errors: list[str] = []
    schema = load_json(CANDIDATE_GATES_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the research-candidate-gates field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    expected_gate_ids = {
        "personal-specificity",
        "historical-specificity",
        "contemporary-specificity",
        "provenance",
        "genericness",
        "counterfactual",
    }
    expected_reasons = {
        "personal-specificity": "missing-personal-signal",
        "historical-specificity": "missing-historical-signal",
        "contemporary-specificity": "missing-contemporary-signal",
        "provenance": "missing-provenance",
        "genericness": "generic-candidate",
        "counterfactual": "counterfactual-failure",
    }
    evaluations = data.get("evaluations")
    if not isinstance(evaluations, list):
        return errors
    seen_candidate_ids: set[str] = set()
    for index, evaluation in enumerate(evaluations):
        if not isinstance(evaluation, dict):
            continue
        candidate_id = evaluation.get("candidate_id")
        if candidate_id in seen_candidate_ids:
            errors.append(
                _signal_error(
                    source,
                    f"evaluations[{index}] duplicates candidate_id {candidate_id!r}",
                    "return exactly one gate evaluation per candidate",
                )
            )
        if isinstance(candidate_id, str):
            seen_candidate_ids.add(candidate_id)
        gates = evaluation.get("gates")
        if not isinstance(gates, list):
            continue
        observed_ids = [gate.get("gate_id") for gate in gates if isinstance(gate, dict)]
        if set(observed_ids) != expected_gate_ids or len(observed_ids) != len(expected_gate_ids):
            errors.append(
                _signal_error(
                    source,
                    f"evaluations[{index}].gates must contain each gate exactly once; observed {sorted(observed_ids)!r}",
                    "emit personal, historical, contemporary, provenance, genericness, and counterfactual gates",
                )
            )
        statuses: list[str] = []
        for gate_index, gate in enumerate(gates):
            if not isinstance(gate, dict):
                continue
            gate_id = gate.get("gate_id")
            status = gate.get("status")
            reason = gate.get("reason_code")
            if isinstance(status, str):
                statuses.append(status)
            if status == "PASS" and reason is not None:
                errors.append(
                    _signal_error(
                        source,
                        f"evaluations[{index}].gates[{gate_index}] PASS carries reason_code {reason!r}",
                        "set reason_code to null for a passing gate",
                    )
                )
            if status == "REJECT":
                if reason != expected_reasons.get(gate_id):
                    errors.append(
                        _signal_error(
                            source,
                            f"evaluations[{index}].gates[{gate_index}] has inconsistent reason_code",
                            "use the deterministic reason code assigned to the gate ID",
                        )
                    )
            if isinstance(gate.get("evidence"), list) and not gate["evidence"]:
                errors.append(
                    _signal_error(
                        source,
                        f"evaluations[{index}].gates[{gate_index}] has no evidence",
                        "retain source repository, commit, and evidence locators for every gate result",
                    )
                )
        expected_overall = "PASS" if statuses and all(status == "PASS" for status in statuses) else "REJECT"
        if evaluation.get("overall_status") != expected_overall:
            errors.append(
                _signal_error(
                    source,
                    f"evaluations[{index}].overall_status does not match gate statuses",
                    "derive overall PASS only when every explicit gate passes",
                )
            )
    return errors


def validate_selection(data: dict, source: str = "selection") -> list[str]:
    """Validate seeded selection ranks and ensure selected references retain provenance."""
    errors: list[str] = []
    schema = load_json(SELECTION_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the research-selection field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors
    selected = data.get("selected_candidates")
    if not isinstance(selected, list):
        return errors
    if data.get("selected_count") != len(selected):
        errors.append(
            _signal_error(
                source,
                "selected_count does not equal selected_candidates length",
                "derive selected_count from the emitted selection package",
            )
        )
    selection_limit = data.get("selection_limit")
    if isinstance(selection_limit, int) and isinstance(data.get("selected_count"), int) and data["selected_count"] > selection_limit:
        errors.append(
            _signal_error(
                source,
                "selected_count exceeds selection_limit",
                "return no more candidates than the requested selection limit",
            )
        )
    candidate_ids: set[str] = set()
    ranks: list[int] = []
    scores: set[str] = set()
    for index, candidate in enumerate(selected):
        if not isinstance(candidate, dict):
            continue
        candidate_id = candidate.get("candidate_id")
        if candidate_id in candidate_ids:
            errors.append(_signal_error(source, f"selected_candidates[{index}] duplicates candidate_id {candidate_id!r}", "select each candidate at most once"))
        if isinstance(candidate_id, str):
            candidate_ids.add(candidate_id)
        rank = candidate.get("rank")
        if isinstance(rank, int) and not isinstance(rank, bool):
            ranks.append(rank)
        score = candidate.get("selection_score")
        if isinstance(score, str):
            if score in scores:
                errors.append(_signal_error(source, f"selected_candidates[{index}] duplicates selection_score", "use the deterministic candidate score for each ranked candidate"))
            scores.add(score)
        inputs = candidate.get("inputs")
        input_refs: dict[tuple[str, str, str], dict] = {}
        if isinstance(inputs, dict):
            for kind, refs in inputs.items():
                if not isinstance(refs, list):
                    continue
                for ref in refs:
                    if not isinstance(ref, dict):
                        continue
                    input_refs[(kind, ref.get("signal_id"), ref.get("attribute"))] = ref
        composition = candidate.get("composition")
        if isinstance(composition, dict):
            for slot_name, slot in composition.items():
                if not isinstance(slot, dict):
                    continue
                key = (slot.get("signal_kind"), slot.get("signal_id"), slot.get("attribute"))
                if key not in input_refs:
                    errors.append(
                        _signal_error(
                            source,
                            f"selected_candidates[{index}].composition.{slot_name} is not traceable to inputs",
                            "preserve candidate composition references through selection",
                        )
                    )
    if ranks and sorted(ranks) != list(range(1, len(selected) + 1)):
        errors.append(_signal_error(source, "selection ranks are not contiguous from 1", "emit deterministic ranks in selection order"))
    return errors


def validate_child_quality_gates(data: dict, source: str = "child-quality-gates") -> list[str]:
    """Validate immutable child gate evidence and preserve stale/unknown/failed states."""
    errors: list[str] = []
    schema = load_json(CHILD_QUALITY_GATES_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the child-quality-gates field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors
    results = data.get("results")
    if not isinstance(results, list):
        return errors
    if data.get("repository_count") != len(results):
        errors.append(_signal_error(source, "repository_count does not equal results length", "derive the count from every manifest repository result"))
    seen: set[str] = set()
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        repository = result.get("repository")
        if repository in seen:
            errors.append(_signal_error(source, f"results[{index}] duplicates repository {repository!r}", "record one immutable gate result per repository"))
        if isinstance(repository, str):
            seen.add(repository)
        status = result.get("status")
        execution_mode = result.get("execution_mode")
        gates = result.get("gates")
        gate_statuses = [gate.get("status") for gate in gates if isinstance(gate, dict)] if isinstance(gates, list) else []
        if status == "PASSED" and (execution_mode != "immutable-archive" or not gate_statuses or any(value != "PASSED" for value in gate_statuses)):
            errors.append(_signal_error(source, f"results[{index}] PASSED without all immutable archive gates passing", "run every manifest command at the exact observed commit"))
        if status == "FAILED" and "FAILED" not in gate_statuses:
            errors.append(_signal_error(source, f"results[{index}] FAILED without a failed gate", "preserve the failing command status and redacted evidence"))
        if status == "BLOCKED" and execution_mode != "NOT_RUN":
            errors.append(_signal_error(source, f"results[{index}] BLOCKED with an execution mode", "do not report blocked work as executed"))
        if result.get("workspace_state") in {"MISSING", "UNKNOWN"} and status != "BLOCKED":
            errors.append(_signal_error(source, f"results[{index}] has unavailable workspace state but is not BLOCKED", "preserve missing or unknown child checkout state"))
        for gate_index, gate in enumerate(gates if isinstance(gates, list) else []):
            if not isinstance(gate, dict):
                continue
            gate_status = gate.get("status")
            exit_code = gate.get("exit_code")
            if gate_status == "PASSED" and exit_code != 0:
                errors.append(_signal_error(source, f"results[{index}].gates[{gate_index}] passed with non-zero exit code", "retain the observed command exit status"))
            if gate_status == "FAILED" and exit_code == 0:
                errors.append(_signal_error(source, f"results[{index}].gates[{gate_index}] failed with zero exit code", "align gate status with the command result"))
            if gate_status == "NOT_RUN" and exit_code is not None:
                errors.append(_signal_error(source, f"results[{index}].gates[{gate_index}] NOT_RUN has an exit code", "leave exit_code null for unexecuted gates"))
    return errors


def validate_research_provenance(data: dict, source: str = "provenance") -> list[str]:
    """Validate that every structured proposition reference remains traceable."""
    errors: list[str] = []
    schema = load_json(RESEARCH_PROVENANCE_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the research-provenance field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors
    propositions = data.get("propositions")
    selection = data.get("selection_decision")
    if not isinstance(propositions, list) or not isinstance(selection, dict):
        return errors
    if data.get("proposition_count") != len(propositions):
        errors.append(_signal_error(source, "proposition_count does not equal propositions length", "derive the count from every emitted proposition trace"))
    selected_refs = selection.get("selected_candidates")
    if not isinstance(selected_refs, list):
        return errors
    if selection.get("selected_count") != len(selected_refs):
        errors.append(_signal_error(source, "selection_decision.selected_count does not equal selected_candidates length", "preserve the selection decision count"))
    selected_by_id: dict[str, dict] = {}
    ranks: list[int] = []
    for index, selected in enumerate(selected_refs):
        if not isinstance(selected, dict):
            continue
        candidate_id = selected.get("candidate_id")
        if candidate_id in selected_by_id:
            errors.append(_signal_error(source, f"selection_decision.selected_candidates[{index}] duplicates {candidate_id!r}", "record one selection decision per candidate"))
        if isinstance(candidate_id, str):
            selected_by_id[candidate_id] = selected
        rank = selected.get("rank")
        if isinstance(rank, int) and not isinstance(rank, bool):
            ranks.append(rank)
    if ranks and sorted(ranks) != list(range(1, len(ranks) + 1)):
        errors.append(_signal_error(source, "selection decision ranks are not contiguous from 1", "retain the deterministic selection ranks"))
    proposition_ids: set[str] = set()
    proposition_candidates: set[str] = set()
    for index, proposition in enumerate(propositions):
        if not isinstance(proposition, dict):
            continue
        proposition_id = proposition.get("proposition_id")
        if proposition_id in proposition_ids:
            errors.append(_signal_error(source, f"propositions[{index}] duplicates proposition_id {proposition_id!r}", "derive one stable proposition ID per selected candidate"))
        if isinstance(proposition_id, str):
            proposition_ids.add(proposition_id)
        candidate_id = proposition.get("candidate_id")
        if candidate_id in proposition_candidates:
            errors.append(_signal_error(source, f"propositions[{index}] duplicates candidate_id {candidate_id!r}", "emit one proposition trace per selected candidate"))
        if isinstance(candidate_id, str):
            proposition_candidates.add(candidate_id)
        selected_ref = selected_by_id.get(candidate_id)
        if selected_ref is None:
            errors.append(_signal_error(source, f"propositions[{index}] is not present in the selection decision", "trace only candidates selected by the seeded decision"))
        elif proposition.get("selection") != selected_ref:
            errors.append(_signal_error(source, f"propositions[{index}] selection differs from selection_decision", "copy rank and score without mutation"))
        candidate = proposition.get("candidate")
        rule = proposition.get("rule")
        structured = proposition.get("structured_output")
        signals = proposition.get("normalized_signals")
        if not isinstance(candidate, dict) or not isinstance(rule, dict) or not isinstance(structured, dict) or not isinstance(signals, list):
            continue
        if candidate.get("candidate_id") != candidate_id or candidate.get("rule_id") != proposition.get("rule_id"):
            errors.append(_signal_error(source, f"propositions[{index}] candidate identity is inconsistent", "preserve candidate and rule IDs through the trace"))
        if rule.get("rule_id") != proposition.get("rule_id") or rule.get("rule_set_hash") != data.get("rule_set_hash"):
            errors.append(_signal_error(source, f"propositions[{index}] rule identity is inconsistent", "preserve the active rule and registry hash"))
        if structured.get("output_type") != rule.get("output_type") or structured.get("template") != rule.get("template"):
            errors.append(_signal_error(source, f"propositions[{index}] structured output differs from rule", "use the finite rule template without free-form rewriting"))
        trace_by_id: dict[str, dict] = {}
        for signal_index, trace in enumerate(signals):
            if not isinstance(trace, dict):
                continue
            signal_id = trace.get("signal_id")
            if signal_id in trace_by_id:
                errors.append(_signal_error(source, f"propositions[{index}].normalized_signals[{signal_index}] duplicates {signal_id!r}", "record one trace per normalized signal"))
            if isinstance(signal_id, str):
                trace_by_id[signal_id] = trace
        if {trace.get("signal_kind") for trace in trace_by_id.values()} != {"self", "art-history", "marketing"}:
            errors.append(_signal_error(source, f"propositions[{index}] does not trace all required signal kinds", "preserve self, art-history, and marketing provenance"))
        inputs = candidate.get("inputs")
        if isinstance(inputs, dict):
            for kind, refs in inputs.items():
                if not isinstance(refs, list):
                    continue
                for ref_index, ref in enumerate(refs):
                    if not isinstance(ref, dict):
                        continue
                    if ref.get("signal_kind") != kind:
                        errors.append(_signal_error(source, f"propositions[{index}].candidate.inputs.{kind}[{ref_index}] has an inconsistent signal kind", "keep each provenance reference in its declared signal bucket"))
                    trace = trace_by_id.get(ref.get("signal_id"))
                    if trace is None:
                        errors.append(_signal_error(source, f"propositions[{index}].candidate.inputs.{kind}[{ref_index}] has no normalized signal trace", "retain every selected signal in normalized_signals"))
                        continue
                    for field in ("signal_kind", "source_repository", "source_commit", "source_entity_ids", "source_locators", "evidence_locators"):
                        if ref.get(field) != trace.get(field):
                            errors.append(_signal_error(source, f"propositions[{index}] input {ref.get('signal_id')!r} mismatches normalized signal {field}", "preserve source provenance exactly"))
                    if ref.get("attribute") not in trace.get("attributes", []):
                        errors.append(_signal_error(source, f"propositions[{index}] input attribute is absent from normalized signal trace", "retain every referenced attribute"))
        slots = structured.get("slots") if isinstance(structured, dict) else None
        composition = candidate.get("composition")
        if isinstance(slots, dict) and isinstance(composition, dict):
            for slot_name, slot in slots.items():
                if not isinstance(slot, dict) or not isinstance(composition.get(slot_name), dict):
                    continue
                composition_ref = composition[slot_name]
                trace = trace_by_id.get(slot.get("signal_id"))
                if trace is None:
                    continue
                for field in ("signal_id", "signal_kind", "attribute"):
                    if slot.get(field) != composition_ref.get(field):
                        errors.append(_signal_error(source, f"propositions[{index}].structured_output.slots.{slot_name} loses composition {field}", "preserve rule slot identity"))
                if slot.get("source_repository") != trace.get("source_repository") or slot.get("source_commit") != trace.get("source_commit"):
                    errors.append(_signal_error(source, f"propositions[{index}].structured_output.slots.{slot_name} loses source identity", "copy repository and commit from the normalized signal trace"))
                if slot.get("evidence_locator") not in trace.get("evidence_locators", []):
                    errors.append(_signal_error(source, f"propositions[{index}].structured_output.slots.{slot_name} has an untraceable evidence locator", "use an evidence locator from the normalized signal"))
    if len(propositions) != len(selected_by_id):
        errors.append(_signal_error(source, "proposition count does not cover the selection decision", "emit one proposition trace for every selected candidate"))
    return errors


def validate_v12_e2e(data: dict, manifest: dict | None = None, source: str = "v12-e2e") -> list[str]:
    """Validate v1.2 stage integration and the preserved v1.1 regression boundary."""
    errors: list[str] = []
    schema = load_json(V12_E2E_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the v12-e2e field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors
    pipeline = data.get("pipeline")
    child = data.get("child_quality_gates")
    regression = data.get("v11_regression")
    acceptance = data.get("acceptance")
    if isinstance(pipeline, dict):
        provenance = pipeline.get("provenance", {})
        selection = pipeline.get("selection", {})
        if isinstance(provenance, dict) and isinstance(selection, dict):
            if provenance.get("proposition_count") != selection.get("selected_count"):
                errors.append(_signal_error(source, "provenance count differs from selection count", "trace exactly every selected candidate"))
            if not set(selection.get("selected_candidate_ids", [])):
                errors.append(_signal_error(source, "selection has no selected candidate IDs", "retain the deterministic selected package"))
            if not set(provenance.get("signal_ids", [])):
                errors.append(_signal_error(source, "provenance has no signal IDs", "preserve normalized signal identity through the E2E"))
    if isinstance(child, dict) and isinstance(manifest, dict):
        repositories = manifest.get("repositories", [])
        if child.get("repository_count") != len(repositories):
            errors.append(_signal_error(source, "child gate repository count differs from manifest", "run every manifest-declared child gate"))
        if "FAILED" in child.get("statuses", []) and acceptance and acceptance.get("child_gates_observed"):
            errors.append(_signal_error(source, "failed child gate was hidden by a passing E2E acceptance", "preserve failed child quality gates as a non-passing state"))
    if isinstance(regression, dict):
        if regression.get("remote_operations") != [] or regression.get("raw_conversation_stored") is not False:
            errors.append(_signal_error(source, "v1.1 regression boundary was widened", "keep interaction artifacts reference-only and remote operations empty"))
        regression_acceptance = regression.get("acceptance")
        if isinstance(regression_acceptance, dict) and any(value is not True for value in regression_acceptance.values()):
            errors.append(_signal_error(source, "v1.1 regression acceptance is incomplete", "preserve every v1.1 interaction and artifact invariant"))
    if isinstance(acceptance, dict) and any(value is not True for value in acceptance.values()):
        errors.append(_signal_error(source, "v1.2 E2E acceptance is incomplete", "keep every research, child gate, regression, and remote safety invariant true"))
    return errors


def validate_signal(data: dict, source: str = "signal") -> list[str]:
    """Validate the v1 boundary envelope and its domain-preserving invariants."""
    errors: list[str] = []
    schema = load_json(SIGNAL_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the signal field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    if data.get("contract_version") != "normalized-research-signal/v1":
        errors.append(
            _signal_error(
                source,
                "contract_version must be normalized-research-signal/v1",
                "use the supported major contract version or reject the signal",
            )
        )

    source_data = data.get("source")
    if isinstance(source_data, dict):
        repository = source_data.get("repository")
        if repository not in _known_input_repository_ids():
            errors.append(
                _signal_error(
                    source,
                    f"source.repository {repository!r} is not a declared input repository",
                    "use a repository ID from config/repositories.yaml",
                )
            )
        entity_ids = source_data.get("entity_ids")
        if isinstance(entity_ids, list) and len(entity_ids) != len(set(entity_ids)):
            errors.append(
                _signal_error(
                    source,
                    "source.entity_ids must be unique",
                    "retain stable source entity IDs without duplicates",
                )
            )
        locators = source_data.get("locators")
        if isinstance(locators, list) and len(locators) != len(set(locators)):
            errors.append(
                _signal_error(
                    source,
                    "source.locators must be unique",
                    "retain distinct opaque source locators",
                )
            )

    evidence_refs = data.get("evidence_refs")
    if isinstance(evidence_refs, list):
        evidence_locators = [
            ref.get("locator")
            for ref in evidence_refs
            if isinstance(ref, dict) and isinstance(ref.get("locator"), str)
        ]
        if len(evidence_locators) != len(set(evidence_locators)):
            errors.append(
                _signal_error(
                    source,
                    "evidence_refs locators must be unique",
                    "retain each evidence reference once",
                )
            )
        entity_ids = source_data.get("entity_ids", []) if isinstance(source_data, dict) else []
        for index, ref in enumerate(evidence_refs):
            if not isinstance(ref, dict):
                continue
            entity_id = ref.get("entity_id")
            if entity_id is not None and entity_id not in entity_ids:
                errors.append(
                    _signal_error(
                        source,
                        f"evidence_refs[{index}].entity_id {entity_id!r} is not in source.entity_ids",
                        "reference a declared source entity or omit entity_id",
                    )
                )

    freshness = data.get("freshness")
    validity = data.get("validity")
    if isinstance(freshness, dict) and isinstance(validity, dict):
        if freshness.get("status") == "stale" and validity.get("status") == "valid":
            errors.append(
                _signal_error(
                    source,
                    "stale freshness cannot have valid validity status",
                    "propagate stale state as stale or unknown and retain it as a constraint",
                )
            )
        if freshness.get("status") == "stale":
            constraints = data.get("constraints", [])
            if not any("stale" in constraint.lower() for constraint in constraints if isinstance(constraint, str)):
                errors.append(
                    _signal_error(
                        source,
                        "stale freshness must be represented in constraints",
                        "add an explicit stale/revalidation constraint; do not silently drop the signal",
                    )
                )

    signal_kind = data.get("signal_kind")
    domain = data.get("domain")
    expected_domain = {
        "self": "self_model",
        "art-history": "art_history",
        "marketing": "marketing",
    }.get(signal_kind)
    if expected_domain and isinstance(domain, dict):
        if expected_domain not in domain:
            errors.append(
                _signal_error(
                    source,
                    f"signal_kind {signal_kind!r} requires domain.{expected_domain}",
                    "use the domain extension matching signal_kind",
                )
            )
        if len(domain) == 1 and expected_domain not in domain:
            errors.append(
                _signal_error(
                    source,
                    "domain extension does not match signal_kind",
                    "keep exactly one matching domain extension",
                )
            )

    if signal_kind == "self" and isinstance(domain, dict):
        self_model = domain.get("self_model")
        if isinstance(self_model, dict):
            if self_model.get("export_permitted") is not True:
                errors.append(
                    _signal_error(
                        source,
                        "self-model signal export_permitted must be true",
                        "export only approved derived content within consent_scope",
                    )
                )
            forbidden_raw_fields = {"raw_voice", "raw_voice_text", "raw_voice_body", "raw_audio"}
            leaked = sorted(forbidden_raw_fields.intersection(self_model))
            if leaked:
                errors.append(
                    _signal_error(
                        source,
                        f"self-model signal contains forbidden raw field(s) {leaked!r}",
                        "export an approved raw_voice_locator only; keep raw voice in the child repository",
                    )
                )

    if signal_kind == "art-history" and isinstance(domain, dict):
        art_history = domain.get("art_history")
        if isinstance(art_history, dict):
            source_entity_ids = source_data.get("entity_ids", []) if isinstance(source_data, dict) else []
            for index, relation in enumerate(art_history.get("relations", [])):
                if isinstance(relation, dict) and relation.get("target_entity_id") in source_entity_ids:
                    errors.append(
                        _signal_error(
                            source,
                            f"domain.art_history.relations[{index}] copies a source entity as target",
                            "reference a stable external entity ID rather than copying the canonical graph",
                        )
                    )

    if signal_kind == "marketing" and isinstance(domain, dict):
        marketing = domain.get("marketing")
        if isinstance(marketing, dict) and isinstance(freshness, dict):
            if marketing.get("freshness") != freshness.get("status"):
                errors.append(
                    _signal_error(
                        source,
                        "marketing freshness must match the common freshness status",
                        "preserve one machine-checkable freshness value across the envelope",
                    )
                )
            if marketing.get("freshness") == "stale" and marketing.get("prediction_status") == "confirmed":
                errors.append(
                    _signal_error(
                        source,
                        "stale marketing evidence cannot be marked prediction_status confirmed",
                        "retain stale status and require revalidation before confirmation",
                    )
                )
            if (
                marketing.get("prediction_status") == "confirmed"
                and isinstance(evidence_refs, list)
                and any(
                    isinstance(ref, dict) and ref.get("kind") == "anecdotal"
                    for ref in evidence_refs
                )
            ):
                errors.append(
                    _signal_error(
                        source,
                        "anecdotal marketing evidence cannot be marked prediction_status confirmed",
                        "retain anecdotal evidence status and require non-anecdotal corroboration",
                    )
                )
    return errors


def _artifact_error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def validate_external_artifact(data: dict, source: str = "external-artifact") -> list[str]:
    """Validate a create-only Google Drive artifact reference without reading its content."""
    errors: list[str] = []
    schema = load_json(EXTERNAL_ARTIFACT_SCHEMA_PATH)
    errors.extend(
        _artifact_error(source, schema_error, "correct the external artifact field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    if data.get("contract_version") != "external-artifact/v1":
        errors.append(
            _artifact_error(
                source,
                "contract_version must be external-artifact/v1",
                "use the supported major contract version or reject the artifact",
            )
        )
    if data.get("operation") != "CREATE":
        errors.append(
            _artifact_error(
                source,
                "operation must be CREATE; UPDATE and DELETE are forbidden",
                "create a new artifact and link it with derived_from or supersedes",
            )
        )
    if data.get("provider") != "google-drive":
        errors.append(
            _artifact_error(
                source,
                "provider must be google-drive",
                "store the user artifact in the approved Google Drive location",
            )
        )

    snapshots = data.get("source_snapshots")
    if isinstance(snapshots, list):
        known = _known_repository_ids()
        repositories: list[str] = []
        for index, snapshot in enumerate(snapshots):
            if not isinstance(snapshot, dict):
                continue
            repository = snapshot.get("repository")
            if isinstance(repository, str):
                repositories.append(repository)
                if repository not in known:
                    errors.append(
                        _artifact_error(
                            source,
                            f"source_snapshots[{index}].repository {repository!r} is not declared",
                            "use a repository ID from config/repositories.yaml",
                        )
                    )
        if len(repositories) != len(set(repositories)):
            errors.append(
                _artifact_error(
                    source,
                    "source_snapshots repositories must be unique",
                    "record one immutable commit per consulted repository",
                )
            )

    artifact_id = data.get("artifact_id")
    lineage = data.get("lineage")
    if isinstance(artifact_id, str) and isinstance(lineage, dict):
        for field in ("derived_from", "supersedes"):
            references = lineage.get(field)
            if isinstance(references, list) and artifact_id in references:
                errors.append(
                    _artifact_error(
                        source,
                        f"lineage.{field} must not reference itself",
                        "reference an earlier immutable artifact ID",
                    )
                )
    return errors


def _interaction_error(source: str, detail: str, remediation: str) -> str:
    return f"{source}: {detail}; remediation: {remediation}"


def validate_interaction_event(data: dict, source: str = "interaction-event") -> list[str]:
    """Validate experience metadata while excluding raw conversation and identifiers."""
    errors: list[str] = []
    schema = load_json(INTERACTION_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the interaction event field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    forbidden_fields = {
        "conversation",
        "transcript",
        "prompt",
        "message",
        "raw_text",
        "raw_conversation",
        "user_text",
        "assistant_text",
        "body",
        "content",
    }

    def scan(value, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key.lower() in forbidden_fields:
                    errors.append(
                        _interaction_error(
                            source,
                            f"{child_path} is a forbidden raw conversation field",
                            "store only intent categories and opaque external references",
                        )
                    )
                scan(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    scan(data)

    snapshots = data.get("source_snapshots")
    if isinstance(snapshots, list):
        known = _known_repository_ids()
        repositories: list[str] = []
        for index, snapshot in enumerate(snapshots):
            if not isinstance(snapshot, dict):
                continue
            repository = snapshot.get("repository")
            if isinstance(repository, str):
                repositories.append(repository)
                if repository not in known:
                    errors.append(
                        _interaction_error(
                            source,
                            f"source_snapshots[{index}].repository {repository!r} is not declared",
                            "use a repository ID from config/repositories.yaml",
                        )
                    )
        if len(repositories) != len(set(repositories)):
            errors.append(
                _interaction_error(
                    source,
                    "source_snapshots repositories must be unique",
                    "record one immutable commit per consulted repository",
                )
            )

    privacy = data.get("privacy")
    if isinstance(privacy, dict):
        if privacy.get("raw_conversation_stored") is not False:
            errors.append(
                _interaction_error(
                    source,
                    "privacy.raw_conversation_stored must be false",
                    "retain only privacy-minimal interaction metadata in Git",
                )
            )
        if privacy.get("direct_identifiers_stored") is not False:
            errors.append(
                _interaction_error(
                    source,
                    "privacy.direct_identifiers_stored must be false",
                    "remove direct identifiers and retain an approved opaque reference",
                )
            )
    return errors


def validate_feedback_signal(data: dict, source: str = "feedback-signal") -> list[str]:
    """Validate explicit and inferred feedback without treating inference as user truth."""
    errors: list[str] = []
    schema = load_json(FEEDBACK_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the feedback signal field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    forbidden_fields = {"conversation", "transcript", "prompt", "message", "raw_text", "body", "content"}

    def scan(value, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key.lower() in forbidden_fields:
                    errors.append(
                        _interaction_error(
                            source,
                            f"{child_path} is a forbidden raw feedback field",
                            "retain a privacy-safe summary_code and opaque evidence reference",
                        )
                    )
                scan(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    scan(data)

    explicit_kinds = {"explicit_request", "explicit_dissatisfaction", "output_correction", "knowledge_gap"}
    inferred_kinds = {"inferred_friction", "inferred_need"}
    kind = data.get("kind")
    hypothesis = data.get("hypothesis")
    confidence = data.get("confidence")
    confidence_level = confidence.get("level") if isinstance(confidence, dict) else None
    if kind in inferred_kinds:
        if not isinstance(hypothesis, dict):
            errors.append(
                _interaction_error(source, "inferred feedback requires a hypothesis", "record an unconfirmed claim_code with evidence and confidence")
            )
        elif hypothesis.get("confirmation_status") != "unconfirmed":
            errors.append(
                _interaction_error(source, "inferred feedback hypothesis must start unconfirmed", "require explicit confirmation before changing its status")
            )
        if confidence_level == "explicit":
            errors.append(
                _interaction_error(source, "inferred feedback cannot use explicit confidence", "use high, medium, or low confidence")
            )
    if kind in explicit_kinds:
        if hypothesis is not None:
            errors.append(
                _interaction_error(source, "explicit feedback must not carry an inferred hypothesis", "set hypothesis to null")
            )
        if confidence_level != "explicit":
            errors.append(
                _interaction_error(source, "explicit feedback requires explicit confidence", "set confidence.level to explicit and score to 1")
            )

    target = data.get("target")
    if isinstance(target, dict):
        owner = target.get("owner_repository")
        known = _known_repository_ids() | {"agentic-art-orchestration"}
        if owner not in known:
            errors.append(
                _interaction_error(source, f"target.owner_repository {owner!r} is not declared", "route to the parent or an owning repository from config/repositories.yaml")
            )
    return errors


def validate_async_audit(data: dict, source: str = "async-audit") -> list[str]:
    """Validate a non-blocking audit result and its gated repair proposals."""
    errors: list[str] = []
    schema = load_json(ASYNC_AUDIT_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the asynchronous audit field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    forbidden_fields = {
        "conversation",
        "transcript",
        "prompt",
        "message",
        "raw_text",
        "raw_conversation",
        "user_text",
        "assistant_text",
        "body",
        "content",
        "PRIVATE_RAW",
        "RESTRICTED",
        "credential",
        "direct_identifier",
    }

    def scan(value, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {item.lower() for item in forbidden_fields}:
                    errors.append(
                        _interaction_error(
                            source,
                            f"{path}.{key} is a forbidden raw or sensitive audit field",
                            "retain privacy-safe finding metadata and opaque references only",
                        )
                    )
                scan(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    scan(data)
    if data.get("lane") != "ASYNC_AUDIT":
        errors.append(
            _interaction_error(source, "lane must be ASYNC_AUDIT", "keep audit work on the independent asynchronous lane")
        )
    if data.get("interaction_blocking") is not False:
        errors.append(
            _interaction_error(source, "interaction_blocking must be false", "never wait for audit/refactoring in the interaction request path")
        )
    if data.get("user_artifact_policy") != "READ_ONLY" or data.get("artifact_operations") != []:
        errors.append(
            _interaction_error(source, "user artifacts must be read-only with no operations", "create no update/delete operation for user artifacts")
        )

    snapshot = data.get("source_snapshot")
    source_commits: dict[str, str] = {}
    known = _known_repository_ids() | {"agentic-art-orchestration"}
    if isinstance(snapshot, dict):
        repositories = snapshot.get("repositories")
        if isinstance(repositories, list):
            for index, repository in enumerate(repositories):
                if not isinstance(repository, dict):
                    continue
                repository_id = repository.get("repository")
                commit = repository.get("source_commit")
                if repository_id in source_commits:
                    errors.append(
                        _interaction_error(
                            source,
                            f"source_snapshot.repositories[{index}] duplicates {repository_id!r}",
                            "record one immutable commit per repository",
                        )
                    )
                if isinstance(repository_id, str):
                    source_commits[repository_id] = commit
                    if repository_id not in known:
                        errors.append(
                            _interaction_error(
                                source,
                                f"source snapshot repository {repository_id!r} is not declared",
                                "use manifest repository IDs",
                            )
                        )
        parent_commit = snapshot.get("parent_commit")
        if isinstance(parent_commit, str):
            source_commits["agentic-art-orchestration"] = parent_commit

    lease = data.get("lease")
    if isinstance(lease, dict):
        if lease.get("lane") != "ASYNC_AUDIT" or lease.get("status") != "held":
            errors.append(
                _interaction_error(
                    source,
                    "lease must be held on ASYNC_AUDIT",
                    "acquire the independent audit lane lease before emitting proposals",
                )
            )
        if lease.get("owner") == "unassigned":
            errors.append(
                _interaction_error(source, "held audit lease cannot be unassigned", "record the worker owner and execution ID")
            )

    gates: dict[str, str] = {}
    quality_gates = data.get("quality_gates")
    if isinstance(quality_gates, list):
        for index, gate in enumerate(quality_gates):
            if not isinstance(gate, dict):
                continue
            repository = gate.get("repository")
            status = gate.get("status")
            if repository in gates:
                errors.append(
                    _interaction_error(source, f"quality_gates[{index}] duplicates {repository!r}", "record one gate result per repository")
                )
            if isinstance(repository, str):
                gates[repository] = status
                if repository not in source_commits:
                    errors.append(
                        _interaction_error(source, f"quality gate names unknown repository {repository!r}", "use a repository in the source snapshot")
                    )
                if gate.get("observed_commit") != source_commits.get(repository):
                    errors.append(
                        _interaction_error(
                            source,
                            f"quality gate for {repository!r} is not tied to its source commit",
                            "run or record the gate against the audited immutable commit",
                        )
                    )

    proposals = data.get("proposals")
    proposal_ids: set[str] = set()
    deduplication_keys: set[str] = set()
    audit_hash = data.get("audit_observation", {}).get("audit_hash") if isinstance(data.get("audit_observation"), dict) else None
    if isinstance(proposals, list):
        for index, proposal in enumerate(proposals):
            if not isinstance(proposal, dict):
                continue
            proposal_id = proposal.get("proposal_id")
            key = proposal.get("deduplication_key")
            if proposal_id in proposal_ids:
                errors.append(_interaction_error(source, f"proposals[{index}] duplicates proposal_id {proposal_id!r}", "preserve one proposal per stable ID"))
            if key in deduplication_keys:
                errors.append(_interaction_error(source, f"proposals[{index}] duplicates deduplication_key {key!r}", "suppress duplicate issue or draft-PR proposals"))
            if isinstance(proposal_id, str):
                proposal_ids.add(proposal_id)
            if isinstance(key, str):
                deduplication_keys.add(key)
            repository = proposal.get("repository")
            if repository not in source_commits:
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} targets unknown repository {repository!r}", "route to a source snapshot repository or the parent"))
                continue
            if proposal.get("source_commit") != source_commits[repository]:
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} source commit does not match snapshot", "rebase the proposal on the observed commit"))
            gate_status = proposal.get("quality_gate_status")
            if gate_status != gates.get(repository):
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} gate status is not the recorded repository gate", "do not bypass a missing or failed quality gate"))
            if proposal.get("kind") == "DRAFT_PR" and gate_status != "PASSED":
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} is a draft PR without a passed gate", "keep it as a triage issue until the gate passes"))
            if proposal.get("kind") == "DRAFT_PR" and proposal.get("status") != "READY":
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} draft PR plan is not READY", "make a gated draft plan explicitly READY"))
            finding = proposal.get("finding")
            if isinstance(finding, dict) and finding.get("audit_hash") != audit_hash:
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} is not traceable to this audit", "retain the source audit hash in each proposal"))
            if proposal.get("human_gate") is not True:
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} must retain the human gate", "do not merge or release automatically"))
            if proposal.get("artifact_operations") != []:
                errors.append(_interaction_error(source, f"proposal {proposal_id!r} mutates a user artifact", "keep user artifact operations empty"))
    return errors


def validate_issue_routing(data: dict, source: str = "issue-routing") -> list[str]:
    """Validate authority-based feedback routes without creating remote Issues."""
    errors: list[str] = []
    schema = load_json(ISSUE_ROUTING_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the feedback routing field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    forbidden_fields = {
        "conversation",
        "transcript",
        "prompt",
        "message",
        "raw_text",
        "raw_conversation",
        "user_text",
        "assistant_text",
        "body",
        "content",
        "PRIVATE_RAW",
        "RESTRICTED",
        "credential",
        "direct_identifier",
    }

    def scan(value, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {item.lower() for item in forbidden_fields}:
                    errors.append(
                        _interaction_error(
                            source,
                            f"{path}.{key} is a forbidden raw or sensitive routing field",
                            "retain summary codes and opaque evidence references only",
                        )
                    )
                scan(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    scan(data)
    if data.get("lane") != "FEEDBACK_ROUTING":
        errors.append(_interaction_error(source, "lane must be FEEDBACK_ROUTING", "keep routing on the feedback lane"))
    if data.get("interaction_blocking") is not False:
        errors.append(_interaction_error(source, "interaction_blocking must be false", "do not make the user wait for Issue routing"))
    if data.get("user_artifact_policy") != "READ_ONLY" or data.get("issue_operations") != []:
        errors.append(_interaction_error(source, "routing must not mutate user artifacts or create remote Issues", "return metadata-only Issue candidates"))

    known = _known_repository_ids() | {"agentic-art-orchestration"}
    parent = "agentic-art-orchestration"
    feedback_ids = data.get("input_feedback_ids")
    routes = data.get("routes")
    route_ids: set[str] = set()
    if isinstance(routes, list):
        for index, route in enumerate(routes):
            if not isinstance(route, dict):
                continue
            feedback_id = route.get("feedback_id")
            if feedback_id in route_ids:
                errors.append(_interaction_error(source, f"routes[{index}] duplicates feedback_id {feedback_id!r}", "route each feedback signal once"))
            if isinstance(feedback_id, str):
                route_ids.add(feedback_id)
            target = route.get("target_repository")
            target_role = route.get("target_role")
            if isinstance(target, str) and target not in known:
                errors.append(_interaction_error(source, f"route {feedback_id!r} targets unknown repository {target!r}", "use a manifest repository or the parent"))
            if target_role == "PARENT" and target != parent:
                errors.append(_interaction_error(source, f"route {feedback_id!r} marks a non-parent target as PARENT", "route orchestration and UX feedback to the parent"))
            if target_role == "CHILD" and (target is None or target == parent):
                errors.append(_interaction_error(source, f"route {feedback_id!r} marks the parent as CHILD", "route domain feedback to its owning child"))
            candidates = route.get("candidate_repositories")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if candidate not in known:
                        errors.append(_interaction_error(source, f"route {feedback_id!r} has unknown candidate {candidate!r}", "use manifest repository IDs"))
            inference = route.get("inference")
            kind = route.get("kind")
            if isinstance(inference, dict):
                if kind in {"inferred_friction", "inferred_need"}:
                    if inference.get("is_inferred") is not True or inference.get("hypothesis_status") != "unconfirmed":
                        errors.append(_interaction_error(source, f"inferred route {feedback_id!r} lost its unconfirmed hypothesis", "keep inference separate from user truth"))
                elif inference.get("is_inferred") is not False or inference.get("hypothesis_status") != "not-applicable":
                    errors.append(_interaction_error(source, f"explicit route {feedback_id!r} carries inference state", "mark explicit feedback as not-applicable for inference"))
            status = route.get("routing_status")
            candidate = route.get("issue_candidate")
            if status in {"ROUTED", "TRIAGE"} and not isinstance(candidate, dict):
                errors.append(_interaction_error(source, f"route {feedback_id!r} lacks a metadata-only Issue candidate", "retain a triageable candidate without creating it remotely"))
            if status in {"BLOCKED", "DUPLICATE_SUPPRESSED"} and candidate is not None:
                errors.append(_interaction_error(source, f"route {feedback_id!r} has a candidate after {status}", "suppress or block the candidate without side effects"))
            if isinstance(candidate, dict):
                if candidate.get("target_repository") != target:
                    errors.append(_interaction_error(source, f"Issue candidate for {feedback_id!r} does not match route target", "keep target authority consistent"))
                if feedback_id not in candidate.get("source_feedback_ids", []):
                    errors.append(_interaction_error(source, f"Issue candidate for {feedback_id!r} lost its source reference", "retain the feedback ID in the candidate"))
                if candidate.get("human_gate") is not True or candidate.get("side_effect") != "NONE":
                    errors.append(_interaction_error(source, f"Issue candidate for {feedback_id!r} bypasses the human/no-side-effect boundary", "create no remote Issue automatically"))
                if status == "ROUTED" and candidate.get("creation_permitted") is not True:
                    errors.append(_interaction_error(source, f"routed candidate for {feedback_id!r} is not marked permitted", "keep explicit consent and routing state aligned"))
                if status == "TRIAGE" and candidate.get("creation_permitted") is not False:
                    errors.append(_interaction_error(source, f"triage candidate for {feedback_id!r} is marked creatable", "keep uncertain routing in triage"))
    if isinstance(feedback_ids, list) and set(feedback_ids) != route_ids:
        errors.append(_interaction_error(source, "input_feedback_ids and routes do not cover the same feedback", "retain one traceable route for every input signal"))

    suppressions = data.get("duplicate_suppressions")
    seen_suppressions: set[tuple[object, object]] = set()
    if isinstance(suppressions, list):
        for suppression in suppressions:
            if not isinstance(suppression, dict):
                continue
            pair = (suppression.get("issue_key"), suppression.get("suppressed_feedback_id"))
            if pair in seen_suppressions:
                errors.append(_interaction_error(source, f"duplicate suppression {pair!r} appears twice", "record one suppression per feedback and Issue key"))
            seen_suppressions.add(pair)
            if suppression.get("canonical_feedback_id") not in route_ids or suppression.get("suppressed_feedback_id") not in route_ids:
                errors.append(_interaction_error(source, "duplicate suppression references an unknown feedback ID", "retain the canonical and suppressed route records"))
    return errors


def _scan_forbidden_retrieval_fields(data: object, source: str) -> list[str]:
    errors: list[str] = []
    forbidden_fields = {
        "conversation",
        "transcript",
        "prompt",
        "message",
        "raw_text",
        "raw_query",
        "query",
        "question",
        "user_text",
        "assistant_text",
        "statement",
        "body",
        "content",
        "PRIVATE_RAW",
        "RESTRICTED",
        "credential",
        "direct_identifier",
    }
    forbidden_lower = {field.lower() for field in forbidden_fields}

    def scan(value: object, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in forbidden_lower:
                    errors.append(
                        _interaction_error(
                            source,
                            f"{path}.{key} is a forbidden raw or sensitive retrieval field",
                            "store structured capability codes and opaque evidence locators only",
                        )
                    )
                scan(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    scan(data)
    return errors


def _retrieval_manifest_index(manifest: dict | None = None) -> dict[str, dict]:
    loaded = manifest if manifest is not None else load_yaml(MANIFEST_PATH)
    repositories = loaded.get("repositories") if isinstance(loaded, dict) else None
    return {
        repository.get("id"): repository
        for repository in repositories or []
        if isinstance(repository, dict) and isinstance(repository.get("id"), str)
    }


def _safe_retrieval_locator(value: object) -> bool:
    return (
        _is_safe_relative_path(value)
        and isinstance(value, str)
        and "://" not in value
        and all(character not in value for character in (" ", "\n", "\r"))
    )


def validate_retrieval_request(
    data: dict,
    source: str = "retrieval-request",
    manifest: dict | None = None,
) -> list[str]:
    """Validate a structured request without retaining its conversational wording."""
    errors: list[str] = []
    schema = load_json(RETRIEVAL_REQUEST_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the retrieval request field")
        for schema_error in _schema_errors(data, schema)
    )
    errors.extend(_scan_forbidden_retrieval_fields(data, source))
    if not isinstance(data, dict):
        return errors
    known = set(_retrieval_manifest_index(manifest))
    preferred = data.get("preferred_repositories")
    if isinstance(preferred, list):
        for repository in preferred:
            if repository not in known:
                errors.append(
                    _interaction_error(
                        source,
                        f"preferred repository {repository!r} is not declared",
                        "use a repository ID from config/repositories.yaml",
                    )
                )
    privacy = data.get("privacy")
    if isinstance(privacy, dict):
        if privacy.get("raw_query_stored") is not False:
            errors.append(
                _interaction_error(
                    source,
                    "privacy.raw_query_stored must be false",
                    "derive capability codes transiently and do not persist raw query text",
                )
            )
        if privacy.get("direct_identifiers_stored") is not False:
            errors.append(
                _interaction_error(
                    source,
                    "privacy.direct_identifiers_stored must be false",
                    "remove direct identifiers from the retrieval envelope",
                )
            )
    return errors


def validate_retrieval_index(data: dict, manifest: dict | None = None, source: str = "retrieval-index") -> list[str]:
    """Validate adapter-provided evidence metadata against immutable manifest pins."""
    errors: list[str] = []
    schema = load_json(RETRIEVAL_INDEX_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the retrieval index field")
        for schema_error in _schema_errors(data, schema)
    )
    errors.extend(_scan_forbidden_retrieval_fields(data, source))
    if not isinstance(data, dict):
        return errors
    repositories = _retrieval_manifest_index(manifest)
    seen_evidence: set[str] = set()
    entries = data.get("entries")
    if not isinstance(entries, list):
        return errors
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        prefix = f"{source}: entries[{index}]"
        evidence_id = entry.get("evidence_id")
        if evidence_id in seen_evidence:
            errors.append(_interaction_error(source, f"entries[{index}] duplicates evidence_id {evidence_id!r}", "retain one immutable evidence entry per ID"))
        if isinstance(evidence_id, str):
            seen_evidence.add(evidence_id)
        repository_id = entry.get("repository")
        repository = repositories.get(repository_id)
        if repository is None:
            errors.append(_interaction_error(source, f"entries[{index}] names unknown repository {repository_id!r}", "use a repository declared in the manifest"))
            continue
        observed_commit = repository.get("observed_commit")
        if entry.get("source_commit") != observed_commit:
            errors.append(
                _interaction_error(
                    source,
                    f"entries[{index}] source_commit is not the manifest observed commit",
                    "refresh the adapter index from the immutable repository snapshot",
                )
            )
        if not _safe_retrieval_locator(entry.get("locator")):
            errors.append(_interaction_error(source, f"entries[{index}].locator is unsafe", "use a repository-local or opaque relative locator"))
        profile = repository.get("knowledge_profile", {})
        evidence_rules = profile.get("evidence_rules", {}) if isinstance(profile, dict) else {}
        allowed_kinds = evidence_rules.get("allowed_kinds", []) if isinstance(evidence_rules, dict) else []
        if entry.get("evidence_kind") not in allowed_kinds:
            errors.append(
                _interaction_error(
                    source,
                    f"entries[{index}].evidence_kind is outside the repository profile",
                    "retain the child repository evidence policy at the parent boundary",
                )
            )
        freshness_rules = profile.get("freshness_rules", {}) if isinstance(profile, dict) else {}
        allowed_statuses = freshness_rules.get("allowed_statuses", []) if isinstance(freshness_rules, dict) else []
        if entry.get("freshness_status") not in allowed_statuses:
            errors.append(
                _interaction_error(
                    source,
                    f"entries[{index}].freshness_status is outside the repository profile",
                    "preserve stale or unknown state and follow the child freshness policy",
                )
            )
        capability_codes = entry.get("capability_codes")
        if isinstance(capability_codes, list) and len(capability_codes) != len(set(capability_codes)):
            errors.append(_interaction_error(source, f"entries[{index}].capability_codes are duplicated", "declare each retrieval capability once"))
    return errors


def validate_retrieval_result(
    data: dict,
    manifest: dict | None = None,
    request: dict | None = None,
    source: str = "retrieval-result",
) -> list[str]:
    """Validate selected repositories and evidence provenance in a retrieval result."""
    errors: list[str] = []
    schema = load_json(RETRIEVAL_RESULT_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the retrieval result field")
        for schema_error in _schema_errors(data, schema)
    )
    errors.extend(_scan_forbidden_retrieval_fields(data, source))
    if not isinstance(data, dict):
        return errors
    repositories = _retrieval_manifest_index(manifest)
    known = set(repositories)
    requested = set(data.get("capability_codes", [])) if isinstance(data.get("capability_codes"), list) else set()
    selected = data.get("selected_repositories")
    selected_by_id: dict[str, dict] = {}
    if isinstance(selected, list):
        for index, record in enumerate(selected):
            if not isinstance(record, dict):
                continue
            repository_id = record.get("repository")
            if repository_id in selected_by_id:
                errors.append(_interaction_error(source, f"selected_repositories[{index}] duplicates {repository_id!r}", "select each repository once"))
            if isinstance(repository_id, str):
                selected_by_id[repository_id] = record
            repository = repositories.get(repository_id)
            if repository is None:
                errors.append(_interaction_error(source, f"selected repository {repository_id!r} is unknown", "use a repository declared in the manifest"))
                continue
            if record.get("source_commit") != repository.get("observed_commit"):
                errors.append(_interaction_error(source, f"selected repository {repository_id!r} is not tied to its observed commit", "return the immutable source commit used for retrieval"))
            matched = record.get("matched_capability_codes")
            if isinstance(matched, list) and not set(matched).issubset(requested):
                errors.append(_interaction_error(source, f"selected repository {repository_id!r} reports an unrequested capability", "keep selection evidence tied to the structured request"))
    evidence = data.get("evidence")
    seen_evidence: set[str] = set()
    if isinstance(evidence, list):
        for index, record in enumerate(evidence):
            if not isinstance(record, dict):
                continue
            evidence_id = record.get("evidence_id")
            if evidence_id in seen_evidence:
                errors.append(_interaction_error(source, f"evidence[{index}] duplicates evidence_id {evidence_id!r}", "return each evidence reference once"))
            if isinstance(evidence_id, str):
                seen_evidence.add(evidence_id)
            repository_id = record.get("repository")
            if repository_id not in selected_by_id:
                errors.append(_interaction_error(source, f"evidence[{index}] is outside selected repositories", "return evidence only from the minimum selected set"))
                continue
            repository = repositories.get(repository_id)
            if repository is not None and record.get("source_commit") != repository.get("observed_commit"):
                errors.append(_interaction_error(source, f"evidence[{index}] source_commit does not match its repository pin", "preserve immutable evidence provenance"))
            if not _safe_retrieval_locator(record.get("locator")):
                errors.append(_interaction_error(source, f"evidence[{index}].locator is unsafe", "return a repository-local or opaque relative locator"))
            profile = repository.get("knowledge_profile", {}) if repository else {}
            evidence_rules = profile.get("evidence_rules", {}) if isinstance(profile, dict) else {}
            if record.get("evidence_kind") not in evidence_rules.get("allowed_kinds", []):
                errors.append(_interaction_error(source, f"evidence[{index}] violates its repository evidence policy", "retain the child repository evidence rule"))
            freshness_rules = profile.get("freshness_rules", {}) if isinstance(profile, dict) else {}
            if record.get("freshness_status") not in freshness_rules.get("allowed_statuses", []):
                errors.append(_interaction_error(source, f"evidence[{index}] violates its repository freshness policy", "preserve the source freshness state"))
            matched = record.get("matched_capability_codes")
            if isinstance(matched, list) and not set(matched).issubset(requested):
                errors.append(_interaction_error(source, f"evidence[{index}] reports an unrequested capability", "keep evidence tied to the structured request"))
    if data.get("status") == "NO_MATCH" and (selected_by_id or seen_evidence):
        errors.append(_interaction_error(source, "NO_MATCH result contains selected repositories or evidence", "use COMPLETE_WITH_GAPS when partial evidence exists"))
    if request is not None:
        if data.get("request_ref") != request.get("request_id"):
            errors.append(_interaction_error(source, "request_ref does not match the retrieval request", "retain the request ID for traceability"))
        if data.get("intent_code") != request.get("intent_code") or data.get("capability_codes") != request.get("capability_codes"):
            errors.append(_interaction_error(source, "result request fields do not match the retrieval request", "preserve structured request intent and capability codes"))
    return errors


def validate_improvement_loop(
    data: dict,
    manifest: dict | None = None,
    source: str = "improvement-loop",
) -> list[str]:
    """Validate resumable improvement outcomes without permitting remote side effects."""
    errors: list[str] = []
    schema = load_json(IMPROVEMENT_LOOP_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the improvement loop field")
        for schema_error in _schema_errors(data, schema)
    )
    errors.extend(_scan_forbidden_retrieval_fields(data, source))
    if not isinstance(data, dict):
        return errors

    repositories = _retrieval_manifest_index(manifest)
    known = set(repositories) | {"agentic-art-orchestration"}
    if data.get("lane") != "AUTONOMOUS_IMPROVEMENT":
        errors.append(_interaction_error(source, "lane must be AUTONOMOUS_IMPROVEMENT", "keep improvement work on its independent backstage lane"))
    if data.get("interaction_blocking") is not False:
        errors.append(_interaction_error(source, "interaction_blocking must be false", "never delay the frontstage response for improvement work"))
    if data.get("user_artifact_policy") != "READ_ONLY" or data.get("remote_operations") != []:
        errors.append(_interaction_error(source, "improvement must not mutate user artifacts or perform remote operations", "return a human-gated metadata-only draft plan"))

    input_issue_keys = data.get("input_issue_keys")
    input_keys = set(input_issue_keys) if isinstance(input_issue_keys, list) else set()
    outcomes = data.get("outcomes")
    outcome_by_key: dict[str, dict] = {}
    plan_ids: set[str] = set()
    expected_plan_ids: set[str] = set()
    for index, outcome in enumerate(outcomes if isinstance(outcomes, list) else []):
        if not isinstance(outcome, dict):
            continue
        issue_key = outcome.get("issue_key")
        if issue_key in outcome_by_key:
            errors.append(_interaction_error(source, f"outcomes[{index}] duplicates issue_key {issue_key!r}", "select each canonical Issue once"))
        if isinstance(issue_key, str):
            outcome_by_key[issue_key] = outcome
        if isinstance(issue_key, str) and issue_key not in input_keys:
            errors.append(_interaction_error(source, f"outcome {issue_key!r} is not in input_issue_keys", "retain the Issue routing trace"))
        target = outcome.get("target_repository")
        repository = repositories.get(target) if isinstance(target, str) else None
        if target is not None and target not in known:
            errors.append(_interaction_error(source, f"outcome {issue_key!r} targets unknown repository {target!r}", "route only to a manifest repository or the parent"))
            repository = None
        base_commit = outcome.get("base_commit")
        if repository is not None and base_commit != repository.get("observed_commit"):
            errors.append(_interaction_error(source, f"outcome {issue_key!r} is not tied to the target observed commit", "rebase the improvement plan on the immutable source commit"))
        if target is None and base_commit is not None:
            errors.append(_interaction_error(source, f"outcome {issue_key!r} has a commit without a target repository", "keep unresolved triage metadata unbound"))

        changed_paths = outcome.get("changed_paths")
        if isinstance(changed_paths, list) and repository is not None:
            profile = repository.get("knowledge_profile", {}) if isinstance(repository, dict) else {}
            write_scope = profile.get("write_scope", {}) if isinstance(profile, dict) else {}
            allowed_scope = write_scope.get("allowed_paths", []) if isinstance(write_scope, dict) else []
            if target == "agentic-art-orchestration":
                allowed_scope = ["docs", "execution", "schemas", "tools", "tests", "config"]
            for path in changed_paths:
                if not _is_safe_relative_path(path):
                    errors.append(_interaction_error(source, f"outcome {issue_key!r} has an unsafe changed path", "limit implementation scope to safe relative paths"))
                elif not any(path == root or path.startswith(f"{root}/") for root in allowed_scope):
                    errors.append(_interaction_error(source, f"outcome {issue_key!r} changes a path outside write_scope", "respect the target knowledge profile write scope"))

        work_item = outcome.get("work_item")
        if isinstance(work_item, dict):
            if work_item.get("owner_repository") != target:
                errors.append(_interaction_error(source, f"work item for {issue_key!r} has a different owner", "keep scheduler and Issue authority aligned"))
            if work_item.get("source_commit") != base_commit:
                errors.append(_interaction_error(source, f"work item for {issue_key!r} is not tied to the outcome commit", "retain one immutable base commit across runtime checkpoints"))
            if work_item.get("scheduler_status") != "SELECTED":
                errors.append(_interaction_error(source, f"work item for {issue_key!r} was not scheduler-selected", "do not progress an excluded work item"))

        draft = outcome.get("draft_pr_plan")
        delivery = outcome.get("delivery_status")
        if delivery == "DRAFT_PR_READY":
            if outcome.get("implementation_status") != "PASSED" or outcome.get("test_status") != "PASSED" or outcome.get("quality_gate_status") != "PASSED":
                errors.append(_interaction_error(source, f"draft plan for {issue_key!r} lacks implementation/test/gate evidence", "keep failed or missing evidence out of draft PR planning"))
            if not isinstance(draft, dict):
                errors.append(_interaction_error(source, f"draft plan for {issue_key!r} is missing", "emit a human-gated plan only after all checks pass"))
        elif draft is not None:
            errors.append(_interaction_error(source, f"non-ready outcome {issue_key!r} has a draft PR plan", "keep triage and blocked work without a draft plan"))
        if isinstance(draft, dict):
            plan_id = draft.get("plan_id")
            if plan_id in plan_ids:
                errors.append(_interaction_error(source, f"draft plan {plan_id!r} is duplicated", "emit one plan per canonical Issue"))
            if isinstance(plan_id, str):
                plan_ids.add(plan_id)
                expected_plan_ids.add(plan_id)
            if draft.get("issue_key") != issue_key or draft.get("target_repository") != target:
                errors.append(_interaction_error(source, f"draft plan for {issue_key!r} lost its Issue authority", "keep plan and outcome targets identical"))
            if draft.get("base_commit") != base_commit or draft.get("changed_paths") != changed_paths:
                errors.append(_interaction_error(source, f"draft plan for {issue_key!r} lost its source or path scope", "preserve the checkpointed implementation scope"))
            if draft.get("quality_gate_status") != "PASSED" or draft.get("human_gate") is not True or draft.get("merge_permitted") is not False or draft.get("release_permitted") is not False or draft.get("side_effect") != "NONE":
                errors.append(_interaction_error(source, f"draft plan for {issue_key!r} bypasses a human or side-effect gate", "do not merge, release, or create a remote PR automatically"))

        checkpoints = outcome.get("checkpoints")
        if isinstance(checkpoints, list):
            checkpoint_keys: set[str] = set()
            checkpoint_steps: set[str] = set()
            for checkpoint in checkpoints:
                if not isinstance(checkpoint, dict):
                    continue
                key = checkpoint.get("idempotency_key")
                step = checkpoint.get("step")
                if key in checkpoint_keys:
                    errors.append(_interaction_error(source, f"outcome {issue_key!r} duplicates checkpoint idempotency key", "resume the same checkpoint instead of duplicating side effects"))
                if step in checkpoint_steps:
                    errors.append(_interaction_error(source, f"outcome {issue_key!r} duplicates checkpoint step {step!r}", "record one terminal observation per improvement step"))
                if isinstance(key, str):
                    checkpoint_keys.add(key)
                if isinstance(step, str):
                    checkpoint_steps.add(step)
    if input_keys and not input_keys.issuperset(outcome_by_key):
        errors.append(_interaction_error(source, "outcomes do not have a matching input Issue key", "retain one outcome for each canonical input candidate"))

    plans = data.get("draft_pr_plans")
    actual_plan_ids = {plan.get("plan_id") for plan in plans if isinstance(plan, dict)} if isinstance(plans, list) else set()
    if actual_plan_ids != expected_plan_ids:
        errors.append(_interaction_error(source, "top-level draft_pr_plans do not match outcome plans", "keep the plan index deterministic and traceable"))
    return errors


def validate_interaction_e2e(
    data: dict,
    manifest: dict | None = None,
    source: str = "interaction-e2e",
) -> list[str]:
    """Validate the networkless frontstage/backstage integration proof."""
    errors: list[str] = []
    schema = load_json(INTERACTION_E2E_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the interaction E2E field")
        for schema_error in _schema_errors(data, schema)
    )
    errors.extend(_scan_forbidden_retrieval_fields(data, source))
    if not isinstance(data, dict):
        return errors
    repositories = _retrieval_manifest_index(manifest)
    known = set(repositories)
    snapshots: dict[str, str] = {}
    retrieval = data.get("retrieval", {})
    if isinstance(retrieval, dict):
        for index, snapshot in enumerate(retrieval.get("source_snapshots", [])):
            if not isinstance(snapshot, dict):
                continue
            repository = snapshot.get("repository")
            commit = snapshot.get("commit")
            if repository in snapshots:
                errors.append(_interaction_error(source, f"retrieval source snapshot duplicates {repository!r}", "record one immutable snapshot per repository"))
            if repository not in known:
                errors.append(_interaction_error(source, f"retrieval source snapshot names unknown repository {repository!r}", "use manifest repository IDs"))
            if isinstance(repository, str):
                snapshots[repository] = commit
                if repository in repositories and commit != repositories[repository].get("observed_commit"):
                    errors.append(_interaction_error(source, f"retrieval source snapshot {repository!r} is not pinned to the manifest commit", "preserve the immutable input snapshot"))
    artifact = data.get("artifact", {})
    artifact_snapshots = artifact.get("source_snapshots", []) if isinstance(artifact, dict) else []
    for snapshot in artifact_snapshots:
        if not isinstance(snapshot, dict):
            continue
        repository = snapshot.get("repository")
        commit = snapshot.get("commit")
        if repository not in snapshots or snapshots.get(repository) != commit:
            errors.append(_interaction_error(source, f"artifact snapshot {repository!r} does not match retrieval provenance", "carry the same repository@commit into the artifact envelope"))
    if isinstance(artifact, dict):
        if artifact.get("artifact_id") not in data.get("interaction", {}).get("artifact_refs", []):
            errors.append(_interaction_error(source, "artifact is not referenced by the interaction outcome", "retain the immutable artifact reference in the experience event"))
        evidence_refs = artifact.get("evidence_refs", [])
        retrieval_evidence = set(retrieval.get("evidence_ids", [])) if isinstance(retrieval, dict) else set()
        if not set(evidence_refs).issubset(retrieval_evidence):
            errors.append(_interaction_error(source, "artifact evidence is not present in retrieval output", "preserve evidence lineage from retrieval to artifact"))
    interaction = data.get("interaction", {})
    if isinstance(interaction, dict):
        if set(interaction.get("artifact_refs", [])) != {artifact.get("artifact_id")}:
            errors.append(_interaction_error(source, "interaction artifact references are inconsistent", "record exactly the created immutable artifact"))
        if interaction.get("raw_conversation_stored") is not False or interaction.get("direct_identifiers_stored") is not False:
            errors.append(_interaction_error(source, "interaction privacy boundary is not closed", "keep raw conversation and direct identifiers outside Git"))
    feedback = data.get("feedback", {})
    if isinstance(feedback, dict) and feedback.get("promoted_to_user_fact") is not False:
        errors.append(_interaction_error(source, "feedback was promoted to user fact", "keep inferred feedback as an unconfirmed hypothesis"))
    routing = data.get("routing", {})
    if isinstance(routing, dict) and routing.get("issue_operations") != []:
        errors.append(_interaction_error(source, "interaction E2E attempted a remote Issue operation", "keep Issue routing metadata-only until a human gate"))
    improvement = data.get("improvement", {})
    if isinstance(improvement, dict) and improvement.get("remote_operations") != []:
        errors.append(_interaction_error(source, "interaction E2E attempted a remote improvement operation", "keep draft PR planning metadata-only"))
    audit = data.get("audit", {})
    if isinstance(audit, dict) and (audit.get("lane") != "ASYNC_AUDIT" or audit.get("interaction_blocking") is not False or audit.get("artifact_operations") != []):
        errors.append(_interaction_error(source, "audit is not independent and read-only", "run audit on its own non-blocking lane"))
    acceptance = data.get("acceptance", {})
    if isinstance(acceptance, dict) and any(value is not True for value in acceptance.values()):
        errors.append(_interaction_error(source, "interaction E2E acceptance is incomplete", "preserve every frontstage/backstage safety invariant"))
    return errors


def validate_agent_ui_result(data: dict, source: str = "agent-ui") -> list[str]:
    """Validate the closed metadata envelope emitted by the initial UI command."""
    errors: list[str] = []
    schema = load_json(AGENT_UI_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the agent UI result field")
        for schema_error in _schema_errors(data, schema)
    )
    errors.extend(_scan_forbidden_retrieval_fields(data, source))
    if not isinstance(data, dict):
        return errors
    startup = data.get("startup", {})
    if isinstance(startup, dict) and startup.get("status") != data.get("status"):
        errors.append(_interaction_error(source, "agent UI status does not match startup status", "do not expose capabilities beyond the startup decision"))
    answer = data.get("answer", {})
    sources = answer.get("sources", []) if isinstance(answer, dict) else []
    known = _known_repository_ids() | {"agentic-art-orchestration"}
    seen: set[str] = set()
    if isinstance(sources, list):
        for index, source_item in enumerate(sources):
            if not isinstance(source_item, dict):
                continue
            repository = source_item.get("repository")
            commit = source_item.get("commit")
            if repository in seen:
                errors.append(_interaction_error(source, f"answer.sources[{index}] duplicates {repository!r}", "emit one repository@commit source record"))
            if repository not in known:
                errors.append(_interaction_error(source, f"answer.sources[{index}] names unknown repository", "use only manifest repository IDs"))
            seen.add(repository)
            if source_item.get("repository_at_commit") != f"{repository}@{commit}":
                errors.append(_interaction_error(source, f"answer.sources[{index}] repository@commit is inconsistent", "render the immutable source commit explicitly"))
    artifact = data.get("artifact", {})
    if isinstance(artifact, dict) and artifact.get("requested") is False:
        if any(artifact.get(field) is not None for field in ("artifact_id", "provider_file_id", "content_hash")):
            errors.append(_interaction_error(source, "not-requested artifact contains a provider reference", "keep absent outputs null"))
    feedback = data.get("feedback", {})
    if isinstance(feedback, dict) and not set(feedback.get("inferred_ids", [])).isdisjoint(set(feedback.get("explicit_ids", []))):
        errors.append(_interaction_error(source, "feedback is both explicit and inferred", "preserve the distinction between observed request and hypothesis"))
    privacy = data.get("privacy", {})
    if isinstance(privacy, dict) and any(privacy.get(field) is not False for field in ("raw_query_stored", "raw_conversation_stored", "drive_content_stored", "credentials_stored", "direct_identifiers_stored")):
        errors.append(_interaction_error(source, "agent UI privacy boundary is open", "store only structured metadata and opaque references"))
    return errors


def validate_initial_operations_e2e(data: dict, source: str = "initial-operations-e2e") -> list[str]:
    """Validate the closed networkless initial operations evidence envelope."""
    errors: list[str] = []
    schema = load_json(INITIAL_OPERATIONS_E2E_SCHEMA_PATH)
    errors.extend(
        _interaction_error(source, schema_error, "correct the initial operations E2E field")
        for schema_error in _schema_errors(data, schema)
    )
    errors.extend(_scan_forbidden_retrieval_fields(data, source))
    if not isinstance(data, dict):
        return errors
    startup = data.get("startup", {})
    if isinstance(startup, dict) and startup.get("ordered_step_count") != 9:
        errors.append(_interaction_error(source, "startup preflight is incomplete", "run all nine read-only startup steps"))
    retrieval = data.get("retrieval", {})
    if isinstance(retrieval, dict):
        for index, source_item in enumerate(retrieval.get("sources", [])):
            if not isinstance(source_item, dict):
                continue
            repository_at_commit = source_item.get("repository_at_commit", "")
            repository = source_item.get("repository")
            if repository not in repository_at_commit or "@" not in repository_at_commit:
                errors.append(_interaction_error(source, f"retrieval.sources[{index}] lacks repository@commit", "retain immutable source provenance in the answer"))
    drive = data.get("drive", {})
    if isinstance(drive, dict) and drive.get("operation_sequence") != ["READ", "CREATE", "READ", "READ", "READ"]:
        errors.append(_interaction_error(source, "Drive operation sequence is not create/read/replay-only", "keep replay as a marker search and read-back without a second CREATE"))
    issue = data.get("issue", {})
    if isinstance(issue, dict):
        if issue.get("create", {}).get("target_repository") != issue.get("reuse", {}).get("target_repository"):
            errors.append(_interaction_error(source, "Issue CREATE/REUSE targets differ", "reuse the same authoritative deduplication target"))
    if data.get("network") != "disabled" or data.get("remote_operations") != []:
        errors.append(_interaction_error(source, "initial operations E2E has remote operations", "keep the qualification path networkless and use a separate opt-in live gate"))
    live_gate = data.get("live_gate", {})
    if isinstance(live_gate, dict) and live_gate.get("status") != "NOT_REQUESTED":
        errors.append(_interaction_error(source, "live gate was implicitly executed", "require an explicit sandbox and human confirmation before live operations"))
    acceptance = data.get("acceptance", {})
    if isinstance(acceptance, dict) and any(value is not True for value in acceptance.values()):
        errors.append(_interaction_error(source, "initial operations E2E acceptance is incomplete", "preserve every startup, provenance, idempotency, and privacy invariant"))
    return errors


def validate_work_item(data: dict, source: str = "work-item") -> list[str]:
    """Validate a resumable cross-repository work item and its safety rules."""
    errors: list[str] = []
    schema = load_json(WORKITEM_SCHEMA_PATH)
    errors.extend(
        _signal_error(source, schema_error, "correct the work item field")
        for schema_error in _schema_errors(data, schema)
    )
    if not isinstance(data, dict):
        return errors

    manifest = load_yaml(MANIFEST_PATH)
    repositories = manifest.get("repositories", []) if isinstance(manifest, dict) else []
    known_repositories = {
        repo.get("id") for repo in repositories if isinstance(repo, dict)
    }
    known_repositories.add("agentic-art-orchestration")
    owner = data.get("owner_repository")
    targets = data.get("target_repositories")
    if owner not in known_repositories:
        errors.append(
            _signal_error(
                source,
                f"owner_repository {owner!r} is not declared",
                "use a repository ID from config/repositories.yaml",
            )
        )
    if isinstance(targets, list):
        for index, repository in enumerate(targets):
            if repository not in known_repositories:
                errors.append(
                    _signal_error(
                        source,
                        f"target_repositories[{index}] {repository!r} is not declared",
                        "use only manifest repository IDs",
                    )
                )
        if owner not in targets:
            errors.append(
                _signal_error(
                    source,
                    "owner_repository must be included in target_repositories",
                    "make the owner an explicit target of the work item",
                )
            )

    allowed_paths = data.get("allowed_paths")
    if isinstance(allowed_paths, list):
        if len(allowed_paths) != len(set(allowed_paths)):
            errors.append(
                _signal_error(
                    source,
                    "allowed_paths must be unique",
                    "declare each writable path once",
                )
            )
        for index, path in enumerate(allowed_paths):
            if not _is_safe_relative_path(path):
                errors.append(
                    _signal_error(
                        source,
                        f"allowed_paths[{index}] is not a safe relative path",
                        "remove absolute paths and . or .. segments",
                    )
                )

    dependencies = data.get("depends_on")
    if isinstance(dependencies, list):
        if len(dependencies) != len(set(dependencies)):
            errors.append(
                _signal_error(
                    source,
                    "depends_on must be unique",
                    "declare each dependency once",
                )
            )
        if data.get("id") in dependencies:
            errors.append(
                _signal_error(
                    source,
                    "work item cannot depend on itself",
                    "remove the self dependency and keep the task DAG acyclic",
                )
            )

    checks = data.get("checks")
    if isinstance(checks, list):
        for index, check in enumerate(checks):
            if not isinstance(check, dict):
                continue
            repository = check.get("repository")
            if repository not in known_repositories:
                errors.append(
                    _signal_error(
                        source,
                        f"checks[{index}].repository {repository!r} is not declared",
                        "run each check in a manifest repository",
                    )
                )
            command = check.get("command")
            if isinstance(command, str) and any(token in command for token in COMMAND_FORBIDDEN_TOKENS):
                errors.append(
                    _signal_error(
                        source,
                        f"checks[{index}].command contains shell control syntax",
                        "split checks into separate safe commands",
                    )
                )

    attempts = data.get("attempts")
    if isinstance(attempts, dict):
        used = attempts.get("used")
        maximum = attempts.get("max")
        if isinstance(used, int) and isinstance(maximum, int) and used > maximum:
            errors.append(
                _signal_error(
                    source,
                    "attempts.used cannot exceed attempts.max",
                    "record the actual retry count within the declared retry budget",
                )
            )
        config = load_yaml(ROOT / "config/orchestration.yaml")
        configured_max = config.get("execution", {}).get("max_attempts")
        if isinstance(maximum, int) and isinstance(configured_max, int) and maximum > configured_max:
            errors.append(
                _signal_error(
                    source,
                    f"attempts.max {maximum} exceeds configured max_attempts {configured_max}",
                    "use the repository retry budget or update policy explicitly",
                )
            )

    lease = data.get("lease")
    terminal_state = data.get("terminal_state")
    if isinstance(lease, dict):
        if lease.get("status") == "available" and lease.get("owner") != "unassigned":
            errors.append(
                _signal_error(
                    source,
                    "available lease must have owner 'unassigned'",
                    "clear the lease owner before returning the item to the queue",
                )
            )
        if lease.get("status") == "held" and lease.get("owner") == "unassigned":
            errors.append(
                _signal_error(
                    source,
                    "held lease must identify its owner",
                    "record the active worker owner and expiry",
                )
            )
        if terminal_state in {"READY", "BACKLOG"} and lease.get("status") == "held":
            errors.append(
                _signal_error(
                    source,
                    "queued work item cannot retain a held lease",
                    "release the lease before returning to BACKLOG or READY",
                )
            )

    evidence = data.get("evidence")
    if terminal_state == "DONE" and isinstance(evidence, dict):
        if not evidence.get("tests"):
            errors.append(
                _signal_error(
                    source,
                    "DONE work item requires test evidence",
                    "record the observed test commands before marking DONE",
                )
            )
        if not evidence.get("commits"):
            errors.append(
                _signal_error(
                    source,
                    "DONE work item requires commit evidence",
                    "record the repository commit SHA or keep the item non-terminal",
                )
            )
    return errors


def validate_repositories(errors: list[str], manifest_path: Path = MANIFEST_PATH) -> None:
    data = load_yaml(manifest_path)
    errors.extend(validate_manifest(data, _source_label(manifest_path)))


def validate_tasks(errors: list[str]) -> None:
    data = load_yaml(ROOT / "execution/task-queue.yaml")
    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    ids = [task.get("id") for task in tasks]
    if len(ids) != len(set(ids)):
        errors.append("execution/task-queue.yaml: task IDs must be unique")
    by_id = {task.get("id"): task for task in tasks}
    for task in tasks:
        task_id = task.get("id", "<missing>")
        for field in ("milestone", "title", "status", "depends_on", "acceptance", "checks"):
            if field not in task:
                errors.append(f"execution/task-queue.yaml: {task_id}.{field} is required")
        if task.get("status") not in STATUSES:
            errors.append(f"execution/task-queue.yaml: {task_id}.status is unknown")
        deps = task.get("depends_on", [])
        for dep in deps:
            if dep not in by_id:
                errors.append(f"execution/task-queue.yaml: {task_id} depends on missing {dep}")
        if task.get("status") == "READY":
            incomplete = [dep for dep in deps if by_id.get(dep, {}).get("status") != "DONE"]
            if incomplete:
                errors.append(f"execution/task-queue.yaml: {task_id} READY with incomplete {incomplete}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str, chain: list[str]) -> None:
        if task_id in visiting:
            errors.append(f"execution/task-queue.yaml: cycle {' -> '.join(chain + [task_id])}")
            return
        if task_id in visited or task_id not in by_id:
            return
        visiting.add(task_id)
        for dep in by_id[task_id].get("depends_on", []):
            visit(dep, chain + [task_id])
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id, [])


def validate(manifest_path: Path = MANIFEST_PATH) -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            errors.append(f"{rel}: required file is missing")
    if errors:
        return errors
    try:
        validate_repositories(errors, manifest_path)
        validate_tasks(errors)
        errors.extend(
            validate_research_execution_boundary(
                load_yaml(V12_BOUNDARY_CONFIG_PATH),
                _source_label(V12_BOUNDARY_CONFIG_PATH),
            )
        )
        errors.extend(
            validate_transformation_rule_registry(
                load_yaml(TRANSFORMATION_RULE_CONFIG_PATH),
                _source_label(TRANSFORMATION_RULE_CONFIG_PATH),
            )
        )
        errors.extend(
            validate_startup_contract(
                load_yaml(STARTUP_POLICY_PATH),
                load_json(STARTUP_REPORT_SCHEMA_PATH),
                _source_label(STARTUP_POLICY_PATH),
                _source_label(STARTUP_REPORT_SCHEMA_PATH),
            )
        )
        errors.extend(
            validate_issue_delivery_contract(
                load_yaml(ISSUE_DELIVERY_POLICY_PATH),
                load_json(ISSUE_DELIVERY_SCHEMA_PATH),
                load_yaml(manifest_path),
                _source_label(ISSUE_DELIVERY_POLICY_PATH),
                _source_label(ISSUE_DELIVERY_SCHEMA_PATH),
            )
        )
        errors.extend(
            validate_drive_live_contract(
                load_yaml(DRIVE_LIVE_POLICY_PATH),
                load_json(DRIVE_LIVE_SCHEMA_PATH),
                _source_label(DRIVE_LIVE_POLICY_PATH),
                _source_label(DRIVE_LIVE_SCHEMA_PATH),
            )
        )
        errors.extend(
            validate_github_sandbox_live_contract(
                load_yaml(GITHUB_SANDBOX_LIVE_POLICY_PATH),
                load_json(GITHUB_SANDBOX_LIVE_SCHEMA_PATH),
                load_yaml(manifest_path),
                _source_label(GITHUB_SANDBOX_LIVE_POLICY_PATH),
                _source_label(GITHUB_SANDBOX_LIVE_SCHEMA_PATH),
            )
        )
        state = load_yaml(ROOT / "execution/state.yaml")
        if state.get("last_completed_task") is None:
            errors.append("execution/state.yaml: last_completed_task is required")
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate orchestration bootstrap")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help="manifest YAML to validate (defaults to config/repositories.yaml)",
    )
    args = parser.parse_args()
    manifest_path = args.manifest if args.manifest.is_absolute() else Path.cwd() / args.manifest
    errors = validate(manifest_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: orchestration bootstrap is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
