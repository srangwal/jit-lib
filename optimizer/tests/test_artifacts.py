import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from evaluator.core import inventory
from optimizer.artifacts import copy_files, freeze, seed_cargo_cache


def response(status="candidate"):
    return {"status": status, "summary": "A proposed change", "guarantees": [
        {"claim": "The application guarantees a fixed operation", "application_references": ["application/src/lib.rs:1"]}],
        "removed_work": "Repeated work", "library_references": ["original/src/lib.rs:1"],
        "why_behavior_is_preserved": "Retains the original result", "expected_benefit": "Less repeated work",
        "profile_assessment": "Unprofiled hypothesis", "local_checks": [], "risks": ["Not independently evaluated"]}


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.context, self.workspace = self.root / "context", self.root / "workspace"
        for name, content in {"original/Cargo.toml": '[package]\nname="test"\nversion="0.1.0"\n',
                              "original/Cargo.lock": "# lock\n", "original/src/lib.rs": "old\n",
                              "application/src/lib.rs": "caller\n"}.items():
            path = self.context / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        copy_files(self.context / "original", self.workspace / "library", inventory(self.context / "original"))
        (self.workspace / "proposal.md").write_text("Source-backed proposal\n")

    def change(self):
        (self.workspace / "library/src/lib.rs").write_text("new\n")

    def test_export_is_independent_git_visible_and_patch_applies(self):
        self.change()
        (self.workspace / "library/tests").mkdir()
        (self.workspace / "library/tests/new.rs").write_text("a new regression\n")
        result = freeze(self.workspace, self.context, self.root, response())
        self.assertTrue(result["sha256"])
        exported = self.root / "candidate"
        self.assertFalse((exported / "Cargo.lock").exists())
        files = subprocess.check_output(["git", "-C", str(exported), "ls-files"], text=True)
        self.assertIn("tests/new.rs", files)
        subprocess.run(["git", "-C", str(exported), "apply", "--reverse", "--check", str(self.root / "candidate.patch")], check=True)
        self.assertEqual(subprocess.run(["git", "-C", str(exported), "rev-parse", "--verify", "HEAD"], capture_output=True).returncode, 128)
        (self.workspace / "library/src/lib.rs").write_text("edited again\n")
        self.assertEqual((exported / "src/lib.rs").read_text(), "new\n")
        self.assertEqual((self.context / "original/src/lib.rs").read_text(), "old\n")

    def test_no_change_produces_no_candidate(self):
        self.assertIsNone(freeze(self.workspace, self.context, self.root, response("no-change")))
        self.assertFalse((self.root / "candidate").exists())

    def test_library_references_can_identify_both_original_and_changed_source(self):
        self.change()
        value = response()
        value["library_references"].append("library/src/lib.rs:1")
        self.assertTrue(freeze(self.workspace, self.context, self.root, value)["sha256"])

    def test_changed_source_reference_cannot_replace_original_evidence_or_escape(self):
        self.change()
        for refs in (["library/src/lib.rs:1"], ["original/src/lib.rs:1", "library/../../outside:1"],
                     ["original/src/lib.rs:1", "library/src/lib.rs:999"]):
            value = response()
            value["library_references"] = refs
            with self.assertRaises(ValueError):
                freeze(self.workspace, self.context, self.root, value)

    def test_changed_source_during_export_cannot_receive_a_stale_identity(self):
        self.change()
        real_copy = shutil.copy2

        def changed_copy(source, destination, *args, **kwargs):
            if Path(source) == self.workspace / "library/src/lib.rs":
                Path(source).write_text("raced after inventory\n")
            return real_copy(source, destination, *args, **kwargs)

        with patch("optimizer.artifacts.shutil.copy2", side_effect=changed_copy):
            with self.assertRaisesRegex(ValueError, "changed while exporting"):
                freeze(self.workspace, self.context, self.root, response())
        self.assertFalse((self.root / "candidate-files.json").exists())

    def test_mismatched_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "without a source change"):
            freeze(self.workspace, self.context, self.root, response())
        self.change()
        with self.assertRaisesRegex(ValueError, "reported no-change"):
            freeze(self.workspace, self.context, self.root, response("no-change"))

    def test_invalid_guarantees_and_missing_proposal_are_rejected(self):
        self.change()
        for references in ([], ["application/src/lib.rs:999"], ["application/../../outside:1"], ["original/src/lib.rs:1"]):
            value = response()
            value["guarantees"][0]["application_references"] = references
            with self.assertRaises(ValueError):
                freeze(self.workspace, self.context, self.root, value)
        (self.workspace / "proposal.md").unlink()
        with self.assertRaisesRegex(ValueError, "proposal.md"):
            freeze(self.workspace, self.context, self.root, response())

    def test_changed_lock_is_rejected(self):
        self.change()
        (self.workspace / "library/Cargo.lock").write_text("changed")
        with self.assertRaisesRegex(ValueError, "lockfile"):
            freeze(self.workspace, self.context, self.root, response())

    def test_links_and_generated_files_are_rejected(self):
        self.change()
        target = self.workspace / "library/escaped"
        target.symlink_to(self.context / "original/src/lib.rs")
        with self.assertRaisesRegex(ValueError, "link"):
            freeze(self.workspace, self.context, self.root, response())
        target.unlink()
        os.link(self.context / "original/src/lib.rs", target)
        with self.assertRaisesRegex(ValueError, "hard link"):
            freeze(self.workspace, self.context, self.root, response())
        target.unlink()
        (self.workspace / "library/target").mkdir()
        with self.assertRaisesRegex(ValueError, "generated"):
            freeze(self.workspace, self.context, self.root, response())

    def test_cache_copies_only_locked_archives_and_index_not_secrets(self):
        cache = self.root / "cache"
        for name in ("credentials.toml", "config.toml", "registry/cache/example/serde-1.0.0.crate",
                     "registry/cache/example/unrelated-1.0.0.crate", "registry/index/example/config.json",
                     "registry/index/example/.cache/se/rd/serde"):
            path = cache / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        lock = self.root / "test.lock"
        lock.write_text('[[package]]\nname="serde"\nversion="1.0.0"\nsource="registry+https://github.com/rust-lang/crates.io-index"\n')
        destination = self.root / "private-cache"
        result = seed_cargo_cache(cache, destination, lock)
        self.assertEqual(result["cached_crates"], ["serde-1.0.0"])
        self.assertFalse((destination / "credentials.toml").exists())
        self.assertFalse((destination / "config.toml").exists())
        self.assertFalse((destination / "registry/cache/example/unrelated-1.0.0.crate").exists())
        self.assertTrue((destination / "registry/index/example/.cache/se/rd/serde").is_file())
        self.assertNotEqual((cache / "registry/cache/example/serde-1.0.0.crate").stat().st_ino,
                            (destination / "registry/cache/example/serde-1.0.0.crate").stat().st_ino)


if __name__ == "__main__":
    unittest.main()
