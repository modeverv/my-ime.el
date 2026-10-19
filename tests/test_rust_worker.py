from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import unittest

from server.kkc_client import kkc_available


RUST_BIN = Path(__file__).resolve().parents[1] / "target" / "release" / "my-ime-stdio"


@unittest.skipUnless(RUST_BIN.exists(), "Rust binary target/release/my-ime-stdio is not built")
class RustWorkerTests(unittest.TestCase):
    def _run_requests(
        self,
        requests: list[dict[str, object]],
        extra_env: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        input_data = "".join(json.dumps(req, ensure_ascii=False) + "\n" for req in requests)
        proc = subprocess.run(
            [str(RUST_BIN)],
            input=input_data,
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    def test_health_and_protocol(self) -> None:
        responses = self._run_requests(
            [
                {"id": 1, "method": "health"},
                {"id": 2, "method": "convert", "text": "serverwo", "metadata": {"source": "test"}},
                {"id": 3, "method": "missing", "text": "x"},
            ],
            extra_env={"MY_IME_BACKEND": "dummy"},
        )
        self.assertEqual(
            responses[0],
            {"ok": True, "service": "my-ime", "transport": "stdio", "id": 1},
        )
        self.assertEqual(responses[1]["text"], "サーバーを")
        self.assertEqual(responses[1]["backend"], "dummy")
        self.assertEqual(responses[1]["id"], 2)
        self.assertIn("unsupported method", str(responses[2].get("error", "")))

    def test_dummy_conversions_and_protection(self) -> None:
        cases = [
            ("org-roam-db-syncwoafter-save-hookdeyobunohaomoi", "org-roam-db-syncをafter-save-hookで呼ぶのは重い"),
            ("gemmaderoomajikashitarakyoushidataninarunodeha", "Gemmaでローマ字化したら教師データになるのでは"),
            (
                "targetwoemacsnigenteisurunaraeijinihongokankeinakutoriaezualphabetnyuuryokushita "
                "monowollmdeeigonihongomajirinooutputnikirikaerukotohakanou",
                "ターゲットをEmacsに限定するなら、英字・日本語関係なく、とりあえずalphabet入力した"
                "ものをLLMで英語日本語混じりのoutputに切り替えることは可能。",
            ),
            ("API response keishiki wa domain ni mochikomanai", "API response形式はdomainに持ち込まない"),
            ("Repository wo Entity kara yobanai hou ga ii", "RepositoryをEntityから呼ばない方がいい"),
            ("MY_IME_BACKEND dummy de offline ni ugoku", "MY_IME_BACKEND=dummyでofflineに動く"),
            ("my-ime-history ni before after wo nokosu", "my-ime-historyにbefore/afterを残す"),
        ]
        reqs = [{"id": i, "method": "convert", "text": src} for i, (src, _) in enumerate(cases)]
        resps = self._run_requests(reqs, extra_env={"MY_IME_BACKEND": "dummy"})
        for (_, expected), resp in zip(cases, resps):
            self.assertEqual(resp["text"], expected)

    def test_candidates_cartesian_product(self) -> None:
        resps = self._run_requests(
            [{"id": 1, "method": "candidates", "text": "kanjihenkandekiru"}],
            extra_env={
                "MY_IME_BACKEND": "dummy",
                "MY_IME_DICTIONARY": '{"kanji": ["漢字", "感じ"], "henkan": ["変換", "返還"], "dekiru": "できる"}',
            },
        )
        self.assertEqual(
            resps[0]["candidates"],
            ["漢字変換できる", "漢字返還できる", "感じ変換できる", "感じ返還できる"],
        )

    @unittest.skipUnless(kkc_available(), "kkc command is not available")
    def test_kkc_end_to_end_matches_python(self) -> None:
        reqs = [
            {"id": 1, "method": "convert", "text": ";;domain drive;;deyaru"},
            {"id": 2, "method": "convert", "text": ";;this is a pen;;"},
            {"id": 3, "method": "convert", "text": "  ;;data is dead;;"},
            {"id": 4, "method": "convert", "text": ";;org-roam-db-sync;;wo;;after-save-hook;;deyobunohaomoi"},
            {"id": 5, "method": "convert", "text": ";;global state;;gayoikannjiniikeru."},
            {"id": 6, "method": "convert", "text": "kyou ha akarui."},
            {"id": 7, "method": "convert", "text": "kyou ha totemo tanosii."},
            {"id": 8, "method": "convert", "text": "de-tawo yomu."},
            {"id": 9, "method": "preedit", "text": "de-tawo yomu"},
            {"id": 10, "method": "preedit", "text": "kyou ha totemo tanosii"},
            {"id": 11, "method": "preedit", "text": "jibunyou"},
            {"id": 12, "method": "convert", "text": "jibunyou"},
        ]
        resps = self._run_requests(
            reqs,
            extra_env={"MY_IME_BACKEND": "kkc", "MY_IME_KKC_NBEST": "3"},
        )
        expected = [
            "domain driveでやる",
            "this is a pen",
            "data is dead",
            "org-roam-db-syncをafter-save-hookで呼ぶのは重い",
            "global stateが良い感じにいける。",
            "今日は明るい。",
            "今日はとても楽しい。",
            "データを読む。",
            "データをよむ",
            "きょうはとてもたのしい",
            "じぶんよう",
            "自分用",
        ]
        self.assertEqual([r["text"] for r in resps], expected)


if __name__ == "__main__":
    unittest.main()
