import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_index


class CaptureTests(unittest.TestCase):
    def test_wrong_source_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            path = source / "crates/mdbook-html/src/html_handlebars/search.rs"
            path.parent.mkdir(parents=True)
            path.write_text("unknown source")
            with self.assertRaisesRegex(ValueError, "unmodified mdBook"):
                capture_index.instrument(source)
            self.assertEqual(path.read_text(), "unknown source")

    def test_missing_patch_anchor_does_not_partially_write(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            path = source / "crates/mdbook-html/src/html_handlebars/search.rs"
            path.parent.mkdir(parents=True)
            data = b"const MAX_WORD_LENGTH_TO_INDEX: usize = 80;"
            path.write_bytes(data)
            with patch.object(capture_index, "SEARCH_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    capture_index.instrument(source)
            self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
