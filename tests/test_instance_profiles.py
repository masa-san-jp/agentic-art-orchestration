import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.instance_profiles import InstanceProfileError, OWNERS, adapt_output_destinations, bootstrap, migration_plan, validate_profile

SHA = "1" * 40

def profile(mode="new-clone", creator="creator-b", instance="instance-b"):
    repositories = {owner: {"code_repository": f"example/{owner}", "code_commit": SHA, "knowledge_store_id": f"{owner}-{creator}", "knowledge_ref": f"knowledge/{creator}", "source_collections": ["public-shared"]} for owner in OWNERS}
    value = {"contract_version":"instance-profile/v1", "instance_id":instance, "creator_id":creator, "mode":mode, "delivery_mode":"internal", "personalization_mode":"explicit-profile", "repositories":repositories, "permissions":{"local_knowledge_write":True,"local_git_commit":True,"remote_write":False,"public_projection":False}}
    if mode == "fork": value.update(origin_instance_id="instance-a", upstream_remote="https://github.com/example/upstream.git")
    return value

class InstanceProfileTests(unittest.TestCase):
    def stores(self, root): return {owner: root / owner for owner in OWNERS}

    def test_aak_04_ac1_fresh_modes_and_idempotent_rerun(self):
        for mode in ("new-clone", "fork"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                root=Path(td); p=profile(mode); first=bootstrap(p,self.stores(root/"stores"),root/"state"); second=bootstrap(p,self.stores(root/"stores"),root/"state")
                self.assertEqual(first, second); self.assertEqual("creator-b", first["creator_id"]); self.assertEqual(set(OWNERS), set(first["knowledge_refs"]))
                changed=copy.deepcopy(p); changed["mode"]="resume"
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=profile(); saved=bootstrap(p,self.stores(root/"stores"),root/"state"); resume=copy.deepcopy(p); resume["mode"]="resume"
            self.assertEqual(saved, bootstrap(resume,self.stores(root/"stores"),root/"state"))
            marker=root/"state/instances/instance-b/instance-resolution.json"; marker.write_text(json.dumps({**saved,"profile_fingerprint":"bad"}))
            with self.assertRaises(InstanceProfileError): bootstrap(resume,self.stores(root/"stores"),root/"state")

    def test_aak_04_ac2_rejects_identity_and_fork_boundary_violations(self):
        p=profile(); p["repositories"]["self-model-notes"]["knowledge_ref"]="knowledge/creator-a"
        self.assertTrue(any("active creator" in e for e in validate_profile(p)))
        p=profile("fork"); del p["upstream_remote"]
        self.assertTrue(any("upstream_remote" in e for e in validate_profile(p)))
        p=profile("fork"); p["origin_instance_id"]=p["instance_id"]
        self.assertTrue(any("origin identity" in e for e in validate_profile(p)))

    def test_aak_04_ac3_code_and_knowledge_updates_are_independent(self):
        saved={"creator_id":"creator-b","code_refs":{"x":{"commit":"a"}},"knowledge_refs":{"x":{"commit":"k1"}}}
        code=copy.deepcopy(saved); code["code_refs"]["x"]["commit"]="b"
        self.assertEqual({}, migration_plan(saved,code)["knowledge_updates"])
        knowledge=copy.deepcopy(saved); knowledge["knowledge_refs"]["x"]["commit"]="k2"
        self.assertEqual({}, migration_plan(saved,knowledge)["code_updates"]); self.assertTrue(migration_plan(saved,knowledge)["dry_run"])

    def test_aak_04_ac4_local_clone_needs_no_remote_or_github_auth(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); result=bootstrap(profile(),self.stores(root/"stores"),root/"state")
            self.assertEqual(set(OWNERS),set(result["knowledge_refs"]))
            self.assertTrue(all((root/"stores"/owner/".git").is_dir() for owner in OWNERS))

    def test_aak_04_ac5_public_seed_is_explicitly_not_personalized(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=profile(); p["personalization_mode"]="public-seed-only"
            self.assertEqual("UNMET_PUBLIC_SEED_ONLY",bootstrap(p,self.stores(root/"stores"),root/"state")["personalization_status"])

    def test_output_destination_adapter_preserves_legacy_contract(self):
        destinations={"contract_version":"output-destinations/v1","profile":"x","destinations":{"state_root":"/state","internal_output_root":"/internal","public_projection_root":"/public"}}
        adapted=adapt_output_destinations(profile(),destinations)
        self.assertEqual("output-destinations/v1",adapted["contract_version"]); self.assertNotIn("public_projection_root",adapted["destinations"])

if __name__ == "__main__": unittest.main()
