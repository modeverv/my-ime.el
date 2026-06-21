# my-ime Architecture

## Shape

`my-ime` is a local conversion service with a thin Emacs client.

```text
Emacs command
  -> local HTTP server
  -> deterministic conversion pipeline
  -> converted text
  -> Emacs buffer replacement
```

The core decision is to keep conversion outside Emacs. Emacs provides editing ergonomics; the server provides reusable conversion behavior.

## Why External Server

An external server gives us one conversion engine for multiple clients:

- Emacs now.
- CLI later.
- Other editors later.
- Docker packaging later.

It also lets us use non-Elisp tools such as `libkkc` and Python libraries without making Emacs responsible for runtime dependencies.

## Primary Input Syntax

Manual terms are marked by the user:

```text
;;domain drive;;deyaru
```

The markers mean: preserve the enclosed text exactly.

This moves the hardest ambiguity out of the model:

```text
domain drive
```

does not need to be guessed as English, romanized Japanese, or a phrase boundary. The user already told the system.

## Pipeline

```text
raw input
  -> manual term protection
  -> automatic technical protection
  -> romaji to hiragana
  -> kana-kanji conversion with kkc
  -> placeholder restoration
  -> response
```

### Manual Term Protection

Input:

```text
;;domain drive;;deyaru
```

Protected:

```text
<TERM_0>deyaru
```

Restored:

```text
domain driveでやる
```

Manual terms are exact byte/text preservation boundaries. If restoration fails, conversion must fail rather than return damaged text.

### Automatic Technical Protection

The existing protection layer remains useful for unmarked technical spans:

- URLs
- file paths
- API paths
- keybindings
- Lisp forms
- hyphenated identifiers
- underscored identifiers
- likely command names

Manual markers are the preferred high-confidence mechanism. Automatic protection is a safety net.

### Romaji to Hiragana

Only unprotected spans are romanized.

The converter should tolerate compact input:

```text
deyaru
```

and spaced input:

```text
de yaru
```

The output of this phase is hiragana plus placeholders.

### kkc

`kkc decoder` is the first kana-kanji engine.

Observed useful behavior:

```text
でかいはつする -> で開発する
でほぞんする   -> で保存する
をじっこうする -> を実行する
```

`kkc decoder` also preserves placeholder-like tokens well:

```text
|||TERM_0|||でかいはつする -> |||TERM_0|||で開発する
```

The runtime should prefer a long-lived subprocess to avoid startup overhead.

## Emacs Client

The existing `emacs/my-ime.el` remains the main editor integration.

It already provides:

- region conversion
- last-sentence conversion
- paragraph conversion
- DWIM conversion
- async requests
- preview/accept/reject flow
- history
- org-aware safety checks

The Emacs side should not need to understand kkc. It sends text to `/convert` and replaces the buffer only after a successful response.

## Server API

### `GET /health`

Returns server health.

### `POST /convert`

Request:

```json
{
  "text": ";;domain drive;;deyaru",
  "metadata": {
    "mode": "org-mode",
    "syntax": "org"
  }
}
```

Response:

```json
{
  "text": "domain driveでやる"
}
```

On unsafe conversion, the server returns an error and the client must leave the buffer unchanged.

## Failure Policy

Fail closed.

Return an error when:

- manual term markers are unbalanced
- placeholders disappear
- placeholders are duplicated unexpectedly
- a restored term differs from its original
- kkc subprocess fails
- output contains unresolved internal placeholders

This is an editor tool. It is better to keep the original input than to silently damage text.

## Packaging

The default runtime is Docker Compose:

```text
small Docker container
  + server
  + libkkc
  + libkkc-data
```

Local development can still run the Python server directly when a local `kkc`
command and data package are available.
