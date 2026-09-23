# What Just-in-Time Library can reuse from SkyDiscover

Assessment recorded: 2026-09-20. Reviewed revision: [`0d932b690670a7e544388ad362e9876c8bd256a0`][upstream].

**Research status, 2026-09-23:** this is a record of source review and proposed reuse. The supervised pilot now precedes reusable automation and search-framework comparisons. Accepted work and its current order are maintained in the [execution plan](../execution-plan.md); this assessment does not independently authorize implementation.

Just-in-Time Library will use agents to specialize an existing dependency for a particular application. SkyDiscover provides related tools for generating and improving programs. This assessment asks which ideas or small implementation pieces could help us, and what we must change to meet our own requirements.

**Current status:** these are recommendations based on source inspection and isolated helper tests. We have not selected SkyDiscover as a dependency or chosen one of its search algorithms. We did not run its complete workflows, benchmark suite, or live Codex integration. Later [Phase 2 experiments](execution-feasibility.md) exercised a direct Codex task integration without upstream execution helpers and exposed a repository-test protection gap. They do not establish AdaEvolve integration or adoption.

The [scope](../scope.md) defines acceptance. The [execution plan](../execution-plan.md) identifies where to evaluate these recommendations. Future tested architecture decisions belong in `docs/design.md`. This document does not select a language, agent count, or final experiment settings.

## Terms needed for this assessment

A **candidate** is one proposed library implementation. A **search policy** decides which previous candidates to build on and how to allocate effort; a **backend** performs coding-agent work. A **controller** enforces budgets, evaluation rules, and acceptance independently of both. An **adapter** translates a shared task/result interface into a product-specific invocation such as Codex CLI.

**Development feedback** may guide optimization; **held-out** inputs/results remain reserved until selection for final evaluation. A **mutant** is an intentionally faulty implementation used to check whether a test detects that fault. An **artifact digest** is a hash identifying exact contents. Digests reveal stale or mismatched records but do not enforce access restrictions.

## Recommendation and scope of reuse

The useful parts are the method for constructing experiments from source/usage evidence, auditing candidates against requirements, validating generated tests, tying records to exact files, checking exported results, defining product-independent agent tasks, and providing structured development feedback. Start with a direct Codex loop. Evaluate AdaEvolve as an optional search policy only after that path works.

SkyDiscover has two relevant components. **Synthesize, also called SkySynth**, supplies most of the experiment-construction, testing, audit, and export ideas. **Optimize** supplies search policies and evaluation interfaces. Our system has additional ownership rules: a protected controller must enforce evaluation, elapsed-time budgets, whether a candidate has completed the required checks, final acceptance, and delivery as a library commit. Neither component meets that whole contract unchanged. The [upstream overview][upstream] describes the reviewed architecture.

| Area | Proposed use | Execution-plan phases |
| --- | --- | --- |
| Experiment construction | Adapt the method and records; consider small helpers after design | 3 and 5 |
| Specification-aware candidate auditing | Review candidate behavior against intended requirements and turn confirmed violations into mandatory development checks while keeping final evaluation frozen | 3, 5, and 6 |
| Generated-test validation | Adapt the original-versus-deliberately-broken comparison and its explicit outcomes | 4 and 5 |
| Provenance and reproducibility | Evaluate digest, audit, checkpoint, and export helpers for selective reuse | 4 and 8 |
| Replaceable agents | Adapt neutral task descriptions and the backend separation; evaluate the Codex adapter | 2–4 |
| Search and feedback | Start with direct Codex iteration; compare AdaEvolve on development data before adoption | 2, 3, and 6 |

## 1. Construct experiments from behavior, workload, and environment evidence

SkySynth records three different kinds of information before implementation: required behavior, observed workload characteristics, and environment constraints. Its [specification builder][spec-builder] and [tools][spec-tools] turn source inspection and user answers into explicit records. Its [planner, evaluator, and critic roles][roles] use those records when making design decisions and measurements.

For our project, derive requirements from the existing application and how it uses the library. Link each claim to its source. Seeing one option value in sampled inputs does not prove the application always uses that value. A specialization assumption needs support from the application contract, or the implementation must check the assumption and fall back correctly for other supported inputs.

Use the workload record to construct replay and the environment record to reproduce it. Profile the original application to assess dependency cost and plausible opportunity. Then make the claims executable as checks: written agreement alone cannot establish faithful replay, correctness, or speedup. We need not adopt the upstream file format or Python helpers to use this idea.

## 2. Validate generated tests against deliberate faults

SkySynth's [test validator][validate-test] asks two questions: does the generated test pass the original reference, and does it fail at least one deliberately broken variant? It records acceptance, rejection, or inability to validate. Its initial-test path retains existing tests without requiring a new mutant. A mutant timing out alone does not count as detecting the intended fault. The [suite runner][suite] defines shell-based tests without requiring a particular implementation language.

Use this during setup and evaluator audit. Keep the original result, the deliberate fault, and the actual rejection together for each detection claim. A test that fails the original or passes the intended faulty variant cannot support that claim. Preserve repository tests and assess errors, side effects, and supported behavior absent from the measured workload.

This is evidence about particular checks, not proof of complete correctness. It does not authorize reducing the application's supported behavior. Complete the protected acceptance suite before search; additional development tests may be useful during search but cannot replace or weaken frozen checks.

## 3. Bind audits, measurements, and exports to exact artifacts

SkySynth's [checkpoint implementation][checkpoint] records hashes of candidate code and evaluation inputs. Audits and measurements identify those hashes; if the content changes, an older audit no longer covers it. The code also checks for changes while copying. Its [finish/export workflow][run] verifies the exported copy in a temporary location and looks for dependencies on the original source path.

These helpers illustrate how to freeze a candidate, determine whether an audit is still applicable, trace a measurement, and verify an export. Adapt the idea to our separate repositories and external experiment directory. A result needs the exact application/library revisions, candidate, fixed evaluator inputs, workload identities, and environment.

Upstream export verification still uses its test runner. Our standalone requirement goes further: the README and scripts must build, test, replay both library variants, and calculate results without SkyDiscover, the generator, or an agent installation/authentication. The delivered library must be a normal commit on its baseline, containing the code actually evaluated.

A matching hash shows correspondence between bytes and a record. It cannot prevent secret reads or prove a candidate-produced report is honest. Independently test the execution boundary. Preserve failed attempts and held-out exposure history instead of inheriting cleanup or fallback-selection behavior that conflicts with our run policy.

## 4. Keep task descriptions independent of the agent product

SkySynth separates [role descriptions][roles], which explain tasks, from [adapters][adapters], which invoke particular coding products. Its [Codex adapter][codex-adapter] generates role configuration from the shared descriptions. We can similarly define a task once and keep product-specific invocation/result handling in a backend.

Use that separation without assuming we need the upstream nine roles or nine agents. Initial coding tasks use Codex CLI. The controller supplies only permitted context and validates results. Replacing the agent product must preserve workflow and acceptance rules.

Optimize's [LLM pool][llm-pool] permits a custom model client. That alone is not a demonstrated Codex CLI integration: our project uses an existing agent runtime instead of reconstructing its model/tool loop. Before adopting an adapter, exercise actual invocation, multi-file library changes, results, cancellation, child-process termination, and protection boundaries. Phase 2's direct Codex evidence does not automatically validate the upstream adapter.

## 5. Use development feedback and evaluate adaptive search

Optimize's [context builders][context] collect previous attempts, measurements, and feedback for the next proposal. Its [search interface][search] separates choosing candidates from generating/evaluating them. Structured development feedback can help Codex repair failures and investigate measured costs while the objective stays fixed.

[AdaEvolve][adaevolve] distributes effort across groups of candidates, balances trying new approaches against refining promising ones, and moves useful candidates between groups. Maintaining several approaches might improve our search, but that is an untested hypothesis. Its candidate representation and model/evaluator connections would need to work with repository snapshots, Codex execution, protected results, and one shared elapsed-time allowance.

First make direct Codex iteration work: propose a change, evaluate it, and revise using permitted feedback. If integration is feasible, compare AdaEvolve under the same development inputs, backend settings, evaluator, hardware, and elapsed-time allowance. Fix measures, repetitions, and adoption criteria before the trial. Compare completed valid candidates, measured gains, overhead, and maintenance cost. Retain the direct path unless evidence supports adoption.

Only the protected controller decides eligibility and acceptance. Search continues within its allowance after an early development success; incomplete evaluations cannot become eligible at expiry. Freeze one candidate before final evaluation. A numeric fitness score is only a search aid: each pair must establish 1.5× library and 1.2× application speedup at the lower endpoint of each two-sided 95% confidence interval. Final failure ends the run. Further optimization needs a separate run and fresh final data planning; exposed evidence can become development material under the scope policy.

## Specification-aware auditing and reward hacking

On 2026-09-21, the user pointed to **“Auditor: Specification-Aware Auditing”**, Section 4.5 of [The Time is Here for Just-in-Time Systems][jit-paper]. The paper's auditor periodically reads implementations against the specification, finds behavior that passes current tests but violates intended requirements, and produces new checks and diagnostic guidance. Appendix B also records failures missed by code auditing and found through execution or human review. This supports combining auditing with executable enforcement; it does not establish protection of a Python test runner's memory.

For our project, make candidate auditing independent of generating that candidate. Provide its exact source, supported application behavior, evidence for assumptions, permitted development results, and timing rules. Review skipped work, removed errors, unjustified assumptions, memorized replay answers, moved timing boundaries, and checker tampering. Each confirmed finding needs a violated requirement and reproducible example. Validate proposed checks against the original and a deliberately faulty variant. Ask the user about unclear intended behavior instead of inventing a restriction.

There are two audits with different subjects: setup audits the generated experiment; candidate auditing examines the library changes the optimizer produced. Keep candidate auditing within the shared search budget, with context that has not seen the current run's held-out data. The protected controller owns findings, check admission, eligibility, and artifact identities. Neither an auditor's approval nor a numeric score grants acceptance. Agent count and audit cadence remain design decisions; the paper's topology is not selected.

**Confirmed policy:** validated findings may add mandatory development checks. The controller records a new check-set version; earlier candidates must pass the additions before they can be selected. Results finishing against an older version cannot restore eligibility. All audits, validation, and rechecks share the original deadline.

Keep final tests, held-out data, measurement rules, thresholds, and ranking unchanged. If a finding needs a change to that fixed contract, end the run and start a newly audited run, preserving findings and exposure history. The [scope](../scope.md#evaluation-independence-and-agent-boundaries) defines the policy. It does not weaken repository-assertion protection.

A new isolated check exercised the unmodified [suite runner][suite] and [test validator][validate-test] at the reviewed revision, which still matched remote `main` on 2026-09-21. The suite reported success for both an incorrect library and a deliberately failing assertion when that library replaced `unittest.TestCase.run`. The validator correctly rejected the test because it could not distinguish original from faulty behavior when explicitly given this forgery mutant; it accepted the same test against an ordinary wrong-output mutant. That demonstrates the value and the limit of mutation evidence: detecting one fault does not protect the test from another. The full upstream auditor/workflow was not executed, so this is not a claim that its auditor would miss the example. Reproduction and exact results are in the [Phase 2 experiment README](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/README.md) and `results/skydiscover-probe/report.json` there.

The confirmed requirement to protect repository assertions remains in force. Specification-aware auditing complements that boundary and does not close the executed integrity gap by itself.

The [reward-hacking findings](reward-hacking-findings.md) preserve the exact runner exploit, helper results, and a later protected fixture experiment. The [defense investigation](reward-hacking-defense.md) incorporates the user's subsequent paper, *Reality Is the Final Verifier*, and other primary research. It extends the evaluation plan without treating SkyDiscover's auditor as an isolation mechanism or adopting another framework by default.

## Compatibility gaps that require adaptation

The following source observations apply only to the reviewed revision. They explain adaptation needed for our requirements; they do not claim that upstream is unsuitable for its intended tasks.

| Upstream behavior or mechanism | Required treatment in our system |
| --- | --- |
| SkySynth can grow its checks during synthesis, and its finish workflow can choose an earlier candidate after a later check fails. [Sources][roles], [finish logic][run]. | Freeze final evaluation before search; grow only validated mandatory development checks and recheck eligibility. Select one candidate before final evaluation; a failed final evaluation ends that run. |
| The host evaluator imports evaluation code and runs stages in an executor thread under an asynchronous timeout. [Source][host-evaluator]. | A timeout around a future does not establish process termination or isolation. Prove enforcement for the agent, candidate, build tools, and children. |
| A later evaluation stage can fail or time out while measurements from earlier stages remain in the result. [Source][host-evaluator]. | Require explicit completion and correctness status before performance ranking; partial measurements cannot make a candidate eligible. |
| The container result parser can retain a positive `combined_score` when the reported status is an error. [Source][container-evaluator]. | Treat verdict and completion as gates independent of the numeric score. Container execution alone does not establish result integrity. |
| Harbor evaluation can retain reward data after a failing test command. [Source][harbor-evaluator]. | Do not equate reward availability with passing our complete correctness and measurement contract. |
| Optimize has generic score aggregation and records final test metrics in its runner. [Score aggregation][metrics], [runner behavior][runner]. | Enforce both library and application gates separately, using the lower endpoint of each two-sided 95% confidence interval. A score or recorded test metric is not final acceptance. |
| Some modes expose evaluator code as optimization context. [Runner configuration][runner], [EvoX controller][evox]. | Expose only permitted development feedback. Protect authoritative checks, held-out inputs, reference answers, controls, and indirect copies. |
| The framework edit hook recognizes selected editing tools; shell commands are outside that hook, and malformed input can pass through. [Source][edit-guard]. | Treat hooks as workflow assistance, not a security boundary. Verify actual unauthorized reads, writes, and result-forgery attempts. |
| Decision records support agent-filled defaults and metadata describing who answered. [Source][decisions]. | Ask the user about unresolved requirements. A record claiming a human decision is not evidence of authorization, and no actor may waive acceptance requirements. |
| Upstream export can depend on framework tooling and clean up working sources or run directories. [Source][run]. | Deliver independently executable experiments and a library commit; preserve required provenance and unsuccessful-run evidence. |
| Unattended helpers manage sessions, permission prompts, and restarts. [Source][unattended]. | Do not adopt their permission handling or restart policy unchanged. Recovery must preserve elapsed budgets, protected state, and data-exposure history. |

## Other useful ideas and implementation references

Other repository areas provide ideas for later decisions. The table names them so readers can find the reviewed material. They remain references or optional later work, not additional v1 requirements or chosen dependencies.

| Area | Potential use and limitation |
| --- | --- |
| Failure-pattern mining | [Bug-history tooling][failure-patterns] can suggest edge cases from source changes and issue evidence. Treat suggestions as hypotheses and source text as untrusted data; verify relevance before adding checks. |
| Audit findings | [Structured findings][findings] and the [auditor role][auditor] distinguish missing guarantees, overfitting, measurement problems, and other reward hacks. Convert findings into executable setup checks or validated development additions under the confirmed policy; an agent's verdict alone cannot establish correctness. |
| Reusable knowledge | The [knowledge-base tools][kb] retain properties, tests, failures, designs, and provenance. Consider this after the basic workflow works; prevent cross-run leakage of held-out data and hand-written pair-specific optimizations. |
| Simpler search policies | [Top-k][topk], [best-of-N][best-of-n], and [beam search][beam] offer selection and diversity ideas if the direct loop has an observed limitation. Supporting multiple policies is not itself a milestone. |
| Reflection and diversity | [GEPA-native][gepa] uses evaluation feedback and combines candidates; [OpenEvolve-native][openevolve] maintains diverse candidates. Their ideas may be useful independently of adopting another framework. A better numeric score does not replace the required correctness and performance checks. |
| Evolving the search algorithm | [EvoX][evox] modifies search machinery itself. Defer it: executing generated search code expands the protection and validation problem around orchestration. |
| External backends | [External optimizer wrappers][external] illustrate backend boundaries. Their direct-model/cloud dependencies and lifecycle assumptions still need evaluation; they are not initial Codex backends. |
| History and recovery | [Search checkpoints][search-checkpoints] and the [monitor implementation][monitor] suggest lineage, progress reporting, and recovery records. Keep authoritative evidence outside agent-writable state. A dashboard is optional. |
| Benchmark acquisition | The [benchmark resolver][benchmark-base] separates acquisition and configuration. This is useful for provenance, but does not generate representative application replay automatically. |
| Real trace examples | The [single-machine key-value-store example][kv] illustrates trace preparation and reference checks. The [router example][router] illustrates dataset identities, splits, and environment/workload records. Its cost/quality simulation objective is not application CPU timing, and source-visible splits do not prove held-out protection. |
| Small workflow fixtures | The [cache tutorial][tutorial] can inform a small integration fixture. Its synthetic inputs and cache objective cannot demonstrate our real-world speedup requirements. |
| Formal checking | The [proved distributed store][proved] illustrates proof artifacts and validation. Formal proof remains future scope; a proof applies to its specified model and assumptions. |
| Broader benchmark coverage | [ADRS, algorithmic, GPU, prompt, and other benchmarks][benchmarks] provide examples of evaluation boundaries and reporting. GPU benchmarks and the [inference-engine example][inference] are outside our CPU-only first version. No example automatically qualifies as one of our two application–library pairs. |
| Integration-test design | [Contract replay tests][contract-tests], [checkpoint tests][checkpoint-tests], and [seeded-search tests][seeded-tests] provide useful validation patterns. Adapt tests for our externally observable contracts; seeded selection alone does not make model-driven execution deterministic. |

Before copying code or adding a dependency, record its revision, modifications, and required attribution. The reviewed repository has an [Apache-2.0 license][license], but record terms for dependencies and datasets actually used too. Weigh maintenance/dependency cost against implementing a small understood idea ourselves. Phase 2 copied an unmodified subset of helpers only into the external reproduction experiment, with license, revision, and hashes; that is not adoption into the generator.

## Evidence and limits of this assessment

Source review covered the main Optimize/Synthesize workflows, search code, evaluators, adapters, artifact tools, examples, benchmark families, and validation infrastructure. It was not a line-by-line review of every file. The following isolated checks ran in temporary fixtures:

| Check | Observed result | What it does not establish |
| --- | --- | --- |
| Generated-test validator | A discriminating toy test returned acceptance; one passing both original and mutant returned rejection; a test failing the original returned inability to validate. | Coverage of a real application or automatic production-quality test generation. |
| Audit freshness | An audit covered unchanged inputs; changing implementation bytes or a workload record invalidated coverage. | Protection from unauthorized access or forged authoritative records. |
| Codex role adapter | It generated nine parseable TOML role files whose instructions matched the shared descriptions. | A successful live Codex invocation, compatibility with the installed CLI, or our desired role count. |
| Framework edit hook | Its decision function blocked a framework-targeting edit payload from an external working directory and allowed a shell-tool payload. | A demonstrated shell write or an operating-system isolation test; no such write was attempted. |
| Custom LLM client hook | An isolated stub probe used the custom client instead of constructing the default API client. | End-to-end Codex integration or support for our candidate lifecycle. |
| Container result parsing | An isolated parser probe retained a positive score from an error-status result. | An executed container exploit or evidence that every upstream caller accepts that result. |

We did not run the full upstream suite, evolutionary searches, examples, performance experiments, or live agent workflows. No result here establishes that AdaEvolve improves our search or that an upstream benchmark meets our targets. Those claims require the planned comparison and our own formal demonstrations.

[upstream]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/README.md
[spec-builder]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/agents/1-specification/spec-builder.md
[spec-tools]: https://github.com/skydiscover-ai/skydiscover/tree/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/spec
[roles]: https://github.com/skydiscover-ai/skydiscover/tree/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/agents
[validate-test]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/scripts/validate_test.py
[suite]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/scripts/suite.py
[checkpoint]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/spec/checkpoint.py
[run]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/spec/run.py
[adapters]: https://github.com/skydiscover-ai/skydiscover/tree/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/adapters
[codex-adapter]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/adapters/codex/agents.py
[llm-pool]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/llm/llm_pool.py
[context]: https://github.com/skydiscover-ai/skydiscover/tree/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/context_builder
[search]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/README.md
[adaevolve]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/adaevolve/README.md
[host-evaluator]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/evaluation/evaluator.py
[container-evaluator]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/evaluation/container_evaluator.py
[harbor-evaluator]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/evaluation/harbor_evaluator.py
[metrics]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/utils/metrics.py
[runner]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/runner.py
[edit-guard]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/hooks/framework_edit_guard.py
[decisions]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/spec/decisions.py
[unattended]: https://github.com/skydiscover-ai/skydiscover/tree/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/scripts/unattended
[failure-patterns]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/spec/failure_patterns.py
[findings]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/spec/findings.py
[auditor]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/agents/2-synthesis-loop/auditor.md
[kb]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/workflow/scripts/kb/README.md
[topk]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/topk/README.md
[best-of-n]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/best_of_n/README.md
[beam]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/beam_search/README.md
[gepa]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/gepa_native/controller.py
[openevolve]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/openevolve_native/README.md
[evox]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/evox/controller.py
[external]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/extras/external/README.md
[search-checkpoints]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/search/utils/checkpoint_manager.py
[monitor]: https://github.com/skydiscover-ai/skydiscover/tree/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/extras/monitor
[benchmark-base]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/optimize/benchmarks/base.py
[kv]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/examples/single-machine-kvstore/README.md
[router]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/examples/llm-router/README.md
[tutorial]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/examples/tutorial/README.md
[proved]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/examples/proved-dist-kvstore/README.md
[benchmarks]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/benchmarks/README.md
[inference]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/skydiscover/synthesize/examples/inference-engine/README.md
[contract-tests]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/tests/spec/test_contract_replay.py
[checkpoint-tests]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/tests/spec/test_checkpoint.py
[seeded-tests]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/tests/search/test_seeded_reproducibility.py
[license]: https://github.com/skydiscover-ai/skydiscover/blob/0d932b690670a7e544388ad362e9876c8bd256a0/LICENSE
[jit-paper]: https://arxiv.org/html/2605.24096v1
