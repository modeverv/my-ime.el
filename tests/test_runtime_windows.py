from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import tarfile
import tempfile
from unittest import mock
import unittest

import server.kkc_client as kkc_client


ROOT = Path(__file__).resolve().parent.parent
INSTALLER_PATH = ROOT / "scripts" / "install-kkc-runtime.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_kkc_runtime", INSTALLER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeInstallerTests(unittest.TestCase):
    def test_detects_windows_x86_64_runtime_name_parts(self) -> None:
        installer = load_installer()
        with mock.patch.object(installer.platform, "system", return_value="Windows"):
            self.assertEqual(installer.detect_runtime_os(), "windows")
        with mock.patch.object(installer.platform, "machine", return_value="AMD64"):
            self.assertEqual(installer.detect_runtime_arch(), "x86_64")

    def test_detects_linux_x86_64_runtime_name_parts(self) -> None:
        installer = load_installer()
        with mock.patch.object(installer.platform, "system", return_value="Linux"):
            self.assertEqual(installer.detect_runtime_os(), "linux")
        with mock.patch.object(installer.platform, "machine", return_value="x86_64"):
            self.assertEqual(installer.detect_runtime_arch(), "x86_64")

    def test_installs_runtime_from_local_submodule_bundle(self) -> None:
        installer = load_installer()
        runtime_name = "my-ime-kkc-runtime-windows-x86_64"
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            local_repo = base / "runtime"
            bundle_root = base / runtime_name
            runtime_dir = base / ".deps" / "kkc-runtime"
            local_repo.mkdir()
            (bundle_root / "bin").mkdir(parents=True)
            (bundle_root / "bin" / "kkc.exe").write_text("test", encoding="utf-8")
            archive = local_repo / f"{runtime_name}.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(bundle_root, arcname=runtime_name)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (local_repo / f"{runtime_name}.tar.gz.sha256").write_text(
                f"{digest}  {archive.name}\n",
                encoding="utf-8",
            )

            installed_archive, installed_sha = installer.obtain_bundle(
                runtime_name=runtime_name,
                runtime_dir=runtime_dir,
                local_repo=local_repo,
                repo_url="https://example.invalid",
            )
            installer.verify_sha256(installed_archive, installed_sha)
            installer.install_archive(installed_archive, runtime_name, runtime_dir)

            self.assertTrue((runtime_dir / "current" / "bin" / "kkc.exe").exists())


class WindowsKkcRuntimeTests(unittest.TestCase):
    def test_kkc_env_maps_configured_data_path_to_libkkc_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"MY_IME_KKC_DATA_PATH": "/runtime/lib/libkkc:/runtime/share/libkkc"},
            clear=True,
        ):
            env = kkc_client._kkc_env("/usr/bin/kkc")

        self.assertEqual(
            env["LIBKKC_DATA_PATH"],
            "/runtime/lib/libkkc:/runtime/share/libkkc",
        )

    def test_find_kkc_command_uses_bundled_windows_exe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime_dir = Path(temp)
            (runtime_dir / "bin").mkdir()
            command = runtime_dir / "bin" / "kkc.exe"
            command.write_text("", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(kkc_client.os, "name", "nt"),
                mock.patch.object(kkc_client, "_bundled_runtime_dir", return_value=runtime_dir),
            ):
                self.assertEqual(kkc_client.find_kkc_command(), str(command))

    def test_windows_runtime_env_prepends_runtime_to_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime_dir = Path(temp)
            command = runtime_dir / "bin" / "kkc.exe"
            (runtime_dir / "bin").mkdir(parents=True)
            (runtime_dir / "lib").mkdir()
            command.write_text("", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"PATH": "C:\\Windows"}, clear=True),
                mock.patch.object(kkc_client.os, "name", "nt"),
                mock.patch.object(kkc_client, "_bundled_kkc_data_path", return_value=""),
                mock.patch.object(kkc_client, "_runtime_dir_for_command", return_value=runtime_dir),
            ):
                env = kkc_client._kkc_env(str(command))

            self.assertTrue(env["PATH"].startswith(str(runtime_dir / "bin") + ";"))
            self.assertIn(";" + str(runtime_dir / "lib") + ";", env["PATH"])


if __name__ == "__main__":
    unittest.main()
