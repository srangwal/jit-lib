# Choosing the first application–library pairs

Baseline research recorded: 2026-09-20. Workload-source decision confirmed: 2026-09-21.

**Historical Python assessment, superseded as the active direction on 2026-09-23.** The user directed us to find application/library candidates in another language to avoid or substantially reduce the protected-test complications. The recommendations and measurements below describe the earlier investigation. Preserve them as evidence; do not treat these pairs as the current implementation target or assume they established isolation feasibility.

Just-in-Time Library will specialize an external library for the way a particular application uses it. Before building that system, we need two plausible demonstrations: applications with real inputs, meaningful library costs, and reproducible correctness checks. This document explains our recommendations and the experiments supporting them.

Here, **qualification** means establishing that a pair is suitable for further work. A **baseline** is the unchanged application and original library. A **corpus** is a collection of actual input files. A **replay** runs a recorded job on those inputs again. None of the timings below measure a specialized library; no specialization has been written. The detailed rules come from the [scope](scope.md), and the work belongs to Phase 1 of the [execution plan](execution-plan.md).

## Earlier recommendation

Each eventual demonstration must establish at least 1.5× speedup for library work and 1.2× for the complete application. For each metric, the lower endpoint of a two-sided 95% confidence interval must meet the target, so a noisy favorable average alone is insufficient. The measurements below assess opportunity; they do not test those targets yet.

The baseline evidence supports proceeding with these two pairs for execution and protection research:

1. **yamllint 1.38.0 → PyYAML 6.0.3**, using real infrastructure configuration files. This is the stronger first integration candidate: the dependency supplies much of the measured runtime, and the application already has a substantial test suite.
2. **MkDocs 1.6.1 → Python-Markdown 3.10.3**, using complete builds of real documentation projects. This provides a different application, library, and workload. It has a plausible but tighter performance margin because themes, extensions, highlighting, and search indexing also cost time.

We installed the applications and libraries from separate checkouts outside this repository, fixing each to an exact revision. We ran original tests, complete jobs on real inputs, profiles of dependency cost, and reproduction in fresh environments. The original implementations remained unchanged. These results justify investigation; they do not establish that either pair will meet the required speedups.

The two workloads are easy to distinguish. yamllint reads Kubespray's YAML files and reports lint findings. MkDocs reads HTTPX or Django REST framework documentation and builds a site. The YAML/Markdown files are the **input data**; `.yamllint` and `mkdocs.yml` control processing. The user accepted complete real project jobs as sufficient workload evidence for v1. Exact final-evaluation membership and measurement rules still need agreement and audit.

The external [experiment README](/private/tmp/jit-lib-qualification.UoOrTd/experiment/README.md) contains the exact installation, test, replay, profile, and reproduction commands. It uses ordinary Git/Python/uv tooling and has no dependency on this project, an agent, or SkyDiscover. Raw evidence is under `/private/tmp/jit-lib-qualification.UoOrTd/experiment/`, with a [portable evidence archive](/private/tmp/jit-lib-qualification-2026-09-20-evidence.tar.gz). This is temporary research storage; preserve the archive before deleting temporary files.

## Pinned sources and actual adoption

| Role | Upstream revision | Evidence |
| --- | --- | --- |
| Application 1 | yamllint `v1.38.0`, `cba56bcde1fdd01c1deb3f945e69764c291a6530` | [Application source](https://github.com/adrienverge/yamllint/tree/cba56bcde1fdd01c1deb3f945e69764c291a6530) |
| Library 1 | PyYAML `6.0.3`, `49790e73684bebad1df05ef8d828fa12f685bffb` | [Library source](https://github.com/yaml/pyyaml/tree/49790e73684bebad1df05ef8d828fa12f685bffb) |
| Application 2 | MkDocs `1.6.1`, `bb7e8b62185b11d9f59bb7f50b13c15134f62f8a` | [Application source](https://github.com/mkdocs/mkdocs/tree/bb7e8b62185b11d9f59bb7f50b13c15134f62f8a) |
| Library 2 | Python-Markdown `3.10.3`, `bb50627dc07fde6ee5ed7478464062c537ebad2c` | [Library source](https://github.com/Python-Markdown/markdown/tree/bb50627dc07fde6ee5ed7478464062c537ebad2c) |
| YAML development inputs | Kubespray `ce6f5fe886a5e10d000db57e639412c8b654445b` | [Its yamllint integration](https://github.com/kubernetes-sigs/kubespray/blob/ce6f5fe886a5e10d000db57e639412c8b654445b/.pre-commit-config.yaml) and [lint configuration](https://github.com/kubernetes-sigs/kubespray/blob/ce6f5fe886a5e10d000db57e639412c8b654445b/.yamllint) |
| Markdown development inputs | HTTPX `b5addb64f0161ff6bfe94c124ef76f6a1fba5254` | [Actual build script](https://github.com/encode/httpx/blob/b5addb64f0161ff6bfe94c124ef76f6a1fba5254/scripts/build), [MkDocs configuration](https://github.com/encode/httpx/blob/b5addb64f0161ff6bfe94c124ef76f6a1fba5254/mkdocs.yml), and [dependency pins](https://github.com/encode/httpx/blob/b5addb64f0161ff6bfe94c124ef76f6a1fba5254/requirements.txt) |
| Markdown development inputs | Django REST framework `b92edf53e21b2de16af5d13529591f1c0d415f93` | [MkDocs configuration](https://github.com/encode/django-rest-framework/blob/b92edf53e21b2de16af5d13529591f1c0d415f93/mkdocs.yml), [dependency pins](https://github.com/encode/django-rest-framework/blob/b92edf53e21b2de16af5d13529591f1c0d415f93/pyproject.toml), and [documentation workflow](https://github.com/encode/django-rest-framework/blob/b92edf53e21b2de16af5d13529591f1c0d415f93/.github/workflows/mkdocs-deploy.yml) |

The linked project configurations establish independent use of these applications. They provide complete real jobs and substantial tests, rather than an input invented around an easy function. For the second pair, **MkDocs is the application**; HTTPX and DRF supply documentation inputs. This is not a benchmark of HTTP serving, API requests, or DRF request processing. No deployment commands were executed.

The source checkouts retain their upstream licenses. No implementation was copied into the generator repository. The external `provenance/*-files.json` records identify tracked source and input files by hashes, including licenses and configurations. These records let a reader check exactly which material produced the evidence.

## Executed baseline evidence

Machine: Apple M4 Pro, 14 cores, 48 GiB RAM, macOS 26.6.2 arm64; CPython 3.12.13; uv 0.11.23. All runs used the local CPU. Packages were built/installed from the selected source checkouts into separate environments. Other dependencies are recorded in `experiment/requirements/`.

### Repository tests

| Suite | Recorded result | Coverage limits |
| --- | --- | --- |
| yamllint | 430 tests, successful, no skips | One Python/platform configuration exercised |
| PyYAML | 1,283 passed | Optional LibYAML extension absent; two upstream warnings recorded |
| MkDocs, in each documentation workload environment | 724 tests, successful, 4 skips | Three Windows-only tests and optional lunr.py coverage skipped |
| Python-Markdown, upstream Pygments test configuration | 1,088 tests, successful, 12 skips | Eight upstream exclusions and four upstream-known syntax limitations |
| MkDocs integration suite | Both built-in themes and four test projects built successfully | Uses a separate environment with upstream documentation dependency pins and the selected app/library versions |

A collected-test count includes tests the runner subsequently skips. The successful unittest totals above therefore include the stated skips; they do not mean every collected test body ran. No assertions, tests, or skip rules were changed. The earlier Markdown run in the HTTPX dependency environment had 110 skips; the upstream Pygments 2.7.1 test configuration was then installed separately to exercise that coverage. Both records remain in the evidence directory. This did not replace Pygments in the application workloads.

PyYAML can include an optional C extension; this installation did not. In the inspected yamllint source, the parsing path explicitly chooses Python's `BaseLoader`, while configuration uses `safe_load`. Thus this qualification did not manufacture a slower parsing baseline by disabling a C loader that yamllint had selected. Formal setup still needs to record this choice and the coverage missing without the extension.

Installed Python sources were compared against the pinned checkouts: 32 yamllint files, 17 PyYAML files, 35 MkDocs files per checked environment, and 33 Markdown files per checked environment, with zero mismatches. All tracked source checkouts remained clean. The loaded versions/paths are recorded in `provenance/repositories-and-environment.json`.

### Real-input replay and elapsed time

| Workload | Complete application job | Input count / bytes | Five-run minimum / median / maximum |
| --- | --- | --- | --- |
| Kubespray | `python -m yamllint --strict .` from the corpus root | 575 selected YAML files / 1,058,381 bytes | 1.1956 / **1.2029** / 1.2373 seconds |
| HTTPX documentation | `python -m mkdocs build --site-dir EXTERNAL_OUTPUT` | 23 Markdown documents / 129,901 bytes, plus project configuration/assets | 0.4949 / **0.5400** / 0.5677 seconds |
| DRF documentation | Same complete MkDocs build, using DRF's configuration and environment | 69 Markdown documents / 984,669 bytes, plus project configuration/assets | 1.0245 / **1.0285** / 1.7106 seconds |

Every replay exited with code zero. Kubespray produced no lint diagnostics. The documentation builds produced recorded diagnostics, including link warnings; successful completion does not mean warning-free inputs. The project's own configurations, extensions, themes, and assets were used unchanged. Kubespray's checked-in hook pins yamllint 1.37.1; the qualification uses 1.38.0 on all files selected by the configuration. This is a real-input corpus replay, not an exact reconstruction of observed pre-commit invocation frequency.

Each timing covers a complete process from launch to exit, so startup and output generation count. The recording script sets `PYTHONHASHSEED=0`, `SOURCE_DATE_EPOCH=1704067200`, and `TZ=UTC`. We recorded five fresh processes in sequence. We did not flush filesystem caches or discard a first “warm-up” run. The slower first DRF build stays in the record. These five-run summaries show original execution cost only; they are neither speedup estimates nor confidence intervals.

The first timing script repeatedly polled to enforce a subprocess timeout. That polling could add tens of milliseconds, material for these short jobs. The corrected script waits for completion while a separate watchdog enforces the timeout. The table uses `yamllint-kubespray-baseline-v2`, `mkdocs-httpx-baseline-v2`, and `mkdocs-drf-baseline`. Superseded observations and the original recorder are preserved rather than silently discarded.

The README reproduction workflow creates fresh `repro-*` environments, reruns the listed suites and five jobs for each corpus, and compares generated sites with the earlier outputs. Its records remain under `results/repro-*` and `reproduction/`, alongside the original observations. This shows that someone can repeat the baseline research without the generator. It does not demonstrate automatic experiment construction or successful candidate evaluation.

The 259 DRF output files matched byte-for-byte. The 83-file HTTPX site initially failed exact comparison on one API page. Its generated signatures contain 60 references to a `UseClientDefault` object's memory address, which varies by process. [HTTPX's sentinel definition](https://github.com/encode/httpx/blob/b5addb64f0161ff6bfe94c124ef76f6a1fba5254/httpx/_client.py#L94) explains the object involved.

We added a narrowly defined comparison rule: only that address may vary; its occurrence count and references to the same singleton must remain consistent. All other bytes and the set of output files must match. The comparison passed and rejected four deliberate faults: a changed default, changed text, inconsistent object identity, and unrelated extra hexadecimal text. We kept the strict failure and raw outputs. Tests/replays had run in fresh environments; we reran the comparison step with this baseline-derived rule. A formal evaluator audit must still approve it before optimization.

The combined documented workflow was subsequently executed successfully under `independent-reproduction`, using those pinned environments with new output directories. All tests and 15 complete replay jobs finished successfully, and the final output comparison passed. Both reproduction attempts are retained.

### Dependency contribution and opportunity

Profiling asks where time goes. It differs from ordinary elapsed-time measurement because the added instrumentation can change cost. These profiles wrap the application's outer calls into the library and include the work nested under those calls. Nested calls are not counted a second time:


| Workload | Library API time / profiled module time | Observed API share |
| --- | --- | --- |
| yamllint / Kubespray | 0.8261 / 1.3074 seconds | **63.2%** |
| MkDocs / HTTPX | 0.2004 / 0.4425 seconds | **45.3%** |
| MkDocs / DRF | 0.5396 / 0.9674 seconds | **55.8%** |

The percentages are exploratory. The wrappers add cost, library imports occurred before the profiled application-module interval, and Markdown calls include third-party extensions and highlighting. Do not interpret 63.2% as a precise fraction of uninstrumented CLI time.

For formal measurement, **logical library work** means the operations the application needs, regardless of which helper, module, thread, or process performs them after specialization. Include initialization and work called indirectly. Otherwise a candidate could appear faster simply by moving code outside the functions we currently time. These profiles do not yet provide that measurement method.

The inspected yamllint source performs syntax parsing with `yaml.parse(..., Loader=yaml.BaseLoader)` and obtains another token stream for lint rules. The profile records 575 explicit loader initializations for token-based linting, 50,427 parse-iterator advances, and substantial scanner work. A separate cProfile run attributes about 60.3% of instrumented exclusive time to Python files in the `yaml` package. Exclusive time counts time in those functions themselves, rather than time spent in called functions. This supports investigating scanner/parser overhead under the application's actual interfaces; it does not justify dropping valid YAML features or skipping syntax checks. [Syntax path](https://github.com/adrienverge/yamllint/blob/cba56bcde1fdd01c1deb3f945e69764c291a6530/yamllint/linter.py#L176), [token path](https://github.com/adrienverge/yamllint/blob/cba56bcde1fdd01c1deb3f945e69764c291a6530/yamllint/parser.py#L123).

For MkDocs, each page constructs a Markdown renderer, registers MkDocs processors, converts its document, and consumes generated content and table-of-contents state. The DRF profile records 69 conversions; Markdown's inline tree processing and block parser are substantial call paths. However, highlighting alone costs about 0.333 seconds within 1.246 seconds of cProfile conversion time. Markdown-package exclusive time is about 21.7% of the full DRF profile and 10.9% of the HTTPX profile; those exclusive figures omit native/stdlib helpers. The search must discover an application-specific opportunity while preserving processor registries, extension order, callbacks, and outputs. The profile does not establish which optimization will work. [MkDocs rendering path](https://github.com/mkdocs/mkdocs/blob/bb7e8b62185b11d9f59bb7f50b13c15134f62f8a/mkdocs/structure/pages.py#L263).

A useful estimate follows Amdahl's law: speeding up only one part of a job leaves the remaining cost unchanged. If the measured fractions were the true elapsed-time fractions, making all measured library work 1.5× faster would give about 1.27× application speedup for Kubespray, 1.18× for HTTPX, and 1.23× for DRF.

These are **hypothetical calculations, not predictions**. Startup, instrumentation, extension costs, and workload membership affect the result. MkDocs has less margin: a 1.5× library gain alone might not meet the application target for the eventual mixture. Each pair must independently meet both targets using the required confidence bounds.

## Correctness work required before optimization

Existing tests establish a starting point. The generated evaluator must also compare complete original-versus-specialized behavior and check supported cases absent from the performance corpus. Setup must generate and audit these comparisons without narrowing the application contract:

| Pair | Original-behavior comparisons | Additional coverage needed |
| --- | --- | --- |
| yamllint / PyYAML | Exact lint findings, rule identifiers, line/column locations, output formats, exit codes, configuration handling, file selection, and stdin behavior | Malformed YAML; Unicode and encoding errors; empty/multiple documents; anchors/aliases/tags; nested collections; configuration errors; ignored files; all supported rules/options; files with expected findings |
| MkDocs / Markdown | Full output file membership and contents, HTML, links/anchors, navigation, TOC, search index, copied assets, diagnostics, exit codes, and relevant filesystem effects | Empty/malformed Markdown; raw HTML and escaping; nested syntax; Unicode; supported extensions and third-party callbacks; renderer state/reset; conflicting processor priorities; invalid configuration; error propagation; supported build/serve behavior beyond measured builds |

Before search, record and fix which tests must run, their expected collection counts, and existing skips. New skips, missing outputs, shortened processing, or weaker assertions cannot become successful candidates. Pin comparison rules before search. Baseline-against-baseline evidence may justify narrowly specified normalization, such as the observed HTTPX sentinel addresses; it does not justify ignoring other HTML differences or all diagnostics.

The evaluator audit must demonstrate rejection of deliberate faults. This baseline research does not show that candidate code cannot interfere with a future checker. Exit code zero also does not prove all work happened. Protected code must own verdicts and timings, verify all required inputs/outputs, and identify the exact candidate that ran.

## Workload population and unexposed input sources

The user confirmed on 2026-09-21 that complete real project jobs qualify as real-world workloads for v1 without recorded CI or production executions. The Kubespray YAML files are yamllint's input data; the complete configured lint job and the HTTPX/DRF documentation builds meet this workload-source criterion. Final workload membership, weights, held-out qualification, and evaluation rules still need to be resolved before optimization.

The represented workload is complete, configured jobs on selected infrastructure repositories and open-source documentation projects. It does not represent measured worldwide usage frequency. Treat a repository job as the unit of work: 575 YAML files are not 575 observed user sessions.

**Development data** is material the optimizer or its research context has already inspected or used. **Held-out data** is reserved for evaluation after candidate selection. Every downloaded/replayed corpus and repository test/integration fixture here is development material. The completed builds cannot later become “untouched” held-out evidence.

The following projects are possible held-out reserves, not finalized test workloads. Research checked their configuration and Git tree metadata, such as paths, sizes, and content identities. It did not download or replay their workload contents. The metadata inventory was complete, and comparing Git blob identities found no exact YAML/Markdown file matches against the corresponding development corpora. This does not rule out similar or related content.

| Potential reserve | Pinned revision | Metadata inventory, before actual workload selection |
| --- | --- | --- |
| [AWX](https://github.com/ansible/awx/tree/bbda905e0069dde6abe625e005dd79a058a76fdb) for yamllint | `bbda905e0069dde6abe625e005dd79a058a76fdb` | 162 YAML files, 409,397 bytes; its lint configuration excludes some paths |
| [HTTPCore docs](https://github.com/encode/httpcore/tree/10a658221deb38a4c5b16db55ab554b0bf731707) for MkDocs | `10a658221deb38a4c5b16db55ab554b0bf731707` | 13 Markdown files, 56,857 bytes |
| [Databases docs](https://github.com/encode/databases/tree/ae3fb16f40201d9ed0ed31bea31a289127169568) for MkDocs | `ae3fb16f40201d9ed0ed31bea31a289127169568` | 5 Markdown files, 19,874 bytes |
| [pipx 1.7.1 docs](https://github.com/pypa/pipx/tree/4462299fa391b7349074facc39c73767853c9d02) for MkDocs | `4462299fa391b7349074facc39c73767853c9d02` | 10 Markdown files, 102,075 bytes, excluding additional generated/copied documentation |
| [SQLModel 0.0.24 docs](https://github.com/fastapi/sqlmodel/tree/de78b8c7bc26038f9f047cc66dd3a49c65864df0) for MkDocs | `de78b8c7bc26038f9f047cc66dd3a49c65864df0` | 64 Markdown files, 517,342 bytes, plus included examples/configuration/assets |

These inventories show additional material exists. Protected setup must still check compatible dependencies, offline builds, generated inputs, exact job membership, and similar/related content before accepting a final split. The smaller sites and different extension mixes may have less performance opportunity than DRF. Do not drop a valid workload after seeing an unfavorable candidate result. If a reserve fails setup requirements, record why and resolve the source choice before search.

pipx and SQLModel use named published releases with existing MkDocs configurations; these are historical documentation inputs, not claims about their current documentation stacks. SQLModel's social-card/assets and inherited configuration need an explicit offline acquisition/build check. Current SQLModel configuration includes Zensical-specific extensions, and current pipx lacks the same root MkDocs configuration; those current trees were not selected. Ansible Lint was also considered, but its YAML-rule documentation had already been inspected during adoption research, so it is treated as exposed under the proposed whole-project separation. Metadata for these non-selected sources remains recorded with their status.

The proposed split keeps whole projects together and audits duplicates/related content across them. Pages from an already profiled site cannot be called unexposed merely because they were assigned to another folder. Since reserves are public, the optimizer must also be prevented from fetching alternate copies. Restricting only a local directory is insufficient.

## Proposed measurement choices for the formal protocol

The table below proposes an evaluation protocol for Phase 3. It is **not an approved default or an implemented formal procedure**. Resolve and audit membership, numerical settings, and acceptance effects before search.

A paired block measures both original and candidate jobs under comparable conditions. Aggregation combines the fixed job mixture. A bootstrap interval estimates measurement uncertainty by resampling whole paired blocks; it does not establish whether the projects represent all users. A ranking rule selects among development candidates but cannot waive final correctness or performance requirements.

| Choice | Proposal and reason |
| --- | --- |
| Development membership | Keep the complete Kubespray lint job and both complete documentation builds above, including their configurations, outputs, and diagnostics. Record any later additions as development exposure. |
| Final membership | Qualify the separate reserve projects above in protected setup; freeze exact revision, complete job membership, configuration, hashes, and related-input grouping. The metadata counts are not a substitute for this manifest. |
| Workload weights | One complete job per selected project per measurement block, with equal job counts. Aggregate baseline elapsed time divided by aggregate candidate elapsed time for that fixed mixture. This is a declared experimental mixture, not inferred production frequency. Report each project's result separately. |
| Application boundary | A fresh CLI process through completion of all required outputs/effects. Include startup, library import, parsing/rendering, output generation, and cleanup performed by the application. Keep the application's options and call sites unchanged. |
| Library boundary | All required dependency work for the same logical operations, including initialization and helpers/callbacks invoked indirectly. During design, find a low-overhead method that still counts this work if the candidate reorganizes its code; the exploratory wrappers do not yet establish it. |
| Initial state | Fresh process per job with equivalent installed environments and declared filesystem/cache state. Two baseline and two candidate warm-up jobs per project before measured blocks; retain their records. This measures repeated local jobs with warm filesystem state, not cold-machine performance. Candidate-specific cache preparation/reuse must be accounted for and justified. |
| Repetition and ordering | Propose 30 paired final blocks; balance baseline-first/candidate-first order 15/15 using a permutation frozen before search. Keep the project order within each block fixed or predeclared. Preserve all measurements; do not extend sampling until a threshold passes. Validate this sample count and timing resolution with baseline-only checks before freeze. |
| Uncertainty | Propose a paired block bootstrap with 10,000 resamples and a frozen seed; report the 2.5th and 97.5th percentiles for each aggregate speedup. Resample whole paired blocks, preserving the project mixture. This addresses measurement variation for the declared corpus, not population-wide representativeness. Audit dependence/drift and the method before use. |
| Development selection | Propose ranking completed, correctness-passing candidates by the smaller of `library lower bound / 1.5` and `application lower bound / 1.2`; break ties by application lower bound, then stable candidate identity. Define the development measurement count before search. No scalar rank can override final correctness or either target. |
| Memory and regressions | Measure peak process-tree memory and per-project elapsed time. How these affect acceptance is still a design decision; no numerical limits are silently introduced here. |
| Stage limits | Set setup/search/final limits after the backend/isolation checks establish agent and protected-evaluation costs. The measured test/replay costs here inform those choices but do not determine an agent search budget. |

For each pair, the lower endpoint of each two-sided 95% confidence interval must meet **1.5× library and 1.2× complete application** speedup. An inconclusive or failed final run ends under the existing scope policy. Reusing revealed final results to tune the same candidate/run is prohibited.

## Alternatives considered

| Pair | Assessment and reason not to recommend it now |
| --- | --- |
| Sphinx / Docutils | Source-level alternative. More documentation build/extension setup to establish a controlled workload. No executable dependency-contribution result was obtained, so it is not qualified. |
| Flake8 / pycodestyle | Source-level alternative. Runtime is shared with tokenization, PyFlakes, and other checks; an executable profile would be needed to justify its margin. No performance rejection is claimed. |
| csvkit / agate | Pinned sources were downloaded as a backup (`csvkit` 2.2.0, `agate` 1.14.2). No real-data replay or test qualification was completed. It remains a research option if either recommendation later fails feasibility. |

We have not measured these alternatives and rejected them for insufficient speed. The recommended pairs already have executable baseline evidence, so we can investigate their execution/protection feasibility before expanding backup research.

## Phase boundary

These pairs are recommended for feasibility and design work. No formal demonstration, automatically generated experiment, achieved gain, protected final-data split, or complete evaluator isolation follows from the baseline results.

Phase 2 has since exercised Codex and small protection experiments, as recorded in the [feasibility report](execution-feasibility.md). Full faithful protection of repository tests remains unresolved. Resolve that boundary, then complete the future `docs/design.md` and audited protocols before dependent generator implementation or optimization.
