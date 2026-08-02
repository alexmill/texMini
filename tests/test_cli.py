from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from texmini import cli


class CliTest(unittest.TestCase):
    def test_parse_args_defaults_to_incremental_pdflatex(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            engine, clean, verbose, auto_install, args, bib_files, tex_file = cli.parse_args(
                ["paper.tex", "refs.bib"]
            )

        self.assertEqual(engine, "pdflatex")
        self.assertFalse(clean)
        self.assertFalse(verbose)
        self.assertTrue(auto_install)
        self.assertEqual(args, ["paper.tex"])
        self.assertEqual(bib_files, ["refs.bib"])
        self.assertEqual(tex_file, "paper.tex")

    def test_parse_args_enables_clean_and_verbose(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            _, clean, verbose, _, args, _, _ = cli.parse_args(["--clean", "--verbose", "paper.tex"])

        self.assertTrue(clean)
        self.assertTrue(verbose)
        self.assertEqual(args, ["paper.tex"])

    def test_parse_args_uses_new_clean_environment(self) -> None:
        with patch.dict(os.environ, {"TEXMINI_CLEAN": "true", "TEXMINI_AUTO_CLEAN": "false"}, clear=True):
            _, clean, _, _, _, _, _ = cli.parse_args(["paper.tex"])

        self.assertTrue(clean)

    def test_parse_args_disables_auto_install(self) -> None:
        with patch.dict(os.environ, {"TEXMINI_AUTO_INSTALL": "false"}, clear=True):
            _, _, _, auto_install, _, _, _ = cli.parse_args(["paper.tex"])

        self.assertFalse(auto_install)

    def test_parse_args_selects_supported_engine(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            engine, _, _, _, args, _, _ = cli.parse_args(["--engine", "lualatex", "paper.tex"])

        self.assertEqual(engine, "lualatex")
        self.assertEqual(args, ["paper.tex"])

    def test_detect_tex_file_auto_detects_single_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("source", encoding="utf-8")
                args: list[str] = []
                detected = cli.detect_tex_file(args, None)
            finally:
                os.chdir(previous)

        self.assertEqual(detected, "paper.tex")
        self.assertEqual(args, ["paper.tex"])

    def test_explicit_missing_bibliography_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("\\bibliography{missing}\n", encoding="utf-8")
            with self.assertRaisesRegex(cli.TexMiniError, "not found"):
                cli.check_bibliography(str(source), [str(Path(directory) / "missing.bib")])

    def test_source_cache_refreshes_after_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("first", encoding="utf-8")
            self.assertEqual(cli.read_source_file(str(source)), "first")
            source.write_text("second version", encoding="utf-8")
            self.assertEqual(cli.read_source_file(str(source)), "second version")

    def test_source_requirements_extract_classes_packages_and_biber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text(
                "\\documentclass{memoir}\n\\usepackage{geometry,microtype}\n"
                "\\usepackage[backend=biber]{biblatex}\n",
                encoding="utf-8",
            )
            files, packages = cli.tex_source_requirements(str(source))

        self.assertEqual(files, ["memoir.cls", "geometry.sty", "microtype.sty", "biblatex.sty"])
        self.assertEqual(packages, ["biber"])

    def test_log_requirements_extract_missing_file_font_and_biber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "! LaTeX Error: File `geometry.sty' not found.\n"
                "mktextfm tcrm1000\n"
                "Package biblatex Warning: Please (re)run Biber on the file:\n",
                encoding="utf-8",
            )
            files, packages = cli.tex_log_requirements(log)

        self.assertEqual(files, ["geometry.sty", "tcrm1000.tfm"])
        self.assertEqual(packages, ["biber"])

    def test_resolver_uses_cached_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            cache.write_text('{"custom.sty": "custom-package"}\n', encoding="utf-8")
            with patch("texmini.cli.run_command") as run:
                resolved = cli.resolve_tinytex_packages(Path("TinyTeX"), ["custom.sty"], cache, env={})

        self.assertEqual(resolved, {"custom.sty": "custom-package"})
        run.assert_not_called()

    def test_resolver_uses_tlmgr_search_and_updates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "map.json"
            result = SimpleNamespace(returncode=0, stdout="custom-package: texmf-dist/tex/latex/custom/custom.sty\n")
            with patch("texmini.cli.run_command", return_value=result):
                resolved = cli.resolve_tinytex_packages(Path("TinyTeX"), ["custom.sty"], cache, env={})

            self.assertEqual(resolved, {"custom.sty": "custom-package"})
            self.assertIn("custom-package", cache.read_text(encoding="utf-8"))

    def test_xelatex_engine_is_installed_on_demand(self) -> None:
        reporter = cli.Reporter()
        with (
            patch("texmini.cli.executable_on_path_with_env", return_value=None),
            patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
            redirect_stdout(io.StringIO()),
        ):
            cli.ensure_tinytex_engine(Path("TinyTeX"), "xelatex", {}, reporter)

        self.assertEqual(install.call_args.args[1], ["xetex"])

    def test_platform_selects_musl_linux_asset(self) -> None:
        with patch("sys.platform", "linux"), patch("platform.machine", return_value="x86_64"), patch(
            "platform.libc_ver", return_value=("musl", "1.2")
        ):
            self.assertEqual(cli.tinytex_platform_key(), "linuxmusl-x86_64")

    def test_no_clean_is_passed_to_latexmk_instead_of_recognized(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            _, clean, _, _, args, _, _ = cli.parse_args(["--no-clean", "paper.tex"])

        self.assertFalse(clean)
        self.assertEqual(args, ["--no-clean", "paper.tex"])

    def test_help_describes_calm_cli_options(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            cli.print_help()

        text = output.getvalue()
        self.assertIn("--clean", text)
        self.assertIn("--verbose", text)
        self.assertIn("--no-install", text)
        self.assertNotIn("--no-clean", text)

    def test_reporter_flushes_status_before_command(self) -> None:
        events: list[str] = []
        stream = Mock()
        stream.write.side_effect = lambda value: events.append(f"write:{value.strip()}")
        stream.flush.side_effect = lambda: events.append("flush")

        with patch("sys.stdout", stream):
            cli.Reporter().status("Compiling paper.tex...")
        self.assertEqual(events[:2], ["write:Compiling paper.tex...", "write:"])
        self.assertIn("flush", events)

    def test_quiet_command_captures_output(self) -> None:
        completed = subprocess.CompletedProcess(["tool"], 0, "routine output\n", None)
        with patch("subprocess.run", return_value=completed) as run:
            result = cli.run_command(["tool"], reporter=cli.Reporter())

        self.assertEqual(result.stdout, "routine output\n")
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.STDOUT)

    def test_verbose_command_tees_output(self) -> None:
        process = SimpleNamespace(stdout=iter(["first\n", "second\n"]), wait=lambda: 0)
        output = io.StringIO()
        with patch("subprocess.Popen", return_value=process), redirect_stdout(output):
            result = cli.run_command(["tool"], reporter=cli.Reporter(verbose=True))

        self.assertEqual(result.stdout, "first\nsecond\n")
        self.assertEqual(output.getvalue(), "first\nsecond\n")

    def test_gpg_warning_is_concise_and_deduplicated(self) -> None:
        reporter = cli.Reporter()
        errors = io.StringIO()
        with redirect_stderr(errors):
            reporter.observe_output("package repository not verified: gpg unavailable")
            reporter.observe_output("package repository not verified: gpg unavailable")

        self.assertEqual(errors.getvalue().count("could not verify repository signatures"), 1)
        self.assertNotIn("package repository", errors.getvalue())

    def test_cleanup_keeps_sources_pdf_and_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in ("tex", "bib", "pdf", "aux", "bbl", "bcf-SAVE-ERROR", "log"):
                (root / f"paper.{suffix}").write_text(suffix, encoding="utf-8")
            (root / "notes.txt").write_text("keep", encoding="utf-8")

            cli.cleanup_auxiliary_files(str(root / "paper.tex"))

            self.assertTrue((root / "paper.tex").exists())
            self.assertTrue((root / "paper.bib").exists())
            self.assertTrue((root / "paper.pdf").exists())
            self.assertTrue((root / "notes.txt").exists())
            self.assertFalse((root / "paper.aux").exists())
            self.assertFalse((root / "paper.bbl").exists())
            self.assertFalse((root / "paper.bcf-SAVE-ERROR").exists())
            self.assertFalse((root / "paper.log").exists())

    def test_document_warnings_filters_layout_chatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "LaTeX Warning: Reference `x' on page 1 undefined.\n"
                "Package biblatex Warning: Please (re)run Biber.\n"
                "Overfull \\hbox (2.0pt too wide)\n"
                "Missing character: There is no Ω in font cmr10!\n",
                encoding="utf-8",
            )

            warnings = cli.document_warnings(log)

        self.assertEqual(len(warnings), 3)
        self.assertNotIn("Overfull", "\n".join(warnings))

    def test_primary_error_extracts_source_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "broken.log"
            log.write_text("! Undefined control sequence.\nl.4 \\doesnotexist\n", encoding="utf-8")

            error = cli.primary_latex_error(log, "broken.tex", [])

        self.assertEqual(error, cli.PrimaryError("Undefined control sequence", "broken.tex", 4))

    def test_primary_error_prefers_missing_file(self) -> None:
        error = cli.primary_latex_error(Path("absent.log"), "paper.tex", ["geometry.sty"])
        self.assertEqual(error, cli.PrimaryError("geometry.sty is missing"))

    def test_archive_validation_rejects_escape(self) -> None:
        safe = tarfile.TarInfo("TinyTeX/bin/tool")
        cli.validate_tinytex_archive_member(safe)
        with self.assertRaises(cli.TexMiniError):
            cli.validate_tinytex_archive_member(tarfile.TarInfo("../escape"))

    def test_release_lookup_uses_github_token_when_available(self) -> None:
        release = io.BytesIO(
            b'{"assets":[{"name":"TinyTeX-0-test-v1.tar.xz","browser_download_url":"https://archive","digest":"sha256:abc"}]}'
        )
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "test-token", "TEXMINI_TINYTEX_BUNDLE": "TinyTeX-0"}),
            patch("texmini.cli.tinytex_platform_key", return_value="test"),
            patch("urllib.request.urlopen", return_value=release) as urlopen,
        ):
            asset = cli.latest_tinytex_asset()

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(request.get_header("User-agent"), f"texmini/{cli.__version__}")
        self.assertEqual(asset, ("TinyTeX-0-test-v1.tar.xz", "https://archive", "sha256:abc"))

    def _tinytex_archive(self) -> bytes:
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:xz") as archive:
            info = tarfile.TarInfo("TinyTeX/bin/test/latexmk")
            content = b"latexmk"
            info.size = len(content)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(content))
        return payload.getvalue()

    def test_tinytex_archive_verifies_checksum_before_extraction(self) -> None:
        archive = self._tinytex_archive()
        digest = f"sha256:{hashlib.sha256(archive).hexdigest()}"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch.dict(os.environ, {"TEXMINI_TINYTEX_BUNDLE": "TinyTeX-1"}),
                patch("texmini.cli.executable_on_path", return_value="/usr/bin/perl"),
                patch("texmini.cli.latest_tinytex_asset", return_value=("TinyTeX-1-test.tar.xz", "https://test", digest)),
                patch("urllib.request.urlopen", return_value=io.BytesIO(archive)),
                patch("texmini.cli.update_tinytex_manager"),
            ):
                cli.install_tinytex_archive(root)

            self.assertTrue((root / "bin" / "test" / "latexmk").is_file())

    def test_checksum_failure_stops_before_extraction(self) -> None:
        archive = self._tinytex_archive()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch.dict(os.environ, {"TEXMINI_TINYTEX_BUNDLE": "TinyTeX-1"}),
                patch("texmini.cli.executable_on_path", return_value="/usr/bin/perl"),
                patch(
                    "texmini.cli.latest_tinytex_asset",
                    return_value=("TinyTeX-1-test.tar.xz", "https://test", "sha256:" + "0" * 64),
                ),
                patch("urllib.request.urlopen", return_value=io.BytesIO(archive)),
                patch("tarfile.open") as tar_open,
            ):
                with self.assertRaisesRegex(cli.TexMiniError, "Checksum verification failed"):
                    cli.install_tinytex_archive(root)
            tar_open.assert_not_called()
            self.assertFalse(root.exists())

    def test_archive_without_digest_is_supported(self) -> None:
        archive = self._tinytex_archive()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch.dict(os.environ, {"TEXMINI_TINYTEX_BUNDLE": "TinyTeX-1"}),
                patch("texmini.cli.executable_on_path", return_value="/usr/bin/perl"),
                patch("texmini.cli.latest_tinytex_asset", return_value=("TinyTeX-1-test.tar.xz", "https://test", None)),
                patch("urllib.request.urlopen", return_value=io.BytesIO(archive)),
                patch("texmini.cli.update_tinytex_manager"),
            ):
                cli.install_tinytex_archive(root)
            self.assertTrue(root.exists())

    def _managed_root(self, directory: str) -> Path:
        root = Path(directory) / "TinyTeX"
        bin_dir = root / "bin" / "test"
        bin_dir.mkdir(parents=True)
        for name in ("latexmk", "biber", "pdflatex", "kpsewhich", "tlmgr"):
            (bin_dir / name).write_text("", encoding="utf-8")
        return root

    def test_backend_preinstalls_source_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("\\usepackage{geometry}\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=["geometry.sty"]),
                    patch("texmini.cli.resolve_tinytex_packages", return_value={"geometry.sty": "geometry"}),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                    patch("texmini.cli.run_tinytex_compile", return_value=SimpleNamespace(returncode=0)),
                ):
                    outcome = cli.run_tinytex_backend("pdflatex", True, False, "paper.tex", ["paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(install.call_args.args[1], ["geometry"])

    def test_backend_continues_beyond_five_dependency_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text("! LaTeX Error: File `dep.sty' not found.\n", encoding="utf-8")
            compile_results = [SimpleNamespace(returncode=1) for _ in range(7)] + [SimpleNamespace(returncode=0)]
            resolutions = [{"dep.sty": f"package-{index}"} for index in range(7)]
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch("texmini.cli.resolve_tinytex_packages", side_effect=resolutions),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                    patch("texmini.cli.run_tinytex_compile", side_effect=compile_results),
                ):
                    outcome = cli.run_tinytex_backend("pdflatex", True, False, "paper.tex", ["paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(install.call_count, 7)

    def test_backend_stops_at_twenty_install_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text("! LaTeX Error: File `dep.sty' not found.\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch(
                        "texmini.cli.resolve_tinytex_packages",
                        side_effect=[{"dep.sty": f"package-{index}"} for index in range(21)],
                    ),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                    patch("texmini.cli.run_tinytex_compile", return_value=SimpleNamespace(returncode=1)),
                ):
                    outcome = cli.run_tinytex_backend("pdflatex", True, False, "paper.tex", ["paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.failure_kind, "ceiling")
        self.assertEqual(install.call_count, 20)

    def test_backend_reports_unmapped_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text("! LaTeX Error: File `unknown.sty' not found.\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch("texmini.cli.resolve_tinytex_packages", return_value={}),
                    patch("texmini.cli.run_tinytex_compile", return_value=SimpleNamespace(returncode=1)),
                ):
                    outcome = cli.run_tinytex_backend("pdflatex", True, False, "paper.tex", ["paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.failure_kind, "unmapped")
        self.assertEqual(outcome.unmapped_files, ("unknown.sty",))

    def test_no_install_classifies_missing_package_without_installing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("\\usepackage{geometry}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text("! LaTeX Error: File `geometry.sty' not found.\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=["geometry.sty"]),
                    patch("texmini.cli.install_tinytex_packages") as install,
                    patch("texmini.cli.run_tinytex_compile", return_value=SimpleNamespace(returncode=2)),
                ):
                    outcome = cli.run_tinytex_backend("pdflatex", False, False, "paper.tex", ["paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 2)
        self.assertEqual(outcome.failure_kind, "disabled")
        install.assert_not_called()

    def test_install_failure_returns_tlmgr_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("\\usepackage{geometry}\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=["geometry.sty"]),
                    patch("texmini.cli.resolve_tinytex_packages", return_value={"geometry.sty": "geometry"}),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=7)),
                ):
                    outcome = cli.run_tinytex_backend("pdflatex", True, False, "paper.tex", ["paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 7)
        self.assertEqual(outcome.failure_kind, "install_failed")

    def test_main_retains_build_files_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("source", encoding="utf-8")
                Path("paper.aux").write_text("state", encoding="utf-8")
                Path("paper.pdf").write_text("pdf", encoding="utf-8")
                outcome = cli.BuildOutcome(0, 0.14, True)
                output = io.StringIO()
                with patch("texmini.cli.run_tinytex_backend", return_value=outcome), redirect_stdout(output):
                    result = cli.main(["paper.tex"])
                auxiliary_retained = Path("paper.aux").exists()
            finally:
                os.chdir(previous)

        self.assertEqual(result, 0)
        self.assertTrue(auxiliary_retained)
        self.assertIn("Built paper.pdf in 0.14s", output.getvalue())
        self.assertIn("retained for faster rebuilds", output.getvalue())

    def test_main_clean_removes_build_files_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("source", encoding="utf-8")
                Path("paper.aux").write_text("state", encoding="utf-8")
                Path("paper.pdf").write_text("pdf", encoding="utf-8")
                outcome = cli.BuildOutcome(0, 0.2, False)
                output = io.StringIO()
                with patch("texmini.cli.run_tinytex_backend", return_value=outcome), redirect_stdout(output):
                    result = cli.main(["--clean", "paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(result, 0)
        self.assertFalse(Path(directory, "paper.aux").exists())
        self.assertIn("paper.pdf is up to date", output.getvalue())
        self.assertIn("Removed auxiliary build files", output.getvalue())

    def test_main_failure_reports_line_and_partial_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("broken.tex").write_text("source", encoding="utf-8")
                Path("broken.log").write_text("log", encoding="utf-8")
                outcome = cli.BuildOutcome(
                    3,
                    0.2,
                    True,
                    failure_kind="ordinary",
                    primary_error=cli.PrimaryError("Undefined control sequence", "broken.tex", 4),
                )
                errors = io.StringIO()
                with patch("texmini.cli.run_tinytex_backend", return_value=outcome), redirect_stderr(errors):
                    result = cli.main(["broken.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(result, 3)
        text = errors.getvalue()
        self.assertIn("Build failed: Undefined control sequence at broken.tex:4", text)
        self.assertIn("See broken.log", text)
        self.assertIn("broken.pdf may be incomplete", text)

    def test_main_no_install_explains_disabled_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("source", encoding="utf-8")
                outcome = cli.BuildOutcome(
                    1,
                    0.1,
                    False,
                    failure_kind="disabled",
                    missing_files=("geometry.sty",),
                    primary_error=cli.PrimaryError("geometry.sty is missing"),
                )
                errors = io.StringIO()
                with patch("texmini.cli.run_tinytex_backend", return_value=outcome), redirect_stderr(errors):
                    result = cli.main(["--no-install", "paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(result, 1)
        self.assertIn("geometry.sty is missing", errors.getvalue())
        self.assertIn("disabled by --no-install", errors.getvalue())

    def test_failure_reports_tlmgr_install_error_after_missing_file(self) -> None:
        outcome = cli.BuildOutcome(
            7,
            0.1,
            False,
            failure_kind="install_failed",
            primary_error=cli.PrimaryError("geometry.sty is missing"),
        )
        errors = io.StringIO()
        with redirect_stderr(errors):
            cli.report_failure(outcome, "paper.tex", True, cli.Reporter())

        self.assertIn("geometry.sty is missing", errors.getvalue())
        self.assertIn("TeX Live package installation failed", errors.getvalue())

    def test_compile_uses_noninteractive_file_line_diagnostics(self) -> None:
        with patch("texmini.cli.run_command", return_value=SimpleNamespace(returncode=1)) as run:
            cli.run_tinytex_compile("pdflatex", ["paper.tex"], Path("TinyTeX"), env={})

        self.assertEqual(
            run.call_args.args[0],
            ["latexmk", "-pdf", "-interaction=nonstopmode", "-file-line-error", "paper.tex"],
        )

    def test_verbose_install_subcommand_is_supported(self) -> None:
        with patch("texmini.cli.install_tinytex", return_value=0) as install:
            result = cli.main(["--verbose", "install-tinytex"])

        self.assertEqual(result, 0)
        install.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
