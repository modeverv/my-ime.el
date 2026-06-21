from __future__ import annotations

import os
import unittest

from server.converter import (
    _drops_technical_terms,
    _unsafe_model_drift,
    convert,
    convert_candidates,
    dummy_convert,
)
from server.dictionary import load_dictionary, load_dictionary_candidates


class ConverterTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["MY_IME_BACKEND"] = "dummy"

    def tearDown(self) -> None:
        os.environ.pop("MY_IME_DICTIONARY", None)
        os.environ.pop("MY_IME_DICTIONARY_PATH", None)
        os.environ.pop("LLM_IME_DICTIONARY", None)
        os.environ.pop("LLM_IME_DICTIONARY_PATH", None)
        load_dictionary.cache_clear()
        load_dictionary_candidates.cache_clear()

    def test_dummy_keeps_placeholders(self) -> None:
        self.assertEqual(dummy_convert("<TECH_0>wo<TECH_1>deyobu"), "<TECH_0>を<TECH_1>で呼ぶ")

    def test_dummy_preserves_space_between_protected_tokens(self) -> None:
        self.assertEqual(dummy_convert("<TECH_0> <TECH_1> wo tataku"), "<TECH_0> <TECH_1>を叩く")
        self.assertEqual(dummy_convert("<TECH_0> status wo kakunin suru"), "<TECH_0> statusを確認する")
        self.assertEqual(dummy_convert("url wo mamoru"), "URLを守る")
        self.assertEqual(dummy_convert("placeholder ga nakunattara error ni suru"), "placeholderがなくなったらerrorにする")

    def test_dummy_does_not_convert_inside_technical_english_words(self) -> None:
        self.assertEqual(dummy_convert("API response keishiki wa domain ni mochikomanai"), "API response形式はdomainに持ち込まない")
        self.assertEqual(dummy_convert("Repository wo Entity kara yobanai hou ga ii"), "RepositoryをEntityから呼ばない方がいい")
        self.assertEqual(dummy_convert("technical term wo nihongo ni yakushi sugita toki wa fallback suru"), "technical termを日本語に訳しすぎた時はfallbackする")
        self.assertEqual(dummy_convert("chat completion response ga reasoning only nara error ni suru"), "chat completion responseがreasoning onlyならerrorにする")
        self.assertEqual(dummy_convert("ApplicationService de transaction boundary wo motsu"), "ApplicationServiceでtransaction boundaryを持つ")
        self.assertEqual(dummy_convert("endpoint de smoke suru"), "endpointでsmokeする")
        self.assertEqual(dummy_convert("response format wo JSON schema ni suru"), "response formatをJSON schemaにする")
        self.assertEqual(dummy_convert("short sentence nara 0.5b model de tariru kamo"), "short sentenceなら0.5B modelで足りるかも")
        self.assertEqual(dummy_convert("history ni original to converted wo nokosu"), "historyにoriginalとconvertedを残す")
        self.assertEqual(dummy_convert("strict prompt de explanation wo kinshi suru"), "strict promptでexplanationを禁止する")

    def test_dummy_normalizes_common_technical_phrases(self) -> None:
        self.assertEqual(dummy_convert("no extra text rate wo metrics ni ireru"), "no-extra-text rateをmetricsに入れる")
        self.assertEqual(dummy_convert("train valid test ni repeatable ni split suru"), "train/valid/testにrepeatableにsplitする")
        self.assertEqual(dummy_convert("full ime wa command based workflow no ato"), "full IMEはcommand-based workflowの後")
        self.assertEqual(dummy_convert("paths urls commands keybindings wo preserve suru"), "paths/URLs/commands/keybindingsをpreserveする")
        self.assertEqual(dummy_convert("MY_IME_BACKEND dummy de offline ni ugoku"), "MY_IME_BACKEND=dummyでofflineに動く")
        self.assertEqual(dummy_convert("my-ime-history ni before after wo nokosu"), "my-ime-historyにbefore/afterを残す")

    def test_detects_dropped_technical_terms(self) -> None:
        self.assertTrue(
            _drops_technical_terms(
                "full ime wa command based workflow no ato",
                "フルイメはコマンドベースのワークフローで動作します",
            )
        )
        self.assertFalse(
            _drops_technical_terms(
                "full ime wa command based workflow no ato",
                "full IMEはcommand based workflowの後",
            )
        )
        self.assertTrue(_drops_technical_terms("meaning wo tsuika shinai", "意味を追加しない"))
        self.assertTrue(_drops_technical_terms("26b class wa teacher ni dake tsukau", "26bクラスは教師にだけ使う"))
        self.assertTrue(_drops_technical_terms("MY_IME_KKC_COMMAND wo env de kaeru", "MY_IME_KKC_COMMANDを環境で変える"))
        self.assertTrue(
            _drops_technical_terms(
                "technical term wo nihongo ni yakushi sugita toki wa fallback suru",
                "技術用語を日本語に訳しすぎた時はフォールバックする",
            )
        )
        self.assertTrue(_drops_technical_terms("chunk ga nagasugiru toki wa max chars de kiru", "チャンクが長すぎる時は最大文字数で切る"))
        self.assertTrue(_drops_technical_terms("inputs fragment ga mazattara training record ni shinai", "入力断片が混ざったら学習記録にしない"))

    def test_detects_unsafe_model_drift(self) -> None:
        self.assertTrue(
            _unsafe_model_drift(
                "response format wo json ni suru",
                "response formatをJSONに変す",
            )
        )
        self.assertTrue(
            _unsafe_model_drift(
                "async result wa source text ga kawattara discard suru",
                "async result は source text が わってる か か か か か か か か",
            )
        )
        self.assertFalse(
            _unsafe_model_drift(
                "ApplicationService de transaction boundary wo motsu",
                "ApplicationServiceでtransaction boundaryを持つ",
            )
        )

    def test_convert_restores_protected_tokens(self) -> None:
        result = convert("org-roam-db-syncwoafter-save-hookdeyobunohaomoi")
        self.assertEqual(result.text, "org-roam-db-syncをafter-save-hookで呼ぶのは重い")
        self.assertEqual(result.backend, "dummy")

    def test_convert_plan_example_baseline(self) -> None:
        result = convert("gemmaderoomajikashitarakyoushidataninarunodeha")
        self.assertEqual(result.text, "Gemmaでローマ字化したら教師データになるのでは")

    def test_convert_prototype_success_example(self) -> None:
        result = convert(
            "targetwoemacsnigenteisurunaraeijinihongokankeinakutoriaezualphabetnyuuryokushita "
            "monowollmdeeigonihongomajirinooutputnikirikaerukotohakanou"
        )
        self.assertEqual(
            result.text,
            "ターゲットをEmacsに限定するなら、英字・日本語関係なく、とりあえずalphabet入力した"
            "ものをLLMで英語日本語混じりのoutputに切り替えることは可能。",
        )

    def test_convert_candidates_expands_dictionary_cartesian_product(self) -> None:
        os.environ["MY_IME_DICTIONARY"] = (
            '{"kanji": ["漢字", "感じ"], "henkan": ["変換", "返還"], "dekiru": "できる"}'
        )
        result = convert_candidates("kanjihenkandekiru")
        self.assertEqual(
            result.candidates,
            (
                "漢字変換できる",
                "漢字返還できる",
                "感じ変換できる",
                "感じ返還できる",
            ),
        )


if __name__ == "__main__":
    unittest.main()
