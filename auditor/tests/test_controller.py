import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auditor.agent import validate_response
from auditor.run import REPO, audit, auditor_provenance, candidate_checkout, main, promote
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

    def test_promotion_uses_portable_identity_and_keeps_existing_metadata(self):
        result = {"status": "reproduced", "reason": "Mismatch"}
        identity = {"evaluation": str(REPO / ".evaluator/runs/example"), "evaluation_report_sha256": "report-hash"}
        target = Path(promote(proposal(), finding(), result, self.fixtures, identity))
        metadata = json.loads((target / "audit.json").read_text())
        self.assertEqual(metadata["identity"]["evaluation"], {"kind": "repository-relative", "path": ".evaluator/runs/example"})
        before = (target / "audit.json").read_bytes()
        promote(proposal(), finding(), result, self.fixtures, {"evaluation": "/external/new-evaluation"})
        self.assertEqual((target / "audit.json").read_bytes(), before)
        other = dict(proposal(), id="external")
        other["files"] = [dict(item) for item in other["files"]]
        other["files"][-1]["content"] += "\nExtra words."
        details = dict(finding(), probe_ids=["external"])
        target = Path(promote(other, details, result, self.fixtures,
                              {"evaluation": "/external/machine/results/run-123", "evaluation_report_sha256": "digest"}))
        reference = json.loads((target / "audit.json").read_text())["identity"]["evaluation"]
        self.assertEqual(reference, {"kind": "external-artifact", "name": "run-123", "report_sha256": "digest"})

    def test_provenance_records_effective_options_and_frozen_contract(self):
        options = SimpleNamespace(model="model-override", reasoning_effort="medium", max_rounds=7, agent_timeout=4, probe_timeout=2)
        record = auditor_provenance(self.root, options)
        self.assertEqual(record["model"], "model-override")
        self.assertEqual(record["max_rounds"], 7)
        self.assertEqual(record["agent_timeout_seconds"], 4)
        for name in ("prompt.md", "response.schema.json", "config.json", "probes.py", "agent.py", "run.py"):
            self.assertIn(name, record["source_files_sha256"])
            self.assertEqual((self.root / "auditor-source" / name).read_bytes(), (REPO / "auditor" / name).read_bytes())
        self.assertEqual(record["sandbox"]["probe_policy_source_sha256"], record["source_files_sha256"]["probes.py"])

    def test_source_contract_drift_cannot_produce_clean_report(self):
        options = SimpleNamespace(model="model-override", reasoning_effort="medium", max_rounds=1, agent_timeout=4, probe_timeout=2)
        record = auditor_provenance(self.root, options)
        record["source_files_sha256"]["prompt.md"] = "different-recorded-prompt"
        result, _, _ = self.run_audit([response()], provenance=record)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("source or contract changed", result["error"])
        self.assertEqual(result["auditor"]["model"], "model-override")

    def test_unsupported_platform_fails_before_auth_and_keeps_provenance(self):
        output = self.root / "failed-audit"
        argv = ["auditor/run.py", "--evaluation", "/unused", "--output", str(output), "--model", "test-model", "--max-rounds", "2"]
        with patch("sys.argv", argv), patch("auditor.run.sys.platform", "linux"), patch("auditor.run.check_login") as login:
            self.assertEqual(main(), 3)
        login.assert_not_called()
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["auditor"]["model"], "test-model")
        self.assertEqual(report["auditor"]["max_rounds"], 2)
        self.assertIn("requires macOS", report["error"])

    def test_auth_failure_retains_cli_version_and_provenance(self):
        output = self.root / "auth-failure"
        argv = ["auditor/run.py", "--evaluation", "/unused", "--output", str(output)]
        with patch("sys.argv", argv), patch("auditor.run.check_platform"), \
                patch("auditor.run.shutil.which", return_value="/test/codex"), \
                patch("auditor.run.subprocess.run", return_value=SimpleNamespace(stdout="codex test-version\n")), \
                patch("auditor.run.check_login", side_effect=RuntimeError("authentication required")):
            self.assertEqual(main(), 3)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["auditor"]["coding_agent"], {"name": "codex", "executable": "/test/codex", "version": "codex test-version"})
        self.assertIn("authentication required", report["error"])

    def test_sample_report_retains_new_and_historical_agent_versions(self):
        from scripts.sample_reports import audit_excerpt
        path = self.root / "report.json"
        write_json(path, {"status": "incomplete", "auditor": {"coding_agent": {
            "name": "claude", "version": "test-version", "executable": "/local/machine/claude"}}})
        self.assertEqual(audit_excerpt(path)["auditor"]["coding_agent"], {"name": "claude", "version": "test-version"})
        write_json(path, {"status": "incomplete", "auditor": {"codex": {"version": "historical"}}})
        self.assertEqual(audit_excerpt(path)["auditor"]["codex_version"], "historical")

    def test_response_contract_rejects_missing_fields_or_unknown_status(self):
        for value in ({"action": "finish"}, response(findings=[dict(finding(), status="safe")])):
            with self.assertRaises(ValueError):
                validate_response(value)
        self.assertEqual(validate_response(response()), response())


if __name__ == "__main__":
    unittest.main()
