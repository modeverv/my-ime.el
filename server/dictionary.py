"""Local personal dictionary support for my-ime."""

from __future__ import annotations

from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import re
from typing import Iterable

from .config import env


PLACEHOLDER_SPLIT_RE = re.compile(r"(<TECH_\d+>)")
SKK_CANDIDATE_RE = re.compile(r"/([^/;]+)(?:;[^/]*)?/")
ASCII_RUN_RE = re.compile(r"[A-Za-z0-9_]+")
PASSTHROUGH_ROMAJI_TOKENS = (
    "kara",
    "made",
    "yori",
    "wo",
    "de",
    "ni",
    "no",
    "ga",
    "ha",
    "wa",
    "to",
    "mo",
    "ka",
    "ya",
    "e",
    "he",
)


class DictionaryError(RuntimeError):
    """Raised when a personal dictionary cannot be loaded."""


@lru_cache(maxsize=16)
def load_dictionary(source: str) -> tuple[tuple[str, str], ...]:
    """Load dictionary entries from JSON text or a file path."""

    if not source:
        return ()
    path = Path(source).expanduser()
    if path.exists():
        text = path.read_text(encoding="utf-8")
        entries = _parse_dictionary_text(text, path.suffix.lower())
    else:
        entries = _parse_dictionary_text(source, ".json")
    return tuple(sorted(entries, key=lambda item: len(item[0]), reverse=True))


def configured_dictionary() -> tuple[tuple[str, str], ...]:
    """Return entries from environment configuration."""

    inline = env("DICTIONARY")
    path = env("DICTIONARY_PATH")
    entries: list[tuple[str, str]] = []
    for default_path in _default_dictionary_paths():
        entries.extend(load_dictionary(str(default_path)))
    if inline:
        entries.extend(load_dictionary(inline))
    if path:
        entries.extend(load_dictionary(path))
    return tuple(sorted(_dedupe(entries), key=lambda item: len(item[0]), reverse=True))


@lru_cache(maxsize=16)
def load_dictionary_candidates(source: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Load dictionary entries preserving multiple candidates for each input."""

    if not source:
        return ()
    path = Path(source).expanduser()
    if path.exists():
        text = path.read_text(encoding="utf-8")
        entries = _parse_dictionary_candidate_text(text, path.suffix.lower())
    else:
        entries = _parse_dictionary_candidate_text(source, ".json")
    return tuple(sorted(entries, key=lambda item: len(item[0]), reverse=True))


def configured_dictionary_candidates() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return entries from environment configuration with alternatives intact."""

    inline = env("DICTIONARY")
    path = env("DICTIONARY_PATH")
    entries: list[tuple[str, tuple[str, ...]]] = []
    for default_path in _default_dictionary_paths():
        entries.extend(load_dictionary_candidates(str(default_path)))
    if inline:
        entries.extend(load_dictionary_candidates(inline))
    if path:
        entries.extend(load_dictionary_candidates(path))
    return tuple(
        sorted(_dedupe_candidate_entries(entries), key=lambda item: len(item[0]), reverse=True)
    )


def _default_dictionary_paths() -> list[Path]:
    candidates = [
        Path.cwd() / "data",
        Path(__file__).resolve().parents[1] / "data",
    ]
    paths: list[Path] = []
    seen: set[Path] = set()
    for directory in candidates:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.skk")):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(path)
    return paths


def apply_dictionary(text: str, entries: Iterable[tuple[str, str]] | None = None) -> str:
    """Apply personal dictionary entries outside protected placeholders."""

    entries = tuple(entries if entries is not None else configured_dictionary())
    if not entries:
        return text
    parts = PLACEHOLDER_SPLIT_RE.split(text)
    converted: list[str] = []
    for part in parts:
        if PLACEHOLDER_SPLIT_RE.fullmatch(part):
            converted.append(part)
        else:
            converted.append(_apply_entries_to_plain_text(part, entries))
    return "".join(converted)


def apply_dictionary_with_placeholders(
    text: str,
    entries: Iterable[tuple[str, str]] | None = None,
    placeholder_start: int = 0,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Apply dictionary entries as transient placeholders.

    The returned spans are ``(placeholder, target)`` pairs. This lets callers
    keep dictionary-confirmed Japanese out of a later kana-kanji pass.
    """

    entries = tuple(entries if entries is not None else configured_dictionary())
    if not entries:
        return text, ()

    parts = PLACEHOLDER_SPLIT_RE.split(text)
    converted: list[str] = []
    spans: list[tuple[str, str]] = []
    next_index = placeholder_start
    for part in parts:
        if PLACEHOLDER_SPLIT_RE.fullmatch(part):
            converted.append(part)
            continue
        converted_part, part_spans, next_index = _apply_entries_as_placeholders_to_plain_text(
            part,
            entries,
            next_index,
        )
        converted.append(converted_part)
        spans.extend(part_spans)
    return "".join(converted), tuple(spans)


def apply_dictionary_candidate_sets_with_placeholders(
    text: str,
    entries: Iterable[tuple[str, tuple[str, ...]]] | None = None,
    placeholder_start: int = 0,
    per_word_limit: int = 3,
    max_candidates: int = 50,
) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    """Apply dictionary alternatives and return protected sentence candidates."""

    entries = tuple(entries if entries is not None else configured_dictionary_candidates())
    if not entries:
        return [(text, ())]
    per_word_limit = max(1, per_word_limit)
    max_candidates = max(1, max_candidates)
    parts = PLACEHOLDER_SPLIT_RE.split(text)
    states: list[tuple[str, list[tuple[str, str]], int]] = [("", [], placeholder_start)]
    for part in parts:
        next_states: list[tuple[str, list[tuple[str, str]], int]] = []
        if PLACEHOLDER_SPLIT_RE.fullmatch(part):
            next_states = [
                (prefix + part, spans, next_index)
                for prefix, spans, next_index in states
            ]
        else:
            for prefix, spans, next_index in states:
                for converted, part_spans, new_next_index in _plain_text_candidate_variants(
                    part,
                    entries,
                    next_index,
                    per_word_limit,
                    max_candidates,
                ):
                    next_states.append((prefix + converted, spans + part_spans, new_next_index))
                    if len(next_states) >= max_candidates:
                        break
                if len(next_states) >= max_candidates:
                    break
        states = next_states[:max_candidates]
    return [(candidate_text, tuple(spans)) for candidate_text, spans, _next_index in states]


def _parse_dictionary_text(text: str, suffix: str) -> list[tuple[str, str]]:
    stripped = text.strip()
    if not stripped:
        return []
    if suffix == ".json" or stripped.startswith(("{", "[")):
        return _parse_json_dictionary(stripped)
    if suffix == ".skk" or "/" in stripped:
        return _parse_skk_dictionary(stripped)
    return _parse_tsv_dictionary(stripped)


def _parse_dictionary_candidate_text(text: str, suffix: str) -> list[tuple[str, tuple[str, ...]]]:
    stripped = text.strip()
    if not stripped:
        return []
    if suffix == ".json" or stripped.startswith(("{", "[")):
        return _parse_json_dictionary_candidates(stripped)
    if suffix == ".skk" or "/" in stripped:
        return _parse_skk_dictionary_candidates(stripped)
    return [(source, (target,)) for source, target in _parse_tsv_dictionary(stripped)]


def _parse_json_dictionary(text: str) -> list[tuple[str, str]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DictionaryError(f"invalid dictionary JSON: {exc}") from exc
    if isinstance(payload, dict):
        raw_entries = payload.items()
    elif isinstance(payload, list):
        raw_entries = []
        for item in payload:
            if not isinstance(item, dict):
                raise DictionaryError("dictionary list entries must be objects")
            raw_entries.append((item.get("input"), item.get("output")))
    else:
        raise DictionaryError("dictionary JSON must be an object or list")
    return _validate_entries(raw_entries)


def _parse_json_dictionary_candidates(text: str) -> list[tuple[str, tuple[str, ...]]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DictionaryError(f"invalid dictionary JSON: {exc}") from exc
    if isinstance(payload, dict):
        raw_entries = payload.items()
    elif isinstance(payload, list):
        raw_entries = []
        for item in payload:
            if not isinstance(item, dict):
                raise DictionaryError("dictionary list entries must be objects")
            raw_entries.append((item.get("input"), item.get("output")))
    else:
        raise DictionaryError("dictionary JSON must be an object or list")
    return _validate_candidate_entries(raw_entries)


def _parse_tsv_dictionary(text: str) -> list[tuple[str, str]]:
    raw_entries: list[tuple[str, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" not in line:
            raise DictionaryError(f"line {line_number}: expected tab-separated input/output")
        left, right = line.split("\t", 1)
        raw_entries.append((left, right))
    return _validate_entries(raw_entries)


def _parse_skk_dictionary(text: str) -> list[tuple[str, str]]:
    raw_entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if " " not in line:
            continue
        key, candidates = line.split(None, 1)
        match = SKK_CANDIDATE_RE.search(candidates)
        if match is not None:
            raw_entries.append((key, match.group(1)))
    return _validate_entries(raw_entries)


def _parse_skk_dictionary_candidates(text: str) -> list[tuple[str, tuple[str, ...]]]:
    raw_entries: list[tuple[str, tuple[str, ...]]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if " " not in line:
            continue
        key, candidates = line.split(None, 1)
        targets = tuple(
            part.split(";", 1)[0]
            for part in candidates.split("/")
            if part and part.split(";", 1)[0]
        )
        if targets:
            raw_entries.append((key, targets))
    return _dedupe_candidate_entries(raw_entries)


def _validate_entries(raw_entries: Iterable[tuple[object, object]]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for source, target in raw_entries:
        if isinstance(target, list):
            target = next((value for value in target if isinstance(value, str)), None)
        if not isinstance(source, str) or not isinstance(target, str):
            raise DictionaryError("dictionary entries must be string to string")
        source = source.strip()
        if not source:
            raise DictionaryError("dictionary input must not be empty")
        entries.append((source, target))
    return _dedupe(entries)


def _validate_candidate_entries(
    raw_entries: Iterable[tuple[object, object]],
) -> list[tuple[str, tuple[str, ...]]]:
    entries: list[tuple[str, tuple[str, ...]]] = []
    for source, targets in raw_entries:
        if not isinstance(source, str):
            raise DictionaryError("dictionary input must be a string")
        source = source.strip()
        if not source:
            raise DictionaryError("dictionary input must not be empty")
        if isinstance(targets, str):
            values = (targets,)
        elif isinstance(targets, list):
            values = tuple(target for target in targets if isinstance(target, str))
            if len(values) != len(targets):
                raise DictionaryError("dictionary output candidates must be strings")
        else:
            raise DictionaryError("dictionary output must be a string or list of strings")
        cleaned = tuple(target for target in (value.strip() for value in values) if target)
        if not cleaned:
            raise DictionaryError("dictionary output must not be empty")
        entries.append((source, cleaned))
    return _dedupe_candidate_entries(entries)


def _dedupe(entries: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for source, target in entries:
        if source in seen:
            continue
        seen.add(source)
        deduped.append((source, target))
    return deduped


def _dedupe_candidate_entries(
    entries: Iterable[tuple[str, tuple[str, ...]]],
) -> list[tuple[str, tuple[str, ...]]]:
    merged: dict[str, list[str]] = {}
    for source, targets in entries:
        bucket = merged.setdefault(source, [])
        for target in targets:
            if target not in bucket:
                bucket.append(target)
    return [(source, tuple(targets)) for source, targets in merged.items()]


def _apply_entries_to_plain_text(text: str, entries: Iterable[tuple[str, str]]) -> str:
    result = text
    ascii_entries: list[tuple[str, str]] = []
    for source, target in entries:
        if re.fullmatch(r"[A-Za-z0-9_]+", source):
            ascii_entries.append((source, target))
        else:
            result = result.replace(source, target)
    if ascii_entries:
        result = ASCII_RUN_RE.sub(
            lambda match: _replace_ascii_run(match.group(0), ascii_entries),
            result,
        )
    return result


def _apply_entries_as_placeholders_to_plain_text(
    text: str,
    entries: Iterable[tuple[str, str]],
    placeholder_start: int,
) -> tuple[str, list[tuple[str, str]], int]:
    result = text
    spans: list[tuple[str, str]] = []
    next_index = placeholder_start
    ascii_entries: list[tuple[str, str]] = []
    for source, target in entries:
        if re.fullmatch(r"[A-Za-z0-9_]+", source):
            ascii_entries.append((source, target))
        else:
            result = result.replace(source, target)

    def replace(match: re.Match[str]) -> str:
        nonlocal next_index
        replaced, run_spans, next_index = _replace_ascii_run_with_placeholders(
            match.group(0),
            ascii_entries,
            next_index,
        )
        spans.extend(run_spans)
        return replaced

    if ascii_entries:
        result = ASCII_RUN_RE.sub(replace, result)
    return result, spans, next_index


def _replace_ascii_run(text: str, entries: Iterable[tuple[str, str]]) -> str:
    """Convert an ASCII run only when dictionary segmentation reaches the end."""

    tokens = _segment_ascii_run(text, entries)
    if tokens is None:
        return text
    return "".join(target for _source, target, converted in tokens if converted or target)


def _replace_ascii_run_with_placeholders(
    text: str,
    entries: Iterable[tuple[str, str]],
    placeholder_start: int,
) -> tuple[str, list[tuple[str, str]], int]:
    tokens = _segment_ascii_run(text, entries)
    if tokens is None:
        return text, [], placeholder_start

    result: list[str] = []
    spans: list[tuple[str, str]] = []
    next_index = placeholder_start
    for source, target, converted in tokens:
        if not converted:
            result.append(source)
            continue
        placeholder = f"<TECH_{next_index}>"
        next_index += 1
        result.append(placeholder)
        spans.append((placeholder, target))
    return "".join(result), spans, next_index


def _plain_text_candidate_variants(
    text: str,
    entries: Iterable[tuple[str, tuple[str, ...]]],
    placeholder_start: int,
    per_word_limit: int,
    max_candidates: int,
) -> list[tuple[str, list[tuple[str, str]], int]]:
    result = text
    ascii_entries: list[tuple[str, tuple[str, ...]]] = []
    for source, targets in entries:
        if re.fullmatch(r"[A-Za-z0-9_]+", source):
            ascii_entries.append((source, targets))
        else:
            result = result.replace(source, targets[0])

    states: list[tuple[str, list[tuple[str, str]], int]] = [("", [], placeholder_start)]
    cursor = 0
    for match in ASCII_RUN_RE.finditer(result):
        literal = result[cursor : match.start()]
        if literal:
            states = [(prefix + literal, spans, next_index) for prefix, spans, next_index in states]
        next_states: list[tuple[str, list[tuple[str, str]], int]] = []
        for prefix, spans, next_index in states:
            for converted, run_spans, new_next_index in _ascii_run_candidate_variants(
                match.group(0),
                ascii_entries,
                next_index,
                per_word_limit,
                max_candidates,
            ):
                next_states.append((prefix + converted, spans + run_spans, new_next_index))
                if len(next_states) >= max_candidates:
                    break
            if len(next_states) >= max_candidates:
                break
        states = next_states[:max_candidates]
        cursor = match.end()
    tail = result[cursor:]
    if tail:
        states = [(prefix + tail, spans, next_index) for prefix, spans, next_index in states]
    return states[:max_candidates]


def _ascii_run_candidate_variants(
    text: str,
    entries: Iterable[tuple[str, tuple[str, ...]]],
    placeholder_start: int,
    per_word_limit: int,
    max_candidates: int,
) -> list[tuple[str, list[tuple[str, str]], int]]:
    tokens = _segment_ascii_run_candidates(text, entries)
    if tokens is None:
        return [(text, [], placeholder_start)]

    option_sets: list[tuple[tuple[str, tuple[str, ...], bool], ...]] = []
    for source, targets, converted in tokens:
        if converted:
            options = tuple((source, (target,), True) for target in targets[:per_word_limit])
        else:
            options = ((source, (source,), False),)
        option_sets.append(options)

    variants: list[tuple[str, list[tuple[str, str]], int]] = []
    for combination in product(*option_sets):
        result: list[str] = []
        spans: list[tuple[str, str]] = []
        next_index = placeholder_start
        for source, targets, converted in combination:
            target = targets[0]
            if not converted:
                result.append(source)
                continue
            placeholder = f"<TECH_{next_index}>"
            next_index += 1
            result.append(placeholder)
            spans.append((placeholder, target))
        variants.append(("".join(result), spans, next_index))
        if len(variants) >= max_candidates:
            break
    return variants


def _segment_ascii_run_candidates(
    text: str,
    entries: Iterable[tuple[str, tuple[str, ...]]],
) -> tuple[tuple[str, tuple[str, ...], bool], ...] | None:
    """Return dictionary segmentation with candidate targets for TEXT."""

    entry_map = {source: targets for source, targets in entries}
    starts: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for source, targets in entries:
        starts.setdefault(source[0], []).append((source, targets))
    for candidates in starts.values():
        candidates.sort(key=lambda item: len(item[0]), reverse=True)

    best: dict[
        int,
        tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]] | None,
    ] = {len(text): (0, 0, ())}

    def solve(index: int) -> tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]] | None:
        if index in best:
            return best[index]
        result: tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]] | None = None

        for source, targets in starts.get(text[index], []):
            if not text.startswith(source, index):
                continue
            tail = solve(index + len(source))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars + len(source),
                segments + 1,
                ((source, targets, True),) + suffix,
            )
            result = _prefer_ascii_candidate_segmentation(result, candidate)

        for token in PASSTHROUGH_ROMAJI_TOKENS:
            if token in entry_map or not text.startswith(token, index):
                continue
            tail = solve(index + len(token))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars,
                segments + 1,
                ((token, (token,), False),) + suffix,
            )
            result = _prefer_ascii_candidate_segmentation(result, candidate)

        best[index] = result
        return result

    solved = solve(0)
    if solved is None or solved[0] == 0:
        return None
    return solved[2]


def _prefer_ascii_candidate_segmentation(
    current: tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]] | None,
    candidate: tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]],
) -> tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]]:
    if current is None:
        return candidate
    if candidate[0] != current[0]:
        return candidate if candidate[0] > current[0] else current
    if candidate[1] != current[1]:
        return candidate if candidate[1] < current[1] else current
    candidate_length = sum(len(targets[0]) for _source, targets, _converted in candidate[2])
    current_length = sum(len(targets[0]) for _source, targets, _converted in current[2])
    return candidate if candidate_length < current_length else current


def _segment_ascii_run(
    text: str,
    entries: Iterable[tuple[str, str]],
) -> tuple[tuple[str, str, bool], ...] | None:
    """Return dictionary segmentation for TEXT, or nil when not fully consumed."""

    entry_map = {source: target for source, target in entries}
    starts: dict[str, list[tuple[str, str]]] = {}
    for source, target in entries:
        starts.setdefault(source[0], []).append((source, target))
    for candidates in starts.values():
        candidates.sort(key=lambda item: len(item[0]), reverse=True)

    best: dict[int, tuple[int, int, tuple[tuple[str, str, bool], ...]] | None] = {
        len(text): (0, 0, ())
    }

    def solve(index: int) -> tuple[int, int, tuple[tuple[str, str, bool], ...]] | None:
        if index in best:
            return best[index]
        result: tuple[int, int, tuple[tuple[str, str, bool], ...]] | None = None

        for source, target in starts.get(text[index], []):
            if not text.startswith(source, index):
                continue
            tail = solve(index + len(source))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars + len(source),
                segments + 1,
                ((source, target, True),) + suffix,
            )
            result = _prefer_ascii_segmentation(result, candidate)

        for token in PASSTHROUGH_ROMAJI_TOKENS:
            if token in entry_map or not text.startswith(token, index):
                continue
            tail = solve(index + len(token))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars,
                segments + 1,
                ((token, token, False),) + suffix,
            )
            result = _prefer_ascii_segmentation(result, candidate)

        best[index] = result
        return result

    solved = solve(0)
    if solved is None or solved[0] == 0:
        return None
    return solved[2]


def _prefer_ascii_segmentation(
    current: tuple[int, int, tuple[tuple[str, str, bool], ...]] | None,
    candidate: tuple[int, int, tuple[tuple[str, str, bool], ...]],
) -> tuple[int, int, tuple[tuple[str, str, bool], ...]]:
    if current is None:
        return candidate
    if candidate[0] != current[0]:
        return candidate if candidate[0] > current[0] else current
    if candidate[1] != current[1]:
        return candidate if candidate[1] < current[1] else current
    candidate_length = sum(len(target) for _source, target, _converted in candidate[2])
    current_length = sum(len(target) for _source, target, _converted in current[2])
    return candidate if candidate_length < current_length else current
