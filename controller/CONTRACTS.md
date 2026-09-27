# Controller communication contracts

Each handoff has its own versioned JSON format. IDs and artifact references link
them; component payloads do not need identical fields. The controller validates
native statuses, exit codes, source identities, coverage, and measurement
consistency before using results. Console output is never an acceptance signal.

## Artifact references

References contain `path` (relative to the experiment root) and `sha256` (a full
file digest). Source manifests identify files by name, size, and SHA-256. Candidate
files are checked again after evaluation/audit and before selection.

## Controller to optimizer

`tasks/<attempt>.json` uses `schema_version: optimizer-task/v1` with:

| Field | Required information |
| --- | --- |
| `experiment_id`, `attempt_id`, `request_id` | Which experiment and request this task belongs to. |
| `task` | Objective, focus, and independent success rule. |
| `inputs` | Validated baseline, complete history reference, profile, and prior feedback. |
| `workload` | Selected book IDs, pinned manifest, prepared file hashes, execution recipe, measurement configuration and weighting. |
| `context_paths` | Where the agent finds sources, full prepared books, objective, history, and feedback. |
| `requirements` | Behavior to preserve and prohibited shortcuts. |
| `execution` | Time budget, allowed local tests and diagnostic benchmarks, and network/evaluation restrictions. |

`task.library_reduction_target_percent` records the required time reduction.
`requirements.editable_source` limits source edits to the library. Application
code stays read-only. These constraints apply to every coding-agent runtime.

The task supplements the unified optimizer prompt; it cannot relax the sandbox or
submission checks. The optimizer receives the actual prepared workload files, not
just book names. It specializes for their usage patterns while preserving the
application's supported library usage, including new contents and configurations.
Workload contents alone do not prove a behavioral guarantee.

`context/objective.json` records the effective `library_reduction_target_percent`
and correctness boundary. The controller verifies its hash and target against
the task. Local measurements are diagnostic; independent evaluation decides
whether the candidate meets the target.

## Optimizer base requests

Investigation, base selection, and editing happen in one agent session. Before
editing, the agent atomically writes `workspace/base-request.json`:

```json
{
  "request_id": "base-1",
  "base_candidate_id": "attempt-001",
  "contributing_candidate_ids": ["attempt-002"],
  "reason": "Keep the first candidate's representation and adapt the second idea."
}
```

The base must be `original` or an available earlier candidate. Contributors name
additional candidates whose ideas will be reused. The runner validates these IDs,
saves a protected `optimizer-base-checkpoint/v1` record with source file hashes,
then creates `workspace/library/`. The agent waits for `base-response.json` with
the matching `request_id`, `status: ready`, and checkpoint path/hash before editing.

A new request ID can switch bases in the same session. The runner archives the
abandoned library before replacing it. Reusing an ID with different contents
fails. `starting-point.json` and the final report identify the last checkpoint;
`base_checkpoints` links every checkpoint by path and SHA-256. The controller
checks parentage and source hashes before accepting the submission.

## Controller to evaluator and auditor

Each step saves `request.json` with its component-specific schema version,
experiment/request/attempt IDs and input references. Evaluator requests identify
the frozen candidate, baseline, and evaluator version. Auditor requests identify
the candidate and the exact evaluation result. `command.json` records effective
arguments and the outer timeout; native reports record tool versions and
component settings.

## Results and rich feedback

Every step's `result.json` links its request and native report and records
timestamps, process status, exit code, logs, and protocol errors. Native outcomes
retain their component-specific meanings: a completed evaluator can report a
correctness failure, and a completed auditor can report a confirmed violation.

`feedback/<attempt>-evaluation.json` uses `evaluator-feedback/v1`. It includes:

- `outcome`, `execution_status`, correctness results and error details.
- `performance.aggregate` and `performance.per_book`, each containing original
  and candidate medians in seconds, sample counts, speedup ratio, 95% confidence
  interval, percentage time reduction, asymmetric uncertainty offsets, verdict,
  reason code, and plain-language explanation.
- `performance.regressions`, including uncertain slowdown point estimates.
- `performance.qualification`: recorded target, lower 95% reduction bound,
  whether the target is met, and an explanation. A statistically significant
  gain below the target does not qualify. Application timing does not veto it.
- Measurement configuration, timer boundaries, weighting and statistical scope.
- Hashed raw evidence, output mismatches, and failed-command log excerpts.

Speedup is original time divided by candidate time. Time reduction is
`100 * (1 - 1 / speedup)`. An interval including a speedup of 1 is inconclusive;
missing measurements are explicitly unmeasured. Aggregate medians are medians of
per-block geometric mean durations, not total time for building all books.

`feedback/<attempt>-audit.json` uses `auditor-feedback/v1`, preserving findings,
reproducing probes, unresolved concerns, added checks, and the native result.
The next optimizer receives the feedback contents, not merely external paths.

## Timeline and invalidation

`events.jsonl` records ordered event IDs, timestamps, attempt/step links and
decisions with reasons and evidence references. Components also append phase
records to `output/progress.jsonl`. Raw model events stay under the optimizer or
auditor output directories.

When an audit adds checks, `checks_changed` identifies the old and new evaluator
versions and marks earlier results stale for selection. The new self-check and
reevaluation are separate steps. Requests, results and earlier feedback are never
overwritten. `report.md` is generated from the timeline and can be regenerated
with `Records.render`; it is not a second source of decision logic.

## Complete history contract

Every optimizer request links `tasks/<attempt>-history/ledger.json` through
`inputs.history_ref`. The runner copies the bundle into read-only
`context/history/`; `summary.md` is the readable table. The ledger uses
`schema_version: optimizer-history/v1`:

| Field | Contents |
| --- | --- |
| `current_evaluator_version` | The checks currently used for acceptance. |
| `entries` | Every prior attempt, including attempts with no candidate. Each entry records parentage, proposal, changes, optimizer outcome, evaluations, audits, and evidence links. |
| `candidates` | Candidate ID to frozen library path and source manifest. |
| `artifacts` | Relative file paths with byte counts and SHA-256 hashes for the bundle, excluding the ledger itself. |

Evaluations retain correctness, library/application measurements and uncertainty,
per-book regressions, evaluator version and source, and a `stale` flag. Audits
retain findings and unresolved concerns. Evidence includes patches, proposals,
prompts, reports, and logs; generated builds and caches are excluded. Missing
measurements remain explicit. Older results are readable but cannot establish
acceptance under changed checks.

The optimizer verifies the bundle before copying it. It adds the pinned library
test lockfile to candidate copies for local builds and records the resulting
context manifest. The controller checks that manifest against the supplied
history. The final submission binds task IDs/hash, copied inputs, base
checkpoints, candidate manifest, and explanation.

## Self-check calibration evidence

New self-check reports include `calibration_policy` with criterion
`self-check-point-difference/v1`, `tolerance_percent: 5`, the percentage formula,
per-metric `time_reduction_percent` and `within_tolerance`, and overall `passed`.
Both aggregate metrics must be within ±5%, inclusive; confidence intervals do
not decide calibration. The controller recomputes this policy and rejects a
contradictory status or policy. Feedback retains it as `performance.calibration`.

Historical reports without this field retain their original interval-based rule;
they are not relabeled. A changed evaluator fingerprint requires a fresh
self-check. This change does not alter candidate acceptance: the lower 95%
library time-reduction bound must meet the configured target (default 20%).

## Optimizer submission corrections

A source-reference validation error may trigger one correction call inside the
same optimizer attempt and remaining time budget. The candidate source and base
must remain unchanged. Application references accept only `application/path:line`;
library references accept `original/path:line` or `library/path:line`, with at
least one original-library reference. The optimizer retains the rejected response
and error in `rejected-submission.json`, correction logs in `agent-correction/`,
and its result in `report.json.submission_correction`. A correction is not a new
candidate attempt or an evaluation result. Unresolved errors still stop the run.
