from __future__ import annotations

import os
from unittest import TestCase, mock

from server.stdio_app import handle_request


class StdioAppTests(TestCase):
    def test_health_request(self) -> None:
        self.assertEqual(
            handle_request({"method": "health"}),
            {"ok": True, "service": "my-ime", "transport": "stdio"},
        )

    def test_convert_request_returns_payload(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "dummy"}, clear=False):
            payload = handle_request(
                {
                    "method": "convert",
                    "text": "serverwo",
                    "metadata": {"source": "test"},
                }
            )
        self.assertEqual(payload["text"], "サーバーを")
        self.assertEqual(payload["backend"], "dummy")

    def test_rejects_unknown_method(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported method"):
            handle_request({"method": "missing", "text": "x"})
