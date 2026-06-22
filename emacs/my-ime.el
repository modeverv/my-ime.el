;;; my-ime.el --- IME helpers -*- lexical-binding: t; -*-

;; This file is not part of GNU Emacs.

;;; Commentary:

;; Convert romanized/alphabet Japanese technical prose through a local
;; stdio worker or HTTP server.

;;; Code:

(require 'json)
(require 'cl-lib)
(require 'subr-x)
(require 'url)
(require 'url-http)
(require 'thingatpt)

(declare-function company-begin-backend "company")
(declare-function company-mode "company")

(defgroup my-ime nil
  "IME conversion commands."
  :group 'editing)

(defcustom my-ime-server-url "http://127.0.0.1:8765"
  "Base URL for the legacy local HTTP ime server.
This is used only when `my-ime-transport' is `http'."
  :type 'string
  :group 'my-ime)

(defcustom my-ime-transport 'stdio
  "Transport used for conversion requests.
The standard transport is `stdio', where Emacs owns one local worker process
and communicates with it over standard input and output.  `http' is kept for
the legacy server mode."
  :type '(choice (const :tag "stdio worker" stdio)
                 (const :tag "legacy HTTP server" http))
  :group 'my-ime)

(defcustom my-ime-stdio-command nil
  "Command list used to start the my-ime stdio worker.
When nil, use `my-ime-stdio' from PATH, falling back to the project-local
Python module."
  :type '(choice (const :tag "Auto" nil)
                 (repeat :tag "Command argv" string))
  :group 'my-ime)

(defconst my-ime--load-directory
  (file-name-directory (or load-file-name buffer-file-name default-directory))
  "Directory where my-ime.el was loaded from.")

(defcustom my-ime-project-root
  (file-name-as-directory (expand-file-name ".." my-ime--load-directory))
  "Project root used when starting the project-local stdio worker."
  :type 'directory
  :group 'my-ime)

(defcustom my-ime-runtime-directory
  (expand-file-name ".deps/kkc-runtime/current" my-ime-project-root)
  "Directory containing the downloaded kkc runtime."
  :type 'directory
  :group 'my-ime)

(defcustom my-ime-timeout 10
  "Seconds to wait for the local ime worker."
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

(defcustom my-ime-eager-local-kana nil
  "When non-nil, convert completed romaji syllables locally while typing.
By default, eager-mode waits for SPC and uses the worker preedit path
instead of converting romaji after each character."
  :type 'boolean
  :group 'my-ime)

(defcustom my-ime-live-idle-delay 0.03
  "Idle seconds before `my-ime-live-mode' refreshes the live conversion."
  :type 'number
  :group 'my-ime)

(defcustom my-ime-live-min-chars 3
  "Minimum trimmed source length before live conversion is attempted."
  :type 'integer
  :group 'my-ime)

(defcustom my-ime-live-preview-endpoint "/convert"
  "Endpoint used for `my-ime-live-mode' preview overlays.
Use \"/convert\" for kanji-like live conversion, or \"/preedit\" for lighter
kana-only preview."
  :type '(choice (const :tag "Kanji conversion" "/convert")
                 (const :tag "Kana preedit" "/preedit"))
  :group 'my-ime)

(defcustom my-ime-eager-short-kana-chars 4
  "Number of lowercase romaji chars to kana-convert without waiting for SPC.
Set this to nil or 0 to disable short-window kana conversion."
  :type '(choice (const :tag "Disabled" nil) integer)
  :group 'my-ime)

(defcustom my-ime-eager-org-syntax-guard t
  "When non-nil, skip eager conversion on org syntax lines."
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

(defvar-local my-ime--company-candidates nil
  "Current my-ime company candidates.")

(defvar-local my-ime--company-original nil
  "Original source text for current my-ime company completion.")

(defvar-local my-ime--company-label nil
  "Label for current my-ime company completion.")

(defvar-local my-ime--company-metadata nil
  "Metadata for current my-ime company completion.")

(defvar-local my-ime--company-beg-marker nil
  "Beginning marker for current my-ime company completion.")

(defvar-local my-ime--company-end-marker nil
  "End marker for current my-ime company completion.")

(defvar-local my-ime--suppress-next-ret-conversion nil
  "When non-nil, the next eager RET only inserts a newline.")

(defvar-local my-ime--live-overlay nil
  "Overlay displaying the current live conversion candidate.")

(defvar-local my-ime--live-state nil
  "Current live conversion state.")

(defvar-local my-ime--live-timer nil
  "Idle timer used by `my-ime-live-mode'.")

(defvar-local my-ime--live-sequence 0
  "Monotonic sequence for discarding stale live conversion responses.")

(defvar-local my-ime--live-inhibit-after-change nil
  "When non-nil, live-mode after-change handling is suppressed.")

(defvar my-ime--stdio-process nil
  "Live my-ime stdio worker process.")

(defvar my-ime--stdio-buffer " *my-ime-stdio*"
  "Process buffer for the my-ime stdio worker.")

(defvar my-ime--stdio-stderr-buffer " *my-ime-stdio-stderr*"
  "Stderr buffer for the my-ime stdio worker.")

(defvar my-ime--stdio-next-id 0
  "Next stdio request id.")

(defvar my-ime--stdio-pending (make-hash-table :test 'equal)
  "Pending stdio requests keyed by request id.")

(defvar my-ime--stdio-partial ""
  "Partial stdio response line.")

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
    (define-key map (kbd "C-o") #'my-ime-select-candidate-dwim)
    (define-key map (kbd "C-c j c") #'my-ime-select-candidate-dwim)
    (define-key map (kbd "C-c j v") #'my-ime-preview-dwim-async)
    (define-key map (kbd "C-c j h") #'my-ime-show-history)
    (define-key map (kbd "C-c j e") #'my-ime-eager-mode)
    map)
  "Keymap for `my-ime-mode'.")

(defvar my-ime-eager-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-o") #'my-ime-select-candidate-dwim)
    (define-key map (kbd "RET") #'my-ime-convert-line-and-newline)
    (define-key map (kbd "C-c j e") #'my-ime-eager-mode)
    map)
  "Keymap for `my-ime-eager-mode'.")

(defvar my-ime-live-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'my-ime-live-commit-and-newline)
    (define-key map (kbd "C-o") #'my-ime-live-select-candidate)
    (define-key map (kbd "C-c j RET") #'my-ime-live-commit)
    (define-key map (kbd "C-c j l") #'my-ime-live-mode)
    map)
  "Keymap for `my-ime-live-mode'.")

(defface my-ime-live-preview-face
  '((t :inherit region))
  "Face used for live conversion preview overlays."
  :group 'my-ime)

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
  :lighter " [mj]"
  :keymap my-ime-eager-mode-map
  (if my-ime-eager-mode
      (add-hook 'post-self-insert-hook #'my-ime--eager-post-self-insert nil t)
    (remove-hook 'post-self-insert-hook #'my-ime--eager-post-self-insert t)))

;;;###autoload
(define-minor-mode my-ime-live-mode
  "Minor mode that previews live conversion with an uncommitted overlay."
  :lighter " [mj-live]"
  :keymap my-ime-live-mode-map
  (if my-ime-live-mode
      (progn
        (add-hook 'after-change-functions #'my-ime--live-after-change nil t)
        (my-ime--live-schedule-refresh))
    (remove-hook 'after-change-functions #'my-ime--live-after-change t)
    (my-ime--live-cancel-timer)
    (my-ime--live-clear)))

(defun my-ime--metadata ()
  "Build request metadata for the current buffer."
  `((mode . ,(format "%s" major-mode))
    (buffer_name . ,(buffer-name))
    (syntax . ,(if (derived-mode-p 'org-mode) "org" "plain"))))

(defun my-ime--endpoint-method (endpoint-path)
  "Return stdio method name for ENDPOINT-PATH."
  (cond
   ((equal endpoint-path "/preedit") "preedit")
   ((equal endpoint-path "/candidates") "candidates")
   (t "convert")))

(defun my-ime--stdio-command ()
  "Return argv for starting the stdio worker."
  (cond
   (my-ime-stdio-command my-ime-stdio-command)
   ((executable-find "my-ime-stdio") (list (executable-find "my-ime-stdio")))
   (t (list (my-ime--python-command) "-m" "server.stdio_app"))))

(defun my-ime--python-command ()
  "Return a Python command suitable for the current platform."
  (or (and (my-ime--windows-p) (executable-find "python"))
      (executable-find "python3")
      (executable-find "python")
      "python3"))

(defun my-ime--windows-p ()
  "Return non-nil when running on native Windows Emacs."
  (eq system-type 'windows-nt))

(defun my-ime--runtime-kkc-command (runtime)
  "Return the kkc executable path inside RUNTIME, or nil."
  (cl-find-if
   #'file-executable-p
   (mapcar
    (lambda (name) (expand-file-name name runtime))
    (if (my-ime--windows-p)
        '("bin/kkc.exe")
      '("bin/kkc")))))

(defun my-ime--runtime-library-path (runtime)
  "Return the native library search path entries for RUNTIME."
  (let ((bin-path (expand-file-name "bin" runtime))
        (lib-path (expand-file-name "lib" runtime)))
    (if (my-ime--windows-p)
        (concat bin-path path-separator lib-path)
      lib-path)))

(defun my-ime--prepend-env-path (name prefix)
  "Return an environment assignment that prepends PREFIX to NAME."
  (let ((existing (getenv name)))
    (concat name "=" prefix
            (if (and existing (not (string-empty-p existing)))
                (concat path-separator existing)
              ""))))

(defun my-ime--runtime-env ()
  "Return process environment entries for the kkc runtime."
  (let* ((runtime (file-name-as-directory (expand-file-name my-ime-runtime-directory)))
         (kkc (my-ime--runtime-kkc-command runtime))
         (data-path (concat (expand-file-name "lib/libkkc" runtime)
                            path-separator
                            (expand-file-name "share/libkkc" runtime)))
         (library-path (my-ime--runtime-library-path runtime))
         (env nil))
    (when kkc
      (push (concat "MY_IME_KKC_COMMAND=" kkc) env)
      (push (concat "MY_IME_KKC_DATA_PATH=" data-path) env)
      (push (concat "MY_IME_KKC_LIBRARY_PATH=" library-path) env)
      (push (concat "MY_IME_KKC_DYLD_LIBRARY_PATH="
                    (expand-file-name "lib" runtime))
            env)
      (when (my-ime--windows-p)
        (push (my-ime--prepend-env-path "PATH" library-path) env)))
    env))

(defun my-ime--ensure-stdio-process ()
  "Start and return the my-ime stdio worker process."
  (if (and (process-live-p my-ime--stdio-process)
           (eq (process-status my-ime--stdio-process) 'run))
      my-ime--stdio-process
    (setq my-ime--stdio-partial "")
    (clrhash my-ime--stdio-pending)
    (let* ((buffer (get-buffer-create my-ime--stdio-buffer))
           (stderr-buffer (get-buffer-create my-ime--stdio-stderr-buffer))
           (default-directory (file-name-as-directory my-ime-project-root))
           (process-environment (append (my-ime--runtime-env) process-environment))
           (process
            (make-process
             :name "my-ime-stdio"
             :buffer buffer
             :stderr stderr-buffer
             :command (my-ime--stdio-command)
             :connection-type 'pipe
             :coding 'utf-8
             :filter #'my-ime--stdio-filter
             :sentinel #'my-ime--stdio-sentinel)))
      (set-process-query-on-exit-flag process nil)
      (setq my-ime--stdio-process process)
      process)))

(defun my-ime-stop-stdio-process ()
  "Stop the current my-ime stdio worker process."
  (interactive)
  (when (process-live-p my-ime--stdio-process)
    (delete-process my-ime--stdio-process))
  (setq my-ime--stdio-process nil)
  (clrhash my-ime--stdio-pending)
  (setq my-ime--stdio-partial ""))

(defun my-ime--stdio-sentinel (process event)
  "Reject pending stdio requests when PROCESS reports EVENT."
  (unless (process-live-p process)
    (let* ((stderr (when (get-buffer my-ime--stdio-stderr-buffer)
                     (with-current-buffer my-ime--stdio-stderr-buffer
                       (string-trim (buffer-string)))))
           (message (string-trim
                     (if (and stderr (not (string-empty-p stderr)))
                         (format "stdio process %s: %s" event stderr)
                       (format "stdio process %s" event)))))
      (maphash
       (lambda (_id callbacks)
         (let ((errback (plist-get callbacks :errback)))
           (when errback
             (funcall errback message))))
       my-ime--stdio-pending)
      (clrhash my-ime--stdio-pending)
      (when (eq process my-ime--stdio-process)
        (setq my-ime--stdio-process nil)))))

(defun my-ime--stdio-filter (_process output)
  "Handle stdio worker OUTPUT."
  (setq my-ime--stdio-partial (concat my-ime--stdio-partial output))
  (let ((lines (split-string my-ime--stdio-partial "\n")))
    (setq my-ime--stdio-partial (car (last lines)))
    (dolist (line (butlast lines))
      (setq line (string-trim line))
      (unless (string-empty-p line)
        (my-ime--handle-stdio-line line)))))

(defun my-ime--handle-stdio-line (line)
  "Dispatch one stdio response LINE."
  (condition-case err
      (let* ((json-object-type 'alist)
             (json-array-type 'list)
             (json-key-type 'symbol)
             (payload (json-read-from-string line))
             (id (alist-get 'id payload))
             (callbacks (gethash id my-ime--stdio-pending)))
        (when callbacks
          (remhash id my-ime--stdio-pending)
          (let ((error-message (alist-get 'error payload)))
            (if error-message
                (funcall (plist-get callbacks :errback) error-message)
              (funcall (plist-get callbacks :callback) payload)))))
    (error
     (message "my-ime: invalid stdio response: %s" (error-message-string err)))))

(defun my-ime--stdio-send-request
    (text callback errback &optional extra-metadata endpoint-path)
  "Send TEXT to the stdio worker and return the request id."
  (let* ((process (my-ime--ensure-stdio-process))
         (metadata (append (my-ime--metadata) extra-metadata))
         (id (cl-incf my-ime--stdio-next-id))
         (payload `((id . ,id)
                    (method . ,(my-ime--endpoint-method endpoint-path))
                    (text . ,text)
                    (metadata . ,metadata))))
    (puthash id (list :callback callback :errback errback) my-ime--stdio-pending)
    (condition-case err
        (process-send-string
         process
         (concat (encode-coding-string (json-encode payload) 'utf-8) "\n"))
      (error
       (remhash id my-ime--stdio-pending)
       (funcall errback (error-message-string err))))
    id))

(defun my-ime--stdio-request-payload (text &optional extra-metadata endpoint-path)
  "Synchronously request TEXT through the stdio worker."
  (let ((done nil)
        (result nil)
        (error-message nil)
        (deadline (+ (float-time) my-ime-timeout))
        (process nil)
        (request-id nil))
    (setq process
          (my-ime--ensure-stdio-process))
    (setq request-id
          (my-ime--stdio-send-request
           text
           (lambda (payload)
             (setq result payload
                   done t))
           (lambda (message)
             (setq error-message message
                   done t))
           extra-metadata
           endpoint-path))
    (while (and (not done) (< (float-time) deadline))
      (accept-process-output process 0.05))
    (unless done
      (remhash request-id my-ime--stdio-pending)
      (setq error-message (format "request timed out after %ss" my-ime-timeout)))
    (when error-message
      (error "my-ime: %s" error-message))
    result))

(defun my-ime--stdio-request-payload-async
    (text callback errback &optional extra-metadata endpoint-path)
  "Asynchronously request TEXT through the stdio worker."
  (let ((done nil)
        (request-id nil)
        (timeout-timer nil))
    (setq request-id
          (my-ime--stdio-send-request
           text
           (lambda (payload)
             (unless done
               (setq done t)
               (when timeout-timer
                 (cancel-timer timeout-timer))
               (funcall callback payload)))
           (lambda (message)
             (unless done
               (setq done t)
               (when timeout-timer
                 (cancel-timer timeout-timer))
               (funcall errback message)))
           extra-metadata
           endpoint-path))
    (setq timeout-timer
          (run-at-time
           my-ime-timeout nil
           (lambda ()
             (unless done
               (setq done t)
               (remhash request-id my-ime--stdio-pending)
               (funcall errback
                        (format "request timed out after %ss" my-ime-timeout))))))))

(defun my-ime--request (text &optional extra-metadata endpoint-path)
  "Synchronously convert TEXT using the configured local transport."
  (let* ((payload (my-ime--request-payload text extra-metadata endpoint-path))
         (converted (my-ime--payload-text payload)))
    converted))

(defun my-ime--request-payload (text &optional extra-metadata endpoint-path)
  "Synchronously request TEXT and return the decoded response payload."
  (if (eq my-ime-transport 'stdio)
      (my-ime--stdio-request-payload text extra-metadata endpoint-path)
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
            (my-ime--parse-response-payload-current-buffer))
        (kill-buffer buffer)))))

(defun my-ime--request-async (text callback errback &optional extra-metadata endpoint-path)
  "Asynchronously convert TEXT through the configured transport.
CALLBACK receives converted text.  ERRBACK receives an error string."
  (if (eq my-ime-transport 'stdio)
      (my-ime--stdio-request-payload-async
       text
       (lambda (payload)
         (condition-case err
             (funcall callback (my-ime--payload-text payload))
           (error (funcall errback (error-message-string err)))))
       errback
       extra-metadata
       endpoint-path)
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
        (funcall errback "request could not be started")))))

(defun my-ime--parse-response-current-buffer ()
  "Parse the current url response buffer and return converted text."
  (let* ((payload (my-ime--parse-response-payload-current-buffer))
         (converted (my-ime--payload-text payload)))
    converted))

(defun my-ime--payload-text (payload)
  "Return converted text from response PAYLOAD."
  (let ((converted (alist-get 'text payload)))
    (unless (stringp converted)
      (error "my-ime: response did not contain text"))
    converted))

(defun my-ime--parse-response-payload-current-buffer ()
  "Parse the current url response buffer and return its JSON payload."
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
      payload)))

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

(defun my-ime--replace-bounds-with-selected-candidate
    (beg end label &optional extra-metadata allow-unsafe)
  "Convert BEG END, let the user select a candidate, then replace it."
  (my-ime--ensure-safe-region beg end allow-unsafe)
  (let ((original (buffer-substring-no-properties beg end)))
    (when (string-empty-p original)
      (error "my-ime: empty %s" label))
    (message "my-ime: collecting %s candidates..." label)
    (let* ((metadata extra-metadata)
           (payload (my-ime--request-payload original metadata "/candidates"))
           (candidates (my-ime--payload-candidates payload))
           (candidates (delete-dups (copy-sequence candidates))))
      (cond
       ((null candidates)
        (error "my-ime: no candidates returned"))
       ((null (cdr candidates))
        (let ((converted (car candidates)))
          (my-ime--replace-region-preserve-point beg end converted)
          (my-ime--record-history original converted label metadata)
          (setq my-ime--suppress-next-ret-conversion t)
          (message "my-ime: selected %s" label)))
       ((my-ime--select-candidate-with-company
         beg end label metadata original candidates)
        nil)
       (t
       (let ((converted (my-ime--select-candidate candidates label)))
          (my-ime--replace-region-preserve-point beg end converted)
          (my-ime--record-history original converted label metadata)
          (setq my-ime--suppress-next-ret-conversion t)
          (message "my-ime: selected %s" label)))))))

(defun my-ime--payload-candidates (payload)
  "Return string candidates from a /candidates response PAYLOAD."
  (let* ((raw-candidates (alist-get 'candidates payload))
         (fallback (alist-get 'text payload))
         (candidates (if (listp raw-candidates)
                         (cl-remove-if-not #'stringp raw-candidates)
                       nil)))
    (cond
     (candidates candidates)
     ((stringp fallback) (list fallback))
     (t (error "my-ime: response did not contain candidates")))))

(defun my-ime--select-candidate (candidates label)
  "Select one string from CANDIDATES for LABEL."
  (let ((candidates (delete-dups (copy-sequence candidates))))
    (cond
     ((null candidates)
      (error "my-ime: no candidates returned"))
     ((null (cdr candidates))
      (car candidates))
     (t
      (completing-read
       (format "my-ime %s: " label)
       candidates nil t nil nil (car candidates))))))

(defun my-ime--select-candidate-with-company
    (beg end label metadata original candidates)
  "Use company to select one of CANDIDATES for ORIGINAL between BEG and END."
  (when (and (require 'company nil t)
             (fboundp 'company-begin-backend))
    (condition-case err
        (progn
          (my-ime--company-clear-state)
          (setq my-ime--company-candidates candidates
                my-ime--company-original original
                my-ime--company-label label
                my-ime--company-metadata metadata
                my-ime--company-beg-marker (copy-marker beg)
                my-ime--company-end-marker (copy-marker end t))
          (add-hook 'company-completion-cancelled-hook
                    #'my-ime--company-clear-state nil t)
          (unless (bound-and-true-p company-mode)
            (company-mode 1))
          (goto-char end)
          (company-begin-backend #'my-ime--company-backend)
          t)
      (error
       (my-ime--company-clear-state)
       (message "my-ime: company unavailable, falling back: %s"
                (error-message-string err))
       nil))))

(defun my-ime--company-backend (command &optional arg &rest _ignored)
  "Company backend for the current my-ime candidate set."
  (pcase command
    (`prefix
     (when (and my-ime--company-original
                (markerp my-ime--company-end-marker)
                (= (point) (marker-position my-ime--company-end-marker)))
       (list my-ime--company-original "" t)))
    (`candidates
     (ignore arg)
     my-ime--company-candidates)
    (`sorted t)
    (`duplicates t)
    (`no-cache t)
    (`annotation nil)
    (`post-completion
     (my-ime--company-finish arg))))

(defun my-ime--company-finish (candidate)
  "Record a company-selected my-ime CANDIDATE and clear transient state."
  (let ((original my-ime--company-original)
        (label my-ime--company-label)
        (metadata my-ime--company-metadata))
    (when (and original label)
      (my-ime--record-history original candidate label metadata)
      (setq my-ime--suppress-next-ret-conversion t)
      (message "my-ime: selected %s" label)))
  (my-ime--company-clear-state))

(defun my-ime--company-clear-state (&rest _ignored)
  "Clear transient company state for my-ime candidate selection."
  (when (boundp 'company-completion-cancelled-hook)
    (remove-hook 'company-completion-cancelled-hook
                 #'my-ime--company-clear-state t))
  (when (markerp my-ime--company-beg-marker)
    (set-marker my-ime--company-beg-marker nil))
  (when (markerp my-ime--company-end-marker)
    (set-marker my-ime--company-end-marker nil))
  (setq my-ime--company-candidates nil
        my-ime--company-original nil
        my-ime--company-label nil
        my-ime--company-metadata nil
        my-ime--company-beg-marker nil
        my-ime--company-end-marker nil))

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

(defun my-ime--live-after-change (_beg _end _len)
  "Refresh live conversion after a buffer change."
  (when (and my-ime-live-mode
             (not my-ime--live-inhibit-after-change))
    (my-ime--live-clear)
    (my-ime--live-schedule-refresh)))

(defun my-ime--live-cancel-timer ()
  "Cancel the pending live refresh timer."
  (when (timerp my-ime--live-timer)
    (cancel-timer my-ime--live-timer))
  (setq my-ime--live-timer nil))

(defun my-ime--live-schedule-refresh ()
  "Schedule a live conversion refresh for the current buffer."
  (when (and my-ime-live-mode
             (not (minibufferp))
             (not buffer-read-only))
    (my-ime--live-cancel-timer)
    (cl-incf my-ime--live-sequence)
    (let ((buffer (current-buffer))
          (sequence my-ime--live-sequence))
      (setq my-ime--live-timer
            (run-with-idle-timer
             my-ime-live-idle-delay nil
             (lambda ()
               (when (buffer-live-p buffer)
                 (with-current-buffer buffer
                   (when (and my-ime-live-mode
                              (= sequence my-ime--live-sequence))
                     (my-ime--live-refresh sequence))))))))))

(defun my-ime--live-refresh (sequence)
  "Request and render a live conversion for SEQUENCE."
  (setq my-ime--live-timer nil)
  (let ((bounds (my-ime--live-bounds)))
    (when bounds
      (let* ((beg (car bounds))
             (end (cdr bounds))
             (original (buffer-substring-no-properties beg end))
             (metadata `((trigger . "live-preview")
                         (sequence . ,sequence)))
             (beg-marker (copy-marker beg))
             (end-marker (copy-marker end t))
             (source-buffer (current-buffer)))
        (my-ime--request-async
         original
         (lambda (converted)
           (my-ime--live-handle-response
            source-buffer sequence beg-marker end-marker original converted
            metadata my-ime-live-preview-endpoint))
         (lambda (message)
           (set-marker beg-marker nil)
           (set-marker end-marker nil)
           (when (buffer-live-p source-buffer)
             (with-current-buffer source-buffer
               (when (= sequence my-ime--live-sequence)
                 (message "my-ime: live preview skipped: %s" message)))))
         metadata
         my-ime-live-preview-endpoint)))))

(defun my-ime--live-handle-response
    (source-buffer sequence beg-marker end-marker original converted metadata endpoint)
  "Apply a live conversion response if it still matches the current buffer."
  (if (not (buffer-live-p source-buffer))
      (progn
        (set-marker beg-marker nil)
        (set-marker end-marker nil))
    (with-current-buffer source-buffer
      (unwind-protect
          (when (and my-ime-live-mode
                     (= sequence my-ime--live-sequence)
                     (markerp beg-marker)
                     (markerp end-marker))
            (let ((beg (marker-position beg-marker))
                  (end (marker-position end-marker)))
              (when (and beg end
                         (<= beg end)
                         (string= original
                                  (buffer-substring-no-properties beg end)))
                (my-ime--live-render beg end original converted metadata endpoint))))
        (set-marker beg-marker nil)
        (set-marker end-marker nil)))))

(defun my-ime--live-render (beg end original converted metadata endpoint)
  "Render CONVERTED as a live preview for ORIGINAL between BEG and END."
  (my-ime--live-clear)
  (unless (string= original converted)
    (let ((overlay (make-overlay beg end nil nil t)))
      (overlay-put overlay 'evaporate t)
      (overlay-put overlay 'display
                   (propertize converted
                               'face 'my-ime-live-preview-face))
      (overlay-put overlay 'help-echo original)
      (setq my-ime--live-overlay overlay
            my-ime--live-state
            `((beg_marker . ,(copy-marker beg))
              (end_marker . ,(copy-marker end t))
              (original . ,original)
              (converted . ,converted)
              (metadata . ,metadata)
              (endpoint . ,endpoint))))))

(defun my-ime--live-clear ()
  "Clear the live conversion overlay and state."
  (when (overlayp my-ime--live-overlay)
    (delete-overlay my-ime--live-overlay))
  (setq my-ime--live-overlay nil)
  (when my-ime--live-state
    (let ((beg-marker (alist-get 'beg_marker my-ime--live-state))
          (end-marker (alist-get 'end_marker my-ime--live-state)))
      (when (markerp beg-marker)
        (set-marker beg-marker nil))
      (when (markerp end-marker)
        (set-marker end-marker nil))))
  (setq my-ime--live-state nil))

(defun my-ime--live-bounds ()
  "Return bounds suitable for a live conversion preview."
  (when (and my-ime-live-mode
             (not (minibufferp))
             (not buffer-read-only)
             (not (use-region-p)))
    (let* ((raw-bounds (my-ime--last-sentence-bounds))
           (bounds (and raw-bounds
                        (my-ime--auto-conversion-bounds
                         (car raw-bounds) (cdr raw-bounds)))))
      (when bounds
        (let ((text (buffer-substring-no-properties
                     (car bounds) (cdr bounds))))
          (when (and (>= (length (string-trim text)) my-ime-live-min-chars)
                     (my-ime--auto-convertible-text-p text))
            bounds))))))

(defun my-ime--live-valid-state ()
  "Return current live state if it still matches the buffer."
  (when my-ime--live-state
    (let* ((beg-marker (alist-get 'beg_marker my-ime--live-state))
           (end-marker (alist-get 'end_marker my-ime--live-state))
           (original (alist-get 'original my-ime--live-state))
           (beg (and (markerp beg-marker) (marker-position beg-marker)))
           (end (and (markerp end-marker) (marker-position end-marker))))
      (when (and beg end
                 (<= beg end)
                 (string= original
                          (buffer-substring-no-properties beg end)))
        my-ime--live-state))))

(defun my-ime--live-commit-state (state)
  "Commit live conversion STATE and return non-nil."
  (let* ((beg-marker (alist-get 'beg_marker state))
         (end-marker (alist-get 'end_marker state))
         (original (alist-get 'original state))
         (converted (alist-get 'converted state))
         (metadata (alist-get 'metadata state))
         (beg (marker-position beg-marker))
         (end (marker-position end-marker)))
    (let ((my-ime--live-inhibit-after-change t))
      (my-ime--live-clear)
      (my-ime--replace-region-preserve-point beg end converted))
    (my-ime--record-history original converted "live" metadata)
    t))

;;;###autoload
(defun my-ime-live-commit ()
  "Commit the current live conversion preview."
  (interactive)
  (my-ime--live-cancel-timer)
  (or (let ((state (my-ime--live-valid-state)))
        (and state (my-ime--live-commit-state state)))
      (progn
        (my-ime--live-clear)
        nil)))

;;;###autoload
(defun my-ime-live-commit-and-newline ()
  "Commit the current live conversion preview, then insert a newline."
  (interactive)
  (let ((my-ime--live-inhibit-after-change t))
    (my-ime-live-commit)
    (newline-and-indent)))

;;;###autoload
(defun my-ime-live-select-candidate ()
  "Select a candidate for the current live conversion bounds."
  (interactive)
  (my-ime--live-cancel-timer)
  (let* ((state (my-ime--live-valid-state))
         (bounds (if state
                     (cons (marker-position
                            (alist-get 'beg_marker state))
                           (marker-position
                            (alist-get 'end_marker state)))
                   (my-ime--live-bounds))))
    (my-ime--live-clear)
    (if bounds
        (my-ime--replace-bounds-with-selected-candidate
         (car bounds) (cdr bounds) "live" nil t)
      (my-ime-select-candidate-dwim))))

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

(defconst my-ime--romaji-kana-table
  '(("a" . "あ") ("i" . "い") ("u" . "う") ("e" . "え") ("o" . "お")
    ("ka" . "か") ("ki" . "き") ("ku" . "く") ("ke" . "け") ("ko" . "こ")
    ("kya" . "きゃ") ("kyu" . "きゅ") ("kyo" . "きょ")
    ("ga" . "が") ("gi" . "ぎ") ("gu" . "ぐ") ("ge" . "げ") ("go" . "ご")
    ("gya" . "ぎゃ") ("gyu" . "ぎゅ") ("gyo" . "ぎょ")
    ("sa" . "さ") ("si" . "し") ("shi" . "し") ("su" . "す") ("se" . "せ") ("so" . "そ")
    ("sya" . "しゃ") ("sha" . "しゃ") ("syu" . "しゅ") ("shu" . "しゅ") ("syo" . "しょ") ("sho" . "しょ")
    ("za" . "ざ") ("zi" . "じ") ("ji" . "じ") ("zu" . "ず") ("ze" . "ぜ") ("zo" . "ぞ")
    ("zya" . "じゃ") ("ja" . "じゃ") ("zyu" . "じゅ") ("ju" . "じゅ") ("zyo" . "じょ") ("jo" . "じょ")
    ("ta" . "た") ("ti" . "ち") ("chi" . "ち") ("tu" . "つ") ("tsu" . "つ") ("te" . "て") ("to" . "と")
    ("tya" . "ちゃ") ("cha" . "ちゃ") ("tyu" . "ちゅ") ("chu" . "ちゅ") ("tyo" . "ちょ") ("cho" . "ちょ")
    ("da" . "だ") ("di" . "ぢ") ("du" . "づ") ("de" . "で") ("do" . "ど")
    ("dya" . "ぢゃ") ("dyu" . "ぢゅ") ("dyo" . "ぢょ")
    ("na" . "な") ("ni" . "に") ("nu" . "ぬ") ("ne" . "ね") ("no" . "の")
    ("nya" . "にゃ") ("nyu" . "にゅ") ("nyo" . "にょ")
    ("ha" . "は") ("hi" . "ひ") ("hu" . "ふ") ("fu" . "ふ") ("he" . "へ") ("ho" . "ほ")
    ("fa" . "ふぁ") ("fi" . "ふぃ") ("fe" . "ふぇ") ("fo" . "ふぉ")
    ("hya" . "ひゃ") ("hyu" . "ひゅ") ("hyo" . "ひょ")
    ("ba" . "ば") ("bi" . "び") ("bu" . "ぶ") ("be" . "べ") ("bo" . "ぼ")
    ("bya" . "びゃ") ("byu" . "びゅ") ("byo" . "びょ")
    ("pa" . "ぱ") ("pi" . "ぴ") ("pu" . "ぷ") ("pe" . "ぺ") ("po" . "ぽ")
    ("pya" . "ぴゃ") ("pyu" . "ぴゅ") ("pyo" . "ぴょ")
    ("ma" . "ま") ("mi" . "み") ("mu" . "む") ("me" . "め") ("mo" . "も")
    ("mya" . "みゃ") ("myu" . "みゅ") ("myo" . "みょ")
    ("ya" . "や") ("yu" . "ゆ") ("yo" . "よ")
    ("ra" . "ら") ("ri" . "り") ("ru" . "る") ("re" . "れ") ("ro" . "ろ")
    ("rya" . "りゃ") ("ryu" . "りゅ") ("ryo" . "りょ")
    ("wa" . "わ") ("wi" . "うぃ") ("we" . "うぇ") ("wo" . "を")
    ("va" . "ゔぁ") ("vi" . "ゔぃ") ("vu" . "ゔ") ("ve" . "ゔぇ") ("vo" . "ゔぉ")
    ("la" . "ぁ") ("li" . "ぃ") ("lu" . "ぅ") ("le" . "ぇ") ("lo" . "ぉ")
    ("xa" . "ぁ") ("xi" . "ぃ") ("xu" . "ぅ") ("xe" . "ぇ") ("xo" . "ぉ")
    ("ltu" . "っ") ("xtu" . "っ"))
  "Romaji to hiragana table used by local eager kana conversion.")

(defun my-ime--local-kana-post-self-insert ()
  "Convert a completed romaji suffix before point to kana."
  (when (and my-ime-eager-local-kana
             (characterp last-command-event)
             (not (minibufferp))
             (not buffer-read-only)
             (not (my-ime--inside-manual-term-marker-p))
             (not (my-ime--org-todo-keyword-prefix-at-point-p)))
    (if (eq last-command-event ?-)
        (my-ime--restore-local-kana-before-hyphen)
      (let ((bounds (my-ime--romaji-suffix-bounds)))
        (when bounds
          (let* ((beg (car bounds))
                 (end (cdr bounds))
                 (source (buffer-substring-no-properties beg end))
                 (replacement (my-ime--romaji-suffix-to-kana source)))
            (when replacement
              (my-ime--replace-local-kana-region beg end source replacement))))))))

(defun my-ime--short-kana-post-self-insert ()
  "Convert a small lowercase romaji window before point to kana."
  (when (and (not my-ime-eager-local-kana)
             (integerp my-ime-eager-short-kana-chars)
             (> my-ime-eager-short-kana-chars 0)
             (characterp last-command-event)
             (not (minibufferp))
             (not buffer-read-only)
             (not (memq last-command-event my-ime-eager-trigger-chars))
             (not (my-ime--inside-manual-term-marker-p))
             (not (my-ime--org-todo-keyword-prefix-at-point-p)))
    (if (eq last-command-event ?-)
        (my-ime--short-kana-finalize-before-hyphen)
      (let ((bounds (my-ime--short-kana-bounds)))
        (when bounds
          (let* ((beg (car bounds))
                 (end (cdr bounds))
                 (source (buffer-substring-no-properties beg end))
                 (replacement (my-ime--plain-romaji-to-kana source)))
            (when replacement
              (my-ime--replace-local-kana-region beg end source replacement))))))))

(defun my-ime--short-kana-finalize-before-hyphen ()
  "Reconvert a partially kanaized romaji word before a trailing hyphen."
  (let ((word (my-ime--short-kana-word-before-hyphen)))
    (when word
      (let* ((beg (car word))
             (source (cdr word))
             (replacement (my-ime--romaji-suffix-to-kana (concat source "-"))))
        (when replacement
          (delete-region beg (point))
          (insert (propertize replacement 'my-ime-romaji-source
                              (concat source "-"))))))))

(defun my-ime--short-kana-word-before-hyphen ()
  "Return (BEG . SOURCE) for romaji plus local kana before inserted hyphen."
  (let ((pos (1- (point)))
        (beg (1- (point)))
        (source ""))
    (while (> pos (line-beginning-position))
      (let* ((prev (1- pos))
             (romaji-source (get-text-property prev 'my-ime-romaji-source))
             (char (char-after prev)))
        (cond
         (romaji-source
          (let ((chunk-beg prev))
            (while (and (> chunk-beg (line-beginning-position))
                        (equal (get-text-property (1- chunk-beg)
                                                  'my-ime-romaji-source)
                               romaji-source))
              (setq chunk-beg (1- chunk-beg)))
            (setq source (concat romaji-source source)
                  beg chunk-beg
                  pos chunk-beg)))
         ((and char (>= char ?a) (<= char ?z))
          (setq source (concat (char-to-string char) source)
                beg prev
                pos prev))
         (t
          (setq pos (line-beginning-position))))))
    (when (>= (length source) 3)
      (cons beg source))))

(defun my-ime--short-kana-bounds ()
  "Return bounds for the short romaji window before point."
  (let ((end (point))
        (beg (point))
        (line-beg (line-beginning-position))
        (chars my-ime-eager-short-kana-chars))
    (when (not (get-text-property (1- end) 'my-ime-romaji-source))
      (while (and (> beg line-beg)
                  (< (- end beg) chars)
                  (let ((char (char-before beg)))
                    (and (>= char ?a) (<= char ?z))))
        (setq beg (1- beg)))
      (when (and (<= 3 (- end beg))
                 (<= (- end beg) chars))
        (cons beg end)))))

(defun my-ime--replace-local-kana-region (beg end source replacement)
  "Replace BEG END with local kana REPLACEMENT tagged with SOURCE."
  (my-ime--replace-region-preserve-point
   beg end
   (propertize replacement 'my-ime-romaji-source source)))

(defun my-ime--restore-local-kana-before-hyphen ()
  "Restore locally converted kana before an inserted hyphen."
  (let* ((hyphen-pos (1- (point)))
         (kana-pos (1- hyphen-pos))
         (source (and (>= kana-pos (point-min))
                      (get-text-property kana-pos 'my-ime-romaji-source))))
    (when source
      (let ((beg kana-pos))
        (while (and (> beg (point-min))
                    (equal (get-text-property (1- beg) 'my-ime-romaji-source)
                           source))
          (setq beg (1- beg)))
        (delete-region beg hyphen-pos)
        (goto-char beg)
        (insert source)
        (goto-char (+ beg (length source) 1))))))

(defun my-ime--inside-manual-term-marker-p ()
  "Return non-nil when point is inside an unclosed ;; manual term marker."
  (= 1 (% (my-ime--count-substring
           (buffer-substring-no-properties (line-beginning-position) (point))
           ";;")
          2)))

(defun my-ime--org-todo-keywords ()
  "Return configured org TODO keywords."
  (let ((keywords (or (bound-and-true-p org-todo-keywords-1)
                      '("TODO" "DONE"))))
    (delete-dups
     (cl-remove-if-not
      #'stringp
      (copy-sequence keywords)))))

(defun my-ime--org-todo-keyword-p (token)
  "Return non-nil when TOKEN is an org TODO keyword."
  (let ((keywords (my-ime--org-todo-keywords)))
    (or (member token keywords)
        (member (upcase token) keywords))))

(defun my-ime--org-todo-keyword-prefix-at-point-p ()
  "Return non-nil when point is in an org TODO keyword slot."
  (and my-ime-org-aware
       (derived-mode-p 'org-mode)
       (save-excursion
         (let ((point-at-call (point)))
           (beginning-of-line)
           (when (looking-at "\\s-*\\*+\\s-+\\([^ \t\n]*\\)")
             (let* ((token-beg (match-beginning 1))
                    (token-end (match-end 1))
                    (token (buffer-substring-no-properties
                            token-beg
                            (min point-at-call token-end))))
               (and (<= token-beg point-at-call)
                    (<= point-at-call token-end)
                    (not (string-empty-p token))
                    (cl-some
                     (lambda (keyword)
                       (string-prefix-p (upcase token) (upcase keyword)))
                     (my-ime--org-todo-keywords)))))))))

(defun my-ime--romaji-suffix-bounds ()
  "Return the romaji suffix bounds before point, capped to a small IME window."
  (let ((end (point))
        (beg (point)))
    (while (and (> beg (line-beginning-position))
                (let ((char (char-before beg)))
                  (or (and (>= char ?A) (<= char ?Z))
                      (and (>= char ?a) (<= char ?z))
                      (= char ?-)
                      (= char ?'))))
      (setq beg (1- beg)))
    (when (< beg end)
      (cons (max beg (- end 12)) end))))

(defun my-ime--romaji-suffix-to-kana (source)
  "Return kana replacement for completed romaji SOURCE, or nil to wait."
  (let* ((lower (downcase source))
         (len (length lower)))
    (cond
     ((string= lower "n'")
      "ん")
     ((and (>= len 3)
           (string-prefix-p "nn" lower)
           (cdr (assoc (substring lower 1) my-ime--romaji-kana-table)))
      (concat "ん" (cdr (assoc (substring lower 1) my-ime--romaji-kana-table))))
     ((and (= len 2)
           (string= (substring lower 0 1) "n")
           (not (string= (substring lower 1 2) "n"))
           (not (string-match-p "[aeiouy]" (substring lower 1 2))))
      (concat "ん" (substring source 1 2)))
     ((and (= len 2)
           (string= (substring lower 0 1) (substring lower 1 2))
           (not (string-match-p "[aeioun]" (substring lower 0 1))))
      (concat "っ" (substring source 1 2)))
     ((and (string-search "-" lower)
           (my-ime--hyphenated-romaji-p lower))
      (my-ime--hyphenated-romaji-to-kana lower))
     ((and (string-suffix-p "-" lower)
           (> len 1))
      (let ((base (my-ime--plain-romaji-to-kana
                   (substring lower 0 (1- len)))))
        (when base
          (concat base "ー"))))
     ((cdr (assoc lower my-ime--romaji-kana-table))))))

(defun my-ime--hyphenated-romaji-p (source)
  "Return non-nil when SOURCE is a small hyphenated romaji word."
  (and (string-match-p "\\`[a-z]+\\(?:-[a-z]+\\)+\\'" source)
       (<= (length source) 12)))

(defun my-ime--hyphenated-romaji-to-kana (source)
  "Convert hyphenated romaji SOURCE to kana, treating hyphen as long mark."
  (let ((parts (split-string source "-"))
        (converted nil))
    (catch 'failed
      (setq converted
            (mapcar (lambda (part)
                      (or (my-ime--plain-romaji-to-kana part)
                          (throw 'failed nil)))
                    parts))
      (mapconcat #'identity converted "ー"))))

(defun my-ime--plain-romaji-to-kana (source)
  "Convert a complete non-hyphenated romaji SOURCE to kana, or nil."
  (let ((cursor 0)
        (lower (downcase source))
        (result '()))
    (catch 'failed
      (while (< cursor (length lower))
        (let ((converted nil))
          (catch 'matched
            (dolist (width '(3 2 1))
              (let* ((end (min (length lower) (+ cursor width)))
                     (chunk (substring lower cursor end))
                     (kana (cdr (assoc chunk my-ime--romaji-kana-table))))
                (when (and (= (- end cursor) width) kana)
                  (push kana result)
                  (setq cursor end
                        converted t)
                  (throw 'matched t)))))
          (unless converted
            (throw 'failed nil))))
      (mapconcat #'identity (nreverse result) ""))))

(defun my-ime--auto-convertible-text-p (text)
  "Return non-nil when TEXT looks worth auto-converting."
  (and (>= (length (string-trim text)) my-ime-eager-min-chars)
       (string-match-p "[[:alpha:]ぁ-んァ-ン一-龯々〆〤]" text)
       (my-ime--manual-term-markers-balanced-p text)))

(defun my-ime--auto-conversion-bounds (beg end)
  "Return adjusted bounds for eager conversion, or nil when suppressed."
  (let* ((bounds (if (and my-ime-org-aware
                          my-ime-eager-org-syntax-guard
                          (derived-mode-p 'org-mode))
                     (my-ime--org-adjust-auto-conversion-bounds beg end)
                   (cons beg end)))
         (bounds (and bounds
                      (my-ime--space-preedit-after-manual-term-bounds
                       (car bounds) (cdr bounds)))))
    (when (and bounds
               (< (car bounds) (cdr bounds))
               (not (my-ime--auto-conversion-suppressed-p (car bounds) (cdr bounds))))
      bounds)))

(defun my-ime--auto-conversion-suppressed-p (beg end)
  "Return non-nil when auto-conversion should not touch BEG to END."
  (and my-ime-org-aware
       my-ime-eager-org-syntax-guard
       (derived-mode-p 'org-mode)
       (my-ime--org-auto-conversion-suppressed-p beg end)))

(defun my-ime--org-auto-conversion-suppressed-p (beg end)
  "Return non-nil when org syntax in BEG to END should block eager conversion."
  (or (my-ime--region-has-line-p beg end "\\s-*\\(?:CLOSED:\\|DEADLINE:\\|SCHEDULED:\\)")
      (my-ime--org-unsafe-region-p beg end)))

(defun my-ime--org-adjust-auto-conversion-bounds (beg end)
  "Trim org headline prefix from BEG to END for eager conversion."
  (save-excursion
    (goto-char beg)
    (if (looking-at "\\s-*\\*+\\s-+")
        (let ((adjusted-beg (match-end 0)))
          (goto-char adjusted-beg)
          (when (looking-at "\\([^ \t\n]+\\)\\([ \t]+\\|\\'\\)")
            (let ((token (match-string-no-properties 1)))
              (when (my-ime--org-todo-keyword-p token)
                (setq adjusted-beg (match-end 0)))))
          (cons adjusted-beg end))
      (cons beg end))))

(defun my-ime--space-preedit-after-manual-term-bounds (beg end)
  "Trim manual-term prefix from BEG to END during space preedit."
  (if (not (and my-ime-eager-space-preedit
                (eq last-command-event ?\s)))
      (cons beg end)
    (let* ((text (buffer-substring-no-properties beg end))
           (start 0)
           (last-end nil))
      (while (string-match ";;[^;\n]+;;[ \t]*" text start)
        (setq last-end (match-end 0)
              start (match-end 0)))
      (if last-end
          (cons (+ beg last-end) end)
        (cons beg end)))))

(defun my-ime--eager-endpoint-path ()
  "Return the conversion endpoint path for the current eager trigger."
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
             (not (minibufferp))
             (not buffer-read-only))
    (my-ime--local-kana-post-self-insert)
    (my-ime--short-kana-post-self-insert)
    (when (memq last-command-event my-ime-eager-trigger-chars)
      (let* ((raw-bounds (my-ime--last-sentence-bounds))
             (bounds (my-ime--auto-conversion-bounds (car raw-bounds) (cdr raw-bounds))))
        (when bounds
          (let* ((beg (car bounds))
                 (end (cdr bounds))
                 (text (buffer-substring-no-properties beg end)))
            (when (my-ime--auto-convertible-text-p text)
              (condition-case err
                  (my-ime--replace-bounds-async
                   beg end (my-ime--eager-label)
                   `((trigger . ,(if (eq last-command-event ?\s)
                                     "eager-space"
                                   "eager-punctuation")))
                   nil nil
                   (my-ime--eager-endpoint-path))
                (error (message "my-ime: eager conversion skipped: %s"
                                (error-message-string err)))))))))))

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
      (goto-char beg)
      (when (looking-at "\\([^ \t\n]+\\)\\([ \t]+\\|\\'\\)")
        (let ((token (match-string-no-properties 1)))
          (when (my-ime--org-todo-keyword-p token)
            (setq beg (match-end 0)))))
      (cons beg (or tag line-end)))))

(defun my-ime--select-last-sentence-bounds ()
  "Return bounds for candidate selection at point."
  (if (and my-ime-org-aware
           (derived-mode-p 'org-mode)
           (save-excursion
             (beginning-of-line)
             (looking-at-p "\\s-*\\*+\\s-+")))
      (my-ime--org-headline-text-bounds)
    (my-ime--last-sentence-bounds)))

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
(defun my-ime-select-region-candidate (beg end)
  "Convert the selected region and choose from sentence candidates."
  (interactive "r")
  (unless (use-region-p)
    (error "my-ime: no active region"))
  (my-ime--replace-bounds-with-selected-candidate beg end "region" nil t))

;;;###autoload
(defun my-ime-select-last-sentence-candidate ()
  "Convert the sentence ending at point and choose from candidates."
  (interactive)
  (let ((bounds (my-ime--select-last-sentence-bounds)))
    (my-ime--replace-bounds-with-selected-candidate
     (car bounds) (cdr bounds) "sentence")))

;;;###autoload
(defun my-ime-select-candidate-dwim ()
  "Convert active region, or sentence at point, with candidate selection."
  (interactive)
  (if (use-region-p)
      (my-ime-select-region-candidate (region-beginning) (region-end))
    (my-ime-select-last-sentence-candidate)))

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
  (if my-ime--suppress-next-ret-conversion
      (progn
        (setq my-ime--suppress-next-ret-conversion nil)
        (newline-and-indent))
    (if (and my-ime-c-j-org-only
             (not (derived-mode-p 'org-mode)))
      (newline-and-indent)
      (let* ((raw-bounds (my-ime--current-line-before-point-bounds))
             (bounds (my-ime--auto-conversion-bounds (car raw-bounds) (cdr raw-bounds))))
        (when bounds
          (let* ((beg (car bounds))
                 (end (cdr bounds))
                 (text (buffer-substring-no-properties beg end)))
            (when (my-ime--auto-convertible-text-p text)
              (condition-case err
                  (my-ime--replace-bounds-async
                   beg end "line" '((trigger . "line-newline")) nil t)
                (error (message "my-ime: line conversion skipped: %s"
                                (error-message-string err)))))))
        (newline-and-indent)))))

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
