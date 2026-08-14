from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_startup_capability_matrix_documents_finding_specific_boundaries(self):
        text = (ROOT / "docs/agent-startup.md").read_text(encoding="utf-8")
        for required in (
            "Startup capability matrix",
            "only `remote_update_candidate`",
            "Parent `branch` / `commit` / `pull_request`",
            "`merge` / `release` / `tag`",
            "human gate",
            "qualified snapshot",
            "RESTRICTED",
        ):
            self.assertIn(required, text)

    def test_operator_runbook_has_complete_lifecycle_and_safety_boundaries(self):
        text = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        for required in (
            "最初の1操作",
            "初期化と検査",
            "taskを実行する",
            "signalから成果物まで",
            "repository-aware conversational retrieval",
            "外部artifactのcreate-only保存",
            "feedbackからIssue候補へのルーティング",
            "Issue-to-draft-PR improvement lane",
            "interaction E2Eと中断再開",
            "非同期audit/refactoring lane",
            "handoffの必須項目",
            "tools/workspace.py init --offline-fixture",
            "tools/status.py --check --offline-fixture",
            "tools/async_auditor.py --run-id AUDITOR-002:attempt-1",
            "tools/retrieval.py --check",
            "tools/issue_router.py --check",
            "tests.test_drive_adapter",
            "tests.test_issue_router",
            "tests.test_retrieval",
            "tools/improvement_loop.py --check",
            "tests.test_improvement_loop",
            "tools/interaction_e2e.py --check",
            "tests.test_interaction_e2e",
            "PRIVATE_RAW",
            "merge/releaseはhuman gate",
        ):
            self.assertIn(required, text)

    def test_incident_runbook_covers_failure_and_resume_paths(self):
        text = (ROOT / "docs/incident-runbook.md").read_text(encoding="utf-8")
        for required in (
            "共通フロー",
            "dirty checkout",
            "signal major mismatch",
            "self consent violation",
            "child quality gate failure",
            "secret / forbidden data",
            "lease expiry",
            "worker process kill",
            "Project API unavailable",
            "BLOCKEDにする停止条件",
            "execution_id",
            "tools/security.py --offline-fixture",
        ):
            self.assertIn(required, text)

    def test_readme_links_operator_and_incident_runbooks(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/operator-runbook.md", text)
        self.assertIn("docs/incident-runbook.md", text)
        self.assertIn("docs/interaction-improvement-runbook.md", text)

    def test_v11_runbook_is_operable_without_conversation_history(self):
        text = (ROOT / "docs/interaction-improvement-runbook.md").read_text(encoding="utf-8")
        for required in (
            "最初の1操作と正本",
            "lane topology",
            "repository-aware retrieval",
            "Google Drive artifact",
            "feedbackとIssue routing",
            "autonomous improvement",
            "非同期audit / refactoring",
            "E2Eと復旧",
            "必須の最終検査とhandoff",
            "tools/retrieval.py --check",
            "tools/issue_router.py --check",
            "tools/improvement_loop.py --check",
            "tools/interaction_e2e.py --check",
            "remote_operations=[]",
            "merge、release",
            "同じexecution ID",
        ):
            self.assertIn(required, text)

    def test_v11_design_defines_interaction_and_continuous_improvement_boundaries(self):
        design = (
            ROOT
            / "docs/20260811-agentic-art-orchestration-system-design-specification.md"
        ).read_text(encoding="utf-8")
        plan = (
            ROOT
            / "docs/20260811-agentic-art-orchestration-repository-execution-plan.md"
        ).read_text(encoding="utf-8")
        decisions = (ROOT / "execution/decisions.md").read_text(encoding="utf-8")
        for required in (
            "Interaction is the product surface",
            "Append-only user artifacts",
            "Inference is not user truth",
            "External artifact contract",
            "Feedback and inferred need contract",
            "Issue routing and continuous improvement",
            "Asynchronous audit/refactoring lane",
            "v1.1.0",
        ):
            self.assertIn(required, design)
        for required in (
            "M7 — Interaction, artifact, feedback, and knowledge contracts",
            "M8 — Conversational retrieval and autonomous improvement",
            "M9 — Interaction E2E and v1.1 qualification",
        ):
            self.assertIn(required, plan)
        for required in ("D-006", "D-007", "D-008", "D-009"):
            self.assertIn(required, decisions)
