from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.input_pipeline import run_input_pipeline
from tools.research_request import build_research_request, validate_research_request
from tools.signal_bundle import build_signal_bundle


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = ROOT.parent / "agentic-art-research"


def fixture_signals() -> list[dict]:
    return [
        json.loads((ROOT / "tests" / "fixtures" / "signal" / name).read_text(encoding="utf-8"))
        for name in ("valid_self.json", "valid_art_history.json", "valid_marketing.json")
    ]


class ResearchRequestTests(unittest.TestCase):
    def test_request_is_child_schema_shaped_and_does_not_copy_signal_text(self) -> None:
        bundle = build_signal_bundle(fixture_signals(), "2026-08-14T00:00:00+09:00")
        result = run_input_pipeline(bundle, project_id="pipeline-test", seed_input="default")
        request = build_research_request(
            result["selection"],
            bundle,
            request_id="RR901",
            requested_at="2026-08-14T00:00:00+09:00",
            project_slug="pipeline-test",
            source_commit="a" * 40,
        )
        self.assertEqual([], validate_research_request(request))
        self.assertEqual(["Preserve source repository commits and evidence locators."], request["constraints"]["technical"])
        rendered = json.dumps(request, ensure_ascii=False)
        self.assertNotIn("Revalidate stale fixture", rendered)

    @unittest.skipUnless(RESEARCH_ROOT.is_dir(), "sibling Research checkout is not available in this CI job")
    def test_generated_request_reaches_research_dry_run(self) -> None:
        bundle = build_signal_bundle(fixture_signals(), "2026-08-14T00:00:00+09:00")
        result = run_input_pipeline(bundle, project_id="pipeline-test", seed_input="default")
        request = build_research_request(
            result["selection"],
            bundle,
            request_id="RR902",
            requested_at="2026-08-14T00:00:00+09:00",
            project_slug="pipeline-test-dry-run",
            source_commit="b" * 40,
        )
        import yaml

        with tempfile.TemporaryDirectory(prefix="research-request-test-") as temporary:
            request_path = Path(temporary) / "research-request.yaml"
            request_path.write_text(yaml.safe_dump(request, allow_unicode=True, sort_keys=False), encoding="utf-8")
            child_python = RESEARCH_ROOT / ".venv" / "bin" / "python"
            executable = str(child_python if child_python.is_file() else sys.executable)
            completed = subprocess.run(
                [executable, str(RESEARCH_ROOT / "tools" / "accept_research_request.py"), str(request_path), "--dry-run", "--root", str(RESEARCH_ROOT)],
                cwd=RESEARCH_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("DRY_RUN", json.loads(completed.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
