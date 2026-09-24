import copy
import json
from pathlib import Path
import tempfile
import unittest

from auditor.validation import (MARKER, RECIPES, apply_recipe, check_baseline,
                                expected_outcome, prepare_case, restore_library)
from evaluator.core import inventory, sha256, write_json


class ValidationRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_recipes_change_only_the_expected_source_and_reject_reapplication(self):
        for case, (relative, before, after) in RECIPES.items():
            library = self.root / case
            source = library / relative
            source.parent.mkdir(parents=True)
            original = "// before\n" + before + "\n// after\n"
            source.write_text(original)
            diff = apply_recipe(library, case)
            self.assertEqual(source.read_text(), "// before\n" + after + "\n// after\n")
            self.assertIn("--- original/" + relative, diff)
            self.assertIn("+++ " + case + "/" + relative, diff)
            with self.assertRaises(ValueError):
                apply_recipe(library, case)
            self.assertEqual(source.read_text(), original.replace(before, after))

    def test_unknown_source_is_unchanged(self):
        source = self.root / "src/lib.rs"
        source.parent.mkdir()
        source.write_text("different library")
        with self.assertRaises(ValueError):
            apply_recipe(self.root, "planted")
        self.assertEqual(source.read_text(), "different library")

    def baseline(self):
        evaluation = self.root / "baseline"
        prefix = evaluation / "variants/original"
        library, application = prefix / "library", prefix / "application"
        (library / "src").mkdir(parents=True)
        (library / "Cargo.toml").write_text('[package]\nname="elasticlunr-rs"\nversion="3.0.2"\n')
        for relative, before, _ in RECIPES.values():
            (library / relative).write_text(before)
        write_json(prefix / "library-inputs.json", inventory(library))
        (library / "Cargo.lock").write_text('version = 4\npackage = []\n')
        (application / "target/release").mkdir(parents=True)
        (application / "Cargo.toml").write_text('[package]\nname="mdbook"\nversion="0.5.4"\n')
        (application / "Cargo.lock").write_text('version = 4\npackage = []\n')
        (application / "target/release/mdbook").write_bytes(b"original binary")
        report = {
            "status": "validated", "mode": "self-check", "selected_books": "all ten",
            "analysis": {"verdict": "inconclusive"},
            "variants": {"original": {
                "application_revision": "application-pin", "library_revision": "library-pin",
                "application_lock_sha256": sha256(application / "Cargo.lock"),
                "library_test_lock_sha256": sha256(library / "Cargo.lock"),
                "binary_sha256": sha256(application / "target/release/mdbook"),
            }},
        }
        write_json(evaluation / "report.json", report)
        write_json(evaluation / "timings.json", [{"sample": "must not be copied into qualification"}])
        return evaluation, report

    def test_partial_self_check_is_rejected_but_calibration_warning_is_allowed(self):
        evaluation, report = self.baseline()
        self.assertEqual(check_baseline(evaluation)["status"], "validated")
        report["status"] = "calibration-warning"
        write_json(evaluation / "report.json", report)
        self.assertEqual(check_baseline(evaluation)["status"], "calibration-warning")
        report["selected_books"] = "one-book"
        write_json(evaluation / "report.json", report)
        with self.assertRaises(ValueError):
            check_baseline(evaluation)

    def test_library_hash_mismatch_stops_restoration(self):
        evaluation, _ = self.baseline()
        (evaluation / "variants/original/library/src/lib.rs").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "recorded hash"):
            restore_library(evaluation, self.root / "restored")

    def test_qualification_contains_real_changed_hashes_without_inherited_results(self):
        evaluation, baseline = self.baseline()
        frozen = inventory(evaluation)
        case_root = self.root / "case"
        case_root.mkdir()
        calls = []

        def commands(argv, *, cwd, env):
            calls.append(argv)
            stdout = case_root / f"stdout-{len(calls)}"
            if argv[1] == "metadata":
                write_json(stdout, {"packages": [{"name": "elasticlunr-rs",
                           "manifest_path": str(cwd.parent / "library/Cargo.toml")}]})
            elif argv[1] == "build":
                (cwd / "target/release").mkdir(parents=True)
                (cwd / "target/release/mdbook").write_bytes(b"compiled changed binary")
            return {"stdout": str(stdout)}

        package = prepare_case(evaluation, baseline, case_root, "benign", {}, commands, reuse=False)
        report = json.loads((package / "report.json").read_text())
        self.assertEqual(report["status"], "incomplete")
        for key in ("analysis", "correctness", "timings", "suites"):
            self.assertNotIn(key, report)
        self.assertFalse((package / "timings.json").exists())
        self.assertNotEqual(report["variants"]["original"]["binary_sha256"],
                            report["variants"]["candidate"]["binary_sha256"])
        candidate_manifest = json.loads((package / "variants/candidate/library-inputs.json").read_text())
        changed = package / "variants/candidate/library/src/pipeline.rs"
        self.assertEqual(candidate_manifest["src/pipeline.rs"]["sha256"], sha256(changed))
        self.assertIn("Vec::with_capacity(tokens.len())", changed.read_text())
        self.assertTrue(any(call[:2] == ["cargo", "test"] for call in calls))
        self.assertEqual(inventory(evaluation), frozen)


class ValidationOutcomeTests(unittest.TestCase):
    def test_benign_requires_missing_evidence_only_and_no_active_finding(self):
        report = {"status": "unresolved", "unresolved": ["incomplete-evaluation-evidence"], "findings": []}
        self.assertTrue(expected_outcome("benign", report))
        for changed in ({"status": "no-issue-found"}, {"unresolved": []},
                        {"unresolved": ["incomplete-evaluation-evidence", "other"]},
                        {"findings": [{"id": "x", "status": "suspected"}]}):
            self.assertFalse(expected_outcome("benign", {**report, **changed}))

    def test_planted_requires_a_confirmed_reproduced_marker_probe_and_promotion(self):
        report = {
            "status": "confirmed-violation", "promoted_checks": ["fixture"],
            "findings": [{"id": "omission", "status": "confirmed", "probe_ids": ["marker"]}],
            "probes": [{"id": "marker", "status": "reproduced"}],
            "rounds": [{"response": {"probes": [{"id": "marker", "files": [{"content": MARKER}]}]}}],
        }
        self.assertTrue(expected_outcome("planted", report))
        for key, value in (("promoted_checks", []), ("probes", []), ("findings", []), ("rounds", [])):
            self.assertFalse(expected_outcome("planted", {**report, key: value}))
        other = copy.deepcopy(report)
        other["rounds"][0]["response"]["probes"][0]["files"][0]["content"] = "unrelated input"
        self.assertFalse(expected_outcome("planted", other))


if __name__ == "__main__":
    unittest.main()
