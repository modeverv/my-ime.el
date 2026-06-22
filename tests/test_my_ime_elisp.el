;;; test_my_ime_elisp.el --- Tests for my-ime.el -*- lexical-binding: t; -*-

(require 'ert)
(require 'org)

(load-file (expand-file-name "../emacs/my-ime.el"
                             (file-name-directory
                              (or load-file-name buffer-file-name))))

(defun my-ime-test--type-short-kana (text)
  (dolist (char (string-to-list text))
    (let ((last-command-event char))
      (insert char)
      (my-ime--short-kana-post-self-insert))))

(ert-deftest my-ime-short-kana-converts-four-lowercase-romaji ()
  (with-temp-buffer
    (let ((my-ime-eager-local-kana nil)
          (my-ime-eager-short-kana-chars 4)
          (last-command-event ?u))
      (insert "kyou")
      (my-ime--short-kana-post-self-insert)
      (should (equal (buffer-string) "きょう")))))

(ert-deftest my-ime-short-kana-converts-three-lowercase-romaji ()
  (with-temp-buffer
    (let ((my-ime-eager-local-kana nil)
          (my-ime-eager-short-kana-chars 4)
          (last-command-event ?i))
      (insert "yoi")
      (my-ime--short-kana-post-self-insert)
      (should (equal (buffer-string) "よい")))))

(ert-deftest my-ime-short-kana-finalizes-fa-word-before-hyphen ()
  (with-temp-buffer
    (let ((my-ime-eager-local-kana nil)
          (my-ime-eager-short-kana-chars 4))
      (my-ime-test--type-short-kana "famiri-")
      (should (equal (buffer-string) "ふぁみりー")))))

(ert-deftest my-ime-short-kana-does-not-convert-org-todo-keyword ()
  (with-temp-buffer
    (org-mode)
    (let ((my-ime-eager-local-kana nil)
          (my-ime-eager-short-kana-chars 4)
          (last-command-event ?e))
      (insert "* done")
      (my-ime--short-kana-post-self-insert)
      (should (equal (buffer-string) "* done")))))

(ert-deftest my-ime-short-kana-does-not-convert-uppercase-window ()
  (with-temp-buffer
    (let ((my-ime-eager-local-kana nil)
          (my-ime-eager-short-kana-chars 4)
          (last-command-event ?E))
      (insert "DONE")
      (my-ime--short-kana-post-self-insert)
      (should (equal (buffer-string) "DONE")))))

;;; test_my_ime_elisp.el ends here
