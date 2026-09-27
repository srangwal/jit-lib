"""File comparisons, command records, and paired timing analysis."""

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
import statistics
import subprocess
import threading
import time

if __package__:
    from .environment import build_overrides, cargo_configs, validate_cargo_settings
else:
    from environment import build_overrides, cargo_configs, validate_cargo_settings


class EvaluationError(RuntimeError):
    pass


class CorrectnessError(EvaluationError):
    pass


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def record_progress(directory, phase, **details):
    """Machine-readable phase evidence; console messages are only for convenience."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "progress.jsonl").open("a") as handle:
        handle.write(json.dumps({"schema_version": "component-progress/v1",
                                 "timestamp": datetime.now(timezone.utc).isoformat(),
                                 "phase": phase, **details}, sort_keys=True) + "\n")


def sha256(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def evaluator_fingerprint(root=None):
    """Identify the harness and permanent fixtures used for a run."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    files = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if set(relative.parts) & {"__pycache__", "target", "node_modules", ".git"}:
            continue
        if path.is_symlink():
            raise EvaluationError(f"Symlink evaluator source: {path}")
        if path.is_file() and (path.suffix in {".py", ".json", ".toml", ".rs", ".md", ".lock"}
                               or "fixtures" in relative.parts or "locks" in relative.parts):
            files[relative.as_posix()] = sha256(path)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"sha256": digest, "files": files}


def inventory(root):
    """Compare relative names and bytes, not timestamps or filesystem ordering."""
    root = Path(root)
    if not root.is_dir():
        raise CorrectnessError(f"Missing output directory: {root}")
    files = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise CorrectnessError(f"Unexpected symlink in output: {path}")
        if path.is_file():
            files[name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    if not files:
        raise CorrectnessError(f"Empty output directory: {root}")
    return files


def differences(expected, actual):
    return {
        "missing": sorted(expected.keys() - actual.keys()),
        "extra": sorted(actual.keys() - expected.keys()),
        "changed": sorted(key for key in expected.keys() & actual.keys()
                          if expected[key] != actual[key]),
    }


def compare(expected, actual, record):
    diff = differences(expected, actual)
    write_json(record, diff)
    if any(diff.values()):
        raise CorrectnessError(f"Generated output differs; see {record}")


class Commands:
    """Run commands without a shell; persist failures and externally timed duration."""

    def __init__(self, directory, timeout=1200):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.sequence = 0

    def __call__(self, argv, *, cwd, env):
        self.sequence += 1
        stem = self.directory / f"{self.sequence:04d}"
        argv = list(map(str, argv))
        if Path(argv[0]).name == "cargo":
            validate_cargo_settings(env, Path(cwd).resolve())
        record = {
            "argv": argv, "cwd": str(cwd),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "environment": {**build_overrides(env), **{key: env[key] for key in (
                "CARGO_HOME", "CARGO_TARGET_DIR", "CARGO_NET_OFFLINE", "RUSTUP_TOOLCHAIN",
                "RUSTFLAGS", "TZ", "SOURCE_DATE_EPOCH", "CARGO_INCREMENTAL",
                "CARGO_ENCODED_RUSTFLAGS", "RUSTDOCFLAGS", "RUSTC", "RUSTDOC",
                "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CC", "CFLAGS",
                "CXX", "CXXFLAGS", "LDFLAGS", "npm_config_cache",
                "PUPPETEER_EXECUTABLE_PATH", "JIT_LIB_INDEX_TRACE",
            ) if key in env}},
            "cargo_config_sha256": cargo_configs(env, Path(cwd).resolve()),
            "stdout": str(stem.with_suffix(".stdout.log")),
            "stderr": str(stem.with_suffix(".stderr.log")),
        }
        print(f"[{self.sequence:04d}] {' '.join(argv)}", flush=True)
        started = time.perf_counter()
        process = None
        timed_out = threading.Event()
        watchdog = None
        try:
            with stem.with_suffix(".stdout.log").open("wb") as out, \
                    stem.with_suffix(".stderr.log").open("wb") as err:
                process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out,
                                           stderr=err, start_new_session=True)
                def expire():
                    if process.poll() is None:
                        timed_out.set()
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                watchdog = threading.Timer(self.timeout, expire)
                watchdog.daemon = True
                watchdog.start()
                try:
                    # Blocking wait avoids timeout polling adding up to 50 ms
                    # to these short book builds. The watchdog enforces timeout.
                    record["exit_code"] = process.wait()
                    if timed_out.is_set():
                        raise subprocess.TimeoutExpired(argv, self.timeout)
                except KeyboardInterrupt:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            record["error"] = str(error) or type(error).__name__
            raise EvaluationError(f"Command did not finish: {argv}; logs at {stem}") from error
        finally:
            if watchdog:
                watchdog.cancel()
            record["elapsed_seconds"] = time.perf_counter() - started
            write_json(stem.with_suffix(".json"), record)
        if record["exit_code"]:
            tail = stem.with_suffix(".stderr.log").read_text(errors="replace")[-3000:]
            raise EvaluationError(f"Command exited {record['exit_code']}: {argv}\n{tail}\nLogs: {stem}")
        return record


def percentile(values, fraction):
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def paired_summary(pairs, resamples=10000, seed=20260924):
    """A fixed paired bootstrap over complete blocks; speedup is original / candidate."""
    if len(pairs) < 3:
        raise EvaluationError("At least three paired timing blocks are required")
    if any(not math.isfinite(x) or x <= 0 for pair in pairs for x in pair):
        raise EvaluationError("All durations must be positive and finite")
    logs = [math.log(original / candidate) for original, candidate in pairs]
    rng = random.Random(seed)
    bootstrap = sorted(math.exp(statistics.fmean(rng.choices(logs, k=len(logs))))
                       for _ in range(resamples))
    lo, hi = percentile(bootstrap, .025), percentile(bootstrap, .975)
    return {
        "pairs": len(pairs),
        "original_median_seconds": statistics.median(p[0] for p in pairs),
        "candidate_median_seconds": statistics.median(p[1] for p in pairs),
        "speedup": math.exp(statistics.fmean(logs)),
        "confidence_interval_95": [lo, hi],
        "time_reduction_percent": 100 - 100 / math.exp(statistics.fmean(logs)),
        "time_reduction_confidence_interval_95": [100 - 100 / lo, 100 - 100 / hi],
        "verdict": "improved" if lo > 1 else "slower" if hi < 1 else "inconclusive",
    }


def self_check_calibration(aggregate):
    """Allow up to 5% aggregate time difference relative to the original."""
    tolerance = 5
    metrics = {}
    for name in ("application", "index"):
        speedup = aggregate[name]["speedup"]
        # Ratio bounds avoid rounding the inclusive +/-5% percentage boundaries.
        metrics[name] = {
            "time_reduction_percent": 100 - 100 / speedup,
            "within_tolerance": 1 / (1 + tolerance / 100) <= speedup <= 1 / (1 - tolerance / 100),
        }
    return {
        "criterion": "self-check-point-difference/v1",
        "tolerance_percent": tolerance,
        "time_reduction_formula": "100 * (1 - 1 / speedup_ratio)",
        "metrics": metrics,
        "passed": all(value["within_tolerance"] for value in metrics.values()),
    }


def validate_library_reduction_target(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < 100:
        raise EvaluationError("library reduction target must be finite and in [0, 100) percent")
    return float(value)


def library_qualification(index_metric, target):
    """Qualify library work; application results remain separate observations."""
    target = validate_library_reduction_target(target)
    lo, hi = index_metric["confidence_interval_95"]
    # Compare ratios to avoid cancellation rounding at exact percentage targets.
    meets_target = lo > 1 and lo >= 1 / (1 - target / 100)
    return {
        "criterion": "library-time-reduction/v1",
        "library_reduction_target_percent": target,
        "time_reduction_percent": 100 - 100 / index_metric["speedup"],
        "time_reduction_confidence_interval_95": [100 - 100 / lo, 100 - 100 / hi],
        "meets_target": meets_target,
        "verdict": "improved" if meets_target else "slower" if hi < 1 else "inconclusive",
    }


def analyse(samples, book_ids, repetitions, resamples, seed, library_reduction_target_percent=20):
    validate_library_reduction_target(library_reduction_target_percent)
    by_key = {}
    for sample in samples:
        key = (sample["book"], sample["metric"], sample["block"], sample["variant"])
        if key in by_key:
            raise EvaluationError(f"Duplicate timing: {key}")
        by_key[key] = sample["seconds"]
    result = {"books": {}, "aggregate": {}}
    for metric in ("application", "index"):
        all_pairs = []
        for book in book_ids:
            try:
                pairs = [(by_key[book, metric, block, "original"],
                          by_key[book, metric, block, "candidate"])
                         for block in range(repetitions)]
            except KeyError as error:
                raise EvaluationError(f"Missing timing: {error}") from error
            result["books"].setdefault(book, {})[metric] = paired_summary(pairs, resamples, seed)
            all_pairs.append(pairs)
        # Equal book weights. Resampling a whole block retains its cross-book pairing.
        aggregate_pairs = [tuple(math.exp(statistics.fmean(math.log(pairs[block][v])
                                                           for pairs in all_pairs))
                                 for v in (0, 1)) for block in range(repetitions)]
        result["aggregate"][metric] = paired_summary(aggregate_pairs, resamples, seed)
    result["performance_policy"] = library_qualification(
        result["aggregate"]["index"], library_reduction_target_percent)
    result["verdict"] = result["performance_policy"]["verdict"]
    return result


def markdown_report(report):
    lines = ["# Evaluation report", "", f"Status: **{report['status']}**", "",
             f"Run: `{report['run']}`", ""]
    if "error" in report:
        lines += ["Error:", "", str(report["error"]), ""]
    if "calibration" in report:
        lines += [report["calibration"], ""]
    if "analysis" in report:
        policy = report["analysis"].get("performance_policy")
        if policy and report.get("mode") != "self-check":
            lo, hi = policy["time_reduction_confidence_interval_95"]
            lines += [
                f"Library time-reduction target: **{policy['library_reduction_target_percent']:g}%**. "
                "The lower 95% confidence bound must meet this target and exceed measurement noise.", "",
                f"Measured library time reduction: **{policy['time_reduction_percent']:.2f}%** "
                f"(95% interval: {lo:.2f}–{hi:.2f}%). "
                f"Target met: **{'yes' if policy['meets_target'] else 'no'}**.", "",
                "Application performance is reported separately and does not block library success. "
                "Final acceptance also requires correctness and an audit with no unresolved issue.", "",
            ]
        lines += ["Speedup is original time / candidate time. Values above 1 favor the candidate.", "",
                  "| Book | Book-build speedup (95% interval) | Index speedup (95% interval) |",
                  "| --- | --- | --- |"]
        results = {**report["analysis"]["books"], "Aggregate (equal book weights)": report["analysis"]["aggregate"]}
        for book, metrics in results.items():
            values = []
            for metric in ("application", "index"):
                value = metrics[metric]
                lo, hi = value["confidence_interval_95"]
                values.append(f"{value['speedup']:.3f}× ({lo:.3f}–{hi:.3f}); {value['verdict']}")
            lines.append(f"| {book} | {' | '.join(values)} |")
        lines += ["", "Intervals describe repeated-timing uncertainty for these books on this machine. "
                  "They do not establish performance on other books or protect against machine drift. "
                  "The aggregate verdict can coexist with individual-book regressions; inspect every row.", ""]
    lines += ["Exact commands, logs, source and output manifests, and raw timings accompany report.json.", ""]
    return "\n".join(lines)
