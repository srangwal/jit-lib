# Controller

Run one complete mdBook + elasticlunr-rs experiment. The controller asks the
optimizer for a candidate, evaluates it, audits it, and returns the evidence as
feedback for the next attempt.

## Run an experiment

Follow the root setup guide first. Use a completed self-check that reports
`validated` and includes all ten pinned books:

```sh
python3 controller/run.py --baseline .evaluator/runs/<self-check-run-id>
```

By default, both components use your Codex account. It requires the same macOS, sandbox, Rust, browser,
and dependency setup as the standalone components. A stale evaluator version
triggers a fresh self-check before optimization. A calibration warning stops
the experiment; it does not retry for more favorable measurements.

The defaults implement the agreed policy:

- At most **five attempts**, with **ten minutes of agent time per attempt**.
- Every attempt gets the complete history and actual prepared workload.
  One agent session investigates, chooses any earlier candidate or the original,
  edits, and runs local diagnostics within the ten-minute budget.
- Base checkpoints record decisions and contributing candidates before edits.
  Combining ideas is allowed; application code remains read-only.
- **Every submitted candidate is audited**, including failed or slower ones.
- Stop at the **first qualifying candidate**: correctness passes, the lower
  95% confidence bound for aggregate library time reduction meets **20%**, and
  the audit reports no issue found. Application time does not block success.
- Show individual-book regressions even when the aggregate improves.

Override the target before starting with `--library-reduction-target-percent 30`.
Targets are percentages of time saved: 100 ms to 70 ms is a 30% reduction.
The target must be at least 0 and less than 100; at 0, improvement must still
exceed noise. The indexing timer includes construction, serialization, and
cleanup. Both aggregate application timings and per-book regressions stay visible.
Changing the target requires a new experiment; earlier evidence is never relabeled.
The optimizer changes library code only; application code remains protected.

Preparation, evaluation, and auditing take additional time. The default complete
evaluator command limit is two hours; the complete auditor limit is one hour.
Auditor investigation limits also apply. Change limits or supply a profile with:

```sh
python3 controller/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --output .controller/my-experiment --attempts 3 --optimizer-timeout 300 \
  --evaluation-timeout 7200 --audit-timeout 3600 \
  --profile /path/to/profile.txt
```

Choose the optimizer and auditor agents independently:

```sh
python3 controller/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --optimizer-agent opencode --optimizer-model qwen3.8:27b-mlx \
  --auditor-agent claude --auditor-model sonnet \
  --local-base-url http://127.0.0.1:11434/v1
```

Choices are `codex`, `claude`, and `opencode`. OpenCode requires an already running
local model server and never falls back to a cloud provider. Each component's
`config.json` supplies its defaults. `--model` overrides both models; a component's
`--optimizer-model` or `--auditor-model` takes precedence. See
[coding-agent setup](../coding_agents/README.md).

`--browser`, `--cargo-home`, and `--cache` are optional. No profile is collected
automatically before optimization; the agent may collect local diagnostic profiles.
New book contents and supported configurations remain within the correctness contract. Limits accept at most five attempts and 600 optimizer seconds per attempt.

## Follow what happens

The command prints the experiment directory, normally under
`.controller/experiments/`. Open `report.md` while it runs. Each step points to
its request, result, and supporting evidence. Component stdout/stderr and
`output/progress.jsonl` show ongoing work while a command is running.

| File or directory | What it explains |
| --- | --- |
| `configuration.json`, `source/` | Effective controller settings and captured component source versions. |
| `inputs/` | Frozen original sources, book inputs, baseline evidence, and optional profile. |
| `tasks/` | Task briefs and complete history bundles: readable tables, candidate snapshots, and hashed supporting evidence. |
| `steps/<step>/request.json` | Inputs and identities supplied to a component. |
| `steps/<step>/result.json` | Request linkage, exit status, report hash, and log references. |
| `steps/<step>/output/` | Native component evidence, candidate files, and agent traces. |
| `feedback/` | Timing estimates, confidence intervals, failure details, audit findings, and explanations. |
| `events.jsonl` | Ordered starts, completions, decisions, and check-version changes. |
| `summary.json`, `report.md` | Final status and readable history. |

Controller artifact links are relative to the experiment directory. Native
reports and exact command records may retain original absolute paths; use the
relative controller links when moving evidence. Keep the whole experiment
directory together. Raw timings are preserved; AI responses and timing numbers
will vary between runs.

## Failures and new checks

An unsuccessful candidate consumes an attempt. A no-change response has no
candidate to evaluate or audit. Infrastructure failures stop with evidence;
missing results never become successful verdicts. If a build fails before audit
binaries exist, the auditor is still invoked and may report incomplete.

Reproduced audit findings can add permanent checks under `evaluator/fixtures/`.
The controller records that version change, runs a fresh original-versus-original
self-check, and reevaluates the same frozen candidate. Earlier results remain
attached to their old version. A confirmed violation cannot qualify merely
because a later measurement looks faster.

Only one controller runs per repository at a time. Avoid concurrent manual
evaluations, audits, or edits: they can disturb measurements or invalidate
evidence. Cancellation retains reports and attempts to stop the component's
process tree, including children using separate process groups. This is not a VM
or a guarantee against deliberately escaping processes. Interrupted experiments
are not automatically resumed; use a new output directory.

Exit codes: `0` qualified, `2` budget exhausted without a qualifying candidate,
`1` incomplete, `130` interrupted. No issue found means no violation detected
within that audit, not proof of absence. Performance intervals describe the
fixed corpus and machine; searching multiple candidates does not establish a
population-wide guarantee.

## Code and tests

- `run.py`: command, limits, exclusive run lock, and final report.
- `loop.py`: attempt policy and stop/refresh decisions.
- `components.py`: component commands, task briefs, identity checks, and feedback.
- `feedback.py`: measured improvements, uncertainty, and per-book results.
- `history.py`: every prior attempt, frozen candidate, supporting evidence, and parent links.
- `records.py`: immutable records, evidence hashes, and readable timeline.
- `process.py`: subprocess logs, timeouts, and cancellation.

```sh
python3 -m unittest discover -s controller/tests -v
```

These tests use controlled component responses and real small subprocesses;
they do not call a model or demonstrate a library speedup. See
[the communication contracts](CONTRACTS.md) for record formats.
