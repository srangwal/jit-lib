import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from controller.records import load
from controller.run import main


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.output = self.root / "experiment"
        self.argv = ["--baseline", str(self.root / "missing-baseline"), "--output", str(self.output)]

    def run_cli(self, extra=()):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(self.argv + list(extra))

    def test_limits_are_checked_before_work(self):
        for args in (["--attempts", "6"], ["--optimizer-timeout", "601"],
                     ["--audit-timeout", "nan"], ["--evaluation-timeout", "0"]):
            with self.assertRaises(SystemExit):
                self.run_cli(args)
            self.assertFalse(self.output.exists())

    def test_missing_baseline_records_failure_without_launching_components(self):
        with patch("controller.run.check_platform"), patch("controller.components.run_process") as process:
            self.assertEqual(self.run_cli(), 1)
            process.assert_not_called()
        summary = load(self.output / "summary.json")
        self.assertEqual(summary["status"], "incomplete")
        self.assertIn("FileNotFoundError", summary["error"])
        self.assertIn("incomplete", (self.output / "report.md").read_text())

    def test_existing_experiment_is_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "summary.json"
        marker.write_text("keep")
        with self.assertRaises(SystemExit):
            self.run_cli()
        self.assertEqual(marker.read_text(), "keep")

    def test_cancelled_experiment_retains_distinct_status(self):
        with patch("controller.run.check_platform"), patch("controller.run.experiment", side_effect=KeyboardInterrupt):
            self.assertEqual(self.run_cli(), 130)
        self.assertEqual(load(self.output / "summary.json")["status"], "cancelled")

    def test_independent_agents_and_models_are_recorded(self):
        with patch("controller.run.check_platform"), patch("controller.run.experiment", return_value={"status": "no-qualifying-improvement"}):
            self.assertEqual(self.run_cli(["--optimizer-agent", "opencode", "--auditor-agent", "claude",
                                           "--auditor-model", "explicit-claude-model"]), 2)
        config = load(self.output / "configuration.json")
        self.assertEqual(config["optimizer_runtime"], {"agent": "opencode", "model": "qwen3.8:27b-mlx",
                                                      "local_base_url": "http://127.0.0.1:11434/v1"})
        self.assertEqual(config["auditor_runtime"], {"agent": "claude", "model": "explicit-claude-model", "local_base_url": None})
        self.assertIn("coding_agents", config["code_versions"])

    def test_local_endpoint_is_not_accepted_for_cloud_agents(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["--local-base-url", "http://127.0.0.1:11434/v1"])
        self.assertFalse(self.output.exists())
