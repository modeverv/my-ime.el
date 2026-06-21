"""Small local HTTP server for my-ime."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from typing import Any

from .config import env
from .converter import CandidateResult, ConvertError, convert, convert_candidates, preedit


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class ImeHandler(BaseHTTPRequestHandler):
    server_version = "my-ime/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"ok": True, "service": "my-ime"})
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path not in {"/convert", "/preedit", "/candidates"}:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            request = self._read_json()
            text = request.get("text")
            if not isinstance(text, str):
                self._send_json({"error": "field 'text' must be a string"}, HTTPStatus.BAD_REQUEST)
                return
            metadata = request.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                self._send_json({"error": "field 'metadata' must be an object"}, HTTPStatus.BAD_REQUEST)
                return
            if self.path == "/preedit":
                result = preedit(text, metadata=metadata)
            elif self.path == "/candidates":
                result = convert_candidates(text, metadata=metadata)
            else:
                result = convert(text, metadata=metadata)
        except ConvertError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        payload = {
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
        self._send_json(payload)

    def log_message(self, format: str, *args: Any) -> None:
        if env("LOG_REQUESTS") == "1":
            super().log_message(format, *args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("request body is empty")
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("request body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ImeHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local my-ime server.")
    parser.add_argument("--host", default=env("HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(env("PORT", str(DEFAULT_PORT))))
    args = parser.parse_args()
    server = build_server(args.host, args.port)
    print(f"my-ime server listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
