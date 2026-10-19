use std::env;

pub fn get_env(name: &str, default: &str) -> String {
    let primary = format!("MY_IME_{name}");
    if let Ok(val) = env::var(&primary) {
        return val;
    }
    let legacy = format!("LLM_IME_{name}");
    if let Ok(val) = env::var(&legacy) {
        return val;
    }
    default.to_string()
}
