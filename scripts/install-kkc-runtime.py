#!/usr/bin/env python3
"""Install a prebuilt my-ime kkc runtime bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile


DEFAULT_REPO = "https://raw.githubusercontent.com/modeverv/my-ime-kkc-runtime/main"
ARCHIVE_EXTENSIONS = (".tar.gz", ".zip")


class InstallError(RuntimeError):
    """Raised when the runtime cannot be installed."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", default=".deps/kkc-runtime")
    parser.add_argument("--repo", default=os.environ.get("RUNTIME_REPO", DEFAULT_REPO))
    parser.add_argument("--local-repo", default="runtime/my-ime-kkc-runtime")
    parser.add_argument("--os", dest="runtime_os", default=None)
    parser.add_argument("--arch", dest="runtime_arch", default=None)
    args = parser.parse_args()

    runtime_os = args.runtime_os or detect_runtime_os()
    runtime_arch = args.runtime_arch or detect_runtime_arch()
    runtime_name = f"my-ime-kkc-runtime-{runtime_os}-{runtime_arch}"
    runtime_dir = Path(args.runtime_dir)

    try:
        archive, sha256_file = obtain_bundle(
            runtime_name=runtime_name,
            runtime_dir=runtime_dir,
            local_repo=Path(args.local_repo),
            repo_url=args.repo,
        )
        verify_sha256(archive, sha256_file)
        install_archive(archive, runtime_name, runtime_dir)
    except InstallError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"installed {runtime_name} to {runtime_dir / 'current'}")


def detect_runtime_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "darwin"
    if system == "Linux":
        return "linux"
    if system == "Windows":
        return "windows"
    raise InstallError(f"unsupported runtime OS: {system}")


def detect_runtime_arch() -> str:
    machine = platform.machine().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
    }
    return aliases.get(machine, machine)


def obtain_bundle(
    *,
    runtime_name: str,
    runtime_dir: Path,
    local_repo: Path,
    repo_url: str,
) -> tuple[Path, Path]:
    runtime_dir.mkdir(parents=True, exist_ok=True)

    local = find_local_bundle(runtime_name, local_repo)
    if local is not None:
        archive, sha256_file = local
        target_archive = runtime_dir / archive.name
        target_sha256 = runtime_dir / sha256_file.name
        if archive.resolve() != target_archive.resolve():
            shutil.copy2(archive, target_archive)
        if sha256_file.resolve() != target_sha256.resolve():
            shutil.copy2(sha256_file, target_sha256)
        return target_archive, target_sha256

    return download_bundle(runtime_name, runtime_dir, repo_url)


def find_local_bundle(runtime_name: str, local_repo: Path) -> tuple[Path, Path] | None:
    if not local_repo.exists():
        return None
    for extension in ARCHIVE_EXTENSIONS:
        archive = local_repo / f"{runtime_name}{extension}"
        sha256_file = local_repo / f"{runtime_name}{extension}.sha256"
        if archive.exists() and sha256_file.exists():
            return archive, sha256_file
    return None


def download_bundle(runtime_name: str, runtime_dir: Path, repo_url: str) -> tuple[Path, Path]:
    errors: list[str] = []
    for extension in ARCHIVE_EXTENSIONS:
        archive = runtime_dir / f"{runtime_name}{extension}"
        sha256_file = runtime_dir / f"{runtime_name}{extension}.sha256"
        archive_url = f"{repo_url.rstrip('/')}/{archive.name}"
        sha256_url = f"{repo_url.rstrip('/')}/{sha256_file.name}"
        try:
            download_file(archive_url, archive)
            download_file(sha256_url, sha256_file)
            return archive, sha256_file
        except InstallError as exc:
            errors.append(str(exc))
            archive.unlink(missing_ok=True)
            sha256_file.unlink(missing_ok=True)
    tried = "\n".join(f"- {message}" for message in errors)
    raise InstallError(f"could not obtain runtime bundle {runtime_name}:\n{tried}")


def download_file(url: str, target: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=30) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (urllib.error.URLError, OSError) as exc:
        raise InstallError(f"{url}: {exc}") from exc


def verify_sha256(archive: Path, sha256_file: Path) -> None:
    expected = parse_sha256_file(sha256_file)
    actual = sha256sum(archive)
    if actual.lower() != expected.lower():
        raise InstallError(
            f"sha256 mismatch for {archive.name}: expected {expected}, got {actual}"
        )


def parse_sha256_file(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise InstallError(f"could not read {path}: {exc}") from exc
    if not content:
        raise InstallError(f"empty sha256 file: {path}")
    digest = content.split()[0]
    if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        raise InstallError(f"invalid sha256 file: {path}")
    return digest


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise InstallError(f"could not hash {path}: {exc}") from exc
    return digest.hexdigest()


def install_archive(archive: Path, runtime_name: str, runtime_dir: Path) -> None:
    current = runtime_dir / "current"
    temp_parent = runtime_dir / ".extract"
    temp_parent.mkdir(parents=True, exist_ok=True)
    extract_dir = Path(tempfile.mkdtemp(prefix=f"{runtime_name}-", dir=temp_parent))

    try:
        extract_archive(archive, extract_dir)
        source = extracted_root(extract_dir, runtime_name)
        replacement = runtime_dir / ".current-new"
        if replacement.exists():
            remove_tree(replacement)
        shutil.move(str(source), replacement)
        if current.exists():
            remove_tree(current)
        shutil.move(str(replacement), current)
    finally:
        if extract_dir.exists():
            remove_tree(extract_dir)


def extract_archive(archive: Path, target: Path) -> None:
    try:
        if archive.name.endswith(".tar.gz"):
            with tarfile.open(archive, "r:gz") as tar:
                safe_extract_tar(tar, target)
            return
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zip_file:
                zip_file.extractall(target)
            return
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        raise InstallError(f"could not extract {archive}: {exc}") from exc
    raise InstallError(f"unsupported archive format: {archive}")


def safe_extract_tar(tar: tarfile.TarFile, target: Path) -> None:
    target_root = target.resolve()
    for member in tar.getmembers():
        member_target = (target / member.name).resolve()
        if target_root != member_target and target_root not in member_target.parents:
            raise InstallError(f"archive member escapes target directory: {member.name}")
    try:
        tar.extractall(target, filter="data")
    except TypeError:
        tar.extractall(target)


def extracted_root(extract_dir: Path, runtime_name: str) -> Path:
    named_root = extract_dir / runtime_name
    if named_root.is_dir():
        return named_root
    entries = [entry for entry in extract_dir.iterdir() if entry.name not in {".", ".."}]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir


def remove_tree(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
