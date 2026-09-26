# Optimization workflow

## Goal and status

Test whether an AI agent can make an application faster by specializing one of
its libraries while preserving supported behavior. The optimizer changes the
candidate, the evaluator measures it, the auditor investigates suspicious
shortcuts, and the controller coordinates their work.

The first controller implements this workflow for mdBook + elasticlunr-rs.
See [the command guide](../controller/README.md) to run it.

## 1. Establish a trustworthy starting point

Pin the application, original library, workloads, and evaluator configuration.
Establish baseline correctness and timing evidence, and obtain profiling evidence
showing where time is spent. Supply this context to the optimizer. Missing
profiling evidence must be reported; this design does not imply that an automated
profile collector already exists. Preserve the original library as the unchanged
reference.

**Output:** identified inputs, baseline results, and an explicit attempt budget.

## 2. Turn an observation into a justified proposal

The [optimizer](OPTIMIZER.md) connects an observed cost to code and identifies an
application guarantee that could eliminate unnecessary work. It explains why
supported behavior, including errors and uncommon inputs, should remain intact.
Patterns found only in the evaluation books are insufficient justification.

**Output:** one focused, source-backed proposal and its expected benefit.

## 3. Create a separate candidate

Implement the focused change in a separate library copy without changing the
original reference, application, workloads, or evaluator. Freeze the submitted
candidate so later measurements and findings refer to those exact files.
The optimizer may run local builds and correctness tests before submission;
official performance measurements and acceptance remain external.

**Output:** a candidate and explanation of the implemented change.

## 4. Evaluate and learn

The [evaluator](../documentation/EVALUATOR.md) checks generated output against the
original and measures both complete application time and indexing time. A
successful library improvement must meet the configured time-reduction target
at the lower end of its 95% confidence interval (default target: 20%). Application
timing is reported separately and does not block library success.

**Output:** correctness results, raw timings, and a verdict: incorrect, correct
but not clearly faster, or correct and measurably faster. Return the evidence to
the optimizer for a focused revision when appropriate and within the agreed
budget. Preserve earlier attempts instead of overwriting their evidence.

## 5. Audit and select

The controller invokes the [auditor](../documentation/AUDITOR.md) for every
submitted candidate, including candidates that fail correctness or show no
measurable improvement. The auditor reviews the frozen candidate and evaluation
evidence. It tests suspicious assumptions. A confirmed
gap becomes a check that passes the original and fails the offending candidate.
Rerun the candidate with the strengthened evaluator and record that version.

**Output:** reproduced findings, unresolved concerns, or no issue found within
the audit's scope. Return findings as revision feedback when appropriate. At the
chosen stopping condition, report what the evidence establishes. Unresolved
concerns must not become a clean audit or an accepted claim of correctness.

The [controller](CONTROLLER.md) manages up to five optimizer
attempts, each limited to ten minutes, plus evaluation and auditing time. Before
editing, the optimizer explicitly chooses to revise the previous candidate or
restart from the original. Stop at the first candidate that passes correctness,
meets the aggregate library time-reduction target, and has a completed
audit reporting no issue found. Show individual-book regressions prominently.
If no candidate qualifies within the budget, report that outcome.

## Agreed next step: carry the full history forward

Each new attempt will receive a concise table of every previous candidate and
access to all supporting evidence. The optimizer may revise any earlier
candidate, combine compatible ideas, or restart. Record the starting snapshot,
contributing candidates, and reason before editing; retain parent links after
submission. All combinations require their own evaluation and audit. This is
an approved extension to the current latest-candidate feedback loop; see
[the history design](CONTROLLER.md#agreed-next-step-complete-candidate-history).
