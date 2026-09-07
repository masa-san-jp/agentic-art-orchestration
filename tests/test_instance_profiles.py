import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.instance_profiles import (InstanceProfileError, OWNERS, ROOT,
    adapt_output_destinations, bootstrap, migration_plan, validate_profile)
from tools.knowledge_cycle import LocalOwner
from tools.validate import validate_repository_relationships_contract


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


class InstanceProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "sources" / "code"
        self.source.mkdir(parents=True)
        git(self.source, "init", "-q")
        git(self.source, "config", "user.name", "Synthetic")
        git(self.source, "config", "user.email", "synthetic@example.invalid")
        (self.source / "code.txt").write_text("qualified\n")
        git(self.source, "add", "code.txt")
        git(self.source, "commit", "-qm", "qualified synthetic source")
        self.sha = git(self.source, "rev-parse", "HEAD")
        self.profile = {"contract_version": "instance-profile/v1", "instance_id": "instance-b",
            "creator_id": "creator-b", "mode": "new-clone", "delivery_mode": "internal",
            "personalization_mode": "explicit-profile", "repositories": {},
            "permissions": {"local_knowledge_write": True, "local_git_commit": True,
                            "remote_write": False, "public_projection": False}}
        self.config = {"contract_version": "instance-local-config/v1", "stores": {}, "code_sources": {}, "collections": {
            "shared": {"creator_id": "creator-a", "origin_instance_id": "instance-a", "readers": ["creator-b"]}}}
        for owner in OWNERS:
            store_id = owner + "-b"
            self.profile["repositories"][owner] = {"code_repository": "example/" + owner,
                "code_commit": self.sha, "knowledge_store_id": store_id,
                "knowledge_ref": "knowledge/creator-b", "source_collections": ["shared"]}
            self.config["stores"][store_id] = {"owner": owner, "instance_id": "instance-b",
                "creator_id": "creator-b", "knowledge_ref": "knowledge/creator-b",
                "path": str(self.root / "stores" / owner)}
            self.config["code_sources"]["example/" + owner] = {"path": str(self.source), "qualified_commits": [self.sha]}
        self.state = self.root / "state"
        self.config["output_destinations"] = {"contract_version": "output-destinations/v1", "profile": "local",
            "destinations": {"state_root": str(self.state), "internal_output_root": str(self.root / "internal")}}

    def run_bootstrap(self, **kwargs):
        return bootstrap(self.profile, self.config, self.state, **kwargs)

    def test_aak_04_ac1_modes_reopen_identity_and_empty_personal_history(self):
        for mode in ("new-clone", "fork"):
            with self.subTest(mode=mode):
                p = copy.deepcopy(self.profile); p["mode"] = mode
                if mode == "fork": p.update(origin_instance_id="instance-a", fork_remote="https://github.com/example/fork.git")
                state = self.root / mode / "state"
                config = copy.deepcopy(self.config)
                config["output_destinations"]["destinations"]["state_root"] = str(state)
                for binding in config["stores"].values(): binding["path"] = str(self.root / mode / binding["owner"])
                first = bootstrap(p, config, state)
                p["mode"] = "resume"
                self.assertEqual(first, bootstrap(p, config, state))
                for owner, ref in first["knowledge_refs"].items():
                    store = Path(config["stores"][ref["store_id"]]["path"])
                    self.assertEqual("commit", git(store, "--git-dir=objects.git", "cat-file", "-t", ref["commit"]))
                    self.assertEqual("", git(store, "--git-dir=objects.git", "ls-tree", "-r", ref["commit"]))
                    self.assertEqual("", git(store, "--git-dir=objects.git", "remote"))
                self.assertEqual("creator-a", config["collections"]["shared"]["creator_id"])

    def test_aak_04_ac2_foreign_store_rejected_before_any_write(self):
        self.config["stores"][OWNERS[-1] + "-b"]["creator_id"] = "creator-a"
        with self.assertRaises(InstanceProfileError): self.run_bootstrap()
        self.assertFalse(self.state.exists())
        self.assertFalse((self.root / "stores").exists())

    def test_aak_04_ac2_cannot_adopt_populated_git(self):
        self.config["stores"][OWNERS[0] + "-b"]["path"] = str(self.source)
        with self.assertRaises(InstanceProfileError): self.run_bootstrap()
        self.assertEqual(self.sha, git(self.source, "rev-parse", "HEAD"))

    def test_aak_04_ac2_fork_and_collection_permission_negative(self):
        self.profile["mode"] = "fork"
        self.assertTrue(validate_profile(self.profile))
        self.profile.update(fork_remote="https://github.com/example/fork.git", origin_instance_id="instance-b")
        self.assertTrue(validate_profile(self.profile))
        self.profile["origin_instance_id"] = "instance-a"
        self.config["collections"]["shared"]["readers"] = ["creator-a"]
        with self.assertRaises(InstanceProfileError): self.run_bootstrap()
        self.assertFalse(self.state.exists())

    def test_permissions_paths_and_qualification_fail_closed(self):
        for permission in ("local_git_commit", "local_knowledge_write"):
            p = copy.deepcopy(self.profile); p["permissions"][permission] = False
            with self.assertRaises(InstanceProfileError): bootstrap(p, self.config, self.state)
        config = copy.deepcopy(self.config)
        config["code_sources"]["example/" + OWNERS[0]]["qualified_commits"] = []
        with self.assertRaises(InstanceProfileError): bootstrap(self.profile, config, self.state)
        config = copy.deepcopy(self.config)
        config["stores"][OWNERS[-1] + "-b"]["path"] = config["stores"][OWNERS[0] + "-b"]["path"]
        with self.assertRaises(InstanceProfileError): bootstrap(self.profile, config, self.state)
        self.assertFalse(self.state.exists())

    def test_aak_04_ac3_code_and_knowledge_updates_preserve_previous_run(self):
        first = self.run_bootstrap(run_id="one")
        owner = OWNERS[0]
        store = Path(self.config["stores"][owner + "-b"]["path"])
        provider = LocalOwner(store, owner, owner + "-b", self.sha, creator="creator-b", payload_validator=lambda *_: False)
        parent = provider.knowledge_commit
        tree = provider._git(["rev-parse", parent + "^{tree}"]).decode().strip()
        commit = provider._git(["commit-tree", tree, "-p", parent], b"synthetic owner update").decode().strip()
        provider._git(["update-ref", provider.ref, commit, parent])
        self.assertEqual(first, self.run_bootstrap(run_id="one"))
        second = self.run_bootstrap(run_id="two")
        self.assertEqual(first["code_refs"], second["code_refs"])
        self.assertEqual(commit, second["knowledge_refs"][owner]["commit"])
        (self.source / "code.txt").write_text("qualified next version\n")
        git(self.source, "commit", "-am", "new code")
        new_sha = git(self.source, "rev-parse", "HEAD")
        old_profile = copy.deepcopy(self.profile)
        for owner in OWNERS:
            self.profile["repositories"][owner]["code_commit"] = new_sha
            self.config["code_sources"]["example/" + owner]["qualified_commits"].append(new_sha)
        before = sorted(str(p) for p in self.state.rglob("*"))
        self.run_bootstrap(run_id="three", dry_run=True)
        self.assertEqual(before, sorted(str(p) for p in self.state.rglob("*")))
        with self.assertRaises(InstanceProfileError): self.run_bootstrap(run_id="one")
        third = self.run_bootstrap(run_id="three")
        self.assertEqual(second["knowledge_refs"], third["knowledge_refs"])
        self.assertEqual({}, migration_plan(second, third)["knowledge_updates"])
        self.assertEqual(first, bootstrap(old_profile, self.config, self.state, run_id="one"))

    def test_aak_04_ac4_cli_without_remote_auth_preserves_dirty_source(self):
        (self.source / "code.txt").write_text("uncommitted user work\n")
        status = git(self.source, "status", "--porcelain")
        p = self.root / "profile.json"; p.write_text(json.dumps(self.profile))
        c = self.root / "local.json"; c.write_text(json.dumps(self.config))
        command = [sys.executable, str(ROOT / "tools/workspace.py"), "bootstrap", "--instance-profile", str(p),
            "--local-config", str(c), "--state-root", str(self.state), "--run-id", "cli"]
        first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, first.returncode, first.stderr)
        second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
        self.assertEqual(status, git(self.source, "status", "--porcelain"))
        self.assertEqual("uncommitted user work\n", (self.source / "code.txt").read_text())

    def test_aak_04_ac5_public_seed_is_not_personalized(self):
        self.profile["personalization_mode"] = "public-seed-only"
        self.assertEqual("UNMET_PUBLIC_SEED_ONLY", self.run_bootstrap()["personalization_status"])

    def test_saved_attribution_and_isolated_checkout_cannot_be_rewritten(self):
        self.run_bootstrap()
        config = copy.deepcopy(self.config)
        config["collections"]["shared"]["creator_id"] = "creator-b"
        with self.assertRaises(InstanceProfileError): bootstrap(self.profile, config, self.state)
        checkout = self.state / "instances/instance-b/runs/setup/code" / OWNERS[0]
        (checkout / "code.txt").write_text("tampered")
        with self.assertRaises(InstanceProfileError): self.run_bootstrap()

    def test_public_projection_requires_destination_and_permission(self):
        self.profile["delivery_mode"] = "public-catalog"
        with self.assertRaises(InstanceProfileError): self.run_bootstrap()
        self.profile["permissions"]["public_projection"] = True
        with self.assertRaises(InstanceProfileError): self.run_bootstrap()
        self.config["output_destinations"]["destinations"]["public_projection_root"] = str(self.root / "public")
        result = self.run_bootstrap()
        self.assertEqual("NOT_RUN", result["projection_status"])
        self.assertFalse((self.root / "public").exists())

    def test_concurrent_bootstrap_lock_and_symlink_rejected(self):
        import fcntl
        self.state.mkdir()
        with (self.state / "instance-bootstrap.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(InstanceProfileError): self.run_bootstrap()
        self.assertFalse((self.state / "instances").exists())
        link = self.root / "link"
        link.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(InstanceProfileError): bootstrap(self.profile, self.config, link)

    def test_interrupted_owner_bootstrap_reuses_successful_store(self):
        original = LocalOwner.__init__
        def interrupt(provider, root, owner, *args, **kwargs):
            if owner == OWNERS[2]: raise InstanceProfileError("synthetic interruption")
            return original(provider, root, owner, *args, **kwargs)
        with patch.object(LocalOwner, "__init__", interrupt):
            with self.assertRaises(InstanceProfileError): self.run_bootstrap()
        store = self.root / "stores" / OWNERS[0]
        saved = git(store, "--git-dir=objects.git", "rev-parse", "refs/heads/knowledge")
        result = self.run_bootstrap()
        self.assertEqual(saved, result["knowledge_refs"][OWNERS[0]]["commit"])

    def test_output_destination_adapter_preserves_legacy_contract(self):
        destinations = {"contract_version": "output-destinations/v1", "profile": "local",
            "destinations": {"state_root": "/state", "internal_output_root": "/internal", "public_projection_root": "/public"}}
        adapted = adapt_output_destinations(self.profile, destinations)
        self.assertNotIn("public_projection_root", adapted["destinations"])
        self.assertIn("public_projection_root", destinations["destinations"])

    def test_dependency_190_registry_rejects_extra_authority(self):
        from tools.validate import load_yaml, REPOSITORY_RELATIONSHIPS_PATH
        self.assertEqual([], validate_repository_relationships_contract())
        registry = load_yaml(REPOSITORY_RELATIONSHIPS_PATH)
        registry["unexpected_authority"] = "input"
        self.assertTrue(validate_repository_relationships_contract(registry=registry))


if __name__ == "__main__": unittest.main()
