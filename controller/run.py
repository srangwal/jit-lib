#!/usr/bin/env python3
"""Run up to five traceable optimization/evaluation/audit attempts."""

import argparse
from datetime import datetime, timezone
import fcntl
import math
import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from auditor.run import check_platform
from coding_agents.config import AGENTS, resolve
from controller.components import Components
from controller.loop import experiment
from controller.records import Records, load, now
from evaluator.core import evaluator_fingerprint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Completed validated full ten-book self-check")
    parser.add_argument("--output", type=Path, help="New experiment directory")
    parser.add_argument("--attempts", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--optimizer-timeout", type=float, default=600, help="Agent budget per attempt, at most 600 seconds")
    parser.add_argument("--evaluation-timeout", type=float, default=7200, help="Whole evaluator command limit in seconds")
    parser.add_argument("--audit-timeout", type=float, default=3600, help="Whole auditor command limit in seconds")
    parser.add_argument("--model", help="Override both component models (component-specific flags take precedence)")
    for role in ("optimizer", "auditor"):
        parser.add_argument(f"--{role}-agent", choices=AGENTS)
        parser.add_argument(f"--{role}-model")
    parser.add_argument("--local-base-url", help="Local OpenAI-compatible URL for components using OpenCode")
    parser.add_argument("--library-reduction-target-percent", type=float,
                        default=load(REPO / "evaluator/config.json")["library_reduction_target_percent"],
                        help="Required lower 95%% confidence bound for library time reduction (default: 20)")
    parser.add_argument("--profile", type=Path, help="Optional measured profile; absence is recorded")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--cargo-home", type=Path)
    parser.add_argument("--cache", type=Path, default=REPO / ".evaluator")
    args = parser.parse_args(argv)
    for field in ("optimizer_timeout", "evaluation_timeout", "audit_timeout"):
        if not math.isfinite(getattr(args, field)) or getattr(args, field) <= 0:
            parser.error(f"--{field.replace('_', '-')} must be positive and finite")
    if not math.isfinite(args.library_reduction_target_percent) or not 0 <= args.library_reduction_target_percent < 100:
        parser.error("--library-reduction-target-percent must be finite and in [0, 100)")
    if args.optimizer_timeout > 600:
        parser.error("Optimizer budget cannot exceed 600 seconds per attempt")
    try:
        for role in ("optimizer", "auditor"):
            defaults = load(REPO / role / "config.json")
            agent = getattr(args, role + "_agent") or defaults["agent"]
            selected = resolve(defaults, agent,
                               getattr(args, role + "_model") if getattr(args, role + "_model") is not None else args.model,
                               args.local_base_url if agent == "opencode" else None)
            setattr(args, role + "_runtime", selected)
        if args.local_base_url and not any(getattr(args, role + "_runtime")["agent"] == "opencode" for role in ("optimizer", "auditor")):
            parser.error("--local-base-url requires an OpenCode component")
    except ValueError as error:
        parser.error(str(error))
    for field in ("baseline", "profile", "browser", "cargo_home", "cache"):
        if getattr(args, field):
            setattr(args, field, getattr(args, field).resolve())
    root = Path(os.path.abspath(args.output or REPO / ".controller/experiments" /
                               datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")))
    if any(path.is_symlink() for path in (root, *root.parents)):
        parser.error("Output must not use symlinks")
    if root.is_relative_to(args.baseline) or args.baseline.is_relative_to(root):
        parser.error("Experiment and baseline directories must not overlap")
    lock_path = REPO / ".controller/experiment.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another controller experiment is running in this repository")
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            parser.error("Output already exists; previous evidence is never overwritten")
        records = Records(root)
        summary = {"schema_version": "controller-summary/v1", "experiment_id": root.name,
                   "status": "incomplete", "started_utc": now()}
        try:
            config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
            config.update(policy={"audit": "every_candidate", "stop": "first_qualifying_candidate",
                                  "performance": "library-time-reduction/v1",
                                  "library_reduction_target_percent": args.library_reduction_target_percent,
                                  "application_performance_blocks_success": False, "starting_point": "optimizer_choice"},
                          code_versions={name: evaluator_fingerprint(REPO / name)
                                         for name in ("controller", "optimizer", "evaluator", "auditor", "coding_agents")})
            for name, version in config["code_versions"].items():
                for relative in version["files"]:
                    target = root / "source" / name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(REPO / name / relative, target)
                    records.ref(target)
                if evaluator_fingerprint(root / "source" / name) != version:
                    raise ValueError(f"{name} source changed while capturing experiment inputs")
            config_ref = records.write("configuration.json", config)
            records.event("experiment_started", summary="Starting bounded experiment.", evidence=config_ref)
            records.render("running")
            check_platform()
            summary.update(experiment(records, Components(records, args), args.attempts))
            records.verify()
        except KeyboardInterrupt:
            summary.update(status="cancelled", error="Interrupted by user; evidence retained")
        except Exception as error:
            summary.update(status="incomplete", error=f"{type(error).__name__}: {error}")
        finally:
            summary["finished_utc"] = now()
            records.event("experiment_finished", summary=summary.get("error", summary["status"]),
                          status=summary["status"])
            records.write("summary.json", summary)
            records.render(summary["status"], summary.get("error"))
            print(f"{summary['status']}: {root / 'report.md'}", flush=True)
        return {"qualified": 0, "no-qualifying-improvement": 2, "cancelled": 130}.get(summary["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
