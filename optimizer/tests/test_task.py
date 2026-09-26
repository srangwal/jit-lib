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


if __name__ == "__main__":
    unittest.main()
