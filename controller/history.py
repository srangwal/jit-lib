"""Portable, hashed history supplied to each isolated optimizer attempt."""

from copy import deepcopy
import os
from pathlib import Path
import shutil

from evaluator.core import inventory, sha256, write_json

# These contain generated builds, caches, or copies of context already supplied
# separately. Keep all ordinary logs/JSON/prompts/patches and diagnostic outputs.
EXCLUDED = {".git", "__pycache__", "node_modules", "target", "cargo-home", "tmp",
            "context", "candidate", "variants", "books", "binaries",
            "input", "boundary-check", "coding-agents-source", "auditor-source",
            "runtime-state", ".cargo-target", ".cache", "cache"}


def evidence_files(directory):
    for root, directories, files in os.walk(directory, followlinks=False):
        kept = []
        for name in directories:
            if name in EXCLUDED or (Path(root).name == "workspace" and name == "library"):
                continue
            if (Path(root) / name).is_symlink():
                raise ValueError(f"History evidence directory is a symlink: {Path(root) / name}")
            kept.append(name)
        directories[:] = sorted(kept)
        for name in sorted(files):
            path = Path(root) / name
            if path.is_symlink():
                raise ValueError(f"History evidence is a symlink: {path}")
            yield path


def write_bundle(records, attempt, attempts, candidates, current_version):
    """Freeze all prior attempts; retained evidence is never reinterpreted in place."""
    root = records.root
    destination = root / "tasks" / (attempt + "-history")
    destination.mkdir(parents=True, exist_ok=False)

    def copy(source, relative):
        records.ref(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        records.ref(target)
        return {"path": relative, "sha256": sha256(target)}

    def reference(ref):
        return copy(root / ref["path"], "evidence/" + ref["path"])

    entries = []
    for saved in attempts:
        entry = deepcopy(saved)
        for field in ("optimizer", "evaluations", "audits"):
            values = [entry[field]] if field == "optimizer" else entry[field]
            for value in values:
                value["reference"] = reference(value["reference"])
                if field == "evaluations":
                    value["stale"] = value["evaluator_version"] != current_version
                    version = value["evaluator_version"]
                    if isinstance(version, dict):
                        value["evaluator_source"] = "evidence/checks/" + version["sha256"] + "/source"
        entry["evidence"] = []
        for step in sorted((root / "steps").glob(saved["attempt_id"] + "-*")):
            for source in evidence_files(step):
                entry["evidence"].append(copy(source, "evidence/" + source.relative_to(root).as_posix()))
        entries.append(entry)

    for source in evidence_files(root / "checks"):
        copy(source, "evidence/" + source.relative_to(root).as_posix())

    sources = {}
    for candidate_id, candidate in candidates.items():
        location = "candidates/" + candidate_id + "/library"
        for name, expected in candidate["manifest"].items():
            source = candidate["path"] / name
            if source.is_symlink() or sha256(source) != expected["sha256"] or source.stat().st_size != expected["bytes"]:
                raise ValueError("History candidate changed")
            copy(source, location + "/" + name)
        sources[candidate_id] = {"path": location, "files": candidate["manifest"]}

    lines = ["# Complete optimizer history", "",
             "All measurements compare with the original library. Stale results are historical evidence, not current acceptance evidence.",
             "Full proposal, source, patch, logs and reports are linked in ledger.json. Workloads guide specialization; new supported inputs remain in scope.", "",
             "| Candidate / attempt | Starting point | Proposal | Correctness | Library reduction (95% CI) | Application reduction (95% CI) | Audit / concerns |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    def metric(value):
        if not value:
            return "not measured"
        lo, hi = value["time_reduction_interval_95"]
        return f'{value["time_reduction_percent"]:.2f}% [{lo:.2f}, {hi:.2f}]'
    for entry in entries:
        evaluation = entry["evaluations"][-1] if entry["evaluations"] else {}
        audit = entry["audits"][-1] if entry["audits"] else {}
        metrics = evaluation.get("performance", {}).get("aggregate", {})
        regressions = evaluation.get("performance", {}).get("regressions", [])
        regression_names = [f"{item.get('book', item.get('book_id', '?'))} {item.get('metric', '')}"
                            for item in regressions]
        concerns = (f"{audit.get('outcome', 'not run')}; {len(audit.get('findings', []))} findings; "
                    f"{len(audit.get('unresolved', []))} unresolved; regressions: "
                    + (", ".join(regression_names) if regressions else "none"))
        parentage = (entry.get("starting_point") or {})
        base = parentage.get("base_candidate_id", "original")
        contributors = parentage.get("contributing_candidate_ids", [])
        if contributors:
            base += "; ideas: " + ", ".join(contributors)
        values = ["[" + entry["attempt_id"] + "](ledger.json)" + (" (stale)" if evaluation.get("stale") else ""),
                  base,
                  (entry.get("summary") or entry["optimizer"]["outcome"])[:180],
                  evaluation.get("correctness", {}).get("status", "not completed"),
                  metric(metrics.get("indexing")), metric(metrics.get("application_build")), concerns]
        lines.append("| " + " | ".join(map(cell, values)) + " |")
    (destination / "summary.md").write_text("\n".join(lines) + "\n")
    records.ref(destination / "summary.md")
    ledger = {"schema_version": "optimizer-history/v1", "current_evaluator_version": current_version,
              "entries": entries, "candidates": sources, "artifacts": inventory(destination)}
    write_json(destination / "ledger.json", ledger)
    ref = records.ref(destination / "ledger.json")
    return destination, ref, inventory(destination)
