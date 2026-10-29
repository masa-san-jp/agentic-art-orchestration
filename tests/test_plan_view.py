"""Installation-view step: a fake generator, a temporary Project target, the real projection transaction."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import yaml

from tests import test_public_projection as regression
from tests.test_public_projection import synthetic_owner_boundary
from tools import plan_view
from tools import public_projection as p


PLAN = """# 制作プラン

## 1. 完成像

| 項目 | 内容 |
|---|---|
| position | 鑑賞者は床の白いテープの線の上に立つ。 |
| first_seconds | 壁の小さな色の点が目の中で混ざって見える。 |

## 4. コンセプト

| 項目 | 内容 |
|---|---|
| mechanism | 緑と赤で印した費用シートで安定箇所と予備枠の関係を理解する。 |

## 5. 調査の要約

| 項目 | 内容 |
|---|---|
| 仮説タイトル | 点描に学ぶ試し塗り |

## 8. 技術仕様・材料・資源

| ID | 種類 | 仕様 | 値 | 確認 | 根拠 | 状態 |
|---|---|---|---|---|---|---|
| TS005 | method-dimensions-1 | kind=QUANTITY, statement=展示空間は約3m×4m、キャンバスは縦30cm×横40cm。, quantity=value=3, unit=m | 未設定 | 寸法を確かめる。 | なし | PROVISIONAL |
| TS008 | method-materials | kind=QUALITATIVE, statement=綿布張りの木製パネルに白色ジェッソ下地。 | 未設定 | 素材を確かめる。 | なし | PROVISIONAL |
| TS009 | method-assembly | kind=QUALITATIVE, statement=パネルを壁にフック2点で掛ける。 | 未設定 | 組み立てを確かめる。 | なし | PROVISIONAL |
| TS010 | method-installation | kind=QUALITATIVE, statement=A3費用シートは四隅をマスキングテープで壁に貼る。 | 未設定 | 設置を確かめる。 | なし | PROVISIONAL |

## 9. 工程と作業手順

工程の記述。
"""

# Smallest byte stream the receiver accepts as JPEG (SOI ... EOI).
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300" + "01" * 64 + "ffd9")

FAKE_GENERATOR = '''"""Fake plan_view_command: prompt on stdin, JPEG to argv[1], identity on stdout."""
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
prompt = sys.stdin.read()
with (here / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({"prompt": prompt, "argv": sys.argv[1:]}, ensure_ascii=False) + "\\n")
if (here / "fail").exists():
    print("generator broke", file=sys.stderr); sys.exit(3)
pathlib.Path(sys.argv[1]).write_bytes(bytes.fromhex((here / "jpeg.hex").read_text()))
print("progress line")
print(json.dumps({"adapter": "fake", "tool": "Fake", "version": "fake 1.0"}))
'''


def write_fake_generator(directory: Path) -> list[str]:
    """Install the fake generator below `directory` and return its plan_view_command."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "generator.py").write_text(FAKE_GENERATOR, encoding="utf-8")
    (directory / "jpeg.hex").write_text(JPEG.hex(), encoding="utf-8")
    return [sys.executable, str(directory / "generator.py")]


def generator_calls(directory: Path) -> list[dict]:
    log = directory / "calls.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def passing_sync(target: Path, python: str) -> dict:
    """Stand-in for the Project's catalog_sync + validator (tools/run.py _sync_public_catalog)."""
    (target / "plans/lineage-index.json").write_text('{"records":[]}\n', encoding="utf-8")
    return {"status": "PASSED"}


def receiver_check(record: Path, metadata: dict, entry: dict) -> None:
    """Mirror of agentic-art-project tools/attestation_receiver.py _supplemental_media + _check_introduction."""
    readme = (record / "README.md").read_bytes()
    for field, value in {"introduction_contract": "project-plan-introduction/v1",
                         "introduction_sha256": hashlib.sha256(readme).hexdigest()}.items():
        assert metadata.get(field) == value and entry.get(field) == value, field
    raw = (record / "supplemental-media.json").read_bytes()
    manifest = json.loads(raw)
    assert raw == json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    assert set(manifest) == {"assets", "contract_version", "record_id", "source"}
    assert manifest["contract_version"] == "project-supplemental-public-media/v1" and manifest["record_id"] == metadata["id"]
    source = manifest["source"]
    assert set(source) == {"basis", "commit", "locator", "repository"}
    assert (source["basis"], source["repository"], source["locator"]) == ("existing-public-record", "agentic-art-project", entry["path"])
    assert len(source["commit"]) == 40 and all(c in "0123456789abcdef" for c in source["commit"])
    for asset in manifest["assets"]:
        assert set(asset) == {"byte_length", "media_type", "path", "purpose", "rights_ref", "rights_status", "sha256"}
        assert (asset["purpose"], asset["rights_status"]) == ("README_DOCUMENTATION", "PUBLIC_CLEARED")
        data = (record / asset["path"]).read_bytes()
        assert asset["sha256"] == "sha256:" + hashlib.sha256(data).hexdigest() and asset["byte_length"] == len(data)
        assert data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
        assert f"]({asset['path']})".encode() in readme
        assert asset["path"].encode() not in (record / "plan.md").read_bytes()
    media = {x.relative_to(record).as_posix() for x in (record / "media").rglob("*") if x.is_file()}
    assert media == {asset["path"] for asset in manifest["assets"]}


class PromptTests(unittest.TestCase):
    def test_prompt_is_deterministic_code_over_the_plan_sections(self):
        prompt = plan_view.build_prompt(PLAN)
        self.assertEqual(prompt, plan_view.build_prompt(PLAN))
        self.assertIn("No readable text, no captions, no logos, no watermark.", prompt)
        for line in ("- 作品: 点描に学ぶ試し塗り", "- 鑑賞者の位置: 鑑賞者は床の白いテープの線の上に立つ。",
                     "- 仕組み: 緑と赤で印した費用シートで安定箇所と予備枠の関係を理解する。",
                     "- 寸法: 展示空間は約3m×4m、キャンバスは縦30cm×横40cm。",
                     "- 設置: A3費用シートは四隅をマスキングテープで壁に貼る。"):
            self.assertIn(line, prompt)
        self.assertNotIn("quantity=", prompt)

    def test_a_plan_without_the_fixed_sections_has_no_prompt(self):
        with self.assertRaisesRegex(plan_view.PlanViewError, "PLAN_FACTS_MISSING"):
            plan_view.build_prompt("# plan\n")


class PlanViewStepTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.root = Path(t.name)
        self.helper = regression.PublicProjectionContractTests(); self.helper.setUp()
        self.target = self.helper._new_target(self.root); p.init_target(self.target, apply=True)
        self.helper._git(self.target, "add", "."); self.helper._git(self.target, "commit", "-m", "synthetic scaffold")
        self.report = self.helper._automatic_report(self.root)
        plan = Path(self.report["plan"]); plan.write_text(PLAN, encoding="utf-8")
        self.set_plan_hash()
        self.generator = self.root / "generator"
        self.command = write_fake_generator(self.generator)
        patcher = patch("tools.canonical_plan_projection._owner_bundle", synthetic_owner_boundary)
        patcher.start(); self.addCleanup(patcher.stop)

    def set_plan_hash(self):
        self.report["production_plan_sha256"] = p._sha256_bytes(Path(self.report["plan"]).read_bytes())
        self.report["automatic_plan_authority"] = p.build_automatic_plan_authority(
            producer="tools/run.py", source_status="PLAN_READY", source_id=self.report["run_id"],
            source_sha256=self.report["production_plan_sha256"], destination_resolution=self.report["destination_resolution"])

    def project(self):
        return p.project_plan_automatic(self.report, internal_output_root=self.root / "internal",
                                        public_projection_root=self.target, state_root=self.root / "state")

    def step(self, command=None, sync=passing_sync):
        return plan_view.run_step(self.target, ["P0001"], command=self.command if command is None else command,
                                  python=sys.executable, work=self.root / "state" / self.report["run_id"], sync=sync)

    def record(self) -> Path:
        return next((self.target / "plans").glob("P0001-*"))

    def documents(self) -> tuple[dict, dict]:
        record = self.record()
        metadata = yaml.safe_load((record / "metadata.yaml").read_text(encoding="utf-8"))
        entry = yaml.safe_load((self.target / "plans/index.yaml").read_text(encoding="utf-8"))["records"][0]
        return metadata, entry

    def test_attaches_one_view_that_the_receiver_accepts(self):
        self.assertEqual("APPLIED", self.project()["status"])
        record = self.record()
        plan_bytes, attestation = (record / "plan.md").read_bytes(), (record / "public-plan-attestation.json").read_bytes()
        result = self.step()

        self.assertEqual("ATTACHED", result["status"], result)
        metadata, entry = self.documents()
        receiver_check(record, metadata, entry)
        self.assertEqual(plan_bytes, (record / "plan.md").read_bytes())
        self.assertEqual(attestation, (record / "public-plan-attestation.json").read_bytes())
        manifest = json.loads((record / "supplemental-media.json").read_bytes())
        self.assertEqual("fake-image-generation/P0001/plan-view/v1", manifest["assets"][0]["rights_ref"])
        self.assertEqual(self.helper._git(self.target, "rev-parse", "HEAD"), manifest["source"]["commit"])
        readme = (record / "README.md").read_text(encoding="utf-8")
        self.assertLess(readme.index("<!-- prototype-visualization:end -->"), readme.index("## 制作入口"))
        self.assertIn("Fake の画像生成で作りました", readme)
        self.assertIn(f"指示文 sha256 `{result['prompt_sha256'][:12]}`", readme)
        self.assertIn("寸法は正確ではなく、制作した現物の写真ではありません", readme)
        # The full prompt and output hash stay in the private report, not in the record.
        prompt = generator_calls(self.generator)[0]["prompt"]
        self.assertEqual(prompt, result["prompt"])
        self.assertEqual(hashlib.sha256(prompt.encode()).hexdigest(), result["prompt_sha256"])
        self.assertEqual(hashlib.sha256(JPEG).hexdigest(), result["output_sha256"])
        self.assertNotIn("No readable text", readme)
        self.assertEqual({"adapter": "fake", "tool": "Fake", "version": "fake 1.0"}, result["generator"])
        self.assertTrue((self.target / "plans/lineage-index.json").is_file())

    @unittest.skipUnless(os.environ.get("AAK_PROJECT_CODE_ROOT"), "requires an explicit agentic-art-project checkout")
    def test_actual_project_receiver_accepts_the_supplemental_media(self):
        self.project(); self.assertEqual("ATTACHED", self.step()["status"])
        script = '''import sys
from pathlib import Path
from tools.attestation_receiver import _check_introduction, _supplemental_media
from tools.validate import mapping_fields
from tools.catalog_sync import _parse_list_records
record = Path(sys.argv[1])
metadata = mapping_fields(record / "metadata.yaml")
entry = _parse_list_records(record.parent / "index.yaml", "records")[0]
_check_introduction(record, metadata, entry, 1)
print(sorted(_supplemental_media(record, metadata, entry, set())))
'''
        checked = subprocess.run([sys.executable, "-c", script, str(self.record().resolve())], cwd=os.environ["AAK_PROJECT_CODE_ROOT"],
                                 capture_output=True, text=True)
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertEqual("['media/prototype-whole.jpg']", checked.stdout.strip())

    def test_second_run_is_already_present_without_calling_the_generator(self):
        self.project(); self.assertEqual("ATTACHED", self.step()["status"])
        before = p._tree_fingerprint(self.target)
        self.assertEqual("ALREADY_PRESENT", self.step()["status"])
        self.assertEqual(1, len(generator_calls(self.generator)))
        self.assertEqual(before, p._tree_fingerprint(self.target))

    def test_replay_after_the_attached_view_stays_already_projected(self):
        self.assertEqual("APPLIED", self.project()["status"])
        self.assertEqual("ATTACHED", self.step()["status"])
        before = p._tree_fingerprint(self.target)
        self.assertEqual("ALREADY_PROJECTED", self.project()["status"])
        self.assertEqual(before, p._tree_fingerprint(self.target))
        metadata, entry = self.documents()
        receiver_check(self.record(), metadata, entry)
        # The replay check of the request/approval lane accepts the same paths.
        record = self.record().relative_to(self.target).as_posix()
        plan_data = {"findings": [{"code": "TARGET_DIRTY"}], "root_catalog_enabled": True,
                     "plans": [{"is_new": False, "collection": "plans",
                                "expected_files": {f"{record}/{name}": b"" for name in
                                                   ("plan.md", "public-plan-attestation.json", "metadata.yaml", "README.md")}}]}
        self.assertTrue(p._replay_dirty_target_allowed(self.target, plan_data))
        (self.target / "plans/unrelated.txt").write_text("x\n", encoding="utf-8")
        self.assertFalse(p._replay_dirty_target_allowed(self.target, plan_data))

    def test_a_changed_view_blocks_the_replay(self):
        self.project(); self.step()
        (self.record() / "media/prototype-whole.jpg").write_bytes(JPEG + b"\x00")
        self.assertEqual("BLOCKED_CONFLICT", self.project()["status"])

    def test_a_new_revision_drops_the_old_view_and_gets_its_own(self):
        self.project(); self.step()
        plan = Path(self.report["plan"]); plan.write_text(PLAN.replace("約3m×4m", "約4m×5m"), encoding="utf-8")
        self.set_plan_hash()
        self.report["plan_revision"] = 2
        self.report["run_id"] = "RUN-REVISION-TWO"
        self.report["destination_resolution"] = self.helper._profile_resolution(self.root, self.report["run_id"], public=True)
        self.set_plan_hash()
        self.assertEqual("APPLIED", self.project()["status"])
        record = self.record()
        self.assertFalse((record / "supplemental-media.json").exists())
        self.assertFalse((record / "media/prototype-whole.jpg").exists())
        self.assertNotIn("prototype-visualization", (record / "README.md").read_text(encoding="utf-8"))
        result = self.step()
        self.assertEqual("ATTACHED", result["status"], result)
        self.assertIn("約4m×5m", result["prompt"])
        metadata, entry = self.documents()
        self.assertEqual("2", metadata["introduction_revision"])
        receiver_check(record, metadata, entry)

    def test_no_configured_generator_is_skipped(self):
        self.project(); before = p._tree_fingerprint(self.target)
        self.assertEqual({"status": "SKIPPED", "reason": "NOT_CONFIGURED"}, self.step(command=[]))
        self.assertEqual(before, p._tree_fingerprint(self.target))

    def test_generator_failure_keeps_the_projection_and_names_the_reason(self):
        self.project(); before = p._tree_fingerprint(self.target)
        (self.generator / "fail").write_text("", encoding="utf-8")
        result = self.step()
        self.assertEqual(("FAILED", "GENERATOR_FAILED"), (result["status"], result["reason"]))
        self.assertEqual(["generator broke"], result["detail"])
        self.assertEqual(before, p._tree_fingerprint(self.target))
        self.assertEqual("ALREADY_PROJECTED", self.project()["status"])

    def test_generator_that_writes_no_jpeg_is_a_failure(self):
        self.project()
        (self.generator / "jpeg.hex").write_text(b"\x89PNG\r\n\x1a\n".hex(), encoding="utf-8")
        self.assertEqual("GENERATOR_IMAGE_NOT_JPEG", self.step()["reason"])
        self.assertFalse((self.record() / "supplemental-media.json").exists())

    def test_invalid_catalog_after_attaching_restores_the_record(self):
        self.project(); passing_sync(self.target, sys.executable)
        before = p._tree_fingerprint(self.target)
        calls = []

        def sync(target, python):
            record_path = self.record().relative_to(target).as_posix()
            calls.append(plan_view.view_state(target, record_path, "P0001", self.documents()[1]))
            if calls[-1] == "PRESENT":
                return {"status": "FAILED", "step": "validate", "findings": ["ERROR: README-only media"]}
            return passing_sync(target, python)

        result = self.step(sync=sync)
        self.assertEqual(("FAILED", "CATALOG_SYNC_FAILED", True), (result["status"], result["reason"], result["restored"]))
        self.assertEqual(["PRESENT", "ABSENT"], calls)
        self.assertEqual({"status": "PASSED"}, result["catalog_resync"])
        self.assertEqual(before, p._tree_fingerprint(self.target))

    def test_a_failed_resync_is_not_reported_as_restored(self):
        self.project()
        result = self.step(sync=lambda target, python: {"status": "FAILED", "step": "validate"})
        self.assertEqual(("FAILED", "CATALOG_SYNC_FAILED", False), (result["status"], result["reason"], result["restored"]))
        self.assertEqual("FAILED", result["catalog_resync"]["status"])

    def test_any_exception_after_the_projection_is_a_failed_step(self):
        self.project()
        (self.target / "plans/index.yaml").write_text("- not a mapping\n", encoding="utf-8")
        result = self.step()
        self.assertEqual(("FAILED", "RECEIVER_INDEX_INVALID"), (result["status"], result["reason"]))

    def interrupted_attachment(self, files: int) -> None:
        """Attach a view as if the process were killed after the first `files` record writes."""
        real = plan_view._write
        calls = []

        def write(path, data):
            if len(calls) == files:
                raise KeyboardInterrupt  # stands in for SIGKILL: no rollback runs
            calls.append(path); real(path, data)

        with patch.object(plan_view, "_write", side_effect=write), patch.object(plan_view, "restore"):
            with self.assertRaises(KeyboardInterrupt):
                record_path = self.record().relative_to(self.target).as_posix()
                plan_view.attach(self.target, record_path, "P0001", image=JPEG,
                                 identity={"adapter": "fake", "tool": "Fake", "version": ""},
                                 generated_at="2026-10-29T00:00:00+00:00", prompt_sha256="0" * 64,
                                 source_commit="a" * 40, title="t")

    def test_every_interrupted_attachment_is_repaired_and_attached_again(self):
        self.assertEqual("APPLIED", self.project()["status"])
        passing_sync(self.target, sys.executable)
        projected = p._tree_fingerprint(self.target)
        for files in range(1, 5):  # view / manifest / README / index written, metadata not yet
            with self.subTest(files=files):
                self.interrupted_attachment(files)
                record_path = self.record().relative_to(self.target).as_posix()
                self.assertEqual("PARTIAL", plan_view.view_state(self.target, record_path, "P0001", self.documents()[1]))
                # tools/run.py repairs before projecting, so the replay is not a conflict.
                self.assertEqual([{"record_id": "P0001", "status": "REPAIRED"}], plan_view.repair_partial(self.target))
                self.assertEqual(projected, p._tree_fingerprint(self.target))
                self.assertEqual("ALREADY_PROJECTED", self.project()["status"])
        self.interrupted_attachment(3)
        result = self.step()  # the step itself also repairs, then attaches
        self.assertEqual(("ATTACHED", True), (result["status"], result["repaired_partial_view"]))
        metadata, entry = self.documents()
        receiver_check(self.record(), metadata, entry)

    def test_a_manifest_alone_is_not_already_present(self):
        self.project(); self.step()
        record = self.record()
        readme = (record / "README.md").read_text(encoding="utf-8")
        (record / "README.md").write_text(plan_view.strip_block(readme), encoding="utf-8")
        record_path = record.relative_to(self.target).as_posix()
        self.assertEqual("PARTIAL", plan_view.view_state(self.target, record_path, "P0001", self.documents()[1]))

    def test_a_new_revision_stops_on_curated_supplemental_media(self):
        self.project(); self.step()
        record = self.record()
        manifest = json.loads((record / "supplemental-media.json").read_bytes())
        manifest["assets"][0]["rights_ref"] = "local-render/P0001/plan-view/v1"
        (record / "supplemental-media.json").write_bytes(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        self.next_revision()
        before = p._tree_fingerprint(self.target)
        self.assertEqual("BLOCKED_CONFLICT", self.project()["status"])
        self.assertEqual(before, p._tree_fingerprint(self.target))
        self.assertIn("curated supplemental media requires migration", self.finding())

    def test_a_new_revision_stops_on_a_curated_readme(self):
        self.project()
        readme = self.record() / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\n手で書いた紹介。\n", encoding="utf-8")
        self.next_revision()
        self.assertEqual("BLOCKED_CONFLICT", self.project()["status"])
        self.assertIn("curated README requires migration", self.finding())

    def next_revision(self):
        plan = Path(self.report["plan"]); plan.write_text(PLAN.replace("約3m×4m", "約4m×5m"), encoding="utf-8")
        self.report["plan_revision"] = 2
        self.report["run_id"] = "RUN-REVISION-TWO"
        self.report["destination_resolution"] = self.helper._profile_resolution(self.root, self.report["run_id"], public=True)
        self.set_plan_hash()

    def finding(self) -> str:
        result = json.loads((self.root / "state" / self.report["run_id"] / "public-projection-result.json").read_text())
        return result["findings"][0]["remediation"]

    def test_source_commit_is_one_that_holds_the_record(self):
        self.project()
        record_path = self.record().relative_to(self.target).as_posix()
        head = self.helper._git(self.target, "rev-parse", "HEAD")
        self.assertEqual((head, False), plan_view.source_commit(self.target, record_path))
        self.helper._git(self.target, "add", "."); self.helper._git(self.target, "commit", "-m", "record")
        committed = self.helper._git(self.target, "rev-parse", "HEAD")
        self.helper._git(self.target, "commit", "--allow-empty", "-m", "later")
        self.assertEqual((committed, True), plan_view.source_commit(self.target, record_path))
        manifest = json.loads(json.dumps(self.step()))  # attaches with that commit
        self.assertEqual((committed, True), (manifest["source_commit"], manifest["source_commit_contains_record"]))

    def test_timeout_stops_the_whole_generator_process_group(self):
        self.project()
        hang = self.root / "hang.py"
        pid_file = self.root / "child.pid"
        hang.write_text(
            "import subprocess, sys, time, pathlib\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
            "time.sleep(300)\n", encoding="utf-8")
        result = plan_view.run_step(self.target, ["P0001"], command=[sys.executable, str(hang)], python=sys.executable,
                                    work=self.root / "state" / "hang", sync=passing_sync, timeout=3)
        self.assertEqual(("FAILED", "GENERATOR_TIMEOUT"), (result["status"], result["reason"]))
        child = int(pid_file.read_text())
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)


@unittest.skipUnless(os.environ.get("AAK_PROJECT_CODE_ROOT"), "requires an explicit agentic-art-project checkout")
class RealProjectCatalogTests(unittest.TestCase):
    """The Project's own tools/catalog_sync.py and tools/validate.py --check, on a copy of its catalog."""

    def test_real_catalog_sync_and_validator_accept_a_regenerated_view(self):
        import tarfile
        from tools.run import _sync_public_catalog

        with tempfile.TemporaryDirectory(prefix="plan-view-real-project-") as temporary:
            root = Path(temporary).resolve()
            archive, target = root / "project.tar", root / "project"
            subprocess.run(["git", "-C", os.environ["AAK_PROJECT_CODE_ROOT"], "archive", "--format=tar", "-o", str(archive),
                            "HEAD"], check=True, capture_output=True)
            with tarfile.open(archive) as tar:
                tar.extractall(target, filter="data")
            for args in (["init", "-q", "-b", "main"], ["add", "."],
                         ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "copy"]):
                subprocess.run(["git", "-C", str(target), *args], check=True, capture_output=True)
            record = next((target / "plans").glob("P0019-*")).relative_to(target).as_posix()
            plan_view.remove_view(target, record, "P0019")
            self.assertEqual({"status": "PASSED"}, _sync_public_catalog(target, sys.executable))
            command = write_fake_generator(root / "generator")
            result = plan_view.run_step(target, ["P0019"], command=command, python=sys.executable, work=root / "state",
                                        sync=_sync_public_catalog)
            self.assertEqual("ATTACHED", result["status"], result)
            self.assertEqual({"status": "PASSED"}, result["catalog_sync"])
            self.assertTrue(result["source_commit_contains_record"])


FAKE_CODEX = '''#!{python}
"""Fake codex CLI: --version, or `exec --json ... -` that adds PNGs under $CODEX_HOME/generated_images/<thread>/."""
import json, os, pathlib, struct, sys, zlib
home = pathlib.Path(os.environ["CODEX_HOME"])
if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.0.1"); sys.exit(0)
prompt = sys.stdin.read()
home.mkdir(parents=True, exist_ok=True)
(home / "prompt.txt").write_text(prompt, encoding="utf-8")
(home / "argv.json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
png = (b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(b"\\x00" + b"\\xff\\x00\\x00" * 2 + b"\\x00" + b"\\x00\\xff\\x00" * 2)) + chunk(b"IEND", b""))
thread = "01a10000-0000-7000-8000-000000000001"
mode = (home / "mode").read_text().strip() if (home / "mode").exists() else "one"
# A concurrent session writes its own image at the same time; it must never be picked.
other = home / "generated_images" / "01a1ffff-0000-7000-8000-00000000ffff"
other.mkdir(parents=True, exist_ok=True)
(other / "private.png").write_bytes(png)
folder = home / "generated_images" / thread
folder.mkdir(parents=True, exist_ok=True)
if mode != "none":
    (folder / "image.png").write_bytes(png)
if mode == "two":
    (folder / "second.png").write_bytes(png)
print(json.dumps({"type": "thread.started", "thread_id": thread}))
print(json.dumps({"type": "turn.completed"}))
sys.exit(7 if mode == "fail" else 0)
'''


def _jpeg_converter_available() -> bool:
    import importlib.util
    import shutil
    return bool(shutil.which("sips")) or importlib.util.find_spec("PIL") is not None


class CodexAdapterTests(unittest.TestCase):
    def run_adapter(self, root: Path, mode: str = "one") -> subprocess.CompletedProcess:
        codex = root / "codex"
        codex.write_text(FAKE_CODEX.replace("{python}", sys.executable), encoding="utf-8")
        codex.chmod(0o755)
        (root / "home").mkdir(exist_ok=True)
        (root / "home" / "mode").write_text(mode, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(Path(plan_view.__file__).with_name("plan_view_codex.py")), str(root / "out" / "view.jpg"),
             "--codex", str(codex), "--timeout", "60"],
            input="- 作品: 試し塗り\n", capture_output=True, text=True, env=dict(os.environ, CODEX_HOME=str(root / "home")),
        )

    @unittest.skipUnless(_jpeg_converter_available(), "needs sips or Pillow to convert PNG to JPEG")
    def test_adapter_takes_only_this_threads_image_as_jpeg(self):
        with tempfile.TemporaryDirectory(prefix="plan-view-codex-") as temporary:
            root = Path(temporary)
            completed = self.run_adapter(root)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual({"adapter": "codex", "tool": "Codex", "version": "codex-cli 0.0.1"},
                             plan_view._identity(completed.stdout))
            data = (root / "out" / "view.jpg").read_bytes()
            self.assertTrue(data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"))
            sent = (root / "home" / "prompt.txt").read_text(encoding="utf-8")
            self.assertTrue(sent.startswith("Use your image generation tool"))
            self.assertTrue(sent.endswith("- 作品: 試し塗り\n"))
            self.assertIn("--json", json.loads((root / "home" / "argv.json").read_text()))

    def test_adapter_fails_without_exactly_one_image_of_its_own_thread_or_on_a_codex_error(self):
        for mode, message in (("none", "found 0"), ("two", "found 2"), ("fail", "codex exited 7")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="plan-view-codex-") as temporary:
                root = Path(temporary)
                completed = self.run_adapter(root, mode)
                self.assertEqual(1, completed.returncode)
                self.assertIn(message, completed.stderr)
                self.assertFalse((root / "out" / "view.jpg").exists())


if __name__ == "__main__":
    unittest.main()
