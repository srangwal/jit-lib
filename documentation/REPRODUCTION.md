# Reproduction verification

On 2026-09-24, `python3 scripts/reproduce.py` completed successfully on the
[documented Mac environment](ENVIRONMENT.md). It started with a separate source
copy, no book checkouts, empty Cargo/npm caches, and no evaluator/auditor outputs.
Installed tools, Chrome, the OS, and Codex login were shared.

## Results

- Downloaded and verified all ten pinned book revisions.
- Passed 101 Python tests in the clean source copy.
- Passed the full evaluator self-check: 14 books/fixtures, 1,414 identical output
  files, and 400 timing samples. Both aggregate intervals included 1: book builds
  0.9915–1.0019×; indexing 0.9942–1.0052×. Status: `validated`.
- Baseline audit: `no-issue-found`, using Codex CLI 0.156.1 and `gpt-6-sol` with
  medium reasoning.
- Planted control: reproduced the document-skipping failure and added one check
  in the isolated copy. The full evaluator rerun rejected the candidate at the
  existing marker regression, before performance measurement.
- Harmless control: no findings. Status remained `unresolved` solely because
  its qualification input intentionally omitted a full performance evaluation.

The final compiler/output-override guards were added after that source copy was
created. All 106 tests then passed in the working checkout, and the new guards
accepted all 22 recorded Cargo command environments/configurations from the
cold self-check. Subsequent changes to report links and explanatory text did
not repeat the expensive builds.

## Evidence and limits

Small, checksummed excerpts are in [examples/](examples/README.md). Original
logs and source snapshots remain local under
`.evaluator/reproduction/20260924T195128.097798Z/`; they are ignored artifacts,
not prerequisites for another checkout. The excerpts retain the actual source
fingerprints rather than presenting them as a later code version.

This validates cold setup on the tested Mac, not installation on a fresh OS or
support for other platforms. A new run should obtain the same inputs and exercise
the same checks. Timing numbers and AI responses can differ. No optimization or
general reward-hacking detection guarantee is established by these controls.
