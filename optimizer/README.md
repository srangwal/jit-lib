# Optimizer

Make one application-specific change to elasticlunr-rs for mdBook. The optimizer
uses Codex CLI with `gpt-6-sol`. It returns a candidate for independent evaluation;
it does not decide whether the candidate is correct or faster.

## Run one attempt

Complete the [root setup instructions](../README.md) first, including a self-check
whose report says `validated`. Then run from the repository root, replacing the
placeholder with that run's directory:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id>
```

The default agent limit is 600 seconds. Model calls use your logged-in Codex
account. The supported environment is macOS with `sandbox-exec`, rustup and the
repository's pinned Rust toolchain. A local write-boundary check must pass before
the agent starts; there is no unsandboxed fallback.

The command copies the baseline application, library, books, and results into
the new attempt. The agent can edit its private library and run local builds or
correctness tests. It cannot write to the reference context or existing results
through its sandboxed tools. Tool network access is disabled; the Codex process
still needs network access to the model.

Locked crate archives are copied from your Cargo cache into a private cache.
The shared cache is unchanged. If the baseline used another Cargo cache, pass
`--cargo-home /path/to/that/cache`. Missing cached dependencies may prevent local
tests; their absence is recorded. This command does not download dependencies.

Optional context and settings:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --profile /path/to/profile.txt --feedback /path/to/prior-feedback.md \
  --timeout 600 --model gpt-6-sol
```

Profiles and feedback are copied as input files. Profiling is not collected
automatically. Without a profile, the proposed benefit remains an unprofiled
hypothesis. Each command starts from the original library; automatic revision
loops and candidate selection belong to the future controller.

## Read the output

The command prints `.optimizer/attempts/<attempt-id>/report.md`. It contains the
explanation, source references, agent-reported local checks, risks, and status:

- `candidate-created`: a changed library and explanation were saved.
- `no-change`: the agent declined to submit a change.
- `incomplete`: a tool, timeout, input, or submission check failed. Evidence remains.

Exit code is zero for the first two statuses and one for `incomplete`.
Neither successful status establishes an improvement.

For a candidate, inspect `candidate.patch` and `candidate-files.json`. The
independent source copy is `candidate/`; it has a Git index so the evaluator can
read it, but no commits. Then explicitly run:

```sh
python3 evaluator/run.py run --candidate .optimizer/attempts/<attempt-id>/candidate
```

`report.json` records input identities, optimizer code fingerprint, CLI/compiler
versions, model, and time limit. `agent/` contains the prompt, effective settings,
structured response, events, and stderr. `context/` preserves inputs;
`workspace/` preserves editing and build scratch. Never overwrite an old attempt.
These files are ignored by Git. Local check results are agent claims; independent
verification still belongs to the evaluator and auditor.

## Code and tests

- `context.py` verifies and copies baseline evidence.
- `agent.py` checks write boundaries and invokes the bounded Codex session.
- `artifacts.py` validates the submission and exports its source and patch.
- `run.py` connects these steps for one attempt and writes its report.

```sh
python3 -m unittest discover -s optimizer/tests -v
OPTIMIZER_SANDBOX_TEST=1 python3 -m unittest optimizer.tests.test_agent.OptimizerAgentTests.test_real_sandbox_writes_only_to_workspace -v
```

The second command requires native macOS sandbox execution, outside an enclosing
sandbox that forbids it. It contacts no model. The ordinary tests use agent doubles.

See [optimizer responsibilities](../docs/OPTIMIZER.md),
[controller design](../docs/CONTROLLER.md), and [workflow](../docs/WORKFLOW.md).
