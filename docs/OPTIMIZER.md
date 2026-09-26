# Optimizer

## Purpose

The optimizer is an AI agent that proposes and implements a library change to
make an application faster without changing its supported behavior. The project
goal is described in [GOAL.md](../documentation/GOAL.md).

The optimizer supports mdBook with elasticlunr-rs. Its coding agent is configurable:
Codex CLI (default, `gpt-6-sol`), Claude Code, or OpenCode with a locally hosted
model. Changing the agent does not change its responsibilities or acceptance
checks. See [runtime setup](../coding_agents/README.md).

## Inputs

The first implementation requires a completed evaluator self-check with status
`validated`. Each command makes one attempt, with a default agent limit of ten
minutes. It starts from the original library unless a previous candidate is
supplied; then a separate selection step chooses revise or restart before edits.
Selection and editing share the agent budget. See the
[optimizer command guide](../optimizer/README.md).

Provide the application and original library sources, representative workloads,
baseline evaluation results, and any available profiling evidence. Include the
behavior that must be preserved and the permitted editing boundaries. On later
attempts, also provide evaluator results and auditor findings from earlier
candidates.

Missing measurements must remain visible. Source inspection may suggest where
time is spent, but it cannot substitute for a measured profile or speedup.

## One focused attempt

1. Read the application and library code to understand how the application uses
   the library and what work it requires.
2. Identify a concrete source-backed guarantee that could remove unnecessary
   work. Explain why it holds for supported inputs, rather than only for the
   evaluation books.
3. Propose one focused change and explain its expected benefit and behavior
   preservation, including errors and uncommon inputs.
4. Implement that change in a separate candidate copy. Preserve the original
   library as the reference.
5. Return the candidate, explanation, source references, and results of any local
   checks actually run. Clearly label expectations that remain untested.

## Feedback and boundaries

The optimizer may run local builds and correctness tests to check its edits.
Official performance measurements and acceptance remain outside the optimizer;
local checks do not replace independent evaluation.

The optimizer may revise a candidate after independent evaluation or auditing.
Each submitted revision is a new attempt with retained evidence. It must not
change reference outputs, weaken evaluator checks, alter workloads to hide
failures, or treat its own explanation as a performance verdict.

The [evaluator](../documentation/EVALUATOR.md) decides whether correctness and
measured performance pass. The [auditor](../documentation/AUDITOR.md) investigates
whether the candidate exploits gaps in those checks. Coordination belongs to
the [controller](CONTROLLER.md).
