# Evaluator

The evaluator compares mdBook using the original elasticlunr-rs library with mdBook using the modified library. Correctness should match; performance should improve. The implementation and commands are in [`evaluator/README.md`](../evaluator/README.md).

Keep the mdBook version, book contents, configuration, build settings, and machine the same. Only the library changes.

## Correctness checks

Build the same books with both versions and require identical generated files, including the search index. Check both the set of files and their contents.

Use small test books to cover unusual cases, such as Unicode, empty content, repeated words, and disabled search. Also compare the outputs of the real books used for performance evaluation.

Run the existing application and library tests alongside these comparisons.

## Performance evaluation

Measure two things:

- **Complete book-build time:** does mdBook finish building the book faster?
- **Search-index time:** does constructing, filling, serializing, and cleaning up the index become faster? Replay actual indexing inputs with mdBook's callbacks. Exclude trace loading and final file writes; those writes remain part of complete book-build time.

Use representative real books and already-compiled release builds. Repeat comparisons under comparable conditions to distinguish improvement from normal timing variation. Compilation is outside the measured book-build time.

Only consider performance results from versions that pass the correctness checks. Use the ten pinned books, two warmups, and ten paired timing blocks with alternating execution order.

Any improvement larger than measurement noise is worthwhile; there is no fixed percentage target. Require the paired-bootstrap 95% speedup interval to be above 1 for both metrics. The suite verdict uses equal weights across books; report each book separately so individual regressions remain visible. Record any workload or repetition overrides before a run.

## Validate the evaluator

Before evaluating a modified library:

- Compare the original against itself to confirm matching outputs and establish normal timing variation.
- Deliberately change or remove a generated file and confirm that the correctness checker rejects the result.

Accept an improvement only when correctness checks pass and repeated measurements establish faster book builds and faster indexing work.
