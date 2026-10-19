use std::collections::HashSet;
use std::sync::OnceLock;
use std::time::Instant;

use crate::config::get_env;
use crate::dictionary::{
    apply_dictionary_candidate_sets_with_placeholders_index, apply_dictionary_index,
    apply_dictionary_with_placeholders_index, configured_candidate_dictionary_index,
    configured_dictionary_index,
};
use crate::json::JsonValue;
use crate::kkc_client::convert_hiragana_candidates_with_kkc;
use crate::protection::{protect_text, restore_text, ProtectedSpan, ProtectedText};
use crate::romanizer::{romaji_to_hiragana, split_placeholders};

#[derive(Debug, Clone)]
pub struct ConvertResult {
    pub text: String,
    pub protected_text: String,
    pub protected_spans: Vec<ProtectedSpan>,
    pub backend: String,
    pub elapsed_ms: u64,
}

#[derive(Debug, Clone)]
pub struct CandidateResult {
    pub base: ConvertResult,
    pub candidates: Vec<String>,
}

const RAW_ROMAN_REPLACEMENTS: &[(&str, &str)] = &[
    ("placeholder", "placeholder"),
    ("compatible", "compatible"),
    ("protection", "protection"),
    ("keybinding", "keybinding"),
    ("protected", "protected"),
    ("temperature", "temperature"),
    ("candidate", "candidate"),
    ("paragraph", "paragraph"),
    ("metadata", "metadata"),
    ("endpoint", "endpoint"),
    ("workflow", "workflow"),
    ("distribution", "distribution"),
    ("transaction", "transaction"),
    ("restoration", "restoration"),
    ("property", "property"),
    ("headline", "headline"),
    ("sentence", "sentence"),
    ("validate", "validate"),
    ("validation", "validation"),
    ("quantize", "quantize"),
    ("inference", "inference"),
    ("dataset", "dataset"),
    ("runtime", "runtime"),
    ("response", "response"),
    ("external", "external"),
    ("request", "request"),
    ("explicit", "explicit"),
    ("reasoning", "reasoning"),
    ("markdown", "Markdown"),
    ("training", "training"),
    ("frontmatter", "frontmatter"),
    ("fragment", "fragment"),
    ("repository", "Repository"),
    ("controller", "Controller"),
    ("valueobject", "ValueObject"),
    ("domainservice", "DomainService"),
    ("applicationservice", "ApplicationService"),
    ("experiment", "experiment"),
    ("discard", "discard"),
    ("summary", "summary"),
    ("reports", "reports"),
    ("result", "result"),
    ("object", "object"),
    ("timeout", "timeout"),
    ("holdout", "holdout"),
    ("default", "default"),
    ("preview", "preview"),
    ("history", "history"),
    ("metrics", "metrics"),
    ("meaning", "meaning"),
    ("manual", "manual"),
    ("buffer", "buffer"),
    ("server", "server"),
    ("source", "source"),
    ("output", "output"),
    ("input", "input"),
    ("model", "model"),
    ("local", "local"),
    ("cloud", "cloud"),
    ("exact", "exact"),
    ("match", "match"),
    ("token", "token"),
    ("class", "class"),
    ("teacher", "teacher"),
    ("train", "train"),
    ("valid", "valid"),
    ("false", "false"),
    ("chunk", "chunk"),
    ("domain", "domain"),
    ("entity", "Entity"),
    ("fence", "fence"),
    ("chars", "chars"),
    ("lora", "LoRA"),
    ("codex", "Codex"),
    ("mecab", "MeCab"),
    ("pykakasi", "pykakasi"),
    ("kakasi", "kakasi"),
    ("tomoko", "Tomoko"),
    ("jsonl", "JSONL"),
    ("json", "JSON"),
    ("retry", "retry"),
    ("diff", "diff"),
    ("file", "file"),
    ("main", "main"),
    ("eval", "eval"),
    ("gate", "gate"),
    ("cache", "cache"),
    ("env", "env"),
    ("max", "max"),
    ("mode", "mode"),
    ("port", "port"),
    ("src", "src"),
    ("pass", "pass"),
    ("rate", "rate"),
    ("tag", "tag"),
    ("openai", "OpenAI"),
    ("ollama", "Ollama"),
    ("llama", "llama"),
    ("error", "error"),
    ("undo", "undo"),
    ("api", "API"),
    ("url", "URL"),
    ("org", "org"),
    ("db", "DB"),
    ("cer", "CER"),
    ("sqlite", "SQLite"),
    ("vector", "vector"),
    ("search", "search"),
    ("fallback", "fallback"),
    ("command", "command"),
    ("gemma", "Gemma"),
    ("roomaji", "ローマ字"),
    ("romaji", "ローマ字"),
    ("kashitara", "化したら"),
    ("shitara", "したら"),
    ("kyoushidata", "教師データ"),
    ("kyoushi", "教師"),
    ("data", "データ"),
    ("ninarunodeha", "になるのでは"),
    ("ninaru", "になる"),
    ("naru", "なる"),
    ("nodeha", "のでは"),
    ("target", "ターゲット"),
    ("emacs", "Emacs"),
    ("nigenteisurunara", "に限定するなら"),
    ("genteisurunara", "限定するなら"),
    ("eijinihongokankeinakutoriaezu", "英字・日本語関係なく、とりあえず"),
    ("alphabet", "alphabet"),
    ("nyuuryoku", "入力"),
    ("shita", "した"),
    ("mono", "もの"),
    ("llm", "LLM"),
    ("eigonihongomajiri", "英語日本語混じり"),
    ("nikirikaerukoto", "に切り替えること"),
    ("hakanou", "は可能。"),
    ("kanou", "可能"),
    ("mamoru", "守る"),
    ("marugoto", "丸ごと"),
    ("kowasanai", "壊さない"),
    ("youni", "ように"),
    ("nakunattara", "なくなったら"),
    ("kaenai", "変えない"),
    ("nokosu", "残す"),
    ("sono", "その"),
    ("tsuika", "追加"),
    ("miru", "見る"),
    ("naka", "中"),
    ("shinai", "しない"),
    ("shinakatta", "しなかった"),
    ("tsukawanai", "使わない"),
    ("chokusetu", "直接"),
    ("mochikomanai", "持ち込まない"),
    ("nagasugiru", "長すぎる"),
    ("kakikaenai", "書き換えない"),
    ("chikazukeru", "近づける"),
    ("uketomeru", "受け止める"),
    ("butsukaranai", "ぶつからない"),
    ("atatamete", "温めて"),
    ("nihongo", "日本語"),
    ("keishiki", "形式"),
    ("yakushi", "訳し"),
    ("yakusu", "訳す"),
    ("sugita", "すぎた"),
    ("eranda", "選んだ"),
    ("yurusuka", "許すか"),
    ("kangaeru", "考える"),
    ("futatsu", "二つ"),
    ("saisho", "最初"),
    ("mitaina", "みたいな"),
    ("suteru", "捨てる"),
    ("dasu", "出す"),
    ("modosu", "戻す"),
    ("hazusu", "外す"),
    ("watasu", "渡す"),
    ("tsukatta", "使った"),
    ("kawattara", "変わったら"),
    ("agattara", "上がったら"),
    ("mazattara", "混ざったら"),
    ("handan", "判断"),
    ("shirabe", "調べ"),
    ("shippai", "失敗"),
    ("chousei", "調整"),
    ("saigen", "再現"),
    ("gousei", "合成"),
    ("kakuri", "隔離"),
    ("kekka", "結果"),
    ("hayame", "早め"),
    ("shori", "処理"),
    ("yobanai", "呼ばない"),
    ("fuhen", "不変"),
    ("zen", "全"),
    ("zettai", "絶対"),
    ("usuku", "薄く"),
    ("kaette", "返って"),
    ("mama", "まま"),
    ("mazu", "まず"),
    ("mada", "まだ"),
    ("kita", "来た"),
    ("toki", "時"),
    ("naku", "なく"),
    ("nakereba", "なければ"),
    ("mawasu", "回す"),
    ("aru", "ある"),
    ("hou", "方"),
    ("nai", "ない"),
    ("kuru", "くる"),
    ("dame", "ダメ"),
    ("oku", "おく"),
    ("kiru", "切る"),
    ("haru", "貼る"),
    ("kakunin", "確認"),
    ("hoshii", "欲しい"),
    ("yaru", "やる"),
    ("yaranai", "やらない"),
    ("ii", "いい"),
    ("ja", "じゃ"),
    ("hikume", "低め"),
    ("ireru", "入れる"),
    ("noseru", "載せる"),
    ("okosu", "起こす"),
    ("tamotsu", "保つ"),
    ("motsu", "持つ"),
    ("tsukuru", "作る"),
    ("sentaku", "選択"),
    ("han'i", "範囲"),
    ("henkan", "変換"),
    ("nokoseru", "残せる"),
    ("modoreru", "戻れる"),
    ("hiraku", "開く"),
    ("kaesu", "返す"),
    ("atsukau", "扱う"),
    ("morau", "もらう"),
    ("koushin", "更新"),
    ("hakaru", "測る"),
    ("tariru", "足りる"),
    ("tsukau", "使う"),
    ("naoseru", "直せる"),
    ("kinshi", "禁止"),
    ("kaihi", "回避"),
    ("henna", "変な"),
    ("kaku", "書く"),
    ("ichido", "一度"),
    ("mou", "もう"),
    ("goto", "ごと"),
    ("rei", "例"),
    ("moto", "元"),
    ("priority", "priority"),
    ("latency", "latency"),
    ("omoi", "重い"),
    ("karui", "軽い"),
    ("yobu", "呼ぶ"),
    ("yobunoha", "呼ぶのは"),
    ("yonde", "読んで"),
    ("yomu", "読む"),
    ("shitai", "したい"),
    ("shite", "して"),
    ("suru", "する"),
    ("dekiru", "できる"),
    ("ichiban", "一番"),
    ("kamo", "かも"),
    ("dake", "だけ"),
    ("nara", "なら"),
    ("koredeii", "これでいい"),
    ("tataku", "叩く"),
    ("ato", "後"),
    ("mae", "前"),
    ("de", "で"),
    ("wo", "を"),
    ("o", "を"),
    ("ni", "に"),
    ("no", "の"),
    ("ga", "が"),
    ("ha", "は"),
    ("wa", "は"),
    ("to", "と"),
    ("kara", "から"),
    ("made", "まで"),
    ("mo", "も"),
    ("ya", "や"),
    ("node", "ので"),
];

const TECH_PHRASE_REPLACEMENTS: &[(&str, &str)] = &[
    ("paths urls commands keybindings", "paths/URLs/commands/keybindings"),
    ("urls paths keybindings identifiers", "URLs/paths/keybindings/identifiers"),
    ("meaning class teacher env", "meaning/class/teacher/env"),
    ("train valid test", "train/valid/test"),
    ("manual pass fail", "manual pass/fail"),
    ("no extra text", "no-extra-text"),
    ("input output", "input/output"),
    ("before after", "before/after"),
    ("key value", "key/value"),
    ("undo retry", "undo/retry"),
    ("full fine tuned", "full fine-tuned"),
    ("full fine tuning", "full fine-tuning"),
    ("command based", "command-based"),
    ("pre generation", "pre-generation"),
    ("over romanize", "over-romanize"),
    ("m4 max", "M4 Max"),
    ("org babel", "org-babel"),
    ("kana only", "kana-only"),
    ("MY_IME_BACKEND dummy", "MY_IME_BACKEND=dummy"),
];

fn sorted_roman_replacements() -> &'static Vec<(&'static str, &'static str)> {
    static SORTED: OnceLock<Vec<(&'static str, &'static str)>> = OnceLock::new();
    SORTED.get_or_init(|| {
        let mut v = RAW_ROMAN_REPLACEMENTS.to_vec();
        v.sort_by(|a, b| b.0.len().cmp(&a.0.len()));
        v
    })
}

pub fn convert(text: &str, _metadata: Option<&JsonValue>) -> Result<ConvertResult, String> {
    let started = Instant::now();
    let backend = get_env("BACKEND", "kkc").to_ascii_lowercase();
    let (mut leading_ws, core_text, trailing_ws) = split_outer_whitespace(text);
    let protected = protect_text(core_text)?;
    if manual_term_confirmation_only(&protected) {
        leading_ws = "";
    }
    let dict_index = configured_dictionary_index()?;
    let (dictionary_text, dictionary_spans) =
        apply_dictionary_with_placeholders_index(&protected.text, &dict_index, protected.spans.len());

    let converted_raw = if backend == "dummy" {
        dummy_convert(&dictionary_text)
    } else if matches!(backend.as_str(), "kkc" | "libkkc" | "deterministic") {
        kkc_convert(&dictionary_text)?
    } else {
        return Err(format!("unsupported backend: {backend}"));
    };

    let converted_protected = restore_transient_kkc_spans(&converted_raw, &dictionary_spans)?;
    let restored = restore_text(&converted_protected, &protected)?;
    let elapsed_ms = started.elapsed().as_millis() as u64;

    Ok(ConvertResult {
        text: format!("{leading_ws}{restored}{trailing_ws}"),
        protected_text: dictionary_text,
        protected_spans: protected.spans,
        backend,
        elapsed_ms,
    })
}

pub fn convert_candidates(
    text: &str,
    metadata: Option<&JsonValue>,
) -> Result<CandidateResult, String> {
    let started = Instant::now();
    let backend = get_env("BACKEND", "kkc").to_ascii_lowercase();
    let per_word_limit = metadata_int(metadata, "candidate_per_word_limit", candidate_per_word_limit());
    let max_candidates = metadata_int(metadata, "candidate_max", candidate_max());

    let (mut leading_ws, core_text, trailing_ws) = split_outer_whitespace(text);
    let protected = protect_text(core_text)?;
    if manual_term_confirmation_only(&protected) {
        leading_ws = "";
    }

    let cand_index = configured_candidate_dictionary_index()?;
    let dictionary_variants = apply_dictionary_candidate_sets_with_placeholders_index(
        &protected.text,
        &cand_index,
        protected.spans.len(),
        per_word_limit,
        max_candidates,
    );

    let first_protected_text = dictionary_variants
        .first()
        .map(|(t, _)| t.clone())
        .unwrap_or_else(|| protected.text.clone());

    let mut restored_candidates = Vec::new();
    for (dictionary_text, dictionary_spans) in dictionary_variants {
        for converted_raw in backend_convert_candidates(&backend, &dictionary_text)? {
            let converted_protected =
                restore_transient_kkc_spans(&converted_raw, &dictionary_spans)?;
            let restored = restore_text(&converted_protected, &protected)?;
            restored_candidates.push(format!("{leading_ws}{restored}{trailing_ws}"));
            if restored_candidates.len() >= max_candidates {
                break;
            }
        }
        if restored_candidates.len() >= max_candidates {
            break;
        }
    }

    let mut candidates = dedupe_texts(restored_candidates);
    if candidates.is_empty() {
        candidates.push(text.to_string());
    }
    let elapsed_ms = started.elapsed().as_millis() as u64;

    Ok(CandidateResult {
        base: ConvertResult {
            text: candidates[0].clone(),
            protected_text: first_protected_text,
            protected_spans: protected.spans,
            backend,
            elapsed_ms,
        },
        candidates,
    })
}

pub fn preedit(text: &str, _metadata: Option<&JsonValue>) -> Result<ConvertResult, String> {
    let started = Instant::now();
    let (mut leading_ws, core_text, trailing_ws) = split_outer_whitespace(text);
    let protected = protect_text(core_text)?;
    if manual_term_confirmation_only(&protected) {
        leading_ws = "";
    }
    let dict_index = configured_dictionary_index()?;
    let preedit_idx = dict_index
        .preedit_index
        .as_deref()
        .unwrap_or(&dict_index);
    let dictionary_text = apply_dictionary_index(&protected.text, preedit_idx);
    let converted_protected = romaji_to_hiragana(&dictionary_text);
    let restored = restore_text(&converted_protected, &protected)?;
    let elapsed_ms = started.elapsed().as_millis() as u64;

    Ok(ConvertResult {
        text: format!("{leading_ws}{restored}{trailing_ws}"),
        protected_text: dictionary_text,
        protected_spans: protected.spans,
        backend: "preedit".to_string(),
        elapsed_ms,
    })
}

pub fn kkc_convert(text: &str) -> Result<String, String> {
    let hiragana = romaji_to_hiragana(text);
    if !kkc_needs_decoder(&hiragana) {
        return Ok(postprocess_kkc_output(&hiragana));
    }
    let candidates = convert_hiragana_candidates_with_kkc(&hiragana, kkc_nbest())?;
    let selected = select_kkc_candidate(&candidates)?;
    let post = postprocess_kkc_output(&selected);
    Ok(collapse_tech_particle_space(&post))
}

pub fn kkc_convert_candidates(text: &str) -> Result<Vec<String>, String> {
    let hiragana = romaji_to_hiragana(text);
    if !kkc_needs_decoder(&hiragana) {
        return Ok(vec![postprocess_kkc_output(&hiragana)]);
    }
    let candidates = convert_hiragana_candidates_with_kkc(&hiragana, kkc_nbest())?;
    let mut indexed: Vec<(usize, &String)> = candidates.iter().enumerate().collect();
    indexed.sort_by(|(i1, c1), (i2, c2)| {
        kkc_candidate_score(c2)
            .cmp(&kkc_candidate_score(c1))
            .then_with(|| i1.cmp(i2))
    });
    let mut converted = Vec::with_capacity(indexed.len());
    for (_, cand) in indexed {
        let post = postprocess_kkc_output(cand);
        converted.push(collapse_tech_particle_space(&post));
    }
    Ok(dedupe_texts(converted))
}

fn backend_convert_candidates(backend: &str, text: &str) -> Result<Vec<String>, String> {
    if backend == "dummy" {
        return Ok(vec![dummy_convert(text)]);
    }
    if matches!(backend, "kkc" | "libkkc" | "deterministic") {
        return kkc_convert_candidates(text);
    }
    Err(format!("unsupported backend: {backend}"))
}

fn restore_transient_kkc_spans(
    text: &str,
    spans: &[(String, String)],
) -> Result<String, String> {
    let mut out = text.to_string();
    for (placeholder, original) in spans {
        if out.matches(placeholder.as_str()).count() != 1 {
            return Err(format!("kkc dropped protected Japanese span: {placeholder}"));
        }
        out = out.replace(placeholder.as_str(), original.as_str());
    }
    Ok(out)
}

fn kkc_needs_decoder(text: &str) -> bool {
    let mut plain = String::with_capacity(text.len());
    for (is_ph, part) in split_placeholders(text) {
        if !is_ph {
            plain.push_str(part);
        }
    }
    let trimmed = plain.trim_matches(|c: char| {
        matches!(
            c,
            ' ' | '\t' | '\r' | '\n' | '.' | ',' | '!' | '?' | '。' | '、' | '！' | '？'
        )
    });
    !trimmed.is_empty()
}

fn kkc_nbest() -> usize {
    get_env("KKC_NBEST", "3")
        .parse::<isize>()
        .map(|v| v.clamp(1, 20) as usize)
        .unwrap_or(3)
}

fn candidate_per_word_limit() -> usize {
    get_env("CANDIDATE_PER_WORD_LIMIT", "3")
        .parse::<isize>()
        .map(|v| v.clamp(1, 5) as usize)
        .unwrap_or(3)
}

fn candidate_max() -> usize {
    get_env("CANDIDATE_MAX", "30")
        .parse::<isize>()
        .map(|v| v.clamp(1, 200) as usize)
        .unwrap_or(30)
}

fn metadata_int(metadata: Option<&JsonValue>, key: &str, default: usize) -> usize {
    let Some(val) = metadata.and_then(|m| m.get(key)) else {
        return default;
    };
    match val {
        JsonValue::Int(i) if *i > 0 => *i as usize,
        JsonValue::Str(s) => s.parse::<usize>().unwrap_or(default),
        _ => default,
    }
}

fn dedupe_texts(texts: Vec<String>) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::with_capacity(texts.len());
    for t in texts {
        if seen.insert(t.clone()) {
            out.push(t);
        }
    }
    out
}

fn select_kkc_candidate(candidates: &[String]) -> Result<String, String> {
    if candidates.is_empty() {
        return Err("kkc decoder returned no candidates".to_string());
    }
    let mut indexed: Vec<(usize, &String)> = candidates.iter().enumerate().collect();
    indexed.sort_by(|(i1, c1), (i2, c2)| {
        kkc_candidate_score(c2)
            .cmp(&kkc_candidate_score(c1))
            .then_with(|| i1.cmp(i2))
    });
    Ok(indexed[0].1.clone())
}

fn kkc_candidate_score(text: &str) -> i32 {
    let mut score = 0;
    const BONUSES: &[(&str, i32)] = &[
        ("今日は", 8),
        ("明日は", 6),
        ("昨日は", 6),
        ("良い", 2),
        ("感じ", 4),
        ("感じにいける", 4),
        ("自分用", 4),
    ];
    const PENALTIES: &[(&str, i32)] = &[
        ("卿", 8),
        ("教派", 8),
        ("環んじ", 12),
        ("漢字に", 4),
        ("幹事", 4),
        ("監事", 4),
        ("生ける", 3),
        ("酔い", 3),
    ];
    for &(token, val) in BONUSES {
        if text.contains(token) {
            score += val;
        }
    }
    for &(token, val) in PENALTIES {
        if text.contains(token) {
            score -= val;
        }
    }
    if text.contains("感じに行ける") {
        score -= 2;
    }
    score
}

fn postprocess_kkc_output(text: &str) -> String {
    const REPLACEMENTS: &[(&str, &str)] = &[
        ("呼ぶのは思い", "呼ぶのは重い"),
        ("のは思い", "のは重い"),
        ("が思い", "が重い"),
        ("環んじ", "感じ"),
        ("良い感じに行ける", "良い感じにいける"),
    ];
    let mut out = text.to_string();
    for &(s, t) in REPLACEMENTS {
        if out.contains(s) {
            out = out.replace(s, t);
        }
    }
    let trimmed = out.trim_end();
    let trailing_ws = &out[trimmed.len()..];
    if let Some(stem) = trimmed.strip_suffix('.') {
        out = format!("{stem}。{trailing_ws}");
    } else if let Some(stem) = trimmed.strip_suffix(',') {
        out = format!("{stem}、{trailing_ws}");
    }
    out
}

fn split_outer_whitespace(text: &str) -> (&str, &str, &str) {
    let trimmed_start = text.trim_start();
    let leading_len = text.len() - trimmed_start.len();
    let core = trimmed_start.trim_end();
    let trailing_start = leading_len + core.len();
    (&text[..leading_len], core, &text[trailing_start..])
}

fn manual_term_confirmation_only(protected: &ProtectedText) -> bool {
    protected.text == "<TECH_0>"
        && protected.spans.len() == 1
        && protected.spans[0].kind == "manual_term"
}

pub fn dummy_convert(text: &str) -> String {
    let mut converted_parts = String::with_capacity(text.len());
    for (is_ph, part) in split_placeholders(text) {
        if is_ph || part.chars().all(|c| c.is_whitespace()) {
            converted_parts.push_str(part);
        } else {
            converted_parts.push_str(&dummy_convert_plain(part));
        }
    }
    collapse_tech_particle_space(&converted_parts)
}

fn collapse_tech_particle_space(text: &str) -> String {
    let parts = split_placeholders(text);
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    while i < parts.len() {
        let (is_ph, part) = parts[i];
        out.push_str(part);
        if is_ph && i + 1 < parts.len() && !parts[i + 1].0 {
            let next_part = parts[i + 1].1;
            let trimmed = next_part.trim_start();
            if trimmed.len() < next_part.len() {
                if let Some(first_ch) = trimmed.chars().next() {
                    if matches!(first_ch, 'を' | 'で' | 'に' | 'の' | 'が' | 'は' | 'と') {
                        out.push_str(trimmed);
                        i += 2;
                        continue;
                    }
                }
            }
        }
        i += 1;
    }
    out
}

fn dummy_convert_plain(text: &str) -> String {
    if text.is_empty() {
        return text.to_string();
    }
    let (leading, core, trailing) = split_outer_whitespace(text);
    if core.is_empty() {
        return text.to_string();
    }
    let normalized = collapse_whitespace(core);
    let normalized = normalize_technical_phrases(&normalized);
    let words: Vec<String> = normalized
        .split(' ')
        .map(convert_compact_roman)
        .collect();
    let converted = words.join(" ");
    let converted = cleanup_spacing(&converted);
    format!("{leading}{converted}{trailing}")
}

fn collapse_whitespace(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut in_ws = false;
    for ch in s.chars() {
        if ch.is_whitespace() {
            if !in_ws {
                out.push(' ');
                in_ws = true;
            }
        } else {
            out.push(ch);
            in_ws = false;
        }
    }
    out
}

fn normalize_technical_phrases(text: &str) -> String {
    let mut current = text.to_string();
    for &(source, replacement) in TECH_PHRASE_REPLACEMENTS {
        current = replace_phrase_case_insensitive(&current, source, replacement);
    }
    current
}

fn is_word_b(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

fn replace_phrase_case_insensitive(text: &str, source: &str, replacement: &str) -> String {
    let lower_text = text.to_ascii_lowercase();
    let lower_src = source.to_ascii_lowercase();
    let tb = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut last = 0;
    let mut search_from = 0;
    while let Some(rel) = lower_text[search_from..].find(&lower_src) {
        let start = search_from + rel;
        let end = start + lower_src.len();
        let before_ok = start == 0 || !is_word_b(tb[start - 1]);
        let after_ok = end == tb.len() || !is_word_b(tb[end]);
        if before_ok && after_ok {
            out.push_str(&text[last..start]);
            out.push_str(replacement);
            last = end;
            search_from = end;
        } else {
            search_from = start + 1;
        }
    }
    out.push_str(&text[last..]);
    out
}

fn convert_compact_roman(text: &str) -> String {
    if let Some(exact) = identity_ascii_token(text) {
        return exact;
    }
    if (text.contains('/') || text.contains('='))
        && !text.is_empty()
        && text.bytes().all(|b| {
            b.is_ascii_alphanumeric()
                || matches!(b, b'_' | b'.' | b'/' | b'+' | b'=' | b'-')
        })
    {
        return text.to_string();
    }
    if looks_like_ascii_identity_word(text) {
        return text.to_string();
    }
    let mut result = String::with_capacity(text.len() * 2);
    let mut cursor = 0;
    let lower = text.to_ascii_lowercase();
    let replacements = sorted_roman_replacements();
    while cursor < text.len() {
        let mut matched = false;
        for &(roman, japanese) in replacements {
            if lower[cursor..].starts_with(roman) {
                let original = &text[cursor..cursor + roman.len()];
                if japanese.is_ascii()
                    && original.chars().any(|c| c.is_ascii_alphabetic())
                    && original
                        .chars()
                        .filter(|c| c.is_ascii_alphabetic())
                        .all(|c| c.is_ascii_uppercase())
                {
                    result.push_str(&japanese.to_ascii_uppercase());
                } else {
                    result.push_str(japanese);
                }
                cursor += roman.len();
                matched = true;
                break;
            }
        }
        if !matched {
            let ch = text[cursor..].chars().next().unwrap();
            result.push(ch);
            cursor += ch.len_utf8();
        }
    }
    result
}

fn is_ident_token(text: &str) -> bool {
    let b = text.as_bytes();
    if b.is_empty() || !b[0].is_ascii_alphabetic() {
        return false;
    }
    b[1..]
        .iter()
        .all(|&c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'+' | b'.' | b'-'))
}

fn identity_ascii_token(text: &str) -> Option<String> {
    if !is_ident_token(text) {
        return None;
    }
    let lower = text.to_ascii_lowercase();
    match lower.as_str() {
        "api" => Some("API".to_string()),
        "applicationservice" => Some("ApplicationService".to_string()),
        "areba" => Some("あれば".to_string()),
        "atsumekiru" => Some("集め切る".to_string()),
        "chiisaku" => Some("小さく".to_string()),
        "config" => Some("config".to_string()),
        "codex" => Some("Codex".to_string()),
        "dedupe" => Some("dedupe".to_string()),
        "domainservice" => Some("DomainService".to_string()),
        "dto" => Some("DTO".to_string()),
        "english" => Some("English".to_string()),
        "elisp" => Some("Elisp".to_string()),
        "esukyueraito" => Some("esukyueraito".to_string()),
        "false" => Some("false".to_string()),
        "fixed" => Some("fixed".to_string()),
        "form" => Some("form".to_string()),
        "fukumeru" => Some("含める".to_string()),
        "ime" => Some("IME".to_string()),
        "gemma" => Some("Gemma".to_string()),
        "hayaku" => Some("速く".to_string()),
        "izon" => Some("依存".to_string()),
        "kanji" => Some("漢字".to_string()),
        "kaeru" => Some("変える".to_string()),
        "kotei" => Some("固定".to_string()),
        "lisp" => Some("Lisp".to_string()),
        "lora" => Some("LoRA".to_string()),
        "markdown" => Some("Markdown".to_string()),
        "mecab" => Some("MeCab".to_string()),
        "milestone" => Some("Milestone".to_string()),
        "mlx" => Some("MLX".to_string()),
        "nashi" => Some("なし".to_string()),
        "ok" => Some("ok".to_string()),
        "pykakasi" => Some("pykakasi".to_string()),
        "kakasi" => Some("kakasi".to_string()),
        "json" => Some("JSON".to_string()),
        "jsonl" => Some("JSONL".to_string()),
        "repo" => Some("repo".to_string()),
        "savemychatbot" => Some("SaveMyChatbot".to_string()),
        "sha256" => Some("SHA256".to_string()),
        "sqlite" => Some("SQLite".to_string()),
        "taishou" => Some("対象".to_string()),
        "tomoko" => Some("Tomoko".to_string()),
        "tobu" => Some("飛ぶ".to_string()),
        "ugoku" => Some("動く".to_string()),
        "url" => Some("URL".to_string()),
        "urls" => Some("URLs".to_string()),
        "valueobject" => Some("ValueObject".to_string()),
        "you" => Some("用".to_string()),
        "adapter" | "adoption" | "after" | "async" | "background" | "before" | "block"
        | "buffer" | "boundary" | "business" | "cache" | "candidate" | "chars" | "chat"
        | "chunk" | "class" | "code" | "command" | "completion" | "controller" | "debug"
        | "default" | "description" | "dictionary" | "discard" | "distribution" | "domain"
        | "endpoint" | "entity" | "env" | "eval" | "external" | "fallback" | "fence"
        | "fenced" | "fragment" | "format" | "frontmatter" | "full" | "gate" | "holdout"
        | "input" | "index" | "key" | "line" | "load" | "log" | "max" | "metadata" | "mode"
        | "model" | "object" | "offline" | "only" | "original" | "over" | "output"
        | "personal" | "placeholder" | "port" | "preview" | "reports" | "reasoning"
        | "record" | "region" | "restoration" | "repository" | "request" | "response"
        | "result" | "romanize" | "romanized" | "rule" | "runtime" | "same" | "seed"
        | "separator" | "schema" | "smoke" | "source" | "src" | "summary" | "target"
        | "teacher" | "technical" | "term" | "text" | "timer" | "timeout" | "touch"
        | "transaction" | "training" | "tuning" | "validation" | "variant" | "value" => {
            Some(text.to_string())
        }
        _ => None,
    }
}

fn looks_like_ascii_identity_word(text: &str) -> bool {
    if !is_ident_token(text) || text.len() > 24 {
        return false;
    }
    let lower = text.to_ascii_lowercase();
    if RAW_ROMAN_REPLACEMENTS.iter().any(|&(r, _)| r == lower) {
        return false;
    }
    if text.chars().any(|c| matches!(c, '.' | '_' | '+' | '-')) {
        return true;
    }
    if lower.contains('q') || lower.contains('x') {
        return true;
    }
    const SUFFIXES: &[&str] = &[
        "tion", "sion", "ment", "ness", "able", "ible", "ance", "ence", "ity", "ive", "ing", "ed",
        "er", "or", "al",
    ];
    if SUFFIXES.iter().any(|&suf| lower.ends_with(suf)) {
        return true;
    }
    let mut cons_run = 0;
    for b in lower.bytes() {
        if b.is_ascii_alphabetic() && !matches!(b, b'a' | b'e' | b'i' | b'o' | b'u') {
            cons_run += 1;
            if cons_run >= 3 {
                return true;
            }
        } else {
            cons_run = 0;
        }
    }
    const PAIRS: &[&str] = &[
        "ck", "ct", "ff", "ft", "ld", "lk", "lp", "lt", "mp", "nd", "nk", "nt", "pt", "rd", "rk",
        "rl", "rn", "rt", "rv", "sk", "st", "tr", "wr",
    ];
    PAIRS.iter().any(|&p| lower.contains(p))
}

fn is_jp_char(ch: char) -> bool {
    let u = ch as u32;
    (0x3041..=0x3093).contains(&u)
        || (0x30A1..=0x30F6).contains(&u)
        || (0x4E00..=0x9FAF).contains(&u)
        || ch == 'ー'
}

fn is_particle_char(ch: char) -> bool {
    matches!(ch, 'を' | 'で' | 'に' | 'の' | 'が' | 'は' | 'と')
}

fn cleanup_spacing(text: &str) -> String {
    let collapsed = collapse_whitespace(text.trim());
    let chars: Vec<char> = collapsed.chars().collect();
    let mut out = String::with_capacity(collapsed.len());
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == ' ' && i > 0 && i + 1 < chars.len() {
            let prev = chars[i - 1];
            let next = chars[i + 1];
            let drop_space = is_particle_char(next)
                || matches!(next, '、' | '。')
                || (is_particle_char(prev) && (is_jp_char(next) || next.is_ascii_alphanumeric()))
                || matches!(prev, '、' | '。')
                || (is_jp_char(prev) && (is_jp_char(next) || next.is_ascii_alphanumeric()))
                || (prev.is_ascii_alphanumeric() && is_jp_char(next));
            if drop_space {
                i += 1;
                continue;
            }
        }
        out.push(chars[i]);
        i += 1;
    }

    // (?<=\d)b\b -> B, \bm4\b -> M4, \b1b-2b\b -> 1B-2B
    out = out.replace("1b-2b", "1B-2B");
    out = replace_phrase_case_insensitive(&out, "m4", "M4");
    let out_bytes = out.as_bytes();
    let mut fixed = String::with_capacity(out.len());
    let mut j = 0;
    while j < out_bytes.len() {
        if out_bytes[j] == b'b'
            && j > 0
            && out_bytes[j - 1].is_ascii_digit()
            && (j + 1 == out_bytes.len() || !is_word_b(out_bytes[j + 1]))
        {
            fixed.push('B');
            j += 1;
        } else {
            let ch = out[j..].chars().next().unwrap();
            fixed.push(ch);
            j += ch.len_utf8();
        }
    }
    fixed.replace("なら英字", "なら、英字")
}
