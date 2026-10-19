#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProtectedSpan {
    pub placeholder: String,
    pub original: String,
    pub start: usize,
    pub end: usize,
    pub kind: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProtectedText {
    pub text: String,
    pub spans: Vec<ProtectedSpan>,
}

const PARTICLES: &[&str] = &[
    "kara", "made", "wo", "de", "ni", "ga", "ha", "wa", "to", "no", "mo",
];

const SHORT_ROMAJI_SEGMENTS: &[&str] = &[
    "a", "i", "u", "e", "o", "ka", "ki", "ku", "ke", "ko", "sa", "si", "shi", "su", "se", "so",
    "ta", "ti", "chi", "tu", "tsu", "te", "to", "na", "ni", "nu", "ne", "no", "ha", "hi", "hu",
    "fu", "he", "ho", "ma", "mi", "mu", "me", "mo", "ya", "yu", "yo", "ra", "ri", "ru", "re",
    "ro", "wa", "wo", "ga", "gi", "gu", "ge", "go", "za", "zi", "ji", "zu", "ze", "zo", "da",
    "di", "du", "de", "do", "ba", "bi", "bu", "be", "bo", "pa", "pi", "pu", "pe", "po",
];

const COMMANDS: &[&str] = &[
    "python3", "python", "emacs", "pnpm", "curl", "grep", "make", "git", "npm", "rg", "uv",
];

pub fn protect_text(text: &str) -> Result<ProtectedText, String> {
    if text.matches(";;").count() % 2 != 0 {
        return Err("manual term marker is unbalanced".to_string());
    }

    let mut candidates: Vec<(usize, usize, &'static str, usize)> = Vec::new();

    // 0: manual_term
    for (s, e) in find_manual_terms(text) {
        candidates.push((s, e, "manual_term", 0));
    }
    // 1: url
    for (s, e) in find_urls(text) {
        candidates.push((s, e, "url", 1));
    }
    // 2: lisp_form
    for (s, e) in find_lisp_forms(text) {
        candidates.push((s, e, "lisp_form", 2));
    }
    // 3: file_path
    for (s, e) in find_file_paths(text) {
        candidates.push((s, e, "file_path", 3));
    }
    // 4: api_path
    for (s, e) in find_api_paths(text) {
        candidates.push((s, e, "api_path", 4));
    }
    // 5: mx_command
    for (s, e) in find_mx_commands(text) {
        candidates.push((s, e, "mx_command", 5));
    }
    // 6: shell_invocation
    for (s, e) in find_shell_invocations(text) {
        candidates.push((s, e, "shell_invocation", 6));
    }
    // 7: keybinding
    for (s, e) in find_keybindings(text) {
        candidates.push((s, e, "keybinding", 7));
    }
    // 8: identifier
    for (s, e) in find_identifiers(text) {
        for (sub_s, sub_e) in split_identifier_candidate(&text[s..e], s) {
            candidates.push((sub_s, sub_e, "identifier", 8));
        }
    }
    // 9: likely_command
    for (s, e) in find_likely_commands(text) {
        candidates.push((s, e, "likely_command", 9));
    }

    candidates.sort_by(|a, b| {
        a.0.cmp(&b.0)
            .then_with(|| a.3.cmp(&b.3))
            .then_with(|| (b.1 - b.0).cmp(&(a.1 - a.0)))
    });

    let mut selected: Vec<(usize, usize, &'static str)> = Vec::new();
    let mut occupied: Vec<(usize, usize)> = Vec::new();
    for (start, end, kind, _) in candidates {
        if occupied
            .iter()
            .any(|&(old_start, old_end)| start < old_end && end > old_start)
        {
            continue;
        }
        selected.push((start, end, kind));
        occupied.push((start, end));
    }

    let mut parts = String::with_capacity(text.len());
    let mut spans = Vec::with_capacity(selected.len());
    let mut cursor = 0;
    for (index, (start, end, kind)) in selected.into_iter().enumerate() {
        let placeholder = format!("<TECH_{index}>");
        let raw_slice = &text[start..end];
        let original = if kind == "manual_term" {
            raw_slice[2..raw_slice.len() - 2].to_string()
        } else {
            raw_slice.to_string()
        };
        parts.push_str(&text[cursor..start]);
        parts.push_str(&placeholder);
        spans.push(ProtectedSpan {
            placeholder,
            original,
            start,
            end,
            kind: kind.to_string(),
        });
        cursor = end;
    }
    parts.push_str(&text[cursor..]);

    Ok(ProtectedText { text: parts, spans })
}

pub fn restore_text(converted_text: &str, protected: &ProtectedText) -> Result<String, String> {
    let found_placeholders = find_tech_placeholders(converted_text);
    let mut expected: Vec<&str> = protected
        .spans
        .iter()
        .map(|s| s.placeholder.as_str())
        .collect();
    expected.sort_unstable();

    let mut missing: Vec<&str> = Vec::new();
    for &exp in &expected {
        if !found_placeholders.iter().any(|f| f == exp) {
            missing.push(exp);
        }
    }

    let mut extra: Vec<String> = Vec::new();
    for f in &found_placeholders {
        if !expected.contains(&f.as_str()) && !extra.contains(f) {
            extra.push(f.clone());
        }
    }
    extra.sort();

    let mut duplicates: Vec<&str> = Vec::new();
    for &exp in &expected {
        let count = found_placeholders.iter().filter(|f| f.as_str() == exp).count();
        if count > 1 {
            duplicates.push(exp);
        }
    }

    if !missing.is_empty() || !extra.is_empty() || !duplicates.is_empty() {
        let mut detail = Vec::new();
        if !missing.is_empty() {
            detail.push(format!("missing={}", missing.join(",")));
        }
        if !extra.is_empty() {
            detail.push(format!("extra={}", extra.join(",")));
        }
        if !duplicates.is_empty() {
            detail.push(format!("duplicates={}", duplicates.join(",")));
        }
        return Err(format!(
            "placeholder restoration failed: {}",
            detail.join(" ")
        ));
    }

    let mut restored = converted_text.to_string();
    for span in &protected.spans {
        restored = restored.replace(&span.placeholder, &span.original);
    }
    if !find_tech_placeholders(&restored).is_empty() {
        return Err("placeholder restoration failed: unresolved placeholder".to_string());
    }
    Ok(restored)
}

pub fn protected_tokens(text: &str) -> Result<Vec<String>, String> {
    Ok(protect_text(text)?
        .spans
        .into_iter()
        .map(|s| s.original)
        .collect())
}

pub fn find_tech_placeholders(text: &str) -> Vec<String> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i + 7 < bytes.len() {
        if &bytes[i..i + 6] == b"<TECH_" {
            let mut j = i + 6;
            while j < bytes.len() && bytes[j].is_ascii_digit() {
                j += 1;
            }
            if j > i + 6 && j < bytes.len() && bytes[j] == b'>' {
                out.push(text[i..=j].to_string());
                i = j + 1;
                continue;
            }
        }
        i += 1;
    }
    out
}

fn is_word_char(ch: char) -> bool {
    ch.is_alphanumeric() || ch == '_'
}

fn is_word_boundary_before(text: &str, byte_idx: usize) -> bool {
    if !text.is_char_boundary(byte_idx) {
        return false;
    }
    let prev_is_word = text[..byte_idx]
        .chars()
        .next_back()
        .map(is_word_char)
        .unwrap_or(false);
    let next_is_word = text[byte_idx..]
        .chars()
        .next()
        .map(is_word_char)
        .unwrap_or(false);
    prev_is_word != next_is_word
}

fn is_word_boundary_after(text: &str, byte_idx: usize) -> bool {
    is_word_boundary_before(text, byte_idx)
}

fn is_lisp_sym_char(b: u8) -> bool {
    b.is_ascii_alphanumeric()
        || matches!(
            b,
            b'_' | b'+' | b'*' | b'/' | b'<' | b'>' | b'=' | b'!' | b'?' | b'$' | b'%' | b'&'
                | b'~' | b'.' | b'^' | b':' | b'-'
        )
}

fn is_file_path_char(b: u8) -> bool {
    b.is_ascii_alphanumeric()
        || matches!(
            b,
            b'.' | b'_' | b'~' | b':' | b'@' | b'%' | b'+' | b',' | b'-' | b'=' | b'/'
        )
}

fn is_api_seg_char(b: u8) -> bool {
    b.is_ascii_alphanumeric()
        || matches!(
            b,
            b'.' | b'_' | b'~' | b':' | b'@' | b'%' | b'+' | b',' | b'-'
        )
}

fn find_manual_terms(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i + 4 <= bytes.len() {
        if bytes[i] == b';' && bytes[i + 1] == b';' {
            let mut j = i + 2;
            while j < bytes.len() && bytes[j] != b';' && bytes[j] != b'\n' {
                j += 1;
            }
            if j > i + 2 && j + 1 < bytes.len() && bytes[j] == b';' && bytes[j + 1] == b';' {
                out.push((i, j + 2));
                i = j + 2;
                continue;
            }
        }
        i += 1;
    }
    out
}

fn find_urls(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i + 8 <= bytes.len() {
        let prefix_len = if bytes[i..].starts_with(b"http://") {
            7
        } else if bytes[i..].starts_with(b"https://") {
            8
        } else {
            i += 1;
            continue;
        };
        let mut j = i + prefix_len;
        while j < bytes.len() {
            let ch = text[j..].chars().next().unwrap();
            if ch.is_whitespace() || matches!(ch, '<' | '>' | '(' | ')' | '"' | '\'') {
                break;
            }
            j += ch.len_utf8();
        }
        if j > i + prefix_len {
            out.push((i, j));
            i = j;
        } else {
            i += 1;
        }
    }
    out
}

fn find_lisp_forms(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] != b'(' {
            i += 1;
            continue;
        }
        let mut j = i + 1;
        while j < bytes.len() && is_lisp_sym_char(bytes[j]) {
            j += 1;
        }
        if j == i + 1 {
            i += 1;
            continue;
        }
        let mut last_valid_close = if j < bytes.len() && bytes[j] == b')' {
            Some(j + 1)
        } else {
            None
        };
        // (?:\s+[^()\n]+)*\)
        let mut k = j;
        loop {
            let ws_start = k;
            while k < bytes.len() && (bytes[k] == b' ' || bytes[k] == b'\t' || bytes[k] == b'\r') {
                k += 1;
            }
            if k == ws_start {
                break;
            }
            let body_start = k;
            while k < bytes.len() && bytes[k] != b'(' && bytes[k] != b')' && bytes[k] != b'\n' {
                let ch = text[k..].chars().next().unwrap();
                k += ch.len_utf8();
            }
            if k > body_start && k < bytes.len() && bytes[k] == b')' {
                last_valid_close = Some(k + 1);
            }
            break;
        }
        if let Some(end) = last_valid_close {
            out.push((i, end));
            i = end;
        } else {
            i += 1;
        }
    }
    out
}

fn find_file_paths(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        let slash_pos = if bytes[i] == b'/' {
            Some(i)
        } else if bytes[i] == b'~' && i + 1 < bytes.len() && bytes[i + 1] == b'/' {
            Some(i + 1)
        } else if bytes[i] == b'.' && i + 1 < bytes.len() && bytes[i + 1] == b'/' {
            Some(i + 1)
        } else if bytes[i] == b'.'
            && i + 2 < bytes.len()
            && bytes[i + 1] == b'.'
            && bytes[i + 2] == b'/'
        {
            Some(i + 2)
        } else {
            None
        };
        if let Some(sp) = slash_pos {
            let mut j = sp + 1;
            while j < bytes.len() && is_file_path_char(bytes[j]) {
                j += 1;
            }
            if j > sp + 1 {
                out.push((i, j));
                i = j;
                continue;
            }
        }
        i += 1;
    }
    out
}

fn find_api_paths(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] != b'/' {
            i += 1;
            continue;
        }
        let mut j = i + 1;
        while j < bytes.len() && is_api_seg_char(bytes[j]) {
            j += 1;
        }
        if j == i + 1 {
            i += 1;
            continue;
        }
        let mut segments = 1;
        loop {
            if j < bytes.len() && bytes[j] == b'/' {
                let mut k = j + 1;
                while k < bytes.len() && is_api_seg_char(bytes[k]) {
                    k += 1;
                }
                if k > j + 1 {
                    segments += 1;
                    j = k;
                    continue;
                }
            }
            break;
        }
        if segments >= 2 {
            out.push((i, j));
            i = j;
        } else {
            i += 1;
        }
    }
    out
}

fn find_mx_commands(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i + 4 < bytes.len() {
        if &bytes[i..i + 3] == b"M-x" && is_word_boundary_before(text, i) {
            let mut j = i + 3;
            while j < bytes.len() && bytes[j].is_ascii_whitespace() {
                j += 1;
            }
            if j > i + 3 {
                let cmd_start = j;
                while j < bytes.len() && is_lisp_sym_char(bytes[j]) {
                    j += 1;
                }
                while j > cmd_start && !is_word_boundary_after(text, j) {
                    j -= 1;
                }
                if j > cmd_start {
                    out.push((i, j));
                    i = j;
                    continue;
                }
            }
        }
        i += 1;
    }
    out
}

fn match_command_at(text: &str, i: usize) -> Option<usize> {
    if !is_word_boundary_before(text, i) {
        return None;
    }
    let rest = &text.as_bytes()[i..];
    for &cmd in COMMANDS {
        let cb = cmd.as_bytes();
        if rest.starts_with(cb) {
            let end = i + cb.len();
            if is_word_boundary_after(text, end) {
                return Some(end);
            }
        }
    }
    None
}

fn find_shell_invocations(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if let Some(mut end) = match_command_at(text, i) {
            loop {
                let mut k = end;
                while k < bytes.len() && bytes[k].is_ascii_whitespace() && bytes[k] != b'\n' {
                    k += 1;
                }
                if k == end {
                    break;
                }
                let mut dashes = 0;
                while k < bytes.len() && bytes[k] == b'-' && dashes < 2 {
                    dashes += 1;
                    k += 1;
                }
                if dashes == 0 || k >= bytes.len() || !bytes[k].is_ascii_alphanumeric() {
                    break;
                }
                k += 1;
                while k < bytes.len() && (bytes[k].is_ascii_alphanumeric() || bytes[k] == b'-') {
                    k += 1;
                }
                end = k;
            }
            out.push((i, end));
            i = end;
        } else {
            i += 1;
        }
    }
    out
}

fn find_likely_commands(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if let Some(end) = match_command_at(text, i) {
            out.push((i, end));
            i = end;
        } else {
            i += 1;
        }
    }
    out
}

fn is_key_first_char(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'<' | b'>' | b'?' | b'/' | b'-')
}

fn find_keybindings(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i + 3 <= bytes.len() {
        if matches!(bytes[i], b'C' | b'M' | b'S' | b'A' | b's')
            && bytes[i + 1] == b'-'
            && is_key_first_char(bytes[i + 2])
            && is_word_boundary_before(text, i)
        {
            let mut j = i + 2;
            while j < bytes.len() && is_key_first_char(bytes[j]) {
                j += 1;
            }
            let mut best_end = None;
            let mut probe = j;
            while probe > i + 2 {
                if is_word_boundary_after(text, probe) {
                    best_end = Some(probe);
                    break;
                }
                probe -= 1;
            }
            let mut cur = j;
            loop {
                let mut k = cur;
                while k < bytes.len() && bytes[k].is_ascii_whitespace() && bytes[k] != b'\n' {
                    k += 1;
                }
                if k == cur {
                    break;
                }
                if k + 2 <= bytes.len()
                    && matches!(bytes[k], b'C' | b'M' | b'S' | b'A' | b's')
                    && bytes[k + 1] == b'-'
                {
                    k += 2;
                }
                if k < bytes.len() && bytes[k].is_ascii_alphanumeric() {
                    k += 1;
                    cur = k;
                    if is_word_boundary_after(text, cur) {
                        best_end = Some(cur);
                    }
                } else if k < bytes.len() && bytes[k] == b'<' {
                    let mut m = k + 1;
                    while m < bytes.len() && bytes[m] != b'>' && bytes[m] != b'\n' {
                        m += 1;
                    }
                    if m > k + 1 && m < bytes.len() && bytes[m] == b'>' {
                        cur = m + 1;
                        if is_word_boundary_after(text, cur) {
                            best_end = Some(cur);
                        }
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            if let Some(end) = best_end {
                out.push((i, end));
                i = end;
                continue;
            }
        }
        i += 1;
    }
    out
}

fn find_identifiers(text: &str) -> Vec<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i].is_ascii_alphabetic() && is_word_boundary_before(text, i) {
            let mut j = i + 1;
            while j < bytes.len() && bytes[j].is_ascii_alphanumeric() {
                j += 1;
            }
            let mut segments = 0;
            loop {
                if j + 1 < bytes.len()
                    && (bytes[j] == b'-' || bytes[j] == b'_')
                    && bytes[j + 1].is_ascii_alphanumeric()
                {
                    j += 2;
                    while j < bytes.len() && bytes[j].is_ascii_alphanumeric() {
                        j += 1;
                    }
                    segments += 1;
                } else {
                    break;
                }
            }
            if segments >= 1 {
                out.push((i, j));
                i = j;
                continue;
            }
        }
        i += 1;
    }
    out
}

fn split_identifier_candidate(value: &str, absolute_start: usize) -> Vec<(usize, usize)> {
    let mut spans = Vec::new();
    let mut offset = 0;
    while offset < value.len() {
        if let Some((particle_start, particle_end)) = find_join_to_next_identifier(value, offset) {
            append_identifier_span(&mut spans, value, absolute_start, offset, particle_start);
            offset = particle_end;
            continue;
        }
        if let Some(terminal) = find_terminal_particle(value, offset) {
            append_identifier_span(&mut spans, value, absolute_start, offset, terminal);
        } else {
            append_identifier_span(&mut spans, value, absolute_start, offset, value.len());
        }
        break;
    }
    spans
}

fn append_identifier_span(
    spans: &mut Vec<(usize, usize)>,
    value: &str,
    absolute_start: usize,
    start: usize,
    end: usize,
) {
    let candidate = &value[start..end];
    if is_upper_constant(candidate) {
        return;
    }
    if looks_like_short_hyphenated_romaji(candidate) {
        return;
    }
    if candidate.contains('-') || candidate.contains('_') {
        spans.push((absolute_start + start, absolute_start + end));
    }
}

fn is_upper_constant(s: &str) -> bool {
    let bytes = s.as_bytes();
    if bytes.len() < 2 || !bytes[0].is_ascii_uppercase() {
        return false;
    }
    bytes[1..]
        .iter()
        .all(|&b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_')
}

fn looks_like_short_hyphenated_romaji(value: &str) -> bool {
    let lowered = value.to_ascii_lowercase();
    if lowered.contains('_') || lowered.matches('-').count() != 1 {
        return false;
    }
    let mut parts = lowered.split('-');
    let first = parts.next().unwrap_or("");
    let second = parts.next().unwrap_or("");
    SHORT_ROMAJI_SEGMENTS.contains(&first)
        && short_romaji_segment_with_optional_particle_p(second)
}

fn short_romaji_segment_with_optional_particle_p(value: &str) -> bool {
    if SHORT_ROMAJI_SEGMENTS.contains(&value) {
        return true;
    }
    for &seg in SHORT_ROMAJI_SEGMENTS {
        if let Some(rest) = value.strip_prefix(seg) {
            if PARTICLES.contains(&rest) {
                return true;
            }
        }
    }
    false
}

fn starts_with_next_ident(s: &str) -> bool {
    let bytes = s.as_bytes();
    if bytes.is_empty() || !bytes[0].is_ascii_alphabetic() {
        return false;
    }
    let mut i = 1;
    while i < bytes.len() && bytes[i].is_ascii_alphanumeric() {
        i += 1;
    }
    i < bytes.len() && (bytes[i] == b'-' || bytes[i] == b'_')
}

fn find_join_to_next_identifier(value: &str, start: usize) -> Option<(usize, usize)> {
    for index in (start + 1)..value.len() {
        for &particle in PARTICLES {
            if !value[index..].starts_with(particle) {
                continue;
            }
            let prefix = &value[start..index];
            let suffix = &value[index + particle.len()..];
            if (!prefix.contains('-') && !prefix.contains('_')) || suffix.is_empty() {
                continue;
            }
            if prefix.ends_with('-') || prefix.ends_with('_') {
                continue;
            }
            if starts_with_next_ident(suffix) {
                return Some((index, index + particle.len()));
            }
        }
    }
    None
}

fn find_terminal_particle(value: &str, start: usize) -> Option<usize> {
    for index in (start + 1)..value.len() {
        for &particle in PARTICLES {
            if !value[index..].starts_with(particle) {
                continue;
            }
            let prefix = &value[start..index];
            let suffix = &value[index + particle.len()..];
            if (!prefix.contains('-') && !prefix.contains('_')) || suffix.is_empty() {
                continue;
            }
            if prefix.ends_with('-')
                || prefix.ends_with('_')
                || suffix.contains('-')
                || suffix.contains('_')
            {
                continue;
            }
            if suffix.len() < 4 || !looks_like_romanized_tail(suffix) {
                continue;
            }
            return Some(index);
        }
    }
    None
}

fn looks_like_romanized_tail(value: &str) -> bool {
    let lowered = value.to_ascii_lowercase();
    const MARKERS: &[&str] = &[
        "suru", "shinai", "shitai", "shita", "yobu", "yomu", "deki", "naru", "naka", "toki",
        "mama", "omoi",
    ];
    MARKERS.iter().any(|&m| lowered.contains(m))
}
