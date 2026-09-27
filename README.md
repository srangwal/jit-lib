# jit-lib

We want to answer one question: Can an AI agent make an application faster by tailoring one of its libraries specifically for that application?

A general-purpose library handles many situations. A particular application may only need some of them. If we can establish what the application actually requires, we may be able to simplify the library’s work without changing the application’s behavior.

The intended result is a replacement library that:

- Works through the application’s existing interface.
- Preserves all supported behavior, including errors and uncommon inputs.
- Reduces library work time by the configured target, while reporting complete application time separately.
- Comes with tests and instructions that let someone independently verify the improvement.

## Start here (macOS)

The first experiment uses **mdBook + elasticlunr-rs**. The evaluator checks
matching output and measures speed; the auditor investigates shortcuts and adds
reproducing tests. The controller joins these components into a complete
optimization experiment. To run it yourself, complete steps 1–4 below, then
go to [Run the complete optimization loop](#run-the-complete-optimization-loop).
Steps 5–6 are for evaluating and auditing a candidate manually.

Run the commands below from the repository root. The complete path currently
supports **macOS with `sandbox-exec`**. Linux and Windows need a different auditor
isolation implementation and platform testing.

### 1. Install the tools

Install Apple's command-line tools (`xcode-select --install`),
[Python](https://www.python.org/downloads/) 3.11+,
[Node.js](https://nodejs.org/en/download) 24+,
[Chrome](https://www.google.com/chrome/), and Rust through
[rustup](https://rustup.rs/). Python needs no extra packages.

If you have not cloned the repository yet:

```sh
git clone https://github.com/srangwal/jit-lib.git
cd jit-lib
```

Then run from its root:

```sh
rustup toolchain install 1.95.0 --profile minimal
npm install -g @openai/codex@0.156.1
codex login
python3 evaluator/environment.py
```

The last command checks the prerequisites and prints installed versions. Chrome
is detected at its standard macOS location. For another installation, set:

```sh
export PUPPETEER_EXECUTABLE_PATH="/path/to/chrome-or-chromium"
```

Tested versions and environment recording are described in
[the environment guide](documentation/ENVIRONMENT.md). Codex access to
`gpt-6-sol` is required for the default audit; model calls use your account. For Claude Code or a local OpenCode model, see
[coding-agent setup](coding_agents/README.md). The environment checker and cold-setup
reproduction command below currently check and use the default Codex setup.

### 2. Download the ten books

```sh
python3 evaluator/setup_books.py
```

This fetches the revisions in `evaluator/books.json`. Running it again checks
existing copies. If a copy has local changes or a different revision, setup stops
and leaves it untouched.

### 3. Run the unit tests

```sh
python3 -m unittest discover -s evaluator/tests -v
python3 -m unittest discover -s auditor/tests -v
python3 -m unittest discover -s optimizer/tests -v
python3 -m unittest discover -s controller/tests -v
python3 -m unittest discover -s coding_agents/tests -v
```

### 4. Check the evaluator

```sh
python3 evaluator/run.py self-check --output .evaluator/runs/my-baseline
```

This compares the original library against itself. The first run downloads
dependencies and compiles several copies, so allow substantial time and disk
space. The command prints the location of `report.md` and `report.json`.
Use a new output directory; existing evidence is never overwritten. If you
already have a full ten-book self-check with status `validated`, you can use its
directory instead of `my-baseline` in the controller command below.

Expected status: `validated`. Both aggregate measured time differences must be
within ±5% of original time, inclusive. Confidence intervals are reported but do
not decide this self-check. A `calibration-warning` means a difference exceeds
that tolerance and needs investigation; do not keep rerunning to obtain a
favorable result. Candidate evaluation still requires the lower 95% confidence
bound for library time reduction to meet the target (default 20%).

### 5. Create and evaluate a candidate

Create a separate checkout at the exact library revision:

```sh
mkdir -p .evaluator/candidates
git clone https://github.com/mattico/elasticlunr-rs.git .evaluator/candidates/elasticlunr-rs
git -C .evaluator/candidates/elasticlunr-rs checkout --detach 057ead48ddcefef0be1d34d19339cdd091053267
```

Edit that library, then run:

```sh
python3 evaluator/run.py run --candidate .evaluator/candidates/elasticlunr-rs
```

An unchanged candidate is also a useful first trial. A real improvement must
pass correctness and meet the library time-reduction target at the lower end of
the 95% confidence interval. The default target is 20%; application timing is
reported separately and does not block library success. A controller result also
requires a completed audit with no unresolved issue.
See [evaluator details](evaluator/README.md) for verdicts and timing boundaries.

### 6. Audit the result

Use the run directory printed by either evaluator command:

```sh
python3 auditor/run.py --evaluation .evaluator/runs/<run-id>
```

Open the printed `.auditor/.../report.md`. It explains findings, reproduced
failures, and any checks added. `no-issue-found` means no violation was found
within that investigation, not a guarantee. This command runs one standalone audit.
See [auditor details](auditor/README.md).

## Let the optimizer propose a candidate

After a self-check reports `validated`, run one AI optimization attempt:

```sh
python3 optimizer/run.py --baseline .evaluator/runs/<self-check-run-id>
```

It defaults to Codex CLI with `gpt-6-sol` and a 10-minute agent limit.
Both optimizer and auditor also accept `--agent claude` or `--agent opencode`;
OpenCode requires a locally hosted model. Open the printed
report to see its explanation and any candidate. Local builds, correctness tests, profiling, and diagnostic benchmarks are allowed;
official evaluation remains a separate command.
See [optimizer instructions](optimizer/README.md) for outputs and options.

## Run the complete optimization loop

### Start the experiment

Complete setup steps 1–4 first. You do **not** need to create a candidate or run
the optimizer, evaluator, and auditor separately: the controller does that for you.
From the repository root, run:

```sh
python3 controller/run.py \
  --baseline .evaluator/runs/my-baseline \
  --output .controller/experiments/my-first-experiment \
  --optimizer-agent codex --optimizer-model gpt-6-sol \
  --auditor-agent codex --auditor-model gpt-6-sol \
  --attempts 5 --optimizer-timeout 600 \
  --library-reduction-target-percent 20
```

Replace the baseline path if you used a different self-check directory. Choose a
new experiment directory for each run; existing results are never overwritten.
A stale baseline triggers a fresh self-check before optimization.

To use OpenCode with `qwen3.8:27b-mlx-32k` and two hours per optimizer attempt
and auditor agent call, see the [local-model command](controller/README.md).
That command also increases the whole-audit limit to cover up to three calls.

Set `--library-reduction-target-percent` to your required time reduction for this
experiment, for example `30` for 30%. If omitted, it uses
`library_reduction_target_percent` in `evaluator/config.json` (currently 20).
The controller passes that value to both the evaluator and the optimizer; the
optimizer reads it from `context/objective.json`, also included in its saved
`agent/prompt.md`. The prompt template does not hard-code a percentage. The
threshold stays fixed throughout the experiment.

This command uses your Codex account for both agents. It runs at least three
optimizer attempts, each with ten minutes of agent time. After attempt three,
it selects the best qualifying candidate from any attempt. If none qualifies,
it continues until one qualifies or five attempts are used. `--attempts` sets
the maximum and accepts 3, 4, or 5. A no-change response still uses an attempt;
failures or cancellation can stop the experiment before three attempts.
Builds, evaluation, and auditing take additional time, so
this is **not a 50-minute limit for the whole experiment**. Keep the Mac awake,
avoid other heavy work, and do not edit project files or run another evaluation
while it is measuring performance.

Each attempt receives the full prepared workload and all earlier attempts and
results from this experiment. The optimizer may start from the original or any
earlier candidate and combine ideas. It changes only library code; new book
contents and supported application configurations must still work. Every
submitted candidate is evaluated and audited.

The optimizer also receives a **stretch target** for each attempt:
`max(acceptance threshold, min(95%, 1.5 × best previous measured reduction))`.
With no eligible previous candidate, it uses the acceptance threshold. A 19%
measured reduction raises a 20% initial target to 28.5%. Only independent results
with passed correctness, a clean audit, and current checks guide this target.
The 95% ceiling never lowers a higher acceptance threshold. Both targets measure
time saved relative to the original library. The stretch target encourages
ambition; missing it does not disqualify a candidate.

A candidate qualifies when correctness passes, the **lower end of the 95%
confidence interval for aggregate library time reduction is at least 20%**, and
the audit finds no unresolved issue. Application timings and individual-book
regressions are reported separately; they do not block library success. Audit
`no-issue-found` means no violation was detected within that investigation, not
proof that none exists.

Among qualifying candidates, selection uses the highest lower confidence bound;
an exact tie favors the earlier attempt. New auditor checks trigger a fresh
self-check and reevaluation of the current candidate and earlier candidates
with clean audits before they can guide or win the experiment. Existing audits
remain attached to their frozen source; reevaluation does not clear a violation.

### Follow progress

The terminal prints when each component starts and finishes. Long builds or
agent investigations can be quiet between these messages. In a second terminal,
from the repository root, follow the event log:

```sh
tail -f .controller/experiments/my-first-experiment/events.jsonl
```

Press `Ctrl-C` in this second terminal to stop watching; the experiment continues
in the first terminal. For a readable timeline, open
`.controller/experiments/my-first-experiment/report.md` in your editor and reload
it as the run progresses.

Each component-start message names its live log. For example, once the first
optimizer attempt has started:

```sh
tail -f .controller/experiments/my-first-experiment/steps/attempt-001-optimize/stdout.log
```

Within that step, `stderr.log` contains errors, `output/progress.jsonl` records
detailed progress, and `output/agent/` holds the agent prompt and traces.

### Read the result

Start with these files under `.controller/experiments/my-first-experiment/`:

| Path | What to look for |
| --- | --- |
| `report.md` | Timeline, decisions, and links to evidence. |
| `summary.json` | Final status and, on success, references to the selected candidate, evaluation, and audit. |
| `selection.json` | Winning candidate and the lower confidence bounds used to rank qualifying candidates. |
| `tasks/attempt-001-stretch-target.json` | Acceptance threshold, stretch calculation, and earlier evidence used for attempt 1; later attempts have their own records. |
| `feedback/` | Library/application time reductions, confidence intervals, per-book regressions, and audit feedback. |
| `steps/attempt-001-evaluate/output/report.md` | Full evaluation report for attempt 1; change the number for later attempts. |
| `steps/attempt-001-audit/output/report.md` | Audit findings and checks for that attempt. |
| `steps/attempt-001-optimize/output/` | The replacement library in `candidate/`, its `candidate.patch`, and the optimizer's explanation. |

Use the attempt identified in `summary.json` to find the selected library;
the first attempt is not necessarily the winner. Keep the whole experiment
directory together so its evidence links remain usable. These generated files
are ignored by Git.

Final statuses:

- **`qualified`** (exit 0): a candidate met the success criteria.
- **`no-qualifying-improvement`** (exit 2): the attempt budget ended without success.
- **`incomplete`** (exit 1): a component or prerequisite failed; inspect the report
  and the failed step's logs before deciding on a fix and another run.
- **`cancelled`** (exit 130): interrupted with `Ctrl-C` in the experiment terminal;
  the evidence is retained.

Stopped experiments do not automatically resume. After resolving a failure,
start a new experiment with a new output directory. If a self-check reports a
calibration warning, investigate it rather than repeatedly retrying for a pass.

See [controller instructions](controller/README.md) for other agents and limits,
and the [overall workflow](docs/WORKFLOW.md) for the design.

## Reproduce the complete demonstration

After installing the tools, one command runs setup, tests, the full evaluator
self-check, a baseline audit, and the deliberately faulty and harmless auditor
validation cases:

```sh
python3 scripts/reproduce.py
```

It uses a separate source copy, fresh book checkouts, and empty Cargo/npm caches.
Your installed tools, browser, and Codex login are shared. It prints a directory
containing progress logs and `summary.json`; all reports remain there. This is a
cold setup check on your machine, not an automated OS installation.

[Small example reports](documentation/examples/README.md) show what to expect.
[Auditor validation instructions](auditor/validation/README.md) explain how to
regenerate just those cases. Reproduction means using the same inputs and checks;
performance numbers and AI responses will vary. Builds and raw evidence stay
outside Git.

See the [verification record](documentation/REPRODUCTION.md) for what was run and its limits.
