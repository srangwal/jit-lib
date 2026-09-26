#!/usr/bin/env python3
"""Manually audit a frozen evaluator run with a coding agent and differential probes."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from auditor.agent import check_login, configuration, investigate, validate_response
from auditor.evidence import prepare_evidence
from auditor.probes import run_probe, validate_probe
from evaluator.core import (evaluator_fingerprint, inventory, record_progress, sha256,
                            validate_library_reduction_target, write_json)
from coding_agents.config import add_arguments, apply_arguments, EXECUTABLES, snapshot as snapshot_runtime


def portable_identity(identity):
    """Permanent fixtures retain artifact identity, not a contributor's home path."""
    identity = dict(identity)
    if isinstance(identity.get("evaluation"), str):
        path = Path(identity["evaluation"]).resolve()
        try:
            identity["evaluation"] = {"kind": "repository-relative", "path": path.relative_to(REPO).as_posix()}
        except ValueError:
            identity["evaluation"] = {"kind": "external-artifact", "name": path.name,
                                      "report_sha256": identity.get("evaluation_report_sha256")}
    return identity


def auditor_provenance(root, args):
    """Freeze the controller contract before authentication or model invocation."""
    source = REPO / "auditor"
    snapshot = root / "auditor-source"
    snapshot.mkdir()
    names = sorted({path.name for path in source.glob("*.py")} |
                   {"prompt.md", "response.schema.json", "config.json"})
    manifest = {}
    for name in names:
        shutil.copy2(source / name, snapshot / name)
        manifest[name] = sha256(snapshot / name)
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    return {"source_sha256": digest, "source_files_sha256": manifest,
            "model": args.model, "reasoning_effort": args.reasoning_effort if getattr(args, "agent", "codex") != "opencode" else None, "max_rounds": args.max_rounds,
            "agent_timeout_seconds": args.agent_timeout, "probe_timeout_seconds": args.probe_timeout,
            "platform": {"system": platform.system(), "release": platform.release(),
                         "machine": platform.machine(), "python": platform.python_version()},
            "coding_agent": {"name": getattr(args, "agent", "codex"), "executable": None, "version": None},
            "local_base_url": getattr(args, "local_base_url", None),
            "coding_agents_version": snapshot_runtime(root / "coding-agents-source"),
            "sandbox": {"agent": "read-only", "approval_policy": "never", "web_search": "disabled",
                        "ignore_user_config": True, "ignore_rules": getattr(args, "agent", "codex") == "codex",
                        "tool_runtime": "native Codex" if getattr(args, "agent", "codex") == "codex" else "sandboxed MCP shell",
                        "probe": "macOS sandbox-exec", "probe_executable": "/usr/bin/sandbox-exec",
                        "probe_policy_source_sha256": manifest["probes.py"],
                        "probe_policy_records": "probes/<id>/<variant>-<repetition>/sandbox.sb"}}


def check_platform():
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("Auditing requires macOS with /usr/bin/sandbox-exec; no agent was started")


def promote(probe, finding, result, fixtures, identity):
    if result["status"] != "reproduced" or finding["status"] != "confirmed":
        raise ValueError("Only reproduced, confirmed findings can become fixtures")
    if not finding["requirement"].strip() or probe["id"] not in finding["probe_ids"]:
        raise ValueError("A regression needs its supported requirement and reproduction")
    contents = validate_probe(probe)
    digest = hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()[:16]
    target = fixtures / f"audit-{digest}"
    fixtures.mkdir(parents=True, exist_ok=True)
    if target.exists():
        expected = set(contents) | {"audit.json"}
        if target.is_symlink() or set(inventory(target)) != expected or any(
                (target / name).read_text() != content for name, content in contents.items()):
            raise ValueError(f"Existing fixture differs: {target}")
        return str(target)
    with tempfile.TemporaryDirectory(prefix="audit-fixture-", dir=fixtures.parent) as temporary:
        stage = Path(temporary) / "book"
        for name, content in contents.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        write_json(stage / "audit.json", {"finding": finding, "probe": probe["id"],
                                          "identity": portable_identity(identity), "result": result["reason"]})
        stage.rename(target)
    return str(target)


def audit(package, root, fixtures, *, max_rounds=3, agent=investigate, probe_runner=run_probe,
          agent_options=None, probe_timeout=30, provenance=None):
    report = {"status": "incomplete", "identity": package["identity"],
              "limitations": package["limitations"], "rounds": [], "findings": [],
              "probes": [], "promoted_checks": [], "reevaluation": "not-needed"}
    if provenance is not None:
        report["auditor"] = provenance
    frozen = inventory(package["root"])
    requests, results, findings = {}, {}, {}

    def unchanged():
        if provenance is not None and evaluator_fingerprint(REPO / "coding_agents") != provenance["coding_agents_version"]:
            raise ValueError("Coding-agent adapter changed during investigation")
        if inventory(package["root"]) != frozen:
            raise ValueError("Frozen audit evidence changed during investigation")
        if provenance is not None and any(sha256(REPO / "auditor" / name) != digest
                                          for name, digest in provenance["source_files_sha256"].items()):
            raise ValueError("Auditor source or contract changed during investigation")

    try:
        for number in range(1, max_rounds + 1):
            record_progress(root, "investigation_started", round=number)
            print(f"Audit round {number}/{max_rounds}", flush=True)
            response = agent(package["root"], report["rounds"], root / f"round-{number}",
                             **(agent_options or {}))
            validate_response(response)
            unchanged()
            if response["action"] == "finish" and response["probes"]:
                raise ValueError("A finish response cannot request unexecuted probes")
            for finding in response["findings"]:
                if not finding["id"].strip() or not finding["claim"].strip():
                    raise ValueError("Finding needs an id and claim")
                findings[finding["id"]] = finding
            report["findings"] = list(findings.values())
            round_record = {"response": response, "probe_results": []}
            report["rounds"].append(round_record)
            for probe in response["probes"]:
                record_progress(root, "probe_started", probe=probe["id"], round=number)
                validate_probe(probe)
                if probe["id"] in requests:
                    raise ValueError(f"Probe id reused: {probe['id']}")
                requests[probe["id"]] = probe
                result = probe_runner(probe, package["binaryPaths"], root / "probes" / probe["id"],
                                      [REPO, package["root"], root], timeout=probe_timeout)
                unchanged()
                results[probe["id"]] = result
                round_record["probe_results"].append(result)
                report["probes"].append(result)
                record_progress(root, "probe_completed", probe=probe["id"], status=result["status"])
            if response["action"] == "finish":
                confirmed = []
                unresolved = []
                covered = set()
                for finding in findings.values():
                    if set(finding["probe_ids"]) - results.keys():
                        unresolved.append(finding["id"])
                        continue
                    reproduced = [key for key in finding["probe_ids"]
                                  if results.get(key, {}).get("status") == "reproduced"]
                    if finding["status"] == "confirmed" and reproduced:
                        if not finding["requirement"].strip() or not finding["code_references"]:
                            raise ValueError("Confirmed findings need a requirement and code references")
                        confirmed.append(finding)
                        for key in reproduced:
                            path = promote(requests[key], finding, results[key], fixtures, package["identity"])
                            if path not in report["promoted_checks"]:
                                report["promoted_checks"].append(path)
                            covered.add(key)
                    elif finding["status"] != "dismissed":
                        unresolved.append(finding["id"])
                # An agent cannot erase a controller-observed failure by omitting it.
                unresolved.extend(key for key, value in results.items()
                                  if value["status"] != "not_reproduced" and key not in covered)
                if package["identity"].get("evaluation_status") in {"incomplete", "correctness-failed", None}:
                    unresolved.append("incomplete-evaluation-evidence")
                report["unresolved"] = sorted(set(unresolved))
                report["status"] = ("confirmed-violation" if confirmed else
                                    "unresolved" if unresolved else "no-issue-found")
                report["summary"] = response["summary"]
                break
        else:
            report["error"] = "Investigation round limit reached without a final assessment"
        unchanged()
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="incomplete", error=f"{type(error).__name__}: {error}")
    if report["promoted_checks"]:
        report["reevaluation"] = "required"
    record_progress(root, "assessment_completed", status=report["status"], promoted_checks=report["promoted_checks"])
    return report


def candidate_checkout(package, root):
    """Restore the manifest, including files tracked despite ignore rules."""
    candidate = root / "reevaluation-candidate"
    candidate.mkdir()
    source = package["root"] / "variants/candidate/library"
    manifest = json.loads((source.parent / "library-inputs.json").read_text())
    for relative in manifest:
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    subprocess.run(["git", "init", "--quiet", str(candidate)], check=True)
    subprocess.run(["git", "-C", str(candidate), "add", "--force", "--all"], check=True)
    names = set(subprocess.check_output(["git", "-C", str(candidate), "ls-files", "-z"]).decode().split("\0")) - {""}
    if names != set(manifest) or any(sha256(candidate / name) != manifest[name]["sha256"] for name in names):
        raise ValueError("Reevaluation candidate differs from the submitted input manifest")
    return candidate


def reevaluate(package, root, args):
    """Rebuild exactly the submitted candidate files in a temporary Git index."""
    report = json.loads((package["root"] / "evaluation/report.json").read_text())
    config = report.get("configuration", {})
    field = "library_reduction_target_percent"
    source = "evaluation-report"
    if field not in config:
        # Historical runs predate this policy; make the new default explicit.
        config = json.loads((REPO / "evaluator/config.json").read_text())
        source = "current-evaluator-default"
    target = validate_library_reduction_target(config[field])
    candidate = candidate_checkout(package, root)
    argv = [sys.executable, str(REPO / "evaluator/run.py"), "run", "--candidate", str(candidate),
            "--cache", str(root / "reevaluation"), "--library-reduction-target-percent", str(target)]
    for flag in ("browser", "cargo_home"):
        value = getattr(args, flag)
        if value:
            argv += ["--" + flag.replace("_", "-"), str(value.resolve())]
    write_json(root / "reevaluation-command.json", argv)
    with (root / "reevaluation.log").open("w") as log:
        process = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT)
    reports = sorted((root / "reevaluation/runs").glob("*/report.json"))
    return {"exit_code": process.returncode, "report": str(reports[-1]) if reports else None,
            field: target, "library_reduction_target_source": source}


def save_report(root, report):
    write_json(root / "report.json", report)
    lines = ["# Audit report", "", f"Status: **{report['status']}**", "",
             report.get("summary", report.get("error", "")), "",
             "No-issue-found means no violation detected within this audit, not proof of absence.", ""]
    if report.get("error"):
        lines += ["Error: " + report["error"], ""]
    for finding in report.get("findings", []):
        lines += [f"## {finding['id']} ({finding['status']}: agent assessment)", "",
                  finding["claim"], "", "Requirement: " + finding["requirement"], "",
                  "Code: " + ", ".join(finding["code_references"]), "",
                  "Probes: " + ", ".join(finding["probe_ids"]), "",
                  "Proposed check: " + finding["check_proposal"], ""]
    lines += ["## Permanent checks", "", *[f"- {p}" for p in report.get("promoted_checks", [])], "",
              "Full evaluator rerun: " + str(report.get("reevaluation", "not-started")), "",
              "## Limitations", "", *["- " + item for item in report.get("limitations", [])]]
    (root / "report.md").write_text("\n".join(lines) + "\n")


def main():
    defaults = configuration()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(reasoning_effort=defaults["reasoning_effort"])
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="new directory; default .auditor/runs/<timestamp>")
    add_arguments(parser, defaults)
    parser.add_argument("--max-rounds", type=int, default=defaults["max_rounds"])
    parser.add_argument("--agent-timeout", type=float, default=defaults["agent_timeout_seconds"])
    parser.add_argument("--probe-timeout", type=float, default=defaults["probe_timeout_seconds"])
    parser.add_argument("--reevaluate", action="store_true", help="run full evaluator after adding checks")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--cargo-home", type=Path)
    args = parser.parse_args()
    apply_arguments(parser, args, defaults)
    if args.max_rounds < 1 or any(not math.isfinite(limit) or limit <= 0
                                 for limit in (args.agent_timeout, args.probe_timeout)):
        parser.error("round and time limits must be positive and finite")
    if not args.model.strip():
        parser.error("model must not be empty")
    root = (args.output or REPO / ".auditor/runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")).resolve()
    root.mkdir(parents=True, exist_ok=False)
    print(f"Audit evidence: {root}", flush=True)
    report = {"status": "incomplete"}
    try:
        record_progress(root, "preparation_started")
        report["auditor"] = auditor_provenance(root, args)
        check_platform()
        executable = shutil.which(args.agent_executable or EXECUTABLES[args.agent])
        if not executable:
            raise RuntimeError(f"{args.agent} CLI is required")
        report["auditor"]["coding_agent"]["executable"] = executable
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30, check=True)
        report["auditor"]["coding_agent"]["version"] = version.stdout.strip()
        check_login(executable, args.agent)
        package = prepare_evidence(args.evaluation, root / "input")
        record_progress(root, "preparation_completed")
        package["limitations"] += [
            "Automated experiments cover self-contained book correctness; timing/infrastructure suspicions require separate checks.",
            "Probes use macOS Seatbelt restrictions, not a VM; they have no execution-time disk or memory quota.",
            "Matching local hashes bind these files to the report; they do not authenticate a maliciously rewritten historical run."]
        report = audit(package, root, REPO / "evaluator/fixtures", max_rounds=args.max_rounds,
                       agent_options={"executable": executable, "model": args.model,
                                      "reasoning_effort": args.reasoning_effort, "timeout": args.agent_timeout,
                                      "agent": args.agent, "base_url": args.local_base_url},
                       probe_timeout=args.probe_timeout, provenance=report["auditor"])
        save_report(root, report)
        if report["promoted_checks"] and args.reevaluate:
            print("Running the strengthened evaluator; see reevaluation.log", flush=True)
            report["reevaluation"] = reevaluate(package, root, args)
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="incomplete", error=f"{type(error).__name__}: {error}")
    save_report(root, report)
    record_progress(root, "finished", status=report["status"], error=report.get("error"))
    print(f"Status: {report['status']}. Report: {root / 'report.md'}", flush=True)
    return {"no-issue-found": 0, "confirmed-violation": 1, "unresolved": 2}.get(report["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
