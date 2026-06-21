from __future__ import annotations

import os
from unittest import mock
import unittest

from server.converter import convert, kkc_convert, preedit
from server.kkc_client import convert_hiragana_candidates_with_kkc, kkc_available, parse_kkc_line


class KkcBackendTests(unittest.TestCase):
    def test_parses_kkc_decoder_line(self) -> None:
        line = ">> 0: <|||TECH_0|||/|||TECH_0|||><で/で><開発/かいはつ><する/する>"
        self.assertEqual(parse_kkc_line(line), "|||TECH_0|||で開発する")

    def test_parses_nonzero_candidate_line(self) -> None:
        line = "2: <|||TECH_0|||/|||TECH_0|||><が/が><良/よ><い/い><感じ/かんじ>"
        self.assertEqual(parse_kkc_line(line), "|||TECH_0|||が良い感じ")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_kkc_convert_preserves_placeholder(self) -> None:
        self.assertEqual(kkc_convert("<TECH_0>deyaru"), "<TECH_0>でやる")
        self.assertEqual(kkc_convert("<TECH_0>dekaihatusuru"), "<TECH_0>で開発する")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_convert_manual_term_markers(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc"}, clear=False):
            result = convert(";;domain drive;;deyaru")
        self.assertEqual(result.text, "domain driveでやる")
        self.assertEqual(result.backend, "kkc")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_convert_manual_term_only_confirms_text_without_kkc(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc"}, clear=False):
            result = convert(";;this is a pen;;")
        self.assertEqual(result.text, "this is a pen")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_manual_term_only_drops_leading_indent(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc"}, clear=False):
            result = convert("  ;;data is dead;;")
        self.assertEqual(result.text, "data is dead")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_convert_manual_terms_in_technical_sentence(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc"}, clear=False):
            result = convert(";;org-roam-db-sync;;wo;;after-save-hook;;deyobunohaomoi")
        self.assertEqual(result.text, "org-roam-db-syncをafter-save-hookで呼ぶのは重い")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_kkc_candidates_returns_nbest(self) -> None:
        candidates = convert_hiragana_candidates_with_kkc("<TECH_0>がよいかんじにいける", nbest=3)
        self.assertGreaterEqual(len(candidates), 3)
        self.assertIn("<TECH_0>が良い感じにいける", candidates)

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_convert_manual_term_with_candidate_rerank(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"}, clear=False):
            result = convert(";;global state;;gayoikannjiniikeru")
        self.assertEqual(result.text, "global stateが良い感じにいける")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_convert_terminal_ascii_period_to_japanese_period(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"}, clear=False):
            result = convert(";;global state;;gayoikannjiniikeru.")
        self.assertEqual(result.text, "global stateが良い感じにいける。")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_convert_terminal_ascii_punctuation_before_trailing_space(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"}, clear=False):
            period = convert(";;global state;;gayoikannjiniikeru. ")
            comma = convert(";;global state;;gayoikannjiniikeru, ")
        self.assertEqual(period.text, "global stateが良い感じにいける。 ")
        self.assertEqual(comma.text, "global stateが良い感じにいける、 ")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_convert_plain_romaji_sentence_after_removing_english_skip(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"}, clear=False):
            result = convert("kyou ha akarui.")
        self.assertEqual(result.text, "今日は明るい。")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_dictionary_output_is_not_reconverted_by_kkc(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"}, clear=False):
            result = convert("kyou ha totemo tanosii.")
        self.assertEqual(result.text, "今日はとても楽しい。")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_hyphenated_romaji_data_uses_dictionary(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"}, clear=False):
            result = convert("de-tawo yomu.")
            preview = preedit("de-tawo yomu")
        self.assertEqual(result.text, "データを読む。")
        self.assertEqual(preview.text, "データをよむ")

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_preedit_then_convert_flow(self) -> None:
        with mock.patch.dict(os.environ, {"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"}, clear=False):
            first = preedit("kyou ha totemo tanosii")
            committed = convert(first.text + ".")
        self.assertEqual(first.text, "きょうはとてもたのしい")
        self.assertEqual(committed.text, "今日はとても楽しい。")


if __name__ == "__main__":
    unittest.main()
