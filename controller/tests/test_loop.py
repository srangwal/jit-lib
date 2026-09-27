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
        self.configuration = {"library_reduction_target_percent": 20}
        self.calls = []
        self.optimizer_inputs = []
        self.current_version = "v1"
        self.current_plan = None
        self.candidate_plans = {}

    def initialize(self):
        self.calls.append(("initialize",))
        return {"version": self.current_version, "id": "initial"}

    def version(self):
        return self.current_version

    def optimize(self, attempt, baseline, previous, feedback, stretch_target):
        self.calls.append(("optimize", attempt))
        self.optimizer_inputs.append({"baseline": baseline, "previous": previous,
                                      "feedback": list(feedback), "stretch_target": stretch_target})
        self.current_plan = self.plans[len(self.optimizer_inputs) - 1]
        status = self.current_plan.get("optimizer", "candidate-created")
        result = {"status": status, "result_ref": self.records.write(
            f"{attempt}/optimizer.json", {"status": status})}
        if status == "candidate-created":
            candidate = {"candidate_id": attempt, "manifest_ref": self.records.write(
                f"{attempt}/manifest.json", {"source": attempt})}
            self.candidate_plans[attempt] = self.current_plan
            result["candidate"] = candidate
        return result

    def check_candidate(self, candidate):
        self.calls.append(("check_candidate", candidate["manifest_ref"]["path"]))
        self.records.verify()

    def evaluate(self, attempt, baseline, candidate):
        self.calls.append(("evaluate", attempt, baseline["id"], candidate))
        plan = self.candidate_plans[candidate["candidate_id"]]
        rechecking = "-recheck" in attempt
        if plan.get("evaluation_error") or (rechecking and plan.get("reevaluation_error")):
            raise RuntimeError("Evaluation infrastructure failed")
        status = plan.get("reevaluation" if rechecking else "evaluation", "improved")
        default_reduction = {"improved": 25, "slower": -2, "inconclusive": 19}.get(status, 25)
        reduction = plan.get("recheck_reduction" if rechecking else "reduction", default_reduction)
        interval = plan.get("recheck_interval" if rechecking else "interval", [reduction - 1, reduction + 1])
        feedback = {
            "correctness": {"status": "failed" if status == "correctness-failed" else "passed"},
            "performance": {
                "aggregate": {"indexing": {"time_reduction_percent": reduction,
                                            "time_reduction_interval_95": interval}},
                "qualification": {"met": status == "improved"},
            },
        }
        return {"status": status, "evaluator_version": self.current_version, "feedback": feedback,
                "result_ref": self.records.write(f"{attempt}/evaluation.json", {
                    "status": status, "candidate": candidate["manifest_ref"],
                    "version": self.current_version, "feedback": feedback})}

    def audit(self, attempt, candidate, evaluation):
        self.calls.append(("audit", attempt, evaluation["status"]))
        if self.current_plan.get("audit_error"):
            raise RuntimeError("Audit infrastructure failed")
        if self.current_plan.get("changes_checks"):
            self.current_version = f"v{int(self.current_version[1:]) + 1}"
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
        self.calls.append(("verify_qualification", candidate["candidate_id"]))
        if self.candidate_plans[candidate["candidate_id"]].get("stale_qualification"):
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
        budget = max_attempts if max_attempts is not None else max(3, len(plans))
        plans = list(plans) + [{"optimizer": "no-change"}] * max(0, budget - len(plans))
        self.components = FakeComponents(self.records, plans)
        return experiment(self.records, self.components, max_attempts=budget)

    def events(self):
        path = self.records.root / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def calls(self, name):
        return [call for call in self.components.calls if call[0] == name]

    def stretches(self):
        return [invocation["stretch_target"]["time_reduction_percent"]
                for invocation in self.components.optimizer_inputs]

    def test_qualifier_in_first_attempt_still_runs_three_and_breaks_ties_by_age(self):
        result = self.run_plans([{}, {}, {}, {}, {}])
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["candidate"]["path"], "attempt-001/manifest.json")
        self.assertEqual(len(self.calls("optimize")), 3)
        self.assertEqual(len(self.calls("audit")), 3)
        self.assertEqual(len(self.calls("verify_qualification")), 1)
        self.assertEqual(self.events()[-1]["decision"], "qualify")
        selection = json.loads((self.records.root / result["selection"]["path"]).read_text())
        self.assertEqual(selection["candidate_id"], "attempt-001")
        self.assertEqual(selection["tie_break"], "earliest_attempt")
        self.assertEqual([entry["candidate_id"] for entry in selection["qualifying_candidates"]],
                         ["attempt-001", "attempt-002", "attempt-003"])
        self.records.verify()

    def test_selects_highest_lower_confidence_bound_not_largest_point_estimate(self):
        result = self.run_plans([
            {"reduction": 40, "interval": [21, 59]},
            {"reduction": 30, "interval": [28, 32]},
            {"reduction": 35, "interval": [27, 43]}, {}, {}])
        self.assertEqual(result["candidate"]["path"], "attempt-002/manifest.json")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(self.stretches(), [20, 60, 60])

    def test_can_qualify_in_fourth_or_fifth_attempt_and_stops_immediately(self):
        for qualifying_attempt in (4, 5):
            with self.subTest(qualifying_attempt=qualifying_attempt), tempfile.TemporaryDirectory() as temp:
                self.records = Records(Path(temp).resolve())
                plans = [{"evaluation": "inconclusive"}] * (qualifying_attempt - 1) + [{}]
                result = self.run_plans(plans, max_attempts=5)
                self.assertEqual(result["status"], "qualified")
                self.assertEqual(result["attempts"], qualifying_attempt)
                self.assertEqual(len(self.calls("optimize")), qualifying_attempt)
                self.assertEqual(len(self.calls("audit")), qualifying_attempt)
                self.assertEqual(result["candidate"]["path"], f"attempt-{qualifying_attempt:03d}/manifest.json")

    def test_no_change_third_attempt_still_selects_earlier_qualifier(self):
        result = self.run_plans([{}, {"optimizer": "no-change"}, {"optimizer": "no-change"}, {}, {}])
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["candidate"]["path"], "attempt-001/manifest.json")
        self.assertEqual(len(self.calls("audit")), 1)
        self.assertEqual(self.stretches(), [20, 37.5, 37.5])

    def test_five_no_change_attempts_exhaust_budget_with_linked_feedback(self):
        result = self.run_plans([{"optimizer": "no-change"}] * 5)
        self.assertEqual(result, {"status": "no-qualifying-improvement", "attempts": 5})
        self.assertEqual(len(self.calls("optimize")), 5)
        self.assertEqual(self.calls("evaluate"), [])
        self.assertEqual(self.calls("audit"), [])
        last = self.components.optimizer_inputs[-1]
        self.assertEqual(len(last["feedback"]), 4)
        self.assertIsNone(last["previous"])
        self.assertEqual(self.stretches(), [20] * 5)
        self.records.verify()

    def test_five_measured_candidates_below_acceptance_exhaust_budget(self):
        result = self.run_plans([{"evaluation": "inconclusive", "reduction": 21,
                                  "interval": [19, 23]}] * 5)
        self.assertEqual(result, {"status": "no-qualifying-improvement", "attempts": 5})
        self.assertEqual(len(self.calls("audit")), 5)
        self.assertEqual(self.calls("verify_qualification"), [])
        self.assertEqual(self.stretches(), [20, 31.5, 31.5, 31.5, 31.5])

    def test_stretch_uses_best_eligible_measurement_and_links_its_evidence(self):
        self.run_plans([
            {"evaluation": "inconclusive", "reduction": 19, "interval": [18, 20]},
            {"evaluation": "inconclusive", "reduction": 12, "interval": [11, 13]},
            {"optimizer": "no-change"}])
        self.assertEqual(self.stretches(), [20, 28.5, 28.5])
        target = self.components.optimizer_inputs[2]["stretch_target"]
        self.assertEqual(target["acceptance_threshold_percent"], 20)
        self.assertEqual(target["multiplier"], 1.5)
        self.assertEqual(target["ceiling_percent"], 95)
        best = target["best_previous"]
        self.assertEqual(best["candidate_id"], "attempt-001")
        self.assertEqual(best["time_reduction_percent"], 19)
        self.assertEqual(best["evaluation"]["path"], "attempt-001/evaluation.json")
        self.assertEqual(best["audit"]["path"], "attempt-001/audit.json")
        saved_target = json.loads((self.records.root / "tasks/attempt-003-stretch-target.json").read_text())
        self.assertEqual(saved_target, target)

    def test_stretch_ignores_incorrect_and_unclean_candidates_even_with_large_gains(self):
        self.run_plans([
            {"evaluation": "correctness-failed", "reduction": 80},
            {"audit": "unresolved", "reduction": 80},
            {"audit": "confirmed-violation", "reduction": 80},
            {"evaluation": "inconclusive", "reduction": 19},
            {"optimizer": "no-change"}])
        self.assertEqual(self.stretches(), [20, 20, 20, 20, 28.5])
        for invocation in self.components.optimizer_inputs[:4]:
            self.assertIsNone(invocation["stretch_target"]["best_previous"])

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
                             [f"attempt-{prior:03d}/{kind}.json" for prior in range(1, number + 1)
                              for kind in ("evaluation", "audit")])

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
        next_component = next(name for name in phase_names[refresh + 1:] if name != "check_candidate")
        self.assertEqual(next_component, "evaluate")
        second = self.components.optimizer_inputs[1]
        self.assertEqual(second["baseline"]["version"], "v2")
        self.assertIs(second["previous"], evaluations[0][3])
        self.assertEqual(second["feedback"][-1]["path"], "attempt-001-recheck/evaluation.json")
        changed = next(event for event in self.events() if event["event"] == "checks_changed")
        self.assertEqual((changed["evaluator_before"], changed["evaluator_after"]), ("v1", "v2"))
        self.assertEqual(changed["invalidated_results"][0]["path"], "attempt-001/evaluation.json")
        self.assertTrue(changed["invalidates_all_prior_versions"])

    def test_new_checks_refresh_prior_candidate_before_selection_and_invalidate_old_gain(self):
        result = self.run_plans([
            {"reduction": 40, "reevaluation": "correctness-failed"},
            {"evaluation": "inconclusive"},
            {"changes_checks": True, "audit": "confirmed-violation", "reevaluation": "correctness-failed"}])
        self.assertEqual(result["status"], "qualified")
        # The original winner fails the new check. The refreshed second candidate wins.
        self.assertEqual(result["candidate"]["path"], "attempt-002/manifest.json")
        self.assertEqual(result["evaluation"]["path"], "attempt-002-recheck-after-attempt-003/evaluation.json")
        self.assertEqual(result["audit"]["path"], "attempt-002/audit.json")
        self.assertEqual([call[1] for call in self.calls("evaluate")], [
            "attempt-001", "attempt-002", "attempt-003", "attempt-003-recheck",
            "attempt-001-recheck-after-attempt-003", "attempt-002-recheck-after-attempt-003"])
        self.assertEqual(len(self.calls("audit")), 3)
        self.records.verify()

    def test_next_stretch_uses_refreshed_prior_gain_not_stale_measurement(self):
        self.run_plans([
            {"evaluation": "inconclusive", "reduction": 19,
             "reevaluation": "inconclusive", "recheck_reduction": 10},
            {"changes_checks": True, "audit": "unresolved"},
            {"optimizer": "no-change"}])
        self.assertEqual(self.stretches(), [20, 28.5, 20])
        best = self.components.optimizer_inputs[2]["stretch_target"]["best_previous"]
        self.assertEqual(best["time_reduction_percent"], 10)
        self.assertEqual(best["evaluation"]["path"], "attempt-001-recheck-after-attempt-002/evaluation.json")
        self.assertEqual(best["audit"]["path"], "attempt-001/audit.json")

    def test_prior_correctness_failure_with_clean_audit_is_rechecked_and_can_qualify(self):
        result = self.run_plans([
            {"evaluation": "correctness-failed", "reevaluation": "improved", "recheck_reduction": 35},
            {"changes_checks": True, "audit": "confirmed-violation"},
            {"optimizer": "no-change"}])
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["candidate"]["path"], "attempt-001/manifest.json")
        self.assertEqual(result["evaluation"]["path"], "attempt-001-recheck-after-attempt-002/evaluation.json")
        self.assertEqual(self.stretches(), [20, 20, 52.5])
        self.assertEqual(len(self.calls("audit")), 2)

    def test_new_checks_do_not_clear_prior_unresolved_or_confirmed_audits(self):
        result = self.run_plans([
            {"audit": "unresolved", "reduction": 70},
            {"audit": "confirmed-violation", "reduction": 60},
            {"changes_checks": True, "audit": "confirmed-violation", "reduction": 80}])
        self.assertEqual(result["status"], "no-qualifying-improvement")
        self.assertEqual([call[1] for call in self.calls("evaluate")],
                         ["attempt-001", "attempt-002", "attempt-003", "attempt-003-recheck"])
        self.assertEqual(self.stretches(), [20, 20, 20])
        self.assertEqual(self.calls("verify_qualification"), [])

    def test_incomplete_prior_candidate_refresh_stops_before_next_attempt_or_selection(self):
        with self.assertRaisesRegex(RuntimeError, "could not complete"):
            self.run_plans([
                {"reevaluation": "incomplete"},
                {"changes_checks": True, "audit": "confirmed-violation"}, {}])
        self.assertEqual(len(self.calls("optimize")), 2)
        self.assertEqual(self.calls("verify_qualification"), [])
        self.assertIn("attempt-001-recheck-after-attempt-002", [call[1] for call in self.calls("evaluate")])

    def test_unresolved_audit_cannot_qualify_an_improved_candidate(self):
        result = self.run_plans([{"audit": "unresolved"}])
        self.assertEqual(result["status"], "no-qualifying-improvement")
        self.assertEqual(self.calls("verify_qualification"), [])
        self.assertFalse(any(event.get("decision") == "qualify" for event in self.events()))

    def test_later_infrastructure_failure_does_not_select_an_earlier_qualifier(self):
        with self.assertRaisesRegex(RuntimeError, "Audit infrastructure"):
            self.run_plans([{}, {}, {"audit_error": True}])
        self.assertEqual(len(self.calls("optimize")), 3)
        self.assertEqual(self.calls("verify_qualification"), [])
        self.assertFalse(any(event.get("decision") == "qualify" for event in self.events()))

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
