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
| `inputs` | Validated baseline, previous candidate when available, profile, prior feedback. |
| `workload` | Selected book IDs, pinned manifest, prepared file hashes, execution recipe, measurement configuration and weighting. |
| `context_paths` | Where the agent finds sources, books, and feedback in its copied context. |
| `requirements` | Behavior to preserve and prohibited shortcuts. |
| `execution` | Time budget, allowed local tests, and network/evaluation restrictions. |

`task.library_reduction_target_percent` records the required time reduction.
`requirements.editable_source` limits source edits to the library. Application
code stays read-only. These constraints apply to every coding-agent runtime.

The task supplements the fixed optimizer prompt; it cannot relax the sandbox or
submission checks. Workload contents establish costs, not behavioral guarantees.

On later attempts a separate selection response contains `choice` (`revise` or
`restart`) and `reason`. The optimizer saves `starting-point.json` with source
hashes before creating its writable library. Its final report binds the task
IDs/hash, copied inputs, selected base, candidate manifest, and explanation.

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

## Planned history contract

This agreed extension is not yet implemented. Every optimizer request will link
a complete candidate ledger and a readable table generated from that ledger.
Each row identifies its candidate, base, contributing parents, proposal, changes,
correctness, library/application measurements and uncertainty, per-book
regressions, audit findings, unresolved questions, and evaluator version. Hashed
artifact references lead to the frozen source, patch, logs, and complete results.

Selection will name the starting candidate (or original), contributing candidate
IDs, and a reason. The submission will retain these links. References must resolve
to earlier frozen candidates; missing evidence is explicit. Results under older
checks remain readable but are marked stale for acceptance. Exact schema changes
will accompany implementation rather than claiming the current v1 supports them.
