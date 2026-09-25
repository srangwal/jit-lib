# Repository Guidelines

## Project Structure & Module Organization

- `documentation/`: project goal, evaluator design, and experiment notes.
- `docs/`: optimizer responsibilities, proposed controller, and overall workflow.
- `workloads/books/`: upstream book checkouts; `README.md` records their sources and exact revisions.
- `evaluator/`: Python evaluator, Rust indexing helper, pinned inputs, and correctness fixtures.
- `evaluator/tests/`: Python unit tests; `.evaluator/` holds ignored builds and run evidence.
- `auditor/`: Codex audit controller, evidence packaging, isolated book probes, and tests; `.auditor/` holds ignored audit evidence.
- `optimizer/`: one Codex specialization attempt, protected baseline context, candidate export, and tests; `.optimizer/` holds ignored attempts.
- `scripts/`: cold-setup reproduction and portable report excerpts.
- `rust-toolchain.toml`: pinned Rust version; `evaluator/environment.json` records tested tools.

Update this guide when source modules, tests, or assets are introduced. Describe only directories and behavior verified in the repository.

## Build, Test, and Development Commands

Run commands from the repository root. Start with `python3 evaluator/environment.py`, then
`python3 evaluator/setup_books.py`. See the root README for the complete setup path.
Use `python3 scripts/reproduce.py` to verify fresh books/caches, tests, evaluation, and auditing.

Run `python3 -m unittest discover -s evaluator/tests -v` for evaluator unit tests.
Run `python3 -m unittest discover -s auditor/tests -v` for auditor tests. Audit with `python3 auditor/run.py --evaluation .evaluator/runs/<run-id>`; see `auditor/README.md`.
Run `python3 evaluator/run.py self-check` to validate original versus original. Evaluate a modified library with `python3 evaluator/run.py run --candidate /path/to/elasticlunr-rs`. See `evaluator/README.md` for details.
Run `python3 -m unittest discover -s optimizer/tests -v` for optimizer tests.
Run `python3 optimizer/run.py --baseline .evaluator/runs/<validated-self-check>` for one optimizer attempt; see `optimizer/README.md`. The full experiment controller remains unimplemented.

## Coding Style & Naming Conventions

Use four-space Python indentation and snake_case functions; follow the Rust helper's existing style. Keep modules simple and avoid unrelated refactoring. Use descriptive Markdown headings and short explanations. No repository-wide formatter or linter configuration is present.

## Testing Guidelines

Name Python tests `test_*.py` and use `unittest`. Test meaningful failures: changed/missing outputs, incorrect dependency resolution, and invalid measurements. Run checks appropriate to the change and report exactly what ran. Full evaluation also runs upstream application/library tests. No coverage percentage is required. For documentation changes, verify referenced paths and commands.

Label planted violations as auditor-validation cases. They do not demonstrate reward hacking in independently developed candidates or establish a speedup.

## Commit & Pull Request Guidelines

Existing commits use concise imperative subjects. Keep changes scoped to the requested work.

PR descriptions use `## Summary` with `### What`, `### Why`, and optional `### Implications`; add `## Implementation` only when useful and `## Testing Done` with concrete verification bullets. Keep file paths out of summary paragraphs.

## Agent Instructions

Preserve existing worktree changes. Obtain explicit approval before commits, amendments, pushes, destructive Git operations, or PR comments. Clarify ambiguous requirements before implementation. Confirm code and architecture claims by reading the relevant source. Do not add features or behavior beyond the agreed scope.
