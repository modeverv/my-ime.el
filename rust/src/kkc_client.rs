use std::env;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::{Mutex, OnceLock};

use crate::config::get_env;

pub struct KkcClient {
    command: String,
    model: String,
    process: Option<(Child, ChildStdin, BufReader<ChildStdout>)>,
}

impl KkcClient {
    pub fn new(command: Option<String>, model: Option<String>) -> Result<Self, String> {
        let cmd = match command {
            Some(c) => c,
            None => find_kkc_command()?,
        };
        let mdl = model.unwrap_or_else(|| get_env("KKC_MODEL", "sorted3"));
        Ok(Self {
            command: cmd,
            model: mdl,
            process: None,
        })
    }

    pub fn convert_candidates(
        &mut self,
        hiragana_text: &str,
        nbest: usize,
    ) -> Result<Vec<String>, String> {
        let kkc_input = to_kkc_placeholders(hiragana_text);
        if kkc_input.trim().is_empty() {
            return Ok(vec![hiragana_text.to_string()]);
        }
        let nbest = nbest.max(1);
        let request_text = if nbest == 1 {
            kkc_input
        } else {
            format!("{kkc_input} {nbest}")
        };

        self.ensure_process()?;
        let mut lines = Vec::with_capacity(nbest);
        let write_and_read = (|| -> Result<(), String> {
            let (_, stdin, stdout) = self.process.as_mut().unwrap();
            stdin
                .write_all(format!("{request_text}\n").as_bytes())
                .map_err(|e| format!("kkc decoder failed: {e}"))?;
            stdin
                .flush()
                .map_err(|e| format!("kkc decoder failed: {e}"))?;

            while lines.len() < nbest {
                let mut line = String::new();
                let n = stdout
                    .read_line(&mut line)
                    .map_err(|e| format!("kkc decoder failed: {e}"))?;
                if n == 0 {
                    break;
                }
                if line.trim() == ">>" {
                    continue;
                }
                lines.push(line);
            }
            Ok(())
        })();

        if let Err(e) = write_and_read {
            self.close();
            return Err(e);
        }
        if lines.len() < nbest {
            self.close();
        }
        if lines.is_empty() {
            self.close();
            return Err("kkc decoder stopped unexpectedly".to_string());
        }

        let mut converted = Vec::with_capacity(lines.len());
        for line in lines {
            let parsed = parse_kkc_line(&line)?;
            converted.push(from_kkc_placeholders(&parsed));
        }
        Ok(converted)
    }

    pub fn close(&mut self) {
        if let Some((mut child, stdin, _stdout)) = self.process.take() {
            drop(stdin);
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    fn ensure_process(&mut self) -> Result<(), String> {
        if let Some((child, _, _)) = &mut self.process {
            if let Ok(None) = child.try_wait() {
                return Ok(());
            }
            self.close();
        }

        let mut cmd = Command::new(&self.command);
        cmd.arg("decoder")
            .arg("-m")
            .arg(&self.model)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        for (k, v) in kkc_env(&self.command) {
            cmd.env(k, v);
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("could not start kkc decoder: {e}"))?;
        let stdin = child.stdin.take().ok_or("failed to open kkc stdin")?;
        let stdout = child.stdout.take().ok_or("failed to open kkc stdout")?;
        let mut reader = BufReader::new(stdout);

        let mut h1 = String::new();
        let mut h2 = String::new();
        let _ = reader.read_line(&mut h1);
        let _ = reader.read_line(&mut h2);
        if h1.is_empty() || h2.is_empty() {
            let _ = child.kill();
            let _ = child.wait();
            return Err("kkc decoder did not start".to_string());
        }

        self.process = Some((child, stdin, reader));
        Ok(())
    }
}

static GLOBAL_KKC: OnceLock<Mutex<Option<(String, String, KkcClient)>>> = OnceLock::new();

pub fn convert_hiragana_candidates_with_kkc(
    text: &str,
    nbest: usize,
) -> Result<Vec<String>, String> {
    let cmd = find_kkc_command()?;
    let model = get_env("KKC_MODEL", "sorted3");
    let mutex = GLOBAL_KKC.get_or_init(|| Mutex::new(None));
    let mut guard = mutex.lock().map_err(|e| e.to_string())?;
    let needs_reinit = match &*guard {
        Some((c, m, _)) => c != &cmd || m != &model,
        None => true,
    };
    if needs_reinit {
        *guard = Some((
            cmd.clone(),
            model.clone(),
            KkcClient::new(Some(cmd), Some(model))?,
        ));
    }
    guard.as_mut().unwrap().2.convert_candidates(text, nbest)
}

pub fn find_kkc_command() -> Result<String, String> {
    let configured = get_env("KKC_COMMAND", "");
    if !configured.is_empty() {
        return Ok(configured);
    }
    if let Some(bundled) = bundled_kkc_command() {
        return Ok(bundled.to_string_lossy().to_string());
    }
    if !cfg!(windows) {
        let local_probe = Path::new("/tmp/libkkc-install/bin/kkc");
        if local_probe.exists() {
            return Ok(local_probe.to_string_lossy().to_string());
        }
    }
    if let Some(found) = which_kkc() {
        return Ok(found);
    }
    Err("kkc command not found; set MY_IME_KKC_COMMAND".to_string())
}

pub fn kkc_available() -> bool {
    find_kkc_command().is_ok()
}

pub fn parse_kkc_line(line: &str) -> Result<String, String> {
    let mut s = line.trim();
    if let Some(rest) = s.strip_prefix(">>") {
        s = rest.trim_start();
    }
    let Some((digits, rest)) = s.split_once(':') else {
        return Err(format!(
            "kkc decoder returned unexpected line: {}",
            line.trim_end()
        ));
    };
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return Err(format!(
            "kkc decoder returned unexpected line: {}",
            line.trim_end()
        ));
    }
    let payload = rest.trim_start();
    let mut out = String::new();
    let mut found_any = false;
    let mut rest_slice = payload;
    while let Some(open) = rest_slice.find('<') {
        let after_open = &rest_slice[open + 1..];
        let Some(close) = after_open.find('>') else {
            break;
        };
        let inside = &after_open[..close];
        if !inside.contains('<') {
            if let Some((surface, _reading)) = inside.split_once('/') {
                out.push_str(surface);
                found_any = true;
            }
        }
        rest_slice = &after_open[close + 1..];
    }
    if !found_any {
        return Err(format!(
            "kkc decoder returned no segments: {}",
            line.trim_end()
        ));
    }
    Ok(out)
}

fn to_kkc_placeholders(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len() + 16);
    let mut last = 0;
    let mut i = 0;
    while i + 7 < bytes.len() {
        if &bytes[i..i + 6] == b"<TECH_" {
            let mut j = i + 6;
            while j < bytes.len() && bytes[j].is_ascii_digit() {
                j += 1;
            }
            if j > i + 6 && j < bytes.len() && bytes[j] == b'>' {
                out.push_str(&text[last..i]);
                out.push_str("|||TECH_");
                out.push_str(&text[i + 6..j]);
                out.push_str("|||");
                i = j + 1;
                last = i;
                continue;
            }
        }
        i += 1;
    }
    out.push_str(&text[last..]);
    out
}

fn from_kkc_placeholders(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut last = 0;
    let mut i = 0;
    while i + 11 < bytes.len() {
        if &bytes[i..i + 8] == b"|||TECH_" {
            let mut j = i + 8;
            while j < bytes.len() && bytes[j].is_ascii_digit() {
                j += 1;
            }
            if j > i + 8 && j + 3 <= bytes.len() && &bytes[j..j + 3] == b"|||" {
                out.push_str(&text[last..i]);
                out.push_str("<TECH_");
                out.push_str(&text[i + 8..j]);
                out.push('>');
                i = j + 3;
                last = i;
                continue;
            }
        }
        i += 1;
    }
    out.push_str(&text[last..]);
    out
}

fn bundled_runtime_dir() -> PathBuf {
    if let Ok(cwd) = env::current_dir() {
        let p = cwd.join(".deps").join("kkc-runtime").join("current");
        if p.exists() {
            return p;
        }
    }
    PathBuf::from(".deps/kkc-runtime/current")
}

fn bundled_kkc_command() -> Option<PathBuf> {
    let runtime = bundled_runtime_dir();
    let name = if cfg!(windows) { "kkc.exe" } else { "kkc" };
    let candidate = runtime.join("bin").join(name);
    if candidate.exists() {
        Some(candidate)
    } else {
        None
    }
}

fn which_kkc() -> Option<String> {
    let path_var = env::var("PATH").ok()?;
    let sep = if cfg!(windows) { ';' } else { ':' };
    let name = if cfg!(windows) { "kkc.exe" } else { "kkc" };
    for dir in path_var.split(sep) {
        let p = Path::new(dir).join(name);
        if p.is_file() {
            return Some(p.to_string_lossy().to_string());
        }
    }
    None
}

fn kkc_env(command: &str) -> Vec<(String, String)> {
    let mut vars: Vec<(String, String)> = Vec::new();
    let sep = if cfg!(windows) { ";" } else { ":" };
    let data_path = get_env("KKC_DATA_PATH", "");
    if !data_path.is_empty() {
        vars.push(("LIBKKC_DATA_PATH".to_string(), data_path));
    } else {
        let runtime = bundled_runtime_dir();
        if runtime.join("lib").join("libkkc").join("models").exists() {
            vars.push((
                "LIBKKC_DATA_PATH".to_string(),
                format!(
                    "{}{}{}",
                    runtime.join("lib").join("libkkc").display(),
                    sep,
                    runtime.join("share").join("libkkc").display()
                ),
            ));
        }
    }

    let lib_env_name = if cfg!(windows) {
        "PATH"
    } else if cfg!(target_os = "macos") {
        "DYLD_LIBRARY_PATH"
    } else {
        "LD_LIBRARY_PATH"
    };

    let mut configured = get_env("KKC_LIBRARY_PATH", "");
    if configured.is_empty() {
        configured = get_env("KKC_DYLD_LIBRARY_PATH", "");
    }
    if !configured.is_empty() {
        let existing = env::var(lib_env_name).unwrap_or_default();
        let val = if existing.is_empty() {
            configured
        } else {
            format!("{configured}{sep}{existing}")
        };
        vars.push((lib_env_name.to_string(), val));
    } else if let Some(runtime_dir) = runtime_dir_for_command(command) {
        let prefix = if cfg!(windows) {
            format!(
                "{}{}{}",
                runtime_dir.join("bin").display(),
                sep,
                runtime_dir.join("lib").display()
            )
        } else {
            runtime_dir.join("lib").to_string_lossy().to_string()
        };
        let existing = env::var(lib_env_name).unwrap_or_default();
        let val = if existing.is_empty() {
            prefix
        } else {
            format!("{prefix}{sep}{existing}")
        };
        vars.push((lib_env_name.to_string(), val));
    }
    vars
}

fn runtime_dir_for_command(command: &str) -> Option<PathBuf> {
    let p = Path::new(command);
    let fname = p.file_name()?.to_str()?.to_ascii_lowercase();
    if fname != "kkc" && fname != "kkc.exe" {
        return None;
    }
    let parent = p.parent()?;
    if parent.file_name()?.to_str()? != "bin" {
        return None;
    }
    parent.parent().map(|pp| pp.to_path_buf())
}
