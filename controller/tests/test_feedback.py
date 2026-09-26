"""Feedback preserves uncertainty and refuses contradictory evaluator records."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from controller.feedback import FeedbackError, evaluation_feedback


def metric(speedup=1.25, interval=(1.2, 1.3)):
    lo, hi = interval
    return {
        "pairs": 10, "original_median_seconds": 2.5,
        "candidate_median_seconds": 2.0, "speedup": speedup,
        "confidence_interval_95": list(interval),
        "verdict": "improved" if lo > 1 else "slower" if hi < 1 else "inconclusive",
    }


def report():
    metrics = {"application": metric(1.02, (.98, 1.06)), "index": metric()}
    return {
        "mode": "run", "status": "inconclusive",
        "configuration": {"repetitions": 10, "warmups": 2,
                          "bootstrap_resamples": 10000, "bootstrap_seed": 20260924},
        "correctness": {"book-one": {
            "files": 10, "repeat_identical": True, "candidate_identical": True,
            "capture_identical": True, "index_replay_identical": True}},
        "analysis": {"aggregate": deepcopy(metrics),
                     "books": {"book-one": deepcopy(metrics)}, "verdict": "inconclusive"},
    }


class FeedbackTests(unittest.TestCase):
    def test_improvement_and_asymmetric_interval_are_in_time_units(self):
        raw = report()
        result = evaluation_feedback(raw)
        index = result["performance"]["aggregate"]["indexing"]
        self.assertAlmostEqual(index["time_reduction_percent"], 20)
        self.assertAlmostEqual(index["time_reduction_interval_95"][0], 16.6666666667)
        self.assertAlmostEqual(index["time_reduction_interval_95"][1], 23.0769230769)
        offsets = index["interval_offsets_percentage_points"]
        self.assertAlmostEqual(offsets["lower"], -3.3333333333)
        self.assertAlmostEqual(offsets["upper"], 3.0769230769)
        self.assertEqual(index["original_median_seconds"], 2.5)
        self.assertEqual(index["samples_per_variant"], 10)
        self.assertEqual(raw, report(), "adapter must not mutate evidence")

    def test_inconclusive_explains_interval_not_guessed_cause(self):
        build = evaluation_feedback(report())["performance"]["aggregate"]["application_build"]
        self.assertEqual(build["reason_code"], "interval_includes_no_change")
        self.assertAlmostEqual(build["time_reduction_percent"], 1.9607843137)
        self.assertAlmostEqual(build["time_reduction_interval_95"][0], -2.0408163265)
        self.assertIn("includes 1", build["explanation"])
        self.assertNotIn("background", build["explanation"])

    def test_individual_regression_does_not_override_aggregate_rule(self):
        raw = report()
        raw["status"] = raw["analysis"]["verdict"] = "improved"
        raw["analysis"]["aggregate"]["application"] = metric()
        raw["analysis"]["books"]["book-one"]["application"] = metric(.9, (.85, .95))
        raw["correctness"]["book-two"] = deepcopy(raw["correctness"]["book-one"])
        raw["analysis"]["books"]["book-two"] = {
            "application": metric(1.25 ** 2 / .9, (1.7, 1.8)), "index": metric()}
        result = evaluation_feedback(raw)
        self.assertEqual(result["outcome"], "improved")
        regressions = result["performance"]["regressions"]
        self.assertEqual(regressions[0]["book"], "book-one")
        self.assertEqual(regressions[0]["classification"], "confirmed_slowdown")
        self.assertIn("slowdown signals: 1", result["summary"])

    def test_uncertain_point_slowdown_is_distinguished(self):
        raw = report()
        raw["analysis"]["books"]["book-one"]["index"] = metric(.99, (.95, 1.02))
        raw["correctness"]["book-two"] = deepcopy(raw["correctness"]["book-one"])
        raw["analysis"]["books"]["book-two"] = {
            "application": deepcopy(raw["analysis"]["aggregate"]["application"]),
            "index": metric(1.25 ** 2 / .99, (1.5, 1.7))}
        row = evaluation_feedback(raw)["performance"]["regressions"][0]
        self.assertEqual(row["classification"], "point_estimate_slowdown_not_established")

    def test_missing_measurements_are_not_inconclusive(self):
        raw = report()
        raw["status"] = "incomplete"
        raw["error"] = "Command timed out"
        del raw["analysis"]
        result = evaluation_feedback(raw)
        self.assertEqual(result["execution_status"], "failed")
        self.assertEqual(result["performance"]["status"], "not_measured")
        self.assertEqual(result["performance"]["aggregate"], {})
        self.assertEqual(result["error"], "Command timed out")

    def test_correctness_failure_retains_completed_checks(self):
        raw = report()
        raw["status"] = "correctness-failed"
        raw["error"] = "Replayed search index differs"
        del raw["analysis"]
        result = evaluation_feedback(raw)
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(result["correctness"]["status"], "failed")
        self.assertEqual(result["correctness"]["completed_book_count"], 1)
        self.assertEqual(result["correctness"]["failures"][0]["message"], raw["error"])

    def test_late_failure_does_not_make_existing_analysis_eligible(self):
        raw = report()
        raw["status"] = "incomplete"
        raw["error"] = "Evaluator changed during run"
        result = evaluation_feedback(raw)
        self.assertEqual(result["performance"]["status"], "run_invalid")
        self.assertIn("not eligible", result["summary"])

    def test_self_check_validated_and_calibration_warning(self):
        raw = report()
        raw["mode"] = "self-check"
        raw["status"] = "calibration-warning"
        self.assertEqual(evaluation_feedback(raw)["outcome"], "calibration-warning")
        raw["analysis"]["aggregate"]["index"] = metric(1.0, (.98, 1.02))
        raw["analysis"]["books"]["book-one"]["index"] = metric(1.0, (.98, 1.02))
        raw["status"] = "validated"
        self.assertEqual(evaluation_feedback(raw)["outcome"], "validated")
        raw["status"] = "calibration-warning"
        with self.assertRaises(FeedbackError):
            evaluation_feedback(raw)

    def test_rejects_nonfinite_nonpositive_or_boolean_numbers(self):
        for value in (float("nan"), float("inf"), 0, -1, True):
            for field in ("speedup", "candidate_median_seconds"):
                with self.subTest(value=value, field=field):
                    raw = report()
                    raw["analysis"]["aggregate"]["index"][field] = value
                    with self.assertRaises(FeedbackError):
                        evaluation_feedback(raw)

    def test_rejects_reversed_invalid_or_inconsistent_intervals(self):
        for interval in ([1.3, 1.2], [0, 1.2], [.8, .9], [float("nan"), 1.3], [1.2]):
            with self.subTest(interval=interval):
                raw = report()
                raw["analysis"]["aggregate"]["index"]["confidence_interval_95"] = interval
                with self.assertRaises(FeedbackError):
                    evaluation_feedback(raw)

    def test_rejects_inconsistent_status_and_missing_evidence(self):
        for mutation in (
            lambda r: r.update(status="improved"),
            lambda r: r.update(status="mystery"),
            lambda r: r.update(status="validated"),
            lambda r: r.update(error="failure"),
            lambda r: r.pop("analysis"),
            lambda r: r.pop("correctness"),
            lambda r: r["analysis"].update(verdict="improved"),
            lambda r: r["analysis"]["aggregate"].pop("index"),
            lambda r: r["analysis"]["aggregate"]["index"].update(pairs=9),
            lambda r: r["analysis"]["aggregate"]["index"].update(speedup=1.24),
            lambda r: r["correctness"]["book-one"].update(candidate_identical=False),
            lambda r: r["correctness"]["book-one"].update(index_replay_identical=False),
        ):
            raw = report()
            mutation(raw)
            with self.assertRaises(FeedbackError):
                evaluation_feedback(raw)

    def test_no_check_results_does_not_claim_correctness(self):
        raw = report()
        raw["status"] = "incomplete"
        del raw["correctness"]
        del raw["analysis"]
        result = evaluation_feedback(raw)
        self.assertEqual(result["correctness"]["status"], "not_completed")

    def test_configuration_and_timer_semantics_are_explicit(self):
        result = evaluation_feedback(report())
        measurement = result["performance"]["measurement"]
        self.assertEqual(measurement["books_measured"], 1)
        self.assertEqual(measurement["bootstrap_resamples"], 10000)
        self.assertEqual(measurement["warmups_per_variant_per_book"], 2)
        self.assertIn("not total elapsed time", measurement["aggregate_median_semantics"])
        self.assertIn("not a ratio of medians", measurement["speedup_semantics"])


if __name__ == "__main__":
    unittest.main()
