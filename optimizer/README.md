# Optimizer

Make one application-specific change to elasticlunr-rs for mdBook. The optimizer
uses a configurable coding agent: Codex, Claude Code, or OpenCode with a local
model. Codex with `gpt-6-sol` remains the default. It returns a candidate for independent evaluation;
it does not decide whether the candidate is correct or faster.

## Run one attempt

Complete the [root setup instructions](../README.md) first, including a self-check
whose report says `validated`. Then run from the repository root, replacing the
placeholder with that run's directory:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id>
```

The default agent limit is 600 seconds. Codex and Claude use their logged-in
accounts; OpenCode uses only the configured local model server. The supported environment is macOS with `sandbox-exec`, rustup and the
repository's pinned Rust toolchain. A local write-boundary check must pass before
the agent starts; there is no unsandboxed fallback.

The command copies the baseline application, library, books, and results into
the new attempt. The agent can edit its private library and run local builds or
correctness tests. It cannot write to the reference context or existing results
through its sandboxed tools. Tool network access is disabled. Codex and Claude still connect to their model
services; OpenCode can connect only to the configured loopback model endpoint.

Locked crate archives are copied from your Cargo cache into a private cache.
The shared cache is unchanged. If the baseline used another Cargo cache, pass
`--cargo-home /path/to/that/cache`. Missing cached dependencies may prevent local
tests; their absence is recorded. This command does not download dependencies.

Choose an agent with `--agent codex|claude|opencode`. For example:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --agent claude --model sonnet
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --agent opencode --model qwen3.8:27b-mlx \
  --local-base-url http://127.0.0.1:11434/v1
```

The local model server must already be running. The URL above is a configurable
setup default, not a discovered server address. See [coding agents](../coding_agents/README.md)
for installation, isolation, and runtime evidence. `--agent-executable` selects a
nonstandard CLI path. Defaults live in `config.json`.

Optional context and settings:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --profile /path/to/profile.txt --feedback /path/to/prior-feedback.md \
  --timeout 600 --model gpt-6-sol
```

Profiles and feedback are copied as input files. Profiling is not collected
automatically. Without a profile, the proposed benefit remains an unprofiled
hypothesis. Without a previous candidate, each command starts from the original
library.

## Controller inputs and revisions

The controller can provide a structured task and the previous candidate:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --task /path/to/task.json --feedback /path/to/feedback.json \
  --previous-candidate /path/to/previous/candidate --timeout 600
```

The task uses `schema_version: "optimizer-task/v1"`, nonempty `experiment_id`,
`attempt_id`, and `request_id` strings, plus `task` and `workload` objects. It
describes the objective, workload recipe, requirements, and evidence references.
The runner saves the exact brief and its hash. It cannot override sandbox or
submission rules. Frozen baseline books remain the local workload inputs.

When a previous candidate is supplied, a separate agent session first chooses
`revise` or `restart` and explains why. It can inspect both sources and feedback,
but has no writable library. The runner records the decision before copying the
chosen source into the editing workspace. Selection and editing share the same
600-second agent budget; setup and the boundary probe happen beforehand.

The original reference remains unchanged. A revision's exported patch is still
relative to the original; `attempt-changes.json` describes changes from the
chosen starting point. `no-change` means the selected starting point was left
unchanged, and produces no new candidate.

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
versions, chosen agent, model, local endpoint when applicable, and time limit.
`coding-agents-source/` preserves the shared adapter code and its recorded fingerprint. `agent/` contains the prompt, effective settings,
structured response, events, and stderr. `context/` preserves inputs;
`workspace/` preserves editing and build scratch. Never overwrite an old attempt.
`starting-point.json` records the selected source and hashes; `selection/` holds
the selection session's evidence when a previous candidate was offered.
`progress.jsonl` records phase timestamps for preparation, boundary checks,
starting-point selection, editing, export, and failures.
These files are ignored by Git. Local check results are agent claims; independent
verification still belongs to the evaluator and auditor.

## Code and tests

- `context.py` verifies and copies baseline evidence.
- `agent.py` checks write boundaries and invokes the bounded agent session.
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
