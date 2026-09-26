#!/usr/bin/env python3
"""Make one candidate; leave official evaluation and selection to separate commands."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tomllib

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from coding_agents.runtime import check_login
from coding_agents.config import add_arguments, apply_arguments, EXECUTABLES, snapshot
from evaluator.core import evaluator_fingerprint, inventory, record_progress, write_json
from optimizer.agent import optimize, probe_workspace
from optimizer.artifacts import freeze, seed_cargo_cache
from optimizer.context import prepare_context
from optimizer.task import prepare_task_inputs
from optimizer.checkpoints import BaseCheckpoints

HERE = Path(__file__).resolve().parent


def report_markdown(report):
    lines = ["# Optimizer attempt", "", f"Status: **{report['status']}**", "",
             "This attempt has no independent correctness or performance verdict.", ""]
    if "error" in report:
        lines += [f"Error: {report['error']}", ""]
    if "starting_point" in report:
        choice = report["starting_point"]
        lines += [f"Starting point: **{choice['base_candidate_id']}**. {choice['reason']}", ""]
    if "response" in report:
        response = report["response"]
        lines += [response["summary"], "", "## Rationale", ""]
        for guarantee in response["guarantees"]:
            lines += ["- " + guarantee["claim"] + " (" + ", ".join(guarantee["application_references"]) + ")"]
        for title, field in (("Work removed", "removed_work"), ("Behavior preserved", "why_behavior_is_preserved"),
                             ("Expected benefit", "expected_benefit"), ("Profiling evidence", "profile_assessment")):
            lines += ["", f"**{title}:** {response[field]}"]
        lines += ["", "## Local checks (reported by the agent)", ""]
        for check in response["local_checks"]:
            lines += [f"- `{check['command']}` — {check['outcome']}. {check['details']}"]
        if not response["local_checks"]:
            lines += ["No local checks were reported."]
        lines += ["", "These claims are retained with agent/events.jsonl; they are not evaluator results.",
                  "", "## Remaining risks", ""]
        lines += ["- " + risk for risk in response["risks"]] or ["None reported by the agent."]
    if report.get("candidate"):
        lines += ["", "## Candidate", "", "See `candidate/`, `candidate.patch`, and `candidate-files.json`.",
                  "The snapshot has its own Git index and no commits. Keep it unchanged when evaluating it.",
                  "", "From the repository root:", "", "```sh",
                  "python3 evaluator/run.py run --candidate " + shlex.quote(str(Path(report["attempt"]) / "candidate"))
                  + " --library-reduction-target-percent " + str(report["controller_inputs"]["objective"]["library_reduction_target_percent"]), "```"]
    if "input_identity" in report:
        lines += ["", "## Input limitations", ""]
        lines += ["- " + item for item in report["input_identity"]["limitations"]]
    return "\n".join(lines) + "\n"


def runtime(executable, agent="codex"):
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("Optimizer v1 requires macOS with sandbox-exec; no unsandboxed fallback")
    toolchain = tomllib.loads((REPO / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    versions = {}
    for name, argv in ((agent, [executable, "--version"]),
                       ("rustc", ["rustup", "run", toolchain, "rustc", "--version"]),
                       ("cargo", ["rustup", "run", toolchain, "cargo", "--version"])):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"Cannot check {name}: {result.stderr.strip()}")
        versions[name] = result.stdout.strip()
    return {**versions, "python": platform.python_version(), "platform": platform.platform(),
            "rust_toolchain": toolchain}


def main(argv=None):
    config = json.loads((HERE / "config.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="A completed, validated self-check run")
    parser.add_argument("--profile", type=Path, help="Optional measured profile to include as context")
    parser.add_argument("--feedback", type=Path, help="Optional prior evaluator/auditor feedback file")
    parser.add_argument("--task", type=Path, help="Optional optimizer-task/v1 controller brief")
    parser.add_argument("--previous-candidate", type=Path, help="Legacy candidate available as base ID previous")
    parser.add_argument("--history", type=Path, help="Complete optimizer-history/v1 bundle")
    parser.add_argument("--output", type=Path, help="New attempt directory; existing directories are never overwritten")
    parser.add_argument("--cargo-home", type=Path, default=Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")),
                        help="Read existing crate archives from this cache; never modify it")
    add_arguments(parser, config)
    parser.add_argument("--codex", help="Legacy alias for --agent-executable with --agent codex")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"), default=config["reasoning_effort"])
    parser.add_argument("--timeout", type=float, default=config["agent_timeout_seconds"], help="Agent wall-clock limit in seconds")
    args = parser.parse_args(argv)
    apply_arguments(parser, args, config)
    if args.codex and (args.agent != "codex" or args.agent_executable):
        parser.error("--codex is only an executable override for Codex")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be positive and finite")
    if not args.model.strip():
        parser.error("--model cannot be empty")
    output = (args.output or REPO / ".optimizer/attempts" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")).absolute()
    if any(path.is_symlink() for path in (output, *output.parents)):
        parser.error("--output must not use symlinks")
    output = Path(os.path.abspath(output))
    if output.is_relative_to(args.baseline.resolve()):
        parser.error("--output must be outside the baseline")
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error(f"Attempt already exists: {output}")
    executable_name = args.agent_executable or args.codex or EXECUTABLES[args.agent]
    executable = shutil.which(executable_name)
    if executable:
        executable = str(Path(executable).absolute())
    report = {"status": "incomplete", "attempt": str(output), "baseline": str(args.baseline.resolve()),
              "started_utc": datetime.now(timezone.utc).isoformat(), "invocation": list(argv if argv is not None else sys.argv[1:]),
              "settings": {"agent": args.agent, "model": args.model, "local_base_url": args.local_base_url,
                           "reasoning_effort": args.reasoning_effort if args.agent != "opencode" else None, "timeout_seconds": args.timeout},
              "coding_agents_version": snapshot(output / "coding-agents-source"),
              "optimizer_version": evaluator_fingerprint(HERE)}
    write_json(output / "report.json", report)
    try:
        if not executable:
            raise RuntimeError(f"{args.agent} CLI was not found: {executable_name}")
        report["runtime"] = runtime(executable, args.agent)
        check_login(executable, args.agent)
        print("Preparing baseline context and private library copy...", flush=True)
        record_progress(output, "context_preparation_started")
        context, workspace = output / "context", output / "workspace"
        report["input_identity"] = prepare_context(args.baseline, context, profile=args.profile, feedback=args.feedback)
        report["controller_inputs"] = prepare_task_inputs(context, task=args.task, previous_candidate=args.previous_candidate, history=args.history)
        protected = inventory(context)
        workspace.mkdir()
        report["cargo_cache"] = seed_cargo_cache(args.cargo_home.resolve(), workspace / "cargo-home", context / "original/Cargo.lock")
        record_progress(output, "context_preparation_completed", context="context/identity.json")
        print("Checking that tools can write only inside the private workspace...", flush=True)
        record_progress(output, "boundary_probe_started")
        report["write_boundary_check"] = probe_workspace(workspace, context, output / "boundary-check", executable=executable, agent=args.agent)
        record_progress(output, "boundary_probe_completed", evidence="boundary-check/result.json")
        checkpoints = BaseCheckpoints(workspace, context, output, report)
        print(f"Starting one {args.timeout:g}-second optimizer session. Logs: {output / 'agent'}", flush=True)
        record_progress(output, "session_started", remaining_seconds=args.timeout)
        response = optimize(workspace, context, output / "agent", executable=executable, model=args.model,
                            reasoning_effort=args.reasoning_effort, timeout=args.timeout, agent=args.agent,
                            base_url=args.local_base_url, checkpoint_handler=checkpoints)
        checkpoints.verify()
        report["response"] = response
        record_progress(output, "session_completed", response_status=response["status"], evidence="agent/response.json")
        if (inventory(context) != protected or evaluator_fingerprint(HERE) != report["optimizer_version"]
                or evaluator_fingerprint(REPO / "coding_agents") != report["coding_agents_version"]):
            raise RuntimeError("Protected context or optimizer source changed during the attempt")
        if checkpoints.starting_library is None:
            if response["status"] != "no-change" or (workspace / "library").exists():
                raise ValueError("A candidate requires a trusted base checkpoint before editing")
            from auditor.agent import validate_response
            validate_response(response, json.loads((HERE / "response.schema.json").read_text()))
            if not response["summary"].strip():
                raise ValueError("Optimizer must explain its result")
            report["candidate"] = None
        else:
            report["candidate"] = freeze(workspace, context, output, response, starting_library=checkpoints.starting_library)
        report["status"] = "candidate-created" if report["candidate"] else "no-change"
        record_progress(output, "export_completed", status=report["status"],
                        evidence="changes.json" if checkpoints.starting_library is not None else "report.json")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        report["error"] = str(error) or type(error).__name__
        record_progress(output, "error", error_type=type(error).__name__, evidence="report.json")
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "report.json", report)
        (output / "report.md").write_text(report_markdown(report))
        print(f"{report['status']}: {output / 'report.md'}", flush=True)
        if report.get("error"):
            print(report["error"], file=sys.stderr)
    return 1 if report["status"] == "incomplete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
