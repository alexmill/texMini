from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from texmini import cli, model


class CliTest(unittest.TestCase):
    def test_parse_args_defaults_to_incremental_build(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = cli.parse_args(["paper.tex", "refs.bib"])

        self.assertIsNone(config.engine)
        self.assertFalse(config.clean)
        self.assertFalse(config.verbose)
        self.assertTrue(config.auto_install)
        self.assertFalse(config.watch)
        self.assertFalse(config.shell_escape)
        self.assertEqual(config.latexmk_args, ["paper.tex"])
        self.assertEqual(config.bib_files, ["refs.bib"])
        self.assertEqual(config.tex_file, "paper.tex")

    def test_parse_args_enables_clean_and_verbose(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = cli.parse_args(["--clean", "--verbose", "paper.tex"])

        self.assertTrue(config.clean)
        self.assertTrue(config.verbose)
        self.assertEqual(config.latexmk_args, ["paper.tex"])

    def test_parse_args_uses_new_clean_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"TEXMINI_CLEAN": "true", "TEXMINI_AUTO_CLEAN": "false"},
            clear=True,
        ):
            config = cli.parse_args(["paper.tex"])

        self.assertTrue(config.clean)

    def test_parse_args_disables_auto_install(self) -> None:
        with patch.dict(os.environ, {"TEXMINI_AUTO_INSTALL": "false"}, clear=True):
            config = cli.parse_args(["paper.tex"])

        self.assertFalse(config.auto_install)

    def test_parse_args_selects_supported_engine(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = cli.parse_args(["--engine", "lualatex", "paper.tex"])

        self.assertEqual(config.engine, "lualatex")
        self.assertEqual(config.latexmk_args, ["paper.tex"])

    def test_parse_args_supports_watch_shell_escape_and_synctex(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = cli.parse_args(
                ["-pvc", "-shell-escape", "-synctex=1", "paper.tex"]
            )

        self.assertTrue(config.watch)
        self.assertTrue(config.shell_escape)
        self.assertEqual(
            config.latexmk_args, ["-shell-escape", "-synctex=1", "paper.tex"]
        )

    def test_parse_args_rejects_clean_watch_and_viewer_controls(self) -> None:
        with self.assertRaisesRegex(model.TexMiniError, "--clean cannot be combined"):
            cli.parse_args(["--clean", "--watch", "paper.tex"])
        with self.assertRaisesRegex(model.TexMiniError, "does not launch or control"):
            cli.parse_args(["--watch", "-view=pdf", "paper.tex"])

    def test_parse_args_accepts_view_none_in_watch_mode(self) -> None:
        config = cli.parse_args(["--watch", "-view=none", "paper.tex"])
        self.assertTrue(config.watch)
        self.assertNotIn("-view=none", config.latexmk_args)

    def test_no_clean_is_passed_to_latexmk_instead_of_recognized(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = cli.parse_args(["--no-clean", "paper.tex"])

        self.assertFalse(config.clean)
        self.assertEqual(config.latexmk_args, ["--no-clean", "paper.tex"])

    def test_help_describes_calm_cli_options(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            cli.print_help()

        text = output.getvalue()
        self.assertIn("--clean", text)
        self.assertIn("--watch", text)
        self.assertIn("--shell-escape", text)
        self.assertIn("--verbose", text)
        self.assertIn("--no-install", text)
        self.assertNotIn("--no-clean", text)

    def _managed_root(self, directory: str) -> Path:
        root = Path(directory) / "TinyTeX"
        bin_dir = root / "bin" / "test"
        bin_dir.mkdir(parents=True)
        for name in ("latexmk", "biber", "pdflatex", "kpsewhich", "tlmgr"):
            (bin_dir / name).write_text("", encoding="utf-8")
        return root

    def test_main_retains_build_files_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("source", encoding="utf-8")
                Path("paper.aux").write_text("state", encoding="utf-8")
                Path("paper.pdf").write_text("pdf", encoding="utf-8")
                outcome = model.BuildOutcome(0, 0.14, True)
                output = io.StringIO()
                with (
                    patch("texmini.cli.run_tinytex_backend", return_value=outcome),
                    redirect_stdout(output),
                ):
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
                outcome = model.BuildOutcome(0, 0.2, False)
                output = io.StringIO()
                with (
                    patch("texmini.cli.run_tinytex_backend", return_value=outcome),
                    redirect_stdout(output),
                ):
                    result = cli.main(["--clean", "paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(result, 0)
        self.assertFalse(Path(directory, "paper.aux").exists())
        self.assertIn("paper.pdf is up to date", output.getvalue())
        self.assertIn("Removed auxiliary build files", output.getvalue())

    def test_main_reports_warns_and_cleans_subdirectory_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                source_directory = Path("docs")
                source_directory.mkdir()
                (source_directory / "paper.tex").write_text("source", encoding="utf-8")
                (source_directory / "paper.pdf").write_text("pdf", encoding="utf-8")
                (source_directory / "paper.aux").write_text("state", encoding="utf-8")
                (source_directory / "paper.log").write_text(
                    "LaTeX Warning: There were undefined citations.\n", encoding="utf-8"
                )
                outcome = model.BuildOutcome(0, 0.14, True)
                output = io.StringIO()
                errors = io.StringIO()
                with (
                    patch("texmini.cli.run_tinytex_backend", return_value=outcome),
                    redirect_stdout(output),
                    redirect_stderr(errors),
                ):
                    result = cli.main(["--clean", "docs/paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(result, 0)
        self.assertIn("Built docs/paper.pdf in 0.14s", output.getvalue())
        self.assertIn("undefined citations", errors.getvalue())
        self.assertFalse(Path(directory, "docs", "paper.aux").exists())
        self.assertFalse(Path(directory, "docs", "paper.log").exists())

    def test_main_rejects_missing_source_before_backend_setup(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch("texmini.cli.run_tinytex_backend") as backend,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = cli.main(["missing.tex"])

        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn(
            "LaTeX source file 'missing.tex' does not exist", errors.getvalue()
        )
        backend.assert_not_called()

    def test_main_failure_reports_line_and_partial_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("broken.tex").write_text("source", encoding="utf-8")
                Path("broken.log").write_text("log", encoding="utf-8")
                outcome = model.BuildOutcome(
                    3,
                    0.2,
                    True,
                    failure_kind="ordinary",
                    primary_error=model.PrimaryError(
                        "Undefined control sequence", "broken.tex", 4
                    ),
                )
                errors = io.StringIO()
                with (
                    patch("texmini.cli.run_tinytex_backend", return_value=outcome),
                    redirect_stderr(errors),
                ):
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
                outcome = model.BuildOutcome(
                    1,
                    0.1,
                    False,
                    failure_kind="disabled",
                    missing_files=("geometry.sty",),
                    primary_error=model.PrimaryError("geometry.sty is missing"),
                )
                errors = io.StringIO()
                with (
                    patch("texmini.cli.run_tinytex_backend", return_value=outcome),
                    redirect_stderr(errors),
                ):
                    result = cli.main(["--no-install", "paper.tex"])
            finally:
                os.chdir(previous)

        self.assertEqual(result, 1)
        self.assertIn("geometry.sty is missing", errors.getvalue())
        self.assertIn("disabled by --no-install", errors.getvalue())

    def test_verbose_install_subcommand_is_supported(self) -> None:
        with patch("texmini.cli.install_tinytex", return_value=0) as install:
            result = cli.main(["--verbose", "install-tinytex"])

        self.assertEqual(result, 0)
        install.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
