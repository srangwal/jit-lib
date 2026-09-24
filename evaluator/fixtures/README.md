# Evaluator correctness fixtures

- `edge-cases/`: repeated/disjoint title and body words, nested breadcrumbs,
  Unicode, apostrophes and backslashes, hyphens, long tokens, an empty chapter,
  and a chapter that renders but is excluded from search.
- `json-index/`: `copy-js = false` plus nondefault result limits, boosts,
  Boolean matching, expansion, and heading splitting. In mdBook 0.5.4 this
  still constructs and serializes the index internally but emits no search
  index file. The capture/replay helper checks that internal JSON.
- `search-disabled/`: `enable = false`; no indexing or search assets.

These are correctness inputs, not representative performance workloads.
Build into an external directory so generated output never enters these inputs.
