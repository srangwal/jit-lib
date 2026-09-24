"""Build pinned application/library copies and run their existing test suites."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

from capture_index import instrument
from core import EvaluationError, inventory, sha256, write_json

ROOT = Path(__file__).resolve().parent


def output(commands, argv, cwd, env):
    return Path(commands(argv, cwd=cwd, env=env)["stdout"]).read_text()


def local_env(env):
    result = dict(env)
    # Upstream tests locate fixture binaries below the application's own target.
    result.pop("CARGO_TARGET_DIR", None)
    return result


def registry_packages(lockfile):
    return {(p["name"], p["version"], p.get("source"), p.get("checksum"))
            for p in tomllib.loads(Path(lockfile).read_text())["package"]
            if p.get("source") and p["name"] != "elasticlunr-rs"}


def check_dependency_lock(original, changed):
    before, after = registry_packages(original), registry_packages(changed)
    if before != after:
        raise EvaluationError(f"Non-library dependencies changed: removed={sorted(before-after)}, "
                              f"added={sorted(after-before)}")


def pinned_checkout(destination, pin, env, commands):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        commands(["git", "init", destination], cwd=destination.parent, env=env)
        commands(["git", "remote", "add", "origin", pin["url"]], cwd=destination, env=env)
        commands(["git", "fetch", "--depth", "1", "--no-tags", "origin", pin["revision"]],
                 cwd=destination, env=env)
        commands(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=destination, env=env)
    revision = output(commands, ["git", "rev-parse", "HEAD"], destination, env).strip()
    dirty = output(commands, ["git", "status", "--porcelain", "--untracked-files=all"],
                   destination, env).strip()
    if revision != pin["revision"] or dirty:
        raise EvaluationError(f"Cached source is not clean at pinned revision: {destination}")
    return destination


def snapshot(source, destination, *, candidate=False):
    """Copy current Git-visible files; candidate edits and untracked additions count."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    args = ["git", "-C", str(source), "ls-files", "--cached", "-z"]
    if candidate:
        args += ["--others", "--exclude-standard"]
    names = set(subprocess.check_output(args).decode().split("\0")) - {""}
    destination.mkdir(parents=True, exist_ok=False)
    for name in sorted(names):
        original, target = source / name, destination / name
        if candidate and not original.exists() and not original.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if original.is_symlink():
            target.symlink_to(os.readlink(original))
        elif original.is_file():
            shutil.copy2(original, target)
        else:
            raise EvaluationError(f"Unsupported source entry: {original}")
    if not (destination / "Cargo.toml").is_file():
        raise EvaluationError(f"Library/application root lacks Cargo.toml: {source}")


def use_library(application, library):
    path = application / "Cargo.toml"
    content = path.read_text()
    old = 'elasticlunr-rs = "3.0.2"'
    if content.count(old) != 1:
        raise EvaluationError("Application does not have the pinned elasticlunr dependency declaration")
    relative = os.path.relpath(library, application)
    path.write_text(content.replace(old, f'elasticlunr-rs = {{ path = {json.dumps(relative)} }}'))


def prepare_variants(cache_root, run_root, candidate_path_or_None, env, commands):
    cache_root, run_root = Path(cache_root).resolve(), Path(run_root).resolve()
    env = local_env(env)
    config = json.loads((ROOT / "config.json").read_text())
    sources = {kind: pinned_checkout(cache_root / "sources" / kind, config[kind], env, commands)
               for kind in ("application", "library")}
    host_info = output(commands, ["rustc", "-vV"], run_root, env)
    host = next(line.split(": ", 1)[1] for line in host_info.splitlines() if line.startswith("host: "))
    variants = {"host": host}
    for name in ("original", "candidate", "capture"):
        root = run_root / "variants" / name
        library, application = root / "library", root / "application"
        candidate = name == "candidate" and candidate_path_or_None is not None
        library_source = Path(candidate_path_or_None).resolve() if candidate else sources["library"]
        snapshot(library_source, library, candidate=candidate)
        snapshot(sources["application"], application)
        # Retain the submitted input manifest before adding evaluator test locks.
        source_manifest = inventory(library)
        write_json(root / "library-inputs.json", source_manifest)
        shutil.copy2(ROOT / "locks/library-tests.lock", library / "Cargo.lock")
        use_library(application, library)
        if name == "capture":
            instrument(application)
        metadata = json.loads(output(commands, ["cargo", "metadata", "--format-version", "1"],
                                     application, env))
        resolved = [p for p in metadata["packages"] if p["name"] == "elasticlunr-rs"]
        if len(resolved) != 1 or Path(resolved[0]["manifest_path"]).resolve() != library / "Cargo.toml":
            raise EvaluationError(f"{name}: Cargo did not resolve the intended library copy")
        for package in metadata["packages"]:
            path = Path(package["manifest_path"]).resolve()
            if package["source"] is None and not (path.is_relative_to(application) or path.is_relative_to(library)):
                raise EvaluationError(f"Dependency outside source snapshot: {path}")
        check_dependency_lock(sources["application"] / "Cargo.lock", application / "Cargo.lock")
        commands(["cargo", "build", "--release", "--locked", "--bin", "mdbook"], cwd=application, env=env)
        binary = application / "target/release/mdbook"
        provenance = {
            "application_revision": config["application"]["revision"],
            "library_revision": None if candidate else config["library"]["revision"],
            "library_source": str(library_source), "library_inputs": str(root / "library-inputs.json"),
            "binary_sha256": sha256(binary), "application_lock_sha256": sha256(application / "Cargo.lock"),
            "library_test_lock_sha256": sha256(library / "Cargo.lock"),
            "capture_instrumentation": name == "capture",
        }
        write_json(root / "provenance.json", provenance)
        variants[name] = {"application": application, "library": library, "binary": binary,
                          "provenance": provenance, "host": host}
    return variants


def setup_gui(cache_root, env, commands):
    browser = env.get("PUPPETEER_EXECUTABLE_PATH")
    if not browser or not Path(browser).is_file():
        raise EvaluationError("Set PUPPETEER_EXECUTABLE_PATH to an installed Chrome/Chromium executable")
    root = Path(cache_root).resolve() / "gui"
    root.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(ROOT / "gui" / name, root / name)
    commands(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root, env=env)
    return root


def run_suites(variant, env, commands, gui_root):
    env = local_env(env)
    app, library, host = variant["application"], variant["library"], variant["host"]
    node_modules = app / "node_modules"
    node_modules.symlink_to(Path(gui_root).resolve() / "node_modules", target_is_directory=True)
    results = {}
    for name, args, cwd in (
        ("application", ["cargo", "test", "--workspace", "--locked", "--target", host], app),
        ("application_no_default", ["cargo", "test", "--workspace", "--locked", "--no-default-features", "--target", host], app),
        ("application_gui", ["cargo", "test", "--locked", "--target", host, "--test", "gui"], app),
        ("library", ["cargo", "test", "--locked", "--target", host], library),
    ):
        results[name] = commands(args, cwd=cwd, env=env)
    return results
