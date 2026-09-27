# Execution environment

The complete evaluator-and-auditor workflow currently supports macOS. It was
checked on macOS 26.6.2, Apple silicon (`aarch64-apple-darwin`). The auditor
requires `/usr/bin/sandbox-exec`; it stops if that isolation tool is unavailable.
Linux and Windows require another isolation implementation and testing.

## Versions

| Tool | Tested version | Requirement |
| --- | --- | --- |
| Python | 3.14.7 | 3.11+; standard library only |
| Rust / Cargo | 1.95.0 / 1.95.0 | Exact Rust toolchain, installed through rustup |
| Node.js | 26.9.0 | 24+ |
| npm | 11.19.1 | Use the tested version for reproduction |
| Chrome | 153.0.8010.53 | Installed Chrome/Chromium executable |
| Codex CLI | 0.156.1 | This version is the documented setup target |

`rust-toolchain.toml` pins Rust. `evaluator/environment.json` records the tested
versions. The Node requirement covers the engines required by the committed npm
lockfile. Browser and other version differences are recorded; they are not proof
that an untested combination works.

Run `python3 evaluator/environment.py` before downloading or building. It checks
versions, rustup proxies, browser availability, Codex flags/login, and the macOS
probe prerequisite. It does not make an AI request or prove model access.
Install instructions are in the [root README](../README.md).

## Build settings and evidence

The evaluator selects Rust 1.95.0 explicitly, including for books with their own
toolchain files. It sets `TZ=UTC` and `CARGO_INCREMENTAL=0`. Application and replay
binaries use Cargo's release profile; upstream tests use their normal test
profile. Commands and source manifests retain the precise build arguments and
package profile settings.

Inherited `MDBOOK_*`, `CARGO_TARGET_DIR`, `JIT_LIB_INDEX_TRACE`, and
`CARGO_NET_OFFLINE` settings are removed before setup. Overrides that select another compiler or relocate Cargo targets are rejected
with a setup error, including equivalent `[build]` Cargo configuration. Prepared book
preprocessors run offline after their dependencies have been downloaded.

Each report records tool versions, the browser path, the Rust pin file hash,
and relevant compiler/profile environment overrides. Each command also records
its effective overrides and hashes of applicable Cargo config files. Config
contents are not copied because they can contain credentials. For comparable
runs, use the same flags and Cargo configuration; hashes identify configuration
but cannot recreate a missing file. Compiler defaults come from the pinned
compiler and preserved package manifests.

Use `--cargo-home PATH` to select a dependency cache. `scripts/reproduce.py`
uses empty Cargo and npm caches, fresh books, and new build/output directories.
It shares installed tools, the OS, browser, and your Codex login. This verifies
clean setup on the tested Mac, not installation on an untouched computer.

## Auditor settings

`auditor/config.json` selects `gpt-6-sol`, medium reasoning, three rounds,
600 seconds per agent round, and 30 seconds per probe build. Reports record the
effective values, Codex CLI version, and a fingerprint and snapshot of the audit
code, prompt, schema, and configuration. These are explicit
[Codex configuration settings](https://developers.openai.com/codex/config-reference).
AI responses may differ even with the same recorded settings. Neither a matching
configuration nor a clean audit proves the absence of all reward hacking.
