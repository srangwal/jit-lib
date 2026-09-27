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
Self-check timing passes when both aggregate measured differences are within
±5% of original time, inclusive. Confidence intervals remain visible but do not
determine this calibration result. Candidate acceptance still uses the lower
95% confidence bound and the configured library improvement target.

The defaults implement the agreed policy:

- Run **at least three attempts**, and at most **five**, with **ten minutes of
  agent time per attempt**. A no-change response consumes an attempt.
- Every attempt gets the complete history and actual prepared workload.
  One agent session investigates, chooses any earlier candidate or the original,
  edits, and runs local diagnostics within the ten-minute budget.
- Base checkpoints record decisions and contributing candidates before edits.
  Combining ideas is allowed; application code remains read-only.
- **Every submitted candidate is audited**, including failed or slower ones.
- After attempt three, select the best qualifying candidate if one exists.
  Otherwise continue, stopping as soon as one qualifies or the budget is used.
- Qualification requires passing correctness, a lower 95% confidence bound for
  aggregate library time reduction meeting the fixed acceptance threshold
  (default **20%**), and an audit reporting no issue found. Application time
  does not block success. Among qualifiers, choose the highest lower confidence
  bound; an exact tie favors the earlier attempt.
- Show individual-book regressions even when the aggregate improves.

Override the target before starting with `--library-reduction-target-percent 30`.
Targets are percentages of time saved: 100 ms to 70 ms is a 30% reduction.
The target must be at least 0 and less than 100; at 0, improvement must still
exceed noise. The indexing timer includes construction, serialization, and
cleanup. Both aggregate application timings and per-book regressions stay visible.
Changing the target requires a new experiment; earlier evidence is never relabeled.
The optimizer changes library code only; application code remains protected.

Each attempt also receives a **stretch target** to encourage larger gains:

```text
stretch = max(acceptance threshold, min(95%, 1.5 × best previous measured reduction))
```

With no eligible earlier candidate, the stretch target equals the acceptance
threshold. Eligible candidates passed correctness and a completed audit with no
issue found, and have complete measurements under the current checks. Use the
best measured aggregate library reduction, not the latest candidate or a local
diagnostic estimate. All reductions compare with the original library. For
example, a 19% measured reduction raises a 20% target to 28.5% for the next attempt.
The 95% ceiling never lowers a higher acceptance threshold. Stretch targets guide
the optimizer; they do not change acceptance or limit its ambition.

Preparation, evaluation, and auditing take additional time. The default complete
evaluator command limit is two hours; the complete auditor limit is one hour.
`--optimizer-timeout` defaults to 600 seconds and accepts up to 14400 (four hours).
`--auditor-agent-timeout` sets the limit for each auditor agent call, while
`--audit-timeout` limits the whole audit, including all calls and probes.
The auditor allows up to three calls by default. Change limits or supply a profile with:

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
  --auditor-agent claude --auditor-model claude-opus-5 \
  --local-base-url http://127.0.0.1:11434/v1
```

Choices are `codex`, `claude`, and `opencode`. OpenCode requires an already running
local model server and never falls back to a cloud provider. Each component's
`config.json` supplies its defaults. `--model` overrides both models; a component's
`--optimizer-model` or `--auditor-model` takes precedence. See
[coding-agent setup](../coding_agents/README.md).

For two hours per agent call with the local 32k model:

```sh
python3 controller/run.py --baseline .evaluator/runs/<self-check-run-id> \
  --optimizer-agent opencode --optimizer-model qwen3.8:27b-mlx-32k \
  --auditor-agent opencode --auditor-model qwen3.8:27b-mlx-32k \
  --local-base-url http://127.0.0.1:11434/v1 \
  --optimizer-timeout 7200 --auditor-agent-timeout 7200 --audit-timeout 22500
```

The whole-audit limit above allows three two-hour calls plus 15 minutes for
preparation and probes. Agents may finish early; two hours is a maximum, not a
required duration. The full experiment can take much longer than two hours.

For four hours per optimizer attempt and auditor call for one run, replace the
last line with `--optimizer-timeout 14400 --auditor-agent-timeout 14400 --audit-timeout 44100`.
This allows three four-hour audit calls plus 15 minutes of overhead. Command-line
overrides apply only to that run; the defaults stay unchanged.

`--browser`, `--cargo-home`, and `--cache` are optional. No profile is collected
automatically before optimization; the agent may collect local diagnostic profiles.
New book contents and supported configurations remain within the correctness contract.
`--attempts` accepts 3 through 5; optimizer time defaults to 600 seconds per attempt.

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
| `tasks/<attempt>-stretch-target.json` | This attempt's acceptance threshold, stretch target, and supporting previous result. |
| `steps/<step>/request.json` | Inputs and identities supplied to a component. |
| `steps/<step>/result.json` | Request linkage, exit status, report hash, and log references. |
| `steps/<step>/output/` | Native component evidence, candidate files, and agent traces. |
| `feedback/` | Timing estimates, confidence intervals, failure details, audit findings, and explanations. |
| `events.jsonl` | Ordered starts, completions, decisions, and check-version changes. |
| `summary.json`, `report.md` | Final status and readable history. |
| `selection.json` | On success, the selected candidate and the lower confidence bounds used to compare qualifiers. |

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
attached to their old version. It then reevaluates every earlier candidate whose
audit found no issue, before using those measurements for targets or selection.
These are fresh evaluations, not new audits: the original audit stays attached
to the unchanged candidate. Confirmed violations and unresolved findings are
not cleared by reevaluation.

Infrastructure failures and cancellation can stop a run before three attempts;
the minimum does not require continuing after a failed component.

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
- `policy.py`: stretch targets, candidate eligibility, and ranking.
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
