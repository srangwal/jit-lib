# Evaluation books

Ten public mdBook projects for the mdBook / elasticlunr-rs evaluator. These are pinned source checkouts. The [evaluator](../../evaluator/README.md) prepares copies, checks generated output, and measures performance without modifying these repositories.

Checked out on 2026-09-24 (UTC). The first three retain their previously recorded revisions; the other seven use the upstream HEAD resolved during checkout. Every checkout is detached at the exact revision below.

## Sources and revisions

| Book | Checkout | Book root | Upstream | Exact revision |
| --- | --- | --- | --- | --- |
| Rust By Example | `rust-by-example/` | [rust-by-example/](rust-by-example/) | [rust-lang/rust-by-example](https://github.com/rust-lang/rust-by-example) | `af5ef7024e88587aa3be244422f6365e86c50e85` |
| Rustonomicon | `rustonomicon/` | [rustonomicon/](rustonomicon/) | [rust-lang/nomicon](https://github.com/rust-lang/nomicon) | `5791ca9f5d671328af7a8fe87b42ca90c7211d28` |
| Embedded Rust Book | `embedded-rust/` | [embedded-rust/](embedded-rust/) | [rust-embedded/book](https://github.com/rust-embedded/book) | `0789b0f29e73ecb91213cac10ad0eec1b9333770` |
| The Rust Programming Language | `rust-book/` | [rust-book/](rust-book/) | [rust-lang/book](https://github.com/rust-lang/book) | `1500248d8f230566e4ec9f27fcbb8fe9e2898ab1` |
| Rust Reference | `rust-reference/` | [rust-reference/](rust-reference/) | [rust-lang/reference](https://github.com/rust-lang/reference) | `52ffdc09065e0043e877546da923c01bf875d41d` |
| Command Line Applications in Rust | `rust-cli/` | [rust-cli/](rust-cli/) | [rust-cli/book](https://github.com/rust-cli/book) | `8a865bfe754eef5ff7a39bfc2f57a8e95d591798` |
| Rust and WebAssembly | `rust-wasm/` | [rust-wasm/](rust-wasm/) | [rustwasm/book](https://github.com/rustwasm/book) | `fd0e80576e334ead48481e855312729430227648` |
| mdBook Guide | `mdbook-guide/` | [mdbook-guide/guide/](mdbook-guide/guide/) | [rust-lang/mdBook](https://github.com/rust-lang/mdBook) | `ea1b91d0ea1fa2d62e4c1faeeffd910ce19306fd` |
| Helix Documentation | `helix/` | [helix/book/](helix/book/) | [helix-editor/helix](https://github.com/helix-editor/helix) | `079a789e8cb08ead67f19e1971a1b7438b37354b` |
| Rust Cookbook | `rust-cookbook/` | [rust-cookbook/](rust-cookbook/) | [rust-lang-nursery/rust-cookbook](https://github.com/rust-lang-nursery/rust-cookbook) | `1837612e1b8c78ecc67124cffac76ce5d2f34f97` |

## Local checkout layout

Each directory is an independent, shallow Git checkout with its upstream `origin`. The local `.gitignore` keeps these nested repositories out of parent-repository staging. This README records how to acquire the same sources again.

The mdBook Guide and Helix book live inside larger repositories (`guide/` and `book/`, respectively). Their complete repositories are retained so repository-local helpers and referenced files remain available.

The Rust and WebAssembly repository is archived. Preserve upstream licenses and book configuration. No development/final-evaluation split is assigned by this inventory.

## Set up all books

From the repository root, with Git installed and network access:

```sh
python3 evaluator/setup_books.py
```

The command reads the exact revisions in `evaluator/books.json`. It fetches new
checkouts into temporary directories and installs them only after verification.
Rerunning verifies existing checkout roots, revisions, origins, and clean status;
it never updates or overwrites an existing checkout. A mismatch stops setup with
a clear error. For an isolated destination, pass `--destination /absolute/path/to/books`.
Symlink destinations are rejected.

## Recreate one checkout manually

From `workloads/books/`, substitute a row’s checkout directory, upstream URL, and exact revision below. Use an absent destination directory.

```sh
git init <directory>
git -C <directory> remote add origin https://github.com/<owner>/<repository>.git
git -C <directory> fetch --depth 1 --no-tags origin <revision>
git -C <directory> checkout --detach FETCH_HEAD
```

Generated book output and build artifacts should be stored outside these source checkouts. Building books, installing preprocessors, running tests, and measuring performance are separate setup steps.
