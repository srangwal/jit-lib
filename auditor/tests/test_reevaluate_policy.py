import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from auditor import run
from evaluator.core import EvaluationError


class ReevaluationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = {"root": self.root / "evidence"}
        self.report = self.package["root"] / "evaluation/report.json"
        self.report.parent.mkdir(parents=True)
        self.args = SimpleNamespace(browser=None, cargo_home=None)

    def reevaluate(self, configuration):
        self.report.write_text(json.dumps({"configuration": configuration}))
        with patch.object(run, "candidate_checkout", return_value=self.root / "candidate"), \
                patch.object(run.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as command:
            result = run.reevaluate(self.package, self.root, self.args)
        argv = command.call_args.args[0]
        self.assertEqual(json.loads((self.root / "reevaluation-command.json").read_text()), argv)
        target = float(argv[argv.index("--library-reduction-target-percent") + 1])
        return result, target

    def test_custom_target_survives_auditor_reevaluation(self):
        result, target = self.reevaluate({"library_reduction_target_percent": 35})
        self.assertEqual(target, 35)
        self.assertEqual(result["library_reduction_target_percent"], 35)
        self.assertEqual(result["library_reduction_target_source"], "evaluation-report")

    def test_zero_target_is_preserved(self):
        result, target = self.reevaluate({"library_reduction_target_percent": 0})
        self.assertEqual(target, 0)
        self.assertEqual(result["library_reduction_target_source"], "evaluation-report")

    def test_historical_report_records_current_default_fallback(self):
        default = json.loads((run.REPO / "evaluator/config.json").read_text())["library_reduction_target_percent"]
        result, target = self.reevaluate({})
        self.assertEqual(target, default)
        self.assertEqual(result["library_reduction_target_source"], "current-evaluator-default")

    def test_invalid_recorded_target_cannot_silently_use_default(self):
        for target in (None, True, -1, 100, float("nan"), float("inf")):
            self.report.write_text(json.dumps({"configuration": {"library_reduction_target_percent": target}}))
            with self.subTest(target=target), patch.object(run, "candidate_checkout") as checkout, \
                    patch.object(run.subprocess, "run") as command, self.assertRaises(EvaluationError):
                run.reevaluate(self.package, self.root, self.args)
            checkout.assert_not_called()
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
