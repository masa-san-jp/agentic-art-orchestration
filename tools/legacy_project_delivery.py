"""Project-local delivery for a regenerated historical candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.canonical_plan_projection import source_fields
from tools.project_local_delivery import prepare_lineage, sync_catalog, verify
from tools.public_projection import build_automatic_plan_authority, project_plan_automatic
from tools.repo_local_destinations import validate_resolution


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-project", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--production-code", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--legacy-id", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--child-python", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    args = parser.parse_args()

    project = args.project_root.resolve()
    internal = project / ".agentic-art/internal"
    state_root = project / ".agentic-art/state"
    production_code = args.production_code.resolve()
    # Production's own validator binds production/<slug> to
    # production-plan.yaml.project_id.  Keep the recovery label in the run
    # provenance, while preserving the owner checkout's required project dir.
    source_copy = internal / "production" / args.production_project.resolve().name
    if source_copy.exists():
        # A failed preflight may have left the immutable copied source behind;
        # reuse it only when the expected canonical files are present.
        if not (source_copy / "03_plan/production-plan.md").is_file() or not (source_copy / "03_plan/public-plan-attestation.json").is_file():
            raise ValueError("RECOVERY_SOURCE_CONFLICT")
    else:
        source_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(args.production_project.resolve(), source_copy)
    plan = source_copy / "03_plan/production-plan.md"
    owner = source_fields(plan, production_code)
    body_hash = __import__("hashlib").sha256(plan.read_bytes()).hexdigest()
    attestation_hash = __import__("hashlib").sha256((source_copy / "03_plan/public-plan-attestation.json").read_bytes()).hexdigest()
    saved = json.loads(args.resolution.resolve().read_bytes())
    resolution = saved.get("destination_resolution", saved) if isinstance(saved, dict) else saved
    if not isinstance(resolution, dict):
        raise ValueError("SAVED_RESOLUTION_REQUIRED")
    resolution["run_id"] = args.run_id
    if resolution.get("project_root") != str(project):
        raise ValueError("SAVED_RESOLUTION_PROJECT_MISMATCH")
    if resolution.get("destinations", {}).get("internal_output_root", {}).get("path") != str(internal):
        raise ValueError("SAVED_RESOLUTION_INTERNAL_MISMATCH")
    if resolution.get("destinations", {}).get("public_projection_root", {}).get("path") != str(project):
        raise ValueError("SAVED_RESOLUTION_PUBLIC_MISMATCH")
    if validate_resolution(resolution):
        raise ValueError("SAVED_RESOLUTION_SCHEMA_INVALID")
    # The saved resolution is the pre-output target attestation.  The target
    # may have advanced by a documentation-only branch move while retaining
    # the same native receiver; native validation below is the authority.
    tracked_status = subprocess.check_output(["git", "-C", str(project), "status", "--porcelain", "--untracked-files=no"], text=True).splitlines()
    allowed_existing = {"README.md", "plans/README.md", "plans/index.yaml", "plans/lineage-index.json"}
    if any(line[3:] not in allowed_existing for line in tracked_status if len(line) >= 4):
        raise ValueError("PROJECT_TRACKED_DIFF_OUTSIDE_SAVED_OUTPUT")
    checked = subprocess.run([str(args.child_python), str(project / "tools/validate.py"), "--check", "--root", str(project)], cwd=project, capture_output=True, text=True, timeout=120)
    if checked.returncode:
        raise ValueError("PROJECT_NATIVE_VALIDATOR_FAILED_BEFORE_PROJECTION")
    production_commit = subprocess.check_output(["git", "-C", str(production_code), "rev-parse", "HEAD"], text=True).strip()
    source = {"run_id": args.run_id, "status": "PLAN_READY", "generated_at": "2026-09-10T16:00:00+09:00", "project_slug": args.slug, "project_title": args.title, "production_repository": "agentic-art-production", "production_source_commit": production_commit, "production_plan_sha256": body_hash, "destination_resolution": resolution, **owner}
    source["production_plan_markdown_sha256"] = body_hash
    source["public_plan_attestation_sha256"] = attestation_hash
    source["production_code_root"] = str(production_code)
    source["automatic_plan_authority"] = build_automatic_plan_authority(producer="tools/run.py", source_status="PLAN_READY", source_id=args.run_id, source_sha256=body_hash, destination_resolution=resolution)
    projected = project_plan_automatic(source, internal_output_root=internal, public_projection_root=project, state_root=state_root, projection_id=args.run_id, child_python=str(args.child_python))
    if projected.get("status") not in {"APPLIED", "ALREADY_PROJECTED"}:
        print(json.dumps({"legacy_id": args.legacy_id, "projection": projected}, ensure_ascii=False, indent=2))
        return 2
    run_root = state_root / "legacy-recovery" / args.run_id
    run_root.mkdir(parents=True, exist_ok=True)
    profile_output = run_root / "project-instance-profile.yaml"
    lineage_outputs = []
    for record_id in projected["public_ids"]:
        lineage_input = run_root / (record_id + "-lineage.json")
        prepare_lineage(project, str(args.child_python), project, record_id, args.profile.resolve(), lineage_input, profile_output)
        __import__("subprocess").run([str(args.child_python), str(project / "tools/catalog_lineage.py"), "annotate", "--root", str(project), "--record-id", record_id, "--input", str(lineage_input), "--instance-profile", str(profile_output), "--mode", "new", "--apply"], cwd=project, check=True, capture_output=True, text=True, timeout=120)
        lineage_outputs.append(str(lineage_input))
    sync_catalog(project, str(args.child_python), project)
    expected = [{"record_id": record_id, "content_sha256": body_hash, "creator_id": "synthetic-provider-new-clone-creator", "origin_instance_id": "synthetic-provider-new-clone-instance", "source_identity": source["source_identity"]} for record_id in projected["public_ids"]]
    expected_path = run_root / "expected-delivery.json"
    expected_path.write_bytes(json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n")
    receipt = verify(project, project, str(args.child_python), expected_path, run_root / "local-delivery.json", args.run_id, state_root / args.run_id / "public-projection-result.json")
    result = {"legacy_id": args.legacy_id, "run_id": args.run_id, "source_identity": source["source_identity"], "production_project": str(source_copy), "production_plan_sha256": body_hash, "attestation_sha256": attestation_hash, "projection": projected, "receipt": receipt, "lineage_inputs": lineage_outputs}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
