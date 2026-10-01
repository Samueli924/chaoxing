"""Publication regression checks use synthetic repository contents."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

_path = Path(__file__).resolve().parents[1] / "tools/audit/publication_guard.py"
_spec = importlib.util.spec_from_file_location("publication_guard", _path)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


class PublicationTest(unittest.TestCase):
    def test_private_files_are_rejected_even_if_contents_are_sanitized(self):
        paths = ["docs/handoff/notes.md", "docs/artifacts/example.json", "AGENTS.md",
                 "docs/SESSION-LOG.md", "private/notes.md", "capture_sample.txt", "sample.har"]
        self.assertEqual(len(guard.audit_paths("/nonexistent", paths)), len(paths))

    def test_public_usage_and_synthetic_tests_are_allowed(self):
        self.assertEqual(guard.audit_paths("/nonexistent", ["README.md", "LICENSE",
                        "docs/RUNBOOK.md", "tests/test_private_paths.py", ".env.example"]), [])

    def test_internal_records_cannot_be_renamed_into_public_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "README.md").write_text("本轮新增：内部任务进度\n", encoding="utf-8")
            self.assertTrue(guard.audit_paths(directory, ["README.md"]))
