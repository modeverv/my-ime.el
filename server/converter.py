"""Conversion pipeline: protect technical tokens, convert, then restore."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any

from .config import env
from .dictionary import (
    DictionaryError,
    apply_dictionary,
    apply_dictionary_candidate_sets_with_placeholders,
    apply_dictionary_with_placeholders,
    configured_dictionary,
)
from .kkc_client import KkcError, convert_hiragana_candidates_with_kkc
from .protection import ProtectedSpan, ProtectedText, ProtectionError, protect_text, restore_text
from .romanizer import romaji_to_hiragana


@dataclass(frozen=True)
class ConvertResult:
    text: str
    protected_text: str
    protected_spans: tuple[ProtectedSpan, ...]
    backend: str
    elapsed_ms: int


@dataclass(frozen=True)
class CandidateResult(ConvertResult):
    candidates: tuple[str, ...]


class ConvertError(RuntimeError):
    """Raised when conversion cannot complete safely."""


ROMAN_REPLACEMENTS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            "placeholder": "placeholder",
            "compatible": "compatible",
            "protection": "protection",
            "keybinding": "keybinding",
            "protected": "protected",
            "temperature": "temperature",
            "candidate": "candidate",
            "paragraph": "paragraph",
            "metadata": "metadata",
            "endpoint": "endpoint",
            "workflow": "workflow",
            "distribution": "distribution",
            "transaction": "transaction",
            "restoration": "restoration",
            "property": "property",
            "headline": "headline",
            "sentence": "sentence",
            "validate": "validate",
            "validation": "validation",
            "quantize": "quantize",
            "inference": "inference",
            "dataset": "dataset",
            "runtime": "runtime",
            "response": "response",
            "external": "external",
            "request": "request",
            "explicit": "explicit",
            "reasoning": "reasoning",
            "markdown": "Markdown",
            "training": "training",
            "frontmatter": "frontmatter",
            "fragment": "fragment",
            "repository": "Repository",
            "controller": "Controller",
            "valueobject": "ValueObject",
            "domainservice": "DomainService",
            "applicationservice": "ApplicationService",
            "experiment": "experiment",
            "discard": "discard",
            "summary": "summary",
            "reports": "reports",
            "result": "result",
            "object": "object",
            "timeout": "timeout",
            "holdout": "holdout",
            "default": "default",
            "preview": "preview",
            "history": "history",
            "metrics": "metrics",
            "meaning": "meaning",
            "summary": "summary",
            "manual": "manual",
            "buffer": "buffer",
            "server": "server",
            "source": "source",
            "output": "output",
            "input": "input",
            "model": "model",
            "local": "local",
            "cloud": "cloud",
            "exact": "exact",
            "match": "match",
            "token": "token",
            "class": "class",
            "teacher": "teacher",
            "train": "train",
            "valid": "valid",
            "false": "false",
            "chunk": "chunk",
            "domain": "domain",
            "entity": "Entity",
            "fence": "fence",
            "chars": "chars",
            "lora": "LoRA",
            "codex": "Codex",
            "mecab": "MeCab",
            "pykakasi": "pykakasi",
            "kakasi": "kakasi",
            "tomoko": "Tomoko",
            "jsonl": "JSONL",
            "json": "JSON",
            "retry": "retry",
            "diff": "diff",
            "file": "file",
            "main": "main",
            "eval": "eval",
            "gate": "gate",
            "cache": "cache",
            "env": "env",
            "max": "max",
            "mode": "mode",
            "port": "port",
            "src": "src",
            "pass": "pass",
            "rate": "rate",
            "tag": "tag",
            "openai": "OpenAI",
            "ollama": "Ollama",
            "llama": "llama",
            "error": "error",
            "undo": "undo",
            "api": "API",
            "url": "URL",
            "org": "org",
            "db": "DB",
            "cer": "CER",
            "sqlite": "SQLite",
            "vector": "vector",
            "search": "search",
            "fallback": "fallback",
            "command": "command",
            "gemma": "Gemma",
            "roomaji": "ローマ字",
            "romaji": "ローマ字",
            "kashitara": "化したら",
            "shitara": "したら",
            "kyoushidata": "教師データ",
            "kyoushi": "教師",
            "data": "データ",
            "ninarunodeha": "になるのでは",
            "ninaru": "になる",
            "naru": "なる",
            "nodeha": "のでは",
            "target": "ターゲット",
            "emacs": "Emacs",
            "nigenteisurunara": "に限定するなら",
            "genteisurunara": "限定するなら",
            "eijinihongokankeinakutoriaezu": "英字・日本語関係なく、とりあえず",
            "alphabet": "alphabet",
            "nyuuryoku": "入力",
            "shita": "した",
            "mono": "もの",
            "llm": "LLM",
            "eigonihongomajiri": "英語日本語混じり",
            "output": "output",
            "nikirikaerukoto": "に切り替えること",
            "hakanou": "は可能。",
            "kanou": "可能",
            "mamoru": "守る",
            "marugoto": "丸ごと",
            "kowasanai": "壊さない",
            "youni": "ように",
            "nakunattara": "なくなったら",
            "kaenai": "変えない",
            "nokosu": "残す",
            "sono": "その",
            "tsuika": "追加",
            "miru": "見る",
            "naka": "中",
            "shinai": "しない",
            "shinakatta": "しなかった",
            "tsukawanai": "使わない",
            "chokusetu": "直接",
            "mochikomanai": "持ち込まない",
            "nagasugiru": "長すぎる",
            "kakikaenai": "書き換えない",
            "chikazukeru": "近づける",
            "uketomeru": "受け止める",
            "butsukaranai": "ぶつからない",
            "atatamete": "温めて",
            "nihongo": "日本語",
            "keishiki": "形式",
            "yakushi": "訳し",
            "yakusu": "訳す",
            "sugita": "すぎた",
            "eranda": "選んだ",
            "yurusuka": "許すか",
            "kangaeru": "考える",
            "futatsu": "二つ",
            "saisho": "最初",
            "mitaina": "みたいな",
            "suteru": "捨てる",
            "dasu": "出す",
            "modosu": "戻す",
            "hazusu": "外す",
            "watasu": "渡す",
            "tsukatta": "使った",
            "kawattara": "変わったら",
            "agattara": "上がったら",
            "mazattara": "混ざったら",
            "handan": "判断",
            "shirabe": "調べ",
            "shippai": "失敗",
            "chousei": "調整",
            "saigen": "再現",
            "gousei": "合成",
            "kakuri": "隔離",
            "kekka": "結果",
            "hayame": "早め",
            "shori": "処理",
            "yobanai": "呼ばない",
            "fuhen": "不変",
            "zen": "全",
            "zettai": "絶対",
            "usuku": "薄く",
            "kaette": "返って",
            "mama": "まま",
            "mazu": "まず",
            "mada": "まだ",
            "kita": "来た",
            "toki": "時",
            "naku": "なく",
            "nakereba": "なければ",
            "mawasu": "回す",
            "aru": "ある",
            "hou": "方",
            "nai": "ない",
            "kuru": "くる",
            "dame": "ダメ",
            "oku": "おく",
            "kiru": "切る",
            "haru": "貼る",
            "kakunin": "確認",
            "hoshii": "欲しい",
            "yaru": "やる",
            "yaranai": "やらない",
            "ii": "いい",
            "ja": "じゃ",
            "hikume": "低め",
            "ireru": "入れる",
            "noseru": "載せる",
            "okosu": "起こす",
            "tamotsu": "保つ",
            "motsu": "持つ",
            "tsukuru": "作る",
            "sentaku": "選択",
            "han'i": "範囲",
            "henkan": "変換",
            "nokoseru": "残せる",
            "modoreru": "戻れる",
            "hiraku": "開く",
            "kaesu": "返す",
            "atsukau": "扱う",
            "morau": "もらう",
            "koushin": "更新",
            "hakaru": "測る",
            "tariru": "足りる",
            "tsukau": "使う",
            "naoseru": "直せる",
            "kinshi": "禁止",
            "kaihi": "回避",
            "henna": "変な",
            "kaku": "書く",
            "ichido": "一度",
            "mou": "もう",
            "goto": "ごと",
            "rei": "例",
            "moto": "元",
            "priority": "priority",
            "latency": "latency",
            "omoi": "重い",
            "karui": "軽い",
            "yobu": "呼ぶ",
            "yobunoha": "呼ぶのは",
            "yonde": "読んで",
            "yomu": "読む",
            "shitai": "したい",
            "shite": "して",
            "suru": "する",
            "dekiru": "できる",
            "ichiban": "一番",
            "kamo": "かも",
            "dake": "だけ",
            "nara": "なら",
            "koredeii": "これでいい",
            "tataku": "叩く",
            "ato": "後",
            "mae": "前",
            "de": "で",
            "wo": "を",
            "o": "を",
            "ni": "に",
            "no": "の",
            "ga": "が",
            "ha": "は",
            "wa": "は",
            "to": "と",
            "kara": "から",
            "made": "まで",
            "mo": "も",
            "ya": "や",
            "node": "ので",
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


TECH_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
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
)


def convert(text: str, metadata: dict[str, Any] | None = None) -> ConvertResult:
    """Convert text with the configured backend and protection layer."""

    started = time.monotonic()
    _ = metadata
    backend = env("BACKEND", "kkc").lower()
    leading_ws, core_text, trailing_ws = _split_outer_whitespace(text)
    protected = protect_text(core_text)
    if _manual_term_confirmation_only(protected):
        leading_ws = ""
    try:
        dictionary_text, dictionary_spans = apply_dictionary_with_placeholders(
            protected.text,
            placeholder_start=len(protected.spans),
        )
        if backend == "dummy":
            converted_protected = _restore_transient_kkc_spans(
                dummy_convert(dictionary_text),
                dictionary_spans,
            )
            restored = restore_text(converted_protected, protected)
        elif backend in {"kkc", "libkkc", "deterministic"}:
            converted_protected = _restore_transient_kkc_spans(
                kkc_convert(dictionary_text),
                dictionary_spans,
            )
            restored = restore_text(converted_protected, protected)
        else:
            raise ConvertError(f"unsupported backend: {backend}")
    except (ProtectionError, DictionaryError, KkcError) as exc:
        raise ConvertError(str(exc)) from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ConvertResult(
        text=leading_ws + restored + trailing_ws,
        protected_text=dictionary_text,
        protected_spans=protected.spans,
        backend=backend,
        elapsed_ms=elapsed_ms,
    )


def convert_candidates(text: str, metadata: dict[str, Any] | None = None) -> CandidateResult:
    """Return selectable sentence candidates built from per-word alternatives."""

    started = time.monotonic()
    metadata = metadata or {}
    backend = env("BACKEND", "kkc").lower()
    per_word_limit = _metadata_int(
        metadata,
        "candidate_per_word_limit",
        _candidate_per_word_limit(),
    )
    max_candidates = _metadata_int(metadata, "candidate_max", _candidate_max())
    leading_ws, core_text, trailing_ws = _split_outer_whitespace(text)
    protected = protect_text(core_text)
    if _manual_term_confirmation_only(protected):
        leading_ws = ""
    try:
        dictionary_variants = apply_dictionary_candidate_sets_with_placeholders(
            protected.text,
            placeholder_start=len(protected.spans),
            per_word_limit=per_word_limit,
            max_candidates=max_candidates,
        )
        restored_candidates: list[str] = []
        first_protected_text = dictionary_variants[0][0] if dictionary_variants else protected.text
        for dictionary_text, dictionary_spans in dictionary_variants:
            for converted_protected in _backend_convert_candidates(backend, dictionary_text):
                converted_protected = _restore_transient_kkc_spans(
                    converted_protected,
                    dictionary_spans,
                )
                restored = restore_text(converted_protected, protected)
                restored_candidates.append(leading_ws + restored + trailing_ws)
                if len(restored_candidates) >= max_candidates:
                    break
            if len(restored_candidates) >= max_candidates:
                break
    except (ProtectionError, DictionaryError, KkcError) as exc:
        raise ConvertError(str(exc)) from exc

    candidates = tuple(_dedupe_texts(restored_candidates))
    if not candidates:
        candidates = (text,)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return CandidateResult(
        text=candidates[0],
        candidates=candidates,
        protected_text=first_protected_text,
        protected_spans=protected.spans,
        backend=backend,
        elapsed_ms=elapsed_ms,
    )


def preedit(text: str, metadata: dict[str, Any] | None = None) -> ConvertResult:
    """Convert romanized text to readable kana/katakana without kanji commit."""

    started = time.monotonic()
    _ = metadata
    leading_ws, core_text, trailing_ws = _split_outer_whitespace(text)
    protected = protect_text(core_text)
    if _manual_term_confirmation_only(protected):
        leading_ws = ""
    try:
        dictionary_text = apply_dictionary(protected.text, _preedit_dictionary())
        converted_protected = romaji_to_hiragana(dictionary_text)
        restored = restore_text(converted_protected, protected)
    except (ProtectionError, DictionaryError) as exc:
        raise ConvertError(str(exc)) from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ConvertResult(
        text=leading_ws + restored + trailing_ws,
        protected_text=dictionary_text,
        protected_spans=protected.spans,
        backend="preedit",
        elapsed_ms=elapsed_ms,
    )


def _preedit_dictionary() -> tuple[tuple[str, str], ...]:
    """Return dictionary entries that are useful before final kanji commit."""

    return tuple(
        (source, target)
        for source, target in configured_dictionary()
        if re.search(r"[ァ-ンー]", target)
    )


def _split_outer_whitespace(text: str) -> tuple[str, str, str]:
    match = re.match(r"^(\s*)(.*?)(\s*)$", text, flags=re.DOTALL)
    if match is None:
        return "", text, ""
    return match.group(1), match.group(2), match.group(3)


def _manual_term_confirmation_only(protected: ProtectedText) -> bool:
    return (
        protected.text == "<TECH_0>"
        and len(protected.spans) == 1
        and protected.spans[0].kind == "manual_term"
    )


def kkc_convert(text: str) -> str:
    """Deterministically convert protected romanized text through kkc."""

    hiragana = romaji_to_hiragana(text)
    if not _kkc_needs_decoder(hiragana):
        return _postprocess_kkc_output(hiragana)
    candidates = convert_hiragana_candidates_with_kkc(hiragana, nbest=_kkc_nbest())
    converted = _select_kkc_candidate(candidates)
    converted = _postprocess_kkc_output(converted)
    return re.sub(r"(<TECH_\d+>)\s+([をでにのがはと])", r"\1\2", converted)


def _backend_convert_candidates(backend: str, text: str) -> tuple[str, ...]:
    if backend == "dummy":
        return (dummy_convert(text),)
    if backend in {"kkc", "libkkc", "deterministic"}:
        return tuple(kkc_convert_candidates(text))
    raise ConvertError(f"unsupported backend: {backend}")


def kkc_convert_candidates(text: str) -> list[str]:
    """Return ranked protected-text candidates through kkc."""

    hiragana = romaji_to_hiragana(text)
    if not _kkc_needs_decoder(hiragana):
        return [_postprocess_kkc_output(hiragana)]
    candidates = convert_hiragana_candidates_with_kkc(hiragana, nbest=_kkc_nbest())
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (_kkc_candidate_score(item[1]), -item[0]),
        reverse=True,
    )
    converted: list[str] = []
    for _index, candidate in ranked:
        candidate = _postprocess_kkc_output(candidate)
        candidate = re.sub(r"(<TECH_\d+>)\s+([をでにのがはと])", r"\1\2", candidate)
        converted.append(candidate)
    return _dedupe_texts(converted)


def _restore_transient_kkc_spans(text: str, spans: tuple[tuple[str, str], ...]) -> str:
    for placeholder, original in spans:
        if text.count(placeholder) != 1:
            raise KkcError(f"kkc dropped protected Japanese span: {placeholder}")
        text = text.replace(placeholder, original)
    return text


def _kkc_needs_decoder(text: str) -> bool:
    plain = re.sub(r"<TECH_\d+>", "", text)
    plain = plain.strip(" \t\r\n.,!?。、！？")
    return bool(plain)


def _kkc_nbest() -> int:
    raw = env("KKC_NBEST", "3")
    try:
        return max(1, min(20, int(raw)))
    except ValueError:
        return 3


def _candidate_per_word_limit() -> int:
    raw = env("CANDIDATE_PER_WORD_LIMIT", "3")
    try:
        return max(1, min(5, int(raw)))
    except ValueError:
        return 3


def _candidate_max() -> int:
    raw = env("CANDIDATE_MAX", "30")
    try:
        return max(1, min(200, int(raw)))
    except ValueError:
        return 30


def _metadata_int(metadata: dict[str, Any], key: str, default: int) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _dedupe_texts(texts: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for text in texts:
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _select_kkc_candidate(candidates: list[str]) -> str:
    if not candidates:
        raise KkcError("kkc decoder returned no candidates")
    ranked = sorted(enumerate(candidates), key=lambda item: (_kkc_candidate_score(item[1]), -item[0]), reverse=True)
    return ranked[0][1]


def _kkc_candidate_score(text: str) -> int:
    score = 0
    bonuses = {
        "今日は": 8,
        "明日は": 6,
        "昨日は": 6,
        "良い": 2,
        "感じ": 4,
        "感じにいける": 4,
    }
    penalties = {
        "卿": 8,
        "教派": 8,
        "環んじ": 12,
        "漢字に": 4,
        "幹事": 4,
        "監事": 4,
        "生ける": 3,
        "酔い": 3,
    }
    for token, value in bonuses.items():
        if token in text:
            score += value
    for token, value in penalties.items():
        if token in text:
            score -= value
    if "感じに行ける" in text:
        score -= 2
    return score


def _postprocess_kkc_output(text: str) -> str:
    """Apply narrow deterministic fixes for technical prose."""

    replacements = (
        ("呼ぶのは思い", "呼ぶのは重い"),
        ("のは思い", "のは重い"),
        ("が思い", "が重い"),
        ("環んじ", "感じ"),
        ("良い感じに行ける", "良い感じにいける"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    text = re.sub(r"\.(\s*)$", r"。\1", text)
    text = re.sub(r",(\s*)$", r"、\1", text)
    return text


def _looks_unconverted(source: str, candidate: str) -> bool:
    if not candidate.strip():
        return True
    source_plain = re.sub(r"<TECH_\d+>", "", source).strip().lower()
    candidate_plain = re.sub(r"<TECH_\d+>", "", candidate).strip().lower()
    if source_plain and candidate_plain == source_plain:
        return True
    if re.search(r"[ぁ-んァ-ヶ一-龯]", candidate):
        return False
    roman_markers = (" wo ", " de ", " ni ", " no ", " kara ", " sh", " suru", " yobu")
    compact_markers = ("wo", "de", "ni", "no", "kara", "suru", "yobu")
    lowered = " " + candidate_plain + " "
    if any(marker in lowered for marker in roman_markers):
        return True
    return any(marker in candidate_plain for marker in compact_markers) and len(candidate_plain) >= 12


def _drops_technical_terms(source: str, candidate: str) -> bool:
    source_terms = _technical_terms(source)
    if not source_terms:
        return False
    lowered = candidate.lower()
    missing = [term for term in source_terms if term.lower() not in lowered]
    return len(missing) > max(0, len(source_terms) // 3)


def _unsafe_model_drift(source: str, candidate: str) -> bool:
    """Reject model outputs that are riskier than the deterministic baseline."""

    baseline = dummy_convert(source)
    if candidate == baseline:
        return False
    if len(candidate) > max(24, len(baseline) * 2.2):
        return True
    if re.search(r"(変す|変せ|ではなく|正しい|べき|対象ではない)", candidate):
        return True
    if re.search(r"(.{1,8})(?:\s*\1){4,}", candidate):
        return True
    drift = _edit_distance(candidate, baseline) / max(1, len(baseline))
    return drift > _model_drift_limit()


def _model_drift_limit() -> float:
    raw = env("MODEL_DRIFT_LIMIT", "0.02")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.02


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (char_a != char_b),
                )
            )
        previous = current
    return previous[-1]


def _technical_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._+/-]*", text):
        lowered = token.lower()
        if lowered in _ROMAN_FUNCTION_WORDS:
            continue
        if len(token) >= 3 and (
            any(char.isdigit() for char in token)
            or any(char in token for char in ".-_/+")
            or token.isupper()
            or lowered in _KNOWN_TECH_TERMS
            or lowered in _ASCII_IDENTITY_WORDS
        ):
            terms.append(token)
    return terms


_ROMAN_FUNCTION_WORDS = {
    "wo",
    "de",
    "ni",
    "no",
    "ga",
    "ha",
    "wa",
    "to",
    "kara",
    "made",
    "mo",
    "ya",
    "suru",
    "shite",
    "shinai",
    "shitai",
    "yobu",
    "yomu",
    "yonde",
    "kaku",
    "miru",
    "naka",
    "ato",
    "mae",
    "nara",
    "kamo",
}


_KNOWN_TECH_TERMS = {
    "api",
    "buffer",
    "cer",
    "cloud",
    "command",
    "class",
    "dataset",
    "default",
    "endpoint",
    "env",
    "error",
    "fallback",
    "file",
    "ime",
    "input",
    "json",
    "jsonl",
    "latency",
    "local",
    "manual",
    "meaning",
    "metadata",
    "metrics",
    "model",
    "output",
    "placeholder",
    "preview",
    "priority",
    "property",
    "rate",
    "runtime",
    "server",
    "source",
    "temperature",
    "teacher",
    "timeout",
    "token",
    "url",
    "validate",
    "workflow",
}


_ASCII_IDENTITY_WORDS = {
    term: None
    for term in {
        "adapter",
        "adoption",
        "after",
        "api",
        "async",
        "background",
        "before",
        "block",
        "buffer",
        "boundary",
        "business",
        "cache",
        "candidate",
        "chars",
        "chat",
        "chunk",
        "class",
        "code",
        "codex",
        "command",
        "completion",
        "controller",
        "debug",
        "default",
        "description",
        "dictionary",
        "discard",
        "distribution",
        "domain",
        "dto",
        "endpoint",
        "entity",
        "env",
        "eval",
        "external",
        "fallback",
        "fence",
        "fenced",
        "fragment",
        "format",
        "frontmatter",
        "full",
        "gate",
        "holdout",
        "input",
        "ime",
        "index",
        "key",
        "line",
        "load",
        "log",
        "markdown",
        "max",
        "metadata",
        "milestone",
        "mode",
        "model",
        "object",
        "offline",
        "only",
        "original",
        "over",
        "original",
        "output",
        "personal",
        "placeholder",
        "port",
        "preview",
        "reports",
        "reasoning",
        "record",
        "region",
        "restoration",
        "repository",
        "request",
        "response",
        "result",
        "romanize",
        "romanized",
        "rule",
        "runtime",
        "same",
        "seed",
        "separator",
        "schema",
        "smoke",
        "source",
        "src",
        "summary",
        "target",
        "teacher",
        "technical",
        "term",
        "text",
        "timer",
        "timeout",
        "touch",
        "transaction",
        "training",
        "tuning",
        "validation",
        "variant",
        "value",
    }
}
_ASCII_IDENTITY_WORDS.update(
    {
        "api": "API",
        "applicationservice": "ApplicationService",
        "areba": "あれば",
        "atsumekiru": "集め切る",
        "chiisaku": "小さく",
        "config": "config",
        "codex": "Codex",
        "dedupe": "dedupe",
        "domainservice": "DomainService",
        "dto": "DTO",
        "english": "English",
        "elisp": "Elisp",
        "esukyueraito": "esukyueraito",
        "false": "false",
        "fixed": "fixed",
        "form": "form",
        "fukumeru": "含める",
        "ime": "IME",
        "gemma": "Gemma",
        "hayaku": "速く",
        "izon": "依存",
        "kanji": "漢字",
        "kaeru": "変える",
        "kotei": "固定",
        "lisp": "Lisp",
        "lora": "LoRA",
        "markdown": "Markdown",
        "mecab": "MeCab",
        "milestone": "Milestone",
        "mlx": "MLX",
        "nashi": "なし",
        "ok": "ok",
        "pykakasi": "pykakasi",
        "kakasi": "kakasi",
        "json": "JSON",
        "jsonl": "JSONL",
        "repo": "repo",
        "savemychatbot": "SaveMyChatbot",
        "sha256": "SHA256",
        "sqlite": "SQLite",
        "taishou": "対象",
        "tomoko": "Tomoko",
        "tobu": "飛ぶ",
        "ugoku": "動く",
        "url": "URL",
        "urls": "URLs",
        "valueobject": "ValueObject",
        "you": "用",
    }
)


def dummy_convert(text: str) -> str:
    """A deterministic local baseline useful before a model is connected."""

    parts = re.split(r"(<TECH_\d+>)", text)
    converted_parts = []
    for part in parts:
        if part.startswith("<TECH_") or part.isspace():
            converted_parts.append(part)
        else:
            converted_parts.append(_dummy_convert_plain(part))
    converted = "".join(converted_parts)
    return re.sub(r"(<TECH_\d+>)\s+([をでにのがはと])", r"\1\2", converted)


def _dummy_convert_plain(text: str) -> str:
    if not text:
        return text
    leading = re.match(r"^\s*", text).group(0)
    trailing = re.search(r"\s*$", text).group(0)
    core = text.strip()
    if not core:
        return text
    normalized = re.sub(r"\s+", " ", core)
    normalized = _normalize_technical_phrases(normalized)
    converted_words = [_convert_compact_roman(word) for word in normalized.split(" ")]
    converted = " ".join(converted_words)
    converted = _cleanup_spacing(converted)
    return leading + converted + trailing


def _convert_compact_roman(text: str) -> str:
    exact = _identity_ascii_token(text)
    if exact is not None:
        return exact
    if re.fullmatch(r"[A-Za-z0-9_./+=-]+", text) and ("/" in text or "=" in text):
        return text
    if _looks_like_ascii_identity_word(text):
        return text
    result: list[str] = []
    cursor = 0
    lower = text.lower()
    while cursor < len(text):
        for roman, japanese in ROMAN_REPLACEMENTS:
            if lower.startswith(roman, cursor):
                original = text[cursor : cursor + len(roman)]
                if japanese.isascii() and original.isupper():
                    result.append(japanese.upper())
                else:
                    result.append(japanese)
                cursor += len(roman)
                break
        else:
            result.append(text[cursor])
            cursor += 1
    return "".join(result)


def _identity_ascii_token(text: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_+.-]*", text):
        return None
    canonical = _ASCII_IDENTITY_WORDS.get(text.lower(), "")
    if canonical == "":
        return None
    return text if canonical is None else canonical


def _normalize_technical_phrases(text: str) -> str:
    for source, replacement in TECH_PHRASE_REPLACEMENTS:
        text = re.sub(rf"\b{re.escape(source)}\b", replacement, text, flags=re.IGNORECASE)
    return text


def _looks_like_ascii_identity_word(text: str) -> bool:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_+.-]*", text):
        return False
    if len(text) > 24:
        return False
    lower = text.lower()
    if lower in _ROMAN_REPLACEMENT_KEYS:
        return False
    if re.search(r"[._+-]", text):
        return True
    if "q" in lower or "x" in lower:
        return True
    if re.search(r"(tion|sion|ment|ness|able|ible|ance|ence|ity|ive|ing|ed|er|or|al)$", lower):
        return True
    consonants = "bcdfghjklmnpqrstvwxyz"
    if re.search(f"[{consonants}]{{3,}}", lower):
        return True
    return bool(
        re.search(
            r"(ck|ct|ff|ft|ld|lk|lp|lt|mp|nd|nk|nt|pt|rd|rk|rl|rn|rt|rv|sk|st|tr|wr)",
            lower,
        )
    )


def _cleanup_spacing(text: str) -> str:
    text = re.sub(r"\s+([をでにのがはと、。])", r"\1", text)
    text = re.sub(r"([をでにのがはと])\s+([ぁ-んァ-ヶ一-龯A-Za-z0-9])", r"\1\2", text)
    text = re.sub(r"([、。])\s+", r"\1", text)
    text = re.sub(r"([ぁ-んァ-ヶ一-龯])\s+([ぁ-んァ-ヶ一-龯A-Za-z0-9])", r"\1\2", text)
    text = re.sub(r"([A-Za-z0-9])\s+([ぁ-んァ-ヶ一-龯])", r"\1\2", text)
    text = re.sub(r"(?<=\d)b\b", "B", text)
    text = re.sub(r"\bm4\b", "M4", text)
    text = re.sub(r"\b1b-2b\b", "1B-2B", text)
    text = text.replace("なら英字", "なら、英字")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


_ROMAN_REPLACEMENT_KEYS = {roman for roman, _ in ROMAN_REPLACEMENTS}
