"""Restore recovered Project plan IDs to the historical public sequence.

This is a one-time, explicit repair for the local recovery receiver.  It
requires the six generated records to be present as P0009-P0014, rewrites
only their public IDs/paths and native generated catalogs, and removes the
matching migration reservations after the receiver has validated them.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import yaml


MAPPING = {
    "P0009": "P0001",
    "P0010": "P0002",
    "P0011": "P0003",
    "P0012": "P0005",
    "P0013": "P0006",
    "P0014": "P0007",
}


def _records(root: Path) -> list[dict[str, Any]]:
    value = yaml.safe_load((root / "plans/index.yaml").read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        raise ValueError("PROJECT_INDEX_INVALID")
    return value["records"]


def _assert_preconditions(root: Path) -> None:
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise ValueError("TARGET_MUST_BE_COMMITTED_BEFORE_RENUMBER")
    records = _records(root)
    by_id = {str(row.get("id")): row for row in records}
    if set(MAPPING) - set(by_id):
        raise ValueError("RECOVERED_IDS_MISSING")
    if set(MAPPING.values()) & set(by_id):
        raise ValueError("FINAL_ID_ALREADY_EXISTS")
    for old_id in MAPPING:
        row = by_id[old_id]
        expected = f"plans/{old_id}-{row['slug']}"
        if row.get("path") != expected:
            raise ValueError("RECOVERED_PATH_MISMATCH")
        directory = root / expected
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("RECOVERED_DIRECTORY_INVALID")
        for name in ("metadata.yaml", "lineage.json", "plan.md", "public-plan-attestation.json"):
            path = directory / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("RECOVERED_FILE_INVALID")


def _write_yaml(path: Path, value: object) -> None:
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def renumber(root: Path) -> dict[str, object]:
    root = root.resolve()
    _assert_preconditions(root)
    records = _records(root)
    by_id = {str(row["id"]): row for row in records}
    moved: list[dict[str, str]] = []

    for old_id, new_id in MAPPING.items():
        row = by_id[old_id]
        old_path = root / row["path"]
        new_path = root / f"plans/{new_id}-{row['slug']}"
        if new_path.exists() or new_path.is_symlink():
            raise ValueError("FINAL_DIRECTORY_EXISTS")
        shutil.move(str(old_path), str(new_path))
        metadata_path = new_path / "metadata.yaml"
        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("id") != old_id:
            raise ValueError("RECOVERED_METADATA_ID_MISMATCH")
        metadata["id"] = new_id
        _write_yaml(metadata_path, metadata)

        lineage_path = new_path / "lineage.json"
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        if not isinstance(lineage, dict) or lineage.get("record_id") != old_id:
            raise ValueError("RECOVERED_LINEAGE_ID_MISMATCH")
        lineage["record_id"] = new_id
        lineage_path.write_text(json.dumps(lineage, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

        moved.append({"from": old_id, "to": new_id, "path": f"plans/{new_id}-{row['slug']}"})

    index_path = root / "plans/index.yaml"
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict):
        raise ValueError("PROJECT_INDEX_INVALID")
    for row in index["records"]:
        old_id = str(row["id"])
        if old_id in MAPPING:
            row["id"] = MAPPING[old_id]
            row["path"] = f"plans/{row['id']}-{row['slug']}"
    index["records"] = sorted(index["records"], key=lambda row: row["id"])
    _write_yaml(index_path, index)

    migration_path = root / "plans/migration.yaml"
    migration = yaml.safe_load(migration_path.read_text(encoding="utf-8"))
    if not isinstance(migration, dict) or not isinstance(migration.get("records"), list):
        raise ValueError("MIGRATION_INDEX_INVALID")
    remaining = [row for row in migration["records"] if str(row.get("id")) not in MAPPING.values()]
    migration["records"] = remaining
    _write_yaml(migration_path, migration)

    # The Project repository owns these generated files and their exact
    # rendering.  Do not hand-copy catalog prose from the parent.
    sys.path.insert(0, str(root))
    from tools import catalog_sync

    for path, content in catalog_sync.expected_files(root).items():
        path.write_text(content, encoding="utf-8")

    return {"status": "RENUMBERED", "mapping": moved, "migration_remaining": len(remaining)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(renumber(args.project_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
