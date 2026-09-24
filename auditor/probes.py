"""Run self-contained differential books without exposing reference evidence."""

import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import tomllib

from evaluator.core import differences, inventory, write_json


def validate_probe(probe):
    if not isinstance(probe, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", probe.get("id", "")):
        raise ValueError("Probe id must be a lowercase slug")
    if not isinstance(probe.get("hypothesis"), str) or not probe["hypothesis"].strip():
        raise ValueError("Probe needs a hypothesis")
    files = probe.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 100:
        raise ValueError("Probe must contain 1 to 100 files")
    contents = {}
    total = 0
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
            raise ValueError("Each file needs string path and content")
        name = item["path"]
        path = PurePosixPath(name)
        if (path.is_absolute() or not path.parts or "\\" in name or "\0" in name or
                any(part.startswith(".") for part in name.split("/")) or
                path.as_posix() != name or name in contents or
                (name != "book.toml" and path.parts[0] != "src")):
            raise ValueError(f"Unsafe or duplicate book path: {name}")
        if path.suffix not in {".md", ".toml", ".txt", ".html", ".css", ".js", ".json", ".svg", ".rs"}:
            raise ValueError(f"Unsupported probe file type: {name}")
        total += len(item["content"].encode())
        if total > 1_000_000:
            raise ValueError("Probe inputs exceed one megabyte")
        contents[name] = item["content"]
    if not {"book.toml", "src/SUMMARY.md"} <= contents.keys():
        raise ValueError("Probe requires book.toml and src/SUMMARY.md")
    config = tomllib.loads(contents["book.toml"])
    if set(config) - {"book", "output", "build", "rust"}:
        raise ValueError("Only book, output, build, and rust configuration is supported")
    if "preprocessor" in config or set(config.get("output", {})) - {"html"}:
        raise ValueError("Custom preprocessors and renderers are not supported")
    if config.get("book", {}).get("src", "src") != "src":
        raise ValueError("Probe source directory must be src")
    if "command" in config.get("output", {}).get("html", {}):
        raise ValueError("Renderer commands are not supported")
    _validate_containment(contents, config)
    return contents


def _validate_containment(contents, config):
    """Promoted fixtures must remain self-contained outside the probe sandbox."""
    def contained(target, base="src"):
        if not isinstance(target, str) or "\\" in target or "\0" in target or ":" in target or target.startswith("/"):
            raise ValueError(f"Unsupported book reference: {target}")
        resolved = posixpath.normpath(posixpath.join(base, target))
        if not resolved.startswith("src/") or resolved not in contents:
            raise ValueError(f"Book reference must name a supplied file inside src: {target}")

    if set(config.get("build", {})) - {"create-missing", "use-default-preprocessors"}:
        raise ValueError("Build paths and extra watch directories are unsupported")
    html = config.get("output", {}).get("html", {})
    if "theme" in html or "redirect" in html:
        raise ValueError("Custom themes and redirects are unsupported in audit probes")
    for key in ("additional-css", "additional-js"):
        if not isinstance(html.get(key, []), list):
            raise ValueError(f"{key} must be a list of supplied files")
        for target in html.get(key, []):
            contained(target, "")
    if html.get("input-404"):
        contained(html["input-404"])
        if ".." in PurePosixPath(html["input-404"]).parts:
            raise ValueError("input-404 must not contain parent-directory components")
    # Restrict SUMMARY syntax instead of approximating Markdown's link parser.
    for line in contents["src/SUMMARY.md"].splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line.strip() == "---":
            continue
        match = re.fullmatch(r"\s*[-+*]\s+\[[^\]]*\]\(([^()\s]*)\)\s*", line)
        if not match:
            raise ValueError("SUMMARY must use simple '- [Title](file.md)' chapter links")
        if match[1]:
            contained(match[1])
    for name, content in contents.items():
        if name == "book.toml":
            continue
        for directive in re.finditer(r"\{\{\s*#\s*(include|rustdoc_include|playground|playpen)\s+([^}\s]+)", content):
            contained(directive[2].split(":", 1)[0], posixpath.dirname(name))


def sandbox_profile(scratch, executable, protected_roots):
    """Seatbelt isolation on macOS; no unsandboxed fallback."""
    quote = lambda path: json.dumps(str(Path(path).resolve()))
    roots = ["/Users", "/Volumes", "/private/tmp", "/private/var/folders", *protected_roots]
    protected = " ".join(f"(subpath {quote(root)})" for root in roots)
    return ("(version 1)(allow default)(deny network*)"
            f"(deny file-write* (require-not (subpath {quote(scratch)})))"
            f"(deny file-read-data (require-all (require-any {protected}) "
            f"(require-not (subpath {quote(scratch)}))))"
            f"(deny process-exec (require-not (literal {quote(executable)})))"
            "(deny process-fork)")


def _output_inventory(output):
    if output.is_symlink():
        raise ValueError("Output root must not be a symlink")
    total = 0
    for count, path in enumerate(output.rglob("*"), 1):
        metadata = path.lstat()
        mode = metadata.st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("Output contains a symlink or special file")
        if stat.S_ISREG(mode) and metadata.st_nlink > 1:
            raise ValueError("Output contains a hard link")
        total += metadata.st_size if stat.S_ISREG(mode) else 0
        if count > 5000 or total > 100_000_000:
            raise ValueError("Output exceeds probe evidence limits")
    return inventory(output)


def _execute(binary, contents, destination, protected_roots, timeout):
    destination.mkdir(parents=True)
    result = {"evidence": str(destination)}
    with tempfile.TemporaryDirectory(prefix="jit-audit-probe-") as temp:
        scratch = Path(temp).resolve()
        executable = scratch / "mdbook"
        shutil.copy2(binary, executable)
        executable.chmod(0o700)
        book = scratch / "book"
        for name, content in contents.items():
            path = book / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        output = scratch / "output"
        profile = sandbox_profile(scratch, executable, protected_roots)
        (destination / "sandbox.sb").write_text(profile)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(scratch), "TMPDIR": str(scratch), "TZ": "UTC"}
        argv = ["/usr/bin/sandbox-exec", "-p", profile, str(executable), "build", str(book), "--dest-dir", str(output)]
        result["argv"] = argv
        with (destination / "stdout.log").open("wb") as stdout, (destination / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(argv, cwd=scratch, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                result["exit_code"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                result.update(exit_code=process.returncode, timed_out=True)
            except BaseException:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
        if result["exit_code"] == 0:
            try:
                result["inventory"] = _output_inventory(output)
                shutil.copytree(output, destination / "output")
            except (ValueError, RuntimeError, OSError) as error:
                result["output_error"] = str(error)
        write_json(destination / "result.json", result)
    return result


def run_probe(probe, binaries, evidence_dir, protected_roots, timeout=30):
    """Compare two repeatable original builds with two isolated candidate builds."""
    result = {key: probe.get(key) for key in ("id", "hypothesis", "requirement", "code_references")}
    result.update(status="invalid", runs=[])
    try:
        contents = validate_probe(probe)
    except (ValueError, TypeError, AttributeError) as error:
        result["reason"] = str(error)
        return result
    if not Path("/usr/bin/sandbox-exec").is_file():
        result.update(status="inconclusive", reason="macOS sandbox-exec is required; probe was not executed")
        return result
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    write_json(evidence_dir / "probe.json", probe)
    protected_roots = [*protected_roots, evidence_dir]
    for variant in ("original", "candidate"):
        for repetition in (1, 2):
            record = _execute(Path(binaries[variant]), contents, evidence_dir / f"{variant}-{repetition}", protected_roots, timeout)
            result["runs"].append({"variant": variant, "repetition": repetition, **record})
        first, second = result["runs"][-2:]
        if variant == "original":
            if any(run.get("exit_code") != 0 or "inventory" not in run for run in (first, second)):
                result.update(status="inconclusive", reason="Original could not build a valid output twice")
                break
            if first["inventory"] != second["inventory"]:
                result.update(status="inconclusive", reason="Original output is not repeatable")
                break
            expected = first["inventory"]
        else:
            if any(run.get("timed_out") for run in (first, second)):
                result.update(status="inconclusive", reason="Candidate timed out; no correctness finding established")
            elif first.get("exit_code") != second.get("exit_code") or first.get("inventory") != second.get("inventory") or first.get("output_error") != second.get("output_error"):
                result.update(status="inconclusive", reason="Candidate result is not repeatable")
            elif first["exit_code"] != 0 or "inventory" not in first:
                result.update(status="reproduced", reason="Candidate failed twice on an input the original builds")
            else:
                result["differences"] = differences(expected, first["inventory"])
                changed = any(result["differences"].values())
                result.update(status="reproduced" if changed else "not_reproduced",
                              reason="Candidate output differs twice" if changed else "Both candidate outputs match the original")
    write_json(evidence_dir / "result.json", result)
    return result
