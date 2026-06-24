#!/usr/bin/env python3
"""Extract personal dictionary term candidates from local Markdown notes.

This script intentionally does not assign readings. It only ranks vocabulary
found in Markdown. The SKK romaji keys should be curated separately.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from pathlib import Path
import re
import sys
import unicodedata


DEFAULT_SOURCE = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "iCloud~md~obsidian"
    / "Documents"
    / "seijiro"
    / "000_org"
    / "ai"
)
DEFAULT_OUTPUT = Path(".deps") / "me-term-candidates.tsv"

JAPANESE_RE = re.compile(r"[ぁ-んァ-ヴー一-龯々〆ヵヶ]")
KANJI_OR_KATAKANA_RE = re.compile(r"[ァ-ヴー一-龯々〆ヵヶ]")
ASCII_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[A-Za-z][A-Za-z0-9]*(?:[.+#/_-][A-Za-z0-9]+)*"
    r"(?![A-Za-z0-9_])"
)
SKK_TARGET_RE = re.compile(r"/([^/;]+)(?:;[^/]*)?/")

FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*", re.DOTALL)
FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
HTML_BLOCK_RE = re.compile(r"(?is)<(script|style|svg)\b.*?</\1>")
URL_RE = re.compile(r"https?://\S+|id:[0-9A-Za-z:/._?=&%-]+")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
HTML_TAG_RE = re.compile(r"<[^>\n]{1,200}>")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
ROLE_LINE_RE = re.compile(r"(?im)^#{1,6}\s*(user|assistant|chatgpt|system)\b.*$")
EXPORT_LINE_RE = re.compile(r"(?im)^exported on .*$|^[-*]\s*with savemychatbot.*$")

PARTICLES = ("を", "で", "に", "の", "が", "は")

JP_STOPWORDS = {
    "これ",
    "それ",
    "あれ",
    "ここ",
    "そこ",
    "ため",
    "こと",
    "もの",
    "よう",
    "そう",
    "ところ",
    "わけ",
    "感じ",
    "自分",
    "場合",
    "必要",
    "問題",
    "意味",
    "可能",
    "可能性",
    "重要",
    "以下",
    "以上",
    "今回",
    "現在",
    "最初",
    "最後",
    "全部",
    "一部",
    "全体",
    "基本",
    "理由",
    "方法",
    "内容",
    "状態",
    "関係",
    "部分",
    "方向",
    "対象",
    "結果",
    "結論",
    "前提",
    "説明",
    "理解",
    "確認",
    "処理",
}

ASCII_STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "assistant",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "chatgpt",
    "clippings",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "exported",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "http",
    "https",
    "human",
    "i",
    "id",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "me",
    "more",
    "most",
    "my",
    "new",
    "nil",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "public",
    "return",
    "same",
    "savemychatbot",
    "she",
    "should",
    "so",
    "some",
    "source",
    "such",
    "tags",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "title",
    "to",
    "too",
    "under",
    "until",
    "up",
    "user",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}

ASCII_ALLOWLIST = {
    "agent",
    "agi",
    "ai",
    "api",
    "backend",
    "cache",
    "cli",
    "client",
    "context",
    "dataset",
    "debug",
    "docker",
    "embedding",
    "emacs",
    "frontend",
    "github",
    "gpu",
    "json",
    "kernel",
    "latency",
    "llm",
    "markdown",
    "memory",
    "model",
    "obsidian",
    "prompt",
    "python",
    "runtime",
    "server",
    "token",
    "tool",
    "typescript",
    "ui",
    "vector",
    "workflow",
}


@dataclass(frozen=True)
class Term:
    kind: str
    text: str
    count: int
    score: float


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract vocabulary candidates from local Markdown notes.",
    )
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--max-terms", type=int, default=2500)
    parser.add_argument("--min-japanese-freq", type=int, default=3)
    parser.add_argument("--min-ascii-freq", type=int, default=4)
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--progress-every", type=int, default=500)
    args = parser.parse_args()

    fugashi = _load_fugashi()
    source = args.source.expanduser()
    if not source.exists():
        print(f"source directory does not exist: {source}", file=sys.stderr)
        return 2

    existing_targets = set()
    if not args.include_existing:
        existing_targets = read_existing_targets(args.data_dir)

    tagger = fugashi.Tagger()
    jp_counts: Counter[str] = Counter()
    ascii_counts: dict[str, Counter[str]] = defaultdict(Counter)
    files = sorted(source.rglob("*.md"))

    for index, path in enumerate(files, start=1):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"skip unreadable file: {path}: {exc}", file=sys.stderr)
            continue

        cleaned = clean_markdown(text)
        extract_japanese_terms(cleaned, tagger, jp_counts)
        extract_ascii_terms(cleaned, ascii_counts)

        if args.progress_every and index % args.progress_every == 0:
            print(f"processed {index}/{len(files)} markdown files", file=sys.stderr)

    terms = rank_terms(
        jp_counts=jp_counts,
        ascii_counts=ascii_counts,
        existing_targets=existing_targets,
        min_japanese_freq=args.min_japanese_freq,
        min_ascii_freq=args.min_ascii_freq,
    )[: args.max_terms]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_terms(terms), encoding="utf-8")
    print(
        f"wrote {args.output} with {len(terms)} candidates from {len(files)} markdown files",
        file=sys.stderr,
    )
    return 0


def _load_fugashi():
    try:
        import fugashi  # type: ignore[import-not-found]
    except ImportError as exc:
        print(
            "missing dependency. Install with: python3 -m pip install fugashi unidic-lite",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    return fugashi


def clean_markdown(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = FRONTMATTER_RE.sub(" ", text)
    text = HTML_BLOCK_RE.sub(" ", text)
    text = FENCED_CODE_RE.sub(" ", text)
    text = ROLE_LINE_RE.sub(" ", text)
    text = EXPORT_LINE_RE.sub(" ", text)
    text = WIKI_LINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    text = MD_LINK_RE.sub(lambda m: m.group(1), text)
    text = URL_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", " ", text)
    text = re.sub(r"(?m)^#{1,6}\s*", " ", text)
    return text


def extract_japanese_terms(text: str, tagger, counts: Counter[str]) -> None:
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        if len(buffer) > 1:
            add_japanese_count("".join(buffer), counts, compound=True)
        for surface in buffer:
            add_japanese_count(surface, counts, compound=False)
        buffer.clear()

    for word in tagger(text):
        surface = word.surface.strip()
        if is_japanese_noun(surface, word.feature):
            buffer.append(surface)
            if len(buffer) >= 8:
                flush()
            continue
        flush()
    flush()


def is_japanese_noun(surface: str, feature) -> bool:
    if not surface or surface.isascii():
        return False
    if not KANJI_OR_KATAKANA_RE.search(surface):
        return False
    pos1 = getattr(feature, "pos1", "")
    pos2 = getattr(feature, "pos2", "")
    pos3 = getattr(feature, "pos3", "")
    if pos1 != "名詞":
        return False
    if pos2 == "数詞":
        return False
    if pos3 == "助数詞可能" and len(surface) <= 1:
        return False
    if re.fullmatch(r"[0-9０-９]+", surface):
        return False
    return True


def add_japanese_count(term: str, counts: Counter[str], *, compound: bool) -> None:
    term = clean_target(term)
    if not term or term in JP_STOPWORDS:
        return
    if len(term) < 2 or len(term) > 28:
        return
    if not KANJI_OR_KATAKANA_RE.search(term):
        return
    if not compound and len(term) == 2 and re.fullmatch(r"[一-龯々〆ヵヶ]{2}", term):
        pass
    counts[term] += 1


def extract_ascii_terms(text: str, counts: dict[str, Counter[str]]) -> None:
    for match in ASCII_TERM_RE.finditer(text):
        raw = match.group(0).strip(".,:;!?()[]{}<>\"'")
        if not raw or len(raw) > 50:
            continue
        key = ascii_key(raw)
        if not key:
            continue
        lower = key.lower()
        if lower in ASCII_STOPWORDS:
            continue
        if len(lower) < 2 or len(lower) > 40:
            continue
        if raw.islower() and len(raw) < 4 and lower not in ASCII_ALLOWLIST:
            continue
        counts[lower][clean_target(raw)] += 1


def rank_terms(
    *,
    jp_counts: Counter[str],
    ascii_counts: dict[str, Counter[str]],
    existing_targets: set[str],
    min_japanese_freq: int,
    min_ascii_freq: int,
) -> list[Term]:
    terms: list[Term] = []
    for term, count in jp_counts.items():
        if term in existing_targets:
            continue
        if count < min_japanese_freq and len(term) < 4:
            continue
        if count < max(1, min_japanese_freq - 1) and len(term) < 6:
            continue
        terms.append(Term("jp", term, count, score_term(term, count, "jp")))

    for key, variants in ascii_counts.items():
        count = sum(variants.values())
        target, target_count = choose_ascii_target(variants)
        if target in existing_targets:
            continue
        if not keep_ascii_term(key, target, count, min_ascii_freq):
            continue
        terms.append(Term("ascii", target, target_count, score_term(target, count, "ascii")))

    return sorted(terms, key=lambda item: (item.score, item.count, len(item.text)), reverse=True)


def score_term(term: str, count: int, kind: str) -> float:
    length_bonus = min(len(term), 18) / 6.0
    kind_bonus = 2.0 if kind == "ascii" else 1.0
    return count * (1.0 + math.log1p(length_bonus)) + kind_bonus


def choose_ascii_target(variants: Counter[str]) -> tuple[str, int]:
    def rank(item: tuple[str, int]) -> tuple[int, int, int, str]:
        target, count = item
        has_signal_case = int(any(c.isupper() for c in target[1:]) or target.isupper())
        has_symbol = int(bool(re.search(r"[.+#/_-]", target)))
        return count, has_signal_case, has_symbol, target

    return max(variants.items(), key=rank)


def keep_ascii_term(key: str, target: str, count: int, min_freq: int) -> bool:
    lower = key.lower()
    if lower in ASCII_STOPWORDS:
        return False
    has_signal = (
        any(c.isupper() for c in target)
        or any(c.isdigit() for c in target)
        or bool(re.search(r"[.+#/_-]", target))
        or lower in ASCII_ALLOWLIST
    )
    if has_signal and count >= max(2, min_freq - 1):
        return True
    return count >= min_freq and len(lower) >= 4


def render_terms(terms: list[Term]) -> str:
    lines = ["kind\tcount\tscore\tterm"]
    for term in terms:
        lines.append(f"{term.kind}\t{term.count}\t{term.score:.3f}\t{term.text}")
    return "\n".join(lines) + "\n"


def read_existing_targets(data_dir: Path) -> set[str]:
    targets: set[str] = set()
    if not data_dir.exists():
        return targets
    for path in sorted(data_dir.glob("*.skk")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if not line or line.startswith(";"):
                continue
            for match in SKK_TARGET_RE.finditer(line):
                target = match.group(1)
                targets.add(target)
                for particle in PARTICLES:
                    if target.endswith(particle):
                        targets.add(target[: -len(particle)])
    return targets


def ascii_key(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("C++", "cplusplus").replace("c++", "cplusplus")
    text = text.replace("C#", "csharp").replace("c#", "csharp")
    text = re.sub(r"^\.net$", "dotnet", text, flags=re.IGNORECASE)
    text = text.replace("+", "plus").replace("#", "sharp").replace("&", "and")
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9_]", "", text)
    return text


def clean_target(target: str) -> str:
    target = unicodedata.normalize("NFKC", target)
    target = target.strip()
    target = target.replace("/", "／").replace(";", "；")
    target = re.sub(r"\s+", " ", target)
    return target


if __name__ == "__main__":
    raise SystemExit(main())
