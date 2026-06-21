;;; my-ime.el --- IME helpers -*- lexical-binding: t; -*-

;; This file is not part of GNU Emacs.

;;; Commentary:

;; Convert romanized/alphabet Japanese technical prose through a local
;; HTTP server.  The server is expected to expose /convert and /preedit.

;;; Code:

(require 'json)
(require 'cl-lib)
(require 'subr-x)
(require 'url)
(require 'url-http)
(require 'thingatpt)

(defgroup my-ime nil
  "IME conversion commands."
  :group 'editing)

(defcustom my-ime-server-url "http://127.0.0.1:8765"
  "Base URL for the local ime server."
  :type 'string
  :group 'my-ime)

(defcustom my-ime-timeout 10
  "Seconds to wait for the local ime server."
  :type 'number
  :group 'my-ime)

(defcustom my-ime-sentence-boundary-regexp "[。！？.!?]\\|\\`"
  "Regexp used to find the beginning of the sentence before point."
  :type 'regexp
  :group 'my-ime)

(defcustom my-ime-org-aware t
  "When non-nil, avoid unsafe org-mode regions by default."
  :type 'boolean
  :group 'my-ime)

(defcustom my-ime-history-limit 50
  "Maximum number of conversion records kept in `my-ime-history'."
  :type 'integer
  :group 'my-ime)

(defcustom my-ime-c-j-org-only t
  "When non-nil, line auto-conversion only runs in org buffers."
  :type 'boolean
  :group 'my-ime)

(defcustom my-ime-eager-trigger-chars '(?. ?, ?? ?! ?\s)
  "Characters that trigger eager sentence conversion in `my-ime-eager-mode'."
  :type '(repeat character)
  :group 'my-ime)

(defcustom my-ime-eager-space-preedit t
  "When non-nil, space in `my-ime-eager-mode' performs kana preedit conversion."
  :type 'boolean
  :group 'my-ime)

(defcustom my-ime-eager-min-chars 4
  "Minimum source length before eager conversion is attempted."
  :type 'integer
  :group 'my-ime)

(defvar my-ime-history nil
  "Recent conversion records.
Each entry is an alist with original text, converted text, command label,
buffer name, time, and metadata.")

(defvar my-ime--pending-preview nil
  "Pending preview state for accept/reject/retry commands.")

(defvar my-ime-preview-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "a") #'my-ime-accept-preview)
    (define-key map (kbd "C-c C-c") #'my-ime-accept-preview)
    (define-key map (kbd "r") #'my-ime-reject-preview)
    (define-key map (kbd "q") #'my-ime-reject-preview)
    (define-key map (kbd "g") #'my-ime-retry-preview)
    (define-key map (kbd "n") #'my-ime-alternate-preview)
    map)
  "Keymap for `my-ime-preview-mode'.")

(defvar my-ime-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c j j") #'my-ime-convert-dwim-async)
    (define-key map (kbd "C-c j r") #'my-ime-convert-region-async)
    (define-key map (kbd "C-c j s") #'my-ime-convert-last-sentence-async)
    (define-key map (kbd "C-c j p") #'my-ime-convert-paragraph-async)
    (define-key map (kbd "C-c j v") #'my-ime-preview-dwim-async)
    (define-key map (kbd "C-c j h") #'my-ime-show-history)
    (define-key map (kbd "C-c j e") #'my-ime-eager-mode)
    map)
  "Keymap for `my-ime-mode'.")

(defvar my-ime-eager-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'my-ime-convert-line-and-newline)
    (define-key map (kbd "C-c j e") #'my-ime-eager-mode)
    map)
  "Keymap for `my-ime-eager-mode'.")

(define-derived-mode my-ime-preview-mode special-mode "my-ime-preview"
  "Major mode for my-ime conversion previews.")

;;;###autoload
(define-minor-mode my-ime-mode
  "Minor mode for local LLM IME conversion commands."
  :lighter " my-ime"
  :keymap my-ime-mode-map)

;;;###autoload
(define-minor-mode my-ime-eager-mode
  "Minor mode that eagerly converts the previous sentence after punctuation."
  :lighter " my-ime-eager"
  :keymap my-ime-eager-mode-map
  (if my-ime-eager-mode
      (add-hook 'post-self-insert-hook #'my-ime--eager-post-self-insert nil t)
    (remove-hook 'post-self-insert-hook #'my-ime--eager-post-self-insert t)))

(defun my-ime--metadata ()
  "Build request metadata for the current buffer."
  `((mode . ,(format "%s" major-mode))
    (buffer_name . ,(buffer-name))
    (syntax . ,(if (derived-mode-p 'org-mode) "org" "plain"))))

(defun my-ime--request (text &optional extra-metadata endpoint-path)
  "Synchronously convert TEXT using the local server."
  (let* ((url-request-method "POST")
         (url-request-extra-headers '(("Content-Type" . "application/json; charset=utf-8")))
         (metadata (append (my-ime--metadata) extra-metadata))
         (url-request-data
          (encode-coding-string
           (json-encode `((text . ,text) (metadata . ,metadata)))
           'utf-8))
         (endpoint (concat (string-remove-suffix "/" my-ime-server-url)
                           (or endpoint-path "/convert")))
         (buffer (url-retrieve-synchronously endpoint t t my-ime-timeout)))
    (unless buffer
      (error "my-ime: request timed out after %ss" my-ime-timeout))
    (unwind-protect
        (with-current-buffer buffer
          (my-ime--parse-response-current-buffer))
      (kill-buffer buffer))))

(defun my-ime--request-async (text callback errback &optional extra-metadata endpoint-path)
  "Asynchronously convert TEXT, then call CALLBACK or ERRBACK.
CALLBACK receives converted text.  ERRBACK receives an error string."
  (let* ((url-request-method "POST")
         (url-request-extra-headers '(("Content-Type" . "application/json; charset=utf-8")))
         (metadata (append (my-ime--metadata) extra-metadata))
         (url-request-data
          (encode-coding-string
           (json-encode `((text . ,text) (metadata . ,metadata)))
           'utf-8))
         (endpoint (concat (string-remove-suffix "/" my-ime-server-url)
                           (or endpoint-path "/convert")))
         (done nil)
         (request-buffer nil)
         (timeout-timer nil))
    (setq
     request-buffer
     (url-retrieve
      endpoint
      (lambda (status)
        (unless done
          (setq done t)
          (when timeout-timer
            (cancel-timer timeout-timer))
          (unwind-protect
              (condition-case err
                  (if-let ((url-error (plist-get status :error)))
                      (funcall errback (format "%s" url-error))
                    (funcall callback (my-ime--parse-response-current-buffer)))
                (error (funcall errback (error-message-string err))))
            (when (buffer-live-p (current-buffer))
              (kill-buffer (current-buffer))))))
      nil
      t
      t))
    (if request-buffer
        (setq timeout-timer
              (run-at-time
               my-ime-timeout nil
               (lambda ()
                 (unless done
                   (setq done t)
                   (when (buffer-live-p request-buffer)
                     (kill-buffer request-buffer))
                   (funcall errback
                            (format "request timed out after %ss" my-ime-timeout))))))
      (funcall errback "request could not be started"))))

(defun my-ime--parse-response-current-buffer ()
  "Parse the current url response buffer and return converted text."
  (goto-char (point-min))
  (let ((status (my-ime--response-status)))
    (goto-char (point-min))
    (if (re-search-forward "\r?\n\r?\n" nil t)
        nil
      (goto-char (point-min)))
    (let* ((body (my-ime--decode-response-body (point) (point-max)))
           (json-object-type 'alist)
           (json-array-type 'list)
           (json-key-type 'symbol)
           (payload (with-temp-buffer
                      (insert body)
                      (goto-char (point-min))
                      (json-read))))
      (unless (= status 200)
        (error "my-ime: %s" (or (alist-get 'error payload) status)))
      (let ((converted (alist-get 'text payload)))
        (unless (stringp converted)
          (error "my-ime: response did not contain text"))
        converted))))

(defun my-ime--response-status ()
  "Return the HTTP status code for the current url response buffer."
  (save-excursion
    (goto-char (point-min))
    (cond
     ((looking-at "HTTP/[^ ]+ \\([0-9]+\\)")
      (string-to-number (match-string 1)))
     ((and (boundp 'url-http-response-status)
           (numberp url-http-response-status))
      url-http-response-status)
     (t 200))))

(defun my-ime--decode-response-body (beg end)
  "Return the HTTP response body between BEG and END decoded as UTF-8."
  (let ((body (buffer-substring-no-properties beg end)))
    (decode-coding-string (encode-coding-string body 'raw-text) 'utf-8)))

(defun my-ime--record-history (original converted label metadata)
  "Record a completed conversion from ORIGINAL to CONVERTED."
  (push `((time . ,(current-time-string))
          (buffer_name . ,(buffer-name))
          (label . ,label)
          (original . ,original)
          (converted . ,converted)
          (metadata . ,metadata))
        my-ime-history)
  (when (> (length my-ime-history) my-ime-history-limit)
    (setcdr (nthcdr (1- my-ime-history-limit) my-ime-history) nil)))

(defun my-ime--point-after-replacement (point beg end replacement-length)
  "Return where POINT should move after BEG END is replaced."
  (cond
   ((<= point beg)
    point)
   ((>= point end)
    (+ point (- replacement-length (- end beg))))
   (t
    (+ beg (min replacement-length (- point beg))))))

(defun my-ime--replace-region-preserve-point (beg end replacement)
  "Replace BEG END with REPLACEMENT while preserving point sensibly."
  (let* ((point-before (point))
         (target (my-ime--point-after-replacement
                  point-before beg end (length replacement))))
    (goto-char beg)
    (delete-region beg end)
    (insert replacement)
    (goto-char (min (point-max) (max (point-min) target)))))

(defun my-ime--replace-bounds (beg end label &optional extra-metadata allow-unsafe)
  "Convert the text between BEG and END and replace it on success.
LABEL is used for minibuffer status messages."
  (my-ime--ensure-safe-region beg end allow-unsafe)
  (let ((original (buffer-substring-no-properties beg end)))
    (when (string-empty-p original)
      (error "my-ime: empty %s" label))
    (message "my-ime: converting %s..." label)
    (let* ((metadata extra-metadata)
           (converted (my-ime--request original metadata)))
      (my-ime--replace-region-preserve-point beg end converted)
      (my-ime--record-history original converted label metadata)
      (message "my-ime: converted %s" label))))

(defun my-ime--replace-bounds-async
    (beg end label &optional extra-metadata allow-unsafe keep-end-before-insert endpoint-path)
  "Asynchronously convert BEG END and replace it if the source is unchanged."
  (my-ime--ensure-safe-region beg end allow-unsafe)
  (let ((source-buffer (current-buffer))
        (beg-marker (copy-marker beg))
        (end-marker (copy-marker end (not keep-end-before-insert)))
        (original (buffer-substring-no-properties beg end))
        (metadata extra-metadata))
    (when (string-empty-p original)
      (error "my-ime: empty %s" label))
    (message "my-ime: converting %s asynchronously..." label)
    (my-ime--request-async
     original
     (lambda (converted)
       (if (not (buffer-live-p source-buffer))
           (message "my-ime: source buffer disappeared")
         (with-current-buffer source-buffer
           (let ((current (buffer-substring-no-properties
                           (marker-position beg-marker)
                           (marker-position end-marker))))
             (if (not (string= current original))
                 (message "my-ime: source changed; async result discarded")
               (my-ime--replace-region-preserve-point
                (marker-position beg-marker)
                (marker-position end-marker)
                converted)
               (my-ime--record-history original converted label metadata)
               (message "my-ime: converted %s" label)))))
       (set-marker beg-marker nil)
       (set-marker end-marker nil))
     (lambda (message)
       (set-marker beg-marker nil)
       (set-marker end-marker nil)
       (message "my-ime: %s" message))
     metadata
     endpoint-path)))

(defun my-ime--preview-bounds (beg end label &optional extra-metadata allow-unsafe)
  "Convert text between BEG and END and show an accept/reject preview."
  (my-ime--ensure-safe-region beg end allow-unsafe)
  (let ((original (buffer-substring-no-properties beg end)))
    (when (string-empty-p original)
      (error "my-ime: empty %s" label))
    (message "my-ime: preparing %s preview..." label)
    (let ((converted (my-ime--request original extra-metadata)))
      (setq my-ime--pending-preview
            `((source_buffer . ,(current-buffer))
              (beg_marker . ,(copy-marker beg))
              (end_marker . ,(copy-marker end t))
              (label . ,label)
              (original . ,original)
              (converted . ,converted)
              (metadata . ,extra-metadata)))
      (my-ime--show-preview)
      (message "my-ime: preview ready"))))

(defun my-ime--preview-bounds-async (beg end label &optional extra-metadata allow-unsafe)
  "Asynchronously convert BEG END and show a preview if source is unchanged."
  (my-ime--ensure-safe-region beg end allow-unsafe)
  (let ((source-buffer (current-buffer))
        (beg-marker (copy-marker beg))
        (end-marker (copy-marker end t))
        (original (buffer-substring-no-properties beg end))
        (metadata extra-metadata))
    (when (string-empty-p original)
      (error "my-ime: empty %s" label))
    (message "my-ime: preparing %s preview asynchronously..." label)
    (my-ime--request-async
     original
     (lambda (converted)
       (if (not (buffer-live-p source-buffer))
           (progn
             (set-marker beg-marker nil)
             (set-marker end-marker nil)
             (message "my-ime: source buffer disappeared"))
         (with-current-buffer source-buffer
           (let ((current (buffer-substring-no-properties
                           (marker-position beg-marker)
                           (marker-position end-marker))))
             (if (not (string= current original))
                 (progn
                   (set-marker beg-marker nil)
                   (set-marker end-marker nil)
                   (message "my-ime: source changed; async preview discarded"))
               (setq my-ime--pending-preview
                     `((source_buffer . ,source-buffer)
                       (beg_marker . ,beg-marker)
                       (end_marker . ,end-marker)
                       (label . ,label)
                       (original . ,original)
                       (converted . ,converted)
                       (metadata . ,metadata)))
               (my-ime--show-preview)
               (message "my-ime: preview ready"))))))
     (lambda (message)
       (set-marker beg-marker nil)
       (set-marker end-marker nil)
       (message "my-ime: %s" message))
     metadata)))

(defun my-ime--show-preview ()
  "Render the current pending preview."
  (unless my-ime--pending-preview
    (error "my-ime: no pending preview"))
  (let* ((original (alist-get 'original my-ime--pending-preview))
         (converted (alist-get 'converted my-ime--pending-preview))
         (label (alist-get 'label my-ime--pending-preview))
         (buffer (get-buffer-create "*my-ime preview*"))
         (inhibit-read-only t))
    (with-current-buffer buffer
      (erase-buffer)
      (insert (format "my-ime preview: %s\n\n" label))
      (insert "Keys: a accept, r reject, g retry, n alternate, q reject\n\n")
      (insert "--- original\n+++ converted\n@@\n")
      (insert (my-ime--preview-diff original converted))
      (insert "\n\nConverted:\n\n")
      (insert converted)
      (goto-char (point-min))
      (my-ime-preview-mode))
    (pop-to-buffer buffer)))

(defun my-ime--preview-diff (original converted)
  "Return a compact diff-like preview for ORIGINAL and CONVERTED."
  (if (string= original converted)
      " unchanged\n"
    (concat
     (mapconcat (lambda (line) (concat "-" line))
                (split-string original "\n")
                "\n")
     "\n"
     (mapconcat (lambda (line) (concat "+" line))
                (split-string converted "\n")
                "\n")
     "\n")))

(defun my-ime--apply-preview ()
  "Apply the current pending preview to its source buffer."
  (unless my-ime--pending-preview
    (error "my-ime: no pending preview"))
  (let* ((source-buffer (alist-get 'source_buffer my-ime--pending-preview))
         (beg-marker (alist-get 'beg_marker my-ime--pending-preview))
         (end-marker (alist-get 'end_marker my-ime--pending-preview))
         (original (alist-get 'original my-ime--pending-preview))
         (converted (alist-get 'converted my-ime--pending-preview))
         (label (alist-get 'label my-ime--pending-preview))
         (metadata (alist-get 'metadata my-ime--pending-preview)))
    (unless (buffer-live-p source-buffer)
      (error "my-ime: source buffer is gone"))
    (with-current-buffer source-buffer
      (let ((beg (marker-position beg-marker))
            (end (marker-position end-marker)))
        (unless (string= (buffer-substring-no-properties beg end) original)
          (error "my-ime: source text changed; refusing to apply preview"))
        (my-ime--replace-region-preserve-point beg end converted)
        (my-ime--record-history original converted label metadata)))
    (my-ime--clear-preview)
    (message "my-ime: accepted %s" label)))

(defun my-ime--clear-preview ()
  "Clear preview state and preview buffer."
  (when my-ime--pending-preview
    (let ((beg-marker (alist-get 'beg_marker my-ime--pending-preview))
          (end-marker (alist-get 'end_marker my-ime--pending-preview)))
      (when (markerp beg-marker) (set-marker beg-marker nil))
      (when (markerp end-marker) (set-marker end-marker nil))))
  (setq my-ime--pending-preview nil)
  (let ((buffer (get-buffer "*my-ime preview*")))
    (when buffer
      (kill-buffer buffer))))

(defun my-ime--last-sentence-bounds ()
  "Return bounds for the sentence before point."
  (let ((end (save-excursion
               (skip-chars-backward " \t\n")
               (point)))
        beg
        line-beg)
    (save-excursion
      (goto-char end)
      (setq line-beg (line-beginning-position))
      (when (and (> (point) (point-min))
                 (save-excursion
                   (backward-char 1)
                   (looking-at my-ime-sentence-boundary-regexp)))
        (backward-char 1))
      (if (re-search-backward my-ime-sentence-boundary-regexp line-beg t)
          (setq beg (if (looking-at "\\`") (point) (match-end 0)))
        (setq beg line-beg)))
    (while (and (< beg end)
                (member (char-after beg) '(?\s ?\t ?\n)))
      (setq beg (1+ beg)))
    (cons beg end)))

(defun my-ime--current-line-before-point-bounds ()
  "Return trimmed bounds for the current line before point."
  (let ((beg (line-beginning-position))
        (end (point)))
    (while (and (< beg end)
                (memq (char-after beg) '(?\s ?\t)))
      (setq beg (1+ beg)))
    (while (and (< beg end)
                (memq (char-before end) '(?\s ?\t)))
      (setq end (1- end)))
    (cons beg end)))

(defun my-ime--auto-convertible-text-p (text)
  "Return non-nil when TEXT looks worth auto-converting."
  (and (>= (length (string-trim text)) my-ime-eager-min-chars)
       (string-match-p "[[:alpha:]ぁ-んァ-ン一-龯々〆〤]" text)
       (my-ime--manual-term-markers-balanced-p text)))

(defun my-ime--eager-endpoint-path ()
  "Return the server endpoint path for the current eager trigger."
  (if (and my-ime-eager-space-preedit
           (eq last-command-event ?\s))
      "/preedit"
    "/convert"))

(defun my-ime--eager-label ()
  "Return a status label for the current eager trigger."
  (if (and my-ime-eager-space-preedit
           (eq last-command-event ?\s))
      "eager preedit"
    "eager sentence"))

(defun my-ime--manual-term-markers-balanced-p (text)
  "Return non-nil when TEXT has balanced manual term markers."
  (= 0 (% (my-ime--count-substring text ";;") 2)))

(defun my-ime--count-substring (text needle)
  "Count non-overlapping occurrences of NEEDLE in TEXT."
  (let ((count 0)
        (start 0))
    (while (string-match (regexp-quote needle) text start)
      (setq count (1+ count)
            start (match-end 0)))
    count))

(defun my-ime--eager-post-self-insert ()
  "Convert the previous sentence after eager trigger punctuation."
  (when (and my-ime-eager-mode
             (characterp last-command-event)
             (memq last-command-event my-ime-eager-trigger-chars)
             (not (minibufferp))
             (not buffer-read-only))
    (let* ((bounds (my-ime--last-sentence-bounds))
           (beg (car bounds))
           (end (cdr bounds))
           (text (buffer-substring-no-properties beg end)))
      (when (and (< beg end)
                 (my-ime--auto-convertible-text-p text))
        (condition-case err
            (my-ime--replace-bounds-async
             beg end (my-ime--eager-label)
             `((trigger . ,(if (eq last-command-event ?\s)
                               "eager-space"
                             "eager-punctuation")))
             nil nil
             (my-ime--eager-endpoint-path))
          (error (message "my-ime: eager conversion skipped: %s"
                          (error-message-string err))))))))

(defun my-ime--paragraph-bounds ()
  "Return paragraph bounds around point."
  (if (and my-ime-org-aware (derived-mode-p 'org-mode))
      (my-ime--org-paragraph-bounds)
    (or (bounds-of-thing-at-point 'paragraph)
        (cons (line-beginning-position) (line-end-position)))))

(defun my-ime--org-paragraph-bounds ()
  "Return org-aware paragraph bounds around point."
  (save-excursion
    (let ((beg (line-beginning-position))
          (end (line-end-position)))
      (while (and (> beg (point-min))
                  (save-excursion
                    (goto-char (1- beg))
                    (not (my-ime--org-boundary-line-p))))
        (forward-line -1)
        (setq beg (line-beginning-position)))
      (goto-char end)
      (while (and (< end (point-max))
                  (save-excursion
                    (forward-line 1)
                    (not (my-ime--org-boundary-line-p))))
        (forward-line 1)
        (setq end (line-end-position)))
      (cons beg end))))

(defun my-ime--org-boundary-line-p ()
  "Return non-nil when the current org line should bound prose conversion."
  (or (looking-at-p "\\s-*$")
      (looking-at-p "\\s-*#\\+begin_")
      (looking-at-p "\\s-*#\\+end_")
      (looking-at-p "\\s-*#\\+")
      (looking-at-p "\\s-*|")
      (looking-at-p "\\s-*:[A-Z_]+:\\s-*$")))

(defun my-ime--ensure-safe-region (beg end &optional allow-unsafe)
  "Signal if BEG to END is unsafe for default conversion."
  (when (and my-ime-org-aware (derived-mode-p 'org-mode) (not allow-unsafe))
    (save-excursion
      (goto-char beg)
      (when (my-ime--org-unsafe-region-p beg end)
        (error "my-ime: unsafe org region; select a smaller prose region or set my-ime-org-aware nil")))))

(defun my-ime--org-unsafe-region-p (beg end)
  "Return non-nil when org region BEG END contains unsafe syntax."
  (or (my-ime--org-in-block-p beg end)
      (my-ime--org-in-property-drawer-p beg end)
      (my-ime--region-has-line-p beg end "\\s-*|")
      (my-ime--region-has-line-p beg end "\\s-*#\\+")
      (my-ime--region-has-unprotected-org-link-p beg end)))

(defun my-ime--org-in-block-p (beg end)
  "Return non-nil if BEG END overlaps org block contents."
  (save-excursion
    (goto-char (point-min))
    (let ((inside nil)
          (unsafe nil))
      (while (and (not unsafe) (< (point) end))
        (cond
         ((looking-at-p "\\s-*#\\+begin_\\(src\\|example\\|export\\|quote\\)")
          (setq inside t))
         ((looking-at-p "\\s-*#\\+end_\\(src\\|example\\|export\\|quote\\)")
          (when (and inside (>= (point) beg))
            (setq unsafe t))
          (setq inside nil))
         ((and inside (>= (point) beg))
          (setq unsafe t)))
        (forward-line 1))
      unsafe)))

(defun my-ime--org-in-property-drawer-p (beg end)
  "Return non-nil if BEG END overlaps an org property drawer."
  (save-excursion
    (goto-char (point-min))
    (let ((inside nil)
          (unsafe nil))
      (while (and (not unsafe) (< (point) end))
        (cond
         ((looking-at-p "\\s-*:PROPERTIES:\\s-*$")
          (setq inside t))
         ((looking-at-p "\\s-*:END:\\s-*$")
          (when (and inside (>= (point) beg))
            (setq unsafe t))
          (setq inside nil))
         ((and inside (>= (point) beg))
          (setq unsafe t)))
        (forward-line 1))
      unsafe)))

(defun my-ime--region-has-line-p (beg end regexp)
  "Return non-nil if a line matching REGEXP appears in BEG END."
  (save-excursion
    (goto-char beg)
    (let ((found nil))
      (while (and (not found) (< (point) end))
        (when (looking-at-p regexp)
          (setq found t))
        (forward-line 1))
      found)))

(defun my-ime--region-has-unprotected-org-link-p (beg end)
  "Return non-nil if BEG END appears to include org link syntax."
  (save-excursion
    (goto-char beg)
    (re-search-forward "\\[\\[" end t)))

(defun my-ime--org-headline-text-bounds ()
  "Return safe bounds for the current org headline text."
  (save-excursion
    (beginning-of-line)
    (unless (looking-at "\\(\\*+\\s-+\\)\\(.*?\\)\\(\\s-+:[[:alnum:]_@#%:]+:\\s-*\\)?$")
      (error "my-ime: not on an org headline"))
    (let ((beg (+ (line-beginning-position) (length (match-string 1))))
          (tag (match-beginning 3))
          (line-end (line-end-position)))
      (cons beg (or tag line-end)))))

(defun my-ime--region-or-last-sentence-bounds ()
  "Return active region bounds, or last sentence bounds."
  (if (use-region-p)
      (cons (region-beginning) (region-end))
    (my-ime--last-sentence-bounds)))

(defun my-ime--region-or-paragraph-bounds ()
  "Return active region bounds, or paragraph bounds."
  (if (use-region-p)
      (cons (region-beginning) (region-end))
    (my-ime--paragraph-bounds)))

;;;###autoload
(defun my-ime-convert-region (beg end)
  "Convert the selected region from romanized input to mixed Japanese prose."
  (interactive "r")
  (unless (use-region-p)
    (error "my-ime: no active region"))
  (my-ime--replace-bounds beg end "region" nil t))

;;;###autoload
(defun my-ime-convert-last-sentence ()
  "Convert the sentence ending at point."
  (interactive)
  (let ((bounds (my-ime--last-sentence-bounds)))
    (my-ime--replace-bounds (car bounds) (cdr bounds) "sentence")))

;;;###autoload
(defun my-ime-convert-paragraph ()
  "Convert the paragraph around point."
  (interactive)
  (let ((bounds (my-ime--paragraph-bounds)))
    (my-ime--replace-bounds (car bounds) (cdr bounds) "paragraph")))

;;;###autoload
(defun my-ime-convert-dwim ()
  "Convert active region, or the sentence ending at point."
  (interactive)
  (if (use-region-p)
      (my-ime-convert-region (region-beginning) (region-end))
    (my-ime-convert-last-sentence)))

;;;###autoload
(defun my-ime-convert-region-async (beg end)
  "Asynchronously convert the selected region."
  (interactive "r")
  (unless (use-region-p)
    (error "my-ime: no active region"))
  (my-ime--replace-bounds-async beg end "region" nil t))

;;;###autoload
(defun my-ime-convert-last-sentence-async ()
  "Asynchronously convert the sentence ending at point."
  (interactive)
  (let ((bounds (my-ime--last-sentence-bounds)))
    (my-ime--replace-bounds-async (car bounds) (cdr bounds) "sentence")))

;;;###autoload
(defun my-ime-convert-paragraph-async ()
  "Asynchronously convert the paragraph around point."
  (interactive)
  (let ((bounds (my-ime--paragraph-bounds)))
    (my-ime--replace-bounds-async (car bounds) (cdr bounds) "paragraph")))

;;;###autoload
(defun my-ime-convert-dwim-async ()
  "Asynchronously convert active region, or the sentence ending at point."
  (interactive)
  (if (use-region-p)
      (my-ime-convert-region-async (region-beginning) (region-end))
    (my-ime-convert-last-sentence-async)))

;;;###autoload
(defun my-ime-convert-line-and-newline ()
  "Convert the current line before point asynchronously, then insert a newline.
When `my-ime-c-j-org-only' is non-nil, non-org buffers only insert a
normal newline."
  (interactive)
  (if (and my-ime-c-j-org-only
           (not (derived-mode-p 'org-mode)))
      (newline-and-indent)
    (let* ((bounds (my-ime--current-line-before-point-bounds))
           (beg (car bounds))
           (end (cdr bounds))
           (text (buffer-substring-no-properties beg end)))
      (when (and (< beg end)
                 (my-ime--auto-convertible-text-p text))
        (condition-case err
            (my-ime--replace-bounds-async
             beg end "line" '((trigger . "line-newline")) nil t)
          (error (message "my-ime: line conversion skipped: %s"
                          (error-message-string err)))))
      (newline-and-indent))))

;;;###autoload
(defun my-ime-preview-region (beg end)
  "Preview conversion for the selected region."
  (interactive "r")
  (unless (use-region-p)
    (error "my-ime: no active region"))
  (my-ime--preview-bounds beg end "region" nil t))

;;;###autoload
(defun my-ime-preview-last-sentence ()
  "Preview conversion for the sentence ending at point."
  (interactive)
  (let ((bounds (my-ime--last-sentence-bounds)))
    (my-ime--preview-bounds (car bounds) (cdr bounds) "sentence")))

;;;###autoload
(defun my-ime-preview-paragraph ()
  "Preview conversion for the paragraph around point."
  (interactive)
  (let ((bounds (my-ime--paragraph-bounds)))
    (my-ime--preview-bounds (car bounds) (cdr bounds) "paragraph")))

;;;###autoload
(defun my-ime-preview-dwim ()
  "Preview active region conversion, or sentence conversion at point."
  (interactive)
  (let ((bounds (my-ime--region-or-last-sentence-bounds)))
    (my-ime--preview-bounds (car bounds) (cdr bounds)
                             (if (use-region-p) "region" "sentence")
                             nil
                             (use-region-p))))

;;;###autoload
(defun my-ime-preview-region-async (beg end)
  "Asynchronously prepare a preview for the selected region."
  (interactive "r")
  (unless (use-region-p)
    (error "my-ime: no active region"))
  (my-ime--preview-bounds-async beg end "region" nil t))

;;;###autoload
(defun my-ime-preview-last-sentence-async ()
  "Asynchronously prepare a preview for the sentence ending at point."
  (interactive)
  (let ((bounds (my-ime--last-sentence-bounds)))
    (my-ime--preview-bounds-async (car bounds) (cdr bounds) "sentence")))

;;;###autoload
(defun my-ime-preview-paragraph-async ()
  "Asynchronously prepare a preview for the paragraph around point."
  (interactive)
  (let ((bounds (my-ime--paragraph-bounds)))
    (my-ime--preview-bounds-async (car bounds) (cdr bounds) "paragraph")))

;;;###autoload
(defun my-ime-preview-dwim-async ()
  "Asynchronously preview region conversion, or sentence conversion."
  (interactive)
  (let ((bounds (my-ime--region-or-last-sentence-bounds)))
    (my-ime--preview-bounds-async (car bounds) (cdr bounds)
                                   (if (use-region-p) "region" "sentence")
                                   nil
                                   (use-region-p))))

;;;###autoload
(defun my-ime-convert-org-headline ()
  "Convert only the text part of the current org headline."
  (interactive)
  (unless (derived-mode-p 'org-mode)
    (error "my-ime: not in org-mode"))
  (let ((bounds (my-ime--org-headline-text-bounds)))
    (my-ime--replace-bounds (car bounds) (cdr bounds) "org headline")))

;;;###autoload
(defun my-ime-preview-org-headline ()
  "Preview conversion for only the text part of the current org headline."
  (interactive)
  (unless (derived-mode-p 'org-mode)
    (error "my-ime: not in org-mode"))
  (let ((bounds (my-ime--org-headline-text-bounds)))
    (my-ime--preview-bounds (car bounds) (cdr bounds) "org headline")))

;;;###autoload
(defun my-ime-accept-preview ()
  "Accept the current my-ime preview and replace the source text."
  (interactive)
  (my-ime--apply-preview))

;;;###autoload
(defun my-ime-reject-preview ()
  "Reject the current my-ime preview without changing the source buffer."
  (interactive)
  (my-ime--clear-preview)
  (message "my-ime: rejected preview"))

;;;###autoload
(defun my-ime-retry-preview ()
  "Retry conversion for the current preview."
  (interactive)
  (unless my-ime--pending-preview
    (error "my-ime: no pending preview"))
  (let* ((source-buffer (alist-get 'source_buffer my-ime--pending-preview))
         (original (alist-get 'original my-ime--pending-preview))
         (metadata (alist-get 'metadata my-ime--pending-preview)))
    (unless (buffer-live-p source-buffer)
      (error "my-ime: source buffer is gone"))
    (with-current-buffer source-buffer
      (setf (alist-get 'converted my-ime--pending-preview)
            (my-ime--request original (append metadata '((retry . t))))))
    (my-ime--show-preview)
    (message "my-ime: preview retried")))

;;;###autoload
(defun my-ime-alternate-preview ()
  "Request an alternate candidate for the current preview."
  (interactive)
  (unless my-ime--pending-preview
    (error "my-ime: no pending preview"))
  (let* ((source-buffer (alist-get 'source_buffer my-ime--pending-preview))
         (original (alist-get 'original my-ime--pending-preview))
         (metadata (alist-get 'metadata my-ime--pending-preview)))
    (unless (buffer-live-p source-buffer)
      (error "my-ime: source buffer is gone"))
    (with-current-buffer source-buffer
      (setf (alist-get 'converted my-ime--pending-preview)
            (my-ime--request original (append metadata '((alternate . t))))))
    (my-ime--show-preview)
    (message "my-ime: alternate preview ready")))

;;;###autoload
(defun my-ime-show-history ()
  "Show recent my-ime conversion history."
  (interactive)
  (let ((buffer (get-buffer-create "*my-ime history*"))
        (inhibit-read-only t))
    (with-current-buffer buffer
      (erase-buffer)
      (dolist (record my-ime-history)
        (insert (format "%s  %s  %s\n"
                        (alist-get 'time record)
                        (alist-get 'buffer_name record)
                        (alist-get 'label record)))
        (insert "  original:  " (replace-regexp-in-string "\n" "\\n" (alist-get 'original record)) "\n")
        (insert "  converted: " (replace-regexp-in-string "\n" "\\n" (alist-get 'converted record)) "\n\n"))
      (goto-char (point-min))
      (special-mode))
    (pop-to-buffer buffer)))

(provide 'my-ime)

;;; my-ime.el ends here
