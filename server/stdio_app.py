"""JSON-lines stdio worker for my-ime."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .converter import CandidateResult, ConvertError, convert, convert_candidates, preedit


def _result_payload(result: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": result.text,
        "protected_text": result.protected_text,
        "protected": [
            {
                "placeholder": span.placeholder,
                "original": span.original,
                "kind": span.kind,
            }
            for span in result.protected_spans
        ],
        "backend": result.backend,
        "elapsed_ms": result.elapsed_ms,
    }
    if isinstance(result, CandidateResult):
        payload["candidates"] = list(result.candidates)
    return payload


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Handle one stdio protocol request and return a JSON payload."""

    method = request.get("method", "convert")
    if method == "health":
        return {"ok": True, "service": "my-ime", "transport": "stdio"}

    text = request.get("text")
    if not isinstance(text, str):
        raise ValueError("field 'text' must be a string")

    metadata = request.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("field 'metadata' must be an object")

    if method == "preedit":
        return _result_payload(preedit(text, metadata=metadata))
    if method == "candidates":
        return _result_payload(convert_candidates(text, metadata=metadata))
    if method == "convert":
        return _result_payload(convert(text, metadata=metadata))
    raise ValueError(f"unsupported method: {method}")


def _read_request(line: str) -> dict[str, Any]:
    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("request line is not valid JSON") from exc
    if not isinstance(request, dict):
        raise ValueError("request line must be a JSON object")
    return request


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local my-ime stdio worker.")
    parser.parse_args()

    for line in sys.stdin:
        if not line.strip():
            continue
        request_id: Any = None
        try:
            request = _read_request(line)
            request_id = request.get("id")
            response = handle_request(request)
        except (ConvertError, ValueError) as exc:
            response = {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - last-resort worker isolation
            response = {"error": f"internal error: {exc}"}
        if request_id is not None:
            response["id"] = request_id
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
