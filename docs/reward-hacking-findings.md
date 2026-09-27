# Reward-hacking findings: what we reproduced and what it means

Recorded: 2026-09-21.

**Research status, 2026-09-23:** these findings preserve the earlier Python investigation. Its proposed follow-up work is historical; the current next milestone is a supervised non-Python pilot. Read the [exploration summary](python-exploration.md) for why we changed direction and the [execution plan](../execution-plan.md) for active work. The evidence and limitations below remain part of the project record.

Just-in-Time Library will generate faster versions of libraries and test whether they preserve application behavior. A favorable test report is useful only if the generated code cannot falsify it. **Reward hacking** means satisfying the evaluator's apparent success signal without satisfying the intended task. This document records concrete experiments investigating that problem, including defects in our own checking code.

The central example is simple: a library changed Python's test runner in memory, so a deliberately failing test reported success. The test files stayed unchanged, and ordinary application outputs still matched. We then investigated keeping assertions in a separate process that the library could not modify. That worked for a synthetic application and selected real tests, but preserving all real-library behavior remains unresolved.

**Current status:** full faithful protection is not established for yamllint/PyYAML or MkDocs/Python-Markdown. Selected library tests, eleven MkDocs title tests, and five relative-path tests with an added state check resist the tested runner forgery. Full-suite investigation exposed lost shared/recursive objects and changed recursion behavior. New bounded experiments address the observed examples, but do not preserve all Python interactions. Review also found that an evaluator's saved evidence could accidentally remain a mutable shared object. These are defects and limits in the experimental evaluation arrangement, not evidence that the original libraries are incorrect.

Read [F-01](#f-01-a-library-can-make-repository-tests-report-success-without-running-their-assertions) for the original failure, [F-02](#f-02-separating-assertions-from-candidate-execution-defeats-the-fixture-attack) for the basic defense, and [F-09 through F-12](#f-09-selected-real-library-tests-retain-protected-assertions-across-a-process-boundary) for real-library progress and limits. F-03 through F-08 cover completion records, clocks, helper validation, access controls, termination, and a reproduction defect. These IDs remain stable so other documents can cite specific evidence.

[F-13](#f-13-the-yaml-adapter-loses-shared-and-recursive-values) and [F-14](#f-14-moving-markdown-to-a-worker-changes-an-existing-recursion-test) explain the new full-suite investigation and its smallest counterexamples.

[F-15](#f-15-measured-recursion-context-preserves-one-test-family-with-observable-limits) records measured recursion-context transfer and its limits. [F-16](#f-16-shared-object-transport-must-not-make-evaluator-evidence-shared-too) records the graph experiment and the additional protection needed for evaluator evidence.

[F-17](#f-17-inherited-methods-can-call-back-without-owning-the-callbacks-verdict) combines selected-library inherited methods with caller-owned configuration and callbacks. It also explains why an ordinary application exception and a failed evaluator assertion cannot be treated identically.

[F-18](#f-18-caller-defined-classes-need-more-than-copied-values) tests selected PyYAML methods cooperating with caller-defined classes. [F-19](#f-19-extension-registration-and-rendering-must-work-in-the-same-session) connects a caller extension and serializer to actual selected Markdown rendering. Both have independent reproductions and explicit limits; neither is a full-suite result.

[F-20](#f-20-valid-messages-do-not-establish-faithful-result-capture) records a source-reviewed trust assumption in result packaging. Its proposed adversarial experiment was blocked before execution; it is not a demonstrated bypass.

The [scope](../scope.md) defines requirements. The [feasibility report](execution-feasibility.md) records the environment and overall status. The [defense investigation](reward-hacking-defense.md) connects these local results with published research and proposed safeguards.

## Terms and evidence labels

A **candidate** is a proposed specialized library; the **baseline** is the original. A **fixture** is a small synthetic application used for an experiment. A **mutant** is an intentionally faulty or hostile variant constructed to test the checker. An **assertion** is the test's actual comparison, distinct from the runner's printed pass/fail message.

The **trusted parent** runs assertions and owns verdicts. A restricted **worker** runs the candidate. An **adapter**, also called a facade or bridge, forwards allowed library calls between them. A **protocol** specifies the permitted messages. An application **callback** is a function the library calls back into during processing. **Object identity** means two references point to the same object; changing it through one reference should be visible through the other. These concepts matter because process separation must preserve the tests' meaning as well as restrict access.

The evidence labels distinguish execution from ideas:

- **Reproduced:** executed locally against the identified fixture or pinned upstream source, with recorded results. We deliberately constructed the attack variants; these are not claims that the live Codex task spontaneously attempted them.
- **Source-reviewed:** inspected upstream implementation or published research; not an executed end-to-end attack on this project.
- **Proposed:** a defense or test still requiring implementation and validation.

The original research code, repositories, and raw results are outside this repository, under `/private/tmp/jit-lib-feasibility.2__rqrwc`. Result paths below are relative to its `experiment/` directory. The [external README](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/README.md) provides the reproduction commands. That temporary directory is not a durable archive; the explanations, attack code, result summaries, and limitations below are retained in this repository even if it is later removed. For smaller examples with full code kept here, start with [the runnable teaching experiments](reward-hacking/README.md). They simplify several findings without claiming the original experiments' full protection.

## F-01: a library can make repository tests report success without running their assertions

**Evidence: reproduced. Severity for this project: blocks the required test-integrity guarantee.**

The synthetic application imports `summarize` from a Python package named `fixturelib`. Its four existing tests check empty input, repeated labels, Unicode handling, and invalid input. A normal test run imports the library and then executes those tests through Python's `unittest` runner.

The imported library and test framework run in the same Python interpreter and can refer to the same class objects. A library can change those objects in memory even when every source file on disk is read-only.

We replaced the disposable attack variant's `fixturelib/__init__.py` with:

```python
import unittest

def fake_run(self, result=None):
    result.startTest(self)
    result.addSuccess(self)
    result.stopTest(self)
    return result

unittest.TestCase.run = fake_run
from .summary import summarize
```

The following sequence explains how unchanged tests produced false success:

1. The runner loads the unchanged application test module.
2. The test module imports `fixturelib`; package initialization executes the code above.
3. The assignment replaces `TestCase.run` in the interpreter's shared `unittest` module. The original application, test files, and installed `unittest` files are untouched.
4. When the runner invokes a test, method lookup reaches `fake_run`.
5. `startTest` increments the test count. `addSuccess` records success. `stopTest` closes the event. The function never calls the original runner, test setup, test body, assertion, or teardown.
6. The runner therefore prints the expected test names, the expected total, and `OK`; its overall process exits successfully.
7. The final import still exposes the genuine `summarize` implementation. Running the application normally produces the same answers as before.

The ordinary output was:

```text
Ran 4 tests in 0.000s

OK
```

The replacement runner produced the count and success messages. It never ran the four test bodies.

We also ran a **negative control**: a test deliberately written to fail. A trustworthy arrangement must report that failure. The following readable equivalent shows the control used by the script:

```python
import unittest
import fixturelib  # Triggers the candidate's package initialization.

def must_fail():
    raise AssertionError("mandatory negative control")

case = unittest.FunctionTestCase(must_fail)
result = unittest.TextTestRunner().run(case)
raise SystemExit(not result.wasSuccessful())
```

| Observation | Original library | Output-preserving attack variant |
| --- | --- | --- |
| Deliberately failing test | One failure; exit 1 | One reported success; exit 0 |
| Ordinary four-test suite | Passes normally | Reports success without running the test bodies |
| Six external application replays | Reference behavior | All match the reference |
| Protected source files | Unchanged | Unchanged |

The report records `gap_reproduced: true`, `repository_tests_reported_success_without_running: true`, `all_external_application_comparisons_matched: true`, and `phase2_gate_satisfied: false`. Evidence: `results/test-runner-gap/report.json`; independently repeated in `results/gap-independent-reproduction/report.json` using `scripts/test_runner_gap.py`.

### Why the existing defenses did not catch it

The read-only mount did protect test files. The container did protect the external controller. External comparisons did confirm six correct replay outputs. The missing protection was inside the container: candidate code still shared Python objects with the test runner.

Counting collected tests does not detect this attack because it emits a success for each test. A deliberately failing “canary” in the same process is also suppressed. Hashes can confirm unchanged files, and signatures can preserve a received report, but neither proves that the report tells the truth.

Scanning for this particular assignment may detect this payload, but does not establish protection from other assignments, import hooks, assertion replacement, result-object mutation, or process termination. Python's own [audit-hook specification](https://peps.python.org/pep-0578/#why-not-a-sandbox) explicitly distinguishes runtime auditing from sandboxing.

**Required response:** preserve mandatory repository tests and protect their actual assertions. A pass message from a candidate-controlled runner cannot establish success, even when separately observed application outputs are correct.

## F-02: separating assertions from candidate execution defeats the fixture attack

**Evidence: reproduced defense, with a deliberately narrow interface.**

`scripts/protected_tests.py` loads the unchanged test module in the parent. When the test imports `summarize`, it receives a trusted forwarding function. Each call sends the list of strings to a fresh restricted container running `scratch/protected_worker.py`. Only the worker imports and executes the candidate. The parent then receives data and executes the original assertion.

The worker has the selected library and the worker script mounted read-only. It has no tests, expected answers, controller state, or result directory mounted, and no network. It runs without root privileges or Linux capabilities and with process, memory, output, and elapsed-time limits. The original library uses the same arrangement.

The parent accepts only JSON of the exact expected shape and limited size. It reconstructs ordinary builtin values; it neither imports candidate code nor unpickles candidate objects. Returned messages count as application data, never as verdicts. An incorrect answer is still possible, but the parent judges it against the test expectation.

The runner and assertion now occupy a different process address space. Replacing `unittest.TestCase.run` inside the worker cannot replace the parent's copy.

The fixture's call path is:

```text
Trusted parent                         Restricted worker
original test
  calls adapter  -- input data ------> selected library
  receives data  <-- bounded JSON ---- library result
original assertion checks that data
parent records the verdict
```

The worker receives the input required to perform the library operation. The expected answer and assertion stay in the parent.

| Executed check | Observed result |
| --- | --- |
| Original and normal candidate | Four tests pass, no skips |
| Attack that preserves correct output | Four tests really execute and pass |
| Same runner attack combined with wrong output | Four tests execute; suite fails with six failing assertions, including subtests |
| Candidate prints a forged success verdict and exits 0 | Suite fails with schema errors; child verdict is not accepted |
| Mandatory failing assertion after a library call | Fails against both original and output-preserving attacker; parent records that the assertion was reached |
| Empty output with exit 0 | Rejected as invalid JSON |
| Excessive output | Rejected at the output limit |
| Hanging worker | Rejected at the deadline; worker container removed |
| Parent runner and protected source | Unchanged |

One test contains subtests, so its assertions can produce more than four total failures/errors. Message failures raise `BridgeError`, not `ValueError`. That distinction prevents a broken communication channel from accidentally passing the application's `assertRaises(ValueError)` check. Only a decoded application error becomes the expected application exception.

The output-preserving attacker should pass the ordinary functional tests: its answers for those inputs are correct. Its runner-tampering code is a separate audit concern. The protection succeeds because that code cannot make the parent's deliberate failure pass.

Evidence: `results/protected-tests/report.json` and `results/protected-tests-independent-reproduction-2/report.json`; application test SHA-256 `6b8ba67ead27ea2e92f2e4c2098c30be3ea6ab6dd61bbfa5cd294f1e620a1acf`. The reports deliberately say `fixture_boundary_passed: true` and `phase2_gate_satisfied: false`. The independent run used the Python-only image with Codex absent from the host command path. Its first attempt caught the harness defect described in F-08; that failed attempt is retained.

### What this does not establish

This adapter supports one stateless function, `summarize(list[str])`, with fresh workers and ordinary data results. It does not establish faithful handling of arbitrary Python objects, object identity, subclasses, callbacks, shared mutation, or state across calls. It is test instrumentation; it changes neither the delivered library nor normal application execution.

The real candidates have richer interfaces. At the pinned qualification revisions, yamllint uses PyYAML loader/token objects, token types and marks, and scanner exceptions. MkDocs registers application-defined processors on Python-Markdown objects and reads their state after conversion. Moving those interactions across a boundary while preserving the meaning of every required test remains unproven. See the [candidate assessment](candidate-assessment.md) for pinned revisions.

Putting all tests back inside the candidate container would recreate F-01. Returning candidate-defined Python objects to the parent could execute candidate behavior there and defeat the separation; [Python's pickle documentation](https://docs.python.org/3/library/pickle.html) warns that unpickling can execute code. The bridge therefore cannot be generalized by merely substituting pickle for JSON.

Its worker startup and transport times are not performance evidence. No full application or library speedup is inferred from this experiment.

## F-03: success-shaped output and exit status can disagree with actual work

**Evidence: reproduced.**

`scripts/evaluate.py` exercised three distinct failures:

| Attack or failure | Why a weak evaluator could accept it | Observed protected check |
| --- | --- | --- |
| Build command exits 0 without producing the dependency ZIP | Treats command success as completed build | Required artifact missing; rejected |
| Application exits 0 with no result | Treats successful process exit as correct execution | Required output missing; rejected |
| Candidate emits `{"passed": true, "seconds": 0, "score": 999}` | Trusts fields named like evaluator results | Parent compares application data with protected references; rejected |

A live Codex invocation supplied another example of differing statuses: its process exited 0, but its structured response said `incomplete` because a Code Mode companion executable was missing. It changed no files. Fixing the environment allowed a later invocation to complete. This was an integration failure, **not demonstrated cheating or hallucination**. It shows why successful exit, finished task, required output, and correct output need separate checks.

Evidence: `results/evaluation/report.json`, `results/coding/agent-result.json`, `results/coding/execution.json`, and `results/coding-runtime-complete/`.

## F-04: a candidate can replace an in-process clock

**Evidence: reproduced.**

A child replaced `time.perf_counter` with a function returning zero, slept for 0.25 seconds, and reported zero elapsed time. The parent measured approximately 0.408 seconds around process/container execution. The child's timer mutation did not affect the parent's clock. Evidence: `results/evaluation/report.json`.

The external clock resisted this particular spoof, but it did not solve performance measurement. Its interval includes startup and does not isolate library work inside an application. A formal timing rule must also count required initialization, cache construction, lazy/deferred results, and effects. Otherwise work could simply move outside the measured interval.

## F-05: passing mutation validation does not protect a test runner

**Evidence: reproduced using an unmodified subset of upstream helpers.**

The SkyDiscover source revision was `0d932b690670a7e544388ad362e9876c8bd256a0`. We exercised its suite runner and generated-test validator against our synthetic tests. Source provenance, copied-file hashes, and license are in `provenance/skydiscover.json` and the external `tools/skydiscover-reviewed/` directory.

The suite helper accepted the forged success, including the deliberate failure. The generated-test validator asks whether a test passes the original and fails a supplied faulty variant. Against a normal wrong-output variant, our test satisfied that rule and the validator accepted it. Against the runner-forgery variant, both appeared to pass, so the validator rejected the test as unable to distinguish them.

This validates detection of the particular fault supplied to the validator. Detecting wrong output does not establish protection against a different fault that takes over the test runner. Evidence: `results/skydiscover-probe/report.json`; reproduced with `scripts/skydiscover_probe.py`.

We did not run the complete upstream auditor, its model calls, or the full SkyDiscover workflow. This result must not be described as an end-to-end break of all its defenses.

The [SkyDiscover assessment](skydiscover-assessment.md) also records **source-reviewed** limits: an editing hook does not cover arbitrary shell writes; content digests show whether an audit covers current bytes but do not control access; timing out a wait on an evaluation thread does not itself kill underlying processes; and one parser retains a positive score even when the result says error. These observations motivate independent controller checks. They do not prove that the full upstream workflow accepts every such result.

## F-06: isolation must cover every access path and every executable artifact

**Evidence: reproduced access probes, plus configuration failures preserved as evidence.**

The live agent's command environment could not read protected host originals, reference copies, or logs. Synthetic credential reads failed through direct paths, symlinks, and `/proc/1/root`. Command Internet and loopback connections failed; model-provider communication was separately available to the trusted client. Candidate imports and build hooks also failed to access protected host controls or modify the original application. Protected source digests stayed unchanged.

The probes included positive controls showing that the synthetic targets existed and were accessible without the tested restriction. A hidden path returned `FileNotFoundError`, while another denied path returned `PermissionError`; both mean access failed. An assertion initially expecting only the latter was corrected and its earlier failure retained.

The initial generation-container configuration did not work: missing bubblewrap, denied namespace creation, and a proc-mount restriction had to be diagnosed. The final live probe used the reviewed compatibility adjustment documented in the feasibility report. Candidate/build containers used the default Docker security profile.

Evidence: `results/access-checks/report.json`, `results/evaluation/report.json`, live coding events, and `results/linux-sandbox-probe-*.json`. These are bounded checks of this environment, not proof against every kernel, Docker, sandbox, or agent-runtime vulnerability. A prompt or configuration file claiming isolation is not equivalent to these execution results.

## F-07: stopping the agent's parent process is not enough to stop its work

**Evidence: reproduced defense against a deliberately detached child.**

A child created a new process session, ignored SIGTERM, and wrote a heartbeat. Removing its whole container stopped the heartbeat. A live Codex task was also cancelled while a detached child was active; the container exited with status 137, the heartbeat stopped, and no eligible result was retained.

Stop and remove the execution environment first, then copy/freeze the candidate, then evaluate it. Otherwise a surviving child could change supposedly fixed code after its deadline or audit. Evidence: `results/deadline/report.json`, `results/deadline-independent-reproduction/report.json`, and `results/agent-cancellation/`.

This experiment establishes the tested teardown behavior. Concurrent candidate selection, stale in-flight results, and versioned development-check admission still need their own controller tests during implementation.

## F-08: the harness itself can violate an invariant during reproduction

**Evidence: reproduced ordinary harness defect, fixed and rerun.**

The first independent protected-assertion reproduction failed a required final check: the application directory must remain unchanged. Python had created `application/__pycache__/test_app.cpython-314.pyc` while loading the test module. The source file stayed the same, but a new file violated the directory-integrity rule. Calling that run successful would have hidden a defect in our own harness.

The correction sets `sys.dont_write_bytecode = True` before loading tests. We preserved the failed execution record and original script, recorded the cache hash and diagnosis, removed only that harness-created cache, and reran with a fresh result directory. The rerun exited 0, passed the intended adversarial checks, and confirmed the protected tree remained unchanged. The integrity check was not weakened to ignore the new file.

Evidence: `provenance/protected-tests-reproduction.json` (failed run), `provenance/protected-tests-before-bytecode-fix.py`, `provenance/protected-tests-bytecode-fix.json`, `provenance/protected-tests-reproduction-2.json`, and `results/protected-tests-independent-reproduction-2/report.json`. This was not model reward hacking. It illustrates why independent reproduction and controller invariants must check our own harness as well as candidate behavior.

## F-09: selected real library tests retain protected assertions across a process boundary

**Evidence: reproduced for a limited subset; the full Phase 2 gate remains open.**

The next experiment used the pinned PyYAML 6.0.3 and Python-Markdown 3.10.3 sources from the [candidate assessment](candidate-assessment.md#pinned-sources-and-actual-adoption). The parent loads the original test functions and owns their assertions. Test-only adapters forward a fixed set of operations as bounded JSON to a worker that stays alive across calls. The worker alone imports the candidate and executes library operations, so its state can persist without sharing the parent's interpreter. The worker mounts contain the selected package, normal Markdown distribution metadata, and the worker script, but no repository tests or expected answers.

The selected tests are:

- PyYAML's unchanged `test_loader_error`, `test_loader_error_string`, and `test_loader_error_single` bodies from `tests/legacy_tests/test_errors.py`: 82 + 82 + 3 fixture invocations, **167 cases**. The probe wraps these bodies in `unittest.FunctionTestCase`; it does not run the upstream custom pytest collector. Pinned original helper definitions load in the parent, then the test module's `yaml` binding is replaced with the facade. The actual load operations run against the worker's selected package. One additional valid input must return `{"a": 1}`; negative cases alone are not adequate positive-behavior coverage.
- Markdown's unchanged five `TestMetaData` methods from `tests/test_extensions.py`: HTML conversion, metadata, missing metadata, input without a terminal newline, and reset. A persistent worker preserves each renderer's state between calls. The parent facade supports only `Markdown(extensions=['meta'])`, `convert`, `Meta`, and `reset`.

For each library, we copied the original package and constructed three variants. The output-preserving forgery appends F-01's runner replacement to package initialization. The wrong-output variant additionally replaces YAML loading with empty/`None` results or Markdown conversion with `<p>wrong</p>`. The fake-verdict variant prints `{"passed":true,"tests_run":999}` and exits 0 during import.

| Variant | PyYAML: run / failures / errors / skips | Markdown: run / failures / errors / skips |
| --- | --- | --- |
| Original | 167 / 0 / 0 / 0 | 5 / 0 / 0 / 0 |
| Runner forgery, correct outputs | 167 / 0 / 0 / 0 | 5 / 0 / 0 / 0 |
| Runner forgery, wrong outputs | 167 / 167 / 0 / 0 | 5 / 4 / 0 / 0 |
| Fake verdict and exit 0 | 167 / 0 / 167 / 0 | 5 / 0 / 5 / 0 |

Markdown's reset test ignores the HTML result, so it still passes the wrong-output variant; the other four fail. A missing or malformed worker response counts as a communication failure, not as the YAML error an application test may expect. Both the original and output-preserving forgery reach an added parent assertion after a library call and produce exactly one deliberate failure, with no infrastructure error. The parent's runner and all four original application/library trees remain unchanged.

**Preserved setup failure:** the first Markdown attempt lacked package metadata describing extension entry points. Consequently `extensions=['meta']` failed with `No module named 'meta'`. Inspecting the source confirmed that normal extension lookup uses those installed records to resolve names. We restored the baseline's `markdown-3.10.3.dist-info` metadata after comparing its extension entries with the pinned `pyproject.toml`. No library source or test was weakened. The failed run, original probe script, diagnosis, and eleven metadata-file hashes remain in `provenance/real-library-boundary-1.json`, `provenance/real-boundary-first-real_library_boundary.py`, and `provenance/real-library-metadata*.json`.

The successful run is `results/real-library-boundary-2/report.json`, with command and script hash in `provenance/real-library-boundary-2.json`. Reproduce using `scripts/real_library_boundary.py`; see the external README. It ran with Codex absent from the command path, host CPython 3.14.7, and container CPython 3.13.15 under the pinned Python image. These differ from qualification's CPython 3.12.13. This is a boundary experiment, not equivalent-runtime qualification or a performance result.

**Limits:** no complete application suite ran through this adapter. We attempted seven additional Markdown `TestExtensionClass` tests against the original. All produced errors because the facade lacks `markdown.extensions.Extension`. This is missing adapter support, not a failure in the original library, and it is recorded as unsupported rather than quietly skipped. YAML exception transport supports only the broad `YAMLError` contract used by these cases. The bridge does not preserve arbitrary class instances, identity, nested mutation, extension callbacks, or subclassing. F-10 demonstrates an actual semantic mismatch rather than merely assuming these limitations.

The later [F-17](#f-17-inherited-methods-can-call-back-without-owning-the-callbacks-verdict) supports these same seven class tests through a different bounded mechanism. That progress does not change the outcome or limitations of this earlier adapter.

## F-10: a protective adapter can change behavior while its selected tests pass

**Evidence: reproduced adapter defect with the unmodified original library; not a candidate attack.**

Markdown exposes a mutable metadata dictionary. Two reads of the original property can refer to that same dictionary. F-09's adapter instead sends JSON and builds a new dictionary each time. To check the difference, we ran this observation both directly against the pinned original and through the adapter:

```python
md = markdown.Markdown(extensions=['meta'])
md.convert('Title: Probe\n\nhello')
first = md.Meta
second = md.Meta
same_object = first is second
first['title'].append('changed through alias')
mutation_visible = md.Meta['title'] == ['Probe', 'changed through alias']
```

| Observation | Direct original | Original through facade |
| --- | --- | --- |
| Repeated read returns the same object | True | False |
| Mutation through the first reference appears on the next read | True | False |
| Next read of `title` | `['Probe', 'changed through alias']` | `['Probe']` |

The facade run also reran all five selected metadata tests successfully. The original control executes known baseline code in its own restricted container; it is not presented as protected candidate-test execution. The facade run uses the protected parent/worker boundary. Both use the same package snapshot and image. The snapshot stayed unchanged. Evidence: `results/real-boundary-alias-1/report.json`, its `original-execution.json`, and `provenance/real-boundary-alias-1.json`; reproduction script: `scripts/real_boundary_alias_probe.py`.

This illustrates the “model gap” discussed in the [research investigation](reward-hacking-defense.md#what-the-additional-research-contributes): the checker assumes copied values represent an interface that actually shares mutable objects. Passing a small suite does not establish that assumption. An automatically generated checker could make the same mistake and accept its own simplified view of behavior. We have not established that this particular metadata alias is exercised by MkDocs; it demonstrates why the adapter cannot be called generally transparent. The application's confirmed callback/state dependencies are listed in the [feasibility report](execution-feasibility.md#real-pair-interface-audit-and-subset-result).

Keeping one cached dictionary in the parent is not yet a demonstrated fix. Nested list changes, multiple references, replacement, and reset must all reach the real candidate correctly. Giving the worker unrestricted access to live parent objects could instead expose the checker. The required solution must preserve the interface's meaning and limit what candidate code can do. Both conditions must hold before we call a test faithfully protected.

## F-11: a restricted callback can preserve MkDocs title tests without exposing parent objects

**Evidence: reproduced for eleven existing application tests and one callback contract; full-suite protection remains open.**

The original MkDocs test helper `PageTests._test_extract_title` creates a Markdown renderer and registers a MkDocs `_ExtractTitleTreeprocessor`. During `convert`, Markdown calls that processor. The processor walks a document tree, asks the renderer to serialize/unescape/postprocess text, and stores its result in its own `title` attribute. The test then checks that attribute on the same object. Merely accepting a candidate message saying “the callback set this title” would let the candidate invent what the application did.

The research script `scripts/mkdocs_title_boundary.py` keeps both the actual application callback and unchanged test bodies in the parent. It loads trusted class/helper definitions from the pinned original modules, then supplies a limited Markdown adapter to the test. It also redirects the rendering helper's `_unescape` call. Thus serialization, unescaping, and postprocessing go to the selected library in the worker; those calls do not silently use the baseline. Candidate code never imports into the parent.

The call sequence is:

1. The trusted test creates a renderer and registers its original title processor. The parent keeps that Python object and assigns the renderer a numeric handle, an identifier used in messages. The child registers a forwarding processor with the selected Markdown renderer.
2. During conversion, the forwarding processor sends the document tree as bounded JSON, with the request ID and renderer handle. It receives no live parent object, function, globals, expected title, test body, or way to set a verdict.
3. The parent verifies allowed fields, the operation it is waiting for, renderer identity, callback count, and tree shape. It creates only builtin data and standard-library element objects. Limits are 512 tree nodes, depth 32, 64 KiB per message, and 1 MiB of session output.
4. The parent invokes its registered application callback's `run` method. When that method needs serialization, unescaping, or postprocessing, fixed nested requests execute those operations inside the same child renderer while conversion waits. Normal runs exercise 15 callback invocations and 33 individual postprocessor calls across the eleven tests.
5. The original callback updates its actual parent-owned `title`. This particular callback returns the same root without modifying it; the parent checks both conditions. The child resumes with its original root, preserving child-side root identity for this restricted case.
6. The test reads the actual parent-owned processor and runs its original assertion. A worker “success” message has no authority to set the title or decide the verdict. Once the parent rejects a message, that session cannot resume and later produce a pass.

The selected tests cover setext headings, email escaping, TOC permalink removal, footnote-reference removal, formatting, HTML entities, raw HTML, comments, image alternative text, and attribute-list handling. They are the eleven original methods that call `_test_extract_title`, not the complete page test suite. The direct baseline also ran all eleven before installing the facade.

| Variant/control | Executed result |
| --- | --- |
| Direct original | 11 tests pass, no skips. |
| Original through boundary | 11 tests pass; 15 actual parent callback invocations. |
| Output-preserving F-01 runner forgery | Same 11 passes and 15 callbacks; parent runner remains unchanged. |
| Runner forgery plus replacing every conversion input with `# WRONG TITLE` | All 11 tests fail their existing title assertions; no infrastructure errors. |
| Extra callback fields requesting attribute traversal toward `run.__func__.__globals__.__builtins__.open` | Rejected as invalid callback fields before invoking the callback. No parent attribute traversal is performed. |
| Extra callback fields requesting `title = 'FORGED'` | Rejected as invalid callback fields before invoking the callback. |
| Callback naming another renderer handle | Rejected as outside the authorized conversion. |
| Callback using a stale request ID | Rejected as an invalid response identity. |
| Tree carrying an extra `__class__` field | Rejected as invalid tree data; no class is imported or instantiated from that name. |
| Second callback after a legitimate callback completes | Rejected as a duplicate; only the first callback runs. |
| Callback sent while the parent is awaiting a serializer result | Rejected as outside the authorized conversion; the active callback cannot be re-entered this way. |
| Added mandatory failure after conversion, against original and output-preserving forgery | Each reaches the assertion and produces one failure, zero errors. |
| Added mandatory failure inside the parent callback, against original and output-preserving forgery | Each reaches the assertion and produces one failure, zero errors. The child cannot convert that exception into success. |

Each malformed-message variant causes its first protocol violation to reject the session; all eleven selected tests then report errors, including ten that cannot continue in the rejected session. That is seven constructed protocol variants, **not 77 independently exercised attacks**. Attribute-access packets test the absence of such a protocol capability; they are not claims that a parent filesystem read was attempted and denied by the OS. All attack variants were constructed for the local probe, not spontaneously generated by a coding agent.

Evidence: `results/mkdocs-title-boundary-2/report.json` contains original test IDs/logs, variant results, callback/request records, negative controls, source revisions, source manifests, container commands, and script hashes. `provenance/mkdocs-title-boundary-2.json` records the command and exit status. The initial five-protocol-variant run and its archived script remain in `results/mkdocs-title-boundary-1/`, `provenance/mkdocs-title-boundary-1.json`, and `provenance/mkdocs-title-boundary-1-script.py`. Both runs succeeded. The external README gives an exact standalone command with no agent or model call.

The parent used qualification's CPython 3.12.13 environment; the pinned worker image uses CPython 3.13.15. All four original repositories stayed unchanged. This does not settle the formal runtime or supply performance measurements.

**Limits:** this facade supports one known read-only tree callback, fixed library operations, and one invocation per selected conversion. The child sees a bridge processor, not the actual application class. Trusted baseline class definitions still support parent-side module initialization. General registry inspection, arbitrary subclasses, callback-supplied code, multiple callbacks or callbacks that invoke another callback before completing, mutating or replacement trees, arbitrary shared object graphs, and complete `Page.render` behavior are not established. The parent gained no interface for arbitrary remote attribute access, no pickle transport, and no candidate-code execution. F-10's metadata-alias defect remains unresolved; this different probe does not fix it. Existing application tests were not removed, and this subset cannot replace the required full suites.

This establishes a narrow but real result: an application callback and its assertions can remain in the parent while making nested library calls in the worker. F-12 addresses the next bounded question: callbacks that change the tree and interact with application file objects during MkDocs relative-path processing.

## F-12: selected page-render tests preserve link changes and shared application objects

**Evidence: reproduced for five existing MkDocs tests plus an added state check. Full repository-test protection remains open.**

F-11 kept a read-only title callback in the trusted parent. The next question was harder: can the library call application code that changes the document, and can the application retain its actual shared objects across those calls?

The pinned MkDocs `Page.render` creates a Markdown renderer and registers four application processors. Three walk the document tree: one collects anchors, one extracts a title, and one rewrites relative links and image paths. The fourth examines raw HTML for anchors. After conversion, `Page.render` reads the processors' state. The relative-path processor also stores actual MkDocs `File` objects as keys in `links_to_anchors`; those references must still identify the application's own files.

The external `scripts/mkdocs_relpath_boundary.py` experiment runs unchanged `Page.render`, five original `RelativePathExtensionTests`, and the actual three tree callbacks in the parent. The selected Markdown operations execute in the worker; candidate package code never imports into the parent. The chosen methods are:

- `test_relative_html_link`
- `test_relative_html_link_sub_index_hash`
- `test_relative_html_link_hash_only`
- `test_relative_image_link_from_subpage`
- `test_bad_relative_doc_link`

### How the mutation crosses the boundary

The worker pauses conversion and sends a bounded tree message. The parent checks the request/renderer identity, required callback order, permitted fields, and tree shape before running its registered application callback. It does not expose arbitrary parent attributes or functions.

For relative-path processing, the parent accepts only the link changes the original callback is meant to make: `href` on an `a` element and `src` on an `img` element. It rejects replaced nodes, changed text/structure, or unrelated attribute changes. It sends the permitted edits back as node-index/attribute/value records. The worker applies those edits to its existing tree nodes rather than replacing the tree with the parent's copy. This preserves its node objects and library-specific text types for the exercised path.

The actual application `File` objects stay in the parent. The callback uses them directly, and the checker verifies that each file used as a link-map key is one of those same objects. Serialization, unescaping, and postprocessing calls from the title callback still go to the selected library in the worker.

Raw HTML requires a different arrangement. MkDocs' `_HTMLHandler` inherits from a parser supplied through Markdown. The probe extracts the exact `_RawHTMLPreprocessor` and `_HTMLHandler` class source from the pinned application into `scratch/relpath_raw_application.py` and runs it with the selected library in the worker. The parent accepts only bounded anchor data from that operation. That state remains untrusted returned data, just like converted HTML; it must be checked rather than assumed correct. Table-of-contents data also uses an explicit bounded shape.

### What ran and what it showed

The five original tests pass both directly against the original library and through the protected adapter, with no skips. They also pass against the output-preserving runner-forgery variant. Each protected successful suite exercises **27 parent tree callbacks**; some test methods contain multiple render cases.

An additional state check builds a page with a heading, another-page anchor link, a self-link, an image, and a raw HTML anchor. Direct and protected executions agree exactly on rendered content, title, anchors, table of contents, link records, and diagnostics. The link-map key is the same `File` object as the application's collection entry, and the file's page reference is the original page. Marking that file excluded through another reference changes the state seen by the callback and produces the expected diagnostic on the next render. Both the original and output-preserving forgery match this direct baseline.

| Deliberate variant or control | Recorded result |
| --- | --- |
| Append wrong HTML to every conversion | All five original tests fail; no infrastructure errors. |
| Discard the parent's relative-link edits | Three original tests fail and two pass. This subset does not require changed paths in every case. |
| Remove returned raw-HTML anchor IDs | All five original tests still pass, but the added state check fails its `raw-anchor` assertion: one failure, zero errors. This demonstrates a coverage omission in that small test subset and detection by the extra check. |
| Seven invalid protocol variants: parent-attribute request, foreign renderer, stale request, extra object-class field, unknown callback, reordered callback, and replayed callback | Each rejects the session on its first violation. The five test errors for each variant include later tests unable to use that rejected session; they are not five independent attacks. |
| Valid tree shape containing an `a` element without `href` | The actual parent's callback assertion `assert url is not None` fails. The session is rejected; the result is one failure and four subsequent errors. |
| Valid tree shape containing a parent-looking relative filesystem path | The callback treats it as a documentation link and produces diagnostics. All five original tests fail; no observed host I/O occurs. This is not an OS-level denied-read demonstration. |
| Mandatory failing assertion after rendering, against original and forgery | Each assertion is reached and reports one failure, zero errors. |
| Mandatory failing assertion inside the relative-path callback, against original and forgery | Each assertion is reached and reports one failure, zero errors. |

During callback execution, probe instrumentation intercepts `builtins.open`, `io.open`, `os.open`, `os.system`, `socket.socket`, and `subprocess.Popen`. None of these operations was requested by the tested callback inputs. These mocks measure a limited set of potential parent operations; they are **not an operating-system security boundary** or proof that all callback-driven access is impossible.

The completed report records `bounded_interaction_passed: true`, `phase2_gate_satisfied: false`, `protected_sources_unchanged: true`, and `parent_runner_unchanged: true`. The parent used CPython 3.12.13; the existing pinned worker image uses CPython 3.13.15. No performance claim follows from this experiment.

### Evidence, failed attempts, and limits

The final result is `results/mkdocs-relpath-boundary-5/report.json`. It includes test IDs/logs, the direct state reference, candidate variants, callback records, tree edits, I/O observations, negative controls, source identities, container commands, and helper hashes. The earlier completed run remains in `results/mkdocs-relpath-boundary-4/`; it preceded the added raw-anchor fault. The driver is `scripts/mkdocs_relpath_boundary.py`; its support files are `scratch/relpath_callback_worker.py`, `scratch/title_tree_codec.py`, and `scratch/relpath_raw_application.py`. The [external README](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/README.md#reproduce-the-bounded-mkdocs-relative-path-callback-experiment-f-12) now gives the exact standalone command, prerequisites, expected outcomes, and limits. Final execution and environment records are `provenance/mkdocs-relpath-boundary-5.json` and `provenance/mkdocs-relpath-boundary-environment.json`. Independent worker controls in `provenance/mkdocs-relpath-forgery-controls.json` confirm that the exact forged library falsely passes an in-process failing assertion, while the original reports the failure. The protected parent controls above still fail against that active forgery. All four source repositories are clean, and no probe worker containers remain.

Three earlier failures remain in their result directories and `provenance/mkdocs-relpath-boundary-1.json`, `provenance/mkdocs-relpath-boundary-2.json`, and `provenance/mkdocs-relpath-boundary-3.json`, with archived drivers. First, package comparison incorrectly included pre-existing repository bytecode caches absent from the source-only snapshot; all 33 Python source files matched, and no worker had started. Second, the five protected tests passed but the added heading/state case exposed unsupported nonempty table-of-contents data; the adapter rejected it until bounded support was added. Third, the execution environment denied Docker socket access. That attempt supplies infrastructure-failure evidence, not evidence of a rejected candidate. Run 4 then completed the initial controls; run 5 added the state-only fault above.

This is a test adapter for known processor classes, priorities, order, tree shape, and permitted edits. It does not preserve arbitrary processors, changed/replaced trees, general registry inspection, arbitrary subclasses, shared object graphs, concurrency, or callback reentry. Trusted original class definitions still initialize parent application modules. Raw-HTML state and table-of-contents data returned by the worker need independent checks; bounded data is not automatically truthful data. F-10's metadata-alias defect remains unresolved. No complete application/library suite, general object proxy, formal runtime choice, or safe callback architecture has been established.

The result answers the bounded question positively for these tests and the added state case: a mutating application callback and shared application `File` objects can work while their assertions resist the tested forgery. It does not close Phase 2 or justify skipping the remaining required interfaces and suites. The later [F-16](#f-16-shared-object-transport-must-not-make-evaluator-evidence-shared-too) separately addresses the observed metadata alias defect; its mechanism is not integrated into this earlier callback adapter.

## F-13: the YAML adapter loses shared and recursive values

**Evidence: reproduced with the existing narrow YAML facade and unchanged original PyYAML. No full protected suite is claimed.**

A YAML alias can make two entries refer to the same object. This is a stronger relationship than having equal contents. For example:

```yaml
a: &shared [1]
b: *shared
```

Direct original PyYAML loads this into a dictionary where `result['a'] is result['b']` is true. Appending `2` through `a` also changes the list seen through `b` to `[1, 2]`. The existing facade sends the worker's answer through JSON. That message represents two equal lists, so the parent reconstructs two different objects. Identity is false, and the append through `a` does not appear through `b`.

A second input, `&self [*self]`, represents a list containing a reference to itself. The original returns that recursive list. The existing worker closes the result pipe instead of delivering it. A tree-shaped JSON value cannot express this reference without an additional, explicitly checked graph representation.

| Check | Direct original | Existing facade |
| --- | --- | --- |
| Two alias entries identify one list | True | False |
| Mutation through one alias appears through the other | True | False |
| Recursive list identifies itself as its first element | True | No value returned; result pipe closes |

The source snapshot matches the pinned original. The direct host uses CPython 3.12.13 and the reused worker uses 3.13.15; the report records that mismatch. This is evidence about the existing adapter and representation, not a same-runtime qualification or proof that all process boundaries must fail.

The accompanying inventory reran all **430 yamllint tests and 1,283 pure-Python PyYAML tests**, with no failures or skips, directly against the original. Those runs are ordinary shared-interpreter tests, not protected execution. A second passing application run profiled actual calls into PyYAML. Source and execution show that a full solution must also preserve stateful loaders, token identity/classes, resolver registration, exceptions, actual builtin types, and library selection in application subprocesses. The upstream tests add custom subclasses, constructors, representers, streams, and recursive objects. No tests were excluded to accommodate the facade.

At this stage, stable object identifiers and a checked graph format were proposed ingredients of a future solution. The later [F-16](#f-16-shared-object-transport-must-not-make-evaluator-evidence-shared-too) implements a bounded version; it does not alone resolve class behavior, callbacks, or authority over arbitrary parent objects. The optional native LibYAML suite was already outside the original pure-Python baseline; this investigation introduces no additional exclusion.

Evidence: `results/pyyaml-full-inventory-1/report.json` records the counterexamples, source identities, Python versions, and unchanged tracked sources; `unittest.json` and `pytest.json` record every collected test and outcome. `results/pyyaml-full-profile-1/report.json` records the observed call edges. The [external assessment](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/pyyaml-full-protection-assessment.md) provides source locations and exact standalone reproduction commands. Profiling excludes child-process calls and does not supply performance measurements.

## F-14: moving Markdown to a worker changes an existing recursion test

**Evidence: reproduced on the same CPython 3.12.13 executable with the unchanged original library. This experiment checks semantics, not an adversarial security boundary.**

A process boundary changes more than object transport: it also changes the running program's call stack. Markdown's blockquote parser observes that stack. Its `nearing_recursion_limit()` function subtracts the current stack depth from Python's recursion limit and stops further nesting when fewer than 100 levels remain.

The existing `TestBlockquoteBlocks.test_nesting_limit` temporarily sets a limit relative to its current stack, then converts ten `>` characters. Its unchanged assertion expects five nested blockquotes followed by five literal markers. Direct original execution passes.

The experiment leaves that test body and its assertion helper in the parent, and sends the source text and constructor options to an original-library worker. Both processes use the exact same Python executable. All 33 Python files in the worker's Markdown package match the pinned original.

| Execution of the unchanged test | Output | Test result |
| --- | --- | --- |
| Direct original | Five blockquotes and five literal markers | Pass |
| Worker with its default recursion limit of 1,000 | Ten blockquotes | One assertion failure |
| Worker given the parent's numeric limit of 130 | Eight blockquotes and two literal markers | One assertion failure |

Both worker calls finish normally. There are no skips, timeouts, or infrastructure errors in the completed run. Copying the numeric setting does not copy the stack of active calls that the parser measures. These failures therefore cannot be fixed merely by matching Python versions or returning stable object identifiers.

This matters to evaluator integrity: an adapter that rejects correct original behavior is not a faithful judge of a specialization. Returning the expected HTML, changing the assertion, skipping this case, or secretly rendering with the baseline in the parent would conceal the problem. A different execution arrangement must demonstrate that it preserves the required behavior. This single counterexample does not prove that every possible arrangement is impossible.

The full inventory collected **724 MkDocs tests with four declared skips and 1,088 Markdown tests with twelve declared skips**, without discovery errors. It identified further requirements involving local subclasses, registries, mutable collections, regex matches, file objects, mocks, callbacks, and subprocesses. It also found that **978 Markdown tests inherit support from `markdown.test_tools`**, and 142 executable methods originate in that helper's generated closure. Although the helper lives inside the library package, it contains evaluator assertions and must remain frozen and protected from candidate edits.

Evidence: `results/mkdocs-full-runtime-2/report.json` contains the unchanged test's logs, requests, outputs, executable identity, and source hashes. `results/mkdocs-full-inventory-1/` contains every collected test and source location. The [external assessment](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/mkdocs-full-interface-assessment.md) and [README](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/README.md) explain reproduction. Attempt 1 failed because probe instrumentation called the stack-depth helper from an invalid frame depth before conversion; its report and archived worker remain preserved. It supplies no semantic counterexample. The completed run restored the parent's temporarily redirected helper binding, and the original repositories remained unchanged.

## F-15: measured recursion context preserves one test family, with observable limits

**Evidence: executed twice on the same CPython 3.12.13 executable. This is a behavior experiment, not an adversarial protection mechanism.**

F-14 fails because Markdown considers both the recursion limit and the current stack depth. The next experiment measures their difference at the caller's conversion entry:

```text
remaining budget = caller recursion limit - caller stack depth
worker recursion limit = remaining budget + worker stack depth
```

The worker measures its depth at the actual selected `Markdown.convert` entry. A temporary profiling hook sets the calculated limit, then removes itself before the method body. Only input text, constructor options, and numeric context cross the boundary. The worker receives no expected output, test identifier, parent frame, or parent globals. Its actual selected library performs the conversion.

The unchanged repository test runs at three additional caller depths: 0, 5, and 17 frames. Worker wrapper depths vary independently: 0, 7, and 23 frames. Supplemental inputs use 30 blockquote markers and four relative recursion limits. Those extra comparisons check a range of outputs rather than fitting the mechanism to the test's expected five blockquotes.

| Comparison | Observed result |
| --- | --- |
| Original repository test, direct execution at three caller depths | 3 passes |
| Same test with measured budget transfer | 9 passes |
| Supplemental output and remaining-budget comparisons | 36 matches with direct original execution |
| Default worker or copying only the absolute recursion limit | 6 original assertion failures retained |
| Selected candidate changed to append an HTML comment to its real output | Original assertion rejects the changed output |

The mechanism preserves the observed budget, but changes another observable setting. One case has a caller limit of 132 at depth 13 and a worker limit of 122 at depth 3. Both have 119 levels remaining. Code that reads the absolute limit can still distinguish the executions. Therefore this result does not establish transparent execution for arbitrary library code.

A second approach keeps the absolute limit and adds ordinary wrapper frames until the worker's numeric depth matches the caller. All 27 supported cases match output, limit, depth, and budget. Eighteen cases start with a deeper worker stack and explicitly report unsupported before entering the converter. Adding frames cannot remove existing frames. Even supported cases do not reproduce the identities, names, or globals of the caller's real frames.

The complete report contains **112 executions, not 112 different repository tests**. Imports and construction occur before context adjustment. The experiment does not cover context changes during callbacks, arbitrary callables, candidate interference with the profiling hook, or an OS-enforced worker boundary. The parent imports trusted original assertion support; it does not import the altered candidate. None of these results supplies a performance measurement.

Evidence: `results/runtime-context-2/report.json` and the independently rerun `results/runtime-context-root-reproduction/report.json` agree on the bounded success and padding limits. Both report `security_boundary_demonstration: false` and `phase2_gate_satisfied: false`. `provenance/runtime-context-2.json` and its frozen driver/worker copies record source identities. The earlier 67-case experiment remains preserved. The [external README](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/README.md#transfer-numeric-recursion-context-for-one-markdown-test-family) gives exact commands and prerequisites. Original library and test sources remain unchanged.

## F-16: shared-object transport must not make evaluator evidence shared too

**Evidence: the bounded graph experiment and its independent rerun pass. A review-discovered evidence-ownership defect has a focused executed regression. A subsequent container version and its independent rerun pass the same checks with restricted workers.**

Plain JSON copies a tree of values. To preserve an alias or a cycle, the new message format instead describes a graph: each list or dictionary has a stable identifier, and entries can refer to that identifier. The parent constructs actual builtin lists and dictionaries. Later messages update the already registered objects in place, so existing references see the change.

This has a deliberately small domain: exact builtin lists and dictionaries, string dictionary keys, and bounded inert scalars. It accepts no candidate-defined classes, reconstruction functions, arbitrary attribute access, or executable objects. Messages have a 64 KiB limit, sessions retain at most 256 container objects, and graphs have at most 4,096 entries/references as counted by the codec. Those are experiment limits, not a proposed full-library contract.

The worker imports actual selected PyYAML and Markdown source copies. The parent imports their unchanged test module through an explicit facade and owns its assertions. Direct original and worker executions use the same CPython 3.12.13 executable.

| Check | Observed result |
| --- | --- |
| YAML aliases, mutation through an alias, a list containing itself, and a dictionary referring to itself | Match direct original behavior, with actual builtin container types |
| Markdown metadata read twice, changed through an alias, synchronized across another call, and replaced on reset/conversion | Match direct original identity and state observations; retained old parent aliases keep their contents |
| Five unchanged metadata repository tests | Pass against original and output-preserving runner-forgery candidates; no skips |
| Wrong output combined with runner forgery | YAML observation rejected; four of five metadata tests fail |
| Deliberate parent assertion after conversion | Fails against all three variants, although the forged child runner reports its own false test as passing |
| Thirteen malformed graph/message controls | Rejected; registered object contents remain unchanged in the graph-mutation controls |

### Why saved evidence needed an additional boundary

The first driver saved a returned control dictionary directly in its report. That dictionary was also registered as a shared graph object. Its contents could therefore change when a later valid message updated the same identifier:

```python
shared_result = decode_worker_graph(first_message)
report['observed_control'] = shared_result
decode_worker_graph(later_message)  # Can update that same dictionary in place.
```

The message need not contain an invalid field or touch the report file. Both references identify the same mutable dictionary in the parent. Preserving application aliases, which is necessary for correctness, accidentally preserved an alias into evaluator evidence too.

The fix detaches the validated inert data when recording it as evidence. A regression first records `successful=False` and `body_reached=True`, then applies a structurally valid shared-object update setting the opposite values. The shared application object changes, while the detached evidence stays unchanged. Copying is safe here because this graph domain contains only validated builtin containers and inert scalars; arbitrary candidate objects cannot provide a custom copying function.

Detaching a report does **not** make its original contents truthful. A candidate can lie in the first message. Parent assertions and controller observations remain authoritative; child runner status is diagnostic data.

### Invalid messages and caught infrastructure errors

Validation must finish before existing objects change. Checking graph structure is insufficient if a graph's root has the wrong type for an operation. The regression supplies a valid-looking update that would overwrite a shared list, but gives Markdown metadata a list where a dictionary is required. The decoder rejects it before applying the update.

A separate malformed-worker control exposes another false-pass risk. A test catches `Exception`, so it catches the communication error and its test runner reports success. The parent nevertheless retains a separate infrastructure-failure record, rejects acceptance, and permanently closes that session. A second call is refused. Communication errors use a dedicated `ProtocolError`; they are not transported as a library `ValueError` or `KeyError` that might satisfy an expected-error assertion. A partially failed encoding operation also makes the session unusable.

### Repeating the checks inside restricted containers

The container version reuses the frozen graph codec, worker, and checks. Each worker runs as a non-root user with no network, a read-only root filesystem, no Linux capabilities, no privilege escalation, and bounded memory, CPU, and process count. Its four read-only mounts provide only the selected source, Markdown package metadata, worker script, and codec. A small writable temporary filesystem supports ordinary temporary files. The parent retains the assertions and report files outside those mounts.

Both the first run and an independent repeat preserve the results in the table above, including the evidence-snapshot and caught-error controls. Each run creates and removes 23 containers. The controller inspects their actual configuration and confirms their absence after removal; it does not merely stop its local Docker client.

An additional control using only the original library verifies imports from `/candidate`, matching hashes for all 17 PyYAML and 33 Markdown Python source files, and the absence of the qualification directories `/sources`, `/envs`, and `/wheels`. This control checks environment preparation. An untrusted candidate reporting its own imports would not supply equivalent evidence.

The parent uses macOS CPython 3.12.13 and the container uses Linux CPython 3.12.13. Their version numbers match, but their operating systems and interpreter binaries differ. These runs therefore establish the exercised graph behavior under this container arrangement, not identical runtime environments or timing comparability.

**Limits:** synchronization covers the active exposed metadata graph, not arbitrary mutations of every historical object a library might retain. The codec has no support for custom classes, streams, callbacks, tuples, arbitrary dictionary keys, or concurrency. Graph identifiers do not constitute a general permission system for all parent objects. The initial ordinary worker had no OS confinement or process-tree teardown; the later container version adds those controls for this same limited interface. Passing this small domain addresses the demonstrated F-10/F-13 examples; it does not establish a replacement for the required full suites.

Evidence: `results/shared-graph-boundary-4/report.json` and `results/shared-graph-boundary-independent-1/report.json` record the ordinary-process results. `results/shared-graph-container-1/` and `results/shared-graph-container-independent-1/` add the container reports, configuration inspections, environment control, and cleanup records. Earlier runs and source copies are preserved, including the pre-fix evidence alias. The scripts are `scripts/shared_graph_codec.py`, `scripts/shared_graph_probe.py`, `scripts/shared_graph_container_probe.py`, and `../scratch/shared_graph_worker.py`; report manifests identify the exact scripts and candidate sources. Original and candidate source hashes remain unchanged during execution. The [external README](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/README.md) gives reproduction instructions. The container reports set `os_sandbox: true`; `full_suite_protected`, `performance_claim`, and `phase2_gate_satisfied` remain false in every run.

## F-17: inherited methods can call back without owning the callback's verdict

**Evidence: 39 bounded cases, comprising 69 test executions, passed their expected positive and negative controls in the ordinary-process run and an independent repeat. A later restricted-container version and its independent repeat pass the same controls. Full-suite protection remains unestablished.**

The seven existing Markdown `TestExtensionClass` tests define a local subclass of the library's `Extension` class. The subclass has a configuration dictionary containing mutable lists. The tests call inherited methods to read and change that configuration. The earlier narrow adapter could not support these tests.

The new prototype keeps the test-defined class, configuration, and assertions in the parent. A worker executes inherited methods from the actual selected library. Stable graph identifiers preserve shared configuration between instances and aliases into its nested lists. The evaluator does not copy the original method bodies into its own implementation.

An added test defines its own `getConfig` override. The selected library's `getConfigs` method calls that override for each key. The worker requests the specific parent callback through a checked message. The callback can inspect and change its configuration, assert properties, and call `super().getConfig`, which makes a nested request to the selected library. Parent functions and their globals never become worker objects.

| Check | Observed result |
| --- | --- |
| Seven unchanged repository tests, direct original and original worker | All pass, without skips |
| Same seven tests with worker runner forgery, including a variant that catches callback exceptions | All pass with preserved original behavior; the forgery does not change the parent runner |
| Selected `getConfigs` changed to return an empty dictionary | Three original assertions fail |
| Shared class configuration, nested aliases, parent/worker mutations, callback result identity, and tuple-valued descriptions | Added direct and worker observations match |
| Deliberate assertions before, inside, and after the callback, across three worker variants | All nine remain failures |
| Eleven malformed, unauthorized, or replayed message controls | Rejected without the tested pending configuration changes taking effect |

### An exception is not always a failed evaluation

An application callback may raise `KeyError`, `ValueError`, or even `AssertionError`, and library code may legitimately catch it. The experiment preserves those types and their argument values, including the tested catching behavior. Declaring every caught exception a failed evaluation would change application behavior.

The added mandatory callback assertions use an explicit evaluator marker. If such a failure escapes the parent callback, the parent records it permanently and terminates the worker. It does not send the failure to candidate code to decide whether to catch it. A worker variant that catches ordinary callback exceptions therefore cannot suppress that mandatory assertion. If trusted callback code intentionally catches its own marked assertion before returning, the boundary sees no escaped failure; the corresponding control passes.

This marker is deliberate instrumentation in the **added controls**. The seven original test bodies are unchanged, but the prototype does not automatically identify the intent of every assertion inside arbitrary existing callbacks. That classification remains part of the unresolved full-suite design.

A separate five-case ordinary-`unittest` experiment illustrates the distinction. A test helper's failure escaping the test produces failure. The same helper failure intentionally caught by `assertRaises` inside a callback produces a pass. Catching it outside that callback also produces a pass under ordinary Python semantics, even though its traceback still identifies the genuine helper. A custom test failure class need not be `AssertionError` at all. These constructed cases and an independent repeat show why exception type or helper origin alone cannot determine intended mandatory status. They do not establish that the ambiguous catch pattern occurs in the required upstream suites. Evidence is `results/assertion-provenance-1/report.json` and `results/assertion-provenance-independent-1/report.json`; the [architecture review](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/direction1-architecture-review.md#assertion-provenance-what-unchanged-python-code-actually-tells-us) includes reproduction instructions.

### A passing test body cannot erase a broken evaluation

Review found that the first expanded driver recorded communication failures but still exposed the test runner's `passed` value without an independent eligibility decision. A test expecting or broadly catching an exception could therefore report success after a broken exchange.

The corrected driver records `infrastructure_ok`, `evaluator_ok`, and `eligible` separately from `passed`. All eleven message controls and an unsupported-value encoding control deliberately catch the error. Their test bodies pass, but all twelve evaluations remain ineligible because the protected infrastructure-failure state persists. The failed sessions cannot be reused.

One review claim was itself incorrect: a reviewer reported that malformed exception metadata could bypass a missing type check. Independent source inspection showed that the short-circuit type guard was already present. The claim was withdrawn, and an explicit malformed-metadata control confirmed rejection before mutation. This was added coverage, not a repaired defect. Model review statements require the same source and execution checks as implementation statements.

### Repeating the inheritance checks in restricted containers

The container companion runs the same frozen checks with only the selected source, package metadata, worker, and two protocol helpers mounted read-only. Workers use the source-free pinned Python image, a non-root user, no network, a read-only root, no Linux capabilities, no privilege escalation, and bounded resources. Both runs remove all 59 containers: 58 test workers and one original-only environment control. The controller verifies the configured restrictions and absence after removal.

That environment control verifies the original source hashes, imports from the selected mount, and absence of alternative qualification sources. The parent still runs macOS CPython 3.12.13 while workers run Linux CPython 3.12.13; these are different interpreter binaries and operating systems.

Review caught a problem in reusing the ordinary driver's forgery check. It located the selected source by its position in a process command. A Docker command has different positions, so the filter could find no forged workers; `all([])` would then report success without checking one. The companion now uses controller-owned source roles, requires the expected nonempty groups and per-case worker counts, and checks the deliberate original failure against the forged pass. Empty-group and incorrect-original controls reject. This prevents a vacuous activation claim; candidate-reported runner status remains diagnostic rather than authoritative.

**Limits:** this is an explicit protocol for a small `Extension` interface. It permits the tested override only during `getConfigs`, so it cannot yet support every legitimate candidate rearrangement. Constructor failures before object registration, arbitrary descriptors/metaclasses, general inheritance, and other callbacks remain unsupported. Configuration graphs have the bounded builtin domain described in F-16; tuple support covers only the returned description pairs. The later F-19 separately connects extensions to rendering; it is not integrated into this container checkpoint.

Evidence: `results/extension-callback-4/report.json` and `results/extension-callback-independent-1/report.json` contain matching checks and source hashes. Earlier runs and exact source versions are retained under `provenance/extension-callback-*`. The driver is `scripts/extension_callback_probe.py`, with frozen codec/wire support and `../scratch/extension-callback-worker.py`. The [external README](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/README.md) gives the standalone command and prerequisites. `security_boundary_demonstration` and `phase2_gate_satisfied` remain false.

Container evidence is `results/extension-callback-container-3/` and `results/extension-callback-container-independent-1/`, including configuration, activation, and cleanup records. The companion is `scripts/extension_callback_container_probe.py`. Its reports set `os_sandbox: true` and retain `phase2_gate_satisfied: false`. The first denied Docker preflight is retained; it did not start a container or execute these checks.

## F-18: caller-defined classes need more than copied values

**Evidence: a reduced PyYAML class-ownership experiment and its independent repeat pass their expected controls. This is an ordinary-process mechanism result, not execution of complete unchanged upstream tests.**

A test can define a subclass of a library's `Loader`, override a method, and call the library's base method from that override. Separating the library requires a nested exchange: parent calls worker, worker calls the parent's override, and that override calls the selected base method in the worker before the first call finishes.

The prototype executes the original `_make_loader` helper from PyYAML's structure tests. Its caller methods stay in the parent; the worker executes actual selected parsing and base methods. Recorded requests reach nesting depth two. A second reduced fixture exercises `YAMLObject`: defining a class triggers selected-library registration, a parent constructor creates an instance of the actual caller class, and a parent representer reads it during selected serialization. Numbered owner handles let a worker passback resolve to the identical parent object without importing candidate-defined executable objects into the parent.

| Control | Observed result |
| --- | --- |
| Original direct execution and separated original/runner-forgery execution | Matching sequence, mapping, custom-class fields, serialization, and reconstruction |
| Selected sequence constructor appends `99`; integer constructor adds `1` | Behavioral differences detected, including through nested base-method calls |
| Parent assertion deliberately fails after a selected call | Failure remains a failure with the worker forgery active |
| Eleven malformed authority, result, or encoding controls | Tests catch the errors, but independent infrastructure state rejects eligibility and reuse |

The original override returns a tuple internally, but the selected YAML sequence constructor extends a list with it. The final list is correct original behavior. Similarly, an upstream fixture's equality method returns a tuple expression rather than a Boolean. The experiment records those facts instead of silently correcting the source to match an expectation.

**Limits:** four class bodies are extracted from the upstream `_make_objects` helper into a reduced namespace. Their bodies are unchanged, but their surrounding construction context and qualified names change. The direct baseline uses that same reduced fixture. This cannot be described as running the complete unchanged upstream tests. Builtin aliases/cycles are not integrated, general class identity and streams are unsupported, and every callback exception ends the session, so ordinary catchable callback exceptions are not preserved. No OS sandbox is used. The control named `replayed_callback_id` supplies an invalid first sequence; it does not replay a previously accepted message.

Evidence: `results/mixed-class-boundary-5/report.json` and `results/mixed-class-boundary-independent-1/report.json` use the same frozen sources and pass all eleven controls. The [assessment and reproduction instructions](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/mixed-class-protection-assessment.md) identify the source bodies, exact observations, commands, and retained earlier failures. The scripts are `scripts/mixed_class_probe.py` and `../scratch/mixed_class_worker.py`. `full_suite_protected`, `os_sandbox`, and `phase2_gate_satisfied` remain false.

## F-19: extension registration and rendering must work in the same session

**Evidence: 30 cases pass their expected positive and negative controls in the original run and an independent repeat. They connect one unchanged upstream test and added controls to an actual selected renderer. The experiment uses ordinary processes.**

Supporting an extension's methods in isolation does not show that the library can accept the extension and use it during rendering. This experiment runs Markdown's unchanged `testRegisterSerializer`: a caller-defined extension registers a caller function in `md.output_formats`, and selected Markdown invokes that function while producing the final result.

The worker executes the selected extension constructor, Markdown constructor, extension registration and type check, conversion, serializer dispatch, and final output processing. The extension and serializer callbacks run in the parent. A narrow capability permits format registration; a validated Element snapshot supplies the serializer's input. The worker cannot name an arbitrary parent function or request its globals.

The upstream serializer ignores its input and returns a constant. An added check therefore inspects the actual tree and returns output derived from `alpha` and `beta`. A third renderer uses the earlier function without receiving an extension. This matches the original library's class-level `output_formats` mapping: a registered function can outlive the renderer that registered it. Request sequence checks must reject stale messages without incorrectly revoking this legitimate registration.

| Control | Observed result |
| --- | --- |
| Unchanged upstream test; added input-dependent and persistent-registration checks | Direct and separated observations match |
| Selected constructor throws; selected registration is omitted | Original test errors, showing those selected paths execute |
| Selected serializer dispatch or final output is deliberately wrong | Original assertion fails |
| Mandatory assertion in extension callback, serializer callback, or after rendering, across three variants | All nine remain failures, including with runner forgery and exception swallowing |
| Eight malformed/unauthorized/replayed callbacks and one unsupported facade call | Test bodies catch the errors and pass, but all nine evaluations remain ineligible |

**Limits:** the renderer capability supports format assignment, not a transparent mapping or general renderer access. The Element snapshot does not preserve shared tree identity or synchronize caller mutations. General subclass behavior, arbitrary callbacks, streams, context transfer, and OS isolation are not integrated. Added mandatory assertions use the explicit marker described in F-17; automatic protection of every existing assertion is still unresolved.

Evidence: `results/serializer-callback-3/report.json` and `results/serializer-callback-independent-1/report.json` pass all ten summary checks with identical source hashes. The [assessment and reproduction instructions](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/serializer-callback-assessment.md) explain message authority, registration lifetime, and exact limits. Sources are `scripts/serializer_callback_probe.py`, `scripts/serializer_callback_wire.py`, and `../scratch/serializer-callback-worker.py`. `phase2_gate_satisfied` remains false.

## F-20: valid messages do not establish faithful result capture

**Evidence: source review only. No new attack implementation, mutant, or execution result exists. The attempted experiment-generation task was automatically blocked for possible cybersecurity risk.**

The protected parent checks the data it receives. For example, it verifies that a reply belongs to the active request, uses permitted fields, and describes an allowed object graph. These checks protect the parent from malformed messages and unauthorized operations. A separate question is whether that message faithfully describes what the selected library actually returned.

In the mixed-class worker, the selected `yaml.load` call, `encode(result)`, and JSON output all execute in the same Python interpreter. The graph and serializer prototypes have the same broad arrangement. Their support files have recorded hashes, but file identity does not establish the integrity of live result-capture operations inside that interpreter. The current source does not supply a separate enforcement boundary between candidate execution and result packaging.

This matters especially when the parent reconstructs objects and checks their types or identities. Such a check establishes a property of the reconstructed parent object. A faithful adapter must also justify its correspondence to the object and relevant effects produced by the actual selected library. Validating the message's shape alone does not establish that correspondence.

Normal application replay remains an independent check: the application directly consumes the delivered library's results, and an external comparison can detect differences in the exercised outputs and state. That does not establish faithful transport of every object used by repository tests. No new application replay or successful packaging attack was executed for this finding.

**Next requirement:** establish result capture and its enforcement outside candidate authority, or an independently justified way to verify the corresponding behavior. Adding more object types to a message format does not itself meet that requirement. A different testing engine is one research option, not an adopted solution; its compatibility and operation semantics would also need qualification.

Evidence: the [source-only capture review](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/cross-protocol-protection-assessment.md#additional-source-only-review-who-captures-the-actual-result) records the inspected source paths and hashes. Existing positive and negative results remain valid for their stated cases. Neither this review nor the blocked experiment proves a general bypass or that every process-based design is impossible.

## F-21: a protected host still needs faithful Python operations

**Evidence: exact-release source review and benign runtime experiments, independently repeated. No new attack or protected full-suite result.**

The user authorized a different Python engine for correctness testing only. This experiment uses GraalPy Community 25.2.4 inside a Java host. A **guest** is the Python program managed by that engine; the **host** is the Java program creating the engine and checking its results. The proposed advantage is that ordinary guest Python mutation cannot directly rewrite Java checking code. Whether the complete arrangement safely enforces that separation still depends on its runtime and exposed capabilities.

The recorded startup accepts `SandboxPolicy.UNTRUSTED` and returns the expected scalar values to Java. The configuration disables guest native access, process creation, host class lookup/loading, host filesystem/network access, environment access, and cross-context sharing. It sets explicit resource limits. Startup failures are retained: mutable Java conversion mappings had to be disabled; reserved host stack space had to meet the policy's minimum; and explicitly choosing the POSIX backend was prohibited under this policy. The final configuration uses the documented Java embedding default without enabling native access. Policy acceptance is execution evidence, not a proof against every attack or a test that exhausts each resource limit.

The next experiment passes 15 Java checks of normal Python behavior. It covers an actual returned list, shared aliases, a cycle, visible mutation, exact builtin/subclass type distinctions, a custom sequence, and an explicit Java callback. Both startup and capture checks have independent repetitions with matching source hashes.

The important qualification is **which operation the host performs**. The fixture's `Greeting.__call__` returns `Hello Ada`. It also declares a documented foreign-language call interface that uppercases that result. Calling it with Python syntax returns `Hello Ada`; calling its foreign interface through Java's `Value.execute` returns `HELLO ADA`. This is intentional interface behavior, not a bypass. Likewise, reading the custom sequence through Java invokes its Python indexing method. A host-owned check does not imply that every value read is a passive inspection or that a foreign call has the same meaning as a Python call.

The pinned runtime source gives builtin sequences specialized storage access, so it would also be incorrect to claim that every list read is custom guest behavior. Type, identity, operation, and conversion rules must be qualified together. The successful cases justify further investigation of capture; they do not establish capture for arbitrary library objects.

There is a second, separate ownership problem. Putting both original Python tests and selected Python library code in one guest context leaves the assertions as ordinary Python functions in that context. Moving Java's checker outside it does not automatically protect those functions. Source review of the exact SDK shows that shared values from another context use interoperability operations and enter the object's originating context. A common mechanism still needs to preserve mixed-origin classes, callbacks, shared state, exceptions, and mandatory test verdicts.

A small two-context experiment now gives a concrete compatibility result. All ten observations pass in the one-context control. Across two separately created restricted contexts, base construction, alias identity, list mutation, and callback execution still match. The combined subclass/override/`super()` operation raises a guest `RecursionError`, and `type(shared_a) is list` becomes false for the shared foreign list. Three class-dependent observations do not run after the inheritance error. The recorder exits successfully because it recorded the comparison; that process exit does **not** mean compatibility passed. Its output explicitly records two mismatches. This experiment does not identify the precise failing operation within the combined inheritance step or prove that every alternative mechanism fails.

Separately, the unchanged Markdown recursion test and all 88 API tests pass in a single restricted GraalPy context, with matching reference identifiers/skips and unchanged frozen inputs. Those tests exercise ordinary original code and still share memory with their assertions. They establish compatibility of the exercised tests under the recorded profile, not a protected full suite. These runs use a bounded filesystem adapter for original files and temporary outputs; that adapter is experiment support, not a qualified security boundary. The two-context and original-suite results have controller review but no independent execution repeat. Further work was paused at the user's request.

Evidence and reproduction: [runtime startup](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/runtime/graalpy-25.2.4/README.md), [benign capture checks](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/graalpy-capture/README.md), and [source/API review](/private/tmp/jit-lib-feasibility.2__rqrwc/experiment/graalpy-capture/source-review.md). The runtime reports Python 3.12.8; the qualified CPython reference is 3.12.13. Compatibility is an execution question, not an inference from their shared major/minor version. GraalPy is not adopted, and Phase 2 remains open.

## How to preserve the next finding

For each new finding, record the requirement at risk, exact candidate/checker identities, execution conditions, smallest example, expected and actual behavior, raw evidence location, proposed or tested fix, and untested limits. Keep published reports, proposed attacks, and local executions distinct. Retain failures and inconclusive experiments as well as successes.

Do not infer intent from a defect. A mistaken assumption, fabricated model claim, faulty checker, and deliberate-looking bypass can lead to the same false acceptance and need overlapping technical controls.

The next work is the [defense plan's validation sequence](reward-hacking-defense.md#remaining-validation-and-execution-order). These findings do not authorize weakening tests, changing application call sites, changing the library runtime, or advancing past the unresolved Phase 2 boundary.
