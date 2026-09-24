#!/usr/bin/env python3
"""Export small, portable excerpts without copying raw run evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def short_text(value, limit=400):
    value = re.sub(r'''(?<![\w:])(?:/[^\s`"'<>]+|[A-Za-z]:\\[^\s`"'<>]+)''',
                   "[local path omitted]", str(value))
    return value if len(value) <= limit else value[:limit].rsplit(" ", 1)[0] + "…"


def load_report(location):
    path = location / "report.json" if location.is_dir() else location
    report = json.loads(path.read_text())
    excerpt = {"artifact_type": "illustrative-summary-excerpt",
               "notice": "Summary excerpt; not evaluation input or original raw evidence. Text may be shortened and local paths omitted.",
               "source_report_sha256": digest(path), "status": report["status"]}
    return path, report, excerpt


def evaluation_excerpt(location):
    path, report, excerpt = load_report(location)
    if "mode" in report:
        excerpt["mode"] = report["mode"]
    if "evaluator_version" in report:
        excerpt["evaluator_sha256"] = report["evaluator_version"]["sha256"]
    if "environment" in report:
        excerpt["environment"] = {key: report["environment"][key] for key in (
            "python", "rust_toolchain", "node", "npm", "browser") if key in report["environment"]}
    if "correctness" in report:
        books = report["correctness"].values()
        excerpt["correctness"] = {
            "recorded_books": len(report["correctness"]),
            "candidate_matching_books": sum(book.get("candidate_identical") is True for book in books),
            "recorded_output_files": sum(book.get("files", 0) for book in books)}
    timings = path.parent / "timings.json"
    if timings.is_file():
        excerpt["raw_timing_samples"] = len(json.loads(timings.read_text()))
        excerpt["source_timings_sha256"] = digest(timings)
    if "analysis" in report:
        analysis = report["analysis"]
        excerpt["performance_verdict"] = analysis.get("verdict")
        excerpt["aggregate"] = {
            metric: {key: values[key] for key in ("pairs", "speedup", "confidence_interval_95", "verdict") if key in values}
            for metric, values in analysis.get("aggregate", {}).items()}
    if "calibration" in report:
        excerpt["calibration"] = short_text(report["calibration"])
    return excerpt


def audit_excerpt(location):
    _, report, excerpt = load_report(location)
    if "summary" in report:
        excerpt["summary_excerpt"] = short_text(report["summary"])
    excerpt["findings"] = [
        {key: short_text(finding[key]) for key in ("id", "status", "claim", "requirement") if key in finding}
        for finding in report.get("findings", [])]
    excerpt["reproduced_probes"] = [short_text(probe["id"]) for probe in report.get("probes", [])
                                     if probe.get("status") == "reproduced"]
    excerpt["promoted_checks_count"] = len(report.get("promoted_checks", []))
    if "unresolved" in report:
        excerpt["unresolved"] = [short_text(item) for item in report["unresolved"]]
    if "reevaluation" in report:
        rerun = report["reevaluation"]
        excerpt["reevaluation"] = ({"exit_code": rerun["exit_code"]} if isinstance(rerun, dict)
                                    else short_text(rerun))
    if "auditor" in report:
        config = report["auditor"]
        excerpt["auditor"] = {key: short_text(config[key]) if isinstance(config[key], str) else config[key] for key in (
            "model", "reasoning_effort", "max_rounds", "agent_timeout_seconds",
            "probe_timeout_seconds", "source_sha256") if key in config}
        if config.get("codex", {}).get("version"):
            excerpt["auditor"]["codex_version"] = short_text(config["codex"]["version"])
    return excerpt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--confirmed", type=Path, required=True)
    parser.add_argument("--benign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    excerpts = {"evaluator.json": evaluation_excerpt(args.evaluation),
                "auditor-confirmed.json": audit_excerpt(args.confirmed),
                "auditor-benign.json": audit_excerpt(args.benign)}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, excerpt in excerpts.items():
        (args.output / name).write_text(json.dumps(excerpt, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {len(excerpts)} illustrative excerpts to {args.output}")


if __name__ == "__main__":
    main()
