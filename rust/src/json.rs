use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq)]
pub enum JsonValue {
    Null,
    Bool(bool),
    Number(f64),
    Int(i64),
    Str(String),
    Array(Vec<JsonValue>),
    Object(Vec<(String, JsonValue)>),
}

impl JsonValue {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            JsonValue::Str(s) => Some(s.as_str()),
            _ => None,
        }
    }

    pub fn as_object(&self) -> Option<&[(String, JsonValue)]> {
        match self {
            JsonValue::Object(entries) => Some(entries.as_slice()),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&[JsonValue]> {
        match self {
            JsonValue::Array(items) => Some(items.as_slice()),
            _ => None,
        }
    }

    pub fn get(&self, key: &str) -> Option<&JsonValue> {
        match self {
            JsonValue::Object(entries) => entries
                .iter()
                .rev()
                .find(|(k, _)| k == key)
                .map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn to_json_string(&self) -> String {
        let mut out = String::with_capacity(128);
        self.write_to(&mut out);
        out
    }

    pub fn write_to(&self, out: &mut String) {
        match self {
            JsonValue::Null => out.push_str("null"),
            JsonValue::Bool(true) => out.push_str("true"),
            JsonValue::Bool(false) => out.push_str("false"),
            JsonValue::Int(n) => {
                out.push_str(&n.to_string());
            }
            JsonValue::Number(n) => {
                if n.fract() == 0.0 && *n >= (i64::MIN as f64) && *n <= (i64::MAX as f64) {
                    out.push_str(&(*n as i64).to_string());
                } else {
                    out.push_str(&n.to_string());
                }
            }
            JsonValue::Str(s) => write_escaped_str(out, s),
            JsonValue::Array(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    item.write_to(out);
                }
                out.push(']');
            }
            JsonValue::Object(entries) => {
                out.push('{');
                for (i, (k, v)) in entries.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write_escaped_str(out, k);
                    out.push(':');
                    v.write_to(out);
                }
                out.push('}');
            }
        }
    }
}

pub fn write_escaped_str(out: &mut String, s: &str) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

pub fn parse_json(input: &str) -> Result<JsonValue, String> {
    let mut parser = Parser {
        bytes: input.as_bytes(),
        input,
        pos: 0,
    };
    parser.skip_ws();
    let value = parser.parse_value()?;
    parser.skip_ws();
    if parser.pos != parser.bytes.len() {
        return Err("trailing characters after JSON value".to_string());
    }
    Ok(value)
}

struct Parser<'a> {
    bytes: &'a [u8],
    input: &'a str,
    pos: usize,
}

impl<'a> Parser<'a> {
    fn skip_ws(&mut self) {
        while self.pos < self.bytes.len() {
            match self.bytes[self.pos] {
                b' ' | b'\t' | b'\r' | b'\n' => self.pos += 1,
                _ => break,
            }
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn parse_value(&mut self) -> Result<JsonValue, String> {
        self.skip_ws();
        match self.peek() {
            Some(b'"') => self.parse_string().map(JsonValue::Str),
            Some(b'{') => self.parse_object(),
            Some(b'[') => self.parse_array(),
            Some(b't') => {
                if self.bytes[self.pos..].starts_with(b"true") {
                    self.pos += 4;
                    Ok(JsonValue::Bool(true))
                } else {
                    Err("invalid literal".to_string())
                }
            }
            Some(b'f') => {
                if self.bytes[self.pos..].starts_with(b"false") {
                    self.pos += 5;
                    Ok(JsonValue::Bool(false))
                } else {
                    Err("invalid literal".to_string())
                }
            }
            Some(b'n') => {
                if self.bytes[self.pos..].starts_with(b"null") {
                    self.pos += 4;
                    Ok(JsonValue::Null)
                } else {
                    Err("invalid literal".to_string())
                }
            }
            Some(b'-' | b'0'..=b'9') => self.parse_number(),
            _ => Err("unexpected token in JSON".to_string()),
        }
    }

    fn parse_string(&mut self) -> Result<String, String> {
        if self.peek() != Some(b'"') {
            return Err("expected '\"'".to_string());
        }
        self.pos += 1;
        let mut out = String::new();
        while self.pos < self.bytes.len() {
            let b = self.bytes[self.pos];
            if b == b'"' {
                self.pos += 1;
                return Ok(out);
            }
            if b == b'\\' {
                self.pos += 1;
                if self.pos >= self.bytes.len() {
                    return Err("unterminated escape".to_string());
                }
                match self.bytes[self.pos] {
                    b'"' => {
                        out.push('"');
                        self.pos += 1;
                    }
                    b'\\' => {
                        out.push('\\');
                        self.pos += 1;
                    }
                    b'/' => {
                        out.push('/');
                        self.pos += 1;
                    }
                    b'b' => {
                        out.push('\x08');
                        self.pos += 1;
                    }
                    b'f' => {
                        out.push('\x0c');
                        self.pos += 1;
                    }
                    b'n' => {
                        out.push('\n');
                        self.pos += 1;
                    }
                    b'r' => {
                        out.push('\r');
                        self.pos += 1;
                    }
                    b't' => {
                        out.push('\t');
                        self.pos += 1;
                    }
                    b'u' => {
                        self.pos += 1;
                        let code = self.parse_hex4()?;
                        if (0xD800..=0xDBFF).contains(&code) {
                            if self.bytes.get(self.pos..self.pos + 2) != Some(b"\\u") {
                                return Err("invalid surrogate pair".to_string());
                            }
                            self.pos += 2;
                            let low = self.parse_hex4()?;
                            if !(0xDC00..=0xDFFF).contains(&low) {
                                return Err("invalid low surrogate".to_string());
                            }
                            let combined =
                                0x10000 + (((code as u32 - 0xD800) << 10) | (low as u32 - 0xDC00));
                            if let Some(ch) = char::from_u32(combined) {
                                out.push(ch);
                            } else {
                                return Err("invalid unicode codepoint".to_string());
                            }
                        } else if let Some(ch) = char::from_u32(code as u32) {
                            out.push(ch);
                        } else {
                            return Err("invalid unicode codepoint".to_string());
                        }
                    }
                    _ => return Err("invalid escape sequence".to_string()),
                }
            } else if b < 0x20 {
                return Err("unescaped control character in string".to_string());
            } else {
                let rest = &self.input[self.pos..];
                let ch = rest.chars().next().ok_or("invalid utf-8")?;
                out.push(ch);
                self.pos += ch.len_utf8();
            }
        }
        Err("unterminated string".to_string())
    }

    fn parse_hex4(&mut self) -> Result<u16, String> {
        if self.pos + 4 > self.bytes.len() {
            return Err("incomplete unicode escape".to_string());
        }
        let hex_str = &self.input[self.pos..self.pos + 4];
        self.pos += 4;
        u16::from_str_radix(hex_str, 16).map_err(|_| "invalid hex escape".to_string())
    }

    fn parse_number(&mut self) -> Result<JsonValue, String> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        while let Some(b'0'..=b'9') = self.peek() {
            self.pos += 1;
        }
        let mut is_float = false;
        if self.peek() == Some(b'.') {
            is_float = true;
            self.pos += 1;
            while let Some(b'0'..=b'9') = self.peek() {
                self.pos += 1;
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            is_float = true;
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            while let Some(b'0'..=b'9') = self.peek() {
                self.pos += 1;
            }
        }
        let slice = &self.input[start..self.pos];
        if !is_float {
            if let Ok(i) = slice.parse::<i64>() {
                return Ok(JsonValue::Int(i));
            }
        }
        let n = slice.parse::<f64>().map_err(|_| "invalid number".to_string())?;
        Ok(JsonValue::Number(n))
    }

    fn parse_array(&mut self) -> Result<JsonValue, String> {
        self.pos += 1; // '['
        self.skip_ws();
        let mut items = Vec::new();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(JsonValue::Array(items));
        }
        loop {
            let val = self.parse_value()?;
            items.push(val);
            self.skip_ws();
            match self.peek() {
                Some(b',') => {
                    self.pos += 1;
                    self.skip_ws();
                }
                Some(b']') => {
                    self.pos += 1;
                    return Ok(JsonValue::Array(items));
                }
                _ => return Err("expected ',' or ']' in array".to_string()),
            }
        }
    }

    fn parse_object(&mut self) -> Result<JsonValue, String> {
        self.pos += 1; // '{'
        self.skip_ws();
        let mut entries = Vec::new();
        let mut index_by_key: BTreeMap<String, usize> = BTreeMap::new();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(JsonValue::Object(entries));
        }
        loop {
            self.skip_ws();
            let key = self.parse_string()?;
            self.skip_ws();
            if self.peek() != Some(b':') {
                return Err("expected ':' after object key".to_string());
            }
            self.pos += 1;
            let val = self.parse_value()?;
            if let Some(&idx) = index_by_key.get(&key) {
                entries[idx] = (key, val);
            } else {
                index_by_key.insert(key.clone(), entries.len());
                entries.push((key, val));
            }
            self.skip_ws();
            match self.peek() {
                Some(b',') => {
                    self.pos += 1;
                    self.skip_ws();
                }
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(JsonValue::Object(entries));
                }
                _ => return Err("expected ',' or '}' in object".to_string()),
            }
        }
    }
}
