# Reading the Just-in-Time Library documentation

Just-in-Time Library is a proposed system that specializes an external library for the way a particular application uses it. The goal is to make that application faster while preserving its behavior and providing results the user can reproduce without the generation system.

This directory is the starting point for understanding the project. It assumes a computer science background but no prior knowledge of our work. Documents directly in `docs/` describe the current agreed scope, plan, and, when available, design and implementation. Exploration records belong in [`docs/learnings/`](learnings/README.md), whether the exploration succeeded, failed, or remains inconclusive.

**Current direction, 2026-09-23:** run one supervised experiment with a non-Python application and library to test the performance hypothesis. The reusable generator and general adversarial-protection machinery are deferred. The Python candidate and isolation reports preserve earlier research; they do not describe an adopted implementation or completed first version.

## Recommended reading order

| Order | Document | What you will learn |
| --- | --- | --- |
| 1 | [Project scope](scope.md) | What we intend to build, what falls within the first version, and what counts as success. Defines the main terms, the three repository roles, correctness and performance requirements, agent restrictions, and independent reproduction. This is the authoritative record of agreed requirements. |
| 2 | [Execution plan](execution-plan.md) | How we plan to reach those goals, which phases have made progress, and what evidence we need before moving forward. Read this to understand the current position and remaining work. |
| 3 | [Learnings index](learnings/README.md) | Optional supporting research: what we explored, what the evidence established, and how it affected the project. Start with the Python exploration summary, then use the index to find detailed reports or runnable examples. |

## Where information belongs

- **`docs/`: current project guidance.** Keep accepted requirements, current decisions, planned work, and implementation status here. Distinguish the immediate pilot from later v1 work and proposed behavior from implemented behavior. Remove superseded instructions from the current plan and link to their research record.
- **`docs/learnings/`: exploration evidence.** Keep dated questions, methods, results, limitations, and conclusions here, including successful findings and runnable examples. A useful finding stays here even when it informs an accepted decision; record that decision in the relevant current document and link back to its evidence.

The scope and execution plan are authoritative for current work. A historical report may describe an approach we no longer pursue or an earlier proposed next step; it does not override them. Keep research dates and outcomes intact, correct factual errors explicitly, and state when a later decision supersedes an earlier recommendation. This avoids maintaining two competing versions of the current plan.

Some learning records link to external experiment directories containing source snapshots, scripts, raw results, and reproduction instructions. Those artifacts are outside this repository; some locations are temporary. A report or a successful small experiment does not establish that the complete system works.
