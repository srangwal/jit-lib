#!/usr/bin/env python3
"""Run the complete reproduction in a new source copy with empty caches."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def export_source(destination):
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT).decode().split("\0")
    for name in sorted(set(names) - {""}):
        source = ROOT / name
        if source.is_symlink():
            raise RuntimeError(f"Unexpected source symlink: {source}")
        if not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path)
    args = parser.parse_args()
    root = ROOT / ".evaluator/reproduction" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    root.mkdir(parents=True)
    repo = root / "repository"
    export_source(repo)
    env = dict(os.environ, CARGO_HOME=str(root / "cargo-home"),
               npm_config_cache=str(root / "npm-cache"), GIT_TERMINAL_PROMPT="0")
    if args.browser:
        env["PUPPETEER_EXECUTABLE_PATH"] = str(args.browser.resolve())
    summary = {"status": "incomplete", "stages": [], "shared": [
        "installed system tools and Rust toolchain", "browser", "Codex login/account",
        "operating system and filesystem caches"],
        "fresh": ["source copy", "book checkouts", "Cargo cache", "npm cache",
                  "evaluator builds/results", "auditor results"]}

    def run(label, argv, accepted=(0,)):
        print(f"{label} → {root / (label + '.log')}", flush=True)
        with (root / f"{label}.log").open("w") as log:
            result = subprocess.run([sys.executable, *map(str, argv)], cwd=repo,
                                    env=env, stdout=log, stderr=subprocess.STDOUT)
        summary["stages"].append({"name": label, "exit_code": result.returncode})
        if result.returncode not in accepted:
            print("\n".join((root / f"{label}.log").read_text().splitlines()[-20:]), file=sys.stderr)
            raise RuntimeError(f"{label} failed; read {root / (label + '.log')}")

    print(f"Fresh reproduction: {root}", flush=True)
    try:
        run("environment", ["evaluator/environment.py"])
        run("books", ["evaluator/setup_books.py"])
        for component in ("evaluator", "auditor", "optimizer", "controller", "coding_agents"):
            run(f"{component}-tests", ["-m", "unittest", "discover", "-s", f"{component}/tests", "-v"])
        run("self-check", ["evaluator/run.py", "self-check"], accepted=(0, 1))
        reports = list((repo / ".evaluator/runs").glob("*/report.json"))
        if len(reports) != 1:
            raise RuntimeError("Expected one self-check report")
        evaluation = reports[0].parent
        verdict = json.loads(reports[0].read_text())["status"]
        summary["self_check_status"] = verdict
        summary["evaluation"] = str(evaluation.relative_to(root))
        if verdict not in ("validated", "calibration-warning"):
            raise RuntimeError(f"Self-check failed: {verdict}")
        run("baseline-audit", ["auditor/run.py", "--evaluation", evaluation,
                               "--output", repo / ".auditor/baseline"])
        summary["baseline_audit"] = "repository/.auditor/baseline/report.md"
        run("auditor-validation", ["auditor/validation.py", "--evaluation", evaluation,
                                   "--output", repo / ".auditor/validation",
                                   "--cargo-home", root / "cargo-home", "--reevaluate"])
        summary["auditor_validation"] = "repository/.auditor/validation/summary.json"
        summary["status"] = "passed" if verdict == "validated" else "calibration-warning"
    except (Exception, KeyboardInterrupt) as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        print(summary["error"], file=sys.stderr)
    finally:
        (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Status: {summary['status']}. Summary: {root / 'summary.json'}", flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
