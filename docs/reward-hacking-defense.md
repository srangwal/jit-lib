# Preventing misleading success: reward hacking, hallucinations, and faulty evaluation

Updated: 2026-09-21.

**Milestone update, 2026-09-23:** the user approved one supervised non-Python pilot before reusable automation and general adversarial protection. The controls below remain research for the later system. The pilot keeps original tests, independent output checks, edge cases, held-out inputs, reviewed changes, and the existing performance targets, while explicitly making no claim of general hostile-code protection. See the [execution plan](execution-plan.md#next-milestone-one-supervised-pilot).

Just-in-Time Library will ask an agent to make a dependency faster while preserving application behavior. It must reject a “success” obtained by skipping work, hiding errors, falsifying tests, or reporting measurements that never happened. This document connects published research and our local experiments to defenses we still need to design and validate.

**Reward hacking** means achieving a favorable evaluation signal without meeting the intended requirement. A **hallucination** is an unsupported or invented claim, such as naming an API that does not exist or saying a test ran without evidence. Ordinary bugs in our evaluator can produce the same false acceptance. We need technical checks against the mechanism regardless of intent.

The recommendation combines two kinds of protection. A **specification-aware audit** reviews code against intended application behavior and discovers missing tests. **Execution isolation** prevents candidate code from changing the checker or its results. If Unicode behavior lacks a test, an audit can find the omission; if the library disables the runner, adding another test in that same process will not protect it. We need both, along with source-backed workloads and independent reproduction.

This is research and a proposed design direction under the [scope](scope.md). It is not implemented protection, an agent-count decision, a runtime change, or an extension into production deployment. [Local findings](reward-hacking-findings.md) provide executed evidence, including limited successful defenses and an adapter defect. Phase 2 remains open for the full real application–library pairs.

We cannot enumerate every future attack or prove immunity through finite tests. The practical deliverable is a catalog of concrete failure mechanisms, proposed controls, and evidence showing which representative cases were actually rejected. Passing checks remains bounded evidence about supported behavior.

## What the additional research contributes

The user supplied [Reality Is the Final Verifier, v1](https://arxiv.org/html/2609.12039v1). Its distinctions help locate where trust can fail:

- A **requirement gap** exists when the written contract omits intended behavior.
- A **model gap** exists when our assumed workload or operating conditions differ from reality. Here “model” means our representation of the system, not the language model.
- An **evaluation gap** exists when checks fail to enforce their own rules.

The paper's narrower discussion of reward hacking emphasizes the first two. Our falsified test runner is evaluator tampering. The paper also explains why another reviewer sharing the same assumptions cannot establish real-world adequacy. Appendix A treats an existing implementation as a useful reference for optimization while noting limits of that reference and finite comparisons. We apply those distinctions below without assuming every defect is intentional.

Additional primary sources reviewed:

| Source | Relevant reported finding or idea | Application to our investigation |
| --- | --- | --- |
| [The Time is Here for Just-in-Time Systems, §4.5 and Appendix B](https://arxiv.org/html/2605.24096v1) | Specification-aware auditing; examples include regeneration of predictable values, restricted key assumptions, measurement manipulation, and faults missed by audits. | Retain adversarial candidate review and executable counterexamples; test the evaluator boundary separately. |
| [AIChilles, v2](https://arxiv.org/abs/2606.15834v2) | Searches for valid workloads where an evolved program regresses against its baseline in correctness, runtime, memory, or output quality, combining workload constraints and differential checks. | Investigate counterexample search beyond the optimization corpus. This is an idea to adapt, not a selected dependency or an executed project integration. |
| [Natural emergent misalignment from reward hacking](https://www.anthropic.com/research/emergent-misalignment-reward-hacking) | Controlled training experiments include coding reward hacks such as exiting a test harness early with a success status. | Check execution and completion independently of exit status. These experiments do not establish the behavior or prevalence of hacking in our installed Codex model. |
| [We Have a Package for You!, USENIX Security 2025](https://www.usenix.org/conference/usenixsecurity25/presentation/spracklen) | Empirical study of invented package recommendations and the resulting software-supply-chain risk. | Validate package identity, provenance, version, and actual API behavior; a plausible name is not evidence. |
| [GitInject, v1](https://arxiv.org/html/2606.09935v1) | Demonstrates attacks through untrusted content and configuration in live AI-enabled CI workflows, including credential and judgment manipulation. | Treat imported repositories, instructions, logs, and tool output as possible injection sources; restrict capabilities independently of model compliance. |
| [The Ladder](https://arxiv.org/abs/1502.04585) | Repeated adaptive access can overfit a held-out leaderboard even without direct access to its examples. | Protect final feedback as well as final files. Keep the existing separate-run and exposure-history policy; do not silently add a reusable-holdout algorithm. |
| [Python audit hooks](https://peps.python.org/pep-0578/#why-not-a-sandbox) and [pickle](https://docs.python.org/3/library/pickle.html) | Runtime audit hooks are not themselves a sandbox; unpickling untrusted data can execute code. | Do not present Python hooks or arbitrary object transport as protected assertion execution. |
| [RPyC security documentation](https://rpyc.readthedocs.io/en/latest/docs/security.html) | Recommends capability restrictions and wrappers; exposing connected Python objects or relaxing attribute restrictions can expose much more authority. Classic mode deliberately exposes the server. | A generic object proxy is not an established safe replacement for our limited JSON boundary. Any callback protocol needs explicit, tested permissions. No RPyC implementation was installed or executed here. |
| [PyPy sandbox documentation](https://doc.pypy.org/sandbox.html) | Describes a separate process whose external I/O is mediated by a controller; the page labels this version old/unmaintained and warns about Python 3 compatibility. | It is not a demonstrated solution for these pinned pairs. Our inference: mediating external I/O alone does not isolate assertions from candidate code sharing that guest interpreter. No alternate runtime was adopted. |

The table reports what the cited sources describe. It does not mean we reproduced those studies in this project. The following catalog maps their lessons and our own analysis to Just-in-Time Library. The [SkyDiscover assessment](skydiscover-assessment.md) separately records repository inspection and helper experiments.

## Threat model and trust boundary

The **threat model** specifies what we must treat as untrusted. That includes the proposed library source, import-time code, build/install hooks, background processes, agent-supplied reports, and newly generated evaluation scripts. External repositories, workload files, and logs may contain instructions intended to redirect an agent. We must tolerate incorrect or hostile content without letting it decide acceptance.

Protect the unchanged application/library baseline, checker/assertions, reference answers, held-out inputs and feedback, timing rules/clocks, resource accounting, deadlines, exact candidate identity, and final report. Access through copies, caches, logs, environment variables, fetching tools, shared agent context, or memory counts just as much as direct file access.

The proposed **trusted controller** owns execution policy, artifact identities, comparisons, statistics, and acceptance state. An artifact identity is a revision/hash linking a record to exact contents. Agents propose code, tests, or findings; they cannot grant acceptance. Generated checking code needs audit and containment before becoming part of the fixed evaluator. Naming an agent “auditor” or giving it a separate conversation does not validate its conclusions.

The **trusted computing base** consists of components our checks rely on: the host OS, isolation runtime, and protected controller. The probes do not establish defense against arbitrary host/kernel compromise or hardware side channels. Record versions and repeat relevant checks after changes. Denying file reads also cannot prove that a model knows nothing about public or previously trained-on inputs.

## Failure catalog and concrete defenses

The catalog keeps IDs T01–T26 for traceability. “Local” points to an executed finding F-01–F-12. “Reported” means the published research above. “Hypothesis” means a plausible project case that still needs execution. Evidence for one variant does not establish protection against the whole category.

An **oracle** supplies an expected answer, normally from the pinned original or independent existing tests. A **mutant** is a deliberately faulty variant used to test whether a check detects that particular error. A **frozen contract** fixes evaluation rules before optimization. **Eligibility** means a candidate has completed the checks/measurements required to be considered for selection; a high score alone does not make it eligible.

### Tests, oracles, and result forgery

These failures compromise how we decide correctness. Even perfectly chosen inputs cannot help if the expected answer is contaminated, assertions do not run, or the candidate writes its own pass record.

| ID and mechanism | Proposed control | Verification and evidence now |
| --- | --- | --- |
| T01. Replace the runner or assertion functions in memory; fabricate success events with the correct count. | Keep mandatory assertions and verdict logic outside candidate-controlled memory, preserving the semantics of the required tests. | F-01 reproduced the failure; F-02/F-09 protect fixture/library subsets; F-11 protects eleven title tests and F-12 protects five relative-path tests plus state controls against the tested forgery. Full real-pair protection is open. |
| T02. Exit 0 early, emit fake JUnit/JSON/logs, skip collection, add skips, or disable Python assertions. | Treat process exit as one observation; require protected completion, frozen test selection, and independently established outcomes. | F-03 rejects missing artifacts/output; F-02 rejects a fake verdict. Collection/skip and assertion-disable variants remain to test. |
| T03. Return an object that executes candidate code when the checker compares it, converts it, destroys it, or decodes it. | Transport only validated inert data where the API permits it; do not invoke candidate-defined behavior in the trusted checker. | F-02/F-09 use narrow JSON protocols; F-11/F-12 reject specified object/attribute/callback-protocol requests. F-10 shows that copying values can change semantics. General object support and hostile equality/serialization remain open. |
| T04. Use the candidate to construct its own expected answer, reuse its cache as the reference, or copy candidate logic into a generated oracle. | Obtain expected behavior from the pinned original or independent existing expectations; separate reference execution and artifacts. | Current fixture uses protected baseline outputs. Deliberately contaminated generated oracles still need rejection tests. |
| T05. Weaken normalization, tolerances, error comparisons, or side-effect checks until a wrong result passes. | Audit and freeze comparison rules against original behavior; enumerate required observable effects. | Hypothesis: return the right text but wrong exit status, file content, exception, or state change and verify rejection. |
| T06. Write the result store, forge an audit stamp, reuse an old passing record, or present a positive score alongside an error. | Only the controller creates authoritative records; bind them to immutable inputs and require completion and correctness before considering scores. | F-06 denies tested writes. SkyDiscover's isolated digest/parser probes cover particular helpers, not this project's future controller. |

### Unsupported specialization assumptions and unrealistic workloads

These failures arise when a narrow observed pattern is mistaken for the application contract. Specialization should exploit justified application facts while retaining supported behavior outside the timing corpus.

| ID and mechanism | Proposed control | Verification and evidence now |
| --- | --- | --- |
| T07. Treat a property of sampled inputs as a fact true for all supported use: all text is ASCII, inputs are small, keys are dense, or one option is always selected. | Support any claimed invariant with the application contract; otherwise use a correct guarded fast path and general fallback. | Reported class; project hypotheses: Unicode, large/sparse inputs, unseen supported options, and guard boundaries. |
| T08. Memorize replay answers, recognize fixture names or seeds, regenerate predictable values, or switch behavior when a benchmark is detected. | Forbid evaluation-specific behavior; audit branches/data tables; use valid development perturbations and frozen held-out workloads. | Reported class. Test fresh values, renaming and reordering only where semantics permit, and behavior beyond the replay corpus. Detection cannot prove absence of every trigger. |
| T09. Drop requests, truncate data, approximate results, suppress errors, or handle only easy inputs. | Compare complete outputs, errors, and relevant effects; track input/output completeness externally. | F-02 catches one wrong-output variant. Stateful, large-input, and partial-work variants remain to test. |
| T10. Return correct results for isolated calls but break sequences, repeated use, shared-object mutation, callbacks, concurrency, or recovery after failure. | Derive sequence/state tests from the supported interface, with separate baseline/candidate state; check that the adapter preserves those behaviors too. | F-09 exercises metadata/reset; F-10 reproduces lost alias semantics; F-11 exercises title callback state and nested calls; F-12 preserves selected link mutations and application File identity/state. Broader interfaces, sharing, and concurrency remain open. |
| T11. Build a replay that omits actual configuration, initialization, workflow mix, or input relationships and then claim general real-world gains. | Source every workload assumption; state the represented population and missing usage evidence; preserve related-input grouping. | Candidate qualification provides bounded evidence. Formal workload protocols are not frozen; missing frequencies cannot be invented. |
| T12. Share the same mistaken assumption across generator, auditor, tests, and report. | Require independently grounded expectations and targeted counterexample execution, not a vote among agents. | Reported concern. Seed a plausible false assumption and check whether evidence, rather than repeated agreement, rejects it. |

Caching is permitted if it preserves supported behavior, uses correct keys/invalidation, and includes preparation/reuse costs under the actual application lifecycle. Workload-specific improvements are the purpose of this project when they follow justified application facts.

### Measurements, selection, and data exposure

Correct answers are insufficient if we time less work, compare unequal environments, select lucky samples, or tune against supposed final evidence. The controller must enforce fixed measurement and selection rules.

| ID and mechanism | Proposed control | Verification and evidence now |
| --- | --- | --- |
| T13. Replace a timer, forge profiling events, or report an invented library duration. | Use protected clocks and observations; establish a trustworthy boundary for the same logical library work in both variants. | F-04 protects process elapsed time only. Trusted attribution inside real applications is still design work. |
| T14. Move required work into import/setup, a different helper, a lazy iterator, a background worker, or post-timing cleanup. | Freeze lifecycle and completion boundaries; include required work regardless of module/thread/process; justify and count costs shared across repeated use. | Hypothesis. Deferred-output and eager-precomputation mutants must not gain by moving costs outside the declared interval. |
| T15. Slow the baseline, change flags/versions/resources, warm only the candidate, pollute a shared cache, or alter host settings. | Preserve baseline identity; pin comparable environments; reset permitted state; enforce resource/access policy; use declared paired ordering. | F-06 protects tested baseline files. Cache asymmetry, configuration substitution, and cross-candidate pollution remain to test. |
| T16. Discard unfavorable timings, retry failures as “outliers,” stop at a lucky result, change workload weights, or treat correlated operations as independent samples. | Freeze repetitions, exclusions, sampling units, aggregation, stopping, and ranking; calculate from retained raw observations in the controller. | Scope already requires these rules. Statistical method and numerical settings remain unresolved; fabricated-record tests come before formal runs. |
| T17. Read reserved final examples/answers through copies, logs, network access, injected instructions, shared agent state, or the process running the original reference. | Keep protected material out of every development capability and context; restrict fetching and outgoing communication; separate reference and candidate execution. | F-06 covers specific path/alias/network probes. Context, source-mirror, and cross-role leakage variants still need tests. |
| T18. Tune repeatedly against final scores, rename a failed run, or reuse exposed data as an untouched holdout. | One selected candidate proceeds to final evaluation; a final failure ends that run; retain linked attempts and exposure history. | Reported adaptive-overfitting risk. The policy is agreed; controller enforcement is not implemented. |
| T19. Continue after the deadline, relabel optimization as setup, select using an older check set, or accept late results for another snapshot. | Controller-owned stage clocks, whole-job teardown, immutable identities, versioned checks, and atomic eligibility decisions. | F-07 verifies tested teardown. Concurrent stale-result and new-check/deadline cases remain to test. |

### Hallucinations, injected instructions, and delivery

These failures concern what the agent believes, what untrusted content asks it to do, and whether the delivered result matches the evidence. A plausible name, report, or command is a proposal until source and execution records support it.

| ID and mechanism | Proposed control | Verification and evidence now |
| --- | --- | --- |
| T20. Invent a package/API/flag, assume the wrong version, or install an attacker-registered version of a plausible package name. | Verify provenance and supported APIs from pinned source/documentation and execute the actual build in a clean environment. Route dependency acquisition through controlled setup. | Package hallucinations are reported. Test nonexistent APIs and unexpected dependency changes; registry existence alone is insufficient provenance. |
| T21. Claim a command, test, audit, or independent reproduction ran when it did not; cite a nonexistent artifact or another candidate's log. | Require controller-produced execution records, inputs, exit/completion status, and output hashes for each factual claim. | F-03 demonstrates why completion cannot be inferred. Reject missing, mismatched, or agent-authored substitutes. |
| T22. Invent a speedup, reverse the ratio, confuse throughput with latency, omit units, accept NaN/infinity, or equate a point estimate with a confidence-bound pass. | Typed, bounded records with explicit units/metric direction; protected arithmetic; require both agreed lower-bound thresholds. | Proposed deterministic tests. The 1.21× estimate with 1.10× lower bound must not pass the 1.2× application target. |
| T23. Follow instructions hidden in repository guidance, comments, test failures, a README, generated output, or an auditor message. | Separate task authority from inspected content; pin trusted configuration; restrict tools/credentials and protect controller state regardless of the agent's response. | Reported injection class. Test that a malicious “repair the evaluator” instruction cannot change protected controls or expose data. |
| T24. Execute malicious build/import hooks, abuse symlinks/archive paths, poison caches, or load a different library than the evaluated snapshot. | Isolate build and candidate execution; validate artifacts and paths; record controller-observed loading/build provenance; compare delivered and evaluated contents. | F-03/F-06 cover particular build/access cases. General archive and loader-substitution attacks remain to test. |
| T25. Exhaust resources, hang a checker, flood logs, crash a parser, or get infrastructure failures counted as successful exclusions. | Bounded inputs/outputs/processes/memory/time; distinguish application failure from infrastructure failure; no missing-result pass. | F-02 rejects empty output, flooding, and hangs. Broader parser/resource variants remain to test. |
| T26. Carry an invalid lesson, stale audit, or hidden assumption from another run; export an experiment that secretly needs the agent's environment. | Source and scope retained findings; invalidate stale evidence; freeze dependencies; execute the exported README in a fresh environment without agents. | Existing standalone fixture reproductions supply bounded evidence; F-08 caught a harness side effect during reproduction. Real-pair automatic export is not implemented. |

An unsupported model claim, an ordinary bug, and deliberate cheating can all lead to false acceptance. Record the observed mechanism and evidence; do not infer motive from the result.

## Proposed workflow and ownership

### 1. Make each specialization assumption reviewable

For each optimization assumption, record the claim, supporting application/source evidence, conditions in which it holds, affected change, and the check or fallback preserving other inputs. Keep this in the experiment records; it does not require a new knowledge-base service.

For example, “all sampled documents are ASCII” describes a sample. If the application supports Unicode, the library must still handle it. A fast path can check for ASCII and use a correct general path otherwise. Test both paths, transition cases, and errors.

A missing source, unsupported API, or uncertain intended behavior remains unresolved. The system should ask for clarification where intent or essential usage context is missing; it should not fabricate a rule to unblock optimization. Detectable implementation facts should instead be established by inspection or execution.

### 2. Separate execution from authority

The controller freezes exact candidate contents, starts workers with limits, enforces deadlines, records observations, and calculates acceptance. Candidate/build processes receive only necessary files and capabilities. The optimizer may request evaluation but cannot write the result store or change rules. An auditor may submit a finding but cannot validate it merely by returning `passed: true`.

Run the original reference separately from the candidate. Do not expose expected answers or protected test internals to simplify cross-process calls. Messages need fixed permitted fields and size limits. Distinguish an expected application exception from a broken worker/connection so an infrastructure failure cannot accidentally pass an error test. A checksum connects bytes to a record; it does not make a candidate-produced false report true.

The local findings show the progress and its limits. F-02 separates one simple function from its assertions. F-09 extends that to selected library tests. F-10 then shows copied metadata losing shared-object behavior even though those tests pass. F-11 keeps a real title callback in the parent. F-12 preserves selected link mutations and shared application file objects too, and rejects protocol/data variants. Those callback probes do not fix F-10 or establish safety for arbitrary callbacks. F-15 preserves one recursion-sensitive test family with explicit runtime limits. F-16 addresses the observed builtin sharing/cycle examples, but has no general class or callback protocol.

F-16 also demonstrates why application state and evaluator evidence need separate ownership. Its first driver saved a worker-returned dictionary while leaving it registered for later shared-object updates. Another valid response could alter the earlier record. The corrected experiment detaches validated inert evidence and retains an independent infrastructure-failure record even when a test catches the communication exception. Neither control makes a candidate's original report truthful; authoritative comparisons still belong to the evaluator.

F-17 adds selected-library inherited methods with a caller-owned override and shared configuration, including independently repeated restricted-container execution. It distinguishes ordinary callback exceptions, which application code may catch, from explicitly marked evaluator assertions that escape a callback and must remain failures. The latter are recorded in protected parent state and terminate the worker. This is a demonstrated mechanism for added controls, not an automatic classification of all existing assertions. Its independent eligibility record also prevents caught communication failures from becoming accepted test results.

F-18 demonstrates selected PyYAML methods cooperating with caller-owned classes in a reduced fixture. F-19 connects extension construction, registration, rendering, and a caller serializer in one selected Markdown session. Wrong-source controls verify that the candidate's actual implementation determines the tested behavior. These ordinary-process checkpoints have separate limitations around classes, exceptions, and shared objects. A common arrangement covering the complete suites remains unfinished.

F-20 adds a source-reviewed trust assumption: result packaging currently shares the candidate's interpreter. Parent validation establishes properties of the received representation, but does not alone establish its correspondence to the selected operation's actual result and effects. The proposed adversarial experiment was automatically blocked before execution, so this is not a demonstrated bypass. The architecture must justify the capture boundary as well as the message parser and parent assertions.

A callback still consumes candidate-controlled data. A test adapter must preserve the original test meaning and exercise the actual candidate. It cannot silently substitute the baseline, skip required tests, or become the delivered runtime interface. The normal performance-measurement path also needs to remain distinct from correctness-test instrumentation.

We also reviewed RestrictedPython as a possible ingredient for enforcing checks inside one interpreter. Its documentation explains that rewritten access checks cover restricted source, not the internals of every function that source calls; the embedding application must control which objects and imports are reachable. Its default write guard permits exact builtin lists and dictionaries, rather than distinguishing application data from evaluator-owned containers. A custom ownership policy would therefore need its own implementation, security review, and compatibility evidence. We did not install or execute RestrictedPython, and have not adopted it. See its [security considerations](https://restrictedpython.readthedocs.io/en/latest/usage/security_considerations.html) and [guard implementation](https://github.com/zopefoundation/RestrictedPython/blob/master/src/RestrictedPython/Guards.py).

### 3. Audit behavior and validate counterexamples

Review candidate changes against supported application behavior, including paths absent from the performance workload. Inspect removed checks, assumptions in fast paths, caches, result shortcuts, unusual imports, runtime inspection, process creation, and changes affecting timing. These are review leads, not automatic bans on legitimate optimizations.

Each finding needs the requirement/source, a small valid input or sequence, observed original and candidate behavior, and an executable check. Validate the proposed check against the original and an intentional fault. A model describing a test is not evidence that it ran. **Differential testing** compares original and candidate behavior; it preserves the original contract but does not prove the original has no bugs. If stated requirements conflict with original behavior, ask rather than silently redefining the reference.

Consider AIChilles' approach of searching supported input dimensions for regressions: size, encoding, options, state transitions, and input distributions. A **metamorphic check** tests a justified relationship between executions, for example a transformation that should preserve a result. Reordering is not such a relationship for an order-sensitive API. Correctness examples outside the timing corpus can reveal bugs; performance acceptance still follows the fixed workload and regression rules.

### 4. Grow development checks without moving final acceptance

The user-approved policy applies unchanged:

1. Validate a proposed check against the existing behavioral requirement, the pinned original, and the intended fault. A reference failure or timeout alone is insufficient evidence.
2. The protected controller admits and versions the mandatory development check. Preserve the previous checks and validation evidence.
3. Earlier candidate eligibility becomes stale until the added checks pass. A late result for an older check set cannot restore it.
4. Audit, validation, and rechecks share the original search deadline. Unfinished required work leaves a candidate ineligible.
5. Keep final tests, held-out data, comparison/measurement rules, thresholds, and ranking frozen. A needed contract change ends the run; preserve evidence and start a newly audited run under the exposure policy.

The original contract must specify how development checks may be added. Adding one under that procedure does not edit final artifacts. If a new finding compromises the controller or final evaluator, do not hide it as an ordinary extra development test and continue calling that evaluation valid.

### 5. Derive results from evidence and reproduce them independently

Calculate counts, timing, speedup, intervals, and eligibility from controller-recorded observations. Identify the application, original library, candidate, environment, workload, fixed protocol, and current check set in each record. A report may explain this evidence but cannot fill in nonexistent measurements. Keep unknown, failed, and incomplete outcomes explicit.

Measure equivalent completed jobs in paired original/candidate runs. Each pair must meet both targets at the lower endpoint of a two-sided 95% confidence interval: 1.5× library and 1.2× application. The external-clock experiment did not settle library attribution, statistical sampling units, or interval method. Resolve these before freezing a formal run; the search backend cannot choose a favorable metric or stopping rule.

Export the commit, check additions, raw evidence, limitations, and exact standalone commands. Execute them outside the generator/agent environment. If later user reproduction or newly supplied usage reveals a problem, preserve a linked finding and invalidate the affected claim. Investigate through the agreed new-run process; this does not add automatic deployment, production monitoring, or a new service to v1.

## Remaining validation and execution order

| Stage | Concrete next check | Completion condition |
| --- | --- | --- |
| Phase 2: protect real repository tests | Follow the user's selected direction: broad library-code editing with stronger protected execution. Use the full-suite inventories, retain F-10/F-13/F-14 as compatibility regressions and F-11/F-12 as limited successful controls, and validate the required object/context mechanisms before extending to all suites and callback-driven parent operations. | Original suites retain their semantics and collection; actual candidate code runs; mandatory failures cannot be turned into success. Neither a fixture nor a selected real-test subset closes this gate. |
| Phase 3: make enforcement explicit | Map this catalog to trusted components, permitted capabilities, invariant evidence, measurement boundaries, audit cadence, and artifact ownership. | No acceptance responsibility rests on an untrusted assertion. Resolve remaining scope choices with the user; do not silently narrow supported behavior. |
| Phases 4–5: challenge the controller and generated evaluator | Use deterministic wrong-result, missing-work, altered-oracle, artifact-substitution, malicious-output, injected-instruction, and resource-exhaustion fixtures. | Each attempt is rejected for the intended reason; baseline controls pass; failures and incomplete results remain visible. |
| Phase 6: challenge adaptive search | Add a validated development check while evaluations are in flight; exercise expired budgets, stale audit versions, final-feedback leakage, and linked failed runs. | No stale or incomplete candidate is eligible; final data/rules remain protected; search cannot manufacture another budget. |
| Before Phase 7 demonstrations | Reproduce actual exported builds, protected correctness checks, and measurements independently; review outstanding findings. | Required integrity gates pass for the selected environment and pairs; unresolved blockers prevent an accepted specialization. |

Link each finding to its constructed case, execution evidence, fix status, and limits. Repeat affected checks when a runtime, boundary, message parser, or evaluator changes. Source review and a larger checklist do not replace execution. Successful adversarial tests cover the cases exercised, not every possible future attack.
