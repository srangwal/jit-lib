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
        for args in (["--attempts", "1"], ["--attempts", "2"], ["--attempts", "6"], ["--optimizer-timeout", "14401"],
                     ["--audit-timeout", "nan"], ["--evaluation-timeout", "0"],
                     ["--auditor-agent-timeout", "nan"], ["--auditor-agent-timeout", "0"],
                     ["--library-reduction-target-percent", "nan"],
                     ["--library-reduction-target-percent", "100"],
                     ["--library-reduction-target-percent", "-1"]):
            with self.assertRaises(SystemExit):
                self.run_cli(args)
            self.assertFalse(self.output.exists())

    def test_two_hour_agent_budgets_are_accepted_and_recorded(self):
        with patch("controller.run.check_platform"), patch("controller.run.experiment", return_value={"status": "no-qualifying-improvement"}):
            self.assertEqual(self.run_cli(["--optimizer-timeout", "7200",
                                          "--auditor-agent-timeout", "7200", "--audit-timeout", "22500"]), 2)
        config = load(self.output / "configuration.json")
        self.assertEqual(config["optimizer_timeout"], 7200)
        self.assertEqual(config["auditor_agent_timeout"], 7200)
        self.assertEqual(config["audit_timeout"], 22500)

    def test_four_hour_override_does_not_change_default_budgets(self):
        with patch("controller.run.check_platform"), patch("controller.run.experiment", return_value={"status": "no-qualifying-improvement"}):
            self.assertEqual(self.run_cli(["--optimizer-timeout", "14400",
                                          "--auditor-agent-timeout", "14400", "--audit-timeout", "44100"]), 2)
            config = load(self.output / "configuration.json")
            self.assertEqual(config["optimizer_timeout"], 14400)
            self.assertEqual(config["auditor_agent_timeout"], 14400)
            self.assertEqual(config["audit_timeout"], 44100)
            default_output = self.root / "default-experiment"
            self.assertEqual(self.run_cli(["--output", str(default_output)]), 2)
        defaults = load(default_output / "configuration.json")
        self.assertEqual(defaults["optimizer_timeout"], 600)
        self.assertEqual(defaults["auditor_agent_timeout"], 600)
        self.assertEqual(defaults["audit_timeout"], 3600)

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
        self.assertEqual(config["policy"]["library_reduction_target_percent"], 20)
        self.assertFalse(config["policy"]["application_performance_blocks_success"])
        self.assertEqual(config["policy"]["minimum_attempts"], 3)
        self.assertEqual(config["policy"]["maximum_attempts"], 5)
        self.assertEqual(config["policy"]["stretch_ceiling_percent"], 95)
        self.assertEqual(config["policy"]["stretch_multiplier"], 1.5)
        self.assertEqual(config["policy"]["selection"], "highest_lower_95_library_reduction_bound")

    def test_local_endpoint_is_not_accepted_for_cloud_agents(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["--local-base-url", "http://127.0.0.1:11434/v1"])
        self.assertFalse(self.output.exists())
