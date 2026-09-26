# Optimization workflow

## Goal

Specialize a library for an application's usage and supplied workload while
preserving behavior for new inputs and supported configurations. The optimizer
changes the library, the evaluator checks and measures it, the auditor searches
for invalid shortcuts, and the controller coordinates the experiment.

## 1. Establish the baseline

Pin the application, original library, workloads, and measurement settings. Run
a validated original-versus-original self-check. Preserve those inputs and make
the complete prepared workload available to the optimizer. Supply profiles when
available; missing profiles remain explicit.

## 2. Investigate and choose

Give each attempt a concise table of every previous attempt and access to the
complete supporting evidence. In one continuous session, the optimizer studies
workload characteristics, application guarantees, costs, and earlier results.
It may collect local diagnostic profiles and benchmarks.

It chooses the original or any earlier candidate and may combine compatible
ideas. A runner checkpoint records the base, contributing candidates, and reason
before copying the chosen library into the writable workspace.

## 3. Implement a specialization

The optimizer connects workload characteristics to unnecessary library work and
implements an appropriate change. Algorithm and data structure redesigns across
multiple library files are allowed. Application code stays read-only.

The supplied books do not define all supported inputs. Application guarantees
can justify removing work; merely common input patterns need correct handling
of other inputs. Local correctness tests and diagnostic measurements guide the
attempt. Another checkpoint records any change of starting point.

Freeze the submitted library, proposal, patch, parentage, and local evidence.
Always keep the original library as the independent comparison reference.

## 4. Evaluate and audit

Compare generated outputs and run correctness checks. Measure complete
application builds and library indexing, serialization, and cleanup. The default
success target is a 20% reduction in library time, met at the lower end of the
95% confidence interval. Application timings and per-book regressions remain
visible but do not block library success.

Audit every submitted candidate, including failed or slower ones. Reproduced
violations can add checks. Record the new evaluator version, refresh the
self-check, and reevaluate before accepting a candidate. Older results remain
visible and are marked stale when their checks change.

## 5. Learn or finish

Return results and findings through the growing history. The next attempt can
build on any prior candidate rather than only the latest one. No-change attempts
and unresolved questions remain visible too.

The controller permits at most five attempts, each with up to ten minutes of
agent time. Evaluation and auditing take additional time. Stop at the first
candidate that passes correctness, meets the library target, and has a completed
audit reporting no issue found. Otherwise report why no candidate qualified.

See the [controller guide](../controller/README.md),
[optimizer responsibilities](OPTIMIZER.md), and [contracts](../controller/CONTRACTS.md).
