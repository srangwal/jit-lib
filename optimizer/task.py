"""Freeze optional controller instructions and a previous candidate."""

import json
import os
from pathlib import Path
import stat

from evaluator.core import inventory, sha256
from optimizer.artifacts import copy_files, source_inventory
from optimizer.context import safe_path


def prepare_task_inputs(context, *, task=None, previous_candidate=None):
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
    return result
