"""Client for the external kkc decoder command."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
    bundled_probe = _bundled_kkc_command()
    if bundled_probe is not None:
        return str(bundled_probe)
    if os.name != "nt":
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
    data_path = env("KKC_DATA_PATH")
    if data_path:
        process_env["KKC_DATA_PATH"] = data_path
    else:
        bundled_data_path = _bundled_kkc_data_path()
        if bundled_data_path:
            process_env["KKC_DATA_PATH"] = bundled_data_path
    library_env_name = _library_env_name()
    configured = env("KKC_LIBRARY_PATH") or env("KKC_DYLD_LIBRARY_PATH")
    if configured:
        _prepend_path(process_env, library_env_name, configured)
    else:
        runtime_dir = _runtime_dir_for_command(command)
        if runtime_dir is not None:
            _prepend_runtime_library_path(process_env, runtime_dir)
        elif command == "/tmp/libkkc-install/bin/kkc":
            _prepend_path(process_env, library_env_name, "/tmp/libkkc-install/lib")
            if sys.platform == "darwin":
                _prepend_path(process_env, library_env_name, "/opt/homebrew/lib")
    return process_env


def _bundled_runtime_dir() -> Path:
    return Path(__file__).resolve().parent.parent / ".deps" / "kkc-runtime" / "current"


def _bundled_kkc_command() -> Path | None:
    runtime_dir = _bundled_runtime_dir()
    for name in _kkc_command_names():
        candidate = runtime_dir / "bin" / name
        if candidate.exists():
            return candidate
    return None


def _kkc_command_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("kkc.exe",)
    return ("kkc",)


def _bundled_kkc_data_path() -> str:
    runtime_dir = _bundled_runtime_dir()
    model_dir = runtime_dir / "lib" / "libkkc" / "models"
    if not model_dir.exists():
        return ""
    return os.pathsep.join(
        [
            str(runtime_dir / "lib" / "libkkc"),
            str(runtime_dir / "share" / "libkkc"),
        ]
    )


def _runtime_dir_for_command(command: str) -> Path | None:
    command_path = Path(command)
    if command_path.name.lower() not in {"kkc", "kkc.exe"}:
        return None
    if command_path.parent.name != "bin":
        return None
    return command_path.parent.parent


def _prepend_runtime_library_path(process_env: dict[str, str], runtime_dir: Path) -> None:
    if os.name == "nt":
        _prepend_path(
            process_env,
            "PATH",
            _join_paths([runtime_dir / "bin", runtime_dir / "lib"]),
        )
    else:
        _prepend_path(process_env, _library_env_name(), str(runtime_dir / "lib"))


def _library_env_name() -> str:
    if os.name == "nt":
        return "PATH"
    if sys.platform == "darwin":
        return "DYLD_LIBRARY_PATH"
    return "LD_LIBRARY_PATH"


def _prepend_path(process_env: dict[str, str], name: str, prefix: str) -> None:
    existing = process_env.get(name, "")
    process_env[name] = prefix if not existing else prefix + _path_separator() + existing


def _join_paths(paths: list[Path]) -> str:
    return _path_separator().join(str(path) for path in paths)


def _path_separator() -> str:
    return ";" if os.name == "nt" else os.pathsep
