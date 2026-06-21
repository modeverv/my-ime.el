from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request

from server.app import build_server
from server.dictionary import load_dictionary, load_dictionary_candidates


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["MY_IME_BACKEND"] = "dummy"
        cls.server = build_server("127.0.0.1", 0)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.pop("MY_IME_DICTIONARY", None)
        load_dictionary.cache_clear()
        load_dictionary_candidates.cache_clear()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_health(self) -> None:
        with urllib.request.urlopen(self.url + "/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])

    def test_convert(self) -> None:
        request = urllib.request.Request(
            self.url + "/convert",
            data=json.dumps({"text": "after-save-hookdeyobu"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["text"], "after-save-hookで呼ぶ")

    def test_preedit(self) -> None:
        request = urllib.request.Request(
            self.url + "/preedit",
            data=json.dumps({"text": "kyou ha"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["text"], "きょうは")
        self.assertEqual(payload["backend"], "preedit")

    def test_candidates(self) -> None:
        os.environ["MY_IME_DICTIONARY"] = (
            '{"kanji": ["漢字", "感じ"], "henkan": ["変換", "返還"], "dekiru": "できる"}'
        )
        load_dictionary.cache_clear()
        load_dictionary_candidates.cache_clear()
        request = urllib.request.Request(
            self.url + "/candidates",
            data=json.dumps({"text": "kanjihenkandekiru"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["text"], "漢字変換できる")
        self.assertIn("感じ返還できる", payload["candidates"])


if __name__ == "__main__":
    unittest.main()
