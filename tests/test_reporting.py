from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from texmini import model, reporting


class ReportingTest(unittest.TestCase):
    def test_reporter_flushes_status_before_command(self) -> None:
        events: list[str] = []
        stream = Mock()
        stream.write.side_effect = lambda value: events.append(f"write:{value.strip()}")
        stream.flush.side_effect = lambda: events.append("flush")

        with patch("sys.stdout", stream):
            reporting.Reporter().status("Compiling paper.tex...")
        self.assertEqual(events[:2], ["write:Compiling paper.tex...", "write:"])
        self.assertIn("flush", events)

    def test_quiet_command_captures_output(self) -> None:
        completed = subprocess.CompletedProcess(["tool"], 0, "routine output\n", None)
        with patch("subprocess.run", return_value=completed) as run:
            result = reporting.run_command(["tool"], reporter=reporting.Reporter())

        self.assertEqual(result.stdout, "routine output\n")
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.STDOUT)

    def test_verbose_command_tees_output(self) -> None:
        process = SimpleNamespace(stdout=iter(["first\n", "second\n"]), wait=lambda: 0)
        output = io.StringIO()
        with patch("subprocess.Popen", return_value=process), redirect_stdout(output):
            result = reporting.run_command(
                ["tool"], reporter=reporting.Reporter(verbose=True)
            )

        self.assertEqual(result.stdout, "first\nsecond\n")
        self.assertEqual(output.getvalue(), "first\nsecond\n")

    def test_gpg_warning_is_concise_and_deduplicated(self) -> None:
        reporter = reporting.Reporter()
        errors = io.StringIO()
        with redirect_stderr(errors):
            reporter.observe_output("package repository not verified: gpg unavailable")
            reporter.observe_output("package repository not verified: gpg unavailable")

        self.assertEqual(
            errors.getvalue().count("could not verify repository signatures"), 1
        )
        self.assertNotIn("package repository", errors.getvalue())
        self.assertIn("GnuPG", errors.getvalue())
        self.assertIn("This build is continuing", errors.getvalue())
        self.assertIn("future package installations", errors.getvalue())
        self.assertNotIn("rerun texMini", errors.getvalue())

    def test_windows_gpg_guidance_does_not_recommend_homebrew(self) -> None:
        with patch("sys.platform", "win32"):
            guidance = reporting.gpg_install_guidance()

        self.assertIn("Windows", guidance)
        self.assertNotIn("brew", guidance)

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

            warnings = reporting.document_warnings(log)

        self.assertEqual(len(warnings), 3)
        self.assertNotIn("Overfull", "\n".join(warnings))

    def test_primary_error_extracts_source_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "broken.log"
            log.write_text(
                "! Undefined control sequence.\nl.4 \\doesnotexist\n", encoding="utf-8"
            )

            error = reporting.primary_latex_error(log, "broken.tex", [])

        self.assertEqual(
            error, model.PrimaryError("Undefined control sequence", "broken.tex", 4)
        )

    def test_primary_error_attributes_explicit_line_to_included_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "(./paper.tex\n"
                " (./sections/body.tex\n"
                "./sections/body.tex:17: Undefined control sequence.\n",
                encoding="utf-8",
            )

            error = reporting.primary_latex_error(
                log, "docs/paper.tex", []
            )

        self.assertEqual(
            error,
            model.PrimaryError(
                "Undefined control sequence",
                os.path.normpath("docs/sections/body.tex"),
                17,
            ),
        )

    def test_primary_error_uses_active_included_source_for_classic_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "(./paper.tex\n"
                " (./sections/body.tex\n"
                "! Undefined control sequence.\n"
                "l.9 \\undefinedincludedcommand\n",
                encoding="utf-8",
            )

            error = reporting.primary_latex_error(
                log, "docs/paper.tex", []
            )

        self.assertEqual(
            error,
            model.PrimaryError(
                "Undefined control sequence",
                os.path.normpath("docs/sections/body.tex"),
                9,
            ),
        )

    def test_primary_error_falls_back_to_top_level_after_include_closes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "(./paper.tex\n"
                " (./sections/body.tex\n"
                ")\n"
                "! Undefined control sequence.\n"
                "l.23 \\undefinedmaincommand\n",
                encoding="utf-8",
            )

            error = reporting.primary_latex_error(
                log, "docs/paper.tex", []
            )

        self.assertEqual(
            error,
            model.PrimaryError(
                "Undefined control sequence", os.path.normpath("docs/paper.tex"), 23
            ),
        )

    def test_primary_error_prefers_missing_file(self) -> None:
        error = reporting.primary_latex_error(
            Path("absent.log"), "paper.tex", ["geometry.sty"]
        )
        self.assertEqual(error, model.PrimaryError("geometry.sty is missing"))

    def test_primary_error_names_missing_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "! LaTeX Error: File `sections/analysis.tex' not found.\n"
                "! Emergency stop.\n",
                encoding="utf-8",
            )

            error = reporting.primary_latex_error(log, "paper.tex", [])

        self.assertEqual(
            error,
            model.PrimaryError(
                f"{os.path.normpath('sections/analysis.tex')} is missing"
            ),
        )

    def test_primary_error_names_missing_local_input_from_invocation_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "! LaTeX Error: File `./sections/missing chapter.tex' not found.\n",
                encoding="utf-8",
            )

            error = reporting.primary_latex_error(
                log, "docs/paper.tex", []
            )

        self.assertEqual(
            error,
            model.PrimaryError(
                f"{os.path.normpath('docs/sections/missing chapter.tex')} is missing"
            ),
        )

    def test_primary_error_tolerates_malformed_and_missing_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.log"
            malformed = Path(directory) / "malformed.log"
            malformed.write_bytes(
                b"(./paper.tex\n! Undefined control sequence.\xff\nl.not-a-line nope\n"
            )

            self.assertIsNone(
                reporting.primary_latex_error(missing, "paper.tex", [])
            )
            self.assertEqual(
                reporting.primary_latex_error(malformed, "paper.tex", []),
                model.PrimaryError("Undefined control sequence.\ufffd"),
            )

    def test_log_read_error_does_not_hide_underlying_failure(self) -> None:
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", side_effect=OSError("log disappeared")
        ):
            self.assertIsNone(
                reporting.primary_latex_error(Path("paper.log"), "paper.tex", [])
            )
            self.assertEqual(reporting.document_warnings(Path("paper.log")), [])

    def test_incomplete_warnings_select_content_loss(self) -> None:
        warnings = [
            "Missing character: There is no 東 in font Latin Modern Roman!",
            "LaTeX Warning: There were undefined citations.",
            "Package biblatex Warning: Please (re)run Biber.",
        ]

        incomplete = reporting.incomplete_document_warnings(warnings)

        self.assertEqual(incomplete, warnings[:2])

    def test_incomplete_warnings_cover_standard_reference_word_order(self) -> None:
        warnings = [
            "LaTeX Warning: Reference `sec:missing' on page 1 undefined.",
            "LaTeX Warning: Citation `missing' on page 1 undefined.",
        ]

        self.assertEqual(
            reporting.incomplete_document_warnings(warnings), warnings
        )

    def test_nonverbose_failure_has_exact_attributed_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                log = Path("docs/paper.log")
                log.parent.mkdir()
                log.write_text(
                    "(./paper.tex\n"
                    " (./sections/body.tex\n"
                    "./sections/body.tex:17: Undefined control sequence.\n",
                    encoding="utf-8",
                )
                error = reporting.primary_latex_error(
                    log, "docs/paper.tex", []
                )
                outcome = model.BuildOutcome(
                    12,
                    0.1,
                    False,
                    failure_kind=model.FailureKind.ORDINARY,
                    primary_error=error,
                    layout=model.BuildLayout.beside_source("docs/paper.tex"),
                )
                errors = io.StringIO()
                with redirect_stderr(errors):
                    reporting.report_failure(
                        outcome, "docs/paper.tex", True, reporting.Reporter()
                    )
            finally:
                os.chdir(previous)

        included = os.path.normpath("docs/sections/body.tex")
        log = os.path.normpath("docs/paper.log")
        self.assertEqual(
            errors.getvalue(),
            "Build failed: TeX reported: Undefined control sequence "
            f"at {included}:17\n"
            f"See {log} for complete diagnostics.\n"
            "Run with --verbose to show complete tool output.\n",
        )

    def test_missing_project_input_is_not_described_as_a_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                log = Path("docs/paper.log")
                log.parent.mkdir()
                log.write_text(
                    "! LaTeX Error: File `./sections/missing.tex' not found.\n",
                    encoding="utf-8",
                )
                missing_files = ("./sections/missing.tex",)
                error = reporting.primary_latex_error(
                    log, "docs/paper.tex", list(missing_files)
                )
                outcome = model.BuildOutcome(
                    1,
                    0.1,
                    False,
                    failure_kind=model.FailureKind.UNMAPPED,
                    missing_files=missing_files,
                    unmapped_files=missing_files,
                    primary_error=error,
                    layout=model.BuildLayout.beside_source("docs/paper.tex"),
                )
                errors = io.StringIO()
                with redirect_stderr(errors):
                    reporting.report_failure(
                        outcome, "docs/paper.tex", True, reporting.Reporter()
                    )
            finally:
                os.chdir(previous)

        missing = os.path.normpath("docs/sections/missing.tex")
        log = os.path.normpath("docs/paper.log")
        self.assertEqual(
            errors.getvalue(),
            f"Build failed: TeX reported: {missing} is missing\n"
            "Missing project files are not installed automatically: "
            "./sections/missing.tex\n"
            f"See {log} for complete diagnostics.\n"
            "Run with --verbose to show complete tool output.\n",
        )
        self.assertNotIn("map", errors.getvalue().lower())

    def test_subdirectory_style_is_described_as_a_project_file(self) -> None:
        outcome = model.BuildOutcome(
            1,
            0.1,
            False,
            failure_kind=model.FailureKind.UNMAPPED,
            missing_files=("styles/local.sty",),
            unmapped_files=("styles/local.sty",),
            primary_error=model.PrimaryError("styles/local.sty is missing"),
        )
        errors = io.StringIO()
        with redirect_stderr(errors):
            reporting.report_failure(
                outcome, "paper.tex", True, reporting.Reporter()
            )

        self.assertIn("Missing project files", errors.getvalue())
        self.assertNotIn("Could not map", errors.getvalue())

    def test_explicit_ownership_does_not_guess_log_only_nested_file(self) -> None:
        outcome = model.BuildOutcome(
            1,
            0.1,
            False,
            failure_kind=model.FailureKind.UNMAPPED,
            missing_files=("styles/local.sty", "nested/gamma.sty"),
            unmapped_files=("styles/local.sty", "nested/gamma.sty"),
            project_files=("styles/local.sty",),
            primary_error=model.PrimaryError("styles/local.sty is missing"),
        )
        errors = io.StringIO()

        with redirect_stderr(errors):
            reporting.report_failure(
                outcome, "paper.tex", True, reporting.Reporter()
            )

        self.assertIn(
            "Missing project files are not installed automatically: "
            "styles/local.sty",
            errors.getvalue(),
        )
        self.assertIn(
            "Could not map missing TeX files to packages: nested/gamma.sty",
            errors.getvalue(),
        )

    def test_verbose_failure_omits_nonverbose_hint(self) -> None:
        outcome = model.BuildOutcome(
            2,
            0.1,
            False,
            failure_kind=model.FailureKind.ORDINARY,
        )
        errors = io.StringIO()
        with redirect_stderr(errors):
            reporting.report_failure(
                outcome, "paper.tex", True, reporting.Reporter(verbose=True)
            )

        self.assertEqual(
            errors.getvalue(),
            "Build failed: TeX or latexmk failed, but no primary TeX error "
            "could be identified.\n",
        )

    def test_failure_reports_tlmgr_install_error_after_missing_file(self) -> None:
        outcome = model.BuildOutcome(
            7,
            0.1,
            False,
            failure_kind="install_failed",
            primary_error=model.PrimaryError("geometry.sty is missing"),
        )
        errors = io.StringIO()
        with redirect_stderr(errors):
            reporting.report_failure(outcome, "paper.tex", True, reporting.Reporter())

        self.assertIn("geometry.sty is missing", errors.getvalue())
        self.assertIn("TeX Live package installation failed", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
