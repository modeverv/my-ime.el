"""Local personal dictionary support for my-ime."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import re
from typing import Any, Iterable

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


@dataclass(frozen=True)
class _DictionaryIndex:
    other_non_ascii: tuple[tuple[str, str], ...]
    hyphen_by_sig: dict[str, tuple[tuple[int, str, str], ...]]
    has_ascii_entries: bool
    trie_root: dict[str, object]
    passthrough_by_char: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class _CandidateDictionaryIndex:
    other_non_ascii: tuple[tuple[str, tuple[str, ...]], ...]
    hyphen_by_sig: dict[str, tuple[tuple[int, str, tuple[str, ...]], ...]]
    has_ascii_entries: bool
    trie_root: dict[str, object]
    passthrough_by_char: dict[str, tuple[str, ...]]


@lru_cache(maxsize=32)
def _load_dictionary_impl(source: str) -> tuple[tuple[str, str], ...]:
    if not source:
        return ()
    path = Path(source).expanduser()
    if path.exists():
        text = path.read_text(encoding="utf-8")
        entries = _parse_dictionary_text(text, path.suffix.lower())
    else:
        entries = _parse_dictionary_text(source, ".json")
    return tuple(sorted(entries, key=lambda item: len(item[0]), reverse=True))


def load_dictionary(source: str) -> tuple[tuple[str, str], ...]:
    """Load dictionary entries from JSON text or a file path."""

    return _load_dictionary_impl(source)


@lru_cache(maxsize=16)
def _configured_dictionary_cached(
    inline: str,
    path: str,
    default_paths: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    for default_path in default_paths:
        entries.extend(load_dictionary(default_path))
    if inline:
        entries.extend(load_dictionary(inline))
    if path:
        entries.extend(load_dictionary(path))
    return tuple(sorted(_dedupe(entries), key=lambda item: len(item[0]), reverse=True))


def configured_dictionary() -> tuple[tuple[str, str], ...]:
    """Return entries from environment configuration."""

    inline = env("DICTIONARY")
    path = env("DICTIONARY_PATH")
    default_paths = _default_dictionary_paths_cached(str(Path.cwd()))
    return _configured_dictionary_cached(inline, path, default_paths)


@lru_cache(maxsize=32)
def _load_dictionary_candidates_impl(source: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not source:
        return ()
    path = Path(source).expanduser()
    if path.exists():
        text = path.read_text(encoding="utf-8")
        entries = _parse_dictionary_candidate_text(text, path.suffix.lower())
    else:
        entries = _parse_dictionary_candidate_text(source, ".json")
    return tuple(sorted(entries, key=lambda item: len(item[0]), reverse=True))


def load_dictionary_candidates(source: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Load dictionary entries preserving multiple candidates for each input."""

    return _load_dictionary_candidates_impl(source)


@lru_cache(maxsize=16)
def _configured_dictionary_candidates_cached(
    inline: str,
    path: str,
    default_paths: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    entries: list[tuple[str, tuple[str, ...]]] = []
    for default_path in default_paths:
        entries.extend(load_dictionary_candidates(default_path))
    if inline:
        entries.extend(load_dictionary_candidates(inline))
    if path:
        entries.extend(load_dictionary_candidates(path))
    return tuple(
        sorted(_dedupe_candidate_entries(entries), key=lambda item: len(item[0]), reverse=True)
    )


def configured_dictionary_candidates() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return entries from environment configuration with alternatives intact."""

    inline = env("DICTIONARY")
    path = env("DICTIONARY_PATH")
    default_paths = _default_dictionary_paths_cached(str(Path.cwd()))
    return _configured_dictionary_candidates_cached(inline, path, default_paths)


@lru_cache(maxsize=8)
def _default_dictionary_paths_cached(cwd_str: str) -> tuple[str, ...]:
    candidates = [
        Path(cwd_str) / "data",
        Path(__file__).resolve().parents[1] / "data",
    ]
    paths: list[str] = []
    seen: set[Path] = set()
    for directory in candidates:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.skk")):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(str(path))
    return tuple(paths)


def _default_dictionary_paths() -> list[Path]:
    return [Path(p) for p in _default_dictionary_paths_cached(str(Path.cwd()))]


def _clear_dictionary_caches() -> None:
    _load_dictionary_impl.cache_clear()
    _configured_dictionary_cached.cache_clear()
    _default_dictionary_paths_cached.cache_clear()
    _build_dictionary_index.cache_clear()


def _clear_dictionary_candidate_caches() -> None:
    _load_dictionary_candidates_impl.cache_clear()
    _configured_dictionary_candidates_cached.cache_clear()
    _default_dictionary_paths_cached.cache_clear()
    _build_candidate_dictionary_index.cache_clear()


load_dictionary.cache_clear = _clear_dictionary_caches  # type: ignore[attr-defined]
load_dictionary_candidates.cache_clear = _clear_dictionary_candidate_caches  # type: ignore[attr-defined]


def _ensure_entries_tuple(
    entries: Iterable[tuple[str, str]] | None,
) -> tuple[tuple[str, str], ...]:
    if entries is None:
        return configured_dictionary()
    if isinstance(entries, tuple):
        return entries
    return tuple(entries)


def _ensure_candidate_entries_tuple(
    entries: Iterable[tuple[str, tuple[str, ...]]] | None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if entries is None:
        return configured_dictionary_candidates()
    if isinstance(entries, tuple):
        return entries
    return tuple(entries)


def apply_dictionary(text: str, entries: Iterable[tuple[str, str]] | None = None) -> str:
    """Apply personal dictionary entries outside protected placeholders."""

    entries_tuple = _ensure_entries_tuple(entries)
    if not entries_tuple:
        return text
    index = _build_dictionary_index(entries_tuple)
    parts = PLACEHOLDER_SPLIT_RE.split(text)
    converted: list[str] = []
    for part in parts:
        if PLACEHOLDER_SPLIT_RE.fullmatch(part):
            converted.append(part)
        else:
            converted.append(_apply_index_to_plain_text(part, index))
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

    entries_tuple = _ensure_entries_tuple(entries)
    if not entries_tuple:
        return text, ()
    index = _build_dictionary_index(entries_tuple)

    parts = PLACEHOLDER_SPLIT_RE.split(text)
    converted: list[str] = []
    spans: list[tuple[str, str]] = []
    next_index = placeholder_start
    for part in parts:
        if PLACEHOLDER_SPLIT_RE.fullmatch(part):
            converted.append(part)
            continue
        converted_part, part_spans, next_index = _apply_index_as_placeholders_to_plain_text(
            part,
            index,
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

    entries_tuple = _ensure_candidate_entries_tuple(entries)
    if not entries_tuple:
        return [(text, ())]
    index = _build_candidate_dictionary_index(entries_tuple)
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
                for converted, part_spans, new_next_index in _plain_text_candidate_variants_indexed(
                    part,
                    index,
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


def _hyphen_sig(source: str) -> str:
    idx = source.find("-")
    if idx > 0 and idx + 1 < len(source):
        return source[idx - 1 : idx + 2]
    return "-"


@lru_cache(maxsize=64)
def _build_dictionary_index(entries: tuple[tuple[str, str], ...]) -> _DictionaryIndex:
    other_non_ascii: list[tuple[str, str]] = []
    hyphen_buckets: dict[str, list[tuple[int, str, str]]] = {}
    trie_root: dict[str, Any] = {}
    entry_keys: set[str] = set()
    has_ascii_entries = False

    for order_idx, (source, target) in enumerate(entries):
        if ASCII_RUN_RE.fullmatch(source):
            has_ascii_entries = True
            if source not in entry_keys:
                entry_keys.add(source)
                node = trie_root
                for ch in source:
                    child = node.get(ch)
                    if child is None:
                        child = {}
                        node[ch] = child
                    node = child
                node[""] = (source, target)
        elif "-" in source:
            sig = _hyphen_sig(source)
            hyphen_buckets.setdefault(sig, []).append((order_idx, source, target))
        else:
            other_non_ascii.append((source, target))

    passthrough_by_char: dict[str, list[str]] = {}
    for token in PASSTHROUGH_ROMAJI_TOKENS:
        if token not in entry_keys:
            passthrough_by_char.setdefault(token[0], []).append(token)

    return _DictionaryIndex(
        other_non_ascii=tuple(other_non_ascii),
        hyphen_by_sig={k: tuple(v) for k, v in hyphen_buckets.items()},
        has_ascii_entries=has_ascii_entries,
        trie_root=trie_root,
        passthrough_by_char={k: tuple(v) for k, v in passthrough_by_char.items()},
    )


@lru_cache(maxsize=64)
def _build_candidate_dictionary_index(
    entries: tuple[tuple[str, tuple[str, ...]], ...],
) -> _CandidateDictionaryIndex:
    other_non_ascii: list[tuple[str, tuple[str, ...]]] = []
    hyphen_buckets: dict[str, list[tuple[int, str, tuple[str, ...]]]] = {}
    trie_root: dict[str, Any] = {}
    entry_keys: set[str] = set()
    has_ascii_entries = False

    for order_idx, (source, targets) in enumerate(entries):
        if ASCII_RUN_RE.fullmatch(source):
            has_ascii_entries = True
            if source not in entry_keys:
                entry_keys.add(source)
                node = trie_root
                for ch in source:
                    child = node.get(ch)
                    if child is None:
                        child = {}
                        node[ch] = child
                    node = child
                node[""] = (source, targets)
        elif "-" in source:
            sig = _hyphen_sig(source)
            hyphen_buckets.setdefault(sig, []).append((order_idx, source, targets))
        else:
            other_non_ascii.append((source, targets))

    passthrough_by_char: dict[str, list[str]] = {}
    for token in PASSTHROUGH_ROMAJI_TOKENS:
        if token not in entry_keys:
            passthrough_by_char.setdefault(token[0], []).append(token)

    return _CandidateDictionaryIndex(
        other_non_ascii=tuple(other_non_ascii),
        hyphen_by_sig={k: tuple(v) for k, v in hyphen_buckets.items()},
        has_ascii_entries=has_ascii_entries,
        trie_root=trie_root,
        passthrough_by_char={k: tuple(v) for k, v in passthrough_by_char.items()},
    )


def _apply_non_ascii_from_index(text: str, index: _DictionaryIndex) -> str:
    result = text
    for source, target in index.other_non_ascii:
        if source in result:
            result = result.replace(source, target)
    if "-" in result and index.hyphen_by_sig:
        sigs: list[str] = []
        pos = result.find("-")
        while pos != -1:
            if pos > 0 and pos + 1 < len(result):
                sig = result[pos - 1 : pos + 2]
                if sig not in sigs:
                    sigs.append(sig)
            pos = result.find("-", pos + 1)
        if "-" in index.hyphen_by_sig:
            sigs.append("-")
        if len(sigs) == 1:
            for _ord, source, target in index.hyphen_by_sig.get(sigs[0], ()):
                if source in result:
                    result = result.replace(source, target)
        elif len(sigs) > 1:
            candidates: list[tuple[int, str, str]] = []
            for sig in sigs:
                candidates.extend(index.hyphen_by_sig.get(sig, ()))
            candidates.sort(key=lambda item: item[0])
            for _ord, source, target in candidates:
                if source in result:
                    result = result.replace(source, target)
    return result


def _apply_non_ascii_from_candidate_index(text: str, index: _CandidateDictionaryIndex) -> str:
    result = text
    for source, targets in index.other_non_ascii:
        if source in result:
            result = result.replace(source, targets[0])
    if "-" in result and index.hyphen_by_sig:
        sigs: list[str] = []
        pos = result.find("-")
        while pos != -1:
            if pos > 0 and pos + 1 < len(result):
                sig = result[pos - 1 : pos + 2]
                if sig not in sigs:
                    sigs.append(sig)
            pos = result.find("-", pos + 1)
        if "-" in index.hyphen_by_sig:
            sigs.append("-")
        if len(sigs) == 1:
            for _ord, source, targets in index.hyphen_by_sig.get(sigs[0], ()):
                if source in result:
                    result = result.replace(source, targets[0])
        elif len(sigs) > 1:
            candidates: list[tuple[int, str, tuple[str, ...]]] = []
            for sig in sigs:
                candidates.extend(index.hyphen_by_sig.get(sig, ()))
            candidates.sort(key=lambda item: item[0])
            for _ord, source, targets in candidates:
                if source in result:
                    result = result.replace(source, targets[0])
    return result


def _apply_index_to_plain_text(text: str, index: _DictionaryIndex) -> str:
    result = _apply_non_ascii_from_index(text, index)
    if index.has_ascii_entries:
        result = ASCII_RUN_RE.sub(
            lambda match: _replace_ascii_run_indexed(match.group(0), index),
            result,
        )
    return result


def _apply_index_as_placeholders_to_plain_text(
    text: str,
    index: _DictionaryIndex,
    placeholder_start: int,
) -> tuple[str, list[tuple[str, str]], int]:
    result = _apply_non_ascii_from_index(text, index)
    spans: list[tuple[str, str]] = []
    next_index = placeholder_start

    def replace(match: re.Match[str]) -> str:
        nonlocal next_index
        replaced, run_spans, next_index = _replace_ascii_run_with_placeholders_indexed(
            match.group(0),
            index,
            next_index,
        )
        spans.extend(run_spans)
        return replaced

    if index.has_ascii_entries:
        result = ASCII_RUN_RE.sub(replace, result)
    return result, spans, next_index


def _replace_ascii_run_indexed(text: str, index: _DictionaryIndex) -> str:
    tokens = _segment_ascii_run_indexed(text, index)
    if tokens is None:
        return text
    return "".join(target for _source, target, converted in tokens if converted or target)


def _replace_ascii_run_with_placeholders_indexed(
    text: str,
    index: _DictionaryIndex,
    placeholder_start: int,
) -> tuple[str, list[tuple[str, str]], int]:
    tokens = _segment_ascii_run_indexed(text, index)
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


def _plain_text_candidate_variants_indexed(
    text: str,
    index: _CandidateDictionaryIndex,
    placeholder_start: int,
    per_word_limit: int,
    max_candidates: int,
) -> list[tuple[str, list[tuple[str, str]], int]]:
    result = _apply_non_ascii_from_candidate_index(text, index)
    if not index.has_ascii_entries:
        return [(result, [], placeholder_start)]

    states: list[tuple[str, list[tuple[str, str]], int]] = [("", [], placeholder_start)]
    cursor = 0
    for match in ASCII_RUN_RE.finditer(result):
        literal = result[cursor : match.start()]
        if literal:
            states = [(prefix + literal, spans, next_index) for prefix, spans, next_index in states]
        next_states: list[tuple[str, list[tuple[str, str]], int]] = []
        for prefix, spans, next_index in states:
            for converted, run_spans, new_next_index in _ascii_run_candidate_variants_indexed(
                match.group(0),
                index,
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


def _ascii_run_candidate_variants_indexed(
    text: str,
    index: _CandidateDictionaryIndex,
    placeholder_start: int,
    per_word_limit: int,
    max_candidates: int,
) -> list[tuple[str, list[tuple[str, str]], int]]:
    tokens = _segment_ascii_run_candidates_indexed(text, index)
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


def _segment_ascii_run_candidates_indexed(
    text: str,
    index: _CandidateDictionaryIndex,
) -> tuple[tuple[str, tuple[str, ...], bool], ...] | None:
    """Return dictionary segmentation with candidate targets for TEXT."""

    trie_root = index.trie_root
    passthrough_by_char = index.passthrough_by_char
    text_len = len(text)

    best: dict[
        int,
        tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]] | None,
    ] = {text_len: (0, 0, ())}

    def solve(pos: int) -> tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]] | None:
        if pos in best:
            return best[pos]
        result: tuple[int, int, tuple[tuple[str, tuple[str, ...], bool], ...]] | None = None

        node: dict[str, Any] | None = trie_root
        matches: list[tuple[str, tuple[str, ...]]] = []
        for cursor in range(pos, text_len):
            node = node.get(text[cursor])
            if node is None:
                break
            hit = node.get("")
            if hit is not None:
                matches.append(hit)

        for source, targets in reversed(matches):
            tail = solve(pos + len(source))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars + len(source),
                segments + 1,
                ((source, targets, True),) + suffix,
            )
            result = _prefer_ascii_candidate_segmentation(result, candidate)

        for token in passthrough_by_char.get(text[pos], ()):
            if not text.startswith(token, pos):
                continue
            tail = solve(pos + len(token))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars,
                segments + 1,
                ((token, (token,), False),) + suffix,
            )
            result = _prefer_ascii_candidate_segmentation(result, candidate)

        best[pos] = result
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


def _segment_ascii_run_indexed(
    text: str,
    index: _DictionaryIndex,
) -> tuple[tuple[str, str, bool], ...] | None:
    """Return dictionary segmentation for TEXT, or nil when not fully consumed."""

    trie_root = index.trie_root
    passthrough_by_char = index.passthrough_by_char
    text_len = len(text)

    best: dict[int, tuple[int, int, tuple[tuple[str, str, bool], ...]] | None] = {
        text_len: (0, 0, ())
    }

    def solve(pos: int) -> tuple[int, int, tuple[tuple[str, str, bool], ...]] | None:
        if pos in best:
            return best[pos]
        result: tuple[int, int, tuple[tuple[str, str, bool], ...]] | None = None

        node: dict[str, Any] | None = trie_root
        matches: list[tuple[str, str]] = []
        for cursor in range(pos, text_len):
            node = node.get(text[cursor])
            if node is None:
                break
            hit = node.get("")
            if hit is not None:
                matches.append(hit)

        for source, target in reversed(matches):
            tail = solve(pos + len(source))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars + len(source),
                segments + 1,
                ((source, target, True),) + suffix,
            )
            result = _prefer_ascii_segmentation(result, candidate)

        for token in passthrough_by_char.get(text[pos], ()):
            if not text.startswith(token, pos):
                continue
            tail = solve(pos + len(token))
            if tail is None:
                continue
            converted_chars, segments, suffix = tail
            candidate = (
                converted_chars,
                segments + 1,
                ((token, token, False),) + suffix,
            )
            result = _prefer_ascii_segmentation(result, candidate)

        best[pos] = result
        return result

    solved = solve(0)
    if solved is None or solved[0] == 0:
        return None
    return solved[2]


def _segment_ascii_run(
    text: str,
    entries: Iterable[tuple[str, str]],
) -> tuple[tuple[str, str, bool], ...] | None:
    """Return dictionary segmentation for TEXT, or nil when not fully consumed."""

    return _segment_ascii_run_indexed(text, _build_dictionary_index(_ensure_entries_tuple(entries)))


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
