# mdBook evaluator

Compare mdBook 0.5.4 using original elasticlunr-rs 3.0.2 with the same
application using a modified library. Code lives here; downloaded sources,
compiled binaries, and results live in the ignored `.evaluator/` directory.

## Run it

Follow the [root setup guide](../README.md). Requires Python 3.11+, Git,
Rust 1.95.0 through rustup, Node 24+, npm, and installed Chrome/Chromium.
Run `python3 evaluator/setup_books.py` to acquire the ten pinned books.
Initial preparation downloads pinned application/library sources and dependencies.

```sh
# Check the evaluator using original versus original.
python3 evaluator/run.py self-check --browser /path/to/chrome

# Evaluate a Git checkout of the modified elasticlunr-rs library.
python3 evaluator/run.py run --candidate /path/to/elasticlunr-rs --browser /path/to/chrome

# Test the evaluator's Python code without compiling upstream projects.
python3 -m unittest discover -s evaluator/tests -v
```

On macOS, a typical browser path is
`'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'`.
This standard location is detected automatically. Alternatively, set
`PUPPETEER_EXECUTABLE_PATH`. `--cargo-home PATH` reuses a
dependency cache. Candidate snapshots include tracked edits and nonignored
untracked files; the checkout is not changed. Keep dependencies compatible with
the pinned application lockfile: changing unrelated dependency versions is rejected.

Every invocation creates a new `.evaluator/runs/<timestamp>/`. Read `report.md`
for the verdict and `report.json` for details. Command logs, source snapshots,
output hashes, correctness outputs, captured indexing inputs, and raw
`timings.json` remain available for inspection. Failed runs retain their evidence.

## What is checked

1. Run existing application, no-default-feature, browser, and library tests for
   both variants. Build release binaries and book preprocessors before timing.
2. Build ten real books and every book under `fixtures/`. Require identical
   filenames and bytes between original, repeated original, and candidate.
3. Capture indexing inputs with a separate original mdBook build. Require that
   capture leaves complete book output unchanged. Replay those inputs against
   each library and require exactly matching serialized indexes.
4. Warm up each variant twice, then collect ten paired timing blocks, alternating
   which variant runs first. Check outputs after every measured build/replay.

The checker also deliberately changes, removes, and adds files and must reject
each alteration. Fixture details are in `fixtures/README.md`; pinned real books
and preparation commands are in `books.json`.

The [auditor](../auditor/README.md) can add reproduced failures as permanent
fixtures. Reports record an `evaluator_version` fingerprint of the harness and
fixtures. A run cannot finish successfully if these files change while it runs.

## Measurements and verdict

**Book-build time** is externally measured process wall time, including normal
preprocessors, rendering, indexing, and output writes. Output cleanup and
comparison are outside the timer. Builds start with fresh output directories;
filesystem caches are warm, not artificially flushed.

**Index time** measures construction, normalization/tokenization, inserting
documents, serialization/JavaScript escaping, and index cleanup. A Rust helper
replays actual mdBook inputs with the same callbacks. Trace reading and writing
the final output file are excluded; file-writing costs remain in book-build
time. See `index-replay/README.md` for the exact boundary.

A worthwhile improvement is **any improvement larger than measurement noise**.
We estimate noise with a paired bootstrap over timing blocks: both metrics'
95% speedup intervals must lie entirely above 1. No fixed percentage is required.
Otherwise the verdict is inconclusive, or slower when an interval lies below 1.

The suite verdict uses equal-weight geometric mean speedups across books.
Per-book results remain visible, including regressions; an aggregate improvement
does not mean every book improved. Per-book intervals are exploratory and have
no adjustment for multiple comparisons; apparent changes can occur even in
original-versus-original runs. Intervals apply to this fixed corpus and
machine, not unseen books. These are supervised measurements, not protection
against a library deliberately falsifying timings or modifying its environment.

`self-check` can never demonstrate a real optimization. It reports a calibration
warning if identical variants appear significantly different. Investigate the
machine or measurement conditions before accepting candidate results.

Defaults are recorded in `config.json`. `--books rust-by-example,rustonomicon`
selects a recorded subset; `--repetitions N` and `--warmups N` override counts.
Subset runs do not qualify the full corpus. Fix these choices before comparing
candidates, and avoid repeatedly rerunning until a favorable interval appears.

## Book preparation

Pinned checkouts must be clean. Copies are prepared inside the run directory.
Three books compile their own preprocessors; timed builds run those preprocessors
normally with Cargo offline. The pinned Rust 1.95.0 toolchain overrides moving
book toolchain files and is recorded. Rust and WebAssembly's obsolete `author`
field is migrated to `authors` in the copy, identically for both variants.
The original checkout remains unchanged. Rust By Example permits its optional
gettext preprocessor to be absent for the default English build.

## Historical validation example

The full original-versus-original run on 2026-09-24 passed exact output checks
for all ten real books and three fixtures (1,376 generated files). Both overall
timing intervals included 1: book builds 0.991–1.008×, indexing 0.998–1.009×.
Some individual-book intervals excluded 1; they do not demonstrate an optimization.

Both variants passed 270 application tests, 243 no-default-feature tests
(two ignored), 23 browser tests, 55 library tests, and three replay-helper tests.
The evaluator's 32 Python tests also passed, including deliberate corruption
and calibration checks. No optimized library has been evaluated.

Local evidence: `.evaluator/runs/20260924T055553.065243Z/report.md` and adjacent
logs and raw timings. These generated artifacts are ignored by Git.

For portable excerpts and regeneration commands, see [example reports](../documentation/examples/README.md).
The complete cold-setup check is `python3 scripts/reproduce.py`.
