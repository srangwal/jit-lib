import json
from pathlib import Path
import tempfile
import unittest

from optimizer.task import prepare_task_inputs


class TaskInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.context = self.root / "context"
        (self.context / "original").mkdir(parents=True)
        (self.context / "original/Cargo.lock").write_text("original lock")
        self.previous = self.root / "previous"
        self.previous.mkdir()
        (self.previous / "Cargo.toml").write_text('[package]\nname="test"\n')

    def test_previous_cannot_supply_changed_lock(self):
        (self.previous / "Cargo.lock").write_text("changed lock")
        with self.assertRaisesRegex(ValueError, "lockfile"):
            prepare_task_inputs(self.context, previous_candidate=self.previous)

    def test_previous_cannot_escape_through_symlink(self):
        (self.previous / "escape").symlink_to(self.context / "original")
        with self.assertRaisesRegex(ValueError, "link"):
            prepare_task_inputs(self.context, previous_candidate=self.previous)

    def test_previous_rejects_build_artifacts_before_copy(self):
        (self.previous / "target").mkdir()
        with self.assertRaisesRegex(ValueError, "generated"):
            prepare_task_inputs(self.context, previous_candidate=self.previous)
        self.assertFalse((self.context / "previous").exists())

    def test_valid_task_requires_linkage_and_workload(self):
        task = self.root / "task.json"
        value = {"schema_version": "optimizer-task/v1", "experiment_id": "exp", "attempt_id": "a",
                 "request_id": "r", "task": {"objective": "Improve"}, "workload": {"books": ["one"]}}
        for field in ("experiment_id", "attempt_id", "request_id", "task", "workload"):
            invalid = dict(value)
            invalid.pop(field)
            task.write_text(json.dumps(invalid))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                prepare_task_inputs(self.context, task=task)
            self.assertFalse((self.context / "task.json").exists())

    def test_experiment_target_overrides_baseline_target(self):
        (self.context / "evaluation").mkdir()
        (self.context / "evaluation/report.json").write_text(json.dumps({
            "configuration": {"library_reduction_target_percent": 20}}))
        task = self.root / "task.json"
        task.write_text(json.dumps({
            "schema_version": "optimizer-task/v1", "experiment_id": "exp",
            "attempt_id": "a", "request_id": "r",
            "task": {"library_reduction_target_percent": 35},
            "workload": {"books": ["one"]}}))

        result = prepare_task_inputs(self.context, task=task)

        objective = json.loads((self.context / "objective.json").read_text())
        self.assertEqual(objective["library_reduction_target_percent"], 35)
        self.assertEqual(objective["source"], "task.json")
        self.assertEqual(result["objective"]["library_reduction_target_percent"], 35)

    def test_stretch_target_is_preserved_separately_from_acceptance(self):
        task = self.root / "task.json"
        stretch = {"schema_version": "optimizer-stretch-target/v1", "time_reduction_percent": 28.5,
                   "acceptance_threshold_percent": 20, "multiplier": 1.5, "ceiling_percent": 95,
                   "best_previous": {"candidate_id": "attempt-001", "time_reduction_percent": 19,
                                     "evaluation": {"path": "evaluation.json"}, "audit": {"path": "audit.json"}}}
        task.write_text(json.dumps({"schema_version": "optimizer-task/v1", "experiment_id": "exp",
                                   "attempt_id": "a", "request_id": "r", "workload": {"books": ["one"]},
                                   "task": {"library_reduction_target_percent": 20,
                                            "optimizer_stretch_target": stretch}}))
        result = prepare_task_inputs(self.context, task=task)
        objective = json.loads((self.context / "objective.json").read_text())
        self.assertEqual(objective["library_reduction_target_percent"], 20)
        self.assertEqual(objective["optimizer_stretch_target"], stretch)
        self.assertEqual(result["objective"]["optimizer_stretch_target"], stretch)

    def test_invalid_stretch_target_is_rejected(self):
        for bad in (None, True, -1, 19, 100, float("nan"), float("inf")):
            with self.subTest(amount=bad):
                context = self.root / ("context-" + str(bad))
                context.mkdir()
                task = self.root / "task.json"
                task.write_text(json.dumps({"schema_version": "optimizer-task/v1", "experiment_id": "exp",
                    "attempt_id": "a", "request_id": "r", "workload": {"books": ["one"]},
                    "task": {"library_reduction_target_percent": 20, "optimizer_stretch_target": {
                        "schema_version": "optimizer-stretch-target/v1", "acceptance_threshold_percent": 20,
                        "time_reduction_percent": bad}}}))
                with self.assertRaisesRegex(ValueError, "Invalid optimizer stretch target"):
                    prepare_task_inputs(context, task=task)


if __name__ == "__main__":
    unittest.main()
