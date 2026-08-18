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

from texmini import __version__, model, project, runtime


class RuntimeTest(unittest.TestCase):
    @staticmethod
    def _write_host_tool(directory: Path, name: str) -> Path:
        path = directory / (f"{name}.bat" if os.name == "nt" else name)
        path.write_text("@exit /b 0\n" if os.name == "nt" else name, encoding="utf-8")
        path.chmod(0o755)
        return path

    @staticmethod
    def _tinytex_archive(missing: set[str] | None = None) -> bytes:
        missing = missing or set()
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:xz") as archive:
            for tool in ("latexmk", "tlmgr", "kpsewhich", "pdflatex", "lualatex"):
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
    def _manifest_data() -> dict[str, object]:
        version = "2099.01"
        return {
            "schema_version": 1,
            "tinytex_version": version,
            "repository": "https://packages.example.test/tlnet",
            "assets": {
                "darwin": {
                    "filename": f"TinyTeX-1-darwin-v{version}.tar.xz",
                    "sha256": "1" * 64,
                    "format": "tar.xz",
                },
                "linux-x86_64": {
                    "filename": f"TinyTeX-1-linux-x86_64-v{version}.tar.xz",
                    "sha256": "2" * 64,
                    "format": "tar.xz",
                },
                "linux-arm64": {
                    "filename": f"TinyTeX-1-linux-arm64-v{version}.tar.xz",
                    "sha256": "3" * 64,
                    "format": "tar.xz",
                },
                "linuxmusl-x86_64": {
                    "filename": (
                        f"TinyTeX-1-linuxmusl-x86_64-v{version}.tar.xz"
                    ),
                    "sha256": "4" * 64,
                    "format": "tar.xz",
                },
                "windows-x86_64": {
                    "filename": f"TinyTeX-1-windows-v{version}.exe",
                    "sha256": "5" * 64,
                    "format": "windows-sfx",
                },
            },
        }

    @staticmethod
    def _write_managed_tools(root: Path, windows: bool | None = None) -> None:
        windows = os.name == "nt" if windows is None else windows
        binary = root / "bin" / "platform"
        binary.mkdir(parents=True)
        names = (
            (
                "latexmk.exe",
                "tlmgr.bat",
                "kpsewhich.exe",
                "pdflatex.exe",
                "lualatex.exe",
            )
            if windows
            else ("latexmk", "tlmgr", "kpsewhich", "pdflatex", "lualatex")
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
            all(
                len(asset.sha256) == 64
                and asset.sha256 == asset.sha256.lower()
                and all(character in "0123456789abcdef" for character in asset.sha256)
                for asset in manifest.assets.values()
            )
        )

    def test_packaged_manifest_is_cached_and_immutable(self) -> None:
        runtime._load_runtime_manifest.cache_clear()
        self.addCleanup(runtime._load_runtime_manifest.cache_clear)

        first = runtime.load_runtime_manifest()
        second = runtime.load_runtime_manifest()

        self.assertIs(first, second)
        with self.assertRaises(TypeError):
            first.assets["darwin"] = first.assets["darwin"]  # type: ignore[index]

    def test_manifest_parser_enforces_platform_filename_format_and_digest(self) -> None:
        parsed = runtime._parse_runtime_manifest(self._manifest_data())

        self.assertEqual(parsed.tinytex_version, "2099.01")
        self.assertEqual(set(parsed.assets), set(runtime.RUNTIME_ASSET_FORMATS))

        mutations = {
            "missing platform": lambda data: data["assets"].pop("linux-arm64"),
            "unknown platform": lambda data: data["assets"].update(
                {"windows-arm64": data["assets"]["windows-x86_64"]}
            ),
            "wrong version filename": lambda data: data["assets"]["darwin"].update(
                {"filename": "TinyTeX-1-darwin-v2099.02.tar.xz"}
            ),
            "uppercase digest": lambda data: data["assets"][
                "linux-x86_64"
            ].update({"sha256": "A" * 64}),
            "wrong format": lambda data: data["assets"]["windows-x86_64"].update(
                {"format": "tar.xz"}
            ),
            "insecure repository": lambda data: data.update(
                {"repository": "http://packages.example.test/tlnet"}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                data = json.loads(json.dumps(self._manifest_data()))
                mutate(data)
                with self.assertRaisesRegex(
                    model.TexMiniError, "Invalid TinyTeX runtime manifest"
                ):
                    runtime._parse_runtime_manifest(data)

    def test_layout_hook_requires_exact_pinned_runtime_metadata(self) -> None:
        manifest = runtime.load_runtime_manifest()
        platform_key, asset = next(iter(manifest.assets.items()))
        metadata = {
            "schema_version": 1,
            "tinytex_version": manifest.tinytex_version,
            "platform": platform_key,
            "asset": asset.filename,
            "sha256": asset.sha256,
            "repository": manifest.repository,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / runtime.RUNTIME_METADATA).write_text(
                json.dumps(metadata), encoding="utf-8"
            )

            self.assertTrue(runtime.runtime_supports_layout_hook(root))
            with patch.dict(
                os.environ, {"TEXMINI_DISABLE_LAYOUT_HOOK": "1"}
            ):
                self.assertFalse(runtime.runtime_supports_layout_hook(root))
            metadata["sha256"] = "0" * 64
            (root / runtime.RUNTIME_METADATA).write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            self.assertFalse(runtime.runtime_supports_layout_hook(root))

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

    def test_unknown_linux_libc_and_arm64_musl_fail_closed(self) -> None:
        for machine, libc in (("x86_64", ""), ("x86_64", "mystery"), ("arm64", "musl")):
            with (
                self.subTest(machine=machine, libc=libc),
                patch("sys.platform", "linux"),
                patch("platform.machine", return_value=machine),
                patch("platform.libc_ver", return_value=(libc, "1.0")),
                self.assertRaisesRegex(model.TexMiniError, "unsupported"),
            ):
                runtime.tinytex_platform_key()

    def test_unknown_linux_libc_fails_before_download(self) -> None:
        with (
            patch("sys.platform", "linux"),
            patch("platform.machine", return_value="x86_64"),
            patch("platform.libc_ver", return_value=("", "")),
            patch("texmini.runtime.download") as download,
            self.assertRaisesRegex(model.TexMiniError, "unrecognized Linux C library"),
        ):
            runtime.install_tinytex_runtime(Path("TinyTeX"))
        download.assert_not_called()

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

    @unittest.skipIf(os.name == "nt", "symlink extraction requires Windows privileges")
    def test_one_pass_extraction_preserves_file_mode_and_safe_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "runtime.tar.xz"
            destination = Path(directory) / "payload"
            destination.mkdir()
            with tarfile.open(archive_path, mode="w:xz") as archive:
                content = b"managed tool"
                tool = tarfile.TarInfo("TinyTeX/bin/test/tool")
                tool.size = len(content)
                tool.mode = 0o755
                archive.addfile(tool, io.BytesIO(content))
                link = tarfile.TarInfo("TinyTeX/bin/test/tool-link")
                link.type = tarfile.SYMTYPE
                link.linkname = "tool"
                archive.addfile(link)
                hardlink = tarfile.TarInfo("TinyTeX/bin/test/tool-hardlink")
                hardlink.type = tarfile.LNKTYPE
                hardlink.linkname = "TinyTeX/bin/test/tool"
                hardlink.mode = 0o755
                archive.addfile(hardlink)

            extracted = runtime._extract_tinytex_archive(archive_path, destination)

            tool_path = extracted / "bin" / "test" / "tool"
            self.assertEqual(tool_path.read_bytes(), content)
            self.assertTrue(tool_path.stat().st_mode & 0o111)
            self.assertTrue((tool_path.parent / "tool-link").is_symlink())
            self.assertEqual((tool_path.parent / "tool-hardlink").read_bytes(), content)

    def test_late_unsafe_archive_member_never_creates_final_runtime(self) -> None:
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:xz") as archive:
            for tool_name in (
                "latexmk",
                "tlmgr",
                "kpsewhich",
                "pdflatex",
                "lualatex",
            ):
                info = tarfile.TarInfo(f"TinyTeX/bin/test/{tool_name}")
                content = tool_name.encode()
                info.size = len(content)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(content))
            unsafe = tarfile.TarInfo("../late-escape")
            unsafe.size = 1
            archive.addfile(unsafe, io.BytesIO(b"x"))

        def provide_asset(_url: str, destination: Path, _digest: str) -> None:
            destination.write_bytes(payload.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch("texmini.runtime.tinytex_platform_key", return_value="test"),
                patch("texmini.runtime.check_runtime_prerequisites"),
                patch("texmini.runtime.load_runtime_manifest", return_value=self._manifest()),
                patch("texmini.runtime.download", side_effect=provide_asset),
                self.assertRaisesRegex(model.TexMiniError, "Unsafe path"),
            ):
                runtime.install_tinytex_runtime(root)

            self.assertFalse(root.exists())
            self.assertFalse((Path(directory).parent / "late-escape").exists())

    def test_fresh_tar_install_is_validated_and_records_provenance(self) -> None:
        archive = self._tinytex_archive()
        manifest = self._manifest()

        def provide_asset(_url: str, destination: Path, _digest: str) -> None:
            destination.write_bytes(archive)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            status_messages: list[str] = []
            with (
                patch("texmini.runtime.tinytex_platform_key", return_value="test"),
                patch("texmini.runtime.check_runtime_prerequisites"),
                patch("texmini.runtime.load_runtime_manifest", return_value=manifest),
                patch("texmini.runtime.download", side_effect=provide_asset),
            ):
                runtime.install_tinytex_runtime(
                    root, SimpleNamespace(status=status_messages.append)
                )

            metadata = json.loads(
                (root / runtime.RUNTIME_METADATA).read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["texmini_version"], __version__)
            self.assertEqual(metadata["tinytex_version"], "2099.01")
            self.assertEqual(metadata["platform"], "test")
            latexmk = "latexmk.exe" if os.name == "nt" else "latexmk"
            self.assertTrue((root / "bin" / "test" / latexmk).is_file())
            self.assertIn(
                "Expect about 300–350 MB of disk use for the managed runtime.",
                status_messages,
            )

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
            for name in (
                "latexmk",
                "tlmgr",
                "kpsewhich",
                "pdflatex",
                "lualatex",
            ):
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
            managed_tlmgr = runtime.managed_tool(root, "tlmgr")
            host_bin = Path(directory) / "host-bin"
            host_bin.mkdir()
            host_tlmgr = self._write_host_tool(host_bin, "tlmgr")
            cache = Path(directory) / "map.json"
            env = runtime.tinytex_env(root)
            env["PATH"] = f"{host_bin}{os.pathsep}{env['PATH']}"
            self.assertEqual(
                runtime.executable_on_path_with_env("tlmgr", env),
                os.fspath(host_tlmgr),
            )
            with patch("texmini.runtime.run_command", return_value=result) as run:
                resolved = runtime.resolve_tinytex_packages(
                    root, ["custom.sty"], cache, env=env
                )

        self.assertEqual(resolved, {"custom.sty": "custom-package"})
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[0], managed_tlmgr)
        self.assertEqual(arguments[1:3], ["--repository", "https://tlnet.yihui.org"])
        self.assertEqual(arguments[-1], r"/(?:custom\.sty)$")
        managed_env = run.call_args.kwargs["env"]
        self.assertNotIn("TEXLIVE_DOWNLOADER", managed_env)
        self.assertEqual(managed_env["TL_DOWNLOAD_ARGS"], "-m texmini._download")

    def test_tlmgr_install_ignores_host_path(self) -> None:
        result = SimpleNamespace(returncode=0, stdout="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            self._write_managed_tools(root)
            managed_tlmgr = runtime.managed_tool(root, "tlmgr")
            host_bin = Path(directory) / "host-bin"
            host_bin.mkdir()
            host_tlmgr = self._write_host_tool(host_bin, "tlmgr")
            env = runtime.tinytex_env(root)
            env["PATH"] = f"{host_bin}{os.pathsep}{env['PATH']}"
            self.assertEqual(
                runtime.executable_on_path_with_env("tlmgr", env),
                os.fspath(host_tlmgr),
            )
            with patch("texmini.runtime.run_command", return_value=result) as run:
                runtime.install_tinytex_packages(root, ["geometry"], env=env)

        self.assertEqual(run.call_args.args[0][0], managed_tlmgr)

    def test_resolver_batches_uncached_file_searches_and_maps_each_path(self) -> None:
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "alpha-package:\n"
                "  texmf-dist/tex/latex/alpha/alpha.sty\n"
                "beta-package: texmf-dist/bibtex/bst/beta/beta.bst\n"
                "shared-package:\n"
                "  texmf-dist/tex/latex/shared/nested/gamma.sty\n"
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            with (
                patch("texmini.runtime.managed_tool", return_value="/managed/tlmgr"),
                patch("texmini.runtime.run_command", return_value=result) as run,
            ):
                resolved = runtime.resolve_tinytex_packages(
                    Path("TinyTeX"),
                    ["alpha.sty", "beta.bst", "nested/gamma.sty"],
                    cache,
                    env={},
                )

        self.assertEqual(
            resolved,
            {
                "alpha.sty": "alpha-package",
                "beta.bst": "beta-package",
                "nested/gamma.sty": "shared-package",
            },
        )
        run.assert_called_once()
        pattern = run.call_args.args[0][-1]
        self.assertIn(r"alpha\.sty", pattern)
        self.assertIn(r"beta\.bst", pattern)
        self.assertIn(r"nested/gamma\.sty", pattern)

    def test_ambiguous_tlmgr_metadata_is_not_resolved_or_cached(self) -> None:
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "runtime-package: texmf-dist/tex/latex/pkg/custom.sty\n"
                "source-package: texmf-dist/source/latex/pkg/custom.sty\n"
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            with (
                patch("texmini.runtime.managed_tool", return_value="/managed/tlmgr"),
                patch("texmini.runtime.run_command", return_value=result),
            ):
                resolved = runtime.resolve_tinytex_packages(
                    Path("TinyTeX"), ["custom.sty"], cache, env={}
                )

            self.assertEqual(resolved, {})
            self.assertFalse(cache.exists())

        self.assertIsNone(runtime.package_from_tlmgr_search(result.stdout))

    def test_search_chunks_bound_file_count(self) -> None:
        names = [f"package-{index}.sty" for index in range(65)]

        chunks = runtime._tlmgr_search_chunks(names)

        self.assertEqual([len(chunk) for chunk in chunks], [32, 32, 1])

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

    def test_local_file_discovery_reuses_analyzed_sources_and_walks_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "paper.tex"
            source.write_text("source", encoding="utf-8")
            local = project / "vendor" / "local.sty"
            local.parent.mkdir()
            local.write_text("local", encoding="utf-8")
            result = SimpleNamespace(returncode=0, stdout="")
            previous = Path.cwd()
            try:
                os.chdir(project)
                with (
                    patch("texmini.runtime.project_source_files") as discover,
                    patch("texmini.runtime.os.walk", wraps=os.walk) as walk,
                    patch("texmini.runtime.managed_tool", return_value="kpsewhich"),
                    patch("texmini.runtime.run_command", return_value=result) as run,
                ):
                    missing = runtime.missing_tinytex_source_files(
                        Path("TinyTeX"),
                        "paper.tex",
                        env={},
                        source_files=["local.sty", "remote.sty"],
                        source_paths=[source],
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(missing, ["remote.sty"])
        discover.assert_not_called()
        walk.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1], "remote.sty")

    def test_complete_project_scan_reuses_nested_source_without_second_walk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            source = project_root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            local = project_root / "vendor" / "local.sty"
            local.parent.mkdir()
            local.write_text("local", encoding="utf-8")
            result = SimpleNamespace(returncode=0, stdout="")
            previous = Path.cwd()
            try:
                os.chdir(project_root)
                with (
                    patch("texmini.runtime.os.walk") as walk,
                    patch("texmini.runtime.managed_tool", return_value="kpsewhich"),
                    patch("texmini.runtime.run_command", return_value=result) as run,
                ):
                    missing = runtime.missing_tinytex_source_files(
                        Path("TinyTeX"),
                        "paper.tex",
                        env={},
                        source_files=["local.sty", "remote.sty"],
                        source_paths=[source, local],
                        project_scan_complete=True,
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(missing, ["remote.sty"])
        walk.assert_not_called()
        self.assertEqual(run.call_args.args[0][-1], "remote.sty")

    def test_explicit_missing_local_path_is_never_substituted_by_tex_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            with patch("texmini.runtime.run_command") as run:
                resolved = runtime.resolve_tinytex_packages(
                    Path("TinyTeX"),
                    ["./styles/publisher.sty", "../publisher.cls"],
                    cache,
                    env={},
                )

            self.assertEqual(resolved, {})
            run.assert_not_called()

    def test_relative_subdirectory_class_or_style_is_source_project_owned(self) -> None:
        self.assertTrue(runtime.is_project_source_reference("styles/local.sty"))
        self.assertTrue(runtime.is_project_source_reference(r"classes\publisher.cls"))
        self.assertFalse(runtime.is_project_source_reference("geometry.sty"))

    def test_missing_source_subdirectory_files_never_reach_kpsewhich(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text(
                "\\documentclass{classes/publisher}\n"
                "\\usepackage{styles/local}\n"
                "\\bibliographystyle{bibliography/custom}\n",
                encoding="utf-8",
            )
            requirements = project.analyze_source_requirements(str(source))
            with patch("texmini.runtime.run_command") as run:
                missing = runtime.missing_tinytex_source_files(
                    Path("TinyTeX"),
                    str(source),
                    env={},
                    source_files=list(requirements.files),
                    source_paths=requirements.sources,
                )

        self.assertEqual(missing, [])
        run.assert_not_called()

    def test_xelatex_engine_is_installed_on_demand(self) -> None:
        with (
            patch(
                "texmini.runtime.managed_executable",
                side_effect=[None, "/managed/xelatex"],
            ),
            patch(
                "texmini.runtime.install_tinytex_packages",
                return_value=SimpleNamespace(returncode=0),
            ) as install,
        ):
            runtime.ensure_tinytex_engine(
                Path("TinyTeX"), "xelatex", {}, SimpleNamespace(status=lambda _: None)
            )

        self.assertEqual(install.call_args.args[1], ["xetex"])

    def test_engine_install_must_create_managed_executable(self) -> None:
        with (
            patch("texmini.runtime.managed_executable", return_value=None),
            patch(
                "texmini.runtime.install_tinytex_packages",
                return_value=SimpleNamespace(returncode=0),
            ),
            self.assertRaisesRegex(model.TexMiniError, "did not provide xelatex"),
        ):
            runtime.ensure_tinytex_engine(
                Path("TinyTeX"), "xelatex", {}, SimpleNamespace(status=lambda _: None)
            )

    def test_host_xelatex_does_not_satisfy_managed_engine_provisioning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            self._write_managed_tools(root)
            host_bin = Path(directory) / "host-bin"
            host_bin.mkdir()
            host_engine = self._write_host_tool(host_bin, "xelatex")
            env = runtime.tinytex_env(root)
            env["PATH"] = f"{root / 'bin' / 'platform'}{os.pathsep}{host_bin}"
            self.assertEqual(
                runtime.executable_on_path_with_env("xelatex", env),
                os.fspath(host_engine),
            )

            def install(_root, packages, _env, _reporter):
                self.assertEqual(packages, ["xetex"])
                self._write_host_tool(root / "bin" / "platform", "xelatex")
                return SimpleNamespace(returncode=0)

            reporter = SimpleNamespace(status=lambda _message: None)
            with patch(
                "texmini.runtime.install_tinytex_packages", side_effect=install
            ) as install_packages:
                runtime.ensure_tinytex_engine(root, "xelatex", env, reporter)

            install_packages.assert_called_once()
            self.assertEqual(
                runtime.managed_executable(root, "xelatex"),
                os.fspath(
                    root
                    / "bin"
                    / "platform"
                    / ("xelatex.bat" if os.name == "nt" else "xelatex")
                ),
            )

    def test_host_lualatex_does_not_mask_corrupt_managed_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            self._write_managed_tools(root)
            managed_lualatex = root / "bin" / "platform" / (
                "lualatex.exe" if os.name == "nt" else "lualatex"
            )
            managed_lualatex.unlink()
            host_bin = Path(directory) / "host-bin"
            host_bin.mkdir()
            host_engine = self._write_host_tool(host_bin, "lualatex")
            env = runtime.tinytex_env(root)
            env["PATH"] = f"{root / 'bin' / 'platform'}{os.pathsep}{host_bin}"
            self.assertEqual(
                runtime.executable_on_path_with_env("lualatex", env),
                os.fspath(host_engine),
            )

            with (
                patch("texmini.runtime.install_tinytex_packages") as install,
                self.assertRaisesRegex(model.TexMiniError, "does not provide lualatex"),
            ):
                runtime.ensure_tinytex_engine(
                    root,
                    "lualatex",
                    env,
                    SimpleNamespace(status=lambda _message: None),
                )

            install.assert_not_called()

    def test_tinytex_environment_retains_host_pygments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            self._write_managed_tools(root)
            host_bin = Path(directory) / "host-bin"
            host_bin.mkdir()
            pygmentize = self._write_host_tool(host_bin, "pygmentize")
            with patch.dict(os.environ, {"PATH": os.fspath(host_bin)}):
                env = runtime.tinytex_env(root)
                self.assertEqual(
                    runtime.executable_on_path_with_env("pygmentize", env),
                    os.fspath(pygmentize),
                )

    def test_runtime_prerequisite_retains_host_perl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            host_bin = Path(directory)
            perl = self._write_host_tool(host_bin, "perl")
            with patch.dict(os.environ, {"PATH": os.fspath(host_bin)}):
                self.assertEqual(runtime.executable_on_path("perl"), os.fspath(perl))
                runtime.check_runtime_prerequisites("darwin")

    def test_common_runtime_mappings_cover_font_and_eps_dependencies(self) -> None:
        self.assertEqual(runtime.common_texlive_package_for_file("8r.enc"), "dvips")
        self.assertEqual(runtime.common_texlive_package_for_file("tcrm0700.tfm"), "ec")
        self.assertEqual(runtime.DIRECT_TOOL_PACKAGES["repstopdf"], "epstopdf")


if __name__ == "__main__":
    unittest.main()
