from __future__ import annotations

import io
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
        self.assertIn("then rerun texMini", errors.getvalue())

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
            error, model.PrimaryError("sections/analysis.tex is missing")
        )

    def test_incomplete_warnings_select_content_loss(self) -> None:
        warnings = [
            "Missing character: There is no 東 in font Latin Modern Roman!",
            "LaTeX Warning: There were undefined citations.",
            "Package biblatex Warning: Please (re)run Biber.",
        ]

        incomplete = reporting.incomplete_document_warnings(warnings)

        self.assertEqual(incomplete, warnings[:2])

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
