#!/usr/bin/env python3
"""Compare mdBook builds and replay indexing against two library snapshots."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import tomllib

from builds import prepare_variants, registry_packages, run_suites, setup_gui
from capture_index import prepare_replay
from core import (Commands, CorrectnessError, EvaluationError, analyse, compare,
                  evaluator_fingerprint, inventory, markdown_report, sha256, write_json)
from prepare_books import prepare_book
from environment import build_environment, runtime_info

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VARIANTS = ("original", "candidate")


def validate_checker(root):
    """Exercise actual changed, missing and extra files, not just mocked hashes."""
    root.mkdir()
    tree = root / "output"
    tree.mkdir()
    (tree / "index.html").write_text("original page")
    (tree / "searchindex.js").write_text("original index")
    expected = inventory(tree)
    compare(expected, inventory(tree), root / "identical.json")
    for mutation in ("changed", "missing", "extra"):
        index = tree / "searchindex.js"
        index.write_text("wrong index" if mutation == "changed" else "original index")
        if mutation == "missing":
            index.unlink()
        if mutation == "extra":
            (tree / "unexpected.html").write_text("unexpected")
        try:
            compare(expected, inventory(tree), root / f"{mutation}.json")
        except CorrectnessError:
            pass
        else:
            raise EvaluationError(f"Correctness checker accepted {mutation} output")
    shutil.rmtree(tree)
    return {"identical_accepted": True, "changed_rejected": True,
            "missing_rejected": True, "extra_rejected": True}


def book_build(binary, book, output, commands, *, trace=None):
    # Always start with an absent destination; cleaning is outside the timer.
    if output.exists():
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    env = dict(book["env"])
    if trace is not None:
        env["JIT_LIB_INDEX_TRACE"] = str(trace)
    return commands([binary, "build", book["root"], "--dest-dir", output],
                    cwd=book["root"], env=env)


def index_replay(binary, trace, output, expected, commands, env):
    record = commands([binary, trace, output], cwd=binary.parent, env=env)
    result = json.loads(Path(record["stdout"]).read_text())
    if output.read_bytes() != expected:
        raise CorrectnessError(f"Replayed search index differs: {output}")
    seconds = result["elapsed_seconds"]
    if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds <= 0:
        raise EvaluationError(f"Invalid index duration: {seconds}")
    if result["output_bytes"] != len(expected):
        raise CorrectnessError("Replay reported an incorrect output size")
    return seconds, record


def input_manifest(root):
    """Hash prepared book inputs; exclude only the known preprocessor build dir."""
    return {p.relative_to(root).as_posix(): sha256(p)
            for p in sorted(root.rglob("*"))
            if ".cargo-target" not in p.relative_to(root).parts and p.is_file()}


def execute(args, run, report, commands, env):
    config = report["configuration"]
    report["checker_validation"] = validate_checker(run / "checker-validation")
    for command in (["rustc", "-vV"], ["cargo", "--version"], ["node", "--version"],
                    ["npm", "--version"]):
        commands(command, cwd=run, env=env)
    gui = setup_gui(args.cache, env, commands)
    variants = prepare_variants(args.cache, run, args.candidate, env, commands)
    report["variants"] = {name: variants[name]["provenance"] for name in (*VARIANTS, "capture")}
    report["suites"] = {}
    for name in VARIANTS:
        report["suites"][name] = run_suites(variants[name], env, commands, gui)
        replay_root = run / "variants" / name / "replay"
        prepare_replay(replay_root, variants[name]["library"],
                       variants[name]["application"] / "Cargo.lock")
        commands(["cargo", "build", "--release"], cwd=replay_root, env=env)
        extra = registry_packages(replay_root / "Cargo.lock") - registry_packages(
            variants[name]["application"] / "Cargo.lock")
        if extra:
            raise EvaluationError(f"Replay dependencies differ from application: {sorted(extra)}")
        commands(["cargo", "test", "--locked"], cwd=replay_root, env=env)
        variants[name]["replay"] = replay_root / "target/release/index-replay"
        variants[name]["provenance"]["replay_binary_sha256"] = sha256(variants[name]["replay"])
        variants[name]["provenance"]["replay_lock_sha256"] = sha256(replay_root / "Cargo.lock")

    # All compilation and preprocessing preparation finishes before any timings.
    entries = json.loads((HERE / "books.json").read_text())
    if args.books:
        selected = set(args.books.split(","))
        unknown = selected - {entry["id"] for entry in entries}
        if unknown:
            raise EvaluationError(f"Unknown book IDs: {sorted(unknown)}")
        entries = [entry for entry in entries if entry["id"] in selected]
    write_json(run / "books.json", entries)
    books = {}
    for entry in entries:
        destination = run / "books" / entry["id"]
        root, book_env = prepare_book(entry, REPO / "workloads/books", destination, env, commands)
        books[entry["id"]] = {"root": root, "env": book_env, "inputs": destination,
                               "performance": True, "search": True}
    for source in sorted((HERE / "fixtures").iterdir()):
        if not source.is_dir():
            continue
        destination = run / "books" / f"fixture-{source.name}"
        shutil.copytree(source, destination)
        fixture_config = tomllib.loads((destination / "book.toml").read_text())
        books[f"fixture-{source.name}"] = {
            "root": destination, "inputs": destination, "env": env,
            "performance": False,
            "search": fixture_config.get("output", {}).get("html", {}).get("search", {}).get("enable", True),
        }
    input_hashes = {name: input_manifest(book["inputs"]) for name, book in books.items()}
    write_json(run / "book-inputs.json", input_hashes)

    correctness = {}
    for name, book in books.items():
        print(f"Correctness: {name}", flush=True)
        root = run / "correctness" / name
        original_output = root / "original"
        book_build(variants["original"]["binary"], book, original_output, commands)
        expected = inventory(original_output)
        write_json(root / "expected.json", expected)
        for label, variant in (("repeat", "original"), ("candidate", "candidate"), ("capture", "capture")):
            trace = root / "trace.json" if label == "capture" else None
            book_build(variants[variant]["binary"], book, root / label, commands, trace=trace)
            compare(expected, inventory(root / label), root / f"{label}-comparison.json")
        trace = root / "trace.json"
        if trace.is_file() != book["search"]:
            raise CorrectnessError(f"{name}: unexpected presence/absence of search-index trace")
        if book["search"]:
            captured = json.loads(trace.read_text())
            expected_index = captured["expected_output"].encode()
            if captured["copy_js"]:
                assets = list(original_output.glob("searchindex*.js"))
                if len(assets) != 1 or assets[0].read_bytes() != expected_index:
                    raise CorrectnessError(f"{name}: trace differs from actual search-index asset")
            for variant in VARIANTS:
                index_replay(variants[variant]["replay"], trace, root / f"{variant}-index",
                             expected_index, commands, env)
            book.update(trace=trace, expected_index=expected_index)
        book["expected"] = expected
        correctness[name] = {"files": len(expected), "repeat_identical": True,
                             "candidate_identical": True, "capture_identical": True,
                             "index_replay_identical": book["search"]}
    report["correctness"] = correctness
    write_json(run / "correctness.json", correctness)

    def measure(book_id, variant, metric, label):
        book = books[book_id]
        work = run / "timing-work" / book_id
        work.mkdir(parents=True, exist_ok=True)
        if metric == "application":
            output = work / variant
            record = book_build(variants[variant]["binary"], book, output, commands)
            compare(book["expected"], inventory(output),
                    run / "timing-checks" / f"{label}-{book_id}-{variant}-{metric}.json")
            seconds = record["elapsed_seconds"]
        else:
            seconds, record = index_replay(variants[variant]["replay"], book["trace"],
                                          work / f"{variant}-index", book["expected_index"], commands, env)
        return {"book": book_id, "variant": variant, "metric": metric,
                "seconds": seconds, "command_stdout": record["stdout"]}

    book_ids = [entry["id"] for entry in entries]
    for block in range(config["warmups"]):
        for book_id in book_ids:
            for metric in ("application", "index"):
                for variant in VARIANTS:
                    measure(book_id, variant, metric, f"warmup-{block}")
    samples = []
    for block in range(config["repetitions"]):
        print(f"Timing block {block + 1}/{config['repetitions']}", flush=True)
        order = VARIANTS if block % 2 == 0 else tuple(reversed(VARIANTS))
        for book_id in book_ids:
            for metric in ("application", "index"):
                for variant in order:
                    sample = measure(book_id, variant, metric, f"block-{block}")
                    sample["block"] = block
                    samples.append(sample)
                    write_json(run / "timings.json", samples)
    for name, book in books.items():
        if input_hashes[name] != input_manifest(book["inputs"]):
            raise CorrectnessError(f"Prepared book inputs changed during evaluation: {name}")
    for name in (*VARIANTS, "capture"):
        if sha256(variants[name]["binary"]) != report["variants"][name]["binary_sha256"]:
            raise CorrectnessError(f"Application binary changed during evaluation: {name}")
    report["analysis"] = analyse(samples, book_ids, config["repetitions"],
                                  config["bootstrap_resamples"], config["bootstrap_seed"])
    if args.mode == "self-check":
        report["status"] = ("validated" if all(metric["verdict"] == "inconclusive"
                                             for metric in report["analysis"]["aggregate"].values())
                            else "calibration-warning")
        report["calibration"] = (
            "Original versus original: no real speedup is possible. An interval excluding 1 "
            "indicates timing bias or a statistical false positive; investigate before accepting candidates."
        )
    else:
        report["status"] = report["analysis"]["verdict"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "self-check"))
    parser.add_argument("--candidate", type=Path, help="elasticlunr-rs Git checkout including local edits")
    parser.add_argument("--books", help="comma-separated IDs; default all ten, subset is recorded")
    parser.add_argument("--cache", type=Path, default=REPO / ".evaluator")
    parser.add_argument("--cargo-home", type=Path)
    parser.add_argument("--browser", type=Path, help="installed Chrome/Chromium executable")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--warmups", type=int)
    args = parser.parse_args()
    if (args.mode == "run") != (args.candidate is not None):
        parser.error("run requires --candidate; self-check compares original against original")
    config = json.loads((HERE / "config.json").read_text())
    for field in ("repetitions", "warmups"):
        value = getattr(args, field)
        if value is not None:
            config[field] = value
    if config["repetitions"] < 3 or config["warmups"] < 0:
        parser.error("require at least 3 repetitions and a nonnegative warmup count")
    if args.books:
        ids = {entry["id"] for entry in json.loads((HERE / "books.json").read_text())}
        if not set(args.books.split(",")) <= ids:
            parser.error("unknown --books IDs; see evaluator/books.json")
    args.cache = args.cache.resolve()
    run = args.cache / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run.mkdir(parents=True, exist_ok=False)
    report = {"run": str(run), "mode": args.mode, "status": "incomplete",
              "configuration": config, "python": sys.version, "platform": platform.platform(),
              "invocation": sys.argv, "selected_books": args.books or "all ten",
              "evaluator_version": evaluator_fingerprint()}
    write_json(run / "configuration.json", report)
    commands = Commands(run / "commands", config["command_timeout_seconds"])
    print(f"Evidence and report: {run}", flush=True)
    try:
        removed = {}
        env = build_environment(os.environ, args.cargo_home, args.browser,
                                removed_overrides=removed)
        report["environment"] = runtime_info(env, cwd=run)
        report["environment"]["removed_overrides"] = removed
        write_json(run / "configuration.json", report)
        execute(args, run, report, commands, env)
        if evaluator_fingerprint() != report["evaluator_version"]:
            raise EvaluationError("Evaluator or fixtures changed during the run; rerun with a fixed version")
    except (Exception, KeyboardInterrupt) as error:
        report["status"] = "correctness-failed" if isinstance(error, CorrectnessError) else "incomplete"
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    finally:
        write_json(run / "report.json", report)
        (run / "report.md").write_text(markdown_report(report))
    print(f"Status: {report['status']}. Report: {run / 'report.md'}")
    return 1 if report["status"] in ("incomplete", "correctness-failed", "calibration-warning") else 0


if __name__ == "__main__":
    sys.exit(main())
