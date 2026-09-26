# Auditor

The auditor uses a configurable coding agent to investigate a frozen evaluator run.
Choose Codex (the default), Claude Code, or OpenCode with a local model. It asks whether
the modified library preserves supported behavior and whether the reported
improvement is credible. See [the design](../documentation/AUDITOR.md).

## Run an audit

From the repository root on macOS, with `sandbox-exec` available and your chosen
agent installed. The default command uses your Codex login:

```sh
python3 auditor/run.py --evaluation .evaluator/runs/<run-id>
```

Choose another runtime without changing the audit checks:

```sh
python3 auditor/run.py --evaluation .evaluator/runs/<run-id> \
  --agent claude --model sonnet
python3 auditor/run.py --evaluation .evaluator/runs/<run-id> \
  --agent opencode --model qwen3.8:27b-mlx \
  --local-base-url http://127.0.0.1:11434/v1
```

The local server must already be running; the example URL is a configurable
default. See [coding agents](../coding_agents/README.md) for setup and boundaries.
`--agent-executable` overrides the CLI path.

This runs one standalone audit. The controller audits every submitted candidate. It can add confirmed
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
2. `agent.py` invokes the selected agent with protected evidence and structured JSON output.
   `prompt.md` directs source review and hypothesis generation. The agent does
   not execute candidate binaries; it returns proposed test books.
3. `probes.py` builds each proposed book twice with each frozen binary. Matching
   reference builds establish the expected output; repeated candidate differences
   reproduce a failure. Timeouts and unstable results remain inconclusive.
4. `run.py` feeds results back to the agent, retains unresolved concerns, and promotes
   validated books after the agent identifies the supported requirement violated.
   Confirmation without an actual reproduction cannot promote a check.

Reports, agent conversations, proposed books, output differences, and execution
logs are retained under `.auditor/runs/<timestamp>/`. `report.md` is the readable
summary; `report.json` contains the complete investigation. Exit codes are `0`
for no issue found within scope, `1` for a confirmed violation, `2` for unresolved
concerns, and `3` for an incomplete audit. These are audit outcomes, not an
automatic acceptance policy.

Each report records the effective model, round/time limits, chosen agent and CLI version,
platform and Python version, and sandbox policies under `auditor`. The
`auditor-source/` snapshot contains the controller modules, prompt, response
schema, and default configuration, with file hashes and a combined fingerprint.
`coding-agents-source/` also preserves the shared adapter code and fingerprint.
Platform, authentication, and other early failures retain this provenance where
available. Missing CLI version or binary information remains null rather than
being inferred.

New permanent fixture metadata references evaluations inside this checkout by
repository-relative path. External evaluations use a basename and report hash,
not the originating machine's absolute path. Existing fixture metadata is kept.

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

`config.json` selects the agent and its model: `gpt-6-sol` for Codex, `sonnet`
for Claude, and `qwen3.8:27b-mlx` for OpenCode. `--model` overrides that default.
Codex and Claude use medium reasoning by default; OpenCode records reasoning
as unset. Codex uses its native read-only sandbox. Claude and OpenCode use a
sandboxed shell tool that can write only to private scratch, protecting audit
evidence. OpenCode has no cloud fallback. The default budget is three rounds
with a ten-minute timeout per round;
`--max-rounds`, `--agent-timeout`, and `--probe-timeout` adjust those limits.
Exhausting the round budget produces an incomplete audit.

## Tests

```sh
python3 -m unittest discover -s auditor/tests -v
python3 -m unittest discover -s evaluator/tests -v
```

Unit tests cover evidence tampering, sandbox boundaries, repeatability, false
confirmations, missing probe evidence, fixture promotion, and exact candidate
reconstruction. Models are not called by unit tests.

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

To recreate these controls from a new self-check, follow the
[validation recipe](validation/README.md). The root command
`python3 scripts/reproduce.py` runs the complete cold-setup demonstration in an
isolated source copy. [Portable examples](../documentation/examples/README.md)
are small report excerpts; the original run artifacts are not checkout dependencies.
