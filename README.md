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
reproducing tests. No library speedup has been demonstrated yet.

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
python3 evaluator/run.py self-check
```

This compares the original library against itself. The first run downloads
dependencies and compiles several copies, so allow substantial time and disk
space. The command prints the location of `report.md` and `report.json`.
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

After the full ten-book self-check reports `validated`:

```sh
python3 controller/run.py --baseline .evaluator/runs/<self-check-run-id>
```

The controller allows five optimizer attempts, each with up to ten minutes of
agent time. It evaluates and audits every submitted candidate, sends the results
back as feedback, and stops at the first qualifying candidate. Evaluation and
auditing take additional time. Every attempt receives the complete history and supplied workload. In one
agent session, it can choose any earlier candidate, combine ideas, or restart
from the original. Runner checkpoints retain those decisions and parent links.
New book contents and supported configurations must still work.

Open the printed `.controller/.../report.md` to follow requests, measured
improvements and uncertainty, audit findings, and decisions. The output includes
raw logs and linked JSON records. A stale baseline triggers a fresh self-check.
Use `--optimizer-agent` and `--auditor-agent` to choose their runtimes independently.
See [controller instructions](controller/README.md) for examples, limits, failure handling,
and the [overall workflow](docs/WORKFLOW.md).

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
