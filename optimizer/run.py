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

from auditor.agent import check_login
from evaluator.core import evaluator_fingerprint, inventory, write_json
from optimizer.agent import optimize, probe_workspace
from optimizer.artifacts import copy_files, freeze, seed_cargo_cache
from optimizer.context import prepare_context

HERE = Path(__file__).resolve().parent


def report_markdown(report):
    lines = ["# Optimizer attempt", "", f"Status: **{report['status']}**", "",
             "This attempt has no independent correctness or performance verdict.", ""]
    if "error" in report:
        lines += [f"Error: {report['error']}", ""]
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
                  "python3 evaluator/run.py run --candidate " + shlex.quote(str(Path(report["attempt"]) / "candidate")), "```"]
    if "input_identity" in report:
        lines += ["", "## Input limitations", ""]
        lines += ["- " + item for item in report["input_identity"]["limitations"]]
    return "\n".join(lines) + "\n"


def runtime(executable):
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("Optimizer v1 requires macOS with sandbox-exec; no unsandboxed fallback")
    toolchain = tomllib.loads((REPO / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    versions = {}
    for name, argv in (("codex", [executable, "--version"]),
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
    parser.add_argument("--output", type=Path, help="New attempt directory; existing directories are never overwritten")
    parser.add_argument("--cargo-home", type=Path, default=Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")),
                        help="Read existing crate archives from this cache; never modify it")
    parser.add_argument("--codex", default="codex", help="Codex CLI executable")
    parser.add_argument("--model", default=config["model"])
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"), default=config["reasoning_effort"])
    parser.add_argument("--timeout", type=float, default=config["agent_timeout_seconds"], help="Agent wall-clock limit in seconds")
    args = parser.parse_args(argv)
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
    executable = shutil.which(args.codex)
    if executable:
        executable = str(Path(executable).absolute())
    report = {"status": "incomplete", "attempt": str(output), "baseline": str(args.baseline.resolve()),
              "started_utc": datetime.now(timezone.utc).isoformat(), "invocation": list(argv if argv is not None else sys.argv[1:]),
              "settings": {"model": args.model, "reasoning_effort": args.reasoning_effort, "timeout_seconds": args.timeout},
              "optimizer_version": evaluator_fingerprint(HERE)}
    write_json(output / "report.json", report)
    try:
        if not executable:
            raise RuntimeError(f"Codex CLI was not found: {args.codex}")
        report["runtime"] = runtime(executable)
        check_login(executable)
        print("Preparing baseline context and private library copy...", flush=True)
        context, workspace = output / "context", output / "workspace"
        report["input_identity"] = prepare_context(args.baseline, context, profile=args.profile, feedback=args.feedback)
        protected = inventory(context)
        workspace.mkdir()
        copy_files(context / "original", workspace / "library", inventory(context / "original"))
        report["cargo_cache"] = seed_cargo_cache(args.cargo_home.resolve(), workspace / "cargo-home", context / "original/Cargo.lock")
        print("Checking that tools can write only inside the private workspace...", flush=True)
        report["write_boundary_check"] = probe_workspace(workspace, context, output / "boundary-check", executable=executable)
        print(f"Starting one {args.timeout:g}-second optimizer attempt. Logs: {output / 'agent'}", flush=True)
        response = optimize(workspace, context, output / "agent", executable=executable, model=args.model,
                            reasoning_effort=args.reasoning_effort, timeout=args.timeout)
        report["response"] = response
        if inventory(context) != protected or evaluator_fingerprint(HERE) != report["optimizer_version"]:
            raise RuntimeError("Protected context or optimizer source changed during the attempt")
        report["candidate"] = freeze(workspace, context, output, response)
        report["status"] = "candidate-created" if report["candidate"] else "no-change"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        report["error"] = str(error) or type(error).__name__
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
