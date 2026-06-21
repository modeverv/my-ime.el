# my-ime Plan

## Goal

Build a local text conversion service that turns romanized Japanese mixed with manually marked technical terms into Japanese-English technical prose.

The first useful target is not a full realtime IME. It is a fast, predictable command-based converter that can be called from Emacs and later from other editors or tools.

Example:

```text
;;domain drive;;deyaru
```

becomes:

```text
domain driveでやる
```

## Current Direction

Use an external local HTTP server as the conversion engine.

Emacs remains a thin client:

```text
region / sentence / paragraph
  -> POST /convert
  -> replace buffer only on success
```

The server owns the conversion logic:

```text
manual term marks
  -> placeholders
  -> romaji to hiragana
  -> kkc kana-kanji conversion
  -> placeholder restore
```

This keeps the conversion core reusable outside Emacs. Docker Compose is the default fixed runtime for the server and kkc dependencies.

## Input Contract

Manual technical terms are written with double semicolon markers:

```text
;;domain drive;;deyaru
;;org-roam-db-sync;;wo;;after-save-hook;;deyobunohaomoi
```

Rules:

- Text inside `;;...;;` is preserved exactly.
- Marked terms may contain spaces.
- Marked terms are restored without the surrounding markers.
- Unmarked text is treated as romanized Japanese candidate text.
- Existing automatic protection for URLs, paths, keybindings, identifiers, and Lisp forms remains useful as a safety net.

## Milestone 1: kkc Server Path

Goal: make the practical non-LLM path work end to end.

Tasks:

- Add manual `;;...;;` term protection.
- Add romaji-to-hiragana conversion for the unprotected spans.
- Add a `kkc decoder` client.
- Use a long-lived `kkc decoder` subprocess when possible.
- Parse `kkc` segment output into plain converted text.
- Restore placeholders exactly.
- Keep `/convert` compatible with the existing Emacs client.
- Add tests for manual terms, spaces, identifiers, URLs, and failure cases.

Acceptance:

- `;;domain drive;;deyaru` converts to `domain driveでやる`.
- `;;TERM;;de開発する`-style mixed input does not damage the term.
- Server errors do not modify the Emacs buffer.
- Short conversions feel instant.

## Milestone 2: Emacs Reuse

Goal: keep the existing Emacs UX and point it at the new backend.

Tasks:

- Keep `emacs/my-ime.el` as the primary client.
- Keep region, last-sentence, paragraph, DWIM, async, preview, and history commands.
- Update docs and examples to use `;;...;;`.
- Ensure undo returns to the original romanized input.
- Keep org safety guards.

Acceptance:

- Existing keybindings still work.
- User can type marked romanized text in org-mode and convert it with one command.
- Preview and async flows still discard stale responses safely.

## Milestone 3: Quality Layer

Goal: improve the deterministic output without making the runtime fragile.

Tasks:

- Add optional dictionary replacements before or after kkc.
- Keep common particles and verbs deterministic where safe.
- Add narrow postprocessing rules only when they are easy to test.
- Keep candidate reranking deterministic.

Acceptance:

- The non-LLM path remains useful by itself.
- Protected terms are still restored exactly.

## Milestone 4: Evaluation

Goal: evaluate the new architecture instead of the old SFT-first plan.

Tasks:

- Refresh `data/eval.jsonl` with `;;...;;` manual-term examples.
- Add kkc-specific benchmark cases.
- Measure exact manual-term preservation.
- Measure kana-kanji quality on common technical prose.
- Measure latency through `/convert`.

Acceptance:

- Evaluation exposes term damage, romanized residue, and bad kanji choices.
- The server can pass a small practical smoke set before any model work.

## Later

Potential later work:

- Add a CLI client.
- Add editor integrations beyond Emacs.
- Add a personal term dictionary learned from local org/md/code files.
- Revisit small-model fine-tuning only after the kkc-based baseline is clearly understood.

## Archived Plan

The previous LLM/SFT-heavy plan is archived at:

```text
old/PLAN.md
```
