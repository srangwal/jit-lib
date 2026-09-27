# Controller

## Purpose and status

The controller is ordinary orchestration code that coordinates the optimizer,
evaluator, and auditor. It manages the experiment; it does not invent library
changes or replace independent correctness and performance checks.

The first implementation is in `controller/`. Existing optimizer, evaluator and
auditor commands remain independently usable. See the
[command guide](../controller/README.md) and [contracts](../controller/CONTRACTS.md).

## Inputs and responsibilities

Start with pinned application, original library, and workload versions; evaluator
configuration; optimizer settings; and an explicitly chosen experiment budget.
Record the versions and effective settings used for each attempt.

The controller should:

- Give the optimizer readable context and a separate writable candidate copy.
- Preserve the original reference, workloads, checks, and prior evidence.
- Freeze each submitted candidate before independent evaluation or auditing.
- Run the evaluator and pass its actual results back to the optimizer.
- Invoke the auditor for every submitted candidate, including candidates that
  fail correctness or show no measurable improvement.
- Retain unsuccessful attempts, findings, logs, and links between revisions.
- Stop when the agreed budget or stopping condition is reached, and report the
  result supported by the available evidence.

Write boundaries must be enforced by the chosen execution setup, not merely
requested in a prompt. Any limits to that enforcement must be stated.

## Standard communication and debugging

Each component handoff should have its own versioned JSON contract suited to
its task. Contracts do not need an identical envelope or payload. Use consistent
experiment, attempt, request, and artifact identities to connect the records.
The existing components write JSON reports; the controller adapters link and
validate these contracts before using them. Missing, malformed, or unsupported
records produce an explicit failure.

Each request and result should identify the experiment, attempt, step, component,
and request it answers. Record timestamps, effective settings and code versions,
input and output file references with hashes, and a short explanation. Use
relative artifact paths so an experiment directory can be moved. Large source
trees, logs, prompts, responses, patches, and measurements remain separate files
referenced by these records. Do not include credentials in recorded settings.

Keep execution status separate from the component's conclusion: an evaluator
can finish normally and report incorrect behavior. Preserve component-specific
results in their own contracts. Distinguish agent-reported claims from
observed command results, measurements, and reproduced audit findings.

The controller should maintain an append-only `events.jsonl` timeline with
ordered event IDs. Record component starts, meaningful phase changes, completion,
errors, timeouts, feedback, and controller decisions. Every decision must name
its reason and supporting result. Link retries and revisions to their earlier
steps; never overwrite earlier requests or evidence. Interrupted steps remain
visibly incomplete. Added audit checks must record the evaluator version change
and which earlier results require reevaluation.

Generate a readable `report.md` from these same records. A person should be able
to follow each loop from request to candidate, evaluation, audit, feedback, and
next action, then open the exact supporting files. Preserve raw tool logs as
additional evidence; controller decisions must not depend on parsing console text.

The implementation uses component-specific contracts and validation, adapters
around existing commands, and structured phase events inside components. Tests
cover malformed results, wrong attempt IDs, changed artifacts, interrupted
steps, report generation, and repeated optimization decisions.

## Decisions and outputs

Keep correctness failures, inconclusive timings, measured improvements,
unresolved audit concerns, and incomplete runs distinct. A faster measurement
cannot excuse changed supported behavior. A failed tool call cannot become a
successful verdict.

When an audit adds a validated check, preserve the new evaluator version and
run a fresh self-check. Reevaluate the current frozen candidate, then every
earlier candidate whose audit found no issue. These fresh measurements support
future targets and selection; old measurements retain their evaluator version.
The prior audit still applies to the same frozen code, and is not rerun by this
step. Reevaluation never clears a confirmed violation or unresolved audit finding.

The output is an experiment history: candidate identities, evaluation results,
audit findings, revisions, and the reason the experiment stopped. The controller
must not label a candidate successful on the optimizer's assertion alone.

## Agreed first-version policy

- Run at least three optimizer attempts and at most five. Each attempt defaults
  to ten minutes; a per-run override can increase its limit to four hours.
  Auditor agent calls have a separate configurable limit, and the whole audit
  has an outer limit covering all calls and probes. Evaluation and auditing take
  additional time. No-change responses count as attempts;
  infrastructure failures or cancellation can stop the run sooner.
- Audit every submitted candidate, regardless of its evaluation verdict. If
  missing evidence prevents an audit from completing, record that limitation;
  the candidate cannot qualify with an incomplete audit.
- From attempt three onward, stop once any candidate qualifies, or when the
  attempt budget is used. Select the qualifier with the highest lower confidence
  bound; exact ties favor the earlier attempt.
  Qualification requires passing correctness, a lower 95% confidence bound for
  aggregate library time reduction that meets the configured target (default
  20%), and a completed audit reporting no issue found. Application timing is
  reported separately and does not block library success. No issue found is limited to the
  audit's scope; it is not proof that no violation exists.
- Let the optimizer choose the original or any earlier candidate, and combine
  compatible ideas. Record the base, contributing parents, and reason before editing.
  Always compare candidates against the unchanged original library.
- Measure library indexing, serialization, and cleanup with the existing timer.
  Use equal book weights and prominently show individual-book regressions.
  Results must use the current checks and recorded target before they qualify.
- The optimizer may change library code only. Keep application sources protected;
  changing the application is not a valid optimization.

These policies are implemented by the controller. Standalone component commands
perform one operation and do not run the experiment loop.

## Acceptance and stretch targets

The acceptance threshold is configured before the experiment and stays fixed.
Each optimizer attempt also receives a stretch target:

```text
stretch = max(acceptance threshold, min(95%, 1.5 × best previous measured reduction))
```

Use the best measured aggregate library reduction from any earlier candidate
that passed correctness and a completed audit with no issue found. Its evaluation
must be complete and use the current checks. With no eligible result, use the
acceptance threshold. A worse attempt does not lower the target while the same
best result remains eligible. All gains compare with the original library.

For a 20% acceptance threshold, an earlier 19% measured reduction sets the next
stretch target to 28.5%. The optimizer should aim beyond that target where
feasible. The 95% ceiling never lowers a higher acceptance threshold. Stretch
uses a measured estimate; acceptance still uses the lower 95% confidence bound.
Record both targets and the evidence used for the calculation in each task.

## Complete candidate history

Before every attempt, the controller provides a concise table of **every**
earlier attempt, plus read-only access to the supporting evidence. The optimizer
uses one continuous session to investigate, choose a base, edit, and test.

| Each entry contains | Purpose |
| --- | --- |
| Candidate ID, starting candidate, proposal, and changes | Understand what was tried and why. |
| Correctness, library/application measurements, and confidence intervals | See outcomes and measurement uncertainty. |
| Per-book regressions, audit findings, and unresolved questions | Avoid repeating failures or overlooking concerns. |
| Source snapshot, patch, logs, and evaluator version | Inspect and reproduce the exact attempt. |

The optimizer may choose any earlier candidate, combine compatible ideas from
several candidates, or restart from the original. Before editing, record the
chosen starting snapshot, all contributing candidate IDs, and the reason for
the choice. A trusted runner checkpoint copies the chosen library into the workspace.
The new candidate records those parent links and its exact patch so
a reader can follow its evolution. Combining ideas creates a new candidate that
needs fresh evaluation and audit; parent results do not transfer automatically.

Preserve old measurements with their evaluator version and mark them stale when
checks change. Every candidate still compares against the unchanged original.
Missing evidence and attempts that produced no candidate remain visible.

The full workload is available to the optimizer, but is not an exhaustive list
of supported inputs. Require correct behavior for new book contents and supported
configurations. Workload patterns guide optimization; application guarantees or
correct runtime guards justify restrictive assumptions.

See [WORKFLOW.md](WORKFLOW.md) for how the roles connect.
