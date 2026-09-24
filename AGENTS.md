# Repository Guidelines

## Project Structure & Module Organization

- `documentation/`: project goal, evaluator design, and experiment notes.
- `workloads/books/`: upstream book checkouts; `README.md` records their sources and exact revisions.
- `evaluator/`: Python evaluator, Rust indexing helper, pinned inputs, and correctness fixtures.
- `evaluator/tests/`: Python unit tests; `.evaluator/` holds ignored builds and run evidence.
- `AGENTS.md`: contributor and agent instructions.

Update this guide when source modules, tests, or assets are introduced. Describe only directories and behavior verified in the repository.

## Build, Test, and Development Commands

Run `python3 -m unittest discover -s evaluator/tests -v` for evaluator unit tests.
Run `python3 evaluator/run.py self-check --browser /path/to/chrome` to validate original versus original. Evaluate a modified library with `python3 evaluator/run.py run --candidate /path/to/elasticlunr-rs --browser /path/to/chrome`. See `evaluator/README.md` for dependencies, measurement boundaries, and reports.

## Coding Style & Naming Conventions

Use four-space Python indentation and snake_case functions; follow the Rust helper's existing style. Keep modules simple and avoid unrelated refactoring. Use descriptive Markdown headings and short explanations. No repository-wide formatter or linter configuration is present.

## Testing Guidelines

Name Python tests `test_*.py` and use `unittest`. Test meaningful failures: changed/missing outputs, incorrect dependency resolution, and invalid measurements. Run checks appropriate to the change and report exactly what ran. Full evaluation also runs upstream application/library tests. No coverage percentage is required. For documentation changes, verify referenced paths and commands.

## Commit & Pull Request Guidelines

Existing commits use concise imperative subjects. Keep changes scoped to the requested work.

PR descriptions use `## Summary` with `### What`, `### Why`, and optional `### Implications`; add `## Implementation` only when useful and `## Testing Done` with concrete verification bullets. Keep file paths out of summary paragraphs.

## Agent Instructions

Preserve existing worktree changes. Obtain explicit approval before commits, amendments, pushes, destructive Git operations, or PR comments. Clarify ambiguous requirements before implementation. Confirm code and architecture claims by reading the relevant source. Do not add features or behavior beyond the agreed scope.
