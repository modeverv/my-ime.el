"""Small romaji-to-hiragana converter for deterministic IME input."""

from __future__ import annotations

import re


PLACEHOLDER_RE = re.compile(r"(<TECH_\d+>)")


def romaji_to_hiragana(text: str) -> str:
    """Convert romanized Japanese outside placeholders to hiragana.

    This is intentionally small and IME-oriented. It accepts compact input
    such as ``dekaihatusuru`` and space-separated input such as ``de yaru``.
    Unknown ASCII characters are preserved so callers can fail or protect
    terms at a higher layer.
    """

    parts = PLACEHOLDER_RE.split(text)
    converted: list[str] = []
    for part in parts:
        if PLACEHOLDER_RE.fullmatch(part):
            converted.append(part)
        else:
            converted.append(_plain_romaji_to_hiragana(part))
    return "".join(converted)


def _plain_romaji_to_hiragana(text: str) -> str:
    text = normalize_romaji(text)
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if not char.isascii() or not char.isalpha():
            result.append(char)
            index += 1
            continue

        lower = text[index:].lower()
        if len(lower) >= 2 and lower[0] == lower[1] and lower[0] not in "aeioun":
            result.append("っ")
            index += 1
            continue
        if lower.startswith("n'"):
            result.append("ん")
            index += 2
            continue
        if lower[0] == "n" and (len(lower) == 1 or lower[1] not in "aeiouy"):
            result.append("ん")
            index += 1
            continue

        matched = False
        for width in (3, 2, 1):
            chunk = lower[:width]
            kana = ROMAJI_TABLE.get(chunk)
            if kana is None:
                continue
            result.append(kana)
            index += width
            matched = True
            break
        if not matched:
            result.append(char)
            index += 1
    return "".join(result)


def normalize_romaji(text: str) -> str:
    """Normalize common compact-input slips before kana conversion."""

    return re.sub(r"nn(?=[bcdfghjklmpqrstvwxyz])", "n", text, flags=re.IGNORECASE)


ROMAJI_TABLE: dict[str, str] = {
    "a": "あ",
    "i": "い",
    "u": "う",
    "e": "え",
    "o": "お",
    "ka": "か",
    "ki": "き",
    "ku": "く",
    "ke": "け",
    "ko": "こ",
    "kya": "きゃ",
    "kyu": "きゅ",
    "kyo": "きょ",
    "ga": "が",
    "gi": "ぎ",
    "gu": "ぐ",
    "ge": "げ",
    "go": "ご",
    "gya": "ぎゃ",
    "gyu": "ぎゅ",
    "gyo": "ぎょ",
    "sa": "さ",
    "si": "し",
    "shi": "し",
    "su": "す",
    "se": "せ",
    "so": "そ",
    "sya": "しゃ",
    "sha": "しゃ",
    "syu": "しゅ",
    "shu": "しゅ",
    "syo": "しょ",
    "sho": "しょ",
    "za": "ざ",
    "zi": "じ",
    "ji": "じ",
    "zu": "ず",
    "ze": "ぜ",
    "zo": "ぞ",
    "zya": "じゃ",
    "ja": "じゃ",
    "zyu": "じゅ",
    "ju": "じゅ",
    "zyo": "じょ",
    "jo": "じょ",
    "ta": "た",
    "ti": "ち",
    "chi": "ち",
    "tu": "つ",
    "tsu": "つ",
    "te": "て",
    "to": "と",
    "tya": "ちゃ",
    "cha": "ちゃ",
    "tyu": "ちゅ",
    "chu": "ちゅ",
    "tyo": "ちょ",
    "cho": "ちょ",
    "da": "だ",
    "di": "ぢ",
    "du": "づ",
    "de": "で",
    "do": "ど",
    "dya": "ぢゃ",
    "dyu": "ぢゅ",
    "dyo": "ぢょ",
    "na": "な",
    "ni": "に",
    "nu": "ぬ",
    "ne": "ね",
    "no": "の",
    "nya": "にゃ",
    "nyu": "にゅ",
    "nyo": "にょ",
    "ha": "は",
    "hi": "ひ",
    "hu": "ふ",
    "fu": "ふ",
    "he": "へ",
    "ho": "ほ",
    "hya": "ひゃ",
    "hyu": "ひゅ",
    "hyo": "ひょ",
    "ba": "ば",
    "bi": "び",
    "bu": "ぶ",
    "be": "べ",
    "bo": "ぼ",
    "bya": "びゃ",
    "byu": "びゅ",
    "byo": "びょ",
    "pa": "ぱ",
    "pi": "ぴ",
    "pu": "ぷ",
    "pe": "ぺ",
    "po": "ぽ",
    "pya": "ぴゃ",
    "pyu": "ぴゅ",
    "pyo": "ぴょ",
    "ma": "ま",
    "mi": "み",
    "mu": "む",
    "me": "め",
    "mo": "も",
    "mya": "みゃ",
    "myu": "みゅ",
    "myo": "みょ",
    "ya": "や",
    "yu": "ゆ",
    "yo": "よ",
    "ra": "ら",
    "ri": "り",
    "ru": "る",
    "re": "れ",
    "ro": "ろ",
    "rya": "りゃ",
    "ryu": "りゅ",
    "ryo": "りょ",
    "wa": "わ",
    "wi": "うぃ",
    "we": "うぇ",
    "wo": "を",
    "va": "ゔぁ",
    "vi": "ゔぃ",
    "vu": "ゔ",
    "ve": "ゔぇ",
    "vo": "ゔぉ",
    "la": "ぁ",
    "li": "ぃ",
    "lu": "ぅ",
    "le": "ぇ",
    "lo": "ぉ",
    "xa": "ぁ",
    "xi": "ぃ",
    "xu": "ぅ",
    "xe": "ぇ",
    "xo": "ぉ",
    "ltu": "っ",
    "xtu": "っ",
}
