from __future__ import annotations

import unittest

from server.romanizer import normalize_romaji, romaji_to_hiragana


class RomanizerTests(unittest.TestCase):
    def test_converts_compact_romaji(self) -> None:
        self.assertEqual(romaji_to_hiragana("dekaihatusuru"), "でかいはつする")
        self.assertEqual(romaji_to_hiragana("wojikkou suru"), "をじっこうする")
        self.assertEqual(romaji_to_hiragana("deyobunohaomoi"), "でよぶのはおもい")
        self.assertEqual(romaji_to_hiragana("yoi"), "よい")
        self.assertEqual(romaji_to_hiragana("famiri-"), "ふぁみりー")

    def test_preserves_placeholders_and_removes_input_spaces(self) -> None:
        self.assertEqual(romaji_to_hiragana("<TECH_0> de yaru"), "<TECH_0>でやる")

    def test_normalizes_double_n_before_consonants(self) -> None:
        self.assertEqual(normalize_romaji("kannjiniikeru"), "kanjiniikeru")
        self.assertEqual(romaji_to_hiragana("kannjiniikeru"), "かんじにいける")
        self.assertEqual(romaji_to_hiragana("konnichi"), "こんにち")


if __name__ == "__main__":
    unittest.main()
