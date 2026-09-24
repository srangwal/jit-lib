import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Commands, CorrectnessError, EvaluationError, analyse, compare, inventory, paired_summary


class OutputComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = self.root / "original"
        self.candidate = self.root / "candidate"
        for directory in (self.original, self.candidate):
            (directory / "nested").mkdir(parents=True)
            (directory / "index.html").write_bytes(b"one")
            (directory / "nested/search.js").write_bytes(b"search")
        self.record = self.root / "comparison.json"

    def check(self):
        compare(inventory(self.original), inventory(self.candidate), self.record)

    def test_identical_content_ignores_timestamps(self):
        os.utime(self.candidate / "index.html", (1, 1))
        self.check()
        self.assertEqual(json.loads(self.record.read_text()), {"missing": [], "extra": [], "changed": []})

    def test_same_length_changed_file_is_rejected_and_named(self):
        (self.candidate / "index.html").write_bytes(b"two")
        with self.assertRaises(CorrectnessError):
            self.check()
        self.assertEqual(json.loads(self.record.read_text())["changed"], ["index.html"])

    def test_missing_and_extra_files_are_rejected_and_named(self):
        (self.candidate / "nested/search.js").unlink()
        (self.candidate / "extra.js").write_bytes(b"search")
        with self.assertRaises(CorrectnessError):
            self.check()
        self.assertEqual(json.loads(self.record.read_text()), {
            "missing": ["nested/search.js"], "extra": ["extra.js"], "changed": []})

    def test_missing_empty_and_symlink_outputs_are_rejected(self):
        with self.assertRaises(CorrectnessError):
            inventory(self.root / "absent")
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(CorrectnessError):
            inventory(empty)
        (self.candidate / "link").symlink_to(self.original / "index.html")
        with self.assertRaises(CorrectnessError):
            inventory(self.candidate)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.commands = Commands(self.root / "logs", timeout=5)

    def run_python(self, code):
        return self.commands([sys.executable, "-c", code], cwd=self.root, env=os.environ.copy())

    def test_success_records_exact_command_outputs_and_duration(self):
        record = self.run_python("import sys; print('stdout'); print('stderr', file=sys.stderr)")
        self.assertEqual(record["exit_code"], 0)
        self.assertGreater(record["elapsed_seconds"], 0)
        self.assertEqual(Path(record["stdout"]).read_text(), "stdout\n")
        self.assertEqual(Path(record["stderr"]).read_text(), "stderr\n")
        self.assertEqual(json.loads((self.root / "logs/0001.json").read_text()), record)
        self.assertEqual(record["argv"][:2], [sys.executable, "-c"])

    def test_nonzero_exit_preserves_logs_and_failure_code(self):
        with self.assertRaisesRegex(EvaluationError, "deliberate failure"):
            self.run_python("import sys; print('before failure'); print('deliberate failure', file=sys.stderr); sys.exit(7)")
        record = json.loads((self.root / "logs/0001.json").read_text())
        self.assertEqual(record["exit_code"], 7)
        self.assertEqual(Path(record["stdout"]).read_text(), "before failure\n")
        self.assertEqual(Path(record["stderr"]).read_text(), "deliberate failure\n")

    def test_missing_executable_still_records_error(self):
        with self.assertRaises(EvaluationError):
            self.commands([self.root / "does-not-exist"], cwd=self.root, env=os.environ.copy())
        record = json.loads((self.root / "logs/0001.json").read_text())
        self.assertTrue(record["error"])
        self.assertGreaterEqual(record["elapsed_seconds"], 0)

    def test_timeout_stops_process_and_saves_error(self):
        self.commands.timeout = 0.3
        started = time.monotonic()
        with self.assertRaises(EvaluationError):
            self.run_python("import os, pathlib, time; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(60)")
        self.assertLess(time.monotonic() - started, 5)
        record = json.loads((self.root / "logs/0001.json").read_text())
        self.assertTrue(record["error"])
        pid = int((self.root / "pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


def samples_for(application_ratio=2, index_ratio=2):
    return [
        {"book": book, "metric": metric, "block": block, "variant": variant,
         "seconds": (block + 1) * (ratio if variant == "original" else 1)}
        for book in ("small", "large")
        for metric, ratio in (("application", application_ratio), ("index", index_ratio))
        for block in range(3)
        for variant in ("original", "candidate")
    ]


class StatisticsTests(unittest.TestCase):
    def test_clear_improvement_and_regression(self):
        for ratio, verdict in ((2, "improved"), (0.5, "slower")):
            with self.subTest(ratio=ratio):
                result = paired_summary([(ratio * x, x) for x in (1, 2, 3)], 200)
                self.assertEqual(result["verdict"], verdict)
                self.assertAlmostEqual(result["speedup"], ratio)
                for bound in result["confidence_interval_95"]:
                    self.assertAlmostEqual(bound, ratio)

    def test_noisy_and_identical_timings_are_inconclusive(self):
        for pairs in ([(1, 2), (1, 1), (2, 1)], [(1, 1)] * 3):
            result = paired_summary(pairs, 1000)
            self.assertEqual(result["verdict"], "inconclusive")
            lo, hi = result["confidence_interval_95"]
            self.assertLessEqual(lo, 1)
            self.assertGreaterEqual(hi, 1)

    def test_invalid_and_insufficient_durations_are_rejected(self):
        for pairs in ([(1, 1)] * 2, [(1, 1), (1, 1), (0, 1)],
                      [(1, 1), (1, 1), (math.nan, 1)],
                      [(1, 1), (1, 1), (1, math.inf)],
                      [(1, 1), (1, 1), (1, -1)]):
            with self.subTest(pairs=pairs), self.assertRaises(EvaluationError):
                paired_summary(pairs, 200)

    def test_missing_and_duplicate_samples_are_rejected(self):
        samples = samples_for()
        with self.assertRaisesRegex(EvaluationError, "Missing timing"):
            analyse(samples[:-1], ["small", "large"], 3, 200, 1)
        with self.assertRaisesRegex(EvaluationError, "Duplicate timing"):
            analyse(samples + [samples[0]], ["small", "large"], 3, 200, 1)

    def test_both_metrics_must_improve(self):
        result = analyse(samples_for(), ["small", "large"], 3, 200, 1)
        self.assertEqual(result["verdict"], "improved")
        result = analyse(samples_for(index_ratio=0.5), ["small", "large"], 3, 200, 1)
        self.assertEqual(result["aggregate"]["application"]["verdict"], "improved")
        self.assertEqual(result["aggregate"]["index"]["verdict"], "slower")
        self.assertEqual(result["verdict"], "slower")

    def test_equal_book_weight_keeps_individual_regression_visible(self):
        samples = samples_for()
        for sample in samples:
            if sample["book"] == "large":
                sample["seconds"] *= 1000 * (0.25 if sample["variant"] == "original" else 1)
        result = analyse(samples, ["small", "large"], 3, 200, 1)
        self.assertAlmostEqual(result["aggregate"]["application"]["speedup"], 1)
        self.assertEqual(result["books"]["small"]["application"]["verdict"], "improved")
        self.assertEqual(result["books"]["large"]["application"]["verdict"], "slower")


if __name__ == "__main__":
    unittest.main()
