from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def unwrapped_production_commands(markdown: str) -> list[str]:
    """Inspect each shell/inline invocation, never borrow a wrapper from a neighbour."""
    target = re.compile(r"(?<![\w])(?:tools/)?(run|self_hearing|purpose_e2e)\.py(?=\s|$)")
    problems = []

    def check(command: str) -> None:
        for match in target.finditer(command):
            arguments = re.split(r";|&&|\|", command[match.end():], maxsplit=1)[0]
            if not re.match(r"\s+(?:--|open\b|answer\b|skip\b)", arguments):
                continue  # Bare filenames are references, not invocations.
            if match.group(1) == "purpose_e2e" and "--live-private" not in arguments:
                continue
            if "--offline-fixture" in arguments and "--live-private" not in arguments:
                continue
            prefix = command[:match.start()]
            if not re.search(r"tools/credential_free\.py\s+.*?--state-root\s+\S+\s+--\s+\S*python(?:3)?\s+$", prefix):
                problems.append(command.strip())

    fence = re.compile(r"^[ \t]*(```|~~~)([^\n]*)\n(.*?)^[ \t]*\1[ \t]*$", re.M | re.S)
    for block in fence.finditer(markdown):
        if block.group(2).strip() not in {"", "bash", "sh", "shell", "zsh"}:
            continue
        joined = re.sub(r"\\[ \t]*\n[ \t]*", " ", block.group(3))
        heredoc = None
        for line in joined.splitlines():
            if heredoc:
                if line.strip() == heredoc:
                    heredoc = None
                continue
            for command in re.split(r";|&&|\|\|", line):
                check(command)
            delimiter = re.search(r"<<[ \t]*['\"]?(\w+)['\"]?", line)
            if delimiter:
                heredoc = delimiter.group(1)
    prose = fence.sub("", markdown)
    for command in re.findall(r"`([^`\n]+)`", prose):
        check(command)
    return problems


class DocumentationTests(unittest.TestCase):
    def test_live_documented_commands_use_credential_free_entry(self):
        documents = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md"))]
        for document in documents:
            with self.subTest(document=str(document.relative_to(ROOT))):
                self.assertEqual([], unwrapped_production_commands(document.read_text(encoding="utf-8")))

    def test_command_guard_rejects_unwrapped_invocations_individually(self):
        for invocation in ("tools/run.py --state-root /external/state",
                           "tools/self_hearing.py open --run-id TEST",
                           "tools/self_hearing.py answer TASK --run-id TEST",
                           "tools/self_hearing.py skip TASK --reason skipped",
                           "tools/purpose_e2e.py --live-private --attempt-id live"):
            with self.subTest(invocation=invocation):
                self.assertTrue(unwrapped_production_commands(f"`{invocation}`"))
                wrapped = f".venv/bin/python tools/credential_free.py --state-root /external/state -- \\\n  .venv/bin/python {invocation}"
                self.assertEqual([], unwrapped_production_commands(f"```bash\n{wrapped}\n```"))
                self.assertTrue(unwrapped_production_commands(f"```bash\n{wrapped}\npython3 {invocation}\n```"))
                self.assertTrue(unwrapped_production_commands(f"```bash\n{wrapped}; python3 {invocation}\n```"))
                self.assertTrue(unwrapped_production_commands(f"```bash\n{wrapped} | python3 {invocation}\n```"))
        self.assertEqual([], unwrapped_production_commands("```sh\npython3 tools/run.py --offline-fixture\n```"))
        self.assertTrue(unwrapped_production_commands("```sh\npython3 tools/run.py --offline-fixture\npython3 tools/run.py --run-id LIVE\n```"))
        self.assertTrue(unwrapped_production_commands("```sh\npython3 tools/run.py --run-id LIVE | python3 tools/run.py --offline-fixture\n```"))
        self.assertTrue(unwrapped_production_commands("   ```bash\n   python3 tools/run.py --run-id LIVE\n   ```"))
        self.assertTrue(unwrapped_production_commands("`run.py --run-id LIVE`"))
        self.assertEqual([], unwrapped_production_commands("`tools/batch_run.py --help`"))
        self.assertEqual([], unwrapped_production_commands("`tools/run.py` owns run state."))

    def test_production_entry_requires_no_public_token_and_keeps_private_fallback(self):
        for name in ("AGENTS.md", "docs/agent-runtime-guide.md", "docs/operator-runbook.md", "docs/instance-setup.md"):
            with self.subTest(document=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                for requirement in ("tools/credential_free.py", "--state-root", "PUBLIC", "private", "GH_CONFIG_DIR"):
                    self.assertIn(requirement, text)
        runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        standard, private = runbook.split("#### privateに戻した場合の代替：read-only token", 1)
        self.assertNotIn("gh auth login", standard)
        self.assertIn("gh auth login", private)
        self.assertIn("gh-readonly", private)
        self.assertIn("GH_ENTERPRISE_TOKEN GITHUB_ENTERPRISE_TOKEN", private)

    def test_fresh_clone_bootstrap_is_canonical_and_venv_based(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        prepare = readme.index("python3 -m venv .venv")
        install = readme.index(".venv/bin/pip install -r requirements-dev.txt", prepare)
        bootstrap = readme.index("#### ブートストラップ検証", install)
        snapshot = readme.index("tools/workspace.py snapshot", bootstrap)
        suite = readme.index(".venv/bin/python -m unittest discover -s tests -v", snapshot)
        self.assertLess(prepare, install)
        self.assertLess(snapshot, suite)
        self.assertIn("### 制作 run を回す人／エージェント向け", readme)
        self.assertIn("### このリポジトリを開発する人向け", readme)
        self.assertIn("Python 3.11", readme)
        for command in ("tools/purpose_e2e.py --offline-fixture", "tools/self_hearing.py open",
                        "tools/self_hearing.py answer", "tools/self_hearing.py skip", "tools/run.py --run-id"):
            self.assertIn(command, readme)
        self.assertIn("回答を一時ファイルに書かず", readme)
        self.assertIn("テーマ・repo名・slug・titleを質問しません", readme)
        self.assertIn("tools/workspace.py init --offline-fixture --fixture-root", readme)
        self.assertIn("tools/interaction_e2e.py", readme)
        self.assertIn("README.md#ブートストラップ検証", agents)
        self.assertIn("README.md#ブートストラップ検証", runbook)
        self.assertNotIn("python3 tools/validate.py --check", agents)
        self.assertNotIn("python3 -m unittest discover -s tests -v", agents)
        self.assertNotIn("python3 tools/validate.py --check", readme)
        self.assertNotIn("python3 -m unittest discover -s tests -v", readme)
        self.assertNotIn("python3 tools/batch_status.py", runbook)

    def test_manifest_workspace_bootstrap_is_operable_and_fail_closed(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runbook = (ROOT / "docs/operator-runbook.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs/agent-runtime-guide.md").read_text(encoding="utf-8")
        combined = "\n".join((readme, runbook, guide))
        for required in (
            "tools/workspace.py bootstrap",
            "--workspace-root",
            "--offline-fixture",
            "--fixture-root",
            "--json",
            "gh auth status --hostname github.com",
            "gh auth setup-git",
            "GIT_TERMINAL_PROMPT=0",
            "config/repositories.yaml.repositories",
            "workspace-bootstrap/v1",
            "tool-owned",
            "same-filesystem",
            "BLOCKED_PIN_DRIFT",
            "BLOCKED_EXISTING_WORKSPACE",
            "BLOCKED_REMOTE_ACCESS",
            "BLOCKED_RACE",
            "CLONE_FAILED",
            "tools/pin_adopt.py --dry-run",
            "tools/pinned_workspace.py",
            "tests.test_workspace_bootstrap",
            "changed_count: 0",
            "remote_operations",
            "child_mutations",
            "既存の`init`、`fetch`、`status`、`guard`、`snapshot`",
        ):
            self.assertIn(required, combined)
        self.assertIn("set +e", combined)
        self.assertIn('test "$BOOTSTRAP_EXIT" -eq 2', combined)
        self.assertIn("credential、token、remote応答本文", combined)
        self.assertNotIn("自動checkoutしてpinを更新", combined)

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
            "project_plan_automatic",
            "project_batch_automatic",
            "AUTOMATIC_PLAN",
            "NOT_REQUIRED",
            "PLAN_READY",
            "PASSED",
            "BLOCKED_CONFIGURATION",
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
