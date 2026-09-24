from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as evaluator
from core import CorrectnessError, EvaluationError, sha256


class EvaluatorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_checker_exercises_actual_changed_missing_and_extra_outputs(self):
        root = self.root / "checker"
        result = evaluator.validate_checker(root)
        self.assertTrue(all(result.values()))
        self.assertEqual(json.loads((root / "identical.json").read_text()),
                         {"changed": [], "missing": [], "extra": []})
        for mutation, filename in (("changed", "searchindex.js"),
                                   ("missing", "searchindex.js"),
                                   ("extra", "unexpected.html")):
            self.assertEqual(json.loads((root / f"{mutation}.json").read_text())[mutation], [filename])
        self.assertFalse((root / "output").exists())

    def test_replay_rejects_corrupt_output_even_with_plausible_metrics(self):
        output = self.root / "index"
        stdout = self.root / "stdout"

        def command(argv, **kwargs):
            output.write_bytes(b"wrong")
            stdout.write_text(json.dumps({"elapsed_seconds": 0.01, "output_bytes": 5}))
            return {"stdout": str(stdout)}

        with self.assertRaises(CorrectnessError):
            evaluator.index_replay(self.root / "replay", self.root / "trace", output,
                                   b"right", command, {})

    def test_replay_rejects_invalid_time_and_incorrect_size(self):
        output, stdout = self.root / "index", self.root / "stdout"
        for seconds, size in ((True, 5), (0, 5), (-1, 5), (float("nan"), 5), (float("inf"), 5), (0.01, 6)):
            def command(argv, **kwargs):
                output.write_bytes(b"right")
                stdout.write_text(json.dumps({"elapsed_seconds": seconds, "output_bytes": size}))
                return {"stdout": str(stdout)}

            with self.subTest(seconds=seconds, size=size), self.assertRaises(EvaluationError):
                evaluator.index_replay(self.root / "replay", self.root / "trace", output,
                                       b"right", command, {})

    def execute_with_stub_toolchain(self, failure=None, *, index_bias=False):
        """Exercise real orchestration and file checking without compiling upstream."""
        metadata = self.root / "metadata"
        metadata.mkdir()
        (metadata / "fixtures").mkdir()
        (metadata / "books.json").write_text(json.dumps([{"id": "mini"}]))
        evidence = self.root / "run"
        evidence.mkdir()
        variants = {}
        for name in ("original", "candidate", "capture"):
            base = evidence / "variants" / name
            application, library = base / "application", base / "library"
            application.mkdir(parents=True)
            library.mkdir()
            (application / "Cargo.lock").write_text('version = 4\n\n[[package]]\nname = "stub"\nversion = "0.1.0"\n')
            binary = application / "mdbook"
            binary.write_bytes(name.encode())
            variants[name] = {
                "application": application, "library": library, "binary": binary,
                "provenance": {"binary_sha256": sha256(binary)},
            }

        def prepare_replay(destination, library, lock):
            (destination / "target/release").mkdir(parents=True)
            (destination / "target/release/index-replay").write_bytes(b"stub")
            (destination / "Cargo.lock").write_bytes(lock.read_bytes())

        def prepare_book(entry, source, destination, env, commands):
            destination.mkdir(parents=True)
            (destination / "book.toml").write_text('[book]\ntitle = "Minimal"\n')
            (destination / "chapter.md").write_text("# Minimal\nHello\n")
            return destination, env

        calls = []

        def commands(argv, *, cwd, env):
            argv = list(argv)
            calls.append(list(map(str, argv)))
            stdout = evidence / f"stdout-{len(calls)}"
            stdout.write_text("")
            executable = Path(argv[0])
            if executable.name == "mdbook":
                output = Path(argv[-1])
                output.mkdir()
                (output / "index.html").write_bytes(b"book")
                (output / "searchindex.js").write_bytes(b"right index")
                if "JIT_LIB_INDEX_TRACE" in env:
                    if failure == "capture":
                        (output / "index.html").write_bytes(b"capture changed output")
                    Path(env["JIT_LIB_INDEX_TRACE"]).write_text(json.dumps({
                        "expected_output": "right index", "copy_js": True,
                    }))
            elif executable.name == "index-replay":
                content = b"wrong index" if failure == "replay" and "candidate" in executable.parts else b"right index"
                Path(argv[2]).write_bytes(content)
                seconds = 0.02 if index_bias and "original" in executable.parts else 0.01
                stdout.write_text(json.dumps({"elapsed_seconds": seconds, "output_bytes": len(content)}))
            return {"stdout": str(stdout), "elapsed_seconds": 0.01}

        report = {"configuration": {"warmups": 0, "repetitions": 3,
                                    "bootstrap_resamples": 100, "bootstrap_seed": 1}}
        args = SimpleNamespace(cache=self.root / "cache", candidate=None, books=None, mode="self-check")
        with ExitStack() as stack:
            for name, replacement in (("HERE", metadata), ("setup_gui", lambda *args: self.root),
                                      ("prepare_variants", lambda *args: variants),
                                      ("run_suites", lambda *args: {}),
                                      ("prepare_replay", prepare_replay), ("prepare_book", prepare_book)):
                stack.enter_context(patch.object(evaluator, name, replacement))
            with self.assertRaises(CorrectnessError) if failure else nullcontext():
                evaluator.execute(args, evidence, report, commands, {})
        if failure:
            self.assertFalse((evidence / "timings.json").exists())
            self.assertFalse((evidence / "timing-work").exists())
            self.assertNotIn("analysis", report)
        return calls, report

    def test_capture_mismatch_stops_before_replay_or_performance(self):
        calls, _ = self.execute_with_stub_toolchain("capture")
        self.assertFalse(any(Path(call[0]).name == "index-replay" for call in calls))

    def test_candidate_replay_mismatch_stops_before_performance(self):
        calls, _ = self.execute_with_stub_toolchain("replay")
        self.assertEqual(sum(Path(call[0]).name == "index-replay" for call in calls), 2)

    def test_self_check_warns_when_only_index_timing_shows_bias(self):
        _, report = self.execute_with_stub_toolchain(index_bias=True)
        self.assertEqual(report["analysis"]["aggregate"]["application"]["verdict"], "inconclusive")
        self.assertEqual(report["analysis"]["aggregate"]["index"]["verdict"], "improved")
        self.assertEqual(report["analysis"]["verdict"], "inconclusive")
        self.assertEqual(report["status"], "calibration-warning")

    def test_self_check_accepts_when_both_timing_metrics_agree(self):
        _, report = self.execute_with_stub_toolchain()
        self.assertEqual(report["status"], "validated")


if __name__ == "__main__":
    unittest.main()
