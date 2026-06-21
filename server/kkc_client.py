"""Client for the external kkc decoder command."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import threading

from .config import env


class KkcError(RuntimeError):
    """Raised when kkc conversion fails."""


SEGMENT_RE = re.compile(r"<([^<>/]*)/[^<>]*>")
CANDIDATE_LINE_RE = re.compile(r"^(?:>>\s*)?\d+:\s*(.*)$")
TECH_PLACEHOLDER_RE = re.compile(r"<TECH_(\d+)>")
KKC_PLACEHOLDER_RE = re.compile(r"\|\|\|TECH_(\d+)\|\|\|")


class KkcClient:
    """Long-lived ``kkc decoder`` subprocess."""

    def __init__(self, command: str | None = None, model: str | None = None) -> None:
        self.command = command or find_kkc_command()
        self.model = model or env("KKC_MODEL", "sorted3")
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def convert(self, hiragana_text: str) -> str:
        """Convert hiragana text containing placeholders to kana-kanji text."""

        return self.convert_candidates(hiragana_text, nbest=1)[0]

    def convert_candidates(self, hiragana_text: str, nbest: int = 3) -> list[str]:
        """Return up to NBEST kana-kanji candidates for hiragana text."""

        kkc_input = _to_kkc_placeholders(hiragana_text)
        if not kkc_input.strip():
            return [hiragana_text]
        nbest = max(1, nbest)
        request_text = kkc_input if nbest == 1 else f"{kkc_input} {nbest}"
        lines: list[str] = []
        with self._lock:
            process = self._ensure_process()
            assert process.stdin is not None
            assert process.stdout is not None
            try:
                process.stdin.write(request_text + "\n")
                process.stdin.flush()
                lines = _read_kkc_lines(process, nbest)
            except OSError as exc:
                self.close()
                raise KkcError(f"kkc decoder failed: {exc}") from exc
            if len(lines) < nbest:
                self.close()
            if not lines:
                stderr = ""
                if process.stderr is not None:
                    try:
                        stderr = process.stderr.read()
                    except OSError:
                        stderr = ""
                self.close()
                raise KkcError(f"kkc decoder stopped unexpectedly: {stderr.strip()}")
        converted = [parse_kkc_line(line) for line in lines]
        return [_from_kkc_placeholders(candidate) for candidate in converted]

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=1)
        except Exception:
            process.kill()
        finally:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        env = _kkc_env(self.command)
        try:
            process = subprocess.Popen(
                [self.command, "decoder", "-m", self.model],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1,
            )
        except OSError as exc:
            raise KkcError(f"could not start kkc decoder: {exc}") from exc
        assert process.stdout is not None
        headers = [process.stdout.readline(), process.stdout.readline()]
        if not all(headers):
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise KkcError(f"kkc decoder did not start: {stderr.strip()}")
        self._process = process
        return process


_GLOBAL_CLIENT: KkcClient | None = None
_GLOBAL_LOCK = threading.Lock()


def convert_hiragana_with_kkc(text: str) -> str:
    """Convert hiragana text through a shared kkc decoder process."""

    global _GLOBAL_CLIENT
    with _GLOBAL_LOCK:
        if _GLOBAL_CLIENT is None:
            _GLOBAL_CLIENT = KkcClient()
        client = _GLOBAL_CLIENT
    return client.convert(text)


def _read_kkc_lines(process: subprocess.Popen[str], nbest: int) -> list[str]:
    """Read up to NBEST candidate lines without blocking forever."""

    assert process.stdout is not None
    lines: list[str] = []

    def reader() -> None:
        while len(lines) < nbest:
            line = process.stdout.readline()
            if not line:
                break
            if line.strip() == ">>":
                continue
            lines.append(line)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(_kkc_read_timeout())
    return lines


def _kkc_read_timeout() -> float:
    raw = env("KKC_READ_TIMEOUT", "2.0")
    try:
        return max(0.05, float(raw))
    except ValueError:
        return 2.0


def convert_hiragana_candidates_with_kkc(text: str, nbest: int = 3) -> list[str]:
    """Return kana-kanji candidates through a shared kkc decoder process."""

    global _GLOBAL_CLIENT
    with _GLOBAL_LOCK:
        if _GLOBAL_CLIENT is None:
            _GLOBAL_CLIENT = KkcClient()
        client = _GLOBAL_CLIENT
    return client.convert_candidates(text, nbest=nbest)


def find_kkc_command() -> str:
    """Return the configured or discovered kkc command path."""

    configured = env("KKC_COMMAND")
    if configured:
        return configured
    local_probe = Path("/tmp/libkkc-install/bin/kkc")
    if local_probe.exists():
        return str(local_probe)
    found = shutil.which("kkc")
    if found:
        return found
    raise KkcError("kkc command not found; set MY_IME_KKC_COMMAND")


def kkc_available() -> bool:
    """Return whether a kkc command can be discovered."""

    try:
        find_kkc_command()
    except KkcError:
        return False
    return True


def parse_kkc_line(line: str) -> str:
    """Parse one ``kkc decoder`` result line into plain text."""

    match = CANDIDATE_LINE_RE.match(line.strip())
    if match is None:
        raise KkcError(f"kkc decoder returned unexpected line: {line.rstrip()}")
    payload = match.group(1)
    segments = SEGMENT_RE.findall(payload)
    if not segments:
        raise KkcError(f"kkc decoder returned no segments: {line.rstrip()}")
    return "".join(segments)


def _to_kkc_placeholders(text: str) -> str:
    return TECH_PLACEHOLDER_RE.sub(r"|||TECH_\1|||", text)


def _from_kkc_placeholders(text: str) -> str:
    return KKC_PLACEHOLDER_RE.sub(r"<TECH_\1>", text)


def _kkc_env(command: str) -> dict[str, str]:
    process_env = os.environ.copy()
    configured = env("KKC_DYLD_LIBRARY_PATH")
    if configured:
        process_env["DYLD_LIBRARY_PATH"] = configured
    elif command == "/tmp/libkkc-install/bin/kkc":
        existing = process_env.get("DYLD_LIBRARY_PATH", "")
        prefix = "/tmp/libkkc-install/lib:/opt/homebrew/lib"
        process_env["DYLD_LIBRARY_PATH"] = prefix if not existing else prefix + ":" + existing
    return process_env
