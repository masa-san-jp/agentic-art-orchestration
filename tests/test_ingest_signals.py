from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_ingest", ROOT / "tools/ingest_signals.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class IngestConfigurationTests(unittest.TestCase):
    def _self_model_export_with_help(self, help_result: object, requester: str | None):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            checkout = workspace / "self-model" / "tools"
            checkout.mkdir(parents=True)
            (checkout / "export_signals.py").write_text("print('{}')\n", encoding="utf-8")
            actual = subprocess.CompletedProcess(["python"], 0, stdout="{}", stderr="")

            def fake_run(command, **kwargs):
                if "--help" in command:
                    return help_result
                return actual

            with patch.object(MODULE.subprocess, "run", side_effect=fake_run) as runner:
                result = MODULE._export(
                    {"id": "self-model", "path": "self-model"}, workspace,
                    "artistic-research", sys.executable, workspace / "profile", requester,
                )
        return result, runner.call_args_list

    def test_self_model_requester_is_forwarded_when_help_advertises_it(self):
        result, calls = self._self_model_export_with_help(
            subprocess.CompletedProcess(["help"], 0, stdout="--requester RUN", stderr=""), "RUN-1",
        )
        self.assertEqual({}, result)
        self.assertIn("--requester", calls[1].args[0])
        self.assertEqual(30, calls[0].kwargs["timeout"])

    def test_self_model_requester_is_omitted_when_old_help_lacks_it(self):
        result, calls = self._self_model_export_with_help(
            subprocess.CompletedProcess(["help"], 0, stdout="--profile-root", stderr=""), "RUN-1",
        )
        self.assertEqual({}, result)
        self.assertNotIn("--requester", calls[1].args[0])

    def test_self_model_requester_none_skips_help_probe(self):
        result, calls = self._self_model_export_with_help(None, None)
        self.assertEqual({}, result)
        self.assertEqual(1, len(calls))
        self.assertNotIn("--help", calls[0].args[0])

    def test_help_probe_timeout_or_oserror_continues_without_requester(self):
        for failure in (subprocess.TimeoutExpired("help", 30), OSError("help unavailable")):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                checkout = workspace / "self-model" / "tools"
                checkout.mkdir(parents=True)
                (checkout / "export_signals.py").write_text("print('{}')\n", encoding="utf-8")
                actual = subprocess.CompletedProcess(["python"], 0, stdout="{}", stderr="")

                def fake_run(command, **kwargs):
                    if "--help" in command:
                        raise failure
                    return actual

                with patch.object(MODULE.subprocess, "run", side_effect=fake_run) as runner:
                    self.assertEqual({}, MODULE._export(
                        {"id": "self-model", "path": "self-model"}, workspace,
                        "artistic-research", sys.executable, workspace / "profile", "RUN-1",
                    ))
                self.assertNotIn("--requester", runner.call_args_list[1].args[0])

    def test_explicit_profile_is_a_literal_argument_only_for_self_model(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            profile = workspace / "外部 profile $(not-a-command)"
            for identifier in ("self-model", "art-history", "marketing-trends"):
                with self.subTest(repository=identifier):
                    checkout = workspace / identifier / "tools"
                    checkout.mkdir(parents=True)
                    profile_option = (
                        "parser.add_argument('--profile-root', required=True)\n"
                        if identifier == "self-model" else ""
                    )
                    (checkout / "export_signals.py").write_text(
                        "import argparse, json\n"
                        "parser = argparse.ArgumentParser()\n"
                        "parser.add_argument('--purpose', required=True)\n"
                        + profile_option
                        + "print(json.dumps(vars(parser.parse_args())))\n",
                        encoding="utf-8",
                    )
                    result = MODULE._export(
                        {"id": identifier, "path": identifier}, workspace,
                        "artistic-research", sys.executable, profile,
                    )
                    self.assertEqual("artistic-research", result["purpose"])
                    if identifier == "self-model":
                        self.assertEqual(str(profile), result["profile_root"])
                    else:
                        self.assertNotIn("profile_root", result)
            self.assertFalse(profile.exists())

    def test_missing_profile_blocks_all_exports_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            existing = output / "portfolio.json"
            existing.write_bytes(b"existing portfolio must survive")
            # Self Model need not be the first declared input.
            manifest = {"repositories": [
                {"id": "art-history", "role": "input-kb"},
                {"id": "self-model", "role": "input-kb"},
            ]}
            with patch.object(MODULE, "load_yaml", return_value=manifest), \
                    patch.object(MODULE, "_export") as exporter:
                with self.assertRaisesRegex(MODULE.IngestBlocked, "PROFILE_ROOT_REQUIRED"):
                    MODULE.ingest(root / "workspace", output, "artistic-research", sys.executable)
            exporter.assert_not_called()
            self.assertEqual(b"existing portfolio must survive", existing.read_bytes())
            self.assertEqual([existing], list(output.iterdir()))

    def test_self_model_export_requires_profile_before_reading_checkout(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(MODULE.subprocess, "run") as process:
            with self.assertRaisesRegex(MODULE.IngestBlocked, "PROFILE_ROOT_REQUIRED"):
                MODULE._export({"id": "self-model", "path": "missing"}, Path(directory), "p", sys.executable)
            process.assert_not_called()

    def test_missing_profile_cli_returns_blocked_without_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "signals"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/ingest_signals.py"),
                 "--workspace-root", str(root / "missing"), "--output", str(output),
                 "--purpose", "artistic-research"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertEqual("BLOCKED", json.loads(result.stderr)["status"])
            self.assertIn("PROFILE_ROOT_REQUIRED", json.loads(result.stderr)["detail"])
            self.assertFalse(output.exists())

    def test_every_declared_input_has_an_adapter(self):
        manifest = MODULE.load_yaml(ROOT / "config/repositories.yaml")
        inputs = {item["id"] for item in manifest["repositories"] if item.get("role") == "input-kb"}

        self.assertEqual(inputs, set(MODULE.ADAPTERS))

    def test_missing_exporter_is_reported_with_the_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MODULE.IngestError) as raised:
                MODULE._export({"id": "art-history", "path": "art-history-notes"}, Path(directory), "p", "python3")

        self.assertIn("art-history", str(raised.exception))

    def test_a_failing_export_stops_the_ingest(self):
        """A partial set would hide which knowledge was missing."""
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            checkout = workspace / "art-history-notes/tools"
            checkout.mkdir(parents=True)
            (checkout / "export_signals.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")

            with self.assertRaises(MODULE.IngestError):
                MODULE._export({"id": "art-history", "path": "art-history-notes"}, workspace, "p", "python3")

    def test_non_json_output_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            checkout = workspace / "art-history-notes/tools"
            checkout.mkdir(parents=True)
            (checkout / "export_signals.py").write_text("print('not json')\n", encoding="utf-8")

            with self.assertRaises(MODULE.IngestError) as raised:
                MODULE._export({"id": "art-history", "path": "art-history-notes"}, workspace, "p", "python3")

        self.assertIn("not JSON", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
