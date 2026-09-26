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
rerun the frozen candidate against it. Keep earlier results attached to the
version that produced them.

The output is an experiment history: candidate identities, evaluation results,
audit findings, revisions, and the reason the experiment stopped. The controller
must not label a candidate successful on the optimizer's assertion alone.

## Agreed first-version policy

- Run at most five optimizer attempts, with up to ten minutes per attempt.
  Evaluation and auditing take additional time; this is not a fifty-minute
  limit for the whole experiment.
- Audit every submitted candidate, regardless of its evaluation verdict. If
  missing evidence prevents an audit from completing, record that limitation;
  the candidate cannot qualify with an incomplete audit.
- Stop at the first qualifying candidate, or when the attempt budget is used.
  Qualification requires passing correctness, an aggregate improvement beyond
  measurement noise in both indexing and complete book-building time, and a
  completed audit reporting no issue found. No issue found is limited to the
  audit's scope; it is not proof that no violation exists.
- Let the optimizer explicitly choose whether to revise the previous candidate
  or restart from the original. Record the choice and its reason before editing.
  Always compare candidates against the unchanged original library.
- Retain the evaluator's existing aggregate performance rule. Prominently show
  individual-book regressions; aggregate improvement does not mean every book
  improved. Results must use the current checks before they can qualify.

These policies are implemented by the controller. Standalone component commands
perform one operation and do not run the experiment loop.

See [WORKFLOW.md](WORKFLOW.md) for how the roles connect.
