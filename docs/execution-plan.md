# Just-in-Time Library: execution plan

Just-in-Time Library will use coding agents to specialize a dependency for an existing application. A successful result must preserve application behavior, make the library and application measurably faster, and let the user reproduce the result without the generator. The [scope](scope.md) defines those requirements. This document explains the work needed to satisfy them and the evidence required at each stage.

**Current position: one supervised pilot comes next; Phase 2 remains incomplete and is deferred.** On 2026-09-23 the user directed us to choose application/library candidates in another language and approved testing one pair before building the reusable generator and its general adversarial-protection machinery. The objective is the shortest credible path to testing the specialization hypothesis. Earlier yamllint/PyYAML and MkDocs/Python-Markdown results remain historical evidence. Their ordinary builds/tests work, but full protected execution is unresolved. The generator and real specialization demonstrations are not implemented.

Complete real project jobs qualify as real-world workloads for v1. Kubespray's configured lint job and HTTPX/DRF's full documentation builds meet that source requirement; recorded production/CI executions are unnecessary. We still need to fix exact final workload membership, weights, starting state, and held-out evaluation rules before optimization.

**Active work:** qualify one non-Python pair using actual source, a real replayable workload, measured library cost, and practical supervised evaluation. The Python/GraalPy investigation is set aside; its results remain recorded. The two-demonstration milestone remains the later reusable-v1 goal. Use subagents sparingly, as requested on 2026-09-23.

## Next milestone: one supervised pilot

This milestone changes the earlier implementation order. We will test whether specialization produces substantial gains before investing in a reusable generator or a general mechanism for running hostile library code safely. It does not mark Phase 2 complete or remove that requirement from the later system.

1. **Qualify one pair.** Pin separate application and library checkouts outside this repository. Reproduce an unchanged complete real project job, run original tests, and profile the library's contribution. Source review alone cannot establish a useful performance opportunity.
2. **Fix the experiment.** Record development and held-out inputs, baseline behavior, independent output comparisons, edge cases, timing boundaries, repetition and confidence-interval rules, ranking, and elapsed-time limits. Resolve missing choices before optimization. Keep exposed inputs in development and final evaluation frozen.
3. **Generate and review library changes.** Use Codex CLI for coding through a bounded supervised workflow. Retain broad algorithm and data-structure editing, original tests, and application call sites. Review each proposed change for both supported behavior and evaluator interference before accepting its evidence. Do not substitute a hand-written specialization for the agent's work.
4. **Evaluate one selected candidate.** Run the original suites, independent output comparisons, and edge-case checks. Measure the same complete jobs with original and specialized libraries, then perform held-out final evaluation after candidate selection. Require the lower endpoint of each two-sided 95% confidence interval to reach **1.5× library** and **1.2× application** speedup.
5. **Deliver a reproducible outcome.** Preserve changes, commands, raw results, and limitations whether the outcome succeeds, fails, or remains inconclusive. A successful result includes a commit atop the library baseline and an external experiment README whose build, test, and measurement commands have been run independently of the agent.

Manual preparation and review of experiment tooling are allowed in this pilot. Reusable orchestration, automatic experiment construction, the second formal pair, search-framework comparisons, and comprehensive adversarial protection are deferred. Supervision and independent checks reduce risk; they do not establish that arbitrary candidate code cannot forge in-process test results. Report that limit explicitly.

## How to read the plan

A **candidate** is a proposed specialized library; the **baseline** is the unchanged original. **Qualification** asks whether a pair is suitable for investigation, not whether it already achieves a speedup. A **fixture** is a small synthetic application used to test system behavior. A **bounded experiment** answers a narrow technical question with a limited test surface; passing it does not establish the full system.

The **protected controller** is ordinary software that owns deadlines, artifact identities, eligibility, and acceptance. Agents may propose changes and tests, but cannot decide their own grade. An **evaluation contract** records the inputs, checks, measurements, and selection rules fixed before search. **Development** evidence can guide optimization; **held-out** evidence is reserved for evaluation after candidate selection.

For context and evidence, use the [candidate assessment](candidate-assessment.md), [feasibility report](execution-feasibility.md), [reproduced findings](reward-hacking-findings.md), [defense investigation](reward-hacking-defense.md), and [SkyDiscover assessment](skydiscover-assessment.md). The latter recommends ideas to adapt and a conditional AdaEvolve comparison; it does not select a framework, implementation language, agent count, CLI, or configuration schema.

When a requirement or intended behavior is ambiguous, stop the affected work and ask for clarification. Record the answer. Do not weaken a requirement to make a phase pass. Meeting a phase's evidence requirement is not an additional recurring manual-approval requirement.

## Execution order and milestones

The phases below describe the later reusable-v1 program. They follow the supervised pilot; they are not all prerequisites for starting it.

| Phase | Deliverable | Evidence required to move forward |
| --- | --- | --- |
| 1. Qualify candidate pairs | Candidate assessment with two recommended pairs and their usage sources | Reproducible original builds, baseline checks, replay evidence, and measured dependency contribution |
| 2. Prove execution and isolation feasibility | Recorded backend and isolation checks on the target machine | Agent invocation works; representative attempts to access protected data or forge evaluation fail |
| 3. Resolve the design and evaluation contracts | System design and complete experiment protocols | Interfaces, access boundaries, measurement rules, failure handling, and outstanding choices are explicit |
| 4. Build controlled execution | Repository/environment management, stage control, evaluator boundary, and Codex backend integration | A small fixture exercises execution, protected results, timeouts, and artifact export |
| 5. Automate experiment construction | Generation and audit of standalone replay, tests, and measurement tooling | The system builds an audited experiment from real repository and usage inputs |
| 6. Implement and integrate specialization search | Bounded search, candidate selection, final evaluation, and commit delivery | The full workflow works on development data and passes acceptance-integrity checks |
| 7. Run both formal demonstrations | Two results from the same frozen generator revision | Each pair passes correctness, both confidence-bound targets, and independent reproduction |
| 8. Complete the evidence review | Final validation report and complete external experiment directories | Every first-version acceptance requirement maps to executed evidence |

For the pilot, establish reviewed standalone evaluation before optimization. For the reusable system, establish the stronger execution boundary required by Phase 2 before dependent automation. In either case, a promising speedup must have actual correctness and measurement evidence.

## Phase 1: qualify two application–library pairs

**Purpose:** find two pairs worth building the reusable workflow around. The [candidate assessment](candidate-assessment.md) records the completed baseline research and its limitations.

For each promising pair, record pinned source revisions, independent adoption, the dependency relationship, usage sources, and setup requirements. Then perform these checks:

1. Prepare separate application/library checkouts and external research outputs.
2. Build the original application, run its tests, and verify which library it loaded.
3. Reconstruct complete jobs from real inputs, recording commands, configuration, and state. Define the represented population. If frequencies are unknown, call the chosen job mixture an experimental choice rather than observed usage.
4. Profile dependency time. Explain why both targets might be attainable while keeping measured costs separate from hypotheses about improvements.
5. Assess correctness coverage beyond the timing workload: supported options, errors, side effects, and assumptions requiring guards or a fallback.
6. Identify enough appropriate unexposed material for final evaluation. Everything inspected or used for tuning remains development material, with its exposure recorded.

Research scripts help qualify the pair. They cannot substitute for the generator's later ability to construct experiments. Do not hand-write a specialization during qualification.

**Deliverable and completion condition:** `docs/candidate-assessment.md` must recommend two pairs with executable original builds/checks/replays, usable real workloads, plausible performance opportunity, and a credible correctness strategy. Record why assessed alternatives were not selected. Source inspection alone is insufficient. If two pairs cannot qualify, continue research or ask about the blocking constraint; do not lower targets.

## Phase 2: prove execution and isolation feasibility

**Purpose:** establish that the planned execution arrangement can run useful coding tasks and trustworthy tests on the local CPU-only machine. Do this before committing to a dependent architecture.

Exercise the installed Codex CLI on a small coding task. Verify actual invocation, working directory, result capture, permitted paths, and termination. CLI documentation alone cannot establish these behaviors. If using a local Linux container, verify its compatibility and restrictions through execution.

The protection tests must cover agent tools, candidate imports, build/install hooks, and child processes. Challenge the boundary with attempts to read held-out copies, references, or shared logs; change the original application, baseline, evaluator, controller, or results; forge success or timings; exit successfully without producing required work; modify an in-process test runner or clock; and keep changing source after the deadline or snapshot.

Original Linux environment compatibility is now demonstrated and repeated: the qualified repository suites and MkDocs integration builds pass on CPython 3.12.13, with exact unittest collection and existing skips matching the macOS references. Missing locale and native Tidy prerequisites were fixed without changing tests. These [baseline results](execution-feasibility.md#original-full-suite-compatibility-on-linux) close the environment-compatibility subtask, not the protected-assertion gate.

Keep a record of both effective defenses and successful bypasses. Distinguish normal application inputs/outputs from protected controls. Allowing the agent client to contact its model provider must not give candidate code unrestricted network access or access to alternate held-out source copies.

### The unresolved test problem

The [feasibility report](execution-feasibility.md#real-pair-interface-audit-and-subset-result) describes the tested interfaces. Assertions now run outside candidate-controlled memory for a simple fixture, selected upstream library tests, and eleven MkDocs title tests. Seven malformed callback-message variants were rejected. But an earlier metadata adapter copied an object that the original API shares: selected tests passed even though identity and mutation behavior changed.

An **adapter** here is test-only code that forwards calls across processes. A **callback** is an application function the library calls during its work. To protect real tests, the adapter must preserve calls, exceptions, objects, state, and callbacks while preventing the candidate from controlling the checker. It must exercise the selected candidate, not silently replace parts with original-library behavior.

The bounded relative-path experiment is now complete for five existing MkDocs page-render tests and an added state check. It preserves tested link changes and shared application file identity/state, rejects the constructed protocol/data faults, and keeps deliberate parent assertion failures effective. One state fault still passes the five original tests but fails the added check, illustrating the limit of a small subset. See [F-12](reward-hacking-findings.md#f-12-selected-page-render-tests-preserve-link-changes-and-shared-application-objects) for evidence.

The full-suite inventories now record all 430 yamllint, 1,283 PyYAML, 724 MkDocs, and 1,088 Markdown tests in the qualified references, including existing skips. They identify the required object, class, callback, stream, runtime-state, and subprocess interactions. No tests were removed to suit the adapter. Two further experiments exposed concrete problems: YAML aliases lost identity/mutation and recursive values could not cross the earlier narrow facade; an unchanged Markdown recursion test failed in a worker even on the same Python executable. See [F-13](reward-hacking-findings.md#f-13-the-yaml-adapter-loses-shared-and-recursive-values) and [F-14](reward-hacking-findings.md#f-14-moving-markdown-to-a-worker-changes-an-existing-recursion-test).

**Decision, 2026-09-21: preserve broad library-code editing and investigate stronger protected execution.** The user selected direction 1. A predefined transformation family is not the v1 approach. The strong assertion requirement remains in force; a concrete execution architecture still needs evidence. More test-specific adapters alone cannot establish a complete solution.

The first mechanism checkpoints tested a checked representation of shared/circular builtin objects, including persistent mutation across calls, and transfer of the runtime context needed by the observed recursion behavior. The latter derives from actual caller/worker state, not a test identifier or expected output. Independent architecture reviews then assessed whether these mechanisms could belong to an execution boundary that also handles the inventoried classes, callbacks, and subprocesses. Successful mechanism probes are necessary evidence, not completion of that architecture.

The shared-object part now passes its bounded checks and independent reruns with ordinary workers and restricted Linux containers: YAML aliases/cycles and Markdown metadata identity/mutations match direct original behavior; wrong outputs and malformed updates are rejected; deliberate parent assertions still fail under child runner forgery. Review also found and corrected a shared alias into recorded evaluator evidence. The container runs verify minimal read-only mounts, configured restrictions, and removal of every worker. See [F-16](reward-hacking-findings.md#f-16-shared-object-transport-must-not-make-evaluator-evidence-shared-too). This supports only bounded builtin graphs, not full-suite execution.

The runtime-context part now has a reproduced, limited result: measured remaining-budget transfer passes the unchanged Markdown test across nine depth combinations and matches 36 supplemental comparisons. It changes the absolute recursion limit; measured stack padding preserves that value only when the worker is not already deeper. Neither technique reproduces arbitrary caller frames or protects its own instrumentation. See [F-15](reward-hacking-findings.md#f-15-measured-recursion-context-preserves-one-test-family-with-observable-limits).

The inheritance checkpoint passes the seven unchanged Markdown extension-class tests, plus controls for a caller-owned override, nested selected base-method execution, shared state, and exceptions. Independent ordinary-process and restricted-container runs confirm the 39-case result; each container run removes all 59 workers/control containers. Mandatory parent assertions remain failures, and independent infrastructure state rejects caught protocol errors. See [F-17](reward-hacking-findings.md#f-17-inherited-methods-can-call-back-without-owning-the-callbacks-verdict). Its callback policy remains narrow, and its added mandatory assertions use explicit markers.

Two further ordinary-process checkpoints have independent reproductions. [F-18](reward-hacking-findings.md#f-18-caller-defined-classes-need-more-than-copied-values) preserves selected PyYAML base-method calls and caller-owned custom objects in a reduced fixture; it does not run complete unchanged upstream tests. [F-19](reward-hacking-findings.md#f-19-extension-registration-and-rendering-must-work-in-the-same-session) connects one unchanged Markdown serializer test and added controls to actual selected construction, registration, and rendering in one session. The next task is to establish a common execution design covering the complete source-backed interface inventory. Adding separate test-specific facades cannot establish that design.

The integration reviews identify incompatible class lifetimes, graph formats, exception rules, and import routes across these prototypes. They also identify a separate result-capture obligation: the selected library and the code packaging its return value currently share a worker interpreter. A checked message is not by itself evidence that this packaging preserved the actual return value. [F-20](reward-hacking-findings.md#f-20-valid-messages-do-not-establish-faithful-result-capture) records this source-reviewed assumption and the proposed experiment's automatic block; no bypass was executed. Resolve the capture boundary and common ownership rules before expanding the facades.

**Authorized investigation:** a different Python engine may be explored solely for protected correctness testing; the delivered application and all performance measurements remain on CPython. Begin with exact-release runtime startup, host-owned result capture, and its observable Python semantics. In parallel, qualify the unchanged original suites and compare their collected tests, skips, and results with the references. Keep ordinary compatibility runs distinct from protected execution. GraalPy is the initial source-reviewed option, not an adopted runtime. Successful startup or a scalar-return demonstration cannot close Phase 2.

**Recorded checkpoint:** GraalPy Community 25.2.4 starts under `UNTRUSTED`; startup and 15 benign capture checks have independent repetitions. The unchanged Markdown recursion test and all 88 API tests pass in one guest context, with matching test IDs/skips and unchanged inputs. That is bounded compatibility, not assertion protection. A separate two-context experiment preserves several normal interactions but changes exact list type and fails its combined inheritance/`super()` operation with `RecursionError`. Three dependent checks remain unexecuted. These latter results are reviewed implementer runs, not independently repeated full-suite evidence. [F-21](reward-hacking-findings.md#f-21-a-protected-host-still-needs-faithful-python-operations) and the [feasibility report](execution-feasibility.md#authorized-investigation-a-separate-engine-for-correctness-tests) explain the evidence and limits. Investigation is paused at the user's request; GraalPy has not been adopted.

For each mechanism, retain direct-original controls, actual selected-candidate execution, known failure cases, and negative controls for malformed data or evaluator interference. Identify exactly which objects and operations are permitted across the boundary. Then validate the complete arrangement against the required interfaces and suites, retain F-10/F-13/F-14 as regression cases, and reproduce it independently. Known callback source can still perform unintended actions on candidate-controlled data; the probes' limited I/O observations do not prove arbitrary callbacks safe. The successful subsets supply no performance evidence and do not close Phase 2.

For potential SkyDiscover reuse, test the smallest path from a product-independent task through Codex to a multi-file library change, an immutable snapshot, and a development result. Verify cancellation and all child-process termination. Apply the same controls to any upstream adapter/helper. Role files, edit hooks, hashes, and evaluator callbacks are not isolation by themselves. If AdaEvolve cannot fit these controls, retain the direct Codex path and record why.

**Deliverable and completion condition:** record at least one permitted local arrangement that supports Codex and the required execution boundaries. Extend protected testing to all required real-pair interfaces/suites without changing the tests' meaning, reducing required coverage, or substituting the baseline. Instructions asking an agent not to read files or separate directories with unchanged permissions do not qualify. If the boundary cannot be demonstrated, resolve it before implementing search.

## Phase 3: resolve the design and evaluation contracts

**Purpose:** turn verified feasibility into implementable decisions. Write `docs/design.md` when the necessary evidence exists; that file is a future deliverable, not an existing architecture.

| Decision | Required outcome |
| --- | --- |
| Generator implementation and entry points | Language, packaging, invocation, and input validation suitable for the selected environment |
| Agent responsibilities | Task inputs, allowed context, outputs, and independence requirements; decide agent count from these responsibilities |
| Specification-aware candidate audit | Inputs drawn from intended application behavior, candidate source, and permitted development evidence; audit cadence within the shared budget; validated counterexamples and protected findings; version mandatory development additions and invalidate stale eligibility while preserving the frozen final contract |
| Backend integration | A product-independent task/result contract with an initial Codex CLI implementation |
| SkyDiscover reuse and search integration | Which ideas or code to adapt, the pinned source and attribution for copied code, dependency costs, and the boundary between search policy, Codex execution, and the protected controller; leave AdaEvolve adoption conditional on the Phase 6 comparison |
| Execution protection | Tested process and filesystem boundaries, protected repository assertions, network policy, permitted output locations, and treatment of shared context and untrusted instructions |
| Repository and environment management | External checkouts, preserved baseline, isolated candidate snapshots, dependency selection, and build environments |
| Stage lifecycle | Allowed transitions, elapsed-time accounting, termination, candidate eligibility, final failure handling, and evidence preservation |
| Artifact ownership | Which component creates, validates, freezes, reads, and writes each artifact |
| Assumptions and evidence | Source-backed specialization assumptions, treatment of hallucinated APIs or unsupported workload claims, required execution evidence, and mapping of the attack catalog to enforcement and tests |
| Standalone delivery | How generated evaluation scripts run and produce reports without importing or invoking the generator or an agent |

Separate responsibilities that need protection without assuming each needs an agent. Use deterministic code for deadlines, identities, calculations, and authoritative acceptance. Use existing agent runtimes for agent work instead of building a new reasoning/tool loop.

Adapt SkyDiscover's distinction between behavior requirements, workload observations, and environment constraints. Record the sources supporting each. An observed workload property cannot narrow supported behavior. Keep task descriptions independent of the product used to execute them. Distinguish completed, failed, and incomplete results; a numeric search score cannot override correctness or missing work. Prefer the underlying idea over importing helpers with incompatible runtimes or unnecessary dependencies.

For each pair, complete a protocol that specifies:

- Sources, claimed population, exact membership, weights, separation units, and duplicate/related-input treatment.
- Baseline tests/results, fixed output comparisons, permitted normalizations, edge cases, and relevant state/side effects.
- Full application timing and logical library work, including startup, input preparation, caches, background work, and any justified reuse of preparation costs.
- Paired ordering, environment controls, repetitions, exclusions, aggregation, sampling units, and two-sided 95% confidence-interval calculation.
- Development ranking, plus how memory use and per-workflow regressions affect acceptance.
- Setup, search, and final/reproduction limits, informed by measured execution costs.

The generated setup process will create and audit the actual contract for each formal run. Missing fields must block search. The plan introduces no numerical time limits, regression limits, or statistical defaults.

The accepted audit policy is to grow validated mandatory **development** checks while keeping final evaluation fixed. Define admission and check-set versioning. Adding a check makes earlier candidate eligibility stale until rechecks pass; old results finishing late cannot restore it. Audits, validation, and rechecks share the search deadline. A finding requiring changed final rules ends the run and requires a new audited run with exposure history preserved.

**Completion condition:** the design shows both pairs passing through the same workflow, with explicit task inputs, outputs, ownership, and verifiable behavior. Resolve unanswered choices before dependent implementation.

## Phase 4: build controlled execution and backend integration

**Purpose:** implement the shared machinery the later agent workflow relies on. Establish versioned generator source, its development environment, and test entry points using Phase 3 decisions.

Build only what is needed to validate run inputs/external paths; prepare pinned sources/environments without altering controls; execute commands within declared access/time limits; capture actual results and loaded dependencies; maintain immutable candidate/evaluator identities; enforce controller-owned stage transitions; invoke Codex through the product-independent task/result interface; and export executable checks that work outside the generator.

Consider SkyDiscover's digest, audit-freshness, measurement, and export helpers as references. An audit must identify the exact candidate and evaluation inputs it covered. A later source change makes that approval stale. Reject changed exports and mismatched records. These identity checks complement isolation; they do not prevent unauthorized access. Reuse must not make independent reproduction require SkyDiscover or an agent.

Use a small repository fixture and a deterministic test backend to exercise the contract. Swap that backend without changing workflow or acceptance code, then run a live Codex task. This demonstrates replaceability without requiring a second production agent integration.

**Completion condition:** the fixture builds and runs under protection; forbidden writes and forged results do not become accepted evidence; deadlines stop unfinished work; exported checks run without the generator/agent. Preserve failures rather than inventing successful results to advance a stage.

## Phase 5: automate experiment construction and audit

**Purpose:** demonstrate that the generator can create an experiment from repositories and supplied usage sources, rather than relying on our hand-written research harnesses.

1. Collect exact usage material and record its origin. Establish original build/test behavior.
2. Generate replay, original-behavior comparisons, edge cases, measurement scripts, and reproduction instructions.
3. Audit the replay against sources and baseline references. Introduce representative faults and confirm that checks detect them.
4. Validate the complete contract, establish protected development/held-out separation, and freeze approved artifacts.
5. Execute exported baseline build, tests, replay, and reporting in a fresh environment or controlled reset.

For a generated check claiming to detect a fault, adapt SkyDiscover's validation method: it must pass the original and reject a deliberate variant exhibiting that fault. A **mutant** is such an intentionally incorrect variant. A check failing the original, passing both implementations, or merely timing out does not establish the claimed fault detection. Preserve original tests and record the limited coverage each mutant demonstrates. Complete setup validation before freezing protected checks.

Keep any setup/audit context containing held-out information out of optimization. Fix audit failures within setup; exceeding its limit leaves the run incomplete.

Integrate first with one pair, then use the second to check that the same construction process works from different inputs. Pair-specific generated scripts belong in external outputs. Hand-written generator branches or manually repaired experiments cannot count as automatic construction.

**Completion condition:** the system produces an audited, independently executable real-input experiment. Required baseline tests pass and deliberate bad behavior fails. Compare baseline against baseline first to check dependency selection and comparisons before assessing specialization.

## Phase 6: implement specialization search and complete the workflow

**Purpose:** connect candidate generation, protected evaluation, selection, and delivery under one budget.

1. Give the optimizer only permitted application/library context and development evidence. Generate and snapshot a library candidate while preserving application logic/calls and the library language/runtime.
2. Run the latest mandatory development correctness checks. Identify the exact candidate and check set in each result before considering performance for selection.
3. Measure candidates that have passed the required correctness checks, using the fixed development procedure. Retain failed attempts and execution records.
4. Continue search after an early target is met. At expiry, stop unfinished work and select only a candidate with completed required audits/checks/measurements using the declared ranking.
5. Freeze that candidate, run protected final evaluation, and calculate results from recorded observations.
6. Produce the library commit and experiment directory. Verify that delivered source and actually loaded code match the evaluated snapshot.
7. Execute the README independently before declaring success. Preserve the specific outcome and available evidence for failures or incomplete runs.

Review candidate behavior independently during search. Admit new mandatory development checks only after validating the existing requirement, reference, and intended fault. Version them under controller ownership and recheck eligibility, including candidates whose older evaluation finishes later. Preserve checks/evidence and share the original deadline. Final tests/data, comparison/measurement rules, thresholds, and ranking stay fixed. A required contract change ends the run. Export new development checks and their validation for standalone reproduction.

Debug using fixtures and declared development data. Do not repeatedly consult final reserves while developing. After final failure, further optimization requires a separate run and fresh final-evaluation planning under the [scope](scope.md#system-responsibilities-and-workflow).

### Compare search strategies only after the direct path works

Start with a direct Codex loop: generate, evaluate, provide structured development feedback, and revise. Keep final data and authoritative controls outside its context.

If Phase 2 supports a viable integration, compare AdaEvolve on development data using the same Codex settings, sources, evaluator, hardware, and elapsed-time allowance. Fix comparison measures, repetitions, and adoption criteria in the design first. Compare completed valid candidates, measured development gains, runtime overhead, and maintenance/integration complexity. Upstream benchmark claims cannot substitute for this trial.

Adopt AdaEvolve only if results justify it and it respects access, deadline, eligibility, and lifecycle rules. Otherwise retain the direct loop and document why. Neither strategy controls acceptance rules. Other search algorithms, a knowledge base, and a dashboard remain optional future work.

**Completion condition:** the full workflow, including rejections and timeouts, runs without manually supplied library implementations or application changes. Integration success remains separate from formal performance success.

## Required validation before formal demonstrations

These checks validate observable requirements during Phases 4–6. They are not an additional feature backlog.

| Behavior | Required check |
| --- | --- |
| Agent replacement | Substitute a test backend without changing workflow or acceptance logic; verify the initial Codex backend with an actual invocation |
| Evaluator independence | Reject attempted protected reads/writes and forged verdicts from agent tools, candidate code, and build processes |
| Untrusted content and transport | Repository guidance, logs, and tool output cannot change protected authority; hostile or malformed result data cannot execute in the checker or become a pass |
| Correctness integrity | Detect representative wrong outputs, errors, state changes, reduced test collection, and weakened checks |
| Generated-test validation | Verify that a check passes the original and detects its intended deliberate fault; reject reference failures, nondiscriminating checks, and inconclusive validation as coverage evidence |
| Development-check evolution | Adding a validated mandatory check invalidates prior eligibility; older in-flight results cannot restore it; rechecks and audit work share the deadline; final checks, workloads, measurement rules, and ranking stay unchanged |
| Measurement integrity | Keep required work inside its declared boundary; reject missing measurements and apply the frozen repetition/exclusion rules |
| Confidence-bound acceptance | Check that an adequate point estimate with an inadequate confidence bound cannot pass either threshold |
| Budget enforcement | Stop unfinished work, exclude incomplete candidates, continue search after an early development success, and preserve completed evidence |
| Artifact correspondence | Reject stale audits, changed evaluator artifacts, candidate code that differs from the evaluated snapshot, and source changes during export |
| Evidence integrity | Reject invented or mismatched command/test/measurement records and contaminated reference answers; factual report claims must have matching execution evidence |
| Independent reproduction | Build, test, replay both variants, and calculate results using exported artifacts without generator or SkyDiscover imports or agent access |

Use focused automated checks and an end-to-end integration run. Synthetic examples establish system behavior, not real-world performance gains. Use the [defense catalog](reward-hacking-defense.md#failure-catalog-and-concrete-defenses) for concrete attack/error cases and record which variants actually ran. Resolve library timing separately from the protected process-clock probe. A source audit, matching test count, or plausible report cannot establish that assertions or measurements were protected.

Exercise the development-check policy with a candidate that passes initial tests only because a required behavior lacks coverage. A validated new counterexample must make it ineligible. A compliant candidate becomes eligible again only after passing the added check, within the deadline. Confirm that audits cannot rewrite requirements or weaken checks, changed candidates invalidate old audits, and changes needed to the frozen contract end the run with evidence retained. Test assertion protection separately; a favorable audit does not provide it.

## Phase 7: execute two formal demonstrations on one generator revision

**Purpose:** demonstrate the actual first-version result after implementation and validation pass. Freeze the generator revision and run both pairs with pinned sources, complete audited contracts, chosen stage limits, and recorded held-out exposure history.

Each pair must provide passing repository tests, original-behavior comparisons, edge cases, and declared coverage/exclusions. It must establish at least **1.5× library** and **1.2× application** speedup at the lower endpoint of each two-sided **95% confidence interval**. Report separate library/application measurements, memory, workflow regressions, raw observations, and limitations.

Explain the application-specific mechanism. Deliver a commit on the pinned library baseline, selected through the application's normal dependency reference, and a complete external experiment whose independent reproduction has run successfully. Both pairs must use the same generator revision and requirements; success on one cannot offset failure on the other.

If the second pair reveals a generator defect, distinguish a general repair from a forbidden hand-written special case. Preserve earlier results, resolve ambiguity, freeze the corrected generator, and rerun both demonstrations on it. Any optimization following final-data exposure needs fresh final-evaluation planning.

**Completion condition:** two accepted, independently reproducible results from the same generator. If a pair fails, record that result and use permitted development research or revisit qualification. Do not reduce targets, shift timing boundaries, or relabel exposed data to claim success.

## Phase 8: review evidence and complete delivery

**Purpose:** make it possible to audit the claim that v1 is complete. Create `docs/validation-report.md` mapping each acceptance requirement to executed evidence for both pairs. Verify generator/source revisions, delivered commits, frozen protocols, audit results, correctness, timing intervals, and independent reproduction records.

Record which SkyDiscover ideas/code were adopted or rejected and why, including the search-strategy comparison. Preserve pinned origins, modifications, and required attribution for copied code. Align design and assessment with the implemented system.

Check each external README for exact setup, repository/data preparation, build/install, test, paired timing, and comparison commands. Include expected outcomes, access requirements, initial state, and output locations. Replace placeholders with exercised commands and artifacts.

Review existing evidence; repeat execution only for a missing record, relevant change, or specific unresolved concern. Distinguish implemented features, executed checks, measurements, failed attempts, and limitations.

**Completion condition:** all scope requirements hold for the reusable system and both demonstrations, and the user can reproduce results outside the agent system. This supports reuse; it does not guarantee gains for arbitrary future pairs.

## Handling blocked phases

These phase gates apply to the reusable system. The supervised pilot follows its explicit review-based boundary above; missing workload, correctness, timing, budget, or held-out rules still block pilot optimization.

| Finding | Required response |
| --- | --- |
| Missing or ambiguous usage context | Stop and ask for the missing information; do not invent workload representativeness |
| Insufficient measured performance opportunity | Revisit candidate qualification with the recorded evidence |
| Unproven evaluator or held-out protection | Stop before optimization and resolve the execution boundary |
| Unclear correctness, timing, or resource policy | Ask for clarification and record the answer before freezing the experiment |
| Failed final evaluation | End that run, preserve evidence, and use the agreed separate-run policy for further optimization |
| Generator changes after a formal demonstration | Preserve old results and validate both pairs on the final shared revision |

No calendar schedule or numerical experiment budget is assumed. Measured build/replay costs will inform those choices. The next step is one non-Python baseline build, original-test run, real-job replay, and profile to qualify the supervised pilot. General protected repository-test execution remains deferred and unresolved.
