use std::collections::{HashMap, HashSet};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};

use crate::config::get_env;
use crate::json::{parse_json, JsonValue};
use crate::romanizer::split_placeholders;

const PASSTHROUGH_ROMAJI_TOKENS: &[&str] = &[
    "kara", "made", "yori", "wo", "de", "ni", "no", "ga", "ha", "wa", "to", "mo", "ka", "ya", "e",
    "he",
];

fn ascii_char_idx(b: u8) -> Option<usize> {
    match b {
        b'0'..=b'9' => Some((b - b'0') as usize),
        b'A'..=b'Z' => Some(10 + (b - b'A') as usize),
        b'a'..=b'z' => Some(36 + (b - b'a') as usize),
        b'_' => Some(62),
        _ => None,
    }
}

pub fn is_ascii_run_str(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| ascii_char_idx(b).is_some())
}

#[derive(Clone)]
struct TrieNode<T> {
    children: [u32; 63],
    value: Option<T>,
}

impl<T: Clone> Default for TrieNode<T> {
    fn default() -> Self {
        Self {
            children: [0; 63],
            value: None,
        }
    }
}

pub struct DictionaryIndex {
    pub other_non_ascii: Vec<(String, String)>,
    pub hyphen_by_sig: HashMap<[u8; 3], Vec<(usize, String, String)>>,
    pub hyphen_edge: Vec<(usize, String, String)>,
    pub has_ascii_entries: bool,
    trie: Vec<TrieNode<(String, String)>>,
    passthrough_by_char: [Vec<&'static str>; 63],
    pub preedit_index: Option< Box<DictionaryIndex> >,
}

pub struct CandidateDictionaryIndex {
    pub other_non_ascii: Vec<(String, Vec<String>)>,
    pub hyphen_by_sig: HashMap<[u8; 3], Vec<(usize, String, Vec<String>)>>,
    pub hyphen_edge: Vec<(usize, String, Vec<String>)>,
    pub has_ascii_entries: bool,
    trie: Vec<TrieNode<(String, Vec<String>)>>,
    passthrough_by_char: [Vec<&'static str>; 63],
}

fn contains_katakana(s: &str) -> bool {
    s.chars().any(|ch| {
        let u = ch as u32;
        (0x30A1..=0x30F3).contains(&u) || ch == 'ー'
    })
}

impl DictionaryIndex {
    pub fn build(entries: &[(String, String)], build_preedit: bool) -> Self {
        let mut other_non_ascii = Vec::new();
        let mut hyphen_by_sig: HashMap<[u8; 3], Vec<(usize, String, String)>> = HashMap::new();
        let mut hyphen_edge = Vec::new();
        let mut trie: Vec<TrieNode<(String, String)>> = vec![TrieNode::default()];
        let mut entry_keys: HashSet<String> = HashSet::new();
        let mut has_ascii_entries = false;

        for (order_idx, (source, target)) in entries.iter().enumerate() {
            if is_ascii_run_str(source) {
                has_ascii_entries = true;
                if entry_keys.insert(source.clone()) {
                    let mut node_idx = 0usize;
                    for b in source.bytes() {
                        let c_idx = ascii_char_idx(b).unwrap();
                        let next = trie[node_idx].children[c_idx];
                        if next == 0 {
                            let new_idx = trie.len() as u32;
                            trie.push(TrieNode::default());
                            trie[node_idx].children[c_idx] = new_idx;
                            node_idx = new_idx as usize;
                        } else {
                            node_idx = next as usize;
                        }
                    }
                    trie[node_idx].value = Some((source.clone(), target.clone()));
                }
            } else if let Some(idx) = source.find('-') {
                let sb = source.as_bytes();
                if idx > 0 && idx + 1 < sb.len() {
                    let sig = [sb[idx - 1], b'-', sb[idx + 1]];
                    hyphen_by_sig.entry(sig).or_default().push((
                        order_idx,
                        source.clone(),
                        target.clone(),
                    ));
                } else {
                    hyphen_edge.push((order_idx, source.clone(), target.clone()));
                }
            } else {
                other_non_ascii.push((source.clone(), target.clone()));
            }
        }

        let mut passthrough_by_char: [Vec<&'static str>; 63] =
            std::array::from_fn(|_| Vec::new());
        for &token in PASSTHROUGH_ROMAJI_TOKENS {
            if !entry_keys.contains(token) {
                let c_idx = ascii_char_idx(token.as_bytes()[0]).unwrap();
                passthrough_by_char[c_idx].push(token);
            }
        }

        let preedit_index = if build_preedit {
            let preedit_entries: Vec<(String, String)> = entries
                .iter()
                .filter(|(_, t)| contains_katakana(t))
                .cloned()
                .collect();
            Some(Box::new(DictionaryIndex::build(&preedit_entries, false)))
        } else {
            None
        };

        Self {
            other_non_ascii,
            hyphen_by_sig,
            hyphen_edge,
            has_ascii_entries,
            trie,
            passthrough_by_char,
            preedit_index,
        }
    }
}

impl CandidateDictionaryIndex {
    pub fn build(entries: &[(String, Vec<String>)]) -> Self {
        let mut other_non_ascii = Vec::new();
        let mut hyphen_by_sig: HashMap<[u8; 3], Vec<(usize, String, Vec<String>)>> =
            HashMap::new();
        let mut hyphen_edge = Vec::new();
        let mut trie: Vec<TrieNode<(String, Vec<String>)>> = vec![TrieNode::default()];
        let mut entry_keys: HashSet<String> = HashSet::new();
        let mut has_ascii_entries = false;

        for (order_idx, (source, targets)) in entries.iter().enumerate() {
            if is_ascii_run_str(source) {
                has_ascii_entries = true;
                if entry_keys.insert(source.clone()) {
                    let mut node_idx = 0usize;
                    for b in source.bytes() {
                        let c_idx = ascii_char_idx(b).unwrap();
                        let next = trie[node_idx].children[c_idx];
                        if next == 0 {
                            let new_idx = trie.len() as u32;
                            trie.push(TrieNode::default());
                            trie[node_idx].children[c_idx] = new_idx;
                            node_idx = new_idx as usize;
                        } else {
                            node_idx = next as usize;
                        }
                    }
                    trie[node_idx].value = Some((source.clone(), targets.clone()));
                }
            } else if let Some(idx) = source.find('-') {
                let sb = source.as_bytes();
                if idx > 0 && idx + 1 < sb.len() {
                    let sig = [sb[idx - 1], b'-', sb[idx + 1]];
                    hyphen_by_sig.entry(sig).or_default().push((
                        order_idx,
                        source.clone(),
                        targets.clone(),
                    ));
                } else {
                    hyphen_edge.push((order_idx, source.clone(), targets.clone()));
                }
            } else {
                other_non_ascii.push((source.clone(), targets.clone()));
            }
        }

        let mut passthrough_by_char: [Vec<&'static str>; 63] =
            std::array::from_fn(|_| Vec::new());
        for &token in PASSTHROUGH_ROMAJI_TOKENS {
            if !entry_keys.contains(token) {
                let c_idx = ascii_char_idx(token.as_bytes()[0]).unwrap();
                passthrough_by_char[c_idx].push(token);
            }
        }

        Self {
            other_non_ascii,
            hyphen_by_sig,
            hyphen_edge,
            has_ascii_entries,
            trie,
            passthrough_by_char,
        }
    }
}

static DICT_CACHE: OnceLock<Mutex<HashMap<(String, String, String), Arc<DictionaryIndex>>>> =
    OnceLock::new();
static CAND_DICT_CACHE: OnceLock<
    Mutex<HashMap<(String, String, String), Arc<CandidateDictionaryIndex>>>,
> = OnceLock::new();

pub fn configured_dictionary_index() -> Result<Arc<DictionaryIndex>, String> {
    let inline = get_env("DICTIONARY", "");
    let path = get_env("DICTIONARY_PATH", "");
    let cwd = env::current_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();
    let key = (inline.clone(), path.clone(), cwd);

    let cache = DICT_CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(guard) = cache.lock() {
        if let Some(found) = guard.get(&key) {
            return Ok(Arc::clone(found));
        }
    }

    let mut entries = Vec::new();
    for default_path in default_dictionary_paths() {
        entries.extend(load_dictionary(&default_path.to_string_lossy())?);
    }
    if !inline.is_empty() {
        entries.extend(load_dictionary(&inline)?);
    }
    if !path.is_empty() {
        entries.extend(load_dictionary(&path)?);
    }
    let mut deduped = dedupe(entries);
    deduped.sort_by(|a, b| b.0.chars().count().cmp(&a.0.chars().count()));
    let built = Arc::new(DictionaryIndex::build(&deduped, true));

    if let Ok(mut guard) = cache.lock() {
        guard.insert(key, Arc::clone(&built));
    }
    Ok(built)
}

pub fn configured_candidate_dictionary_index() -> Result<Arc<CandidateDictionaryIndex>, String> {
    let inline = get_env("DICTIONARY", "");
    let path = get_env("DICTIONARY_PATH", "");
    let cwd = env::current_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();
    let key = (inline.clone(), path.clone(), cwd);

    let cache = CAND_DICT_CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(guard) = cache.lock() {
        if let Some(found) = guard.get(&key) {
            return Ok(Arc::clone(found));
        }
    }

    let mut entries = Vec::new();
    for default_path in default_dictionary_paths() {
        entries.extend(load_dictionary_candidates(&default_path.to_string_lossy())?);
    }
    if !inline.is_empty() {
        entries.extend(load_dictionary_candidates(&inline)?);
    }
    if !path.is_empty() {
        entries.extend(load_dictionary_candidates(&path)?);
    }
    let mut deduped = dedupe_candidate_entries(entries);
    deduped.sort_by(|a, b| b.0.chars().count().cmp(&a.0.chars().count()));
    let built = Arc::new(CandidateDictionaryIndex::build(&deduped));

    if let Ok(mut guard) = cache.lock() {
        guard.insert(key, Arc::clone(&built));
    }
    Ok(built)
}

fn expand_tilde(source: &str) -> PathBuf {
    if let Some(rest) = source.strip_prefix("~/") {
        if let Ok(home) = env::var("HOME") {
            return PathBuf::from(home).join(rest);
        }
    }
    PathBuf::from(source)
}

pub fn load_dictionary(source: &str) -> Result<Vec<(String, String)>, String> {
    if source.is_empty() {
        return Ok(Vec::new());
    }
    let path = expand_tilde(source);
    let mut entries = if path.exists() && path.is_file() {
        let text = fs::read_to_string(&path).map_err(|e| e.to_string())?;
        let suffix = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| format!(".{}", e.to_ascii_lowercase()))
            .unwrap_or_default();
        parse_dictionary_text(&text, &suffix)?
    } else {
        parse_dictionary_text(source, ".json")?
    };
    entries.sort_by(|a, b| b.0.chars().count().cmp(&a.0.chars().count()));
    Ok(entries)
}

pub fn load_dictionary_candidates(source: &str) -> Result<Vec<(String, Vec<String>)>, String> {
    if source.is_empty() {
        return Ok(Vec::new());
    }
    let path = expand_tilde(source);
    let mut entries = if path.exists() && path.is_file() {
        let text = fs::read_to_string(&path).map_err(|e| e.to_string())?;
        let suffix = path
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| format!(".{}", e.to_ascii_lowercase()))
            .unwrap_or_default();
        parse_dictionary_candidate_text(&text, &suffix)?
    } else {
        parse_dictionary_candidate_text(source, ".json")?
    };
    entries.sort_by(|a, b| b.0.chars().count().cmp(&a.0.chars().count()));
    Ok(entries)
}

fn default_dictionary_paths() -> Vec<PathBuf> {
    let mut candidate_dirs = Vec::new();
    if let Ok(cwd) = env::current_dir() {
        candidate_dirs.push(cwd.join("data"));
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(root) = exe.parent().and_then(|p| p.parent()).and_then(|p| p.parent()) {
            candidate_dirs.push(root.join("data"));
        }
    }
    let mut paths = Vec::new();
    let mut seen = HashSet::new();
    for dir in candidate_dirs {
        if !dir.is_dir() {
            continue;
        }
        if let Ok(read_dir) = fs::read_dir(&dir) {
            let mut skk_files: Vec<PathBuf> = read_dir
                .filter_map(|e| e.ok().map(|e| e.path()))
                .filter(|p| p.extension().and_then(|ext| ext.to_str()) == Some("skk"))
                .collect();
            skk_files.sort();
            for p in skk_files {
                let resolved = fs::canonicalize(&p).unwrap_or_else(|_| p.clone());
                if seen.insert(resolved) {
                    paths.push(p);
                }
            }
        }
    }
    paths
}

fn parse_dictionary_text(text: &str, suffix: &str) -> Result<Vec<(String, String)>, String> {
    let stripped = text.trim();
    if stripped.is_empty() {
        return Ok(Vec::new());
    }
    if suffix == ".json" || stripped.starts_with('{') || stripped.starts_with('[') {
        return parse_json_dictionary(stripped);
    }
    if suffix == ".skk" || stripped.contains('/') {
        return parse_skk_dictionary(stripped);
    }
    parse_tsv_dictionary(stripped)
}

fn parse_dictionary_candidate_text(
    text: &str,
    suffix: &str,
) -> Result<Vec<(String, Vec<String>)>, String> {
    let stripped = text.trim();
    if stripped.is_empty() {
        return Ok(Vec::new());
    }
    if suffix == ".json" || stripped.starts_with('{') || stripped.starts_with('[') {
        return parse_json_dictionary_candidates(stripped);
    }
    if suffix == ".skk" || stripped.contains('/') {
        return parse_skk_dictionary_candidates(stripped);
    }
    let tsv = parse_tsv_dictionary(stripped)?;
    Ok(tsv.into_iter().map(|(s, t)| (s, vec![t])).collect())
}

fn parse_json_dictionary(text: &str) -> Result<Vec<(String, String)>, String> {
    let payload = parse_json(text).map_err(|e| format!("invalid dictionary JSON: {e}"))?;
    let mut raw = Vec::new();
    match payload {
        JsonValue::Object(entries) => {
            for (k, v) in entries {
                let target = match v {
                    JsonValue::Str(s) => Some(s),
                    JsonValue::Array(items) => items.into_iter().find_map(|item| match item {
                        JsonValue::Str(s) => Some(s),
                        _ => None,
                    }),
                    _ => None,
                };
                let t = target.ok_or_else(|| "dictionary entries must be string to string".to_string())?;
                let s = k.trim().to_string();
                if s.is_empty() {
                    return Err("dictionary input must not be empty".to_string());
                }
                raw.push((s, t));
            }
        }
        JsonValue::Array(items) => {
            for item in items {
                let obj = item
                    .as_object()
                    .ok_or_else(|| "dictionary list entries must be objects".to_string())?;
                let input = obj
                    .iter()
                    .find(|(k, _)| k == "input")
                    .and_then(|(_, v)| v.as_str())
                    .ok_or_else(|| "dictionary entries must be string to string".to_string())?;
                let output = obj
                    .iter()
                    .find(|(k, _)| k == "output")
                    .and_then(|(_, v)| match v {
                        JsonValue::Str(s) => Some(s.clone()),
                        JsonValue::Array(arr) => {
                            arr.iter().find_map(|x| x.as_str().map(|s| s.to_string()))
                        }
                        _ => None,
                    })
                    .ok_or_else(|| "dictionary entries must be string to string".to_string())?;
                let s = input.trim().to_string();
                if s.is_empty() {
                    return Err("dictionary input must not be empty".to_string());
                }
                raw.push((s, output));
            }
        }
        _ => return Err("dictionary JSON must be an object or list".to_string()),
    }
    Ok(dedupe(raw))
}

fn parse_json_dictionary_candidates(text: &str) -> Result<Vec<(String, Vec<String>)>, String> {
    let payload = parse_json(text).map_err(|e| format!("invalid dictionary JSON: {e}"))?;
    let mut raw = Vec::new();
    match payload {
        JsonValue::Object(entries) => {
            for (k, v) in entries {
                let s = k.trim().to_string();
                if s.is_empty() {
                    return Err("dictionary input must not be empty".to_string());
                }
                let values = extract_candidate_targets(v)?;
                raw.push((s, values));
            }
        }
        JsonValue::Array(items) => {
            for item in items {
                let obj = item
                    .as_object()
                    .ok_or_else(|| "dictionary list entries must be objects".to_string())?;
                let input = obj
                    .iter()
                    .find(|(k, _)| k == "input")
                    .and_then(|(_, v)| v.as_str())
                    .ok_or_else(|| "dictionary input must be a string".to_string())?;
                let s = input.trim().to_string();
                if s.is_empty() {
                    return Err("dictionary input must not be empty".to_string());
                }
                let out_val = obj
                    .iter()
                    .find(|(k, _)| k == "output")
                    .map(|(_, v)| v.clone())
                    .ok_or_else(|| {
                        "dictionary output must be a string or list of strings".to_string()
                    })?;
                let values = extract_candidate_targets(out_val)?;
                raw.push((s, values));
            }
        }
        _ => return Err("dictionary JSON must be an object or list".to_string()),
    }
    Ok(dedupe_candidate_entries(raw))
}

fn extract_candidate_targets(v: JsonValue) -> Result<Vec<String>, String> {
    let raw_list = match v {
        JsonValue::Str(s) => vec![s],
        JsonValue::Array(arr) => {
            let mut out = Vec::with_capacity(arr.len());
            for item in arr {
                match item {
                    JsonValue::Str(s) => out.push(s),
                    _ => return Err("dictionary output candidates must be strings".to_string()),
                }
            }
            out
        }
        _ => return Err("dictionary output must be a string or list of strings".to_string()),
    };
    let cleaned: Vec<String> = raw_list
        .into_iter()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    if cleaned.is_empty() {
        return Err("dictionary output must not be empty".to_string());
    }
    Ok(cleaned)
}

fn parse_tsv_dictionary(text: &str) -> Result<Vec<(String, String)>, String> {
    let mut raw = Vec::new();
    for (line_idx, raw_line) in text.lines().enumerate() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((left, right)) = line.split_once('\t') else {
            return Err(format!(
                "line {}: expected tab-separated input/output",
                line_idx + 1
            ));
        };
        let s = left.trim().to_string();
        if s.is_empty() {
            return Err("dictionary input must not be empty".to_string());
        }
        raw.push((s, right.to_string()));
    }
    Ok(dedupe(raw))
}

fn parse_skk_dictionary(text: &str) -> Result<Vec<(String, String)>, String> {
    let mut raw = Vec::new();
    for raw_line in text.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with(';') || !line.contains(' ') {
            continue;
        }
        let mut iter = line.split_whitespace();
        let Some(key) = iter.next() else { continue };
        let rest = &line[key.len()..].trim_start();
        for part in rest.split('/') {
            if part.is_empty() {
                continue;
            }
            let cand = part.split(';').next().unwrap_or("");
            if !cand.is_empty() {
                raw.push((key.to_string(), cand.to_string()));
                break;
            }
        }
    }
    Ok(dedupe(raw))
}

fn parse_skk_dictionary_candidates(text: &str) -> Result<Vec<(String, Vec<String>)>, String> {
    let mut raw = Vec::new();
    for raw_line in text.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with(';') || !line.contains(' ') {
            continue;
        }
        let mut iter = line.split_whitespace();
        let Some(key) = iter.next() else { continue };
        let rest = &line[key.len()..].trim_start();
        let mut targets = Vec::new();
        for part in rest.split('/') {
            if part.is_empty() {
                continue;
            }
            let cand = part.split(';').next().unwrap_or("");
            if !cand.is_empty() {
                targets.push(cand.to_string());
            }
        }
        if !targets.is_empty() {
            raw.push((key.to_string(), targets));
        }
    }
    Ok(dedupe_candidate_entries(raw))
}

fn dedupe(entries: Vec<(String, String)>) -> Vec<(String, String)> {
    let mut seen = HashSet::new();
    let mut out = Vec::with_capacity(entries.len());
    for (s, t) in entries {
        if seen.insert(s.clone()) {
            out.push((s, t));
        }
    }
    out
}

fn dedupe_candidate_entries(entries: Vec<(String, Vec<String>)>) -> Vec<(String, Vec<String>)> {
    let mut order: Vec<String> = Vec::new();
    let mut merged: HashMap<String, Vec<String>> = HashMap::new();
    for (source, targets) in entries {
        let bucket = merged.entry(source.clone()).or_insert_with(|| {
            order.push(source);
            Vec::new()
        });
        for t in targets {
            if !bucket.contains(&t) {
                bucket.push(t);
            }
        }
    }
    order
        .into_iter()
        .map(|k| {
            let v = merged.remove(&k).unwrap_or_default();
            (k, v)
        })
        .collect()
}

pub fn apply_dictionary_index(text: &str, index: &DictionaryIndex) -> String {
    let mut out = String::with_capacity(text.len());
    for (is_placeholder, part) in split_placeholders(text) {
        if is_placeholder {
            out.push_str(part);
        } else {
            out.push_str(&apply_index_to_plain_text(part, index));
        }
    }
    out
}

pub fn apply_dictionary_with_placeholders_index(
    text: &str,
    index: &DictionaryIndex,
    placeholder_start: usize,
) -> (String, Vec<(String, String)>) {
    let mut out = String::with_capacity(text.len());
    let mut spans = Vec::new();
    let mut next_index = placeholder_start;
    for (is_placeholder, part) in split_placeholders(text) {
        if is_placeholder {
            out.push_str(part);
        } else {
            let (converted_part, part_spans, new_next) =
                apply_index_as_placeholders_to_plain_text(part, index, next_index);
            out.push_str(&converted_part);
            spans.extend(part_spans);
            next_index = new_next;
        }
    }
    (out, spans)
}

pub fn apply_dictionary_candidate_sets_with_placeholders_index(
    text: &str,
    index: &CandidateDictionaryIndex,
    placeholder_start: usize,
    per_word_limit: usize,
    max_candidates: usize,
) -> Vec<(String, Vec<(String, String)>)> {
    let per_word_limit = per_word_limit.max(1);
    let max_candidates = max_candidates.max(1);
    let mut states: Vec<(String, Vec<(String, String)>, usize)> =
        vec![(String::new(), Vec::new(), placeholder_start)];

    for (is_placeholder, part) in split_placeholders(text) {
        let mut next_states = Vec::new();
        if is_placeholder {
            for (mut prefix, spans, next_idx) in states {
                prefix.push_str(part);
                next_states.push((prefix, spans, next_idx));
            }
        } else {
            for (prefix, spans, next_idx) in states {
                for (converted, part_spans, new_next_idx) in plain_text_candidate_variants_indexed(
                    part,
                    index,
                    next_idx,
                    per_word_limit,
                    max_candidates,
                ) {
                    let mut combined_spans = spans.clone();
                    combined_spans.extend(part_spans);
                    next_states.push((
                        format!("{prefix}{converted}"),
                        combined_spans,
                        new_next_idx,
                    ));
                    if next_states.len() >= max_candidates {
                        break;
                    }
                }
                if next_states.len() >= max_candidates {
                    break;
                }
            }
        }
        next_states.truncate(max_candidates);
        states = next_states;
    }

    states.into_iter().map(|(t, s, _)| (t, s)).collect()
}

fn apply_non_ascii_from_index(text: &str, index: &DictionaryIndex) -> String {
    let mut result = text.to_string();
    for (source, target) in &index.other_non_ascii {
        if result.contains(source.as_str()) {
            result = result.replace(source.as_str(), target.as_str());
        }
    }
    if result.contains('-') && (!index.hyphen_by_sig.is_empty() || !index.hyphen_edge.is_empty()) {
        let rb = result.as_bytes();
        let mut sigs: Vec<[u8; 3]> = Vec::new();
        for i in 1..rb.len().saturating_sub(1) {
            if rb[i] == b'-' {
                let sig = [rb[i - 1], b'-', rb[i + 1]];
                if !sigs.contains(&sig) {
                    sigs.push(sig);
                }
            }
        }
        if sigs.len() == 1 && index.hyphen_edge.is_empty() {
            if let Some(bucket) = index.hyphen_by_sig.get(&sigs[0]) {
                for (_, source, target) in bucket {
                    if result.contains(source.as_str()) {
                        result = result.replace(source.as_str(), target.as_str());
                    }
                }
            }
        } else {
            let mut candidates: Vec<&(usize, String, String)> =
                index.hyphen_edge.iter().collect();
            for sig in &sigs {
                if let Some(bucket) = index.hyphen_by_sig.get(sig) {
                    candidates.extend(bucket.iter());
                }
            }
            candidates.sort_by_key(|item| item.0);
            for (_, source, target) in candidates {
                if result.contains(source.as_str()) {
                    result = result.replace(source.as_str(), target.as_str());
                }
            }
        }
    }
    result
}

fn apply_non_ascii_from_candidate_index(text: &str, index: &CandidateDictionaryIndex) -> String {
    let mut result = text.to_string();
    for (source, targets) in &index.other_non_ascii {
        if result.contains(source.as_str()) {
            result = result.replace(source.as_str(), &targets[0]);
        }
    }
    if result.contains('-') && (!index.hyphen_by_sig.is_empty() || !index.hyphen_edge.is_empty()) {
        let rb = result.as_bytes();
        let mut sigs: Vec<[u8; 3]> = Vec::new();
        for i in 1..rb.len().saturating_sub(1) {
            if rb[i] == b'-' {
                let sig = [rb[i - 1], b'-', rb[i + 1]];
                if !sigs.contains(&sig) {
                    sigs.push(sig);
                }
            }
        }
        if sigs.len() == 1 && index.hyphen_edge.is_empty() {
            if let Some(bucket) = index.hyphen_by_sig.get(&sigs[0]) {
                for (_, source, targets) in bucket {
                    if result.contains(source.as_str()) {
                        result = result.replace(source.as_str(), &targets[0]);
                    }
                }
            }
        } else {
            let mut candidates: Vec<&(usize, String, Vec<String>)> =
                index.hyphen_edge.iter().collect();
            for sig in &sigs {
                if let Some(bucket) = index.hyphen_by_sig.get(sig) {
                    candidates.extend(bucket.iter());
                }
            }
            candidates.sort_by_key(|item| item.0);
            for (_, source, targets) in candidates {
                if result.contains(source.as_str()) {
                    result = result.replace(source.as_str(), &targets[0]);
                }
            }
        }
    }
    result
}

fn find_ascii_runs(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut runs = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if ascii_char_idx(bytes[i]).is_some() {
            let start = i;
            i += 1;
            while i < bytes.len() && ascii_char_idx(bytes[i]).is_some() {
                i += 1;
            }
            runs.push((start, i));
        } else {
            i += 1;
        }
    }
    runs
}

fn apply_index_to_plain_text(text: &str, index: &DictionaryIndex) -> String {
    let result = apply_non_ascii_from_index(text, index);
    if !index.has_ascii_entries {
        return result;
    }
    let mut out = String::with_capacity(result.len());
    let mut cursor = 0;
    for (start, end) in find_ascii_runs(&result) {
        out.push_str(&result[cursor..start]);
        let run = &result[start..end];
        if let Some(tokens) = segment_ascii_run_indexed(run, index) {
            for (_src, target, converted) in tokens {
                if converted || !target.is_empty() {
                    out.push_str(&target);
                }
            }
        } else {
            out.push_str(run);
        }
        cursor = end;
    }
    out.push_str(&result[cursor..]);
    out
}

fn apply_index_as_placeholders_to_plain_text(
    text: &str,
    index: &DictionaryIndex,
    placeholder_start: usize,
) -> (String, Vec<(String, String)>, usize) {
    let result = apply_non_ascii_from_index(text, index);
    let mut spans = Vec::new();
    let mut next_index = placeholder_start;
    if !index.has_ascii_entries {
        return (result, spans, next_index);
    }
    let mut out = String::with_capacity(result.len());
    let mut cursor = 0;
    for (start, end) in find_ascii_runs(&result) {
        out.push_str(&result[cursor..start]);
        let run = &result[start..end];
        if let Some(tokens) = segment_ascii_run_indexed(run, index) {
            for (source, target, converted) in tokens {
                if !converted {
                    out.push_str(&source);
                } else {
                    let ph = format!("<TECH_{next_index}>");
                    next_index += 1;
                    out.push_str(&ph);
                    spans.push((ph, target));
                }
            }
        } else {
            out.push_str(run);
        }
        cursor = end;
    }
    out.push_str(&result[cursor..]);
    (out, spans, next_index)
}

type SegItem = (String, String, bool);
type SegScore = (usize, usize, Vec<SegItem>);

fn prefer_ascii_segmentation(current: Option<SegScore>, candidate: SegScore) -> SegScore {
    let Some(cur) = current else { return candidate };
    if candidate.0 != cur.0 {
        return if candidate.0 > cur.0 { candidate } else { cur };
    }
    if candidate.1 != cur.1 {
        return if candidate.1 < cur.1 { candidate } else { cur };
    }
    let cand_len: usize = candidate.2.iter().map(|(_, t, _)| t.chars().count()).sum();
    let cur_len: usize = cur.2.iter().map(|(_, t, _)| t.chars().count()).sum();
    if cand_len < cur_len {
        candidate
    } else {
        cur
    }
}

fn segment_ascii_run_indexed(text: &str, index: &DictionaryIndex) -> Option<Vec<SegItem>> {
    let bytes = text.as_bytes();
    let n = bytes.len();
    let mut memo: Vec<Option<Option<SegScore>>> = vec![None; n + 1];
    memo[n] = Some(Some((0, 0, Vec::new())));

    fn solve(
        pos: usize,
        bytes: &[u8],
        text: &str,
        index: &DictionaryIndex,
        memo: &mut [Option<Option<SegScore>>],
    ) -> Option<SegScore> {
        if let Some(cached) = &memo[pos] {
            return cached.clone();
        }
        let mut best: Option<SegScore> = None;

        let mut node_idx = 0usize;
        let mut matches: Vec<(String, String)> = Vec::new();
        for &b in &bytes[pos..] {
            let Some(c_idx) = ascii_char_idx(b) else { break };
            let next = index.trie[node_idx].children[c_idx];
            if next == 0 {
                break;
            }
            node_idx = next as usize;
            if let Some(hit) = &index.trie[node_idx].value {
                matches.push(hit.clone());
            }
        }

        for (source, target) in matches.into_iter().rev() {
            let s_len = source.len();
            if let Some((conv_chars, segs, mut suffix)) =
                solve(pos + s_len, bytes, text, index, memo)
            {
                let mut v = Vec::with_capacity(suffix.len() + 1);
                v.push((source, target, true));
                v.append(&mut suffix);
                let cand = (conv_chars + s_len, segs + 1, v);
                best = Some(prefer_ascii_segmentation(best, cand));
            }
        }

        if let Some(c_idx) = ascii_char_idx(bytes[pos]) {
            for &token in &index.passthrough_by_char[c_idx] {
                if text[pos..].starts_with(token) {
                    if let Some((conv_chars, segs, mut suffix)) =
                        solve(pos + token.len(), bytes, text, index, memo)
                    {
                        let mut v = Vec::with_capacity(suffix.len() + 1);
                        v.push((token.to_string(), token.to_string(), false));
                        v.append(&mut suffix);
                        let cand = (conv_chars, segs + 1, v);
                        best = Some(prefer_ascii_segmentation(best, cand));
                    }
                }
            }
        }

        memo[pos] = Some(best.clone());
        best
    }

    let solved = solve(0, bytes, text, index, &mut memo)?;
    if solved.0 == 0 {
        return None;
    }
    Some(solved.2)
}

type CandSegItem = (String, Vec<String>, bool);
type CandSegScore = (usize, usize, Vec<CandSegItem>);

fn prefer_ascii_candidate_segmentation(
    current: Option<CandSegScore>,
    candidate: CandSegScore,
) -> CandSegScore {
    let Some(cur) = current else { return candidate };
    if candidate.0 != cur.0 {
        return if candidate.0 > cur.0 { candidate } else { cur };
    }
    if candidate.1 != cur.1 {
        return if candidate.1 < cur.1 { candidate } else { cur };
    }
    let cand_len: usize = candidate
        .2
        .iter()
        .map(|(_, t, _)| t[0].chars().count())
        .sum();
    let cur_len: usize = cur.2.iter().map(|(_, t, _)| t[0].chars().count()).sum();
    if cand_len < cur_len {
        candidate
    } else {
        cur
    }
}

fn segment_ascii_run_candidates_indexed(
    text: &str,
    index: &CandidateDictionaryIndex,
) -> Option<Vec<CandSegItem>> {
    let bytes = text.as_bytes();
    let n = bytes.len();
    let mut memo: Vec<Option<Option<CandSegScore>>> = vec![None; n + 1];
    memo[n] = Some(Some((0, 0, Vec::new())));

    fn solve(
        pos: usize,
        bytes: &[u8],
        text: &str,
        index: &CandidateDictionaryIndex,
        memo: &mut [Option<Option<CandSegScore>>],
    ) -> Option<CandSegScore> {
        if let Some(cached) = &memo[pos] {
            return cached.clone();
        }
        let mut best: Option<CandSegScore> = None;

        let mut node_idx = 0usize;
        let mut matches: Vec<(String, Vec<String>)> = Vec::new();
        for &b in &bytes[pos..] {
            let Some(c_idx) = ascii_char_idx(b) else { break };
            let next = index.trie[node_idx].children[c_idx];
            if next == 0 {
                break;
            }
            node_idx = next as usize;
            if let Some(hit) = &index.trie[node_idx].value {
                matches.push(hit.clone());
            }
        }

        for (source, targets) in matches.into_iter().rev() {
            let s_len = source.len();
            if let Some((conv_chars, segs, mut suffix)) =
                solve(pos + s_len, bytes, text, index, memo)
            {
                let mut v = Vec::with_capacity(suffix.len() + 1);
                v.push((source, targets, true));
                v.append(&mut suffix);
                let cand = (conv_chars + s_len, segs + 1, v);
                best = Some(prefer_ascii_candidate_segmentation(best, cand));
            }
        }

        if let Some(c_idx) = ascii_char_idx(bytes[pos]) {
            for &token in &index.passthrough_by_char[c_idx] {
                if text[pos..].starts_with(token) {
                    if let Some((conv_chars, segs, mut suffix)) =
                        solve(pos + token.len(), bytes, text, index, memo)
                    {
                        let mut v = Vec::with_capacity(suffix.len() + 1);
                        v.push((token.to_string(), vec![token.to_string()], false));
                        v.append(&mut suffix);
                        let cand = (conv_chars, segs + 1, v);
                        best = Some(prefer_ascii_candidate_segmentation(best, cand));
                    }
                }
            }
        }

        memo[pos] = Some(best.clone());
        best
    }

    let solved = solve(0, bytes, text, index, &mut memo)?;
    if solved.0 == 0 {
        return None;
    }
    Some(solved.2)
}

fn plain_text_candidate_variants_indexed(
    text: &str,
    index: &CandidateDictionaryIndex,
    placeholder_start: usize,
    per_word_limit: usize,
    max_candidates: usize,
) -> Vec<(String, Vec<(String, String)>, usize)> {
    let result = apply_non_ascii_from_candidate_index(text, index);
    if !index.has_ascii_entries {
        return vec![(result, Vec::new(), placeholder_start)];
    }

    let mut states: Vec<(String, Vec<(String, String)>, usize)> =
        vec![(String::new(), Vec::new(), placeholder_start)];
    let mut cursor = 0;
    for (start, end) in find_ascii_runs(&result) {
        let literal = &result[cursor..start];
        if !literal.is_empty() {
            for (prefix, _, _) in &mut states {
                prefix.push_str(literal);
            }
        }
        let run = &result[start..end];
        let mut next_states = Vec::new();
        for (prefix, spans, next_idx) in states {
            for (converted, run_spans, new_next_idx) in ascii_run_candidate_variants_indexed(
                run,
                index,
                next_idx,
                per_word_limit,
                max_candidates,
            ) {
                let mut combined_spans = spans.clone();
                combined_spans.extend(run_spans);
                next_states.push((
                    format!("{prefix}{converted}"),
                    combined_spans,
                    new_next_idx,
                ));
                if next_states.len() >= max_candidates {
                    break;
                }
            }
            if next_states.len() >= max_candidates {
                break;
            }
        }
        next_states.truncate(max_candidates);
        states = next_states;
        cursor = end;
    }
    let tail = &result[cursor..];
    if !tail.is_empty() {
        for (prefix, _, _) in &mut states {
            prefix.push_str(tail);
        }
    }
    states.truncate(max_candidates);
    states
}

fn ascii_run_candidate_variants_indexed(
    text: &str,
    index: &CandidateDictionaryIndex,
    placeholder_start: usize,
    per_word_limit: usize,
    max_candidates: usize,
) -> Vec<(String, Vec<(String, String)>, usize)> {
    let Some(tokens) = segment_ascii_run_candidates_indexed(text, index) else {
        return vec![(text.to_string(), Vec::new(), placeholder_start)];
    };

    let mut option_sets: Vec<Vec<(String, String, bool)>> = Vec::with_capacity(tokens.len());
    for (source, targets, converted) in tokens {
        if converted {
            let opts: Vec<(String, String, bool)> = targets
                .into_iter()
                .take(per_word_limit)
                .map(|t| (source.clone(), t, true))
                .collect();
            option_sets.push(opts);
        } else {
            option_sets.push(vec![(source.clone(), source, false)]);
        }
    }

    let mut combinations: Vec<Vec<(String, String, bool)>> = vec![Vec::new()];
    for opts in option_sets {
        let mut next_combos = Vec::new();
        for prefix in &combinations {
            for opt in &opts {
                let mut c = prefix.clone();
                c.push(opt.clone());
                next_combos.push(c);
            }
        }
        combinations = next_combos;
    }

    let mut variants = Vec::new();
    for combo in combinations.into_iter().take(max_candidates) {
        let mut out = String::new();
        let mut spans = Vec::new();
        let mut next_idx = placeholder_start;
        for (source, target, converted) in combo {
            if !converted {
                out.push_str(&source);
            } else {
                let ph = format!("<TECH_{next_idx}>");
                next_idx += 1;
                out.push_str(&ph);
                spans.push((ph, target));
            }
        }
        variants.push((out, spans, next_idx));
    }
    variants
}
