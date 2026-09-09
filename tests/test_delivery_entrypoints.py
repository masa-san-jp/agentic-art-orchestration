"""Requested-delivery entrypoint regressions (no provider or network required)."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import knowledge_cycle_run as cycle


class CycleDeliveryEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cycle-delivery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path("/private/tmp/aa217-project")
        if not (source / ".git").exists() or not (source / "public-project.yaml").is_file():
            self.skipTest("qualified Project checkout is unavailable")
        self.project = self.root / "project"
        subprocess.run(["git", "clone", "-q", str(source), str(self.project)], check=True)

    def _profile_and_context(self):
        owners = cycle.OWNERS
        creator = "cycle-test-creator"
        profile = {
            "contract_version": "instance-profile/v1", "instance_id": "cycle-test-instance",
            "origin_instance_id": "cycle-test-origin", "creator_id": creator,
            "mode": "new-clone", "delivery_mode": "public-catalog",
            "personalization_mode": "explicit-profile", "permissions": {
                "local_knowledge_write": True, "local_git_commit": True,
                "remote_write": False, "public_projection": True,
            }, "repositories": {},
        }
        local = {
            "contract_version": "instance-local-config/v1", "stores": {},
            "code_sources": {}, "collections": {},
            "output_destinations": {
                "contract_version": "output-destinations/v1", "profile": "legacy",
                "destinations": {"state_root": str(self.root / "legacy-state"),
                                 "internal_output_root": str(self.root / "legacy-internal"),
                                 "public_projection_root": str(self.root / "legacy-public")},
            },
        }
        for owner in owners:
            store_id = owner + "-store"
            profile["repositories"][owner] = {
                "code_repository": "synthetic/" + owner, "code_commit": "a" * 40,
                "knowledge_store_id": store_id, "knowledge_ref": "knowledge/" + creator,
                "source_collections": [],
            }
            local["stores"][store_id] = {
                "owner": owner, "instance_id": profile["instance_id"],
                "creator_id": creator, "knowledge_ref": "knowledge/" + creator,
                "path": str(self.root / "stores" / owner),
            }
        profile_path = self.root / "profile.json"
        local_path = self.root / "local.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        local_path.write_text(json.dumps(local), encoding="utf-8")
        query_inputs = {owner: str(self.root / (owner + "-query.json")) for owner in owners}
        write_inputs = {owner: str(self.root / (owner + "-write.json")) for owner in owners if owner != "agentic-art-project"}
        context = {
            "contract_version": "knowledge-cycle-context/v1", "run_id": "CYCLEV2",
            "instance_profile": str(profile_path), "local_config": str(local_path),
            "clock": "2026-09-10T00:00:00Z",
            "production_project_root": str(self.project / ".agentic-art" / "internal" / "production" / "project"),
            "query_inputs": query_inputs, "write_inputs": write_inputs,
            "project_root": str(self.project),
            "delivery_contract": {"contract_version": "delivery-contract/v1", "target": "project-local"},
        }
        return profile, local, context

    def test_cycle_context_project_root_replaces_legacy_destinations_before_bootstrap(self):
        _profile, _local, context = self._profile_and_context()
        state_root = self.project / ".agentic-art" / "state"
        observed = {}

        def fake_bootstrap(profile, local, state, **kwargs):
            observed["local"] = copy.deepcopy(local)
            observed["state"] = Path(state)
            from tools.repo_local_destinations import resolve_project_root
            return {"destination_resolution": resolve_project_root(self.project, run_id=context["run_id"])}

        with patch.object(cycle, "bootstrap", side_effect=fake_bootstrap), \
                patch.object(cycle, "checked_code"), patch.object(cycle, "_advance"):
            result = cycle.advance(context, state_root)

        self.assertEqual("output-destinations/v2", observed["local"]["output_destinations"]["contract_version"])
        self.assertEqual(str(self.project), observed["local"]["output_destinations"]["project_root"])
        self.assertEqual(state_root.resolve(), observed["state"].resolve())
        self.assertEqual("project-local", result["delivery_contract"]["target"])
        saved = json.loads((state_root / "knowledge-cycles" / "CYCLEV2" / "context.json").read_text())
        self.assertEqual(str(self.project), saved["project_root"])

    def test_project_local_target_without_project_root_fails_closed(self):
        _profile, _local, context = self._profile_and_context()
        context.pop("project_root")
        with patch.object(cycle, "checked_code"):
            with self.assertRaisesRegex(ValueError, "PROJECT_ROOT_REQUIRED"):
                cycle.advance(context, self.root / "state")


if __name__ == "__main__":
    unittest.main()
