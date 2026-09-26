import json
from pathlib import Path
import tempfile
import unittest

from controller.records import Records, load


class RecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.records = Records(self.root)

    def test_immutable_requests_and_append_only_events_render_same_history(self):
        ref = self.records.write("steps/one/request.json", {"objective": "improve"})
        self.records.event("component_started", step_id="one", request=ref)
        self.records.event("decision", summary="Needs revision", evidence=ref)
        self.records.render("running")
        with self.assertRaises(FileExistsError):
            self.records.write("steps/one/request.json", {})
        events = [json.loads(line) for line in (self.root / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["sequence"] for event in events], [1, 2])
        self.assertIn("Needs revision", (self.root / "report.md").read_text())
        self.assertIn("steps/one/request.json", (self.root / "report.md").read_text())
        self.records.verify()

    def test_changed_or_missing_artifacts_fail(self):
        ref = self.records.write("source.json", {"unchanged": True})
        (self.root / ref["path"]).write_text("tampered")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.records.verify()
        (self.root / ref["path"]).unlink()
        with self.assertRaises(ValueError):
            self.records.verify()

    def test_rejects_escaped_paths_symlinks_and_nonfinite_json(self):
        with self.assertRaises(ValueError):
            self.records.write("../outside.json", {})
        self.records.write("actual.json", {})
        (self.root / "link.json").symlink_to("actual.json")
        with self.assertRaises(ValueError):
            self.records.ref(self.root / "link.json")
        for text in ('{"value": NaN}', '{"value":1,"value":2}'):
            (self.root / "invalid.json").write_text(text)
            with self.assertRaises(ValueError):
                load(self.root / "invalid.json")

    def test_interruption_leaves_started_step_visible(self):
        self.records.event("component_started", step_id="unfinished")
        self.records.render("cancelled", "Interrupted")
        report = (self.root / "report.md").read_text()
        self.assertIn("unfinished", report)
        self.assertIn("cancelled", report)
        self.assertNotIn("component_finished", report)
