# Auditor

The auditor uses Codex CLI to investigate a frozen evaluator run. It asks whether
the modified library preserves supported behavior and whether the reported
improvement is credible. See [the design](../documentation/AUDITOR.md).

## Run an audit

From the repository root, with Codex CLI installed and logged in:

```sh
python3 auditor/run.py --evaluation .evaluator/runs/<run-id>
```

This runs manually; no scheduling policy is implemented. It can add confirmed
regression books to `evaluator/fixtures/audit-<hash>/`. The existing evaluator
automatically includes those books in future correctness checks.

To also rebuild the frozen candidate and run the strengthened evaluator after
adding checks:

```sh
python3 auditor/run.py --evaluation .evaluator/runs/<run-id> \
  --reevaluate \
  --browser "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

Pass `--cargo-home /path/to/cargo-home` if your dependency cache uses a separate
location. Without `--reevaluate`, the report explicitly marks a full rerun as
required when checks were added. A reproduced correctness failure may stop the
rerun before performance measurement, as intended.

## How the code fits together

1. `evidence.py` verifies recorded library/binary hashes and freezes sources,
   outputs, command logs, timings, and current evaluator code. Missing historical
   provenance is reported, not reconstructed.
2. `agent.py` runs `codex exec` with read-only tools and structured JSON output.
   `prompt.md` directs source review and hypothesis generation. The agent does
   not execute candidate binaries; it returns proposed test books.
3. `probes.py` builds each proposed book twice with each frozen binary. Matching
   reference builds establish the expected output; repeated candidate differences
   reproduce a failure. Timeouts and unstable results remain inconclusive.
4. `run.py` feeds results back to Codex, retains unresolved concerns, and promotes
   validated books after the agent identifies the supported requirement violated.
   Confirmation without an actual reproduction cannot promote a check.

Reports, agent conversations, proposed books, output differences, and execution
logs are retained under `.auditor/runs/<timestamp>/`. `report.md` is the readable
summary; `report.json` contains the complete investigation. Exit codes are `0`
for no issue found within scope, `1` for a confirmed violation, `2` for unresolved
concerns, and `3` for an incomplete audit. These are audit outcomes, not an
automatic acceptance policy.

## Boundaries

Automated experiments currently support self-contained mdBook correctness cases.
Timing manipulation and other concerns can be investigated from source/evidence,
but checks requiring new measurement machinery remain unresolved proposals.
The auditor does not automatically write arbitrary executable evaluator code.

Probe execution requires macOS `sandbox-exec`; there is no unsandboxed fallback.
Each build gets a fresh directory with protected reference files, restricted
writes, and blocked network/fork access. This is not a VM or a disk/memory quota.
The optional full rerun uses the evaluator's existing build/test execution model,
which does not sandbox candidate build scripts or upstream test suites.

Codex uses its installed default model unless `--model` is supplied. User config
and execution rules are ignored for the audit process; existing Codex login is
used. The default budget is three rounds with a ten-minute timeout per round;
`--max-rounds`, `--agent-timeout`, and `--probe-timeout` adjust those limits.
Exhausting the round budget produces an incomplete audit.

## Tests

```sh
python3 -m unittest discover -s auditor/tests -v
python3 -m unittest discover -s evaluator/tests -v
```

Unit tests cover evidence tampering, sandbox boundaries, repeatability, false
confirmations, missing probe evidence, fixture promotion, and exact candidate
reconstruction. Codex is not called by unit tests.

Live validation on 2026-09-24 also exercised Codex and real mdBook binaries:

- Original-versus-original: no issue found within the source/evidence audit.
- Planted document-skipping library: Codex generated a reproducing book, the
  controller confirmed it and added a fixture, and the full evaluator rerun
  rejected the candidate at that fixture after all ten real books passed.
- Behavior-preserving token-vector preallocation: no violation finding. The
  controller retained an unresolved outcome because the supplied control
  evidence had no full timing results. Separately, all 55 library tests and a
  38-file output comparison passed.

Local reports are `.auditor/validation-{baseline,planted,benign}/report.md`.
The two changed-library inputs were explicitly labeled synthetic qualification
inputs. These checks validate the auditor workflow; they establish no speedup or
general detection guarantee. The faulty candidate failed before timing started.
