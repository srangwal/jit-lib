# Small experiments you can run and change

These four experiments explain the evaluation problems behind Phase 2 of
Just-in-Time Library. They use a toy addition function and Python's standard
library. You do not need our candidate repositories, Docker, Codex, a model,
network access, or any third-party packages.

These are deliberately constructed teaching examples. They do not show that an
agent spontaneously attempted to cheat, and they do not establish that Phase 2
is complete. The fourth example demonstrates a faulty adapter rather than
cheating by a library.

Use Python 3. Run the examples as scripts in fresh processes, not by importing
them into a persistent notebook. The examples that alter Python objects do so
in memory; ending the process discards those changes. `-B` prevents Python from
creating bytecode-cache files.

Verified locally with CPython 3.14.7: all six modes across examples 1 and 2
produced the expected exit statuses and test-body counts; examples 3 and 4
completed with their checks passing. Commands also worked from outside this
directory when given absolute script paths.

From the project root:

```sh
cd docs/reward-hacking
```

Read and run them in this order:

| Order | Full source | What it demonstrates |
| --- | --- | --- |
| 1 | [01_forged_tests.py](01_forged_tests.py) and [toy_library.py](toy_library.py) | A library can return correct answers while making a test runner report success without running assertions. |
| 2 | [02_separate_assertions.py](02_separate_assertions.py), using the same toy library | Moving assertions to a separate process defeats that specific in-memory forgery. |
| 3 | [03_fake_timer.py](03_fake_timer.py) | A library process can report zero time for work that actually took time; a parent's clock still measures elapsed time. |
| 4 | [04_json_changes_objects.py](04_json_changes_objects.py) | Copying data through JSON can change shared-object behavior even when the initial values are equal. |

## 1. Report passing tests without running them

The toy library adds two numbers. Its `configure` function selects one of three
behaviors:

- `original`: calculate the correct sum and leave the test runner alone.
- `forged`: calculate the correct sum, but replace `unittest.TestCase.run` with
  a function that reports success without calling the test body.
- `wrong`: return a sum that is one too large, without tampering with the runner.

The forgery is an explicit switch for readability. Candidate code could perform
the same assignment when its package is imported. It changes a shared Python
class in memory, without editing the test files.

The two tests assert that `add(2, 3)` equals `5` and `999`, respectively. The
second assertion is deliberately false. A working test runner must reject it.

Run these commands individually:

```sh
python3 -B 01_forged_tests.py original
python3 -B 01_forged_tests.py forged
python3 -B 01_forged_tests.py wrong
```

Expected results:

| Mode | Ordinary answer | Bodies entered | Runner reports | Process exit status |
| --- | ---: | ---: | --- | ---: |
| `original` | 5 | 2 | One failure | 1 |
| `forged` | 5 | 0 | Two successes, `OK` | 0 |
| `wrong` | 6 | 2 | Two failures | 1 |

**The failures are intentional.** A traceback ending with the deliberate
assertion and `FAILED (failures=1)` is the expected original result. A process
exit status of 1 means the test suite failed. You can inspect the previous
command's status with `echo $?` immediately afterward.

Notice that both `original` and `forged` return `5` to an ordinary caller.
Checking that answer alone cannot reveal whether the repository assertions ran.
Also notice that the forged runner still claims to have run two tests: its
`startTest` calls increment the count even though it never enters their bodies.

The printed list of entered bodies makes this particular demonstration visible.
It lives in the same process, so it is not a general tamper-resistant detector.

**Try changing it:** change the `999` expectation in `01_forged_tests.py` to `5`.
The original should then pass with both bodies entered. Forged mode should still
report success with neither body entered. Restore `999` before the next comparison.

## 2. Keep the assertions outside the library's Python process

The second script runs the same two comparisons, but its parent process never
imports `toy_library`. Instead, each `remote_add` call starts a worker process:

1. The parent sends two numbers as JSON.
2. The worker imports and configures the toy library, then calls `add`.
3. The worker returns JSON containing the answer.
4. The parent checks the message shape and performs the assertion itself.

The worker's success exit status only indicates command completion. It does not
decide whether the answer is correct. The parent accepts a single integer value,
not a worker-supplied test verdict or executable Python object.

```sh
python3 -B 02_separate_assertions.py original
python3 -B 02_separate_assertions.py forged
python3 -B 02_separate_assertions.py wrong
```

| Worker mode | Bodies entered in parent | Parent reports | Process exit status |
| --- | ---: | --- | ---: |
| `original` | 2 | One deliberate failure | 1 |
| `forged` | 2 | One deliberate failure | 1 |
| `wrong` | 2 | Two failures | 1 |

All modes should also print `Parent runner unchanged: True` and
`Parent imported toy_library: False`. In forged mode, the worker changes its own
copy of `unittest.TestCase.run`. The parent's copy remains unaffected, so the
deliberately false assertion still fails.

**Try changing it:** change `999` to `5` in this script. Original and forged modes
should both pass, with both bodies executed. Wrong mode should fail both tests.
The forgery's correct answers can satisfy honest tests; its runner replacement
cannot control the parent's result. Detecting prohibited source changes is a
separate concern.

**Limit:** these are ordinary subprocesses, not restricted containers or security
sandboxes. The worker retains ordinary user permissions to files and other
resources. This example demonstrates resistance to the particular Python-memory
mutation in example 1, not protection against arbitrary hostile code. It also
handles only integer addition, not the rich interfaces required by our real pairs.

## 3. Lie about elapsed time

Both child processes sleep for 0.25 seconds and return `4`. The tampered child
first replaces its own `time.perf_counter` with a function that always returns
zero. The parent uses its own clock around each subprocess invocation.

```sh
python3 -B 03_fake_timer.py
```

The honest child should report at least approximately 0.25 seconds. The tampered
child should report exactly zero. The parent should measure at least 0.25 seconds
for both. The script checks these properties and exits 0 when they hold; exact
durations depend on your machine.

**Try changing it:** increase `DELAY` to `1.0`. The parent should observe the longer
wait while the tampered child still reports zero.

The parent's interval includes interpreter startup and communication. This
demonstrates why an untrusted timing report cannot determine the performance
score; it is not a finished benchmark or a measurement of library-only time.
The child remains an ordinary subprocess, with the same isolation limits as
example 2.

## 4. Break correct behavior while trying to transport results

The last script starts with a dictionary whose `left` and `right` entries point
to the same list. It compares that original structure with a JSON round trip:
`json.loads(json.dumps(...))`.

```sh
python3 -B 04_json_changes_objects.py
```

Expected observations:

1. The original and copied structures initially compare equal.
2. In the original, `left is right` is true. After JSON copying, it is false.
3. Appending `3` through `left` changes the original's `right` to `[1, 2, 3]`.
   The copied structure's `right` remains `[1, 2]`.
4. A Python list can contain a reference to itself. JSON serialization rejects
   that circular structure with a `ValueError`, which the script catches and prints.

The script's checks should pass and it should exit 0. No worker is needed to
demonstrate this problem: the copying step itself loses the shared references.

**Try changing it:** print the JSON string inside `main`. It contains the two
lists' values, but nothing expressing that they originally identified one list.

This explains a remaining Phase 2 issue. Separating assertions from library code
can prevent one kind of tampering while an inadequate adapter changes legitimate
behavior. We need both trustworthy assertions and faithful execution.

## Connection to the recorded research

These examples simplify [F-01 and F-02](../reward-hacking-findings.md#f-01-a-library-can-make-repository-tests-report-success-without-running-their-assertions),
[F-04](../reward-hacking-findings.md#f-04-a-candidate-can-replace-an-in-process-clock),
and [F-13](../reward-hacking-findings.md#f-13-the-yaml-adapter-loses-shared-and-recursive-values).
The original experiments include additional controls and limitations described
there. These teaching files do not replace their evidence or resolve the full
protection problem in [Phase 2](../execution-plan.md#phase-2-prove-execution-and-isolation-feasibility).
