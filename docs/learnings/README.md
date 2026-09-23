# Exploration records and lessons

This directory preserves what we learned from investigations, experiments, and source reviews, including successful, failed, and inconclusive results. It is supporting evidence for the project, not a second specification. Read the [current scope](../scope.md) and [execution plan](../execution-plan.md) for what we have agreed to do now.

As of 2026-09-23, the next milestone is one supervised non-Python specialization pilot. The Python/GraalPy investigation is set aside; it did not establish complete protected execution or a real specialization speedup. Research into reusable automation and general adversarial protection remains relevant to later v1 work.

## Reading order

| Order | Record | Contents and outcome |
| --- | --- | --- |
| 1 | [Python exploration summary](python-exploration.md) | The connected account of the original candidates, baseline results, protection experiments, remaining problems, and why we changed direction. Start here for the overall lesson. |
| 2 | [Python candidate assessment](candidate-assessment.md) | Exact application/library versions, real workload sources, original tests, exploratory timings, and reproduction. Establishes baseline execution and possible opportunity, not specialization gains or selection for the new pilot. |
| 3 | [Execution and isolation feasibility](execution-feasibility.md) | Agent execution, external checking, restricted environments, test adapters, and the test-only engine investigation. Several bounded checks worked; faithful protection of complete original suites remained unresolved. |
| 4 | [Reward-hacking findings](reward-hacking-findings.md) | Findings F-01–F-21, with mechanisms, results, failed attempts, and limits. Distinguishes deliberately constructed attacks, ordinary harness defects, source-reviewed concerns, and reproduced defenses. |
| 5 | [Runnable reward-hacking examples](reward-hacking/README.md) | Small complete Python programs demonstrating forged test success, separate assertions, timer tampering, and lost shared-object behavior. Read these earlier if you prefer learning by running code. |
| 6 | [Defense investigation](reward-hacking-defense.md) | Published research and local evidence about misleading success, hallucinations, test omissions, data exposure, and candidate interference. Proposed controls are distinguished from tested protection. |
| 7 | [SkyDiscover assessment](skydiscover-assessment.md) | Source review and isolated helper tests identifying useful ideas and possible code reuse. It does not establish adoption or an executed complete SkyDiscover workflow; accepted follow-up work is in the current plan. |

## How to maintain these records

Record the question, source revisions and environment, what actually ran, the result, its limits, and the resulting lesson or decision. Distinguish inspected source, proposed work, executed experiments, and independently reproduced results. Preserve failed attempts and explain corrections rather than silently replacing unfavorable evidence.

Keep the date and scope of each result visible. When a direction changes, add a status note linking to the current decision instead of treating an old proposed next step as active work. Promote accepted requirements or decisions into the current documents in `docs/`, with a link back to the supporting record.

Some reports refer to temporary external experiment directories. Their local paths may be unavailable on another machine or disappear later; the reports state those limits. No new experiments were run as part of this documentation reorganization.
