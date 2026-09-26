import json
import os
from pathlib import Path
import tempfile
import unittest

from evaluator.core import inventory
from optimizer.checkpoints import BaseCheckpoints
from optimizer.task import prepare_task_inputs


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.context = self.root / "context"
        (self.context / "original/src").mkdir(parents=True)
        (self.context / "original/Cargo.toml").write_text('[package]\nname="example"\n')
        (self.context / "original/Cargo.lock").write_text("package=[]\n")
        (self.context / "original/src/lib.rs").write_text("original")
        self.report = {}
        self.manager = BaseCheckpoints(self.workspace, self.context, self.root, self.report)

    def request(self, **changes):
        value = {"request_id": "first", "base_candidate_id": "original", "contributing_candidate_ids": [], "reason": "Evidence"}
        value.update(changes)
        (self.workspace / "base-request.json").write_text(json.dumps(value))
        self.manager()

    def test_repeated_request_is_idempotent_and_cannot_replace_its_reason(self):
        self.request()
        self.manager()
        self.assertEqual(len(self.manager.checkpoints), 1)
        with self.assertRaisesRegex(ValueError, "reused"):
            self.request(reason="Different")

    def test_unknown_base_and_contributor_are_rejected(self):
        for change in ({"base_candidate_id": "invented"}, {"contributing_candidate_ids": ["invented"]}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "Unknown"):
                self.request(**change)
        self.assertFalse((self.workspace / "library").exists())

    def test_edits_before_first_checkpoint_are_rejected(self):
        (self.workspace / "library").mkdir()
        with self.assertRaisesRegex(ValueError, "preceded"):
            self.request()

    def test_checkpoint_forgery_is_detected(self):
        self.request()
        (self.root / self.manager.checkpoints[0]["path"]).write_text("forged")
        with self.assertRaisesRegex(ValueError, "checkpoint changed"):
            self.manager.verify()

    def test_request_symlink_and_hardlink_are_rejected(self):
        other = self.root / "other"
        other.write_text("{}")
        request = self.workspace / "base-request.json"
        request.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.manager()
        request.unlink()
        os.link(other, request)
        with self.assertRaisesRegex(ValueError, "independent"):
            self.manager()

    def test_response_symlink_cannot_overwrite_external_file(self):
        other = self.root / "other"
        other.write_text("preserved")
        (self.workspace / "base-response.json").symlink_to(other)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.request()
        self.assertEqual(other.read_text(), "preserved")

    def history(self):
        history = self.root / "history"
        tree = history / "candidates/attempt-001/library"
        tree.mkdir(parents=True)
        (tree / "Cargo.toml").write_text('[package]\nname="example"\n')
        (tree / "lib.rs").write_text("previous")
        (history / "summary.md").write_text("All attempts")
        ledger = {"schema_version": "optimizer-history/v1", "entries": [{"candidate_id": "attempt-001"}],
                  "candidates": {"attempt-001": {"path": "candidates/attempt-001/library", "files": inventory(tree)}},
                  "artifacts": inventory(history)}
        (history / "ledger.json").write_text(json.dumps(ledger))
        return history

    def test_history_snapshot_available_as_base_with_original_lock(self):
        identity = prepare_task_inputs(self.context, history=self.history())
        self.assertEqual(identity["history"]["files"], inventory(self.context / "history"))
        self.manager = BaseCheckpoints(self.workspace, self.context, self.root, self.report)
        self.request(base_candidate_id="attempt-001")
        self.assertEqual((self.workspace / "library/lib.rs").read_text(), "previous")
        self.assertEqual((self.workspace / "library/Cargo.lock").read_text(), "package=[]\n")
        self.assertEqual(self.report["starting_point"]["source"], "context/history/candidates/attempt-001/library")

    def test_history_tamper_is_rejected_before_agent_start(self):
        history = self.history()
        (history / "candidates/attempt-001/library/lib.rs").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "manifest"):
            prepare_task_inputs(self.context, history=history)

    def test_history_hardlink_is_rejected(self):
        history = self.history()
        os.link(history / "summary.md", self.root / "summary-link")
        with self.assertRaisesRegex(ValueError, "hard link"):
            prepare_task_inputs(self.context, history=history)

    def test_effective_objective_uses_current_default_for_old_baseline(self):
        (self.context / "evaluation").mkdir()
        (self.context / "evaluation/report.json").write_text('{"configuration":{}}')
        result = prepare_task_inputs(self.context)
        self.assertEqual(result["objective"]["library_reduction_target_percent"], 20)
        self.assertEqual(result["objective"]["source"], "current evaluator/config.json")


if __name__ == "__main__":
    unittest.main()
