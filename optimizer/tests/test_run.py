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

    def test_runtime_selection_reaches_optimizer_and_report(self):
        for selected, model, endpoint in (("claude", "sonnet", None),
                ("opencode", "qwen3.8:27b-mlx", "http://127.0.0.1:11434/v1")):
            output = self.root / selected
            with patch("optimizer.run.optimize", return_value=response("no-change")) as optimize:
                self.assertEqual(self.run_cli(["--baseline", str(self.baseline), "--output", str(output),
                                               "--agent", selected]), 0)
            self.assertEqual(optimize.call_args.kwargs["agent"], selected)
            self.assertEqual(optimize.call_args.kwargs["model"], model)
            self.assertEqual(optimize.call_args.kwargs["base_url"], endpoint)
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["settings"]["agent"], selected)
            self.assertIn("runtime.py", report["coding_agents_version"]["files"])

    def test_remote_opencode_endpoint_fails_before_creating_attempt(self):
        with self.assertRaises(SystemExit):
            self.run_cli(self.argv + ["--agent", "opencode", "--local-base-url", "https://example.com/v1"])
        self.assertFalse(self.output.exists())

    def test_progress_records_ordered_phases_and_choice_before_editing(self):
        def optimize(workspace, context, destination, **kwargs):
            records = [json.loads(line) for line in (self.output / "progress.jsonl").read_text().splitlines()]
            phases = [record["phase"] for record in records]
            self.assertIn("choice_completed", phases)
            self.assertEqual(phases[-1], "edit_started")
            return response("no-change")
        with patch("optimizer.run.optimize", side_effect=optimize):
            self.assertEqual(self.run_cli(), 0)
        records = [json.loads(line) for line in (self.output / "progress.jsonl").read_text().splitlines()]
        self.assertEqual([record["phase"] for record in records], [
            "context_preparation_started", "context_preparation_completed", "boundary_probe_started",
            "boundary_probe_completed", "choice_started", "choice_completed", "edit_started",
            "edit_completed", "export_completed"])

    def test_failure_progress_preserves_completed_and_unfinished_phases(self):
        with patch("optimizer.run.optimize", side_effect=RuntimeError("Agent failed")):
            self.assertEqual(self.run_cli(), 1)
        records = [json.loads(line) for line in (self.output / "progress.jsonl").read_text().splitlines()]
        self.assertEqual([record["phase"] for record in records][-2:], ["edit_started", "error"])
        self.assertEqual(records[-1]["error_type"], "RuntimeError")
        self.assertEqual(json.loads((self.output / "report.json").read_text())["status"], "incomplete")

    def previous(self):
        previous = self.root / "previous"
        (previous / "src").mkdir(parents=True)
        (previous / "Cargo.toml").write_text('[package]\nname="test"\n')
        (previous / "src/lib.rs").write_text("previous\n")
        (previous / ".git").mkdir()
        (previous / ".git/config").write_text("ignored metadata")
        return previous

    def test_revision_choice_is_recorded_before_editing_and_uses_previous_source(self):
        previous = self.previous()
        calls = []
        def optimize(workspace, context, destination, **kwargs):
            calls.append(kwargs)
            if kwargs.get("selection"):
                self.assertFalse((self.output / "workspace/library").exists())
                self.assertNotEqual(workspace, self.output / "workspace")
                return {"choice": "revise", "reason": "Keep the prior improvement."}
            self.assertEqual((workspace / "library/src/lib.rs").read_text(), "previous\n")
            self.assertEqual(json.loads((context / "starting-point.json").read_text())["choice"], "revise")
            self.assertEqual(json.loads((self.output / "report.json").read_text())["starting_point"]["choice"], "revise")
            (workspace / "library/src/lib.rs").write_text("revised\n")
            (workspace / "proposal.md").write_text("Revision evidence")
            return response()
        with patch("optimizer.run.optimize", side_effect=optimize):
            self.assertEqual(self.run_cli(self.argv + ["--previous-candidate", str(previous)]), 0)
        self.assertLess(calls[1]["timeout"], calls[0]["timeout"])
        self.assertEqual((previous / "src/lib.rs").read_text(), "previous\n")
        self.assertEqual((self.output / "candidate/src/lib.rs").read_text(), "revised\n")
        self.assertFalse((self.output / "context/previous/.git").exists())

    def test_revision_no_change_is_relative_to_selected_candidate(self):
        with patch("optimizer.run.optimize", side_effect=[{"choice": "revise", "reason": "Investigate prior attempt."}, response("no-change")]):
            self.assertEqual(self.run_cli(self.argv + ["--previous-candidate", str(self.previous())]), 0)
        self.assertEqual(json.loads((self.output / "report.json").read_text())["status"], "no-change")
        self.assertFalse((self.output / "candidate").exists())

    def test_restart_choice_uses_original_and_preserves_previous(self):
        with patch("optimizer.run.optimize", side_effect=[{"choice": "restart", "reason": "The prior idea was invalid."}, response("no-change")]):
            self.assertEqual(self.run_cli(self.argv + ["--previous-candidate", str(self.previous())]), 0)
        self.assertEqual((self.output / "workspace/library/src/lib.rs").read_text(), "original\n")

    def test_selection_cannot_change_protected_context(self):
        def select(workspace, context, destination, **kwargs):
            (context / "previous/src/lib.rs").chmod(0o644)
            (context / "previous/src/lib.rs").write_text("tampered")
            return {"choice": "revise", "reason": "Invalid"}
        with patch("optimizer.run.optimize", side_effect=select) as agent:
            self.assertEqual(self.run_cli(self.argv + ["--previous-candidate", str(self.previous())]), 1)
            self.assertEqual(agent.call_count, 1)
        self.assertFalse((self.output / "workspace/library").exists())

    def test_selection_consumes_shared_timeout(self):
        with patch("optimizer.run.optimize", return_value={"choice": "revise", "reason": "Keep it"}) as agent, \
                patch("optimizer.run.time.monotonic", side_effect=[0, 1, 601]):
            self.assertEqual(self.run_cli(self.argv + ["--previous-candidate", str(self.previous())]), 1)
            self.assertEqual(agent.call_count, 1)
        self.assertIn("budget exhausted", (self.output / "report.md").read_text())

    def test_controller_brief_is_frozen_and_linked_in_report(self):
        task = self.root / "task.json"
        task.write_text(json.dumps({"schema_version": "optimizer-task/v1", "experiment_id": "exp",
                                  "attempt_id": "a1", "request_id": "r1", "task": {"objective": "Improve"},
                                  "workload": {"manifest_ref": "books"}}))
        with patch("optimizer.run.optimize", return_value=response("no-change")):
            self.assertEqual(self.run_cli(self.argv + ["--task", str(task)]), 0)
        self.assertEqual((self.output / "context/task.json").read_text(), task.read_text())
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["controller_inputs"]["task"]["request_id"], "r1")

    def test_invalid_task_never_launches_optimizer(self):
        task = self.root / "task.json"
        task.write_text('{"schema_version":"unsupported"}')
        with patch("optimizer.run.optimize") as agent:
            self.assertEqual(self.run_cli(self.argv + ["--task", str(task)]), 1)
            agent.assert_not_called()

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
