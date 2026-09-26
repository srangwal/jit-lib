"""Exercise the experiment policy with frozen files and controlled components."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from controller.loop import experiment
from controller.records import Records


class FakeComponents:
    def __init__(self, records, plans):
        self.records = records
        self.plans = plans
        self.calls = []
        self.optimizer_inputs = []
        self.current_version = "v1"
        self.current_plan = None
        self.current_candidate = None

    def initialize(self):
        self.calls.append(("initialize",))
        return {"version": self.current_version, "id": "initial"}

    def version(self):
        return self.current_version

    def optimize(self, attempt, baseline, previous, feedback):
        self.calls.append(("optimize", attempt))
        self.optimizer_inputs.append({"baseline": baseline, "previous": previous, "feedback": list(feedback)})
        self.current_plan = self.plans[len(self.optimizer_inputs) - 1]
        status = self.current_plan.get("optimizer", "candidate-created")
        result = {"status": status, "result_ref": self.records.write(
            f"{attempt}/optimizer.json", {"status": status})}
        if status == "candidate-created":
            candidate = {"manifest_ref": self.records.write(f"{attempt}/manifest.json", {"source": attempt})}
            self.current_candidate = candidate
            result["candidate"] = candidate
        return result

    def check_candidate(self, candidate):
        self.calls.append(("check_candidate", candidate["manifest_ref"]["path"]))
        self.records.verify()

    def evaluate(self, attempt, baseline, candidate):
        self.calls.append(("evaluate", attempt, baseline["id"], candidate))
        if self.current_plan.get("evaluation_error"):
            raise RuntimeError("Evaluation infrastructure failed")
        key = "reevaluation" if attempt.endswith("-recheck") else "evaluation"
        status = self.current_plan.get(key, "improved")
        return {"status": status, "evaluator_version": self.current_version,
                "result_ref": self.records.write(f"{attempt}/evaluation.json", {
                    "status": status, "candidate": candidate["manifest_ref"], "version": self.current_version})}

    def audit(self, attempt, candidate, evaluation):
        self.calls.append(("audit", attempt, evaluation["status"]))
        if self.current_plan.get("audit_error"):
            raise RuntimeError("Audit infrastructure failed")
        if self.current_plan.get("changes_checks"):
            self.current_version = "v2"
        if self.current_plan.get("tamper_candidate"):
            (self.records.root / candidate["manifest_ref"]["path"]).write_text("changed")
        return {"status": self.current_plan.get("audit", "no-issue-found"),
                "result_ref": self.records.write(f"{attempt}/audit.json", {
                    "status": self.current_plan.get("audit", "no-issue-found")})}

    def validate_check_change(self, before, after, audit):
        self.calls.append(("validate_check_change", before, after))
        if self.current_plan.get("invalid_change"):
            raise ValueError("Auditor changed existing evaluator code/checks")

    def refresh_baseline(self, attempt):
        self.calls.append(("refresh_baseline", attempt))
        if self.current_plan.get("refresh_error"):
            raise RuntimeError("Fresh self-check did not validate")
        return {"version": self.current_version, "id": "refreshed"}

    def verify_qualification(self, baseline, candidate, evaluation, audit):
        self.calls.append(("verify_qualification",))
        if self.current_plan.get("stale_qualification"):
            self.current_version = "v-stale"
        if baseline["version"] != self.current_version or evaluation["evaluator_version"] != self.current_version:
            raise ValueError("Cannot qualify stale evaluation evidence")


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.records = Records(Path(self.temp.name).resolve())
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def run_plans(self, plans, max_attempts=None):
        self.components = FakeComponents(self.records, plans)
        return experiment(self.records, self.components, max_attempts=max_attempts or len(plans))

    def events(self):
        path = self.records.root / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def calls(self, name):
        return [call for call in self.components.calls if call[0] == name]

    def test_first_qualifying_candidate_stops_without_spending_remaining_attempts(self):
        result = self.run_plans([{}, {}, {}, {}, {}])
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(len(self.calls("optimize")), 1)
        self.assertEqual(len(self.calls("audit")), 1)
        self.assertEqual(len(self.calls("verify_qualification")), 1)
        self.assertEqual(self.events()[-1]["decision"], "qualify")
        self.records.verify()

    def test_five_no_change_attempts_exhaust_budget_with_linked_feedback(self):
        result = self.run_plans([{"optimizer": "no-change"}] * 5)
        self.assertEqual(result, {"status": "no-qualifying-improvement", "attempts": 5})
        self.assertEqual(len(self.calls("optimize")), 5)
        self.assertEqual(self.calls("evaluate"), [])
        self.assertEqual(self.calls("audit"), [])
        last = self.components.optimizer_inputs[-1]
        self.assertEqual(len(last["feedback"]), 4)
        self.assertIsNone(last["previous"])
        self.records.verify()

    def test_every_failed_or_unproven_candidate_is_audited_and_passed_forward(self):
        result = self.run_plans([
            {"evaluation": "correctness-failed", "audit": "confirmed-violation"},
            {"evaluation": "slower"}, {"evaluation": "inconclusive"}, {}])
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["attempts"], 4)
        self.assertEqual([call[2] for call in self.calls("audit")],
                         ["correctness-failed", "slower", "inconclusive", "improved"])
        for number, invocation in enumerate(self.components.optimizer_inputs[1:], 1):
            previous_attempt = f"attempt-{number:03d}"
            self.assertEqual(invocation["previous"]["manifest_ref"]["path"], previous_attempt + "/manifest.json")
            self.assertEqual([ref["path"] for ref in invocation["feedback"]],
                             [previous_attempt + "/evaluation.json", previous_attempt + "/audit.json"])

    def test_incomplete_evaluation_is_audited_before_stopping(self):
        with self.assertRaisesRegex(RuntimeError, "could not complete"):
            self.run_plans([{"evaluation": "incomplete"}, {}])
        self.assertEqual(self.calls("audit"), [("audit", "attempt-001", "incomplete")])
        self.assertEqual(len(self.calls("optimize")), 1)
        self.assertFalse(any(event.get("decision") == "qualify" for event in self.events()))

    def test_added_check_refreshes_baseline_then_reevaluates_same_candidate(self):
        result = self.run_plans([
            {"changes_checks": True, "audit": "confirmed-violation", "reevaluation": "correctness-failed"},
            {"optimizer": "no-change"}])
        self.assertEqual(result["status"], "no-qualifying-improvement")
        evaluations = self.calls("evaluate")
        self.assertEqual([call[1:3] for call in evaluations],
                         [("attempt-001", "initial"), ("attempt-001-recheck", "refreshed")])
        self.assertIs(evaluations[0][3], evaluations[1][3])
        phase_names = [call[0] for call in self.components.calls]
        refresh = phase_names.index("refresh_baseline")
        self.assertEqual(phase_names[refresh + 1], "evaluate")
        second = self.components.optimizer_inputs[1]
        self.assertEqual(second["baseline"]["version"], "v2")
        self.assertIs(second["previous"], evaluations[0][3])
        self.assertEqual(second["feedback"][-1]["path"], "attempt-001-recheck/evaluation.json")
        changed = next(event for event in self.events() if event["event"] == "checks_changed")
        self.assertEqual((changed["evaluator_before"], changed["evaluator_after"]), ("v1", "v2"))
        self.assertEqual(changed["invalidated_results"][0]["path"], "attempt-001/evaluation.json")
        self.assertTrue(changed["invalidates_all_prior_versions"])

    def test_unresolved_audit_cannot_qualify_an_improved_candidate(self):
        result = self.run_plans([{"audit": "unresolved"}])
        self.assertEqual(result["status"], "no-qualifying-improvement")
        self.assertEqual(self.calls("verify_qualification"), [])
        self.assertIn("audit=unresolved", self.events()[-1]["summary"])

    def test_unapproved_source_change_stops_before_refresh_or_selection(self):
        with self.assertRaisesRegex(ValueError, "existing evaluator"):
            self.run_plans([{"changes_checks": True, "invalid_change": True}])
        self.assertEqual(self.calls("validate_check_change"), [("validate_check_change", "v1", "v2")])
        self.assertEqual(self.calls("refresh_baseline"), [])
        self.assertEqual(self.calls("verify_qualification"), [])

    def test_audit_incomplete_stops_without_next_attempt(self):
        with self.assertRaisesRegex(RuntimeError, "could not complete"):
            self.run_plans([{"audit": "incomplete"}, {}])
        self.assertEqual(len(self.calls("audit")), 1)
        self.assertEqual(len(self.calls("optimize")), 1)

    def test_audit_exception_stops_without_next_attempt(self):
        with self.assertRaisesRegex(RuntimeError, "Audit infrastructure"):
            self.run_plans([{"audit_error": True}, {}])
        self.assertEqual(len(self.calls("optimize")), 1)

    def test_evaluation_exception_stops_without_claiming_result(self):
        with self.assertRaisesRegex(RuntimeError, "Evaluation infrastructure"):
            self.run_plans([{"evaluation_error": True}, {}])
        self.assertEqual(len(self.calls("optimize")), 1)
        self.assertFalse(any(event.get("decision") == "qualify" for event in self.events()))

    def test_stale_qualification_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale evaluation"):
            self.run_plans([{"stale_qualification": True}])
        self.assertEqual(len(self.calls("verify_qualification")), 1)
        self.assertFalse(any(event.get("decision") == "qualify" for event in self.events()))

    def test_candidate_tampering_during_audit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Recorded artifact changed"):
            self.run_plans([{"tamper_candidate": True}])
        self.assertEqual(self.calls("verify_qualification"), [])

    def test_failed_self_check_after_new_checks_stops(self):
        with self.assertRaisesRegex(RuntimeError, "self-check did not validate"):
            self.run_plans([{"changes_checks": True, "refresh_error": True}])
        self.assertEqual(len(self.calls("evaluate")), 1)
        self.assertEqual(self.calls("verify_qualification"), [])

    def test_incomplete_optimizer_stops_before_evaluation(self):
        with self.assertRaisesRegex(RuntimeError, "Optimizer did not complete"):
            self.run_plans([{"optimizer": "incomplete"}, {}])
        self.assertEqual(self.calls("evaluate"), [])
        self.assertEqual(self.calls("audit"), [])


if __name__ == "__main__":
    unittest.main()
