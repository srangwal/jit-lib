import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluator.core import inventory
from optimizer.run import main
from optimizer.tests.test_artifacts import response


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        (self.baseline / "unchanged").write_text("baseline")
        self.output = self.root / "attempt"
        self.argv = ["--baseline", str(self.baseline), "--output", str(self.output)]
        for target, kwargs in (("optimizer.run.runtime", {"return_value": {"codex": "test-double"}}),
                               ("optimizer.run.check_login", {"return_value": None}),
                               ("optimizer.run.shutil.which", {"return_value": "/fake/codex"}),
                               ("optimizer.run.prepare_context", {"side_effect": self.context}),
                               ("optimizer.run.probe_workspace", {"return_value": {"workspace": True, "context": False}})):
            mock = patch(target, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)

    def context(self, baseline, destination, **kwargs):
        for name, value in {"original/Cargo.toml": '[package]\nname="test"\n',
                            "original/src/lib.rs": "original\n", "original/Cargo.lock": "package=[]\n",
                            "application/src/lib.rs": "caller\n"}.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        return {"limitations": ["Test double context"], "files": inventory(destination)}

    def run_cli(self, argv=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(argv or self.argv)

    def test_candidate_is_exported_without_evaluation_and_metadata_is_saved(self):
        def optimize(workspace, context, destination, **kwargs):
            (workspace / "library/src/lib.rs").write_text("candidate\n")
            (workspace / "proposal.md").write_text("A proposal\n")
            return response()
        with patch("optimizer.run.optimize", side_effect=optimize):
            self.assertEqual(self.run_cli(), 0)
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["status"], "candidate-created")
        self.assertEqual(report["settings"]["model"], "gpt-6-sol")
        self.assertEqual(report["settings"]["timeout_seconds"], 600)
        self.assertIn("optimizer_version", report)
        self.assertNotIn("performance_verdict", report)
        self.assertEqual(list(self.baseline.iterdir()), [self.baseline / "unchanged"])

    def test_no_change_retains_report_without_candidate(self):
        with patch("optimizer.run.optimize", return_value=response("no-change")):
            self.assertEqual(self.run_cli(), 0)
        self.assertEqual(json.loads((self.output / "report.json").read_text())["status"], "no-change")
        self.assertFalse((self.output / "candidate").exists())

    def test_agent_failure_is_incomplete_and_retained(self):
        with patch("optimizer.run.optimize", side_effect=RuntimeError("Agent failed")):
            self.assertEqual(self.run_cli(), 1)
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["error"], "Agent failed")

    def test_auth_failure_keeps_cli_version_and_does_not_invoke_agent(self):
        with patch("optimizer.run.check_login", side_effect=RuntimeError("Authentication required")), \
                patch("optimizer.run.optimize") as agent:
            self.assertEqual(self.run_cli(), 1)
            agent.assert_not_called()
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["runtime"]["codex"], "test-double")
        self.assertEqual(report["status"], "incomplete")

    def test_context_tampering_prevents_candidate_export(self):
        def optimize(workspace, context, destination, **kwargs):
            (context / "application/src/lib.rs").write_text("tampered")
            return response("no-change")
        with patch("optimizer.run.optimize", side_effect=optimize):
            self.assertEqual(self.run_cli(), 1)
        self.assertIn("Protected context", (self.output / "report.md").read_text())

    def test_cannot_overwrite_existing_attempt(self):
        self.output.mkdir()
        (self.output / "report.json").write_text("keep")
        with self.assertRaises(SystemExit):
            self.run_cli()
        self.assertEqual((self.output / "report.json").read_text(), "keep")

    def test_parent_components_cannot_write_into_baseline(self):
        args = ["--baseline", str(self.baseline), "--output", str(self.root / "scratch/../baseline/new")]
        with self.assertRaises(SystemExit):
            self.run_cli(args)
        self.assertEqual(list(self.baseline.iterdir()), [self.baseline / "unchanged"])

    def test_invalid_limits_fail_before_creating_output(self):
        for timeout in ("nan", "inf", "0", "-1"):
            with self.assertRaises(SystemExit):
                self.run_cli(self.argv + ["--timeout", timeout])
            self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
