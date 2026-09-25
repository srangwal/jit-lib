# Optimization workflow

## Goal and status

Test whether an AI agent can make an application faster by specializing one of
its libraries while preserving supported behavior. The optimizer changes the
candidate, the evaluator measures it, the auditor investigates suspicious
shortcuts, and the proposed controller coordinates their work.

This is the intended workflow. Implement the optimizer first; the complete
controller and automatic audit scheduling are deferred.

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
worthwhile improvement must exceed measurement noise in both metrics.

**Output:** correctness results, raw timings, and a verdict: incorrect, correct
but not clearly faster, or correct and measurably faster. Return the evidence to
the optimizer for a focused revision when appropriate and within the agreed
budget. Preserve earlier attempts instead of overwriting their evidence.

## 5. Audit and select

When invoked, the [auditor](../documentation/AUDITOR.md) reviews the frozen
candidate and evaluation evidence. It tests suspicious assumptions. A confirmed
gap becomes a check that passes the original and fails the offending candidate.
Rerun the candidate with the strengthened evaluator and record that version.

**Output:** reproduced findings, unresolved concerns, or no issue found within
the audit's scope. Return findings as revision feedback when appropriate. At the
chosen stopping condition, report what the evidence establishes. Unresolved
concerns must not become a clean audit or an accepted claim of correctness.

The proposed [controller](CONTROLLER.md) will manage these transitions. A final
audit is recommended before accepting an improvement; the acceptance policy
still needs to be decided.
