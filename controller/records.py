"""Immutable handoffs and an append-only human-auditable event history."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from evaluator.core import sha256


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON value: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), parse_constant=reject, object_pairs_hook=unique)


class Records:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.sequence = 0
        self.references = []

    def ref(self, path):
        path = Path(path)
        relative = path.absolute().relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"Artifact is a symlink: {current}")
        if not path.is_file():
            raise ValueError(f"Missing artifact: {path}")
        ref = {"path": relative.as_posix(), "sha256": sha256(path)}
        self.references.append(ref)
        return ref

    def write(self, relative, value):
        path = self.root / relative
        if path.is_absolute() and not path.resolve().is_relative_to(self.root):
            raise ValueError("Record path escapes experiment")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        return self.ref(path)

    def verify(self):
        for reference in self.references:
            path = self.root / reference["path"]
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise ValueError(f"Recorded artifact path changed: {reference['path']}")
            if not path.is_file() or path.is_symlink() or sha256(path) != reference["sha256"]:
                raise ValueError(f"Recorded artifact changed: {reference['path']}")

    def event(self, kind, **details):
        self.sequence += 1
        record = {"schema_version": "controller-event/v1", "sequence": self.sequence,
                  "timestamp": now(), "event": kind, **details}
        with (self.root / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        print(f"[{self.sequence}] {kind}: {details.get('summary', details.get('step_id', ''))}", flush=True)
        return record

    def render(self, status, error=None):
        lines = ["# Controller experiment", "", f"Status: **{status}**", ""]
        if error:
            lines += [f"Error: {error}", ""]
        lines += ["Audit no-issue-found is limited to the investigation; it is not proof of absence.",
                  "", "## Timeline", ""]
        path = self.root / "events.jsonl"
        for line in path.read_text().splitlines() if path.exists() else []:
            entry = json.loads(line)
            lines += [f"- **{entry['sequence']}. {entry['event']}** "
                      f"({entry.get('attempt_id', 'setup')}) — {entry.get('summary', entry.get('step_id', ''))}"]
            for name in ("request", "result", "evidence", "feedback", "audit", "candidate"):
                ref = entry.get(name)
                if isinstance(ref, dict) and "path" in ref:
                    lines.append(f"  [{name}]({ref['path']})")
        lines += ["", "Requests and results are immutable. See `events.jsonl` for IDs, timestamps, and decisions.",
                  "Raw component reports and logs remain beside each step's result.", ""]
        (self.root / "report.md").write_text("\n".join(lines))
