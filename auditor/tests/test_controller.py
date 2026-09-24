import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from auditor.agent import validate_response
from auditor.run import audit, candidate_checkout, promote
from evaluator.core import inventory, write_json


def proposal():
    return {"id": "new-text", "hypothesis": "Candidate skips unseen content",
            "requirement": "Index every supported chapter", "code_references": ["src/lib.rs:12"],
            "files": [{"path": "book.toml", "content": '[book]\ntitle="Book"\n'},
                      {"path": "src/SUMMARY.md", "content": "- [Chapter](chapter.md)\n"},
                      {"path": "src/chapter.md", "content": "# Chapter\nNew content."}]}


def finding(status="confirmed"):
    return {"id": "skipped-content", "status": status, "claim": "Candidate skips chapter text",
            "requirement": "Index every supported chapter", "code_references": ["src/lib.rs:12"],
            "probe_ids": ["new-text"], "check_proposal": "Keep the changed-content book"}


def response(action="finish", findings=None, probes=None):
    return {"action": action, "summary": "Investigated changed content",
            "findings": findings or [], "probes": probes or []}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        package = self.root / "input"
        package.mkdir()
        (package / "source.rs").write_text("frozen source")
        self.package = {"root": package, "binaryPaths": {},
                        "identity": {"evaluation_status": "inconclusive"}, "limitations": []}
        self.fixtures = self.root / "fixtures"

    def run_audit(self, answers, outcome="reproduced", **kwargs):
        agent = Mock(side_effect=answers)
        probe = Mock(return_value={"id": "new-text", "status": outcome, "reason": "Controlled test result"})
        result = audit(self.package, self.root, self.fixtures, agent=agent,
                       probe_runner=probe, **kwargs)
        return result, agent, probe

    def test_reproduction_is_promoted_and_requires_full_reevaluation(self):
        result, agent, probe = self.run_audit([
            response("probe", [finding("suspected")], [proposal()]),
            response(findings=[finding()])])
        self.assertEqual(result["status"], "confirmed-violation")
        self.assertEqual(result["reevaluation"], "required")
        fixture = Path(result["promoted_checks"][0])
        self.assertEqual((fixture / "src/chapter.md").read_text(), proposal()["files"][2]["content"])
        self.assertEqual(json.loads((fixture / "audit.json").read_text())["identity"], self.package["identity"])
        self.assertEqual(agent.call_count, 2)
        self.assertEqual(probe.call_count, 1)

    def test_agent_confirmation_without_reproduction_is_unresolved(self):
        result, _, _ = self.run_audit([response(findings=[finding()])])
        self.assertEqual(result["status"], "unresolved")
        self.assertFalse(self.fixtures.exists())

    def test_matching_candidate_does_not_validate_agent_accusation(self):
        result, _, _ = self.run_audit([response("probe", probes=[proposal()]),
                                      response(findings=[finding()])], outcome="not_reproduced")
        self.assertEqual(result["status"], "unresolved")
        self.assertFalse(result["promoted_checks"])

    def test_failed_or_omitted_probes_cannot_become_clean(self):
        for outcome in ("reproduced", "inconclusive", "invalid"):
            with self.subTest(outcome=outcome):
                result, _, _ = self.run_audit([response("probe", probes=[proposal()]), response()], outcome)
                self.assertEqual(result["status"], "unresolved")

    def test_suspicion_cannot_be_silently_dropped(self):
        result, _, _ = self.run_audit([response("probe", [finding("suspected")]), response()])
        self.assertEqual(result["status"], "unresolved")

    def test_original_control_with_no_suspicions_is_scoped_no_issue(self):
        result, _, _ = self.run_audit([response()])
        self.assertEqual(result["status"], "no-issue-found")

    def test_invented_probe_reference_cannot_support_clean_verdict(self):
        result, _, _ = self.run_audit([response(findings=[finding("dismissed")])])
        self.assertEqual(result["status"], "unresolved")

    def test_reevaluation_retains_manifested_files_despite_ignore_rules(self):
        library = self.package["root"] / "variants/candidate/library"
        library.mkdir(parents=True)
        (library / ".gitignore").write_text("lib.rs\n")
        (library / "lib.rs").write_text("submitted source")
        write_json(library.parent / "library-inputs.json", inventory(library))
        candidate = candidate_checkout(self.package, self.root)
        self.assertEqual((candidate / "lib.rs").read_text(), "submitted source")

    def test_incomplete_evaluation_cannot_be_clean(self):
        self.package["identity"]["evaluation_status"] = "incomplete"
        result, _, _ = self.run_audit([response()])
        self.assertEqual(result["status"], "unresolved")

    def test_agent_failure_and_budget_exhaustion_are_incomplete(self):
        for answers in ([RuntimeError("agent failed")], [response("probe")]):
            result, _, _ = self.run_audit(answers, max_rounds=1)
            self.assertEqual(result["status"], "incomplete")

    def test_tampering_prevents_clean_verdict(self):
        def tamper(*args, **kwargs):
            (self.package["root"] / "source.rs").write_text("changed")
            return response()
        result = audit(self.package, self.root, self.fixtures, agent=tamper)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("evidence changed", result["error"])

    def test_reused_probe_ids_and_finish_with_probes_fail(self):
        for answers in ([response(probes=[proposal()])],
                        [response("probe", probes=[proposal()])] * 2):
            result, _, _ = self.run_audit(answers)
            self.assertEqual(result["status"], "incomplete")

    def test_promotion_cannot_overwrite_existing_fixture(self):
        result = {"status": "reproduced", "reason": "Mismatch"}
        target = Path(promote(proposal(), finding(), result, self.fixtures, {}))
        (target / "src/chapter.md").write_text("user edit")
        with self.assertRaises(ValueError):
            promote(proposal(), finding(), result, self.fixtures, {})
        self.assertEqual((target / "src/chapter.md").read_text(), "user edit")

    def test_response_contract_rejects_missing_fields_or_unknown_status(self):
        for value in ({"action": "finish"}, response(findings=[dict(finding(), status="safe")])):
            with self.assertRaises(ValueError):
                validate_response(value)
        self.assertEqual(validate_response(response()), response())


if __name__ == "__main__":
    unittest.main()
