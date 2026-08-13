from __future__ import annotations

import io
import json
import os
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from texmini import __version__, model, runtime


class RuntimeTest(unittest.TestCase):
    @staticmethod
    def _tinytex_archive(missing: set[str] | None = None) -> bytes:
        missing = missing or set()
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:xz") as archive:
            for tool in ("latexmk", "tlmgr", "kpsewhich", "pdflatex"):
                if tool in missing:
                    continue
                if os.name == "nt":
                    filename = f"{tool}.bat" if tool == "tlmgr" else f"{tool}.exe"
                else:
                    filename = tool
                info = tarfile.TarInfo(f"TinyTeX/bin/test/{filename}")
                content = tool.encode()
                info.size = len(content)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(content))
        return payload.getvalue()

    @staticmethod
    def _manifest(
        asset_format: str = "tar.xz", filename: str = "TinyTeX-test.tar.xz"
    ) -> runtime.RuntimeManifest:
        return runtime.RuntimeManifest(
            1,
            "2099.01",
            "https://packages.example.test/tlnet",
            {
                "test": runtime.RuntimeAsset(filename, "a" * 64, asset_format),
                "windows-x86_64": runtime.RuntimeAsset(
                    "TinyTeX-test.exe", "b" * 64, "windows-sfx"
                ),
            },
        )

    @staticmethod
    def _write_managed_tools(root: Path, windows: bool | None = None) -> None:
        windows = os.name == "nt" if windows is None else windows
        binary = root / "bin" / "platform"
        binary.mkdir(parents=True)
        names = (
            ("latexmk.exe", "tlmgr.bat", "kpsewhich.exe", "pdflatex.exe")
            if windows
            else ("latexmk", "tlmgr", "kpsewhich", "pdflatex")
        )
        for name in names:
            path = binary / name
            path.write_text(name, encoding="utf-8")
            path.chmod(0o755)
        if windows:
            runscript = root / "bin" / "windows" / "runscript.tlu"
            perl = root / "tlpkg" / "tlperl" / "bin" / "perl.exe"
            runscript.parent.mkdir(parents=True)
            perl.parent.mkdir(parents=True)
            runscript.write_text("runscript", encoding="utf-8")
            perl.write_text("perl", encoding="utf-8")

    def test_manifest_is_the_complete_pinned_source_of_truth(self) -> None:
        manifest = runtime.load_runtime_manifest()

        self.assertEqual(manifest.schema_version, 1)
        self.assertEqual(manifest.tinytex_version, "2026.08")
        self.assertEqual(manifest.repository, "https://tlnet.yihui.org")
        self.assertEqual(
            set(manifest.assets),
            {
                "darwin",
                "linux-x86_64",
                "linux-arm64",
                "linuxmusl-x86_64",
                "windows-x86_64",
            },
        )
        self.assertTrue(
            all(len(asset.sha256) == 64 for asset in manifest.assets.values())
        )

    def test_asset_url_is_constructed_without_a_release_api(self) -> None:
        manifest = self._manifest()
        asset = manifest.assets["test"]

        self.assertEqual(
            runtime.tinytex_asset_url(manifest, asset),
            "https://github.com/rstudio/tinytex-releases/releases/download/"
            "v2099.01/TinyTeX-test.tar.xz",
        )
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        self.assertNotIn("api.github.com", source)

    def test_supported_platform_mappings(self) -> None:
        with patch("sys.platform", "darwin"):
            self.assertEqual(runtime.tinytex_platform_key(), "darwin")
        with (
            patch("sys.platform", "linux"),
            patch("platform.machine", return_value="x86_64"),
            patch("platform.libc_ver", return_value=("glibc", "2.36")),
        ):
            self.assertEqual(runtime.tinytex_platform_key(), "linux-x86_64")
        with (
            patch("sys.platform", "linux"),
            patch("platform.machine", return_value="aarch64"),
            patch("platform.libc_ver", return_value=("glibc", "2.36")),
        ):
            self.assertEqual(runtime.tinytex_platform_key(), "linux-arm64")
        with (
            patch("sys.platform", "linux"),
            patch("platform.machine", return_value="x86_64"),
            patch("platform.libc_ver", return_value=("musl", "1.2")),
        ):
            self.assertEqual(runtime.tinytex_platform_key(), "linuxmusl-x86_64")
        with (
            patch("sys.platform", "win32"),
            patch("platform.machine", return_value="AMD64"),
        ):
            self.assertEqual(runtime.tinytex_platform_key(), "windows-x86_64")

    def test_unsupported_platform_fails_before_download(self) -> None:
        with (
            patch("sys.platform", "freebsd"),
            patch("texmini.runtime.download") as download,
            self.assertRaisesRegex(model.TexMiniError, "Supported platforms"),
        ):
            runtime.install_tinytex_runtime(Path("TinyTeX"))
        download.assert_not_called()

    def test_missing_unix_perl_fails_before_download(self) -> None:
        with (
            patch("texmini.runtime.tinytex_platform_key", return_value="darwin"),
            patch("texmini.runtime.executable_on_path", return_value=None),
            patch("texmini.runtime.download") as download,
            self.assertRaisesRegex(model.TexMiniError, "Perl is required"),
        ):
            runtime.install_tinytex_runtime(Path("TinyTeX"))
        download.assert_not_called()

    def test_windows_skips_system_perl_preflight(self) -> None:
        with patch("texmini.runtime.executable_on_path") as executable:
            runtime.check_runtime_prerequisites("windows-x86_64")
        executable.assert_not_called()

    def test_archive_validation_rejects_escape_and_escaping_link(self) -> None:
        runtime.validate_tinytex_archive_member(tarfile.TarInfo("TinyTeX/bin/tool"))
        with self.assertRaises(model.TexMiniError):
            runtime.validate_tinytex_archive_member(tarfile.TarInfo("../escape"))
        link = tarfile.TarInfo("TinyTeX/bin/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../escape"
        with self.assertRaises(model.TexMiniError):
            runtime.validate_tinytex_archive_member(link)

    def test_fresh_tar_install_is_validated_and_records_provenance(self) -> None:
        archive = self._tinytex_archive()
        manifest = self._manifest()

        def provide_asset(_url: str, destination: Path, _digest: str) -> None:
            destination.write_bytes(archive)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch("texmini.runtime.tinytex_platform_key", return_value="test"),
                patch("texmini.runtime.check_runtime_prerequisites"),
                patch("texmini.runtime.load_runtime_manifest", return_value=manifest),
                patch("texmini.runtime.download", side_effect=provide_asset),
            ):
                runtime.install_tinytex_runtime(root)

            metadata = json.loads(
                (root / runtime.RUNTIME_METADATA).read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["texmini_version"], __version__)
            self.assertEqual(metadata["tinytex_version"], "2099.01")
            self.assertEqual(metadata["platform"], "test")
            self.assertTrue((root / "bin" / "test" / "latexmk").is_file())

    def test_failed_validation_does_not_install_partial_runtime(self) -> None:
        archive = self._tinytex_archive({"kpsewhich"})

        def provide_asset(_url: str, destination: Path, _digest: str) -> None:
            destination.write_bytes(archive)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch("texmini.runtime.tinytex_platform_key", return_value="test"),
                patch("texmini.runtime.check_runtime_prerequisites"),
                patch(
                    "texmini.runtime.load_runtime_manifest",
                    return_value=self._manifest(),
                ),
                patch("texmini.runtime.download", side_effect=provide_asset),
                self.assertRaisesRegex(model.TexMiniError, "kpsewhich"),
            ):
                runtime.install_tinytex_runtime(root)
            self.assertFalse(root.exists())

    def test_existing_legacy_runtime_is_reused_without_network_or_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            self._write_managed_tools(root)
            with (
                patch("texmini.runtime.tinytex_platform_key", return_value="test"),
                patch("texmini.runtime.check_runtime_prerequisites"),
                patch("texmini.runtime.download") as download,
            ):
                runtime.install_tinytex_runtime(root)

            download.assert_not_called()
            self.assertFalse((root / runtime.RUNTIME_METADATA).exists())

    def test_windows_sfx_uses_discrete_noninteractive_arguments(self) -> None:
        manifest = self._manifest()

        def provide_asset(_url: str, destination: Path, _digest: str) -> None:
            destination.write_bytes(b"verified executable")

        def extract(args: list[str], **kwargs: object) -> SimpleNamespace:
            output = Path(args[2].removeprefix("-o"))
            extracted = output / "TinyTeX"
            self._write_managed_tools(extracted, windows=True)
            for name in ("latexmk", "tlmgr", "kpsewhich", "pdflatex"):
                path = extracted / "bin" / "platform" / name
                path.write_text(name, encoding="utf-8")
                path.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="")

        with tempfile.TemporaryDirectory(prefix="texmini path ") as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch(
                    "texmini.runtime.tinytex_platform_key",
                    return_value="windows-x86_64",
                ),
                patch("texmini.runtime.load_runtime_manifest", return_value=manifest),
                patch("texmini.runtime.download", side_effect=provide_asset),
                patch("texmini.runtime.run_command", side_effect=extract) as run,
            ):
                runtime.install_tinytex_runtime(root)

            arguments = run.call_args.args[0]
            self.assertEqual(arguments[1], "-y")
            self.assertTrue(arguments[2].startswith("-o"))
            self.assertEqual(len(arguments), 3)
            self.assertTrue(root.is_dir())

    def test_managed_environment_forces_python_downloader(self) -> None:
        with tempfile.TemporaryDirectory(prefix="texmini path ") as directory:
            root = Path(directory) / "TinyTeX"
            self._write_managed_tools(root)
            with patch.dict(
                os.environ,
                {"TEXLIVE_DOWNLOADER": "curl", "PATH": os.environ.get("PATH", "")},
            ):
                env = runtime.tinytex_env(root)

        self.assertNotIn("TEXLIVE_DOWNLOADER", env)
        self.assertEqual(env["TL_DOWNLOAD_PROGRAM"], os.path.abspath(os.sys.executable))
        self.assertEqual(env["TL_DOWNLOAD_ARGS"], "-m texmini._download")
        self.assertIn("texmini path ", env["PATH"])

    def test_tlmgr_search_uses_pinned_repository_and_downloader(self) -> None:
        result = SimpleNamespace(
            returncode=0,
            stdout="custom-package: texmf-dist/tex/latex/custom/custom.sty\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            self._write_managed_tools(root)
            cache = Path(directory) / "map.json"
            env = runtime.tinytex_env(root)
            with patch("texmini.runtime.run_command", return_value=result) as run:
                resolved = runtime.resolve_tinytex_packages(
                    root, ["custom.sty"], cache, env=env
                )

        self.assertEqual(resolved, {"custom.sty": "custom-package"})
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[1:3], ["--repository", "https://tlnet.yihui.org"])
        managed_env = run.call_args.kwargs["env"]
        self.assertNotIn("TEXLIVE_DOWNLOADER", managed_env)
        self.assertEqual(managed_env["TL_DOWNLOAD_ARGS"], "-m texmini._download")

    def test_tlmgr_failure_preserves_downloader_context(self) -> None:
        errors = io.StringIO()
        result = SimpleNamespace(
            returncode=1,
            stdout="tlmgr: package download failed\nError: Download failed for asset\n",
        )
        with redirect_stderr(errors):
            runtime._report_tlmgr_failure(result, runtime.Reporter())

        self.assertIn("package download failed", errors.getvalue())
        self.assertIn("Download failed for asset", errors.getvalue())

    def test_resolver_uses_cached_mapping_without_tlmgr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            cache.write_text('{"custom.sty": "custom-package"}\n', encoding="utf-8")
            with patch("texmini.runtime.run_command") as run:
                resolved = runtime.resolve_tinytex_packages(
                    Path("TinyTeX"), ["custom.sty"], cache, env={}
                )

        self.assertEqual(resolved, {"custom.sty": "custom-package"})
        run.assert_not_called()

    def test_xelatex_engine_is_installed_on_demand(self) -> None:
        with (
            patch("texmini.runtime.executable_on_path_with_env", return_value=None),
            patch(
                "texmini.runtime.install_tinytex_packages",
                return_value=SimpleNamespace(returncode=0),
            ) as install,
        ):
            runtime.ensure_tinytex_engine(
                Path("TinyTeX"), "xelatex", {}, SimpleNamespace(status=lambda _: None)
            )

        self.assertEqual(install.call_args.args[1], ["xetex"])

    def test_common_runtime_mappings_cover_font_and_eps_dependencies(self) -> None:
        self.assertEqual(runtime.common_texlive_package_for_file("8r.enc"), "dvips")
        self.assertEqual(runtime.common_texlive_package_for_file("tcrm0700.tfm"), "ec")
        self.assertEqual(runtime.DIRECT_TOOL_PACKAGES["repstopdf"], "epstopdf")


if __name__ == "__main__":
    unittest.main()
