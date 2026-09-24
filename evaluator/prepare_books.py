"""Prepare pinned book copies without modifying the upstream checkouts."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib


def prepare_book(entry, source_root, work_root, env, command_runner):
    """Return (book_root, environment) after building configured preprocessors.

    ``work_root`` must not exist. ``command_runner(argv, *, cwd, env)`` must
    raise on nonzero exit and should retain its command and output in run logs.
    Preparation is excluded from book-build timings. Configured preprocessors
    still run normally during each build, using their already compiled binaries.
    """
    source = Path(source_root).resolve() / entry["checkout"]
    destination = Path(work_root).resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != entry["revision"]:
        raise ValueError(f"{entry['id']}: expected {entry['revision']}, got {revision}")
    status = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"],
        text=True,
    ).strip()
    if status:
        raise ValueError(f"{entry['id']}: checkout is not clean:\n{status}")
    if destination.exists():
        raise FileExistsError(destination)

    # Copy precisely the committed tree: ignored output and nested Git metadata
    # cannot become accidental evaluator inputs. Preserve symlinks and modes.
    tracked = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "-z"]
    ).decode().split("\0")
    destination.mkdir(parents=True)
    for relative in filter(None, tracked):
        original = source / relative
        copied = destination / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        if original.is_symlink():
            copied.symlink_to(os.readlink(original))
        elif original.is_file():
            shutil.copy2(original, copied)
        else:
            raise ValueError(f"Unsupported tracked input: {original}")

    prepared_env = dict(env)
    prepared_env["CARGO_TARGET_DIR"] = str(destination / ".cargo-target")
    # Some books request a moving nightly; use the caller's explicitly chosen
    # toolchain so preparation and subsequent timed builds use the same compiler.
    prepared_env.setdefault("RUSTUP_TOOLCHAIN", "stable")
    book_root = destination / entry["book_root"]
    config = book_root / "book.toml"
    original_config = config.read_bytes()
    transformations = []
    if entry.get("compatibility") == "legacy-author":
        parsed = tomllib.loads(original_config.decode())
        book_config = parsed["book"]
        if "authors" in book_config or not isinstance(book_config.get("author"), str):
            raise ValueError("Expected one legacy book.author string and no book.authors")
        old_line = 'author = ' + json.dumps(book_config["author"], ensure_ascii=False)
        new_line = 'authors = [' + json.dumps(book_config["author"], ensure_ascii=False) + ']'
        lines = original_config.decode().splitlines(keepends=True)
        matching = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == old_line]
        if len(matching) != 1:
            raise ValueError("Legacy author field does not match the pinned configuration")
        lines[matching[0]] = new_line + "\n"
        config.write_text("".join(lines))
        transformations.append({"file": "book.toml", "before": old_line, "after": new_line})
    provenance = {
        "id": entry["id"], "source_revision": revision,
        "config_sha256_before": hashlib.sha256(original_config).hexdigest(),
        "config_sha256_after": hashlib.sha256(config.read_bytes()).hexdigest(),
        "transformations": transformations,
        "preparation_commands": entry["prepare"],
        "rustup_toolchain": prepared_env["RUSTUP_TOOLCHAIN"],
    }
    (destination / "preparation.json").write_text(json.dumps(provenance, indent=2) + "\n")
    for command in entry["prepare"]:
        command_runner(command, cwd=book_root, env=prepared_env)
    prepared_env["CARGO_NET_OFFLINE"] = "true"
    return book_root, prepared_env
