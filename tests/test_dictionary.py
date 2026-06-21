from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from server.dictionary import apply_dictionary, apply_dictionary_with_placeholders, load_dictionary
from server.converter import convert


class DictionaryTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("MY_IME_DICTIONARY", None)
        os.environ.pop("MY_IME_DICTIONARY_PATH", None)
        os.environ.pop("LLM_IME_DICTIONARY", None)
        os.environ.pop("LLM_IME_DICTIONARY_PATH", None)
        load_dictionary.cache_clear()

    def test_inline_json_dictionary(self) -> None:
        entries = load_dictionary('{"gemmade": "Gemmaで", "henkan": "変換"}')
        self.assertEqual(apply_dictionary("gemmadehenkan", entries), "Gemmaで変換")

    def test_tsv_dictionary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dict.tsv"
            path.write_text("nyuuryoku\t入力\n", encoding="utf-8")
            entries = load_dictionary(str(path))
        self.assertEqual(entries, (("nyuuryoku", "入力"),))

    def test_skk_dictionary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dict.skk"
            path.write_text("serverwo /サーバーを/\ncache /キャッシュ/\n", encoding="utf-8")
            entries = load_dictionary(str(path))
        self.assertIn(("serverwo", "サーバーを"), entries)
        self.assertIn(("cache", "キャッシュ"), entries)

    def test_dictionary_does_not_replace_inside_ascii_words(self) -> None:
        entries = (("kyou", "今日"), ("serverwo", "サーバーを"))
        self.assertEqual(apply_dictionary("kyoushi data", entries), "kyoushi data")
        self.assertEqual(apply_dictionary("serverwo cache", entries), "サーバーを cache")

    def test_dictionary_does_not_modify_placeholders(self) -> None:
        entries = (("<TECH_0>", "壊れた"), ("yobu", "呼ぶ"))
        self.assertEqual(apply_dictionary("<TECH_0>woyobu", entries), "<TECH_0>wo呼ぶ")

    def test_dictionary_can_emit_transient_placeholders(self) -> None:
        entries = (("serverwo", "サーバーを"), ("cachede", "キャッシュで"))
        text, spans = apply_dictionary_with_placeholders("serverwo cachede tukau", entries)
        self.assertEqual(text, "<TECH_0> <TECH_1> tukau")
        self.assertEqual(spans, (("<TECH_0>", "サーバーを"), ("<TECH_1>", "キャッシュで")))

    def test_converter_uses_configured_dictionary(self) -> None:
        os.environ["MY_IME_BACKEND"] = "dummy"
        os.environ["MY_IME_DICTIONARY"] = '{"watashinokonoheniha": "私のこの辺には"}'
        result = convert("watashinokonoheniha")
        self.assertEqual(result.text, "私のこの辺には")


if __name__ == "__main__":
    unittest.main()
