"""Add raw document capture to an evaluator-owned mdBook 0.5.4 source copy."""

import hashlib
import json
from pathlib import Path
import shutil

SEARCH_SHA256 = "54dd3e1d47d29b7b3c7c940f14ae7176434b3f6ae15606b0f763ad6340fd6fe7"


def prepare_replay(destination: Path, library: Path, lockfile_source: Path) -> Path:
    """Create the helper project with the same direct dependency pins as mdBook."""
    template = Path(__file__).parent / "index-replay"
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "src").mkdir()
    shutil.copy2(template / "src/main.rs", destination / "src/main.rs")
    manifest = (template / "Cargo.toml").read_text().replace(
        'elasticlunr-rs = "=3.0.2"',
        f"elasticlunr-rs = {{ path = {json.dumps(str(library.resolve()))} }}",
    )
    (destination / "Cargo.toml").write_text(manifest)
    shutil.copy2(lockfile_source, destination / "Cargo.lock")
    return destination / "Cargo.toml"


def instrument(source_copy: Path) -> None:
    """Patch the private capture build. Source checkouts must not be passed here."""
    path = source_copy / "crates/mdbook-html/src/html_handlebars/search.rs"
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != SEARCH_SHA256:
        raise ValueError("capture requires the unmodified mdBook 0.5.4 search.rs")
    source = original.decode()
    replacements = [
        (
            "const MAX_WORD_LENGTH_TO_INDEX: usize = 80;",
            """const MAX_WORD_LENGTH_TO_INDEX: usize = 80;

thread_local! {
    static JIT_LIB_DOCUMENTS: std::cell::RefCell<Vec<Vec<String>>> =
        const { std::cell::RefCell::new(Vec::new()) };
}""",
        ),
        (
            "    let mut index = IndexBuilder::new()",
            "    JIT_LIB_DOCUMENTS.with(|docs| docs.borrow_mut().clear());\n"
            "    let mut index = IndexBuilder::new()",
        ),
        (
            "    let items = items.iter().map(|&x| collapse_whitespace(x.trim()));",
            """    JIT_LIB_DOCUMENTS.with(|docs| {
        docs.borrow_mut().push(items.iter().map(|s| s.to_string()).collect());
    });
    let items = items.iter().map(|&x| collapse_whitespace(x.trim()));""",
        ),
        (
            "    let index = write_to_json(index, search_config, doc_urls)?;",
            """    let index = write_to_json(index, search_config, doc_urls)?;
    if let Some(path) = std::env::var_os("JIT_LIB_INDEX_TRACE") {
        let mut trace: serde_json::Value = serde_json::from_str(&index)?;
        trace.as_object_mut().unwrap().remove("index");
        trace["copy_js"] = serde_json::json!(search_config.copy_js);
        trace["expected_output"] = serde_json::json!(if search_config.copy_js {
            format!(
                "window.search = Object.assign(window.search, JSON.parse('{}'));",
                index.replace("\\\\", "\\\\\\\\").replace("'", "\\\\'")
            )
        } else {
            index.clone()
        });
        trace["documents"] = JIT_LIB_DOCUMENTS.with(|docs| {
            serde_json::to_value(&*docs.borrow()).unwrap()
        });
        std::fs::write(path, serde_json::to_vec(&trace)?)?;
    }""",
        ),
    ]
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError(f"unsupported or already instrumented mdBook search source: {old!r}")
        source = source.replace(old, new)
    path.write_text(source)
