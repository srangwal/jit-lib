"""Freeze the effective objective, controller instructions, and candidate history."""

import json
import math
import os
import re
from pathlib import Path
import stat

from evaluator.core import inventory, sha256, write_json
from optimizer.artifacts import copy_files, source_inventory
from optimizer.context import safe_path


def prepare_task_inputs(context, *, task=None, previous_candidate=None, history=None):
    result = {}
    if task is not None:
        task = Path(os.path.abspath(task))
        safe_path(task.parent, task.name)
        raw = task.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("schema_version") != "optimizer-task/v1":
            raise ValueError("Unsupported optimizer task schema")
        for key in ("experiment_id", "attempt_id", "request_id"):
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError(f"Optimizer task requires {key}")
        for key in ("task", "workload"):
            if not isinstance(value.get(key), dict) or not value[key]:
                raise ValueError(f"Optimizer task requires {key}")
        (context / "task.json").write_bytes(raw)
        (context / "task.json").chmod(0o444)
        result["task"] = {"path": "context/task.json", "sha256": sha256(context / "task.json"),
                          **{key: value[key] for key in ("experiment_id", "attempt_id", "request_id")}}
    if previous_candidate is not None:
        source = Path(os.path.abspath(previous_candidate))
        safe_path(source.parent, source.name)
        if not source.is_dir():
            raise ValueError("Previous candidate must be an existing directory")
        # Optimizer exports contain a Git index, but Git metadata is never input.
        files = {}
        for root, directories, names in os.walk(source, followlinks=False):
            if Path(root) == source:
                directories[:] = [name for name in directories if name != ".git"]
                names = [name for name in names if name != ".git"]
            for name in directories + names:
                path = Path(root) / name
                if set(path.relative_to(source).parts) & {".git", "target", "node_modules", "__pycache__"}:
                    raise ValueError(f"Previous candidate contains generated files: {path}")
                mode = path.lstat()
                if not (stat.S_ISREG(mode.st_mode) or stat.S_ISDIR(mode.st_mode)):
                    raise ValueError(f"Previous candidate contains a link or special file: {path}")
                if stat.S_ISREG(mode.st_mode):
                    if mode.st_nlink != 1:
                        raise ValueError(f"Previous candidate contains a hard link: {path}")
                    files[path.relative_to(source).as_posix()] = {"bytes": mode.st_size, "sha256": sha256(path)}
        if "Cargo.toml" not in files:
            raise ValueError("Previous candidate lacks Cargo.toml")
        previous = context / "previous"
        copy_files(source, previous, files)
        if source_inventory(previous) != files:
            raise ValueError("Previous candidate changed while copying")
        for name, expected in files.items():
            path = safe_path(source, name)
            if path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
                raise ValueError("Previous candidate changed while copying")
        lock = context / "original/Cargo.lock"
        if "Cargo.lock" in files and sha256(previous / "Cargo.lock") != sha256(lock):
            raise ValueError("Previous candidate changed the supplied library test lockfile")
        (previous / "Cargo.lock").write_bytes(lock.read_bytes())
        for path in previous.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & 0o555)
        result["previous"] = {"path": "context/previous", "files": inventory(previous)}
    if history is not None:
        result["history"] = prepare_history(context, history)
    target = None
    target_source = None
    for relative in ("task.json", "evaluation/report.json"):
        path = context / relative
        if path.exists():
            value = json.loads(path.read_text())
            settings = value.get("task" if relative == "task.json" else "configuration", {})
            if "library_reduction_target_percent" in settings:
                target = settings["library_reduction_target_percent"]
                target_source = relative
                break
    if target is None:
        config = Path(__file__).resolve().parents[1] / "evaluator/config.json"
        target = json.loads(config.read_text())["library_reduction_target_percent"]
        target_source = "current evaluator/config.json"
    if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target) or not 0 <= target < 100:
        raise ValueError("Invalid library time-reduction target")
    objective = {"library_reduction_target_percent": target, "source": target_source,
                 "correctness_boundary": "Application library usage, including new contents and supported configurations"}
    if task is not None:
        stretch = json.loads((context / "task.json").read_text())["task"].get("optimizer_stretch_target")
        if stretch is not None:
            amount = stretch.get("time_reduction_percent") if isinstance(stretch, dict) else None
            if (not isinstance(stretch, dict) or stretch.get("schema_version") != "optimizer-stretch-target/v1"
                    or stretch.get("acceptance_threshold_percent") != target
                    or isinstance(amount, bool) or not isinstance(amount, (int, float))
                    or not math.isfinite(amount) or not target <= amount < 100):
                raise ValueError("Invalid optimizer stretch target")
            objective["optimizer_stretch_target"] = stretch
    write_json(context / "objective.json", objective)
    (context / "objective.json").chmod(0o444)
    result["objective"] = {"path": "context/objective.json", "sha256": sha256(context / "objective.json"), **objective}
    return result


def prepare_history(context, history):
    source = Path(os.path.abspath(history))
    safe_path(source.parent, source.name)
    ledger_path = safe_path(source, "ledger.json")
    if not ledger_path.is_file() or ledger_path.stat().st_nlink != 1:
        raise ValueError("History ledger must be an independent file")
    raw = ledger_path.read_bytes()
    ledger = json.loads(raw)
    if (not isinstance(ledger, dict) or ledger.get("schema_version") != "optimizer-history/v1"
            or not isinstance(ledger.get("entries"), list) or not isinstance(ledger.get("candidates"), dict)
            or not isinstance(ledger.get("artifacts"), dict)):
        raise ValueError("Unsupported optimizer history schema")
    actual = source_inventory(source)
    expected = dict(ledger["artifacts"])
    if "ledger.json" in expected:
        raise ValueError("History manifest must not include its ledger")
    expected["ledger.json"] = {"bytes": len(raw), "sha256": sha256(ledger_path)}
    if actual != expected or "summary.md" not in actual:
        raise ValueError("History artifact inventory differs from its manifest")
    destination = context / "history"
    copy_files(source, destination, actual)
    if source_inventory(destination) != actual or source_inventory(source) != actual:
        raise ValueError("History changed while copying")
    lock = context / "original/Cargo.lock"
    for candidate_id, candidate in ledger["candidates"].items():
        if (not re.fullmatch(r"[A-Za-z0-9_-]+", candidate_id) or candidate_id in {"original", "previous"}
                or not isinstance(candidate, dict)
                or candidate.get("path") != f"candidates/{candidate_id}/library"
                or not isinstance(candidate.get("files"), dict)):
            raise ValueError("Invalid history candidate")
        tree = safe_path(destination, candidate["path"])
        if source_inventory(tree) != candidate["files"] or "Cargo.toml" not in candidate["files"]:
            raise ValueError("History candidate differs from its source manifest")
        if "Cargo.lock" in candidate["files"] and sha256(tree / "Cargo.lock") != sha256(lock):
            raise ValueError("History candidate changed the supplied library test lockfile")
        (tree / "Cargo.lock").write_bytes(lock.read_bytes())
    for path in destination.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode & 0o555)
    return {"path": "context/history", "ledger_sha256": sha256(destination / "ledger.json"),
            "files": inventory(destination)}
