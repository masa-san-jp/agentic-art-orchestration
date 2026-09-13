from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "autonomous_plan_acceptance", ROOT / "tools/verify_autonomous_plan_acceptance.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


OWNERS = sorted(MODULE.REQUIRED_OWNERS)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AutonomousPlanAcceptanceTests(unittest.TestCase):
    def _write(self, root: Path, name: str, value: object, *, raw: bool = False) -> Path:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw:
            path.write_text(str(value), encoding="utf-8")
        else:
            path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _ref(self, path: Path) -> dict[str, str]:
        return {"path": str(path), "sha256": _sha(path)}

    def _manifest(self, root: Path) -> Path:
        code_pins = {owner: ("a" * 40) for owner in OWNERS}
        knowledge_pins = {owner: {"ref": "knowledge/test-owner", "commit": "b" * 40} for owner in OWNERS}
        runs = []
        for mode in MODULE.MODES:
            baseline_id = f"{mode}-one"
            for sequence, run_id in ((1, baseline_id), (2, f"{mode}-two")):
                request_sha = hashlib.sha256(run_id.encode()).hexdigest()
                plan = self._write(root, f"{run_id}/production-plan.md", f"plan {run_id}\n", raw=True)
                delivery = self._write(root, f"{run_id}/delivery.json", {"contract_version": "delivery-completion/v1", "target": "project-local", "status": "COMPLETED", "missing": []})
                owner_records = []
                for owner in OWNERS:
                    evidence = self._write(root, f"{run_id}/owners/{owner}.json", {"repository": owner, "observed_commit": code_pins[owner], "status": "PASS"})
                    owner_records.append({"owner": owner, "repository": owner, "observed_commit": code_pins[owner], "status": "PASS", **self._ref(evidence) | {"evidence_path": str(evidence)}})
                # The explicit form above keeps the schema's evidence_path key
                # visible while using one hash helper for every external file.
                for record in owner_records:
                    record["evidence_sha256"] = _sha(Path(record["evidence_path"]))
                    record.pop("path", None)
                    record.pop("sha256", None)
                trace_events = [
                    {"kind": "entrypoint", "source": "README.md"},
                    {"kind": "instruction", "source": "README.md"},
                    {"kind": "instruction", "source": "production-request"},
                    {"kind": "provider_call", "operation": "ollama"},
                    {"kind": "delivery", "operation": "project_local"},
                ]
                trace = self._write(root, f"{run_id}/operation-trace.json", {"contract_version": "agent-operation-trace/v1", "run_id": run_id, "events": trace_events})
                provider_execution = self._write(root, f"{run_id}/provider-execution.json", {
                    "contract_version": "provider-execution-evidence/v1",
                    "run_id": run_id,
                    "mode": mode,
                    "provider_type": "ollama",
                    "model": "qwen3.8:27b",
                    "external_agent": True,
                    "synthetic_identity": True,
                    "identity": {"instance_id": f"instance-{mode}", "creator_id": f"creator-{mode}", "synthetic": True},
                    "invocation": {"command": ["ollama", "run", "qwen3.8:27b"], "exit_code": 0},
                    "events": [
                        {"kind": "provider_request", "request_sha256": request_sha},
                        {"kind": "provider_response", "status": "COMPLETED", "exit_code": 0},
                        {"kind": "harness_result", "status": "COMPLETED", "exit_code": 0, "plan_sha256": _sha(plan)},
                    ],
                })
                if sequence == 1:
                    adoption_evidence = self._write(root, f"{run_id}/adoption.json", {"contract_version": "knowledge-adoption-evidence/v1", "run_id": run_id, "status": "BASELINE"})
                    content_check = self._write(root, f"{run_id}/content-check.json", {"contract_version": "knowledge-adoption-content-check/v1", "run_id": run_id, "status": "BASELINE", "content_checked": True, "adopted_count": 0})
                    adoption = {"status": "BASELINE", **self._ref(adoption_evidence) | {"evidence_path": str(adoption_evidence)}, "content_check_path": str(content_check), "content_check_sha256": _sha(content_check)}
                    adoption["evidence_sha256"] = _sha(adoption_evidence)
                    adoption.pop("path", None)
                    adoption.pop("sha256", None)
                else:
                    source_content = self._write(root, f"{run_id}/source-knowledge.json", '{"record":"baseline"}\n', raw=True)
                    target_content = self._write(root, f"{run_id}/target-knowledge.json", '{"record":"baseline","adopted":"new-step"}\n', raw=True)
                    adoption_evidence = self._write(root, f"{run_id}/adoption.json", {"contract_version": "knowledge-adoption-evidence/v1", "run_id": run_id, "status": "ADOPTED", "source_run_id": baseline_id})
                    content_check = self._write(root, f"{run_id}/content-check.json", {
                        "contract_version": "knowledge-adoption-content-check/v1", "run_id": run_id, "status": "ADOPTED", "content_checked": True,
                        "adopted_count": 1, "changed_decision_or_step": True, "source_content_path": str(source_content), "source_content_sha256": _sha(source_content),
                        "target_content_path": str(target_content), "target_content_sha256": _sha(target_content), "comparisons": [{"id": "new-step", "disposition": "ADOPTED"}],
                    })
                    adoption = {"status": "ADOPTED", "source_run_id": baseline_id, "evidence_path": str(adoption_evidence), "evidence_sha256": _sha(adoption_evidence), "content_check_path": str(content_check), "content_check_sha256": _sha(content_check)}
                identity = {"instance_id": f"instance-{mode}", "creator_id": f"creator-{mode}", "synthetic": True}
                runs.append({
                    "mode": mode, "sequence": sequence, "run_id": run_id, "identity": identity,
                    "inputs": {"entrypoint": "README_DEFAULT", "request_sha256": request_sha, "input_snapshot_sha256": hashlib.sha256(("snapshot-" + run_id).encode()).hexdigest(), "instruction_sources": ["README.md", "production-request"]},
                    "code_pins": code_pins, "knowledge_pins": knowledge_pins,
                    "provider_execution": {"evidence_path": str(provider_execution), "evidence_sha256": _sha(provider_execution)},
                    "artifacts": [{"path": str(plan), "sha256": _sha(plan), "kind": "plan"}],
                    "owner_revalidation": owner_records, "operation_trace": {"path": str(trace), "sha256": _sha(trace), "human_questions": 0, "forbidden_operations": []},
                    "knowledge_adoption": adoption, "delivery": {"path": str(delivery), "sha256": _sha(delivery)}, "human_gate": "NOT_REQUIRED",
                })
        manifest = {
            "contract_version": "autonomous-plan-acceptance/v1", "task": "AP-06", "status": "PASS",
            "provider": {"type": "ollama", "model": "qwen3.8:27b", "available": True, "external_agent": True, "synthetic_identity": True},
            "code_pins": code_pins, "knowledge_pins": knowledge_pins, "runs": runs,
            "acceptance": {"six_runs": True, "owner_revalidation": True, "delivery_completion": True, "zero_human_questions": True, "second_run_adoption": True, "fork_upstream_unchanged": True, "ac11": "PASS"},
            "privacy": {"raw_conversation_stored": False, "credentials_stored": False, "private_raw_stored": False, "restricted_stored": False},
            "human_gates": {"merge": "NOT_RUN", "release": "NOT_RUN", "publication": "NOT_RUN", "physical_work": "NOT_RUN"},
        }
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return path

    def test_manifest_cross_checks_external_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            report = MODULE.verify_manifest(self._manifest(Path(directory)))
        self.assertEqual("PASS", report["status"])
        self.assertEqual(6, report["run_count"])
        self.assertTrue(all(report["checks"].values()))

    def test_manifest_rejects_trace_that_claims_zero_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            trace_path = Path(manifest["runs"][0]["operation_trace"]["path"])
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["events"].append({"kind": "human_question", "source": "agent"})
            trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")
            manifest["runs"][0]["operation_trace"]["sha256"] = _sha(trace_path)
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            report = MODULE.verify_manifest(path)
        self.assertEqual("FAILED", report["status"])
        self.assertTrue(any("human question count" in error for error in report["errors"]))

    def test_provider_unavailable_is_a_valid_not_run_terminal_report(self):
        manifest = {
            "contract_version": "autonomous-plan-acceptance/v1", "task": "AP-06", "status": "NOT_RUN",
            "provider": {"type": "ollama", "model": "qwen3.8:27b", "available": False, "external_agent": True, "synthetic_identity": True},
            "code_pins": {"agentic-art-orchestration": "a" * 40}, "knowledge_pins": {"agentic-art-orchestration": {"ref": "knowledge/test", "commit": "b" * 40}}, "runs": [],
            "acceptance": {"six_runs": False, "owner_revalidation": False, "delivery_completion": False, "zero_human_questions": False, "second_run_adoption": False, "fork_upstream_unchanged": False, "ac11": "NOT_RUN"},
            "privacy": {"raw_conversation_stored": False, "credentials_stored": False, "private_raw_stored": False, "restricted_stored": False},
            "human_gates": {"merge": "NOT_RUN", "release": "NOT_RUN", "publication": "NOT_RUN", "physical_work": "NOT_RUN"},
            "blocker": {"category": "provider", "observed": "provider unavailable", "remediation": "start the configured provider and rerun AP-06"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            report = MODULE.verify_manifest(path)
        self.assertEqual("NOT_RUN", report["status"])
        self.assertEqual("NOT_RUN", report["ac11"])


if __name__ == "__main__":
    unittest.main()
