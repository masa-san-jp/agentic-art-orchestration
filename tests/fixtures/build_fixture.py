#!/usr/bin/env python3
"""Build and evaluate the complete four-repository offline failure fixture."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.adapters import adapt_marketing_signal
from tools.audit import build_audit
from tools.security import check_export
from tools.validate import load_yaml, validate_signal
from tools.workspace import (
    expected_remote,
    guard_repository,
    init_workspace,
    load_manifest,
    read_repo_status,
    run_git,
)


class FixtureBuildError(RuntimeError):
    """The offline fixture could not prove one of its scenarios."""


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise FixtureBuildError(detail)


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _commit(path: Path, filename: str, content: str, message: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    run_git(["add", filename], cwd=path)
    run_git(
        [
            "-c",
            "user.name=offline-fixture",
            "-c",
            "user.email=offline-fixture@example.invalid",
            "commit",
            "-m",
            message,
        ],
        cwd=path,
    )


def _make_remote_only_commit(remote: Path, root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="remote-writer-", dir=root) as temporary:
        checkout = Path(temporary) / "checkout"
        run_git(["clone", str(remote), str(checkout)])
        _commit(checkout, "remote-only.txt", "remote\n", "Remote-only fixture change")
        run_git(["push", "origin", "main"], cwd=checkout)


def _signal_scenarios() -> dict:
    marketing = _load_json(ROOT / "tests/fixtures/signal/valid_marketing.json")
    stale = copy.deepcopy(marketing)
    stale["freshness"]["status"] = "stale"
    stale["validity"]["status"] = "stale"
    stale["domain"]["marketing"]["freshness"] = "stale"
    stale["constraints"] = list(stale["constraints"]) + ["Revalidate stale fixture before use."]
    stale["domain"]["marketing"]["prediction_status"] = "pending"
    stale_errors = validate_signal(stale, "fixture:stale")
    incompatible = copy.deepcopy(marketing)
    incompatible["contract_version"] = "normalized-research-signal/v2"
    incompatible_errors = validate_signal(incompatible, "fixture:incompatible")
    self_signal = _load_json(ROOT / "tests/fixtures/signal/valid_self.json")
    privacy = copy.deepcopy(self_signal)
    privacy["domain"]["self_model"]["export_permitted"] = False
    privacy_findings = check_export(privacy, "fixture:privacy")
    return {
        "stale": {"observed": bool(stale_errors) or stale["freshness"]["status"] == "stale", "validator_errors": len(stale_errors)},
        "incompatible": {"observed": bool(incompatible_errors), "validator_errors": len(incompatible_errors)},
        "privacy": {"observed": any(item["code"] == "unapproved-export" for item in privacy_findings), "finding_codes": sorted({item["code"] for item in privacy_findings})},
    }


def build_fixture() -> dict:
    manifest = load_manifest()
    scenario_signals = _signal_scenarios()
    with tempfile.TemporaryDirectory(prefix="agentic-art-orchestration-fixture-") as temporary:
        root = Path(temporary)
        workspace = root / "repos"
        fixture_root = root / "fixture"
        initialized = init_workspace(manifest, workspace, True, fixture_root)
        _require(initialized["changed_count"] == 4, "clean scenario did not clone all four synthetic repositories")
        clean_status = [read_repo_status(repository, workspace) for repository in manifest["repositories"]]
        _require(all(record.get("state") == "clean" for record in clean_status), "clean scenario is not clean")

        self_repo = workspace / "self-model-notes"
        (self_repo / "dirty-fixture.txt").write_text("uncommitted fixture\n", encoding="utf-8")
        self_manifest = next(repository for repository in manifest["repositories"] if repository["id"] == "self-model")
        remotes = fixture_root / "remotes"
        dirty_guard = guard_repository(self_manifest, self_repo, expected_remote(self_manifest, remotes))
        _require("dirty" in dirty_guard["reason_codes"], "dirty scenario was not blocked by the Git guard")

        art_repo = workspace / "art-history-notes"
        art_manifest = next(repository for repository in manifest["repositories"] if repository["id"] == "art-history")
        _commit(art_repo, "local-only.txt", "local\n", "Local-only fixture change")
        _make_remote_only_commit(remotes / "art-history.git", root)
        run_git(["fetch", "origin"], cwd=art_repo)
        diverged_guard = guard_repository(art_manifest, art_repo, expected_remote(art_manifest, remotes))
        _require("diverged" in diverged_guard["reason_codes"], "diverged scenario was not blocked by the Git guard")

        task_queue = load_yaml(ROOT / "execution/task-queue.yaml")
        state = load_yaml(ROOT / "execution/state.yaml")
        snapshot = _load_json(ROOT / "data/snapshot.json")
        portfolio = _load_json(ROOT / "tests/fixtures/portfolio/portfolio.json")
        signals = [_load_json((ROOT / "tests/fixtures/portfolio" / relative).resolve()) for relative in portfolio["signal_files"]]
        audit = build_audit(manifest, snapshot, task_queue, state, signals, portfolio["requirements"], {"fixture": True})
        _require(audit["blocking"] is False, "audit fixture unexpectedly became blocking")
        return {
            "version": 1,
            "network": "disabled",
            "repositories": sorted(repository["id"] for repository in manifest["repositories"]),
            "scenarios": {
                "clean": {"observed": True, "repository_count": len(clean_status)},
                "stale": scenario_signals["stale"],
                "dirty": {"observed": True, "guard_reason": "dirty"},
                "diverged": {"observed": True, "guard_reason": "diverged"},
                "incompatible": scenario_signals["incompatible"],
                "privacy": scenario_signals["privacy"],
            },
            "audit_non_blocking": audit["blocking"] is False,
        }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build and check the offline four-repository fixture")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        first = build_fixture()
        if args.check and first != build_fixture():
            raise FixtureBuildError("offline fixture result is not deterministic")
    except (FixtureBuildError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
