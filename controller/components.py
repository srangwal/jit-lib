"""Explicit command adapters, evidence identities, and optimizer task briefs."""

import hashlib
import json
from pathlib import Path
import shutil
import sys

from coding_agents.config import resolve
from evaluator.core import evaluator_fingerprint, inventory, sha256
from optimizer.context import prepare_context
from controller.feedback import evaluation_feedback
from controller.history import write_bundle
from controller.process import run_process
from controller.records import load, now

REPO = Path(__file__).resolve().parents[1]
EXIT_CODES = {
    "optimizer": {"candidate-created": 0, "no-change": 0, "incomplete": 1},
    "evaluator": {"improved": 0, "slower": 0, "inconclusive": 0, "validated": 0,
                  "correctness-failed": 1, "incomplete": 1, "calibration-warning": 1},
    "auditor": {"no-issue-found": 0, "confirmed-violation": 1, "unresolved": 2, "incomplete": 3},
}


class Components:
    def __init__(self, records, args, runner=run_process):
        self.records, self.args, self.runner = records, args, runner
        self.root = records.root
        self.configuration = None
        self.books = load(REPO / "evaluator/books.json")
        self.code = {name: evaluator_fingerprint(REPO / name) for name in ("controller", "optimizer", "auditor", "coding_agents")}
        self.reference_library = None
        self.reference_books = None
        self.profile_snapshot = args.profile
        self.attempts = []
        self.candidates = {}

    def agent_arguments(self, role):
        selected = getattr(self.args, role + "_runtime", None)
        if selected is None:
            selected = resolve(load(REPO / role / "config.json"), model=self.args.model)
        arguments = ["--agent", selected["agent"], "--model", selected["model"]]
        if selected["local_base_url"]:
            arguments += ["--local-base-url", selected["local_base_url"]]
        return arguments

    def version(self):
        return evaluator_fingerprint()

    def unchanged_code(self):
        for name, fingerprint in self.code.items():
            if evaluator_fingerprint(REPO / name) != fingerprint:
                raise ValueError(f"{name} source changed during experiment")
        self.records.verify()

    def step(self, component, step_id, request, arguments, timeout):
        self.unchanged_code()
        directory = self.root / "steps" / step_id
        directory.mkdir(parents=True, exist_ok=False)
        output = directory / "output"
        request = {**request, "schema_version": f"{component}-request/v1",
                   "experiment_id": self.root.name, "request_id": step_id}
        request_ref = self.records.write(directory.relative_to(self.root) / "request.json", request)
        argv = [sys.executable, str(REPO / component / "run.py"), *map(str, arguments), "--output", str(output)]
        command_ref = self.records.write(directory.relative_to(self.root) / "command.json",
                                         {"argv": argv, "cwd": str(REPO), "timeout_seconds": timeout})
        self.records.event("component_started", step_id=step_id, attempt_id=request.get("attempt_id"),
                           component=component, request=request_ref, evidence=command_ref,
                           summary=f"{component} started; live log: steps/{step_id}/stdout.log")
        self.records.render("running")
        protocol_error = None
        raw_ref = None
        report = {"status": "incomplete"}
        started = now()
        process = {"execution_status": "failed", "exit_code": None}
        try:
            process = self.runner(argv, directory, timeout, REPO)
            if (output / "report.json").exists():
                raw_ref = self.records.ref(output / "report.json")
                report = load(output / "report.json")
                if (not isinstance(report, dict) or not isinstance(report.get("status"), str)
                        or report["status"] not in EXIT_CODES[component]):
                    raise ValueError(f"Invalid {component} report status")
            elif process["execution_status"] == "completed":
                raise ValueError(f"{component} did not produce report.json")
            if process["execution_status"] != "completed":
                report = {"status": "incomplete", "error": process["execution_status"]}
            elif process["exit_code"] != EXIT_CODES[component][report["status"]]:
                raise ValueError(f"{component} exit code contradicts its report")
        except KeyboardInterrupt:
            process = {"execution_status": "cancelled", "exit_code": None}
            protocol_error = "Interrupted by user"
            report = {"status": "incomplete", "error": protocol_error}
        except (OSError, ValueError, RuntimeError) as error:
            protocol_error = str(error)
            report = {"status": "incomplete", "error": protocol_error}
        self.unchanged_code()
        result = {"schema_version": f"{component}-result/v1", "experiment_id": self.root.name,
                  "request_id": step_id, "attempt_id": request.get("attempt_id"),
                  "request": request_ref, "started_utc": started, "finished_utc": now(),
                  "process": process, "status": report["status"], "report": raw_ref,
                  "protocol_error": protocol_error, "error": report.get("error")}
        for name in ("stdout", "stderr"):
            path = directory / f"{name}.log"
            if path.is_file():
                result[name] = self.records.ref(path)
        if (output / "progress.jsonl").is_file():
            result["progress"] = self.records.ref(output / "progress.jsonl")
        result_ref = self.records.write(directory.relative_to(self.root) / "result.json", result)
        error_detail = protocol_error or report.get("error")
        self.records.event("component_finished", component=component, step_id=step_id,
                           attempt_id=request.get("attempt_id"), result=result_ref,
                           summary=f"{component}: {report['status']}" + (f" — {error_detail}" if error_detail else ""))
        self.records.render("running")
        if process["execution_status"] == "cancelled":
            raise KeyboardInterrupt
        return {"status": report["status"], "report": report, "directory": output,
                "result_ref": result_ref, "raw_ref": raw_ref}

    def baseline_context(self, source, name):
        report = load(source / "report.json")
        if report.get("mode") != "self-check" or report.get("status") != "validated":
            raise ValueError("Controller requires a completed, validated evaluator self-check")
        if load(source / "books.json") != self.books:
            raise ValueError("Controller v1 requires the full pinned ten-book workload, not a subset")
        context = self.root / name
        identity = prepare_context(source, context, profile=self.profile_snapshot)
        if (context / "profile.txt").exists():
            self.profile_snapshot = context / "profile.txt"
        evaluation_feedback(report)
        original = load(context / "evaluation/original-library-inputs.json")
        inputs = load(context / "evaluation/book-inputs.json")
        selected = {book["id"]: inputs[book["id"]] for book in self.books}
        if self.reference_library is not None and (original != self.reference_library or selected != self.reference_books):
            raise ValueError("Refreshed baseline changed original library or selected book inputs")
        self.reference_library, self.reference_books = original, selected
        return {"path": source, "context": context, "report": report,
                "report_ref": self.records.ref(context / "evaluation/report.json"),
                "identity_ref": self.records.ref(context / "identity.json"), "identity": identity}

    def initialize(self):
        baseline = self.baseline_context(self.args.baseline, "inputs")
        recorded = baseline["report"]["configuration"]
        expected = load(REPO / "evaluator/config.json")
        for key in ("repetitions", "warmups"):
            expected[key] = recorded[key]
        # Acceptance targets may change, but measurement inputs may not.
        old_measurement = {k: v for k, v in recorded.items() if k != "library_reduction_target_percent"}
        new_measurement = {k: v for k, v in expected.items() if k != "library_reduction_target_percent"}
        if old_measurement != new_measurement:
            raise ValueError("Baseline configuration is incompatible with the current evaluator")
        expected["library_reduction_target_percent"] = self.args.library_reduction_target_percent
        self.configuration = expected
        if baseline["report"]["evaluator_version"] != self.version() or recorded != expected:
            self.records.event("baseline_stale", summary="Evaluator or acceptance target changed; running a fresh self-check.",
                               evidence=baseline["report_ref"])
            baseline = self.refresh_baseline("initial")
        self.records.event("baseline_ready", summary="Validated full-workload reference prepared.",
                           evidence=baseline["identity_ref"])
        return baseline

    def evaluation_args(self):
        args = ["--cache", str(self.args.cache), "--books", ",".join(book["id"] for book in self.books),
                "--repetitions", str(self.configuration["repetitions"]),
                "--warmups", str(self.configuration["warmups"]),
                "--library-reduction-target-percent", str(self.configuration["library_reduction_target_percent"])]
        for field in ("browser", "cargo_home"):
            value = getattr(self.args, field)
            if value:
                args += ["--" + field.replace("_", "-"), str(value)]
        return args

    def refresh_baseline(self, label):
        expected_version = self.version()
        result = self.step("evaluator", label + "-self-check", {"mode": "self-check", "evaluator_version": expected_version},
                           ["self-check", *self.evaluation_args()], self.args.evaluation_timeout)
        if result["status"] != "validated" or result["report"].get("evaluator_version") != expected_version:
            raise RuntimeError("Fresh self-check did not validate; do not rerun merely to obtain favorable timings")
        baseline = self.baseline_context(result["directory"], label + "-inputs")
        if baseline["report"]["configuration"] != self.configuration or self.version() != expected_version:
            raise ValueError("Self-check configuration or evaluator changed")
        return baseline

    def optimize(self, attempt, baseline, previous, feedback, stretch_target):
        self.unchanged_code()
        if previous:
            self.check_candidate(previous)
        context = baseline["context"]
        for candidate in self.candidates.values():
            self.check_candidate(candidate)
        history, history_ref, history_files = write_bundle(
            self.records, attempt, self.attempts, self.candidates, self.version())
        feedback_ref = self.records.write(f"tasks/{attempt}-feedback.json", {
            "schema_version": "optimizer-feedback/v1", "evidence": [
                {"reference": ref, "contents": load(self.root / ref["path"])} for ref in feedback]})
        task = {
            "schema_version": "optimizer-task/v1", "experiment_id": self.root.name,
            "attempt_id": attempt, "request_id": attempt + "-optimize",
            "task": {"objective": "Maximize the reduction in elasticlunr-rs library-work time (index construction, serialization, and cleanup) for this application and supplied workload within the attempt budget. The configured target is a minimum acceptance requirement, not a ceiling; pursue worthwhile gains beyond it while preserving supported behavior. Report mdBook build time separately.",
                     "focus": "Specialize for this application and the complete supplied workload. Investigate substantial opportunities using all earlier candidates and evidence; preserve new supported inputs and configurations.",
                     "success_rule": "Correctness passes; the lower 95% bound for aggregate library time reduction meets the target and exceeds noise; audit finds no unresolved issue. Application timing does not block success.",
                     "library_reduction_target_percent": self.configuration["library_reduction_target_percent"],
                     "optimizer_stretch_target": stretch_target},
            "inputs": {"baseline_ref": baseline["identity_ref"], "history_ref": history_ref,
                       "previous_candidate_ref": previous["manifest_ref"] if previous else None,
                       "profile_ref": self.records.ref(context / "profile.txt") if (context / "profile.txt").exists() else None,
                       "prior_feedback_refs": [feedback_ref]},
            "workload": {"manifest_ref": self.records.ref(context / "evaluation/books.json"),
                         "selected_book_ids": [book["id"] for book in self.books],
                         "prepared_inputs_ref": self.records.ref(context / "evaluation/book-inputs.json"),
                         "execution_recipe": "Build each pinned book with its prepared configuration and search; replay its captured indexing operations.",
                         "measurement_protocol": self.configuration,
                         "aggregation": "equal-weight geometric mean across books"},
            "context_paths": {"application": "application/", "original_library": "original/",
                              "objective": "objective.json",
                              "history": "history/ledger.json", "history_summary": "history/summary.md",
                              "books": "books/", "workload_manifest": "evaluation/books.json",
                              "measurements": "evaluation/report.json", "feedback": "feedback.txt",
                              "note": "Paths here are relative to the optimizer's read-only context; artifact refs are relative to the experiment root."},
            "requirements": {"editable_source": "library/ only; application code is read-only and must not be changed or replaced.",
                             "behavior": "Preserve interface, serialization, errors and uncommon supported inputs; workload contents do not establish guarantees.",
                             "optimization_rules": "Cite application source. No benchmark identities, precomputed outputs, weakened tests, or dependency changes."},
            "execution": {"timeout_seconds": self.args.optimizer_timeout,
                          "local_builds_and_correctness_tests": True, "diagnostic_profiling_and_benchmarks": True, "official_evaluation": False,
                          "tool_network_access": False},
        }
        task_ref = self.records.write(f"tasks/{attempt}.json", task)
        arguments = ["--baseline", str(baseline["path"]), "--task", str(self.root / task_ref["path"]),
                     "--feedback", str(self.root / feedback_ref["path"]), "--history", str(history), "--timeout", str(self.args.optimizer_timeout),
                     *self.agent_arguments("optimizer")]
        if (context / "profile.txt").exists():
            arguments += ["--profile", str(context / "profile.txt")]
        if self.args.cargo_home:
            arguments += ["--cargo-home", str(self.args.cargo_home)]
        result = self.step("optimizer", attempt + "-optimize", {"attempt_id": attempt, "task": task_ref},
                           arguments, self.args.optimizer_timeout + 600)
        if result["status"] != "incomplete":
            report = result["report"]
            supplied = report.get("controller_inputs", {}).get("task", {})
            if any(supplied.get(key) != task[key] for key in ("experiment_id", "attempt_id", "request_id")) or supplied.get("sha256") != task_ref["sha256"]:
                raise ValueError("Optimizer answered a different task")
            if report.get("input_identity", {}).get("baseline_report_sha256") != baseline["report_ref"]["sha256"]:
                raise ValueError("Optimizer used a different baseline")
            copied_files = report.get("input_identity", {}).get("files", {})
            if any(copied_files.get(name) != identity for name, identity in baseline["identity"]["files"].items()):
                raise ValueError("Optimizer context differs from the frozen experiment inputs")
            original_files = inventory(context / "original")
            copied_history = dict(history_files)
            for candidate_id in self.candidates:
                copied_history[f"candidates/{candidate_id}/library/Cargo.lock"] = original_files["Cargo.lock"]
            supplied_history = report.get("controller_inputs", {}).get("history", {})
            if (supplied_history.get("ledger_sha256") != history_ref["sha256"]
                    or supplied_history.get("files") != copied_history):
                raise ValueError("Optimizer copied a different history bundle")
            objective = report.get("controller_inputs", {}).get("objective", {})
            objective_path = result["directory"] / "context/objective.json"
            if (objective.get("path") != "context/objective.json" or not objective_path.is_file()
                    or objective.get("sha256") != sha256(objective_path)
                    or objective.get("library_reduction_target_percent") != task["task"]["library_reduction_target_percent"]
                    or load(objective_path).get("library_reduction_target_percent") != task["task"]["library_reduction_target_percent"]
                    or objective.get("optimizer_stretch_target") != stretch_target
                    or load(objective_path).get("optimizer_stretch_target") != stretch_target):
                raise ValueError("Optimizer used a different optimization objective")
            self.records.ref(objective_path)
            choice = report.get("starting_point")
            checkpoints = report.get("base_checkpoints", [])
            if choice is None:
                if result["status"] != "no-change" or checkpoints:
                    raise ValueError("Optimizer omitted its starting-point choice")
            else:
                if not isinstance(checkpoints, list) or not checkpoints:
                    raise ValueError("Optimizer omitted trusted starting-point checkpoints")
                self.verify_starting_point(choice, original_files)
                for checkpoint in checkpoints:
                    path = result["directory"] / checkpoint["path"]
                    if not path.resolve().is_relative_to(result["directory"].resolve()) or sha256(path) != checkpoint["sha256"]:
                        raise ValueError("Optimizer changed a starting-point checkpoint")
                    self.verify_starting_point(load(path), original_files)
                    self.records.ref(path)
                if checkpoints and load(result["directory"] / checkpoints[-1]["path"]) != choice:
                    raise ValueError("Optimizer final base differs from its last checkpoint")
                choice_ref = self.records.ref(result["directory"] / "starting-point.json")
                if load(self.root / choice_ref["path"]) != choice:
                    raise ValueError("Optimizer changed its recorded starting-point choice")
                self.records.event("starting_point", attempt_id=attempt, evidence=choice_ref,
                                   summary=f"{choice['base_candidate_id']}: {choice['reason']}")
        result["result_ref"] = self.records.write(f"feedback/{attempt}-optimizer.json", {
            "schema_version": "optimizer-result-feedback/v1", "outcome": result["status"],
            "report": result["report"], "native_result": result["result_ref"]})
        if result["status"] == "candidate-created":
            directory = result["directory"]
            manifest_ref = self.records.ref(directory / "candidate-files.json")
            candidate = {"candidate_id": attempt, "starting_point": result["report"]["starting_point"],
                         "path": directory / "candidate", "manifest_ref": manifest_ref,
                         "manifest": load(directory / "candidate-files.json")}
            digest = hashlib.sha256(json.dumps(candidate["manifest"], sort_keys=True).encode()).hexdigest()
            if result["report"].get("candidate", {}).get("sha256") != digest:
                raise ValueError("Optimizer candidate identity disagrees with its manifest")
            self.check_candidate(candidate)
            result["candidate"] = candidate
            self.candidates[attempt] = candidate
        self.attempts.append({"attempt_id": attempt, "candidate_id": attempt if "candidate" in result else None,
                              "starting_point": result["report"].get("starting_point"),
                              "summary": result["report"].get("response", {}).get("summary", result["report"].get("summary", "")),
                              "proposal": result["report"].get("response", {}),
                              "changes": load(result["directory"] / "changes.json") if (result["directory"] / "changes.json").is_file() else None,
                              "optimizer": {"reference": result["result_ref"], "outcome": result["status"]},
                              "evaluations": [], "audits": []})
        return result

    def verify_starting_point(self, choice, original_files):
        if not isinstance(choice, dict):
            raise ValueError("Optimizer omitted a valid starting-point choice")
        base = choice.get("base_candidate_id")
        parents = choice.get("contributing_candidate_ids")
        reason = choice.get("reason")
        if (not isinstance(base, str) or base not in {"original", *self.candidates} or not isinstance(parents, list)
                or any(not isinstance(parent, str) or parent not in self.candidates for parent in parents)
                or len(set(parents)) != len(parents) or not isinstance(reason, str) or not reason.strip()):
            raise ValueError("Optimizer omitted a valid starting-point choice or parentage")
        expected = original_files if base == "original" else {
            **self.candidates[base]["manifest"], "Cargo.lock": original_files["Cargo.lock"]}
        source = "context/original" if base == "original" else f"context/history/candidates/{base}/library"
        if choice.get("files") != expected or choice.get("source") != source:
            raise ValueError("Optimizer's starting-point source does not match its recorded choice")

    def attempt_entry(self, candidate):
        return next(entry for entry in self.attempts if entry["candidate_id"] == candidate["candidate_id"])


    def check_candidate(self, candidate):
        root = candidate["path"]
        actual = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if relative.parts[0] == ".git":
                continue
            if path.is_symlink():
                raise ValueError("Candidate contains a symlink")
            if path.is_file():
                actual[relative.as_posix()] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        if actual != candidate["manifest"]:
            raise ValueError("Frozen candidate changed")

    def evaluate(self, attempt, baseline, candidate):
        before = self.version()
        source_root = self.root / "checks" / before["sha256"] / "source"
        if not source_root.exists():
            for name in before["files"]:
                source = REPO / "evaluator" / name
                target = source_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                self.records.ref(target)
        result = self.step("evaluator", attempt + "-evaluate", {
            "attempt_id": attempt, "mode": "run", "candidate": candidate["manifest_ref"],
            "baseline": baseline["identity_ref"], "evaluator_version": before},
            ["run", "--candidate", str(candidate["path"]), *self.evaluation_args()], self.args.evaluation_timeout)
        try:
            self.verify_evaluation(baseline, candidate, result, before)
            feedback = evaluation_feedback(result["report"])
        except (ValueError, KeyError, OSError) as error:
            result["status"] = "incomplete"
            feedback = {"schema_version": "evaluator-feedback/v1", "execution_status": "failed",
                        "outcome": "incomplete", "error": str(error)}
        evidence = self.evaluation_evidence(result["directory"])
        ref = self.records.write(f"feedback/{attempt}-evaluation.json", {
            **feedback, "request_id": attempt + "-evaluate", "candidate": candidate["manifest_ref"],
            "native_result": result["result_ref"], "raw_report": result["raw_ref"], "evidence": evidence})
        result["result_ref"] = ref
        result["evaluator_version"] = before
        result["feedback"] = feedback
        if "candidate_id" in candidate:
            self.attempt_entry(candidate)["evaluations"].append({
                "reference": ref, "outcome": result["status"], "evaluator_version": before,
                "correctness": feedback.get("correctness", {}), "performance": feedback.get("performance", {}),
                "error": feedback.get("error")})
        self.records.event("evaluation_feedback", attempt_id=attempt, feedback=ref,
                           summary=self.feedback_summary(feedback))
        return result

    @staticmethod
    def feedback_summary(feedback):
        performance = feedback.get("performance", {})
        parts = [f"Evaluation: {feedback.get('outcome')}."]
        if feedback.get("error"):
            parts.append(str(feedback["error"]))
        for metric, result in performance.get("aggregate", {}).items():
            parts.append(f"{metric}: {result['explanation']}")
        if performance.get("qualification"):
            parts.append(performance["qualification"]["explanation"])
        parts.append("Individual-book regressions: " + json.dumps(performance.get("regressions", [])))
        return " ".join(parts)

    def evaluation_evidence(self, directory):
        references = {}
        for name in ("timings.json", "correctness.json", "books.json", "book-inputs.json", "configuration.json"):
            path = directory / name
            if path.is_file():
                references[name] = self.records.ref(path)
        for folder in ("correctness", "timing-checks", "checker-validation", "commands"):
            for path in sorted((directory / folder).rglob("*.json")):
                references[path.relative_to(directory).as_posix()] = self.records.ref(path)
        failed_commands = []
        for path in sorted((directory / "commands").glob("*.json")):
            command = load(path)
            if command.get("exit_code", 0) != 0 or command.get("timed_out"):
                logs = {}
                for stream in ("stdout", "stderr"):
                    log = path.with_suffix(f".{stream}.log")
                    if log.is_file():
                        logs[stream] = {"reference": self.records.ref(log),
                                        "tail": log.read_text(errors="replace")[-4000:],
                                        "tail_limit_characters": 4000}
                failed_commands.append({"command": command, "logs": logs})
        # Include the actual mismatch details directly in feedback, since a path
        # alone is not useful inside the optimizer's copied context.
        mismatches = []
        for folder in ("correctness", "timing-checks"):
            for path in sorted((directory / folder).rglob("*.json")):
                value = load(path)
                if isinstance(value, dict) and any(value.get(key) for key in ("missing", "extra", "changed")):
                    mismatches.append({"reference": self.records.ref(path), "differences": value})
        return {"artifacts": references, "output_mismatches": mismatches, "failed_commands": failed_commands}

    def verify_evaluation(self, baseline, candidate, result, version):
        report, directory = result["report"], result["directory"]
        if self.version() != version:
            raise ValueError("Evaluator changed during evaluation")
        if report.get("status") == "incomplete":
            return
        if report.get("mode") != "run" or report.get("evaluator_version") != version:
            raise ValueError("Evaluator result has wrong mode/version")
        if report.get("configuration") != self.configuration:
            raise ValueError("Evaluator changed measurement configuration")
        if load(directory / "variants/candidate/library-inputs.json") != candidate["manifest"]:
            raise ValueError("Evaluator measured a different candidate")
        original = load(baseline["context"] / "evaluation/original-library-inputs.json")
        if load(directory / "variants/original/library-inputs.json") != original:
            raise ValueError("Evaluator changed original library")
        # Early correctness failures may precede workload preparation.
        if report["status"] != "correctness-failed" or (directory / "books.json").exists():
            if load(directory / "books.json") != self.books:
                raise ValueError("Evaluator used a different workload selection")
        if report["status"] in {"improved", "slower", "inconclusive"}:
            inputs = load(directory / "book-inputs.json")
            if inputs != load(baseline["context"] / "evaluation/book-inputs.json"):
                raise ValueError("Prepared workloads differ from the validated baseline")
            if set(report.get("analysis", {}).get("books", {})) != {book["id"] for book in self.books}:
                raise ValueError("Timing analysis does not cover every selected book")
            if set(report.get("correctness", {})) != set(inputs):
                raise ValueError("Correctness results do not cover all prepared books and fixtures")

    def audit(self, attempt, candidate, evaluation):
        result = self.step("auditor", attempt + "-audit", {
            "attempt_id": attempt, "candidate": candidate["manifest_ref"],
            "evaluation": evaluation["result_ref"]},
            ["--evaluation", str(evaluation["directory"]),
             "--agent-timeout", str(self.args.auditor_agent_timeout),
             *self.agent_arguments("auditor")], self.args.audit_timeout)
        if result["status"] != "incomplete":
            identity = result["report"].get("identity", {})
            if identity.get("evaluation_report_sha256") != sha256(evaluation["directory"] / "report.json"):
                raise ValueError("Auditor inspected a different evaluation")
            manifest_path = evaluation["directory"] / "variants/candidate/library-inputs.json"
            if identity.get("library_manifest_sha256", {}).get("candidate") != sha256(manifest_path):
                raise ValueError("Auditor inspected a different candidate")
            if result["status"] == "no-issue-found" and (result["report"].get("promoted_checks") or result["report"].get("unresolved")):
                raise ValueError("Clean audit contradicts its added checks or unresolved findings")
        # Include findings in feedback itself, not just a path outside agent context.
        result["result_ref"] = self.records.write(f"feedback/{attempt}-audit.json", {
            "schema_version": "auditor-feedback/v1", "request_id": attempt + "-audit",
            "outcome": result["status"], "report": result["report"], "native_result": result["result_ref"]})
        if "candidate_id" in candidate:
            self.attempt_entry(candidate)["audits"].append({
                "reference": result["result_ref"], "outcome": result["status"],
                "findings": result["report"].get("findings", []),
                "unresolved": result["report"].get("unresolved", []), "error": result["report"].get("error")})
        return result

    def validate_check_change(self, before, after, audit):
        old, new = before["files"], after["files"]
        added = set(new) - set(old)
        if any(new.get(name) != digest for name, digest in old.items()) or not added:
            raise ValueError("Auditor changed existing evaluator code/checks")
        promoted = audit["report"].get("promoted_checks", [])
        prefixes = []
        for name in promoted:
            path = Path(name).resolve()
            relative = path.relative_to(REPO / "evaluator")
            if len(relative.parts) != 2 or relative.parts[0] != "fixtures" or not relative.parts[1].startswith("audit-"):
                raise ValueError("Invalid promoted check path")
            prefixes.append(relative.as_posix() + "/")
        if not prefixes or any(not any(name.startswith(prefix) for prefix in prefixes) for name in added):
            raise ValueError("Evaluator changed outside the auditor's reported new checks")
        self.records.write(f"checks/version-{after['sha256']}.json", after)

    def verify_qualification(self, baseline, candidate, evaluation, audit):
        self.unchanged_code()
        self.check_candidate(candidate)
        if evaluation["evaluator_version"] != self.version() or baseline["report"]["evaluator_version"] != self.version():
            raise ValueError("Cannot qualify stale evaluation evidence")
        feedback = evaluation_feedback(evaluation["report"])
        if evaluation["report"].get("configuration") != self.configuration:
            raise ValueError("Cannot qualify evidence with a different acceptance target")
        if feedback["outcome"] != "improved" or audit["status"] != "no-issue-found":
            raise ValueError("Candidate did not qualify")
