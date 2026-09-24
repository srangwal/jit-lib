//! Replay raw mdBook 0.5.4 search documents against a selected elasticlunr-rs.
use elasticlunr::{Index, IndexBuilder, config::SearchOptions};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::{error::Error, fs, sync::LazyLock, time::Instant};

static WHITESPACE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s\s+").unwrap());

#[derive(Clone, Deserialize, Serialize)]
struct ResultsOptions {
    limit_results: u32,
    teaser_word_count: u32,
}

#[derive(Deserialize)]
struct Trace {
    copy_js: bool,
    documents: Vec<[String; 3]>,
    doc_urls: Vec<String>,
    results_options: ResultsOptions,
    search_options: SearchOptions,
}

#[derive(Serialize)]
struct SearchindexJson {
    results_options: ResultsOptions,
    search_options: SearchOptions,
    doc_urls: Vec<String>,
    index: Index,
}

fn tokenize(text: &str) -> Vec<String> {
    text.split(|c: char| c.is_whitespace() || c == '-')
        .filter(|s| !s.is_empty())
        .map(|s| s.trim().to_lowercase())
        .filter(|s| s.len() <= 80)
        .collect()
}

fn replay(trace: &Trace) -> Result<String, serde_json::Error> {
    let mut index = IndexBuilder::new()
        .add_field_with_tokenizer("title", Box::new(&tokenize))
        .add_field_with_tokenizer("body", Box::new(&tokenize))
        .add_field_with_tokenizer("breadcrumbs", Box::new(&tokenize))
        .build();
    for (id, fields) in trace.documents.iter().enumerate() {
        let items = fields
            .iter()
            .map(|text| WHITESPACE.replace_all(text.trim(), " "));
        index.add_doc(&id.to_string(), items);
    }
    let contents = SearchindexJson {
        results_options: trace.results_options.clone(),
        search_options: trace.search_options.clone(),
        doc_urls: trace.doc_urls.clone(),
        index,
    };
    // Match mdBook's stable key ordering and JavaScript escaping exactly.
    let value = serde_json::to_value(&contents)?;
    let json = serde_json::to_string(&value)?;
    let output = if trace.copy_js {
        format!(
            "window.search = Object.assign(window.search, JSON.parse('{}'));",
            json.replace("\\", "\\\\").replace("'", "\\'")
        )
    } else {
        json.clone()
    };
    // Destruction of the library index and intermediate JSON is timed too.
    drop(contents);
    drop(value);
    drop(json);
    Ok(output)
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: index-replay TRACE.json OUTPUT.js".into());
    }
    let trace: Trace = serde_json::from_slice(&fs::read(&args[1])?)?;
    if trace.documents.len() != trace.doc_urls.len() {
        return Err("trace document and URL counts differ".into());
    }
    let start = Instant::now();
    let output = replay(&trace)?;
    let elapsed = start.elapsed().as_secs_f64();
    fs::write(&args[2], &output)?;
    println!(
        "{}",
        serde_json::json!({
            "elapsed_seconds": elapsed,
            "documents": trace.documents.len(),
            "output_bytes": output.len(),
        })
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mdbook_tokenizer_filters_by_utf8_length_and_splits_hyphens() {
        let input = format!("Café-WORLD\t{} {}", "é".repeat(40), "é".repeat(41));
        assert_eq!(tokenize(&input), vec!["café", "world", &"é".repeat(40)]);
    }

    #[test]
    fn whitespace_keeps_single_newlines_but_collapses_runs() {
        assert_eq!(
            WHITESPACE.replace_all("one\ntwo\n\tthree", " "),
            "one\ntwo three"
        );
    }

    #[test]
    fn replay_preserves_raw_fields_urls_and_consecutive_ids() {
        let trace: Trace = serde_json::from_value(serde_json::json!({
            "copy_js": false,
            "documents": [["  Café  ", "one\ntwo\n\tthree's \\", "Parent » Child"],
                          ["Second", "unrelated", "Other"]],
            "doc_urls": ["chapter.html#café", "second.html"],
            "results_options": {"limit_results": 30, "teaser_word_count": 20},
            "search_options": {"bool": "AND", "expand": true, "fields": {}}
        }))
        .unwrap();
        let serialized = replay(&trace).unwrap();
        // mdBook's dependency graph enables serde_json/preserve_order through
        // handlebars. Sorting these keys changes the emitted bytes.
        assert!(serialized.starts_with("{\"results_options\":{\"limit_results\":30,"));
        let output: serde_json::Value = serde_json::from_str(&serialized).unwrap();
        assert_eq!(
            output["index"]["documentStore"]["docs"]["0"]["title"],
            "Café"
        );
        assert_eq!(
            output["index"]["documentStore"]["docs"]["0"]["body"],
            "one\ntwo three's \\"
        );
        assert_eq!(
            output["index"]["documentStore"]["docs"]["1"]["breadcrumbs"],
            "Other"
        );
        assert_eq!(output["doc_urls"][0], "chapter.html#café");
        assert_eq!(output["search_options"]["bool"], "AND");
        let wrapped = replay(&Trace {
            copy_js: true,
            ..trace
        })
        .unwrap();
        assert!(wrapped.starts_with("window.search = Object.assign(window.search, JSON.parse('"));
        assert!(wrapped.contains("three\\'s \\\\\\\\"));
    }
}
