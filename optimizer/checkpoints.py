"""Service base requests outside the agent's write access and retain their lineage."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import threading

from evaluator.core import inventory, record_progress, sha256, write_json
from optimizer.artifacts import copy_files, source_inventory
from optimizer.context import safe_path


@contextmanager
def monitor_requests(handler):
    """Keep one agent session alive while the trusted runner services requests."""
    if handler is None:
        yield
        return
    stopped = threading.Event()
    errors = []

    def monitor():
        while not stopped.wait(0.05):
            try:
                handler()
            except Exception as error:
                errors.append(error)
                return

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()
    if errors:
        raise errors[0]
    handler()


class BaseCheckpoints:
    def __init__(self, workspace, context, output, report):
        self.workspace, self.context, self.output, self.report = workspace, context, output, report
        self.protected = inventory(context)
        self.bases = {"original": context / "original"}
        if (context / "previous").is_dir():
            self.bases["previous"] = context / "previous"
        if (context / "history/ledger.json").is_file():
            ledger = json.loads((context / "history/ledger.json").read_text())
            self.bases.update({key: safe_path(context / "history", value["path"])
                               for key, value in ledger["candidates"].items()})
        self.requests = {}
        self.starting_library = None
        self.checkpoints = []

    def __call__(self):
        request_path = safe_path(self.workspace, "base-request.json")
        if not request_path.exists():
            return
        if request_path.stat().st_nlink != 1 or not request_path.is_file():
            raise ValueError("Base request must be an independent regular file")
        request = json.loads(request_path.read_text())
        if not isinstance(request, dict) or set(request) != {"request_id", "base_candidate_id", "contributing_candidate_ids", "reason"}:
            raise ValueError("Invalid base request fields")
        request_id = request["request_id"]
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
            raise ValueError("Invalid base request ID")
        if request_id in self.requests:
            if request != self.requests[request_id]:
                raise ValueError("Base request ID was reused with different contents")
            return
        base = request["base_candidate_id"]
        contributors = request["contributing_candidate_ids"]
        if not isinstance(base, str) or base not in self.bases:
            raise ValueError("Unknown starting candidate")
        if (not isinstance(contributors, list) or any(not isinstance(key, str) or key not in self.bases or key == "original" for key in contributors)
                or len(set(contributors)) != len(contributors)):
            raise ValueError("Unknown or duplicate contributing candidate")
        if not isinstance(request["reason"], str) or not request["reason"].strip():
            raise ValueError("Starting point needs a reason")
        if inventory(self.context) != self.protected:
            raise RuntimeError("Protected context changed before base selection")
        library = safe_path(self.workspace, "library")
        number = len(self.checkpoints) + 1
        directory = self.output / "base-checkpoints" / f"{number:03d}"
        directory.mkdir(parents=True, exist_ok=False)
        discarded = None
        if library.exists():
            if not self.checkpoints:
                raise ValueError("Library edits preceded the first trusted base checkpoint")
            files = source_inventory(library)
            copy_files(library, directory / "abandoned-library", files)
            if inventory(directory / "abandoned-library") != files:
                raise ValueError("Working library changed while archiving")
            discarded = {"path": str((directory / "abandoned-library").relative_to(self.output)), "files": files}
            shutil.rmtree(library)
        source = self.bases[base]
        files = inventory(source)
        point = {"schema_version": "optimizer-base-checkpoint/v1", **request, "source": str(source.relative_to(self.output)), "files": files}
        if discarded:
            point["abandoned_work"] = discarded
        path = directory / "checkpoint.json"
        write_json(path, point)
        copy_files(source, library, files)
        if inventory(library) != files:
            raise ValueError("Base source changed while copying")
        self.starting_library = source
        self.requests[request_id] = request
        self.checkpoints.append({"path": str(path.relative_to(self.output)), "sha256": sha256(path)})
        self.report["starting_point"] = point
        self.report["base_checkpoints"] = list(self.checkpoints)
        write_json(self.output / "starting-point.json", point)
        write_json(self.output / "report.json", self.report)
        record_progress(self.output, "base_selected", base_candidate_id=base, evidence=str(path.relative_to(self.output)))
        response = {"request_id": request_id, "status": "ready", "base_candidate_id": base,
                    "checkpoint": str(path), "checkpoint_sha256": sha256(path)}
        temporary = safe_path(self.workspace, ".base-response.tmp")
        if temporary.exists():
            if not temporary.is_file() or temporary.stat().st_nlink != 1:
                raise ValueError("Unsafe base response temporary file")
            temporary.unlink()
        write_json(temporary, response)
        target = safe_path(self.workspace, "base-response.json")
        temporary.replace(target)

    def verify(self):
        for item in self.checkpoints:
            if sha256(self.output / item["path"]) != item["sha256"]:
                raise ValueError("Trusted base checkpoint changed")
            checkpoint = json.loads((self.output / item["path"]).read_text())
            abandoned = checkpoint.get("abandoned_work")
            if abandoned and source_inventory(safe_path(self.output, abandoned["path"])) != abandoned["files"]:
                raise ValueError("Archived abandoned work changed")
