# Controller

## Purpose and status

The controller is ordinary orchestration code that coordinates the optimizer,
evaluator, and auditor. It manages the experiment; it does not invent library
changes or replace independent correctness and performance checks.

This is a proposed design. Implementing the complete controller is deferred;
the current implementation task is the optimizer. Existing evaluator and auditor
commands remain independently usable.

## Inputs and responsibilities

Start with pinned application, original library, and workload versions; evaluator
configuration; optimizer settings; and an explicitly chosen experiment budget.
Record the versions and effective settings used for each attempt.

The controller should:

- Give the optimizer readable context and a separate writable candidate copy.
- Preserve the original reference, workloads, checks, and prior evidence.
- Freeze each submitted candidate before independent evaluation or auditing.
- Run the evaluator and pass its actual results back to the optimizer.
- Invoke the auditor according to the eventually selected audit policy.
- Retain unsuccessful attempts, findings, logs, and links between revisions.
- Stop when the agreed budget or stopping condition is reached, and report the
  result supported by the available evidence.

Write boundaries must be enforced by the chosen execution setup, not merely
requested in a prompt. Any limits to that enforcement must be stated.

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

## Audit scheduling

Whether auditing happens after every run, every qualifying improvement, or a
batch of runs remains undecided. A final audit before accepting an improvement
is the current recommendation, not an implemented scheduling or acceptance rule.

See [WORKFLOW.md](WORKFLOW.md) for how the roles connect.
