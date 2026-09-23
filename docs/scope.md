# Just-in-Time Library: project scope

Updated: 2026-09-23

Just-in-Time Library is a proposed tool that changes an external library to make a particular application faster. The application continues to use the library through its existing interface. The central question is whether specializing a dependency for its application's use case produces substantial, reproducible gains while preserving behavior.

This document defines what we have agreed to build and the conditions a result must satisfy. The requirements are agreed; the system design and some experiment settings remain open. Earlier Python pairs have recorded baseline results. On 2026-09-23, the user directed us to find candidates in another language that eliminate or substantially reduce the protected-test difficulty. Those Python pairs are now historical research, not the active implementation target. We have not implemented the generator, produced a real specialization, or demonstrated either required speedup. See the [execution plan](execution-plan.md) for current progress.

## Terms used in this document

| Term | Meaning in this project |
| --- | --- |
| Application–library pair | An existing application and one external library it uses, such as yamllint and PyYAML. |
| Generator | The Just-in-Time Library software we will build. It coordinates agents, experiments, and delivery. |
| Baseline | The pinned, unchanged application and original library used as the reference for comparison. “Pinned” means identified by an exact version or Git revision. |
| Candidate | One proposed version of the specialized library. A candidate is not a successful result until it passes all required checks. |
| Workload and replay | A workload specifies actual inputs, configuration, an operation, and the starting state. Replay means executing that operation again under recorded conditions. Linting a real repository is one example. |
| Development and held-out workloads | Development workloads guide optimization. Held-out workloads remain unavailable to the optimizer until a candidate has been selected for final evaluation. |
| Evaluator and controller | The evaluator runs correctness checks and measurements. The controller enforces stages, deadlines, access restrictions, and acceptance decisions. Candidate code and agents must not control these decisions. |
| Frozen evaluation contract | The recorded rules for an experiment: what runs, what counts as correct, how time is measured, how candidates are ranked, and what constitutes success. Freeze these rules before search so a poor result cannot cause the rules to change. |
| Artifact identity and provenance | The exact revision or content hash identifying an input/output, together with records of where it came from and how it was produced. |
| Reward hacking | Obtaining a favorable evaluation without satisfying the intended task, for example by reporting fabricated test success or omitting work from the measured interval. |

## Goal and first-version milestone

The hypothesis is that knowledge of an application's library usage can justify changes that improve both library performance and complete application performance without changing supported application behavior. [SkySynth: Building Specialized Systems We Can Trust with Agents](https://skydiscover-ai.github.io/blog-skysynth.html) inspired this approach. Our task applies it to the boundary between an existing application and one dependency.

**Immediate milestone, agreed 2026-09-23: one supervised pilot first.** Take the shortest credible path to testing this hypothesis with one non-Python application–library pair. Retain original tests, independent comparisons against original outputs, additional edge-case checks, held-out inputs, reviewed agent-generated library changes, and both existing confidence-bound speedup targets. Build, test, measure, and reproduce the result through standalone tools in an external experiment directory. The pilot may use manually prepared and reviewed experiment tooling; it does not demonstrate automatic experiment construction.

Defer the reusable generator and its general adversarial-protection machinery until after this pilot. The pilot relies on direct review of proposed changes and independently controlled evaluation; it does not claim safety against arbitrary hostile library code or protection of every in-process assertion. Completing the earlier protected-runtime investigation is not a prerequisite for this supervised experiment. The full-v1 requirements below remain the later milestone, and a successful pilot alone cannot satisfy them.

The first version must be a reusable generator and must demonstrate successful specialization on **two distinct application–library pairs**. Both demonstrations must use the same generator revision and the same correctness and performance requirements. Each pair supplies its own repositories and usage sources. The system may generate pair-specific replay scripts and library changes as experiment outputs. We must not hide hand-written optimizations in generator branches, prompts, configuration, or helper scripts: the agent must discover and implement the specialization.

A pair is identified by its upstream application and library projects. Different forks, revisions, checkout paths, or workload splits of the same projects do not count as two pairs. Both pairs must pass; one cannot compensate for the other. Two successes would provide evidence that the generator is reusable, not a guarantee that every library can achieve the targets.

Despite the project's name, specialization happens **offline, before application execution**, for fixed application and library versions. “Offline” here describes when generation happens. Version 1 does not adapt the library while the application runs.

## Repositories, inputs, and outputs

There are three repository roles:

| Repository | Responsibility |
| --- | --- |
| Just-in-Time Library | Holds the reusable generation and coordination code. |
| Application | Holds the consuming application, its dependency reference, and its existing build and test tools. |
| Library | Holds the dependency source. The successful specialization becomes a normal Git commit on top of its selected baseline. |

The application and library checkouts must be outside the generator source tree. Each run also creates a standalone experiment directory outside all three repositories. That directory is an output, not a required fourth repository.

The caller supplies the application revision, library baseline revision, real usage data or explicit locations from which to collect it, and elapsed-time limits for setup, search, and final evaluation/reproduction. For the initial demonstrations, candidate research will identify suitable usage sources. The system need not discover sources unaided, but it must collect the supplied material and construct its own replay and evaluation tools. We do not assume that the application already provides performance benchmarks.

A successful run delivers:

1. A library commit containing the specialization.
2. An external experiment directory containing the workload records, scripts, checks, raw measurements, and exact reproduction instructions.

The user selects the new library by updating the application's dependency version or path. The library must build and run through its normal interface. Neither the generator nor an agent may be required at application runtime.

## Candidate-selection criteria

Start with manageable applications and one external dependency per application. A promising pair must satisfy these conditions:

| Criterion | Requirement or preference |
| --- | --- |
| Adoption | A mature application with substantial independent use. Wide use within a domain qualifies. |
| Language | No language preference. Actively select non-Python application/library pairs whose language properties and interfaces make trustworthy evaluation substantially simpler. Changing only the generator language does not satisfy this decision. |
| Source and setup | Accessible source for both projects and a reproducible build and execution setup. |
| Dependency relationship | Evidence that the application uses the library, including the relevant interfaces and execution paths. |
| Workload evidence | Complete real project jobs with actual inputs and configurations qualify for v1. Recorded CI or production executions are not required. Define what population a real-input corpus represents and what it cannot establish. |
| Performance opportunity | Measurements showing that enough application time goes into the dependency to make both targets plausible, plus a reason to investigate avoidable general-purpose work. |
| Specialization opportunity | Application-specific facts that could justify a different library implementation. |
| Correctness evaluation | A practical way to compare complete application behavior, including errors and less common supported cases. |
| Replay | Workloads that run on the agreed local hardware without live external services. |

A **corpus** is a collection of inputs. YAML configuration files are themselves the data yamllint processes; its separate lint configuration controls the processing. For MkDocs, documentation files and assets are the inputs to a site build. A complete configured lint job or documentation build is sufficient real-world workload evidence for v1. Record its inputs, command, configuration, execution order where relevant, and starting state.

A large corpus can demonstrate input diversity without telling us how often users perform each operation. Recorded usage might establish commands, requests, configurations, frequencies, sequencing, and initial state, but we must not invent missing information. Limit performance claims to the declared workload population. The accepted source criterion does not remove the need for separate held-out evaluation.

Keep measured profiling results separate from optimization hypotheses inferred from source. Recommending a pair does not demonstrate a speedup.

## System responsibilities and workflow

The generator must construct the experiment as well as specialize the library:

1. **Establish the baseline.** Record revisions and environment, verify the actual dependency relationship, and establish the original application's build and test behavior.
2. **Collect and reconstruct usage.** Retrieve the supplied material and determine the inputs, commands, configuration, state, and sequence required for replay. Surface information missing from a faithful replay.
3. **Generate standalone evaluation tools.** Produce replay scripts, correctness comparisons, measurements, and reproduction instructions. Reuse applicable application and library tests.
4. **Audit and freeze the experiment.** A separate review checks the generated evaluator against usage evidence and original behavior. Establish development/held-out separation and fix the experiment rules before optimization.
5. **Search for a specialization.** Give the optimizer application/library context, development inputs, and development feedback. Independently review proposed candidates for violations of supported behavior. Validate any new development checks before admitting them.
6. **Continue within the search allowance.** An early development success does not stop search. Maintain eligible candidates: those with complete required audits, passing checks from the latest admitted check set, and completed development measurements.
7. **Select and freeze one candidate.** Apply the ranking fixed before search, then run the protected final evaluation on held-out workloads. Final results must not guide the search that selected this candidate.
8. **Deliver and reproduce.** Export the library commit and experiment directory. Execute the documented build, test, and benchmark workflow outside the generator before declaring success.

Development failures may be repaired within the search budget. A final correctness failure or failure to establish either required speedup ends the current run. Report the actual outcome and preserve the candidate, results, and measurements. Incomplete checks are not passes.

Further optimization after final evaluation requires a separate run and an explicit plan for fresh final-evaluation data. Previously revealed examples or scores may become development evidence, but they cannot be described as untouched final evidence. Link attempts and preserve exposure history so restarting does not erase failures or data already seen.

## Correctness boundary and permitted changes

The specialization must preserve the selected application's **full supported behavior**: features, configurations, valid inputs, errors, and relevant observable effects, including supported cases absent from the measured workload. Testing on one machine limits our evidence; it does not permit removing behavior supported elsewhere.

Workload observations suggest optimization opportunities. They do not establish universal facts. For example, seeing only ASCII documents does not authorize removing Unicode support. An assumption must follow from the application's supported behavior, or the candidate must handle cases where it is false, such as with a checked fast path and a correct general fallback. Library functionality may be removed only when the application does not require it within this boundary.

Keep application logic and library call sites unchanged. Only the dependency reference may switch between the original and specialized library. Keep the selected library's existing implementation language and normal runtime in v1. The new language decision permits selecting different upstream projects; it does not authorize translating a selected library into another language to manufacture the gain.

Within these limits, the agent may change algorithms, data structures, and executed code. It need not limit itself to deleting unused functionality. Each result must explain the application facts that enabled the change, such as fixed options, known argument types, or recurring operation patterns. A change may also help other applications, but speed alone does not establish application-specific specialization.

On 2026-09-21, the user confirmed that v1 should retain this broad code-editing freedom and investigate stronger protected execution. We will not constrain generated changes to a predefined family of mechanically verified transformations. This selects the research direction; it does not establish that a suitable execution mechanism already works. Protected repository assertions, unchanged test meaning, and the library's normal delivered runtime remain requirements.

The earlier investigation of a different Python engine applied only to correctness tests for the Python pairs; their delivery and timings remained on CPython. No alternative engine was adopted. That investigation is now set aside in favor of candidate reselection. For a new pair, correctness and performance must still be tied to its normal delivered behavior. A passing ordinary suite alone does not establish protection of assertions or faithful capture of candidate results.

The user emphasized that testing the specialization hypothesis is the primary objective. Solving general Python isolation is not a deliverable. Prefer a pair that avoids those complications; preserve the existing correctness, independent evaluation, workload, and speedup requirements. Broad algorithm and data-structure editing remains allowed. Any additional restrictions on candidate code must be made explicit and justified for the selected design, rather than silently imposed or confused with restricting edits to predefined transformations.

Correctness requires all of the following:

- The existing application suite and library tests relevant to the application's supported behavior.
- Comparisons between original and specialized application behavior on real and generated inputs.
- Invalid inputs, errors, edge cases, and relevant side effects.
- Checks of supported behavior that the performance workload does not exercise.

Finite tests provide evidence; they do not prove correctness for every possible execution. Formal verification remains a later objective.

## Evaluation independence and agent boundaries

The evaluator must control acceptance independently of the optimizer. Neither agents nor generated code may change authoritative tests, benchmark code, measurement rules, final workloads, or results. The optimizer must not receive current-run held-out examples or feedback during development.

This restriction covers build scripts, child processes, collaborating agents, shared logs, caches, agent memory, artifacts, and alternate copies of workload sources. A role that has seen current-run held-out material cannot carry that knowledge into optimization. During final replay, the application naturally receives its input; candidate execution still receives no authority over reference answers, evaluator internals, or verdicts. An access or integrity breach invalidates the evaluation.

Protect the controller, acceptance rules, budget accounting, original application, and baseline library against agent and candidate modifications. Preserve the allowed dependency-reference switch. Keep environments equivalent except for the selected library and changes needed to build it: pin application settings, runtime options, other dependencies, and initial-state policies. A candidate may not slow the baseline, substitute its configuration, or depend on undeclared files or runtime services.

### Repository assertions need protection too

An **assertion** is the actual check inside a test, such as comparing a returned title with its expected value. If a Python library shares an interpreter with the test runner, it may modify that runner in memory and report success without executing assertions. Read-only test files do not prevent this. We reproduced exactly that failure; see [F-01](learnings/reward-hacking-findings.md#f-01-a-library-can-make-repository-tests-report-success-without-running-their-assertions).

The reusable v1 system must protect existing repository assertions and verdicts from such interference. Matching external application outputs is insufficient if the repository tests can be forged. Do not skip tests or weaken assertions to avoid the problem. Demonstrate a faithful protected execution arrangement before implementing the dependent reusable system. For the earlier supervised pilot, run the original suites and review changes for evaluator interference, while explicitly recording that general assertion protection remains unestablished. The [feasibility report](learnings/execution-feasibility.md) records the unresolved work, and the [defense investigation](learnings/reward-hacking-defense.md) distinguishes proposed controls from executed evidence.

### Audit the evaluator before using it

Agents may construct evaluation tools during setup. A separate audit must then check replay fidelity, compare baseline behavior with original tests or recorded results, and demonstrate that the generated checks reject representative incorrect results or deliberate faults. Record coverage, limitations, findings, and evidence. Resolve failures before freezing the experiment. Keep audit context independent of optimization; this requirement does not select an agent count.

The audit must approve a complete evaluation contract: commands, exact artifacts, comparison rules, workload membership, timing boundaries, aggregation, repetition and exclusion rules, candidate ranking, stage limits, and how memory use and per-workflow regressions affect acceptance. Missing rules block search. An auditor cannot waive requirements to make a result pass.

### Add development checks without changing final evaluation

A **specification-aware audit** reviews candidate code against intended behavior, including behavior missing from current tests. It may discover an error and propose a new check. The agent may inspect development failures and timings and propose tests; only the protected controller can admit a test as mandatory.

A new check must enforce an existing requirement, pass the pinned original, and reject a deliberately faulty variant demonstrating the claimed error. Keep the requirement, counterexample, and execution results together. A reference failure, inconclusive result, or faulty variant timing out does not alone show detection of the intended error. Ask the user if intended behavior is ambiguous. Auditors may use development evidence, not current-run final inputs or results.

Freeze the admission procedure before search. Version the admitted check sets separately from final artifacts. For example, a candidate that passed check set 1 is not eligible under set 2 until it also passes the added checks. A late result from set 1 cannot restore eligibility. Preserve prior evidence and perform rechecks within the original search deadline. At selection, every eligible candidate must have complete passing evidence for the latest admitted set. Do not drop a check or revert to an older set to recover a favorable candidate.

Final tests, held-out data, comparison and measurement rules, thresholds, and ranking remain frozen. If a finding requires changing that contract, end the run without accepting a result. Preserve the finding and begin a new audited run under the exposure-history policy. This policy does not weaken repository-assertion protection.

### Rules that prevent misleading acceptance

| Question | Required interpretation |
| --- | --- |
| Which tests are relevant? | Before search, freeze the application suite, selected library tests, collection counts, existing skips and expected failures. Explain exclusions and coverage gaps. Required baseline checks must pass. Version later development additions separately; candidates cannot pass by removing tests, collecting fewer tests, adding skips, or weakening assertions. |
| What does “same behavior” mean? | Use the pinned original or independent existing expectations. Specify outputs, exit status, errors, and relevant state changes. Justify every tolerance or normalization from baseline behavior before search; do not relax comparisons after candidate failures. |
| Which inputs count? | Freeze source records, input hashes, membership, split units, and weights against the declared population. Account for duplicates and related inputs across development and held-out groups. Do not remove slow or failing cases after seeing results. |
| What time counts? | Fix the complete application request/job boundary. Include required input preparation, initialization, cache population, output/effects, background work, and teardown. Candidate-only work cannot disappear into untimed setup. Any amortization must follow a lifecycle supported by usage evidence. |
| What is library work? | Follow the same logical library operations, including helpers and background work, in both variants. Moving work to another file, module, thread, or process cannot remove it from measurement. |
| What is legitimate specialization? | Do not embed replay answers or recognize evaluator identity, fixture names, or evaluation mode to choose benchmark-only behavior. Caching/precomputation must remain correct beyond the corpus, with preparation/reuse costs counted. Static specialization based on application invariants remains allowed. |
| Which measurements contribute? | Apply fixed repetition, aggregation, outlier, and retry rules to both variants. Keep raw observations and exclusion reasons. Do not discard candidate failures as outliers or keep sampling until a favorable result appears. Missing measurements are not passes. |
| Which code passed? | Bind development, final, and reproduction evidence to immutable candidate snapshots. Deliver the evaluated code. Verify the dependency actually loaded and unchanged application/baseline controls. Candidate changes require reevaluation under the final-evaluation policy. |

### Agent replacement and standalone execution

Agent roles and count remain design choices. Define responsibilities, permitted context, task inputs, expected outputs, and access restrictions separately from the agent product. Replacing an agent may need backend integration, but it must not require rewriting the workflow or acceptance rules. The replacement must satisfy the same task and access requirements.

Use Codex CLI for initial coding-agent work. Coordinate an existing runtime rather than implementing model calls, tool execution, or a reasoning loop from scratch. Executable evaluator checks determine acceptance regardless of agent participation.

The exported evaluator must also run without the generator, Codex CLI, or another agent. Documented application/library build tools and ordinary evaluation dependencies are permitted.

## Performance requirements and execution environment

Each pair must pass both requirements on held-out workloads:

| Measurement | Required speedup |
| --- | --- |
| Library work within the application's use case | At least **1.5×** |
| Complete application execution | At least **1.2×** |

Elapsed-time speedup is `baseline time / specialized time`. A 150-second library operation taking 100 seconds after specialization is 1.5× faster. An application whose elapsed time falls from 120 seconds to 100 seconds has a 1.2× speedup.

Measurements vary, so a favorable average alone is insufficient. For each metric, the **lower endpoint of a two-sided 95% confidence interval** must meet the target. Report the estimate and interval. An application estimate of 1.21× with interval 1.10×–1.32× does not pass 1.2×: the required gain is unestablished. Report that final evaluation as inconclusive and end the run. Fix the statistical method, sampling units, repetitions, and stopping rule before search and include them in the audit. The interval concerns the declared workloads and environment, not all future usage.

Apply each target to that pair's aggregate workload result, not to each individual workflow. Report library and application results separately, along with per-workflow variation, regressions, and memory use. One pair's result cannot compensate for the other's.

Both targets matter because improving a small part of an application may barely affect total time. If library work takes half the baseline application time and becomes exactly 1.5× faster while everything else stays unchanged, total application speedup is 1.2×. Measure the library's runtime contribution during candidate assessment.

Use one CPU-only machine, preferably the local Mac; a local Linux container is acceptable. Replay must not require live external services or a GPU. Data acquisition and agent invocation occur outside timed application replay.

Measure equivalent completed work under comparable conditions. Rerun the original baseline alongside the candidate in the final paired repetitions; old setup timings are insufficient. Fix run order and initial state, control competing machine activity, record the loaded library/environment, and distinguish instrumented profiling from speedup measurements.

Before optimization, resolve corpus size, coverage, weights, development/held-out separation, aggregation, repeated timing, uncertainty, and candidate ranking. No numerical per-workflow regression or memory limit has been agreed. Document how both affect acceptance before starting a run.

## Run budgets and stopping policy

Each run has configurable elapsed-time limits for three stages: setup, optimization search, and final evaluation/reproduction. No numerical durations, token limits, candidate-count limits, or spending caps have been agreed.

The search clock starts only after setup, evaluator audit, and contract freeze finish. It covers candidate generation, candidate auditing, validation/admission of new development checks, correctness/performance evaluation, and eligibility rechecks. All agents share that elapsed-time allowance; more agents or checks do not create more time.

Continue within the allowance after an early development success. At expiry, stop unfinished optimization work and select the best eligible candidate under the predefined ranking. Required audits/checks and development measurements must have finished. Preserve incomplete artifacts, but do not select them. If no candidate qualifies, report an unsuccessful run.

Setup establishes and audits the baseline and evaluator. Generation, tuning, and development measurements count as search regardless of their process or label. The controller owns deadlines and eligibility; relabeling optimization as setup or final evaluation cannot extend the budget.

Setup and final evaluation/reproduction have their own limits outside the search allowance. If either cannot finish, report an incomplete run and preserve evidence. Deadlines do not waive correctness, performance, audit, or reproduction requirements.

## Standalone experiment directory and reproduction instructions

The external directory needs a README with exact commands, complete enough to reproduce the experiment without reading an agent conversation or generator internals. It must explain:

1. **Environment setup:** hardware/OS expectations, language/build-tool versions, evaluation dependencies, install commands, and relevant environment settings.
2. **Repositories:** application revision, original library revision, specialized commit, checkout commands, and normal dependency selection.
3. **Workload preparation:** sources, included/fetched files, acquisition/preparation commands, hashes, membership/split records, access requirements, and population limits.
4. **Building:** commands for both libraries and the application; separate environments or reset steps that prevent contamination. Explain if the language has no separate compilation step.
5. **Correctness:** original tests, generated comparisons, pass criteria, failure inspection, and coverage gaps.
6. **Performance:** both replays, repetitions/warm-ups, initial state/cache resets, and library/application/per-workflow/memory measurements.
7. **Interpretation:** comparison commands, aggregation/speedup formulas, output locations, reference results, and treatment of measurement variation.

Include executable replay/comparison scripts, the frozen contract/configuration, correctness checks, workload manifests and split identities, raw measurements, test results, audit findings/evidence, and final report. Include the data or exact retrieval instructions subject to documented access requirements.

Also export admitted development checks, version history, validation evidence, and the candidate's results against the latest set. Standalone commands must reproduce these checks and the frozen final evaluation without an auditor or generator.

Connect results to application/library/generator revisions, agent configuration, environment, exact workload contents, and frozen evaluation artifacts. No agent access or authentication may be required for exported build/test/measurement commands.

The report must explain the specialization, both speedups, memory/per-workflow results, correctness coverage, and limitations. Preserve unsuccessful and incomplete evidence without labeling it accepted. For success, execute the README workflow in fresh environments or controlled resets outside the generator. Reviewing the instructions is insufficient. Keep exported final data/results away from the optimizer during search.

## First-version acceptance

The first version is complete when all of these conditions hold:

- Two qualifying pairs pass the same requirements on the same generator revision, without hand-written pair-specific generator changes.
- The system constructs evaluation from supplied real usage sources; the agent discovers and implements each specialization.
- Each generated replay/evaluator passes its independent setup audit, with findings and evidence exported.
- The selected candidate completes required candidate audits and the latest admitted development checks within the search budget. Evidence identifies both its snapshot and check-set version.
- The run follows the frozen contract and passes artifact, isolation, and evaluated-versus-delivered code checks. An integrity failure prevents acceptance even with favorable timings.
- Repository tests, original-behavior comparisons, and edge cases support preservation of full supported application behavior.
- Each pair passes both held-out confidence-bound targets and explains its application-specific specialization mechanism.
- Each library result is a commit on its baseline and works through a normal dependency-reference update.
- Each external experiment contains complete instructions/artifacts, and independent reproduction has executed successfully.
- Reports distinguish measurements, inferred opportunities, limitations, regressions, and unsuccessful attempts.

Evaluator isolation still requires a demonstrated mechanism. Show that unauthorized reads/writes and forged results fail, including attempts from build processes and candidate code. Prompt instructions, separate agent conversations, or separate directories alone are insufficient.

## Decisions deferred to research and design

Candidate research must establish the two recommendations' sources, adoption, replay feasibility, dependency cost, specialization opportunities, and correctness coverage, then define each workload population and measurement method. Choose numerical stage limits when configuring each experiment.

System design must select agent responsibilities/count, coordination structure, backend task/result interface, generator language/entry points, repository/environment management, and enforced evaluation boundaries. These remain choices to resolve against this scope, not implicit features already selected.

There are no unresolved scope decisions blocking candidate research. Some research/design choices remain open, and every experiment must resolve acceptance settings before search. This document supplies no numerical budgets, achieved benchmark results, supported-language guarantee, or fixed agent topology.
