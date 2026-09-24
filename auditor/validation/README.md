# Reproduce the auditor controls

Start with a completed **all-ten-books self-check** from `evaluator/run.py`.
Its status may be `validated` or `calibration-warning`; the latter describes
measurement noise/bias, not different application output. macOS `sandbox-exec`,
the pinned Rust toolchain, and an installed, logged-in Codex CLI are required.
Use the same Cargo home as the self-check so its locked dependencies are cached.

```sh
python3 auditor/validation.py \
  --evaluation .evaluator/runs/<self-check-id> \
  --output .auditor/reproduction-001 \
  --cargo-home /path/to/cargo-home
```

The output directory must be new. The default runs both controls; `--case planted`
or `--case benign` selects one. `--model` overrides the auditor's pinned default.
This invokes Codex and can promote reproduced regression books into the
repository's `evaluator/fixtures/`. Existing fixtures remain enabled and do not
replace the requirement for a fresh differential probe.

The recipes are committed in `auditor/validation.py`:

- **Planted violation:** `Index::add_doc` skips any document containing
  `audit_hidden_marker_5821`. The auditor must reproduce that marker-triggered
  failure, confirm it, and promote a regression check.
- **Benign change:** `Pipeline::run` reserves space for at most its input token
  count. Filtering, ordering, and token contents stay unchanged. The auditor must
  find no active violation and retain `unresolved` solely because these control
  packages intentionally lack a full candidate evaluation.

Each private library is reconstructed from the self-check's original source
manifest and checked against its hashes. Each candidate application is compiled
with the copied lockfile and selected private library, and library tests run.
Release artifacts are copied to independent storage (APFS copy-on-write on macOS)
to speed rebuilding; `--no-reuse-builds` forces a fresh build. No hardlinks or
shared target symlinks are used. The source run remains untouched.

Qualification reports explicitly say `incomplete`. They contain source and
binary identities, **no copied timing samples, successful correctness report,
or performance claim**. The source application snapshot has the same historical
provenance limitations as the input self-check; matching local hashes are not
independent authentication of a maliciously rewritten run.

To also reproduce the full evaluator's rejection of the planted candidate:

```sh
python3 auditor/validation.py \
  --evaluation .evaluator/runs/<self-check-id> \
  --output .auditor/reproduction-with-evaluator \
  --cargo-home /path/to/cargo-home \
  --reevaluate \
  --browser "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

The previously committed marker regression is retained, so the full rerun may
reject the candidate there before reaching the newly proposed book. The auditor
must still reproduce its own probe. This rerun must end in `correctness-failed`; it is not a successful
performance evaluation. `summary.json` records both expected outcomes and makes
the validation command exit nonzero if they are not observed. Per-case diffs,
build/test logs, qualification evidence, audit conversations, probes, and reports
are retained under the output directory. Agent outcomes are not deterministic;
an incomplete investigation is a failed validation, not proof of a code defect.
