pub fn romaji_to_hiragana(text: &str) -> String {
    let mut out = String::with_capacity(text.len() * 2);
    for (is_placeholder, part) in split_placeholders(text) {
        if is_placeholder {
            out.push_str(part);
        } else {
            out.push_str(&plain_romaji_to_hiragana(part));
        }
    }
    out
}

pub fn split_placeholders(text: &str) -> Vec<(bool, &str)> {
    let bytes = text.as_bytes();
    let mut parts = Vec::new();
    let mut last = 0;
    let mut i = 0;
    while i + 7 < bytes.len() {
        if &bytes[i..i + 6] == b"<TECH_" {
            let mut j = i + 6;
            while j < bytes.len() && bytes[j].is_ascii_digit() {
                j += 1;
            }
            if j > i + 6 && j < bytes.len() && bytes[j] == b'>' {
                if i > last {
                    parts.push((false, &text[last..i]));
                }
                parts.push((true, &text[i..=j]));
                i = j + 1;
                last = i;
                continue;
            }
        }
        i += 1;
    }
    if last < text.len() || parts.is_empty() {
        parts.push((false, &text[last..]));
    }
    parts
}

pub fn normalize_romaji(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    while i < chars.len() {
        if i + 2 < chars.len()
            && chars[i].eq_ignore_ascii_case(&'n')
            && chars[i + 1].eq_ignore_ascii_case(&'n')
            && is_consonant_no_n_y(chars[i + 2])
        {
            out.push('n');
            i += 2;
        } else {
            out.push(chars[i]);
            i += 1;
        }
    }
    normalize_jibun_n(&out)
}

fn is_vowel_or_y(ch: char) -> bool {
    matches!(
        ch.to_ascii_lowercase(),
        'a' | 'e' | 'i' | 'o' | 'u' | 'y'
    )
}

fn normalize_jibun_n(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len() + 4);
    let mut i = 0;
    while i < chars.len() {
        // ((?:ji|zi|じ)bun|じぶn)(?=[aeiouy])
        let matched_len = if i + 5 < chars.len()
            && (chars[i].eq_ignore_ascii_case(&'j') || chars[i].eq_ignore_ascii_case(&'z'))
            && chars[i + 1].eq_ignore_ascii_case(&'i')
            && chars[i + 2].eq_ignore_ascii_case(&'b')
            && chars[i + 3].eq_ignore_ascii_case(&'u')
            && chars[i + 4].eq_ignore_ascii_case(&'n')
            && is_vowel_or_y(chars[i + 5])
        {
            Some(5)
        } else if i + 4 < chars.len()
            && chars[i] == 'じ'
            && chars[i + 1].eq_ignore_ascii_case(&'b')
            && chars[i + 2].eq_ignore_ascii_case(&'u')
            && chars[i + 3].eq_ignore_ascii_case(&'n')
            && is_vowel_or_y(chars[i + 4])
        {
            Some(4)
        } else if i + 3 < chars.len()
            && chars[i] == 'じ'
            && chars[i + 1] == 'ぶ'
            && chars[i + 2].eq_ignore_ascii_case(&'n')
            && is_vowel_or_y(chars[i + 3])
        {
            Some(3)
        } else {
            None
        };

        if let Some(len) = matched_len {
            for &c in &chars[i..i + len] {
                out.push(c);
            }
            out.push('\'');
            i += len;
        } else {
            out.push(chars[i]);
            i += 1;
        }
    }
    out
}

fn is_consonant_no_n_y(ch: char) -> bool {
    matches!(
        ch.to_ascii_lowercase(),
        'b' | 'c'
            | 'd'
            | 'f'
            | 'g'
            | 'h'
            | 'j'
            | 'k'
            | 'l'
            | 'm'
            | 'p'
            | 'q'
            | 'r'
            | 's'
            | 't'
            | 'v'
            | 'w'
            | 'x'
            | 'y'
            | 'z'
    )
}

fn plain_romaji_to_hiragana(text: &str) -> String {
    let normalized = normalize_romaji(text);
    let chars: Vec<char> = normalized.chars().collect();
    let mut result = String::with_capacity(normalized.len() * 2);
    let mut index = 0;
    while index < chars.len() {
        let ch = chars[index];
        if ch.is_whitespace() {
            index += 1;
            continue;
        }
        if ch == '-' && !result.is_empty() {
            result.push('ー');
            index += 1;
            continue;
        }
        if !ch.is_ascii() || !ch.is_ascii_alphabetic() {
            result.push(ch);
            index += 1;
            continue;
        }

        let c0 = ch.to_ascii_lowercase();
        let c1 = chars.get(index + 1).map(|c| c.to_ascii_lowercase());
        let c2 = chars.get(index + 2).map(|c| c.to_ascii_lowercase());

        if let Some(next_c) = c1 {
            if c0 == next_c && !matches!(c0, 'a' | 'e' | 'i' | 'o' | 'u' | 'n') {
                result.push('っ');
                index += 1;
                continue;
            }
            if c0 == 'n' && next_c == '\'' {
                result.push('ん');
                index += 2;
                continue;
            }
        }
        if c0 == 'n' {
            let next_is_vowel_or_y = c1
                .map(|nc| matches!(nc, 'a' | 'e' | 'i' | 'o' | 'u' | 'y'))
                .unwrap_or(false);
            if !next_is_vowel_or_y {
                result.push('ん');
                index += 1;
                continue;
            }
        }

        if let (Some(nc1), Some(nc2)) = (c1, c2) {
            let buf = [c0 as u8, nc1 as u8, nc2 as u8];
            if let Ok(s) = std::str::from_utf8(&buf) {
                if let Some(kana) = romaji_lookup(s) {
                    result.push_str(kana);
                    index += 3;
                    continue;
                }
            }
        }
        if let Some(nc1) = c1 {
            let buf = [c0 as u8, nc1 as u8];
            if let Ok(s) = std::str::from_utf8(&buf) {
                if let Some(kana) = romaji_lookup(s) {
                    result.push_str(kana);
                    index += 2;
                    continue;
                }
            }
        }
        let buf = [c0 as u8];
        if let Ok(s) = std::str::from_utf8(&buf) {
            if let Some(kana) = romaji_lookup(s) {
                result.push_str(kana);
                index += 1;
                continue;
            }
        }

        result.push(ch);
        index += 1;
    }
    result
}

fn romaji_lookup(chunk: &str) -> Option<&'static str> {
    match chunk {
        "a" => Some("あ"),
        "i" => Some("い"),
        "u" => Some("う"),
        "e" => Some("え"),
        "o" => Some("お"),
        "ka" => Some("か"),
        "ki" => Some("き"),
        "ku" => Some("く"),
        "ke" => Some("け"),
        "ko" => Some("こ"),
        "kya" => Some("きゃ"),
        "kyu" => Some("きゅ"),
        "kyo" => Some("きょ"),
        "ga" => Some("が"),
        "gi" => Some("ぎ"),
        "gu" => Some("ぐ"),
        "ge" => Some("げ"),
        "go" => Some("ご"),
        "gya" => Some("ぎゃ"),
        "gyu" => Some("ぎゅ"),
        "gyo" => Some("ぎょ"),
        "sa" => Some("さ"),
        "si" | "shi" => Some("し"),
        "su" => Some("す"),
        "se" => Some("せ"),
        "so" => Some("そ"),
        "sya" | "sha" => Some("しゃ"),
        "syu" | "shu" => Some("しゅ"),
        "syo" | "sho" => Some("しょ"),
        "za" => Some("ざ"),
        "zi" | "ji" => Some("じ"),
        "zu" => Some("ず"),
        "ze" => Some("ぜ"),
        "zo" => Some("ぞ"),
        "zya" | "ja" => Some("じゃ"),
        "zyu" | "ju" => Some("じゅ"),
        "zyo" | "jo" => Some("じょ"),
        "ta" => Some("た"),
        "ti" | "chi" => Some("ち"),
        "tu" | "tsu" => Some("つ"),
        "te" => Some("て"),
        "to" => Some("と"),
        "tya" | "cha" => Some("ちゃ"),
        "tyu" | "chu" => Some("ちゅ"),
        "tyo" | "cho" => Some("ちょ"),
        "da" => Some("だ"),
        "di" => Some("ぢ"),
        "du" => Some("づ"),
        "de" => Some("で"),
        "do" => Some("ど"),
        "dya" => Some("ぢゃ"),
        "dyu" => Some("ぢゅ"),
        "dyo" => Some("ぢょ"),
        "na" => Some("な"),
        "ni" => Some("に"),
        "nu" => Some("ぬ"),
        "ne" => Some("ね"),
        "no" => Some("の"),
        "nya" => Some("にゃ"),
        "nyu" => Some("にゅ"),
        "nyo" => Some("にょ"),
        "ha" => Some("は"),
        "hi" => Some("ひ"),
        "hu" | "fu" => Some("ふ"),
        "fa" => Some("ふぁ"),
        "fi" => Some("ふぃ"),
        "fe" => Some("ふぇ"),
        "fo" => Some("ふぉ"),
        "he" => Some("へ"),
        "ho" => Some("ほ"),
        "hya" => Some("ひゃ"),
        "hyu" => Some("ひゅ"),
        "hyo" => Some("ひょ"),
        "ba" => Some("ば"),
        "bi" => Some("び"),
        "bu" => Some("ぶ"),
        "be" => Some("べ"),
        "bo" => Some("ぼ"),
        "bya" => Some("びゃ"),
        "byu" => Some("びゅ"),
        "byo" => Some("びょ"),
        "pa" => Some("ぱ"),
        "pi" => Some("ぴ"),
        "pu" => Some("ぷ"),
        "pe" => Some("ぺ"),
        "po" => Some("ぽ"),
        "pya" => Some("ぴゃ"),
        "pyu" => Some("ぴゅ"),
        "pyo" => Some("ぴょ"),
        "ma" => Some("ま"),
        "mi" => Some("み"),
        "mu" => Some("む"),
        "me" => Some("め"),
        "mo" => Some("も"),
        "mya" => Some("みゃ"),
        "myu" => Some("みゅ"),
        "myo" => Some("みょ"),
        "ya" => Some("や"),
        "yu" => Some("ゆ"),
        "yo" => Some("よ"),
        "ra" => Some("ら"),
        "ri" => Some("り"),
        "ru" => Some("る"),
        "re" => Some("れ"),
        "ro" => Some("ろ"),
        "rya" => Some("りゃ"),
        "ryu" => Some("りゅ"),
        "ryo" => Some("りょ"),
        "wa" => Some("わ"),
        "wi" => Some("うぃ"),
        "we" => Some("うぇ"),
        "wo" => Some("を"),
        "va" => Some("ゔぁ"),
        "vi" => Some("ゔぃ"),
        "vu" => Some("ゔ"),
        "ve" => Some("ゔぇ"),
        "vo" => Some("ゔぉ"),
        "la" | "xa" => Some("ぁ"),
        "li" | "xi" => Some("ぃ"),
        "lu" | "xu" => Some("ぅ"),
        "le" | "xe" => Some("ぇ"),
        "lo" | "xo" => Some("ぉ"),
        "ltu" | "xtu" => Some("っ"),
        _ => None,
    }
}
