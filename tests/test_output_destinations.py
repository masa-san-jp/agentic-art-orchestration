from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import yaml

from tools.output_destinations import (
    DestinationError,
    assert_create_only_directory,
    canonical_resolution_bytes,
    load_destinations_file,
    resolve_destinations,
    resolve_run_destination,
    validate_destination_resolution,
    validate_destination_profile,
)


class OutputDestinationsTests(unittest.TestCase):
    def _profile(self, path: Path, *, state: Path, internal: Path, public: Path | None = None) -> None:
        destinations = {
            "state_root": str(state),
            "internal_output_root": str(internal),
        }
        if public is not None:
            destinations["public_projection_root"] = str(public)
        path.write_text(
            yaml.safe_dump(
                {
                    "contract_version": "output-destinations/v1",
                    "profile": "test",
                    "destinations": destinations,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def test_example_and_profile_are_closed_and_resolution_is_closed(self) -> None:
        from tools.validate import load_json, load_yaml, validate_output_destinations_contract
        from tools.output_destinations import DESTINATION_RESOLUTION_SCHEMA, OUTPUT_DESTINATIONS_SCHEMA

        self.assertEqual(
            [],
            validate_output_destinations_contract(
                load_json(OUTPUT_DESTINATIONS_SCHEMA),
                load_json(DESTINATION_RESOLUTION_SCHEMA),
                load_yaml(Path(__file__).parents[1] / "config/output-destinations.example.yaml"),
            ),
        )
        profile = yaml.safe_load((Path(__file__).parents[1] / "config/output-destinations.example.yaml").read_text())
        self.assertEqual([], validate_destination_profile(profile))
        profile["unexpected"] = True
        self.assertTrue(validate_destination_profile(profile))

    def test_precedence_is_direct_then_cli_file_then_environment_then_legacy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="destinations-precedence-") as temporary:
            root = Path(temporary)
            paths = {
                "direct": root / "direct",
                "profile": root / "profile-state",
                "environment": root / "environment-state",
                "legacy": root / "legacy-state",
                "public": root / "public",
            }
            explicit_file = root / "explicit.yaml"
            environment_file = root / "environment.yaml"
            self._profile(explicit_file, state=paths["profile"], internal=root / "profile-internal", public=paths["public"])
            self._profile(environment_file, state=paths["environment"], internal=root / "environment-internal")

            direct = resolve_destinations(
                explicit_file,
                direct={"state_root": paths["direct"]},
                environment={"AGENTIC_ART_DESTINATIONS_FILE": str(environment_file)},
                legacy_defaults={"state_root": paths["legacy"], "internal_output_root": root / "legacy-internal"},
                repository_root=root / "repository",
                run_id="RUN-001",
            )
            self.assertEqual("cli-file", direct["config_source"])
            self.assertEqual("direct-cli", direct["destinations"]["state_root"]["source"])
            self.assertEqual(str(paths["direct"].resolve()), direct["destinations"]["state_root"]["path"])
            self.assertEqual("profile", direct["destinations"]["internal_output_root"]["source"])
            self.assertIn("public_projection_root", direct["destinations"])

            environment = resolve_destinations(
                environment={"AGENTIC_ART_DESTINATIONS_FILE": str(environment_file)},
                repository_root=root / "repository",
                legacy_defaults={"state_root": paths["legacy"], "internal_output_root": root / "legacy-internal"},
                project_id="project/project-001",
            )
            self.assertEqual("environment-file", environment["config_source"])
            self.assertEqual("profile", environment["destinations"]["state_root"]["source"])
            self.assertEqual("project/project-001", environment["project_id"])

            legacy = resolve_destinations(
                environment={},
                repository_root=root / "repository",
                legacy_defaults={"state_root": paths["legacy"], "internal_output_root": root / "legacy-internal"},
                run_id="RUN-LEGACY",
            )
            self.assertEqual("legacy-defaults", legacy["config_source"])
            self.assertEqual("legacy-default", legacy["destinations"]["state_root"]["source"])
            self.assertNotIn("public_projection_root", legacy["destinations"])

    def test_same_inputs_have_identical_resolution_bytes_and_file_hash_changes_with_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="destinations-determinism-") as temporary:
            root = Path(temporary)
            profile_path = root / "profile.yaml"
            self._profile(profile_path, state=root / "state", internal=root / "internal")
            first, first_hash = load_destinations_file(profile_path)
            second, second_hash = load_destinations_file(profile_path)
            self.assertEqual(first, second)
            self.assertEqual(first_hash, second_hash)
            first_resolution = resolve_destinations(profile_path, repository_root=root / "repository", run_id="RUN-001")
            second_resolution = resolve_destinations(profile_path, repository_root=root / "repository", run_id="RUN-001")
            self.assertEqual(first_resolution, second_resolution)
            self.assertEqual(canonical_resolution_bytes(first_resolution), canonical_resolution_bytes(second_resolution))
            self.assertEqual([], validate_destination_resolution(first_resolution))
            profile_path.write_text(profile_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            _changed, changed_hash = load_destinations_file(profile_path)
            self.assertNotEqual(first_hash, changed_hash)

    def test_profile_and_direct_inputs_are_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="destinations-closed-") as temporary:
            root = Path(temporary)
            profile_path = root / "profile.yaml"
            self._profile(profile_path, state=root / "state", internal=root / "internal")
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            profile["destinations"]["unknown"] = str(root / "unknown")
            profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(DestinationError, "closed output-destinations"):
                load_destinations_file(profile_path)
            with self.assertRaisesRegex(DestinationError, "unknown roles"):
                resolve_destinations(
                    direct={"unknown": root / "unknown"},
                    legacy_defaults={"state_root": root / "state", "internal_output_root": root / "internal"},
                    repository_root=root / "repository",
                    run_id="RUN-001",
                )
            with self.assertRaisesRegex(DestinationError, "both"):
                resolve_destinations(
                    direct={},
                    direct_paths={},
                    legacy_defaults={"state_root": root / "state", "internal_output_root": root / "internal"},
                    repository_root=root / "repository",
                    run_id="RUN-001",
                )

    def test_path_boundaries_reject_repository_child_overlap_and_symlink_alias(self) -> None:
        with tempfile.TemporaryDirectory(prefix="destinations-boundary-") as temporary:
            root = Path(temporary)
            repository = root / "repository"
            child = root / "child"
            repository.mkdir()
            child.mkdir()
            valid_internal = root / "internal"
            with self.assertRaisesRegex(DestinationError, "orchestration repository"):
                resolve_destinations(
                    direct={"state_root": repository / "state", "internal_output_root": valid_internal},
                    repository_root=repository,
                    run_id="RUN-001",
                )
            with self.assertRaisesRegex(DestinationError, "child checkout"):
                resolve_destinations(
                    direct={"state_root": child / "state", "internal_output_root": valid_internal},
                    repository_root=repository,
                    child_roots=(child,),
                    run_id="RUN-001",
                )
            with self.assertRaisesRegex(DestinationError, "overlap"):
                resolve_destinations(
                    direct={"state_root": root / "state", "internal_output_root": root / "state" / "internal"},
                    repository_root=repository,
                    run_id="RUN-001",
                )
            alias = root / "alias"
            try:
                alias.symlink_to(repository, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink unsupported: {exc}")
            with self.assertRaisesRegex(DestinationError, "orchestration repository"):
                resolve_destinations(
                    direct={"state_root": alias / "state", "internal_output_root": valid_internal},
                    repository_root=repository,
                    run_id="RUN-001",
                )

    def test_root_values_require_absolute_existing_directories_and_non_overlapping_roles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="destinations-values-") as temporary:
            root = Path(temporary)
            valid_internal = root / "internal"
            cases = [
                ("relative", "state_root must be absolute"),
                ("", "empty or not a string"),
                ("bad\x00path", "contains NUL"),
            ]
            for value, message in cases:
                with self.subTest(value=value), self.assertRaisesRegex(DestinationError, message):
                    resolve_destinations(
                        direct={"state_root": value, "internal_output_root": valid_internal},
                        repository_root=root / "repository",
                        run_id="RUN-001",
                    )
            file_path = root / "not-a-directory"
            file_path.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(DestinationError, "not a directory"):
                resolve_destinations(
                    direct={"state_root": file_path, "internal_output_root": valid_internal},
                    repository_root=root / "repository",
                    run_id="RUN-001",
                )

    def test_derived_paths_reject_traversal_and_create_only_protects_existing_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="destinations-derived-") as temporary:
            root = Path(temporary)
            derived = resolve_run_destination(root / "state", "RUN-001", "project-001")
            self.assertEqual((root / "state" / "RUN-001" / "project-001").resolve(), derived)
            for unsafe in ("../escape", "/absolute", "a/b", "a\\b", ".", ".."):
                with self.subTest(unsafe=unsafe), self.assertRaises(DestinationError):
                    resolve_run_destination(root / "state", unsafe)
            empty = root / "empty"
            empty.mkdir()
            self.assertEqual(empty.resolve(), assert_create_only_directory(empty))
            populated = root / "populated"
            populated.mkdir()
            (populated / "existing.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(DestinationError, "not empty"):
                assert_create_only_directory(populated)
            file_path = root / "output.json"
            file_path.write_text(json.dumps({"status": "old"}), encoding="utf-8")
            with self.assertRaisesRegex(DestinationError, "not a directory"):
                assert_create_only_directory(file_path)


if __name__ == "__main__":
    unittest.main()
