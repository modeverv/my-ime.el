"""Protect technical spans before sending text to a converter backend."""

from __future__ import annotations

from dataclasses import dataclass
import re


class ProtectionError(RuntimeError):
    """Raised when protected placeholders cannot be restored safely."""


@dataclass(frozen=True)
class ProtectedSpan:
    placeholder: str
    original: str
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class ProtectedText:
    text: str
    spans: tuple[ProtectedSpan, ...]


PARTICLE_JOIN = r"(?:wo|de|ni|ga|ha|wa|to|kara|made|no|mo)"
PARTICLES = ("kara", "made", "wo", "de", "ni", "ga", "ha", "wa", "to", "no", "mo")
SHORT_ROMAJI_SEGMENTS = {
    "a",
    "i",
    "u",
    "e",
    "o",
    "ka",
    "ki",
    "ku",
    "ke",
    "ko",
    "sa",
    "si",
    "shi",
    "su",
    "se",
    "so",
    "ta",
    "ti",
    "chi",
    "tu",
    "tsu",
    "te",
    "to",
    "na",
    "ni",
    "nu",
    "ne",
    "no",
    "ha",
    "hi",
    "hu",
    "fu",
    "he",
    "ho",
    "ma",
    "mi",
    "mu",
    "me",
    "mo",
    "ya",
    "yu",
    "yo",
    "ra",
    "ri",
    "ru",
    "re",
    "ro",
    "wa",
    "wo",
    "ga",
    "gi",
    "gu",
    "ge",
    "go",
    "za",
    "zi",
    "ji",
    "zu",
    "ze",
    "zo",
    "da",
    "di",
    "du",
    "de",
    "do",
    "ba",
    "bi",
    "bu",
    "be",
    "bo",
    "pa",
    "pi",
    "pu",
    "pe",
    "po",
}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("manual_term", re.compile(r";;[^;\n]+;;")),
    ("url", re.compile(r"https?://[^\s<>()\"']+")),
    ("lisp_form", re.compile(r"\([A-Za-z0-9_+*/<>=!?$%&~.^:-]+(?:\s+[^()\n]+)*\)")),
    ("file_path", re.compile(r"(?:~|\.{1,2})?/[A-Za-z0-9._~:@%+,\-=/]+")),
    ("api_path", re.compile(r"/[A-Za-z0-9._~:@%+,\-]+(?:/[A-Za-z0-9._~:@%+,\-]+)+")),
    ("mx_command", re.compile(r"\bM-x\s+[A-Za-z0-9_+*/<>=!?$%&~.^:-]+\b")),
    (
        "shell_invocation",
        re.compile(
            r"\b(?:git|curl|python|python3|rg|grep|make|npm|pnpm|uv|emacs)"
            r"(?:\s+-{1,2}[A-Za-z0-9][A-Za-z0-9-]*)*"
        ),
    ),
    (
        "keybinding",
        re.compile(
            r"\b(?:C|M|S|A|s)-[A-Za-z0-9<>?/-]+"
            r"(?:\s+(?:(?:C|M|S|A|s)-)?(?:[A-Za-z0-9]|<[^>]+>))*\b"
        ),
    ),
    (
        "identifier",
        re.compile(
            rf"\b[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+?"
            rf"(?={PARTICLE_JOIN}(?:[A-Za-z]|$)|$|[^A-Za-z0-9_-])"
        ),
    ),
    ("likely_command", re.compile(r"\b(?:git|curl|python|python3|rg|grep|make|npm|pnpm|uv|emacs)\b")),
)

PLACEHOLDER_RE = re.compile(r"<TECH_(\d+)>")


def protect_text(text: str) -> ProtectedText:
    """Replace technical-looking spans with stable placeholders."""

    if text.count(";;") % 2 != 0:
        raise ProtectionError("manual term marker is unbalanced")

    candidates: list[tuple[int, int, str, int]] = []
    for priority, (kind, pattern) in enumerate(PATTERNS):
        for match in pattern.finditer(text):
            start, end = match.span()
            if start == end:
                continue
            if kind == "identifier":
                for sub_start, sub_end in _split_identifier_candidate(text[start:end], start):
                    candidates.append((sub_start, sub_end, kind, priority))
            else:
                candidates.append((start, end, kind, priority))

    selected: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, kind, _priority in sorted(candidates, key=lambda item: (item[0], item[3], -(item[1] - item[0]))):
        if any(start < old_end and end > old_start for old_start, old_end in occupied):
            continue
        selected.append((start, end, kind))
        occupied.append((start, end))

    parts: list[str] = []
    spans: list[ProtectedSpan] = []
    cursor = 0
    for index, (start, end, kind) in enumerate(selected):
        placeholder = f"<TECH_{index}>"
        original = text[start:end]
        if kind == "manual_term":
            original = original[2:-2]
        parts.append(text[cursor:start])
        parts.append(placeholder)
        spans.append(ProtectedSpan(placeholder, original, start, end, kind))
        cursor = end
    parts.append(text[cursor:])

    return ProtectedText("".join(parts), tuple(spans))


def restore_text(converted_text: str, protected: ProtectedText) -> str:
    """Restore placeholders, validating that no placeholder was lost or duplicated."""

    expected = {span.placeholder for span in protected.spans}
    found = PLACEHOLDER_RE.findall(converted_text)
    found_placeholders = [f"<TECH_{index}>" for index in found]

    missing = sorted(expected - set(found_placeholders))
    extra = sorted(set(found_placeholders) - expected)
    duplicates = sorted(
        placeholder for placeholder in expected if found_placeholders.count(placeholder) > 1
    )
    if missing or extra or duplicates:
        detail = []
        if missing:
            detail.append(f"missing={','.join(missing)}")
        if extra:
            detail.append(f"extra={','.join(extra)}")
        if duplicates:
            detail.append(f"duplicates={','.join(duplicates)}")
        raise ProtectionError("placeholder restoration failed: " + " ".join(detail))

    restored = converted_text
    for span in protected.spans:
        restored = restored.replace(span.placeholder, span.original)
    if PLACEHOLDER_RE.search(restored):
        raise ProtectionError("placeholder restoration failed: unresolved placeholder")
    return restored


def protected_tokens(text: str) -> list[str]:
    """Return the original tokens that would be protected."""

    return [span.original for span in protect_text(text).spans]


def _split_identifier_candidate(value: str, absolute_start: int) -> list[tuple[int, int]]:
    """Split over-greedy joined identifiers at romanized particle boundaries."""

    spans: list[tuple[int, int]] = []
    offset = 0
    while offset < len(value):
        join = _find_join_to_next_identifier(value, offset)
        if join is not None:
            particle_start, particle_end = join
            _append_identifier_span(spans, value, absolute_start, offset, particle_start)
            offset = particle_end
            continue

        terminal = _find_terminal_particle(value, offset)
        if terminal is not None:
            _append_identifier_span(spans, value, absolute_start, offset, terminal)
        else:
            _append_identifier_span(spans, value, absolute_start, offset, len(value))
        break
    return spans


def _append_identifier_span(
    spans: list[tuple[int, int]], value: str, absolute_start: int, start: int, end: int
) -> None:
    candidate = value[start:end]
    if re.fullmatch(r"[A-Z][A-Z0-9_]+", candidate):
        return
    if _looks_like_short_hyphenated_romaji(candidate):
        return
    if "-" in candidate or "_" in candidate:
        spans.append((absolute_start + start, absolute_start + end))


def _looks_like_short_hyphenated_romaji(value: str) -> bool:
    lowered = value.lower()
    if "_" in lowered or lowered.count("-") != 1:
        return False
    parts = lowered.split("-")
    return (
        parts[0] in SHORT_ROMAJI_SEGMENTS
        and _short_romaji_segment_with_optional_particle_p(parts[1])
    )


def _short_romaji_segment_with_optional_particle_p(value: str) -> bool:
    if value in SHORT_ROMAJI_SEGMENTS:
        return True
    return any(
        value == segment + particle
        for segment in SHORT_ROMAJI_SEGMENTS
        for particle in PARTICLES
    )


def _find_join_to_next_identifier(value: str, start: int) -> tuple[int, int] | None:
    for index in range(start + 1, len(value)):
        for particle in PARTICLES:
            if not value.startswith(particle, index):
                continue
            prefix = value[start:index]
            suffix = value[index + len(particle) :]
            if ("-" not in prefix and "_" not in prefix) or not suffix:
                continue
            if prefix.endswith(("-", "_")):
                continue
            if re.match(r"[A-Za-z][A-Za-z0-9]*[-_]", suffix):
                return (index, index + len(particle))
    return None


def _find_terminal_particle(value: str, start: int) -> int | None:
    for index in range(start + 1, len(value)):
        for particle in PARTICLES:
            if not value.startswith(particle, index):
                continue
            prefix = value[start:index]
            suffix = value[index + len(particle) :]
            if ("-" not in prefix and "_" not in prefix) or not suffix:
                continue
            if prefix.endswith(("-", "_")) or "-" in suffix or "_" in suffix:
                continue
            if len(suffix) < 4 or not _looks_like_romanized_tail(suffix):
                continue
            return index
    return None


def _looks_like_romanized_tail(value: str) -> bool:
    lowered = value.lower()
    markers = (
        "suru",
        "shinai",
        "shitai",
        "shita",
        "yobu",
        "yomu",
        "deki",
        "naru",
        "naka",
        "toki",
        "mama",
        "omoi",
    )
    return any(marker in lowered for marker in markers)
