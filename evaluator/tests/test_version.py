from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import evaluator_fingerprint


class VersionTests(unittest.TestCase):
    def test_promoted_fixtures_change_version_but_build_artifacts_do_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "run.py").write_text("harness")
            before = evaluator_fingerprint(root)
            (root / "target").mkdir()
            (root / "target/generated.rs").write_text("artifact")
            self.assertEqual(evaluator_fingerprint(root), before)
            fixture = root / "fixtures/audit-test/src"
            fixture.mkdir(parents=True)
            (fixture / "chapter.md").write_text("new regression")
            after = evaluator_fingerprint(root)
            self.assertNotEqual(before["sha256"], after["sha256"])
            self.assertIn("fixtures/audit-test/src/chapter.md", after["files"])


if __name__ == "__main__":
    unittest.main()
