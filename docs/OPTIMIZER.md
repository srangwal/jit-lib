# Optimizer

## Purpose

Specialize elasticlunr-rs for how mdBook uses it. The optimizer receives the full
supplied workload and uses its characteristics to find unnecessary library work.
It changes library code only; application code remains read-only.

The workload guides optimization, but does not limit correctness to those books.
New book contents and supported configurations must still work, including errors
and uncommon inputs. Remove general-purpose work only when application guarantees
make it unnecessary; use guards and correct fallbacks for observed patterns.

## Inputs

Start with a validated evaluator self-check. Provide pinned application and
original-library sources, all prepared workload files and configurations,
baseline results, available profiles, and the experiment history. The history
includes every earlier attempt, source snapshot, proposal, patch, measurement,
confidence interval, regression, audit finding, and supporting log.

The controller supplies two values in `objective.json`: a fixed acceptance
threshold and this attempt's stretch target. The stretch target is the larger
of acceptance and 1.5 times the best previous measured library reduction, capped
at 95% unless acceptance is higher. Only complete independent evaluations that
passed correctness and audits with no issue found are eligible, using the current
checks. Without eligible history, the two targets are equal. Every reduction
compares with the original library, regardless of the chosen starting candidate.

The coding agent is configurable: Codex, Claude Code, or OpenCode with a local
model. See the [command guide](../optimizer/README.md).

## One continuous attempt

One prompt and one agent session cover investigation, choosing a base, editing,
and local testing. The default budget is ten minutes for all of these together.
Maximize supported gains within that budget. The stretch target guides ambition;
neither target is a ceiling or a reason to stop investigating. Reserve time to
test and submit the strongest supported candidate, even if it misses the stretch
target.

1. Inspect the actual workloads, application usage, profiles, and history.
2. Compare opportunities: connect a workload characteristic to a library cost,
   a safe specialization, and an expected benefit.
3. Choose the original or any earlier candidate. Record the starting snapshot,
   contributing candidates, and reasons through a runner checkpoint before edits.
4. Implement the change in the writable library. Larger algorithm or data
   structure changes across several files are allowed; a small diff is not the goal.
5. Run local correctness checks, profiling, and exploratory benchmarks as useful.
   Record commands, inputs, settings, results, and uncertainty. These measurements
   are diagnostic; they cannot establish acceptance.
6. Submit the candidate, proposal, source evidence, local results, and risks, or
   return `no-change` if no useful change is justified.

The agent can change direction within its session by requesting another base
checkpoint. The runner preserves abandoned work and the decision history.
Combining ideas creates a new candidate requiring its own evaluation and audit.

## Boundaries and acceptance

Keep the original, application, workload, checks, and prior evidence protected.
Do not weaken tests, recognize benchmark identities, precompute answers, or alter
dependency versions. Missing evidence must remain explicit.

The evaluator measures library indexing, serialization, and cleanup. The lower
end of its 95% time-reduction interval must meet the configured acceptance
threshold (default 20%); the stretch target does not change this rule. Correctness must
pass and the auditor must find no unresolved issue. Application performance is
reported separately and does not block library success. The optimizer cannot
accept its own candidate; the [controller](CONTROLLER.md) makes that decision.
