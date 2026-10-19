use std::env;
use std::io::{self, BufRead, Write};

use my_ime_rs::process_line;

fn main() {
    for arg in env::args().skip(1) {
        if arg == "-h" || arg == "--help" {
            println!("Run the local my-ime stdio worker (Rust).");
            return;
        }
    }

    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = io::BufWriter::new(stdout.lock());

    for line_res in stdin.lock().lines() {
        let Ok(line) = line_res else { break };
        if line.trim().is_empty() {
            continue;
        }
        let response = process_line(&line);
        if writeln!(out, "{response}").is_err() {
            break;
        }
        if out.flush().is_err() {
            break;
        }
    }
}
