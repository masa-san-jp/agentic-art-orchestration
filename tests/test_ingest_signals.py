from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("orchestration_ingest", ROOT / "tools/ingest_signals.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class IngestConfigurationTests(unittest.TestCase):
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
