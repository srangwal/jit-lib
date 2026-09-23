# Reading the Just-in-Time Library documentation

Just-in-Time Library is a proposed system that specializes an external library for the way a particular application uses it. The goal is to make that application faster while preserving its behavior and providing results the user can reproduce without the generation system.

These documents explain the agreed requirements, the work planned to meet them, and the research completed so far. They assume a computer science background but no prior knowledge of this project. Start with the first two documents for the overall picture, then follow the order below for the supporting evidence.

**Current direction, 2026-09-23:** run one supervised experiment with a non-Python application and library to test the performance hypothesis. The reusable generator and general adversarial-protection machinery are deferred. The Python candidate and isolation reports preserve earlier research; they do not describe an adopted implementation or completed first version.

For a connected account of the earlier work, read the [archived Python exploration](archive/python-exploration.md). It summarizes the candidates, baseline results, protected-test experiments, unresolved problems, and why we moved to a different path. The detailed reports below retain the supporting evidence.

## Recommended reading order

| Order | Document | What you will learn |
| --- | --- | --- |
| 1 | [Project scope](scope.md) | What we intend to build, what falls within the first version, and what counts as success. Defines the main terms, the three repository roles, correctness and performance requirements, agent restrictions, and independent reproduction. This is the authoritative record of agreed requirements. |
| 2 | [Execution plan](execution-plan.md) | How we plan to reach those goals, which phases have made progress, and what evidence we need before moving forward. Read this to understand the current position and remaining work. |
| 3 | [Candidate assessment](candidate-assessment.md) | Why we previously investigated yamllint with PyYAML and MkDocs with Python-Markdown. Records their real input sources, original-library test and timing results, possible optimization opportunities, and unresolved workload choices. These historical measurements establish starting points, not achieved specialization speedups or selection for the new pilot. |
| 4 | [Execution and isolation feasibility](execution-feasibility.md) | What we have tested about running coding agents and evaluating their output safely. Explains how a library can falsify test success, why separating tests from library execution is difficult, and which parts of that separation have worked so far. |
| 5 | [Reward-hacking findings](reward-hacking-findings.md) | The detailed experiments behind the feasibility report. Each numbered finding explains the mechanism, what we ran, the observed result, its limitations, and where to find the evidence. Start with F-01 and F-02 for the original test-runner problem and basic defense, then read the later findings for the remaining difficulties. |
| 6 | [Reward-hacking defense investigation](reward-hacking-defense.md) | How published research and our experiments inform the protections we need. Covers fabricated results, missing checks, unsupported assumptions, data access, and misleading measurements. Distinguishes controls we propose from protections we have tested. |
| 7 | [SkyDiscover assessment](skydiscover-assessment.md) | Which ideas and implementation pieces from the related SkyDiscover project could help us. Explains experiment construction, auditing, generated-test validation, and optimization search, along with compatibility gaps and the limits of our review. Recommendations here do not establish that we have adopted or implemented those components. |

## Keep requirements, plans, and evidence distinct

For hands-on examples alongside the feasibility and findings reports, use
[the runnable reward-hacking experiments](reward-hacking/README.md). They include
complete Python code, expected results, and small changes to try, with no external
dependencies. Start there if you want to see how forged success and protected
assertions work before reading the detailed research.

Use the **scope** to determine what the system must do and the **execution plan** to find current progress. Use the research reports to understand why we made recommendations and what the experiments establish. A successful small experiment does not establish that the complete system works.

Some reports link to external experiment directories containing source snapshots, scripts, raw results, and reproduction instructions. Those are supporting research artifacts outside this repository. Follow their READMEs when reproducing a particular experiment; the documents here explain its purpose and conclusions. Some artifact locations are temporary, as noted in the reports.
