from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_fresh_clone_bootstrap_is_canonical_and_venv_based(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        canonical = "\n".join(
            (
                "python3 -m venv .venv",
                ".venv/bin/pip install -r requirements-dev.txt",
                ".venv/bin/python tools/validate.py --check",
                ".venv/bin/python -m unittest discover -s tests -v",
            )
        )
        self.assertIn(canonical, readme)
        self.assertIn("tools/workspace.py init --offline-fixture --fixture-root", readme)
        self.assertIn("tools/interaction_e2e.py", readme)
        self.assertIn("README.md#ブートストラップ検証", agents)
        self.assertIn("README.md#ブートストラップ検証", runbook)
        self.assertNotIn("python3 tools/validate.py --check", agents)
        self.assertNotIn("python3 -m unittest discover -s tests -v", agents)
        self.assertNotIn("python3 tools/validate.py --check", readme)
        self.assertNotIn("python3 -m unittest discover -s tests -v", readme)
        self.assertNotIn("python3 tools/batch_status.py", runbook)

    def test_observation_provenance_contract_and_decision_template_are_present(self):
        contract = (ROOT / "docs/cross-repository-contract.md").read_text(encoding="utf-8")
        template = (ROOT / ".github/ISSUE_TEMPLATE/decision.yml").read_text(encoding="utf-8")
        for required in (
            "## Observation provenance",
            "`repository`",
            "`observed_ref`",
            "`observed_via`",
            "`observed_at`",
            "`manifest_pin` / `remote_head` / `local_worktree`",
            "source_repository",
            "source_commit",
            "evidence_locator",
            "unknowns",
            "execution/state.yaml",
        ):
            self.assertIn(required, contract)
        for required in (
            "Decision with observation provenance",
            "observed_ref",
            "observed_via",
            "observed_at",
            "evidence_locator",
            "unknowns",
            "manifest_pin",
            "remote_head",
            "local_worktree",
        ):
            self.assertIn(required, template)

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

    def test_execution_ssot_is_pushed_before_lease_release(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        self.assertIn("lease解放前に作業branchからoriginへ通常のfast-forward push", agents)
        self.assertIn("force pushと既定branchへの直接pushは禁止", agents)
        self.assertIn("実行SSOTを作業branchへfast-forward push", runbook)
        self.assertIn("git push origin <working-branch>", runbook)
        self.assertIn("UNKNOWN", runbook)

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

    def test_public_projection_is_operable_without_conversation_history(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs/agent-runtime-guide.md").read_text(encoding="utf-8")
        gates = (ROOT / "config/human-gates.yaml").read_text(encoding="utf-8")
        combined = "\n".join((readme, runbook, guide, gates))
        for required in (
            "tools/public_projection.py prepare",
            "tools/public_projection.py init-target",
            "tools/public_projection.py project",
            "--target-root",
            "--dry-run",
            "--apply",
            "public-projection-approval/v1",
            "public_share",
            "local-public-project-projection",
            "BLOCKED_HUMAN",
            "BLOCKED_POLICY",
            "BLOCKED_CONFLICT",
            "ALREADY_PROJECTED",
            "public-projection-result.json",
            "catalog marker",
            "commit、push、merge、release",
            "tests.test_public_projection",
        ):
            self.assertIn(required, combined)
        self.assertNotIn("approvalなしでapply", combined)
        self.assertNotIn("自動公開する", combined)

    def test_public_share_gate_scope_is_closed_and_layout_only_init_is_distinct(self):
        gates = (ROOT / "config/human-gates.yaml").read_text(encoding="utf-8")
        self.assertIn("operation_scopes:", gates)
        self.assertIn("tools/public_projection.py project --apply", gates)
        self.assertIn("tools/public_projection.py init-target --apply", gates)
        self.assertIn("repository_visibility_change", gates)
        self.assertIn("target_git_commit_push_merge_release", gates)

    def test_theme_free_planning_entry_is_explicit_and_fail_closed(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs/agent-runtime-guide.md").read_text(encoding="utf-8")
        run = (ROOT / "tools/run.py").read_text(encoding="utf-8")
        self.assertIn("テーマ未指定で制作計画を始める", readme)
        self.assertIn("--intent`、`--slug`、`--title`を付けず", guide)
        self.assertIn("REPOSITORY_DERIVED", guide)
        self.assertIn("observed_commit", guide)
        self.assertIn("`BLOCKED`", guide)
        self.assertIn("_guard_pinned_workspace", run)
        self.assertIn("テーマを自動提案", run)

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
