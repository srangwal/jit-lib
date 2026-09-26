"""Exercise real adapters and evidence checks with controlled component outputs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from controller.components import Components, EXIT_CODES, REPO
from controller.loop import experiment
from controller.records import Records, load
from controller.tests.test_feedback import metric
from evaluator.core import inventory, sha256, write_json


class ComponentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.experiment = self.root / "experiment"
        self.experiment.mkdir()
        self.records = Records(self.experiment)
        self.args = SimpleNamespace(baseline=self.root / "baseline", profile=None, cache=self.root / "cache",
                                    browser=None, cargo_home=None, model="gpt-6-sol", optimizer_timeout=600,
                                    evaluation_timeout=7200, audit_timeout=3600)
        self.components = Components(self.records, self.args, runner=self.runner)
        self.components.books = [{"id": "book-one", "revision": "pinned"}]
        self.calls = []
        self.change_report = lambda component, report: None
        self.config = load(REPO / "evaluator/config.json")
        self.library = self.args.baseline / "variants/original/library"
        self.file(self.library / "Cargo.toml", '[package]\nname="elasticlunr-rs"\n')
        self.file(self.library / "src/lib.rs", "original\n")
        self.original = inventory(self.library)
        self.file(self.library / "Cargo.lock", 'package=[]\n')
        self.file(self.args.baseline / "variants/original/application/Cargo.toml", "application\n")
        self.file(self.args.baseline / "variants/original/application/src/main.rs", "caller\n")
        self.file(self.args.baseline / "books/book-one/src/SUMMARY.md", "# Chapter\n")
        self.inputs = {"book-one": {"src/SUMMARY.md": sha256(self.args.baseline / "books/book-one/src/SUMMARY.md")}}
        self.baseline_report = self.report("self-check", "validated")
        self.evaluation_files(self.args.baseline, self.baseline_report, self.original)

    def file(self, path, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def report(self, mode="run", status="improved"):
        metrics = {key: metric(1, (.98, 1.02)) if mode == "self-check" else metric()
                   for key in ("application", "index")}
        return {"mode": mode, "status": status, "configuration": deepcopy(self.config),
                "evaluator_version": self.components.version(),
                "variants": {"original": {"library_test_lock_sha256": sha256(self.library / "Cargo.lock")}},
                "correctness": {"book-one": {"files": 1, "repeat_identical": True,
                    "candidate_identical": True, "capture_identical": True, "index_replay_identical": True}},
                "analysis": {"books": {"book-one": deepcopy(metrics)}, "aggregate": metrics,
                             "verdict": "inconclusive" if mode == "self-check" else "improved"}}

    def evaluation_files(self, directory, report, candidate):
        for name, value in {"report.json": report, "books.json": self.components.books,
                            "book-inputs.json": self.inputs, "timings.json": [],
                            "correctness.json": report.get("correctness", {}),
                            "variants/original/library-inputs.json": self.original,
                            "variants/candidate/library-inputs.json": candidate}.items():
            write_json(directory / name, value)

    def runner(self, argv, directory, timeout, cwd):
        component = Path(argv[1]).parent.name
        self.calls.append(component)
        output = Path(argv[argv.index("--output") + 1])
        output.mkdir()
        self.file(directory / "stdout.log", "controlled component output\n")
        self.file(directory / "stderr.log", "")
        if component == "optimizer":
            task_path = Path(argv[argv.index("--task") + 1])
            task = load(task_path)
            candidate = output / "candidate"
            for name in self.original:
                self.file(candidate / name, (self.library / name).read_text())
            self.file(candidate / "src/lib.rs", "candidate\n")
            files = inventory(candidate)
            write_json(output / "candidate-files.json", files)
            choice = {"choice": "restart", "reason": "A new idea", "source": "context/original",
                      "files": inventory(self.library)}
            write_json(output / "starting-point.json", choice)
            report = {"status": "candidate-created", "starting_point": choice,
                      "input_identity": {"baseline_report_sha256": sha256(Path(argv[argv.index("--baseline") + 1]) / "report.json"),
                                         "files": load(self.experiment / task["inputs"]["baseline_ref"]["path"])["files"]},
                      "controller_inputs": {"task": {**{key: task[key] for key in (
                          "experiment_id", "attempt_id", "request_id")}, "sha256": sha256(task_path)}},
                      "candidate": {"sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}}
            if "--previous-candidate" in argv:
                previous = Path(argv[argv.index("--previous-candidate") + 1])
                previous_files = {**inventory(previous), "Cargo.lock": inventory(self.library)["Cargo.lock"]}
                report["controller_inputs"]["previous"] = {"files": previous_files}
        elif component == "evaluator":
            if "self-check" in argv:
                shutil.copytree(self.args.baseline, output, dirs_exist_ok=True)
                report = self.report("self-check", "validated")
                self.evaluation_files(output, report, self.original)
            else:
                candidate = Path(argv[argv.index("--candidate") + 1])
                report = self.report()
                self.evaluation_files(output, report, inventory(candidate))
        else:
            evaluation = Path(argv[argv.index("--evaluation") + 1])
            report = {"status": "no-issue-found", "promoted_checks": [], "unresolved": [],
                      "identity": {"evaluation_report_sha256": sha256(evaluation / "report.json"),
                                   "library_manifest_sha256": {"candidate": sha256(evaluation / "variants/candidate/library-inputs.json")}}}
        self.change_report(component, report)
        write_json(output / "report.json", report)
        return {"execution_status": "completed", "exit_code": EXIT_CODES[component].get(report["status"], 0), "elapsed_seconds": .01}

    def test_full_adapter_loop_qualifies_and_links_rich_feedback(self):
        result = experiment(self.records, self.components)
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(self.calls, ["optimizer", "evaluator", "auditor"])
        feedback = load(self.experiment / result["evaluation"]["path"])
        self.assertAlmostEqual(feedback["performance"]["aggregate"]["indexing"]["time_reduction_percent"], 20)
        self.assertIn("timings.json", feedback["evidence"]["artifacts"])
        self.records.verify()
        self.records.render("qualified")
        self.assertIn("20.00%", (self.experiment / "report.md").read_text())

    def test_stale_baseline_refreshes_before_optimizer_with_same_inputs(self):
        self.baseline_report["evaluator_version"]["sha256"] = "old-version"
        write_json(self.args.baseline / "report.json", self.baseline_report)
        result = experiment(self.records, self.components)
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(self.calls, ["evaluator", "optimizer", "evaluator", "auditor"])
        task = load(self.experiment / "tasks/attempt-001.json")
        self.assertEqual(task["inputs"]["baseline_ref"]["path"], "initial-inputs/identity.json")

    def test_stale_baseline_calibration_warning_stops_without_retry(self):
        self.baseline_report["evaluator_version"]["sha256"] = "old-version"
        write_json(self.args.baseline / "report.json", self.baseline_report)
        def mutate(component, report):
            if component == "evaluator":
                report["status"] = "calibration-warning"
        self.change_report = mutate
        with self.assertRaisesRegex(RuntimeError, "Fresh self-check did not validate"):
            experiment(self.records, self.components)
        self.assertEqual(self.calls, ["evaluator"])

    def test_wrong_task_id_is_rejected_before_evaluation(self):
        def mutate(component, report):
            if component == "optimizer":
                report["controller_inputs"]["task"]["request_id"] = "another-request"
        self.change_report = mutate
        with self.assertRaisesRegex(ValueError, "different task"):
            experiment(self.records, self.components)
        self.assertEqual(self.calls, ["optimizer"])

    def test_second_attempt_receives_rich_measurements_and_audit_findings(self):
        def mutate(component, report):
            if component == "auditor" and self.calls.count("auditor") == 1:
                report.update(status="unresolved", unresolved=["needs-further-evidence"],
                              findings=[{"claim": "Investigate uncommon inputs"}])
        self.change_report = mutate
        result = experiment(self.records, self.components)
        self.assertEqual(result["attempts"], 2)
        feedback = load(self.experiment / "tasks/attempt-002-feedback.json")["evidence"]
        self.assertEqual(feedback[0]["contents"]["performance"]["aggregate"]["indexing"]["speedup_ratio"], 1.25)
        self.assertEqual(feedback[1]["contents"]["report"]["findings"][0]["claim"], "Investigate uncommon inputs")
        self.assertIsNotNone(load(self.experiment / "tasks/attempt-002.json")["inputs"]["previous_candidate_ref"])

    def test_wrong_starting_source_is_rejected(self):
        def mutate(component, report):
            if component == "optimizer":
                report["starting_point"]["files"] = {"wrong": {}}
        self.change_report = mutate
        with self.assertRaisesRegex(ValueError, "starting-point source"):
            experiment(self.records, self.components)

    def test_analysis_missing_selected_book_is_audited_but_cannot_qualify(self):
        def mutate(component, report):
            if component == "evaluator":
                report["analysis"]["books"] = {}
        self.change_report = mutate
        with self.assertRaisesRegex(RuntimeError, "could not complete"):
            experiment(self.records, self.components)
        self.assertEqual(self.calls, ["optimizer", "evaluator", "auditor"])
        feedback = load(self.experiment / "feedback/attempt-001-evaluation.json")
        self.assertIn("every selected book", feedback["error"])

    def test_missing_correctness_coverage_cannot_qualify(self):
        def mutate(component, report):
            if component == "evaluator":
                report["correctness"] = {}
        self.change_report = mutate
        with self.assertRaises(RuntimeError):
            experiment(self.records, self.components)
        self.assertIn("all prepared books", (self.experiment / "feedback/attempt-001-evaluation.json").read_text())

    def test_audit_cannot_claim_clean_with_added_check(self):
        def mutate(component, report):
            if component == "auditor":
                report["promoted_checks"] = ["some-check"]
        self.change_report = mutate
        with self.assertRaisesRegex(ValueError, "Clean audit contradicts"):
            experiment(self.records, self.components)

    def test_wrong_audit_evaluation_identity_is_rejected(self):
        def mutate(component, report):
            if component == "auditor":
                report["identity"]["evaluation_report_sha256"] = "wrong"
        self.change_report = mutate
        with self.assertRaisesRegex(ValueError, "different evaluation"):
            experiment(self.records, self.components)

    def test_raw_timings_tampering_is_detected(self):
        result = experiment(self.records, self.components)
        path = self.experiment / "steps/attempt-001-evaluate/output/timings.json"
        path.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "timings.json"):
            self.records.verify()

    def test_malformed_report_and_exit_mismatch_leave_failure_records(self):
        def bad_runner(argv, directory, timeout, cwd):
            output = Path(argv[argv.index("--output") + 1])
            write_json(output / "report.json", {"status": "improved"})
            return {"execution_status": "completed", "exit_code": 17}
        self.components.runner = bad_runner
        result = self.components.step("evaluator", "bad", {}, [], 10)
        self.assertEqual(result["status"], "incomplete")
        record = load(self.experiment / result["result_ref"]["path"])
        self.assertIn("contradicts", record["protocol_error"])
        self.assertEqual(record["process"]["exit_code"], 17)

    def test_only_reported_new_audit_fixtures_may_change_evaluator(self):
        before = {"files": {"run.py": "stable"}}
        after = {"sha256": "new", "files": {"run.py": "stable", "fixtures/audit-example/book.toml": "new"}}
        audit = {"report": {"promoted_checks": [str(REPO / "evaluator/fixtures/audit-example")]}}
        self.components.validate_check_change(before, after, audit)
        after["files"]["run.py"] = "changed"
        with self.assertRaisesRegex(ValueError, "existing evaluator"):
            self.components.validate_check_change(before, after, audit)

    def test_non_string_status_is_a_recorded_protocol_failure(self):
        def runner(argv, directory, timeout, cwd):
            write_json(Path(argv[argv.index("--output") + 1]) / "report.json", {"status": []})
            return {"execution_status": "completed", "exit_code": 0}
        self.components.runner = runner
        result = self.components.step("evaluator", "invalid-status", {}, [], 10)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("Invalid evaluator report status", load(self.experiment / result["result_ref"]["path"])["protocol_error"])
