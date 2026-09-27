import unittest

from controller.policy import best_qualifier, stretch_target


def reviewed(candidate_id, reduction, lower, *, audit="no-issue-found", correctness="passed", version="v1"):
    qualifies = lower >= 20 and correctness == "passed"
    return {"candidate": {"candidate_id": candidate_id}, "audit": {
        "status": audit, "result_ref": {"path": candidate_id + "/audit.json"}},
        "evaluation": {"status": "improved" if qualifies else "inconclusive",
                       "evaluator_version": version, "result_ref": {"path": candidate_id + "/evaluation.json"},
                       "feedback": {"correctness": {"status": correctness}, "performance": {
                           "aggregate": {"indexing": {"time_reduction_percent": reduction,
                                                      "time_reduction_interval_95": [lower, reduction + 1]}},
                           "qualification": {"met": qualifies}}}}}


class PolicyTests(unittest.TestCase):
    def test_no_evidence_and_negative_gain_keep_acceptance_floor(self):
        for entries in ([], [reviewed("a", -10, -15)]):
            self.assertEqual(stretch_target(20, entries, "v1")["time_reduction_percent"], 20)
        self.assertIsNone(stretch_target(20, [], "v1")["best_previous"])

    def test_best_measured_gain_sets_stretch_even_before_qualification(self):
        entries = [reviewed("first", 19, 18), reviewed("second", 15, 14)]
        result = stretch_target(20, entries, "v1")
        self.assertEqual(result["time_reduction_percent"], 28.5)
        self.assertEqual(result["best_previous"]["candidate_id"], "first")
        self.assertEqual(result["best_previous"]["evaluation"], entries[0]["evaluation"]["result_ref"])
        self.assertEqual(result["best_previous"]["audit"], entries[0]["audit"]["result_ref"])

    def test_bad_correctness_audits_and_stale_measurements_do_not_raise_target(self):
        entries = [reviewed("correct", 10, 9), reviewed("wrong", 80, 75, correctness="failed"),
                   reviewed("violation", 80, 75, audit="confirmed-violation"),
                   reviewed("unresolved", 80, 75, audit="unresolved"),
                   reviewed("unfinished", 80, 75, audit="incomplete"),
                   reviewed("stale", 80, 75, version="old")]
        self.assertEqual(stretch_target(20, entries, "v1")["time_reduction_percent"], 20)
        self.assertIsNone(best_qualifier(entries, "v1"))

    def test_cap_does_not_lower_a_higher_acceptance_threshold(self):
        entries = [reviewed("a", 80, 75)]
        self.assertEqual(stretch_target(20, entries, "v1")["time_reduction_percent"], 95)
        self.assertEqual(stretch_target(98, entries, "v1")["time_reduction_percent"], 98)

    def test_winner_uses_lower_bound_while_stretch_uses_point_estimate(self):
        entries = [reviewed("high-mean", 40, 21), reviewed("strong-bound", 30, 25)]
        self.assertEqual(best_qualifier(entries, "v1")["candidate"]["candidate_id"], "strong-bound")
        self.assertEqual(stretch_target(20, entries, "v1")["time_reduction_percent"], 60)

    def test_exact_ties_keep_earlier_candidate(self):
        entries = [reviewed("first", 30, 25), reviewed("later", 35, 25)]
        self.assertIs(best_qualifier(entries, "v1"), entries[0])


if __name__ == "__main__":
    unittest.main()
