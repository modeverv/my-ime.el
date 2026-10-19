pub mod config;
pub mod converter;
pub mod dictionary;
pub mod json;
pub mod kkc_client;
pub mod protection;
pub mod romanizer;

use crate::converter::{convert, convert_candidates, preedit, CandidateResult, ConvertResult};
use crate::json::{parse_json, JsonValue};

fn result_to_json(result: ConvertResult, candidates: Option<Vec<String>>) -> JsonValue {
    let protected_items: Vec<JsonValue> = result
        .protected_spans
        .into_iter()
        .map(|s| {
            JsonValue::Object(vec![
                ("placeholder".to_string(), JsonValue::Str(s.placeholder)),
                ("original".to_string(), JsonValue::Str(s.original)),
                ("kind".to_string(), JsonValue::Str(s.kind)),
            ])
        })
        .collect();

    let mut entries = vec![
        ("text".to_string(), JsonValue::Str(result.text)),
        (
            "protected_text".to_string(),
            JsonValue::Str(result.protected_text),
        ),
        ("protected".to_string(), JsonValue::Array(protected_items)),
        ("backend".to_string(), JsonValue::Str(result.backend)),
        (
            "elapsed_ms".to_string(),
            JsonValue::Int(result.elapsed_ms as i64),
        ),
    ];
    if let Some(cands) = candidates {
        entries.push((
            "candidates".to_string(),
            JsonValue::Array(cands.into_iter().map(JsonValue::Str).collect()),
        ));
    }
    JsonValue::Object(entries)
}

pub fn handle_request(request: &JsonValue) -> Result<JsonValue, String> {
    if request.as_object().is_none() {
        return Err("request line must be a JSON object".to_string());
    }
    let method = match request.get("method") {
        Some(JsonValue::Str(m)) => m.as_str(),
        None => "convert",
        _ => return Err("unsupported method".to_string()),
    };

    if method == "health" {
        return Ok(JsonValue::Object(vec![
            ("ok".to_string(), JsonValue::Bool(true)),
            ("service".to_string(), JsonValue::Str("my-ime".to_string())),
            ("transport".to_string(), JsonValue::Str("stdio".to_string())),
        ]));
    }

    let text = match request.get("text") {
        Some(JsonValue::Str(t)) => t.as_str(),
        _ => return Err("field 'text' must be a string".to_string()),
    };

    let metadata = match request.get("metadata") {
        None | Some(JsonValue::Null) => None,
        Some(m) if m.as_object().is_some() => Some(m),
        _ => return Err("field 'metadata' must be an object".to_string()),
    };

    match method {
        "preedit" => {
            let res = preedit(text, metadata)?;
            Ok(result_to_json(res, None))
        }
        "candidates" => {
            let CandidateResult { base, candidates } = convert_candidates(text, metadata)?;
            Ok(result_to_json(base, Some(candidates)))
        }
        "convert" => {
            let res = convert(text, metadata)?;
            Ok(result_to_json(res, None))
        }
        _ => Err(format!("unsupported method: {method}")),
    }
}

pub fn process_line(line: &str) -> String {
    let parsed = parse_json(line);
    let mut request_id: Option<JsonValue> = None;
    let mut response = match parsed {
        Err(_) => JsonValue::Object(vec![(
            "error".to_string(),
            JsonValue::Str("request line is not valid JSON".to_string()),
        )]),
        Ok(val) => {
            if val.as_object().is_none() {
                JsonValue::Object(vec![(
                    "error".to_string(),
                    JsonValue::Str("request line must be a JSON object".to_string()),
                )])
            } else {
                request_id = val.get("id").cloned();
                match handle_request(&val) {
                    Ok(resp) => resp,
                    Err(e) => JsonValue::Object(vec![("error".to_string(), JsonValue::Str(e))]),
                }
            }
        }
    };

    if let Some(id_val) = request_id {
        if id_val != JsonValue::Null {
            if let JsonValue::Object(ref mut entries) = response {
                entries.push(("id".to_string(), id_val));
            }
        }
    }
    response.to_json_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::converter::dummy_convert;
    use crate::dictionary::{
        apply_dictionary_candidate_sets_with_placeholders_index, apply_dictionary_index,
        apply_dictionary_with_placeholders_index, load_dictionary, load_dictionary_candidates,
        CandidateDictionaryIndex, DictionaryIndex,
    };
    use crate::kkc_client::parse_kkc_line;
    use crate::protection::{protect_text, protected_tokens, restore_text};
    use crate::romanizer::{normalize_romaji, romaji_to_hiragana};
    use std::sync::Mutex;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn test_romanizer() {
        assert_eq!(romaji_to_hiragana("dekaihatusuru"), "でかいはつする");
        assert_eq!(romaji_to_hiragana("wojikkou suru"), "をじっこうする");
        assert_eq!(romaji_to_hiragana("deyobunohaomoi"), "でよぶのはおもい");
        assert_eq!(romaji_to_hiragana("yoi"), "よい");
        assert_eq!(romaji_to_hiragana("famiri-"), "ふぁみりー");
        assert_eq!(romaji_to_hiragana("<TECH_0> de yaru"), "<TECH_0>でやる");
        assert_eq!(normalize_romaji("kannjiniikeru"), "kanjiniikeru");
        assert_eq!(romaji_to_hiragana("kannjiniikeru"), "かんじにいける");
        assert_eq!(romaji_to_hiragana("konnichi"), "こんにち");
        assert_eq!(normalize_romaji("jibunyou"), "jibun'you");
        assert_eq!(romaji_to_hiragana("jibunyou"), "じぶんよう");
        assert_eq!(romaji_to_hiragana("jibunnyou"), "じぶんよう");
        assert_eq!(romaji_to_hiragana("zibunyou"), "じぶんよう");
        assert_eq!(romaji_to_hiragana("じぶnyou"), "じぶんよう");
        assert_eq!(romaji_to_hiragana("jibunno"), "じぶんの");
        assert_eq!(romaji_to_hiragana("jibunni"), "じぶんに");
    }

    #[test]
    fn test_protection() {
        let protected = protect_text("org-roam-db-syncwoafter-save-hookdeyobunohaomoi").unwrap();
        assert_eq!(protected.text, "<TECH_0>wo<TECH_1>deyobunohaomoi");
        assert_eq!(
            protected
                .spans
                .iter()
                .map(|s| s.original.as_str())
                .collect::<Vec<_>>(),
            vec!["org-roam-db-sync", "after-save-hook"]
        );
        let restored = restore_text("<TECH_0>を<TECH_1>で呼ぶのは重い", &protected).unwrap();
        assert_eq!(restored, "org-roam-db-syncをafter-save-hookで呼ぶのは重い");

        let manual = protect_text(";;domain drive;;deyaru").unwrap();
        assert_eq!(manual.text, "<TECH_0>deyaru");
        assert_eq!(manual.spans[0].original, "domain drive");
        assert_eq!(manual.spans[0].kind, "manual_term");
        assert_eq!(
            restore_text("<TECH_0>でやる", &manual).unwrap(),
            "domain driveでやる"
        );

        assert!(protect_text(";;domain drive;deyaru").is_err());

        let text = "curl -s http://127.0.0.1:8765/openapi.json wo /api/v1/convert ni ~/work/ai/foo.org kara C-c j j de (message \"hi\") made";
        let tokens = protected_tokens(text).unwrap();
        assert!(tokens.contains(&"curl -s".to_string()));
        assert!(tokens.contains(&"http://127.0.0.1:8765/openapi.json".to_string()));
        assert!(tokens.contains(&"/api/v1/convert".to_string()));
        assert!(tokens.contains(&"~/work/ai/foo.org".to_string()));
        assert!(tokens.contains(&"C-c j j".to_string()));
        assert!(tokens.contains(&"(message \"hi\")".to_string()));

        let p2 = protect_text("C-c j j de my-ime-convert-dwim wo yobu").unwrap();
        assert_eq!(
            p2.spans
                .iter()
                .map(|s| s.original.as_str())
                .collect::<Vec<_>>(),
            vec!["C-c j j", "my-ime-convert-dwim"]
        );

        let p3 = protect_text("my-ime-history ni before after wo nokosu").unwrap();
        assert_eq!(p3.text, "<TECH_0> ni before after wo nokosu");

        let p4 = protect_text("de-ta wo yomu").unwrap();
        assert_eq!(p4.text, "de-ta wo yomu");
        assert!(p4.spans.is_empty());

        let p5 = protect_text("MY_IME_BACKEND dummy de offline ni ugoku").unwrap();
        assert!(p5.spans.is_empty());

        let p6 = protect_text("after-save-hook de yobu").unwrap();
        assert!(restore_text("壊れた output", &p6).is_err());
        assert!(restore_text("<TECH_0><TECH_0>で呼ぶ", &p6).is_err());
    }

    #[test]
    fn test_dictionary() {
        let entries = load_dictionary(r#"{"gemmade": "Gemmaで", "henkan": "変換"}"#).unwrap();
        let idx = DictionaryIndex::build(&entries, false);
        assert_eq!(apply_dictionary_index("gemmadehenkan", &idx), "Gemmaで変換");

        let e2 = vec![
            ("kyou".to_string(), "今日".to_string()),
            ("serverwo".to_string(), "サーバーを".to_string()),
        ];
        let idx2 = DictionaryIndex::build(&e2, false);
        assert_eq!(apply_dictionary_index("kyoushi data", &idx2), "kyoushi data");
        assert_eq!(
            apply_dictionary_index("serverwo cache", &idx2),
            "サーバーを cache"
        );

        let e3 = vec![
            ("<TECH_0>".to_string(), "壊れた".to_string()),
            ("yobu".to_string(), "呼ぶ".to_string()),
        ];
        let idx3 = DictionaryIndex::build(&e3, false);
        assert_eq!(
            apply_dictionary_index("<TECH_0>woyobu", &idx3),
            "<TECH_0>wo呼ぶ"
        );

        let e4 = vec![
            ("serverwo".to_string(), "サーバーを".to_string()),
            ("cachede".to_string(), "キャッシュで".to_string()),
        ];
        let idx4 = DictionaryIndex::build(&e4, false);
        let (text, spans) =
            apply_dictionary_with_placeholders_index("serverwo cachede tukau", &idx4, 0);
        assert_eq!(text, "<TECH_0> <TECH_1> tukau");
        assert_eq!(
            spans,
            vec![
                ("<TECH_0>".to_string(), "サーバーを".to_string()),
                ("<TECH_1>".to_string(), "キャッシュで".to_string())
            ]
        );

        let cand_entries = load_dictionary_candidates(
            r#"{"kanji": ["漢字", "感じ"], "henkan": ["変換", "返還"]}"#,
        )
        .unwrap();
        let c_idx = CandidateDictionaryIndex::build(&cand_entries);
        let variants = apply_dictionary_candidate_sets_with_placeholders_index(
            "kanjihenkande",
            &c_idx,
            0,
            2,
            10,
        );
        let restored: Vec<String> = variants
            .into_iter()
            .map(|(mut t, s)| {
                for (ph, target) in s {
                    t = t.replace(&ph, &target);
                }
                t
            })
            .collect();
        assert_eq!(
            restored,
            vec!["漢字変換de", "漢字返還de", "感じ変換de", "感じ返還de"]
        );
    }

    #[test]
    fn test_dummy_and_converter() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("MY_IME_BACKEND", "dummy");
        std::env::remove_var("MY_IME_DICTIONARY");

        assert_eq!(
            dummy_convert("<TECH_0>wo<TECH_1>deyobu"),
            "<TECH_0>を<TECH_1>で呼ぶ"
        );
        assert_eq!(
            dummy_convert("API response keishiki wa domain ni mochikomanai"),
            "API response形式はdomainに持ち込まない"
        );
        assert_eq!(
            dummy_convert("MY_IME_BACKEND dummy de offline ni ugoku"),
            "MY_IME_BACKEND=dummyでofflineに動く"
        );

        let r1 = convert("org-roam-db-syncwoafter-save-hookdeyobunohaomoi", None).unwrap();
        assert_eq!(r1.text, "org-roam-db-syncをafter-save-hookで呼ぶのは重い");

        let r2 = convert("gemmaderoomajikashitarakyoushidataninarunodeha", None).unwrap();
        assert_eq!(r2.text, "Gemmaでローマ字化したら教師データになるのでは");

        let r3 = convert(
            "targetwoemacsnigenteisurunaraeijinihongokankeinakutoriaezualphabetnyuuryokushita monowollmdeeigonihongomajirinooutputnikirikaerukotohakanou",
            None,
        )
        .unwrap();
        assert_eq!(
            r3.text,
            "ターゲットをEmacsに限定するなら、英字・日本語関係なく、とりあえずalphabet入力したものをLLMで英語日本語混じりのoutputに切り替えることは可能。"
        );

        assert_eq!(
            dummy_convert("<TECH_0> <TECH_1> wo tataku"),
            "<TECH_0> <TECH_1>を叩く"
        );
        assert_eq!(
            dummy_convert("<TECH_0> status wo kakunin suru"),
            "<TECH_0> statusを確認する"
        );
        assert_eq!(dummy_convert("url wo mamoru"), "URLを守る");
        assert_eq!(
            dummy_convert("placeholder ga nakunattara error ni suru"),
            "placeholderがなくなったらerrorにする"
        );
        assert_eq!(
            dummy_convert("Repository wo Entity kara yobanai hou ga ii"),
            "RepositoryをEntityから呼ばない方がいい"
        );
        assert_eq!(
            dummy_convert("technical term wo nihongo ni yakushi sugita toki wa fallback suru"),
            "technical termを日本語に訳しすぎた時はfallbackする"
        );
        assert_eq!(
            dummy_convert("chat completion response ga reasoning only nara error ni suru"),
            "chat completion responseがreasoning onlyならerrorにする"
        );
        assert_eq!(
            dummy_convert("ApplicationService de transaction boundary wo motsu"),
            "ApplicationServiceでtransaction boundaryを持つ"
        );
        assert_eq!(dummy_convert("endpoint de smoke suru"), "endpointでsmokeする");
        assert_eq!(
            dummy_convert("response format wo JSON schema ni suru"),
            "response formatをJSON schemaにする"
        );
        assert_eq!(
            dummy_convert("short sentence nara 0.5b model de tariru kamo"),
            "short sentenceなら0.5B modelで足りるかも"
        );
        assert_eq!(
            dummy_convert("history ni original to converted wo nokosu"),
            "historyにoriginalとconvertedを残す"
        );
        assert_eq!(
            dummy_convert("strict prompt de explanation wo kinshi suru"),
            "strict promptでexplanationを禁止する"
        );
        assert_eq!(
            dummy_convert("no extra text rate wo metrics ni ireru"),
            "no-extra-text rateをmetricsに入れる"
        );
        assert_eq!(
            dummy_convert("train valid test ni repeatable ni split suru"),
            "train/valid/testにrepeatableにsplitする"
        );
        assert_eq!(
            dummy_convert("full ime wa command based workflow no ato"),
            "full IMEはcommand-based workflowの後"
        );
        assert_eq!(
            dummy_convert("paths urls commands keybindings wo preserve suru"),
            "paths/URLs/commands/keybindingsをpreserveする"
        );
        assert_eq!(
            dummy_convert("my-ime-history ni before after wo nokosu"),
            "my-ime-historyにbefore/afterを残す"
        );

        std::env::set_var(
            "MY_IME_DICTIONARY",
            r#"{"watashinokonoheniha": "私のこの辺には"}"#,
        );
        let r_dict = convert("watashinokonoheniha", None).unwrap();
        assert_eq!(r_dict.text, "私のこの辺には");

        std::env::set_var(
            "MY_IME_DICTIONARY",
            r#"{"kanji": ["漢字", "感じ"], "henkan": ["変換", "返還"], "dekiru": "できる"}"#,
        );
        let c_res = convert_candidates("kanjihenkandekiru", None).unwrap();
        assert_eq!(
            c_res.candidates,
            vec![
                "漢字変換できる",
                "漢字返還できる",
                "感じ変換できる",
                "感じ返還できる"
            ]
        );
        std::env::remove_var("MY_IME_DICTIONARY");
    }

    #[test]
    fn test_stdio_protocol() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("MY_IME_BACKEND", "dummy");
        std::env::remove_var("MY_IME_DICTIONARY");

        let h = process_line(r#"{"id":1,"method":"health"}"#);
        assert_eq!(
            h,
            r#"{"ok":true,"service":"my-ime","transport":"stdio","id":1}"#
        );

        let c = process_line(
            r#"{"id":2,"method":"convert","text":"serverwo","metadata":{"source":"test"}}"#,
        );
        let parsed = parse_json(&c).unwrap();
        assert_eq!(parsed.get("text").and_then(|v| v.as_str()), Some("サーバーを"));
        assert_eq!(parsed.get("backend").and_then(|v| v.as_str()), Some("dummy"));
        assert_eq!(parsed.get("id"), Some(&JsonValue::Int(2)));

        let p = process_line(r#"{"id":3,"method":"preedit","text":"kyou ha"}"#);
        let parsed_p = parse_json(&p).unwrap();
        assert_eq!(parsed_p.get("text").and_then(|v| v.as_str()), Some("きょうは"));
        assert_eq!(
            parsed_p.get("backend").and_then(|v| v.as_str()),
            Some("preedit")
        );

        let err = process_line(r#"{"id":4,"method":"missing","text":"x"}"#);
        let parsed_err = parse_json(&err).unwrap();
        assert!(parsed_err
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .contains("unsupported method"));
    }

    #[test]
    fn test_kkc_line_parser() {
        let line1 = ">> 0: <|||TECH_0|||/|||TECH_0|||><で/で><開発/かいはつ><する/する>";
        assert_eq!(parse_kkc_line(line1).unwrap(), "|||TECH_0|||で開発する");
        let line2 = "2: <|||TECH_0|||/|||TECH_0|||><が/が><良/よ><い/い><感じ/かんじ>";
        assert_eq!(parse_kkc_line(line2).unwrap(), "|||TECH_0|||が良い感じ");
    }

    #[test]
    fn test_kkc_backend_if_available() {
        if !crate::kkc_client::kkc_available() {
            return;
        }
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("MY_IME_BACKEND", "kkc");
        std::env::set_var("MY_IME_KKC_NBEST", "3");
        std::env::remove_var("MY_IME_DICTIONARY");

        assert_eq!(
            crate::converter::kkc_convert("<TECH_0>deyaru").unwrap(),
            "<TECH_0>でやる"
        );
        assert_eq!(
            crate::converter::kkc_convert("<TECH_0>dekaihatusuru").unwrap(),
            "<TECH_0>で開発する"
        );
        assert_eq!(
            convert(";;domain drive;;deyaru", None).unwrap().text,
            "domain driveでやる"
        );
        assert_eq!(
            convert(";;this is a pen;;", None).unwrap().text,
            "this is a pen"
        );
        assert_eq!(
            convert("  ;;data is dead;;", None).unwrap().text,
            "data is dead"
        );
        assert_eq!(
            convert(";;org-roam-db-sync;;wo;;after-save-hook;;deyobunohaomoi", None)
                .unwrap()
                .text,
            "org-roam-db-syncをafter-save-hookで呼ぶのは重い"
        );
        assert_eq!(
            convert(";;global state;;gayoikannjiniikeru", None)
                .unwrap()
                .text,
            "global stateが良い感じにいける"
        );
        assert_eq!(
            convert(";;global state;;gayoikannjiniikeru.", None)
                .unwrap()
                .text,
            "global stateが良い感じにいける。"
        );
        assert_eq!(
            convert(";;global state;;gayoikannjiniikeru. ", None)
                .unwrap()
                .text,
            "global stateが良い感じにいける。 "
        );
        assert_eq!(
            convert(";;global state;;gayoikannjiniikeru, ", None)
                .unwrap()
                .text,
            "global stateが良い感じにいける、 "
        );
        assert_eq!(
            convert("kyou ha akarui.", None).unwrap().text,
            "今日は明るい。"
        );
        assert_eq!(
            convert("kyou ha totemo tanosii.", None).unwrap().text,
            "今日はとても楽しい。"
        );
        assert_eq!(convert("de-tawo yomu.", None).unwrap().text, "データを読む。");
        assert_eq!(preedit("de-tawo yomu", None).unwrap().text, "データをよむ");
        let first = preedit("kyou ha totemo tanosii", None).unwrap();
        assert_eq!(first.text, "きょうはとてもたのしい");
        let committed = convert(&format!("{}.", first.text), None).unwrap();
        assert_eq!(committed.text, "今日はとても楽しい。");
    }
}
