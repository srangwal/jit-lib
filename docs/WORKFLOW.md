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

Supply two targets: the experiment's fixed acceptance threshold, and a stretch
target for this attempt. The stretch target is the larger of acceptance and
1.5 times the best earlier measured library reduction, capped at 95% unless
acceptance is higher. With no eligible result, use acceptance. Only complete
independent evaluations that passed correctness and audits with no issue found
count, and measurements must use the current checks. Local estimates do not count.
The optimizer aims to maximize gains, not merely reach either target.

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
self-check, and reevaluate the current candidate followed by all earlier
candidates whose audit found no issue. Use the refreshed results for targets
and selection. Earlier results stay visible with their old version. These are
new evaluations, not new audits; the same frozen candidate retains its audit,
and confirmed or unresolved findings cannot be cleared by reevaluation.

## 5. Learn or finish

Return results and findings through the growing history. The next attempt can
build on any prior candidate rather than only the latest one. No-change attempts
and unresolved questions remain visible too.

Run at least three attempts, even if an earlier candidate qualifies. After the
third attempt, select the best qualifier from all attempts. If none qualifies,
continue up to the configured limit (three to five, default five), stopping
when one qualifies. Rank qualifiers by the lower end of their 95% library
time-reduction interval; exact ties favor the earlier attempt.

Each attempt has up to ten minutes of agent time; evaluation and auditing take
additional time. No-change responses count as attempts. Infrastructure failures
and cancellation can stop the experiment before three attempts. If the budget
ends without success, report why no candidate qualified and retain every result.

See the [controller guide](../controller/README.md),
[optimizer responsibilities](OPTIMIZER.md), and [contracts](../controller/CONTRACTS.md).
