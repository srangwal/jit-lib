# Search-index replay

This helper reproduces the indexing operations in mdBook 0.5.4's
`crates/mdbook-html/src/html_handlebars/search.rs`. It builds against the selected
elasticlunr-rs source; it does not modify that library.

The evaluator makes a separate, instrumented mdBook source copy with
`capture_index.instrument()`. Setting `JIT_LIB_INDEX_TRACE` to an absolute output
path captures the raw three-field documents before whitespace normalization,
document URLs, search settings, and expected serialized output. The patch rejects
any search source whose SHA-256 differs from the inspected mdBook 0.5.4 file.
The evaluator must verify that capture leaves generated book files unchanged.
Search-disabled builds produce no trace.

`capture_index.prepare_replay(destination, library, lockfile_source)` creates a
standalone Cargo project with a local library dependency, pinned direct
dependencies, and a copy of mdBook's lockfile. Build that project, retaining its
resulting lockfile.

The helper enables `serde_json/preserve_order` and `raw_value`, as mdBook's
dependency graph does through handlebars and axum. In particular, insertion
order must be preserved to match the emitted JSON bytes.

Then invoke:

```text
index-replay TRACE.json OUTPUT
```

The output is the exact `searchindex.js` wrapper when `copy_js` is enabled, or the
serialized index JSON otherwise. Compare bytes with the trace's `expected_output`
and, when present, the generated book's search-index asset. The normal application
correctness check remains separate.

The helper prints JSON containing `elapsed_seconds`, `documents`, and
`output_bytes`. Its timer includes index construction, mdBook's custom tokenizer
and whitespace callback, adding documents, conversion through `serde_json::Value`,
serialization, optional JavaScript escaping, and destruction of the index and
intermediate values. It excludes loading/parsing the trace, writing the output,
and destruction of the final output buffer. Each invocation includes cold regex
initialization, just as a fresh mdBook process does.

This measures the **search-index lifecycle with mdBook callbacks**, not exclusive
library CPU time. Markdown parsing and chapter traversal are not replayed. The
elapsed time is reported inside the helper and is suitable for supervised
evaluation; it is not protected against deliberately dishonest candidate code.
