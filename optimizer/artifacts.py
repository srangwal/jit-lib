"""Keep candidate files separate from scratch work and freeze submitted changes."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tomllib

from auditor.agent import validate_response
from auditor.evidence import safe_path
from evaluator.core import differences, inventory, sha256, write_json

HERE = Path(__file__).resolve().parent


class SourceReferenceError(ValueError):
    """A source citation can be corrected without editing the candidate."""


def copy_files(source, destination, files):
    destination.mkdir(parents=True, exist_ok=False)
    for name in files:
        original = safe_path(source, name)
        target = safe_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        target.chmod(target.stat().st_mode | stat.S_IWUSR)


def source_inventory(root):
    """Reject links and special files, including inside generated directories."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Candidate library must remain a real directory")
    for path in root.rglob("*"):
        mode = path.lstat()
        if not (stat.S_ISREG(mode.st_mode) or stat.S_ISDIR(mode.st_mode)):
            raise ValueError(f"Candidate contains a link or special file: {path}")
        if stat.S_ISREG(mode.st_mode) and mode.st_nlink != 1:
            raise ValueError(f"Candidate contains a hard link: {path}")
        if set(path.relative_to(root).parts) & {".git", "target", "node_modules", "__pycache__"}:
            raise ValueError(f"Keep generated files outside the candidate library: {path}")
    return inventory(root)


def validate_submission(response, context, workspace, changed):
    validate_response(response, json.loads((HERE / "response.schema.json").read_text()))
    if not response["summary"].strip():
        raise ValueError("Optimizer must explain its result")
    if response["status"] == "no-change":
        if changed:
            raise ValueError("Optimizer reported no-change but modified the library")
        return
    if not changed:
        raise ValueError("Optimizer reported a candidate without a source change")
    if not response["guarantees"] or not response["library_references"]:
        raise ValueError("A candidate needs application guarantees and library references")
    for field in ("removed_work", "why_behavior_is_preserved", "expected_benefit", "profile_assessment"):
        if not response[field].strip():
            raise ValueError(f"Candidate explanation is missing {field}")

    def reference(value, prefix, root):
        match = re.fullmatch(r"(.+):(\d+)", value)
        if not match or not match[1].startswith(prefix + "/"):
            raise SourceReferenceError(f"Expected {prefix}/path:line source reference: {value}")
        path = safe_path(root, match[1])
        if not path.is_file() or not 1 <= int(match[2]) <= len(path.read_text().splitlines()):
            raise SourceReferenceError(f"Source reference does not identify an existing line: {value}")

    for guarantee in response["guarantees"]:
        if not guarantee["claim"].strip() or not guarantee["application_references"]:
            raise ValueError("Each guarantee needs a claim and application source references")
        for value in guarantee["application_references"]:
            reference(value, "application", context)
    if not any(value.startswith("original/") for value in response["library_references"]):
        raise ValueError("Library references must include the original source's unnecessary work")
    for value in response["library_references"]:
        if value.startswith("library/"):
            reference(value, "library", workspace)
        else:
            reference(value, "original", context)


def freeze(workspace, context, destination, response, *, starting_library=None):
    """Export an independent Git-visible snapshot; create no commits."""
    original = inventory(context / "original")
    candidate = source_inventory(workspace / "library")
    if candidate.get("Cargo.lock") != original.get("Cargo.lock"):
        raise ValueError("The supplied library test lockfile was changed or removed")
    # Cargo.lock was supplied for local tests, not part of the replacement source.
    original.pop("Cargo.lock", None)
    candidate.pop("Cargo.lock", None)
    if "Cargo.toml" not in candidate:
        raise ValueError("Candidate is missing Cargo.toml")
    diff = differences(original, candidate)
    changed = any(diff.values())
    starting = inventory(starting_library) if starting_library is not None else dict(original)
    starting.pop("Cargo.lock", None)
    attempt_diff = differences(starting, candidate)
    validate_submission(response, context, workspace, any(attempt_diff.values()))
    write_json(destination / "changes.json", diff)
    write_json(destination / "attempt-changes.json", attempt_diff)
    if response["status"] == "no-change":
        return None
    if not changed:
        raise ValueError("Candidate reverted to the original library without a specialization")
    proposal = safe_path(workspace, "proposal.md")
    if not proposal.is_file() or not proposal.read_text().strip():
        raise ValueError("Candidate is missing proposal.md")
    shutil.copy2(proposal, destination / "proposal.md")
    exported = destination / "candidate"
    copy_files(context / "original", exported, original)

    def git(*args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false",
                               "-C", str(exported), *args], env=env, check=True, capture_output=True, timeout=30)

    # An index is enough for the evaluator's ls-files snapshot and a portable diff.
    # No identity, commit, remote, or change to the parent repository is needed.
    git("init", "--quiet", "--template=")
    git("add", "--force", "--", *sorted(original))
    for name in diff["missing"]:
        (exported / name).unlink()
    for name in candidate:
        target = exported / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace / "library" / name, target)
    if diff["extra"]:
        git("add", "--intent-to-add", "--force", "--", *diff["extra"])
    patch = git("diff", "--binary", "--no-ext-diff", "--no-textconv").stdout
    exported_files = {name: {"bytes": (exported / name).stat().st_size,
                             "sha256": sha256(exported / name)} for name in candidate}
    if exported_files != candidate:
        raise ValueError("Candidate changed while exporting; snapshot hashes do not match")
    (destination / "candidate.patch").write_bytes(patch)
    write_json(destination / "candidate-files.json", candidate)
    digest = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
    return {"path": "candidate", "sha256": digest, "files": len(candidate),
            "patch_sha256": sha256(destination / "candidate.patch")}


def seed_cargo_cache(source, destination, lock):
    """Copy available locked crates, never credentials, config, or shared links."""
    destination.mkdir(parents=True, exist_ok=False)
    packages = tomllib.loads(lock.read_text())["package"]
    registry = source / "registry"
    copied, missing = [], []
    for package in packages:
        if not package.get("source", "").startswith("registry+"):
            continue
        name, version = package["name"], package["version"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not re.fullmatch(r"[A-Za-z0-9.+_-]+", version):
            raise ValueError("Invalid crate name or version in test lockfile")
        index_name = (f"1/{name}" if len(name) == 1 else f"2/{name}" if len(name) == 2
                      else f"3/{name[0]}/{name}" if len(name) == 3 else f"{name[:2]}/{name[2:4]}/{name}")
        for index in sorted((registry / "index").glob("*")):
            if not index.is_dir() or index.is_symlink():
                continue
            for relative in ("config.json", ".cache/" + index_name, index_name):
                file = safe_path(index, relative)
                if file.is_file():
                    target = destination / "registry/index" / index.name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
        archives = list((registry / "cache").glob(f"*/{name}-{version}.crate"))
        for archive in archives:
            safe_path(source, archive.relative_to(source))
            target = destination / archive.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive, target)
        (copied if archives else missing).append(f"{name}-{version}")
    return {"source": str(source), "cached_crates": copied, "unavailable_crates": missing,
            "note": "Only existing registry archives and index entries were copied; no downloads."}
