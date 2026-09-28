from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "resolve_catalog_path", ROOT / "tools/resolve_catalog_path.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

VALIDATE_SPEC = importlib.util.spec_from_file_location(
    "orchestration_validate_for_catalog_aliases", ROOT / "tools/validate.py"
)
VALIDATE = importlib.util.module_from_spec(VALIDATE_SPEC)
assert VALIDATE_SPEC and VALIDATE_SPEC.loader
VALIDATE_SPEC.loader.exec_module(VALIDATE)


class CatalogPathAliasTests(unittest.TestCase):
    def test_registry_resolves_all_recorded_renames_and_preserves_current_paths(self):
        registry = MODULE.load_registry()
        aliases = {entry["old_path"]: entry["new_path"] for entry in registry["aliases"]}
        self.assertEqual(9, len(aliases))
        for old_path, new_path in aliases.items():
            with self.subTest(old_path=old_path):
                self.assertEqual(new_path, MODULE.resolve_path(old_path, registry))
        current = "plans/P0001-unchanged-catalog-record"
        self.assertEqual(current, MODULE.resolve_path(current, registry))

    def test_execution_evidence_is_not_rewritten_by_resolution(self):
        before = {
            path.relative_to(ROOT): path.read_bytes()
            for path in (ROOT / "execution").rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        command = [
            sys.executable,
            str(ROOT / "tools/resolve_catalog_path.py"),
            "plans/P0017-auto-auto-plan-20260921t152805z-rev1",
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        self.assertEqual("plans/P0017-receiving-interval\n", result.stdout)
        after = {
            path.relative_to(ROOT): path.read_bytes()
            for path in (ROOT / "execution").rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        self.assertEqual(before, after)

    def test_alias_chain_resolves_and_cycle_is_explicit(self):
        registry = {
            "contract_version": "catalog-path-aliases/v1",
            "source_repository": "agentic-art-project",
            "aliases": [
                {
                    "old_path": "plans/P0090-first",
                    "new_path": "plans/P0090-second",
                    "plan_id": "P0090",
                    "rename_commit": "abcdef1",
                    "reason": "first rename",
                },
                {
                    "old_path": "plans/P0090-second",
                    "new_path": "plans/P0090-current",
                    "plan_id": "P0090",
                    "rename_commit": "abcdef2",
                    "reason": "second rename",
                },
            ],
        }
        self.assertEqual("plans/P0090-current", MODULE.resolve_path("plans/P0090-first", registry))

        cycle = json.loads(json.dumps(registry))
        cycle["aliases"][1]["new_path"] = "plans/P0090-first"
        with self.assertRaises(MODULE.CatalogPathError) as raised:
            MODULE.resolve_path("plans/P0090-first", cycle)
        self.assertIn("CATALOG_PATH_ALIAS_CYCLE", str(raised.exception))

    def test_validator_rejects_alias_cycle(self):
        registry = MODULE.load_registry()
        registry["aliases"][0]["new_path"] = registry["aliases"][1]["old_path"]
        registry["aliases"][1]["new_path"] = registry["aliases"][0]["old_path"]
        errors = VALIDATE.validate_catalog_path_aliases(
            registry,
            VALIDATE.load_json(ROOT / "schemas/catalog-path-aliases.schema.json"),
            "fixture:catalog-path-aliases",
        )
        self.assertIn("CATALOG_PATH_ALIAS_CYCLE", "\n".join(errors))

    def test_history_candidates_detect_directory_renames_without_mutating_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            git_env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            }
            old_dir = root / "plans/P0200-old-slug"
            old_dir.mkdir(parents=True)
            (old_dir / "plan.md").write_text("historical plan\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, env=git_env)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "base"], check=True, env=git_env)
            base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            new_dir = root / "plans/P0200-current-slug"
            subprocess.run(["git", "-C", str(root), "mv", str(old_dir), str(new_dir)], check=True, env=git_env)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "rename"], check=True, env=git_env)
            candidates = MODULE.history_candidates(root, base)
            self.assertEqual(
                [
                    {
                        "old_path": "plans/P0200-old-slug",
                        "new_path": "plans/P0200-current-slug",
                        "plan_id": "P0200",
                        "rename_commit": candidates[0]["rename_commit"],
                        "reason": "Directory rename detected from plans/ rename entries in Git history.",
                    }
                ],
                candidates,
            )
            self.assertEqual("plans/P0200-current-slug", MODULE.resolve_path(candidates[0]["new_path"], {"aliases": candidates, "contract_version": "catalog-path-aliases/v1", "source_repository": "agentic-art-project"}))

    def test_schema_and_validator_accept_registry(self):
        registry = MODULE.load_registry()
        schema = VALIDATE.load_json(ROOT / "schemas/catalog-path-aliases.schema.json")
        self.assertEqual([], VALIDATE._schema_errors(registry, schema, "fixture:catalog-path-aliases"))
        self.assertEqual([], VALIDATE.validate_catalog_path_aliases(registry, schema))


if __name__ == "__main__":
    unittest.main()
