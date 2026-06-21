from __future__ import annotations

import unittest

from server.protection import ProtectionError, protect_text, protected_tokens, restore_text


class ProtectionTests(unittest.TestCase):
    def test_protects_joined_emacs_identifiers(self) -> None:
        protected = protect_text("org-roam-db-syncwoafter-save-hookdeyobunohaomoi")
        self.assertEqual(
            protected.text,
            "<TECH_0>wo<TECH_1>deyobunohaomoi",
        )
        self.assertEqual(
            [span.original for span in protected.spans],
            ["org-roam-db-sync", "after-save-hook"],
        )
        restored = restore_text("<TECH_0>を<TECH_1>で呼ぶのは重い", protected)
        self.assertEqual(restored, "org-roam-db-syncをafter-save-hookで呼ぶのは重い")

    def test_protects_manual_term_markers(self) -> None:
        protected = protect_text(";;domain drive;;deyaru")
        self.assertEqual(protected.text, "<TECH_0>deyaru")
        self.assertEqual(protected.spans[0].original, "domain drive")
        self.assertEqual(protected.spans[0].kind, "manual_term")
        self.assertEqual(restore_text("<TECH_0>でやる", protected), "domain driveでやる")

    def test_manual_term_marker_must_be_balanced(self) -> None:
        with self.assertRaises(ProtectionError):
            protect_text(";;domain drive;deyaru")

    def test_protects_urls_paths_api_paths_keybindings_and_lisp_forms(self) -> None:
        text = (
            "curl -s http://127.0.0.1:8765/openapi.json wo /api/v1/convert ni "
            "~/work/ai/foo.org kara C-c j j de (message \"hi\") made"
        )
        tokens = protected_tokens(text)
        self.assertIn("curl -s", tokens)
        self.assertIn("http://127.0.0.1:8765/openapi.json", tokens)
        self.assertIn("/api/v1/convert", tokens)
        self.assertIn("~/work/ai/foo.org", tokens)
        self.assertIn("C-c j j", tokens)
        self.assertIn('(message "hi")', tokens)

    def test_identifier_particle_split_does_not_cut_english_words(self) -> None:
        protected = protect_text("C-c j j de my-ime-convert-dwim wo yobu")
        self.assertEqual(
            [span.original for span in protected.spans],
            ["C-c j j", "my-ime-convert-dwim"],
        )

    def test_identifier_particle_split_does_not_cut_inside_hyphenated_words(self) -> None:
        protected = protect_text("my-ime-history ni before after wo nokosu")
        self.assertEqual(protected.text, "<TECH_0> ni before after wo nokosu")
        self.assertEqual([span.original for span in protected.spans], ["my-ime-history"])

        protected = protect_text("org-roam-node-find no candidate cache wo atatamete oku")
        self.assertEqual(protected.text, "<TECH_0> no candidate cache wo atatamete oku")
        self.assertEqual([span.original for span in protected.spans], ["org-roam-node-find"])

    def test_short_hyphenated_romaji_is_not_protected(self) -> None:
        protected = protect_text("de-ta wo yomu")
        self.assertEqual(protected.text, "de-ta wo yomu")
        self.assertEqual(protected.spans, ())

    def test_does_not_protect_env_var_names_that_phrase_normalization_handles(self) -> None:
        protected = protect_text("MY_IME_BACKEND dummy de offline ni ugoku")
        self.assertEqual(protected.spans, ())

    def test_restore_fails_if_placeholder_missing(self) -> None:
        protected = protect_text("after-save-hook de yobu")
        with self.assertRaises(ProtectionError):
            restore_text("壊れた output", protected)

    def test_restore_fails_if_placeholder_duplicated(self) -> None:
        protected = protect_text("after-save-hook de yobu")
        with self.assertRaises(ProtectionError):
            restore_text("<TECH_0><TECH_0>で呼ぶ", protected)


if __name__ == "__main__":
    unittest.main()
