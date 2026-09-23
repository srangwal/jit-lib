# Python exploration: results and why we moved on

Exploration record updated: 2026-09-23. This summarizes the recorded investigation; creating this document did not rerun the experiments.

We investigated two Python application–library pairs and several ways to protect their tests from generated library code. Original applications built, their ordinary suites passed, and real workloads ran reproducibly. We also demonstrated a library reporting test success without executing assertions. Separating tests from library execution defeated that attack in small examples, but changed legitimate Python behavior in larger ones. Later experiments repaired individual problems without establishing one complete, faithful, protected arrangement.

We abandoned this path as the active route to the first specialization experiment because it was turning into a general Python execution-isolation project. Our objective is to discover whether application-specific library specialization produces substantial performance gains. On 2026-09-23, the user chose a non-Python pair and one supervised pilot before reusable automation and general adversarial protection. We did not prove that Python protection is impossible, or that Python specialization cannot be valuable. No real specialization speedup was measured during this investigation.

## 1. The original plan and candidates

The proposed generator would examine an application and one dependency, use Codex CLI to generate library changes, and evaluate those changes independently. Application calls would stay unchanged; only the dependency reference would change. Separate external application and library checkouts, plus a standalone experiment directory, would let the user build, test, and reproduce the result without the agent.

We selected the following pairs for initial research:

| Application and library | Real workload | Recorded ordinary baseline |
| --- | --- | --- |
| yamllint 1.38.0 / PyYAML 6.0.3 | Lint Kubespray's actual configuration, covering 575 YAML files | 430 application tests successful; 1,283 pure-Python library tests passed |
| MkDocs 1.6.1 / Python-Markdown 3.10.3 | Build complete HTTPX and Django REST framework documentation sites with their real configurations and assets | 724 application tests per environment, including 4 existing skips; 1,088 library tests, including 12 existing skips; integration builds across two themes and four projects |

These were complete real project jobs, which the user accepted as suitable workloads. They were not invented parser inputs or production traffic traces. Separate held-out evaluation was still required.

Five-run baseline medians were approximately 1.203 seconds for Kubespray, 0.540 seconds for HTTPX, and 1.029 seconds for DRF. Exploratory instrumentation attributed substantial time to the dependency interfaces, but introduced overhead; Markdown calls also included extension and highlighting work. These measurements justified investigation, not a claim that specialization would meet either target.

Standalone baseline reproduction succeeded. A comparison initially found process-dependent object addresses in one generated HTTPX page. A narrow, baseline-derived normalization handled those addresses while retaining checks on all other content and rejecting deliberately altered outputs. The strict comparison failure and raw records were preserved. Full ordinary suites also passed in Linux containers after missing locale and native Tidy prerequisites were supplied without changing tests or skip rules.

Exact revisions, commands, counts, timing limitations, and comparison rules are in the [candidate assessment](candidate-assessment.md). Linux evidence is in the [feasibility report](execution-feasibility.md#original-full-suite-compatibility-on-linux). These are ordinary compatibility results: tests and library code still shared an interpreter.

## 2. What execution feasibility established

The initial feasibility experiment used a small synthetic application before attempting either real pair. A live Codex invocation changed two library files; the application stayed unchanged. The candidate was frozen, exported as a commit atop the fixture baseline, and reproduced without Codex. This was a demonstration of execution and delivery, not one of the required real-world specializations.

The experiments also exercised restricted filesystem access, separation of model-provider communication from candidate network access, read-only sources, external result comparisons, external elapsed-time measurement, and termination of detached child processes. An early invocation exited successfully but reported an incomplete task because a runtime component was missing. That showed why process exit, completed work, required artifacts, and correctness must be checked separately.

Several failures were in our own experiment tooling. A reproduction created Python bytecode in a directory required to stay unchanged; the recorder was fixed and rerun without weakening that requirement. Earlier sandbox setup failures were retained. These were not evidence of an agent deliberately cheating.

The [feasibility results](execution-feasibility.md#results-and-evidence) and findings [F-03 through F-08](reward-hacking-findings.md#f-03-success-shaped-output-and-exit-status-can-disagree-with-actual-work) document these controls and their limits. Passing bounded probes did not establish protection against every possible attack.

## 3. The central failure: unchanged tests can report false success

In ordinary Python execution, a library and the test runner can access the same mutable interpreter objects. Our deliberately constructed library variant replaced `unittest.TestCase.run` in memory. Its replacement announced that each test started and succeeded, but never called the test body or its assertions.

The test files stayed unchanged. The runner printed the expected test count and `OK`, and exited successfully. Even a test deliberately written to fail appeared to pass. Meanwhile, the library retained its genuine application function, so all six independent application replays still matched the original output.

This demonstrated three distinct facts: protecting files does not protect live interpreter state; a reported test count does not prove assertions ran; and matching a finite set of application outputs does not establish repository-test integrity. A container around both library and tests protects the outside controller, but leaves this shared-interpreter relationship intact.

The user initially required the reusable system to protect repository assertions as well as external output checks. We therefore could not close Phase 2 merely by running the original suites inside a container. See [F-01](reward-hacking-findings.md#f-01-a-library-can-make-repository-tests-report-success-without-running-their-assertions) for the full code and exact sequence. These attack variants were deliberately constructed experiments, not observed misconduct by the live coding agent.

## 4. Separate processes worked for simple interfaces

We moved the original test assertions into a trusted parent process and ran the selected library in a restricted worker. An adapter forwarded allowed calls and returned bounded data. The parent compared that data with its own expectations; it did not accept the worker's claimed verdict.

For the simple fixture function, this worked. Correct answers passed, wrong answers failed, malformed or missing replies were rejected, and a mandatory parent assertion still failed even when the worker replaced its own test runner. Independent reproduction confirmed this limited result.

A related timer experiment replaced the worker's clock with a function returning zero. The parent's clock still measured elapsed execution. That protected the tested timing boundary, but did not establish how to attribute logical library work within a complete application.

We also exercised a small subset of SkyDiscover's suite and generated-test-validation helpers. A test could distinguish ordinary wrong output while still being defeated by runner forgery. This showed that validating a test against one deliberate fault does not protect it against all other faults. We did not execute or defeat the complete upstream auditor or workflow. See [F-02](reward-hacking-findings.md#f-02-separating-assertions-from-candidate-execution-defeats-the-fixture-attack), [F-04](reward-hacking-findings.md#f-04-a-candidate-can-replace-an-in-process-clock), and [F-05](reward-hacking-findings.md#f-05-passing-mutation-validation-does-not-protect-a-test-runner).

## 5. Real Python interfaces made separation difficult

Real tests exercise more than input bytes and output bytes. The application and library share objects, modify them, define subclasses, call each other's functions, and observe interpreter state. A protective adapter must preserve those interactions while preventing library code from taking control of the checker.

For example, if two references originally point to one list, copying that list twice changes behavior: mutation through one reference no longer appears through the other. Returning an object that executes arbitrary library code inside the parent would restore some interactions while undermining the separation.

The investigation progressed through these bounded results:

| Stage | What worked or failed | What remained unresolved |
| --- | --- | --- |
| Selected library tests, F-09–F-10 | Selected tests retained parent-owned assertions, but an added check exposed copied Markdown metadata that lost shared identity and mutation | Passing a selected subset did not establish a faithful adapter |
| MkDocs callbacks, F-11–F-12 | Eleven existing title tests and five page-render tests worked with narrow callback protocols; added controls checked state and rejected specified faulty messages | Arbitrary callbacks, shared objects, and the full application suite were not covered |
| Full-suite inventories, F-13–F-14 | Required tests and interfaces were recorded; small controls exposed lost YAML aliases/cycles and a Markdown recursion-test failure after moving execution to a worker | Even unchanged original libraries could behave differently through the adapter |
| Recursion context, F-15 | Measured context transfer preserved one existing recursion-test family and supplemental comparisons | Observable recursion limits and arbitrary caller frames were not generally preserved; this was not a security mechanism |
| Shared object graphs, F-16 | A bounded representation preserved tested aliases, cycles, and mutation; ordinary and restricted-container runs were independently repeated | General classes, streams, callbacks, and all object types were not integrated |
| Inheritance and callbacks, F-17 | Seven unchanged extension-class tests and added controls passed, including independent container reruns | The callback contract was narrow; added mandatory assertions needed explicit markers |
| Caller-defined classes, F-18 | Reduced PyYAML fixtures preserved selected base-method calls and caller-owned objects, with an independent repeat | These were not complete unchanged upstream tests; exception and object rules still differed from other prototypes |
| Registration plus rendering, F-19 | One unchanged serializer test and additional controls exercised actual selected Markdown rendering in one session, with an independent repeat | Full shared tree identity, callbacks, context transfer, and OS isolation were not combined |

An additional F-16 review found that recorded evaluator evidence itself could remain aliased to mutable application data. The fix separated saved evidence from live objects and added an executed regression check. Protecting test code is insufficient if candidate-driven changes can alter the evidence already recorded.

The [numbered findings](reward-hacking-findings.md#f-09-selected-real-library-tests-retain-protected-assertions-across-a-process-boundary) preserve the exact cases, counts, failed attempts, and limitations. The prototypes had different rules for objects, exceptions, imports, and lifetimes. We never demonstrated that combining them preserved complete original suites under one protection model.

## 6. Valid messages did not settle faithful result capture

The parent could validate that a message had the expected structure. A separate question remained: did it faithfully describe the value and effects produced by the selected library?

Source review found that the library and the code packaging its return value shared a worker interpreter. Protecting that packaging code's file did not itself establish that its live operations were beyond candidate influence. Checking a reconstructed parent object's type or identity therefore did not automatically establish the corresponding property of the actual library result.

This was a source-reviewed trust assumption, not an executed new bypass. Automatic safety review blocked the proposed adversarial experiment before attack code or results were produced. The record explicitly preserves that distinction. See [F-20](reward-hacking-findings.md#f-20-valid-messages-do-not-establish-faithful-result-capture).

## 7. A different Python engine did not complete the solution

The user authorized investigating a different engine for correctness tests only. Delivered applications and all performance measurements would still use normal CPython. We investigated GraalPy Community 25.2.4, reporting Python 3.12.8, embedded in Java; the CPython reference was 3.12.13.

Restricted startup succeeded, and Java checked scalar results. Fifteen benign object and callback checks covered selected aliases, cycles, mutation, and types. Startup and those capture checks had independent repetitions. However, a protected Java operation still had to mean the same thing as the Python operation being tested: one fixture deliberately exposed different Python-call and foreign-call behavior.

The unchanged Markdown recursion test and all 88 API tests passed in one restricted Python context, with matching test identifiers and unchanged source inputs. Those were compatibility results. Assertions and library code still shared that context.

A separate two-context fixture preserved several interactions but changed an exact-list-type check and raised `RecursionError` in a combined inheritance/override/`super()` operation. Three dependent checks did not run. These compatibility and two-context runs had source/result review but no independent execution repeat. Complete original suites were not run through a protected arrangement, and GraalPy was never adopted.

See [F-21](reward-hacking-findings.md#f-21-a-protected-host-still-needs-faithful-python-operations) and the [engine investigation](execution-feasibility.md#authorized-investigation-a-separate-engine-for-correctness-tests). These failures describe the tested arrangements, not every possible Python design.

## 8. Why we stopped this path

The remaining task had expanded into designing an execution boundary that preserved classes, callbacks, identity, mutation, exceptions, streams, interpreter context, subprocesses, and faithful result capture while protecting every required assertion. Each successful small experiment addressed part of that task. None established a common implementation covering the complete original suites.

At that point, further Python isolation work was delaying the experiment the project exists to perform. The user made the priority explicit: take the shortest path to finding out whether application-specific specialization delivers substantial performance gains. We therefore chose to seek a different application and library in another language, with a simpler evaluation surface, and to run one supervised pilot first.

This changes the research path and implementation order. It does not reject the workload evidence, establish that either Python library lacks optimization opportunities, or turn an unresolved protection problem into a solved one. Another language may reduce particular difficulties; its name alone does not guarantee trustworthy evaluation.

## 9. What carries forward

The pilot retains original tests, independent original-versus-specialized output comparisons, additional edge cases, held-out inputs, reviewed agent-generated changes, unchanged application call sites, and standalone reproduction. A successful result must still meet both targets at the lower endpoint of a two-sided 95% confidence interval: **1.5× for logical library work and 1.2× for the complete application**.

The supervised pilot does not claim that arbitrary hostile code cannot forge an in-process test result. General adversarial protection, reusable experiment generation, and the two-pair demonstration remain later v1 work. The pilot can provide evidence about the performance hypothesis without claiming that the reusable system is complete.

Keep these practical lessons: validate actual artifacts rather than pass messages; preserve failures and skipped-test inventories; measure outside candidate-controlled clocks; freeze rules before optimization; protect held-out material and recorded evidence; terminate all candidate processes before freezing source; and distinguish a proposed control, a bounded executed check, and full-system evidence.

## Evidence and reading guide

- [Current scope](../scope.md) and [execution plan](../execution-plan.md): authoritative current decisions and next milestone.
- [Candidate assessment](candidate-assessment.md): original Python versions, real workloads, tests, timings, and reproduction.
- [Execution feasibility](execution-feasibility.md): execution environment, isolation checks, and unresolved integration work.
- [Findings F-01–F-21](reward-hacking-findings.md): detailed mechanisms, evidence, and limits.
- [Runnable teaching examples](reward-hacking/README.md): small complete programs for exploring the original problems.
- [Defense investigation](reward-hacking-defense.md) and [SkyDiscover assessment](skydiscover-assessment.md): related research and proposed controls, distinguished from implementation.

Raw experiments were stored outside this repository, principally under `/private/tmp/jit-lib-qualification.UoOrTd` and `/private/tmp/jit-lib-feasibility.2__rqrwc`. Detailed reports link their reproduction instructions and results. These temporary paths may disappear; this learning record summarizes the research but does not bundle those external artifacts or make their local links portable on GitHub.
