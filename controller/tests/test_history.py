"""History remains complete and distinguishes old checks without rewriting reports."""

from pathlib import Path
import tempfile
import unittest

from controller.history import write_bundle
from controller.records import Records, load


class HistoryTests(unittest.TestCase):
    def test_no_change_and_every_evaluation_are_retained_with_staleness(self):
        with tempfile.TemporaryDirectory() as directory:
            records = Records(directory)
            optimize = records.write("feedback/optimizer.json", {"outcome": "no-change"})
            first = records.write("feedback/eval1.json", {"evaluator_version": "old"})
            recheck = records.write("feedback/eval2.json", {"evaluator_version": "new"})
            attempts = [{"attempt_id": "attempt-001", "candidate_id": None, "starting_point": None,
                         "summary": "No justified opportunity", "optimizer": {"reference": optimize, "outcome": "no-change"},
                         "evaluations": [{"reference": first, "evaluator_version": "old"},
                                         {"reference": recheck, "evaluator_version": "new"}], "audits": []}]
            bundle, _, files = write_bundle(records, "attempt-002", attempts, {}, "new")
            ledger = load(bundle / "ledger.json")
            evaluations = ledger["entries"][0]["evaluations"]
            self.assertEqual([item["stale"] for item in evaluations], [True, False])
            self.assertNotIn("stale", attempts[0]["evaluations"][0])
            self.assertEqual(load(Path(directory) / first["path"]), {"evaluator_version": "old"})
            self.assertIn("ledger.json", files)
            records.verify()

    def test_evidence_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            records = Records(directory)
            reference = records.write("feedback/optimizer.json", {"outcome": "candidate-created"})
            step = Path(directory) / "steps/attempt-001-optimize"
            step.mkdir(parents=True)
            (step / "logs").symlink_to(Path(directory) / "feedback", target_is_directory=True)
            attempts = [{"attempt_id": "attempt-001", "optimizer": {"reference": reference},
                         "evaluations": [], "audits": []}]
            with self.assertRaisesRegex(ValueError, "symlink"):
                write_bundle(records, "attempt-002", attempts, {}, "v1")
