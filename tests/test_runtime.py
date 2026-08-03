from __future__ import annotations

import hashlib
import io
import os
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from texmini import __version__, model, reporting, runtime


class RuntimeTest(unittest.TestCase):
    @staticmethod
    def _tinytex_archive() -> bytes:
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:xz") as archive:
            info = tarfile.TarInfo("TinyTeX/bin/test/latexmk")
            content = b"latexmk"
            info.size = len(content)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(content))
        return payload.getvalue()

    def test_missing_source_files_excludes_recursive_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tex").mkdir()
            source = root / "paper.tex"
            source.write_text(
                "\\documentclass{publisher}\n\\bibliographystyle{localplain}\n",
                encoding="utf-8",
            )
            (root / "tex" / "publisher.cls").write_text("local", encoding="utf-8")
            (root / "tex" / "localplain.bst").write_text("local", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                missing = runtime.missing_tinytex_source_files(
                    Path("TinyTeX"),
                    "paper.tex",
                    env={},
                    source_files=["publisher.cls", "localplain.bst"],
                )
            finally:
                os.chdir(previous)

        self.assertEqual(missing, [])

    def test_resolver_uses_cached_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            cache.write_text('{"custom.sty": "custom-package"}\n', encoding="utf-8")
            with patch("texmini.runtime.run_command") as run:
                resolved = runtime.resolve_tinytex_packages(
                    Path("TinyTeX"), ["custom.sty"], cache, env={}
                )

        self.assertEqual(resolved, {"custom.sty": "custom-package"})
        run.assert_not_called()

    def test_resolver_uses_tlmgr_search_and_updates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            result = SimpleNamespace(
                returncode=0,
                stdout="custom-package: texmf-dist/tex/latex/custom/custom.sty\n",
            )
            with patch("texmini.runtime.run_command", return_value=result):
                resolved = runtime.resolve_tinytex_packages(
                    Path("TinyTeX"), ["custom.sty"], cache, env={}
                )

            self.assertEqual(resolved, {"custom.sty": "custom-package"})
            self.assertIn("custom-package", cache.read_text(encoding="utf-8"))

    def test_xelatex_engine_is_installed_on_demand(self) -> None:
        reporter = reporting.Reporter()
        with (
            patch("texmini.runtime.executable_on_path_with_env", return_value=None),
            patch(
                "texmini.runtime.install_tinytex_packages",
                return_value=SimpleNamespace(returncode=0),
            ) as install,
            redirect_stdout(io.StringIO()),
        ):
            runtime.ensure_tinytex_engine(Path("TinyTeX"), "xelatex", {}, reporter)

        self.assertEqual(install.call_args.args[1], ["xetex"])

    def test_platform_selects_musl_linux_asset(self) -> None:
        with (
            patch("sys.platform", "linux"),
            patch("platform.machine", return_value="x86_64"),
            patch("platform.libc_ver", return_value=("musl", "1.2")),
        ):
            self.assertEqual(runtime.tinytex_platform_key(), "linuxmusl-x86_64")

    def test_archive_validation_rejects_escape(self) -> None:
        safe = tarfile.TarInfo("TinyTeX/bin/tool")
        runtime.validate_tinytex_archive_member(safe)
        with self.assertRaises(model.TexMiniError):
            runtime.validate_tinytex_archive_member(tarfile.TarInfo("../escape"))

    def test_release_lookup_uses_github_token_when_available(self) -> None:
        release = io.BytesIO(
            b'{"assets":[{"name":"TinyTeX-0-test-v1.tar.xz","browser_download_url":"https://archive","digest":"sha256:abc"}]}'
        )
        with (
            patch.dict(
                os.environ,
                {"GITHUB_TOKEN": "test-token", "TEXMINI_TINYTEX_BUNDLE": "TinyTeX-0"},
            ),
            patch("texmini.runtime.tinytex_platform_key", return_value="test"),
            patch("urllib.request.urlopen", return_value=release) as urlopen,
        ):
            asset = runtime.latest_tinytex_asset()

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(request.get_header("User-agent"), f"texmini/{__version__}")
        self.assertEqual(
            asset, ("TinyTeX-0-test-v1.tar.xz", "https://archive", "sha256:abc")
        )

    def test_tinytex_archive_verifies_checksum_before_extraction(self) -> None:
        archive = self._tinytex_archive()
        digest = f"sha256:{hashlib.sha256(archive).hexdigest()}"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch.dict(os.environ, {"TEXMINI_TINYTEX_BUNDLE": "TinyTeX-1"}),
                patch(
                    "texmini.runtime.executable_on_path", return_value="/usr/bin/perl"
                ),
                patch(
                    "texmini.runtime.latest_tinytex_asset",
                    return_value=("TinyTeX-1-test.tar.xz", "https://test", digest),
                ),
                patch("urllib.request.urlopen", return_value=io.BytesIO(archive)),
                patch("texmini.runtime.update_tinytex_manager"),
            ):
                runtime.install_tinytex_archive(root)

            self.assertTrue((root / "bin" / "test" / "latexmk").is_file())

    def test_checksum_failure_stops_before_extraction(self) -> None:
        archive = self._tinytex_archive()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch.dict(os.environ, {"TEXMINI_TINYTEX_BUNDLE": "TinyTeX-1"}),
                patch(
                    "texmini.runtime.executable_on_path", return_value="/usr/bin/perl"
                ),
                patch(
                    "texmini.runtime.latest_tinytex_asset",
                    return_value=(
                        "TinyTeX-1-test.tar.xz",
                        "https://test",
                        "sha256:" + "0" * 64,
                    ),
                ),
                patch("urllib.request.urlopen", return_value=io.BytesIO(archive)),
                patch("tarfile.open") as tar_open,
                self.assertRaisesRegex(
                    model.TexMiniError, "Checksum verification failed"
                ),
            ):
                runtime.install_tinytex_archive(root)
            tar_open.assert_not_called()
            self.assertFalse(root.exists())

    def test_archive_without_digest_is_supported(self) -> None:
        archive = self._tinytex_archive()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch.dict(os.environ, {"TEXMINI_TINYTEX_BUNDLE": "TinyTeX-1"}),
                patch(
                    "texmini.runtime.executable_on_path", return_value="/usr/bin/perl"
                ),
                patch(
                    "texmini.runtime.latest_tinytex_asset",
                    return_value=("TinyTeX-1-test.tar.xz", "https://test", None),
                ),
                patch("urllib.request.urlopen", return_value=io.BytesIO(archive)),
                patch("texmini.runtime.update_tinytex_manager"),
            ):
                runtime.install_tinytex_archive(root)
            self.assertTrue(root.exists())


if __name__ == "__main__":
    unittest.main()
