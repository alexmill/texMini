from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from texmini import build, model, reporting


class BuildTest(unittest.TestCase):
    @staticmethod
    def _managed_root(directory: str) -> Path:
        root = Path(directory) / "TinyTeX"
        binary = root / "bin" / "test"
        binary.mkdir(parents=True)
        (binary / "latexmk").write_text("", encoding="utf-8")
        return root

    def test_cleanup_keeps_sources_pdf_and_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in ("tex", "bib", "pdf", "aux", "bbl", "bcf-SAVE-ERROR", "log"):
                (root / f"paper.{suffix}").write_text(suffix, encoding="utf-8")
            (root / "notes.txt").write_text("keep", encoding="utf-8")
            (root / "missfont.log").write_text("diagnostic", encoding="utf-8")

            build.cleanup_auxiliary_files(str(root / "paper.tex"))

            self.assertTrue((root / "paper.tex").exists())
            self.assertTrue((root / "paper.bib").exists())
            self.assertTrue((root / "paper.pdf").exists())
            self.assertTrue((root / "notes.txt").exists())
            self.assertFalse((root / "paper.aux").exists())
            self.assertFalse((root / "paper.bbl").exists())
            self.assertFalse((root / "paper.bcf-SAVE-ERROR").exists())
            self.assertFalse((root / "paper.log").exists())
            self.assertFalse((root / "missfont.log").exists())

    def test_cleanup_uses_resolved_layout_and_removes_extended_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.tex"
            aux_dir = root / "aux"
            out_dir = root / "build"
            aux_dir.mkdir()
            out_dir.mkdir()
            source.write_text("source", encoding="utf-8")
            (out_dir / "publication.pdf").write_text("pdf", encoding="utf-8")
            for suffix in ("idx", "ind", "gls", "nls", "synctex.gz", "xdy"):
                (aux_dir / f"publication.{suffix}").write_text(
                    "state", encoding="utf-8"
                )
            (aux_dir / "publication.fdb_latexmk").write_text(
                '["makeindex people.idx"] "people.ilg" "people.ind"\n',
                encoding="utf-8",
            )
            (root / "people.ilg").write_text("state", encoding="utf-8")
            (root / "people.ind").write_text("state", encoding="utf-8")
            minted = aux_dir / "_minted-publication"
            minted.mkdir()
            (minted / "cache.pygtex").write_text("cache", encoding="utf-8")
            minted_v3 = aux_dir / "_minted"
            minted_v3.mkdir()
            (minted_v3 / "cache.minted").write_text("cache", encoding="utf-8")
            layout = model.BuildLayout(
                source,
                "publication",
                aux_dir,
                out_dir,
                out_dir / "publication.pdf",
                aux_dir / "publication.log",
            )

            build.cleanup_auxiliary_files(str(source), layout)

            self.assertTrue(source.exists())
            self.assertTrue((out_dir / "publication.pdf").exists())
            self.assertFalse(minted.exists())
            self.assertFalse(minted_v3.exists())
            self.assertFalse(any(aux_dir.iterdir()))
            self.assertFalse((root / "people.ilg").exists())
            self.assertFalse((root / "people.ind").exists())

    def test_resolve_build_layout_parses_latexmk_report(self) -> None:
        report = """Latexmk: Cwd: '/project/docs'
Latexmk: Normalized aux dir, out dir, out2 dir:
  '/project/aux', '/project/build', '/project/build'
Latexmk: Base name of generated files:
  'publication'
"""
        completed = SimpleNamespace(returncode=0, stdout=report)
        with patch("texmini.build.run_command", return_value=completed) as run:
            layout = build.resolve_build_layout(
                "pdflatex",
                ["-outdir=build", "-jobname=publication", "docs/paper.tex"],
                "docs/paper.tex",
                {},
                reporting.Reporter(),
            )

        self.assertEqual(layout.jobname, "publication")
        self.assertEqual(layout.aux_dir, Path("/project/aux"))
        self.assertEqual(layout.pdf_path, Path("/project/build/publication.pdf"))
        self.assertEqual(layout.log_path, Path("/project/aux/publication.log"))
        self.assertIn("-dir-report-only", run.call_args.args[0])

    def test_backend_preinstalls_source_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{geometry}\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files",
                        return_value=["geometry.sty"],
                    ),
                    patch(
                        "texmini.build.resolve_tinytex_packages",
                        return_value={"geometry.sty": "geometry"},
                    ),
                    patch(
                        "texmini.build.install_tinytex_packages",
                        return_value=SimpleNamespace(returncode=0),
                    ) as install,
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=0),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(install.call_args.args[1], ["geometry"])

    def test_backend_uses_latexmk_cd_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            source_directory = Path(directory) / "docs"
            source_directory.mkdir()
            source = source_directory / "paper.tex"
            source.write_text("\\documentclass{article}\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                layout = model.BuildLayout(
                    source,
                    "paper",
                    source_directory,
                    source_directory,
                    source_directory / "paper.pdf",
                    source_directory / "paper.log",
                )

                def compile_document(_engine, arguments, _root, **options):
                    self.assertEqual(arguments, ["docs/paper.tex"])
                    self.assertEqual(
                        options["cwd"].resolve(), Path(directory).resolve()
                    )
                    (source_directory / "paper.pdf").write_text("pdf", encoding="utf-8")
                    return SimpleNamespace(returncode=0)

                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch("texmini.build.resolve_build_layout", return_value=layout),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        side_effect=compile_document,
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "docs/paper.tex", ["docs/paper.tex"]
                    )
                    pdf_exists = (source_directory / "paper.pdf").is_file()
            finally:
                os.chdir(previous)

        self.assertTrue(outcome.pdf_changed)
        self.assertTrue(pdf_exists)

    def test_backend_forces_build_when_requested_synctex_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("source", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=0, stdout=""),
                    ) as compile_document,
                ):
                    build.run_tinytex_backend(
                        "pdflatex",
                        True,
                        False,
                        "paper.tex",
                        ["-synctex=1", "paper.tex"],
                    )
            finally:
                os.chdir(previous)

        self.assertTrue(compile_document.call_args.kwargs["force"])

    def test_backend_names_required_ghostscript_for_eps_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\includegraphics{figure.eps}\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.executable_on_path_with_env", return_value=None
                    ),
                    patch("texmini.build.run_tinytex_compile") as compile_document,
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 1)
        self.assertIn("Ghostscript (gs)", outcome.primary_error.message)
        compile_document.assert_not_called()

    def test_backend_reruns_stale_failed_latexmk_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("source", encoding="utf-8")
            Path(directory, "paper.log").write_text(
                "! Undefined control sequence.\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        side_effect=[
                            SimpleNamespace(
                                returncode=1,
                                stdout="Latexmk: Nothing to do for 'paper.tex'.\n",
                            ),
                            SimpleNamespace(returncode=1, stdout="fresh failure\n"),
                        ],
                    ) as compile_document,
                    redirect_stdout(io.StringIO()),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 1)
        self.assertEqual(compile_document.call_count, 2)
        self.assertTrue(compile_document.call_args.kwargs["force"])

    def test_backend_continues_beyond_five_dependency_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\documentclass{article}\n", encoding="utf-8"
            )
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `dep.sty' not found.\n", encoding="utf-8"
            )
            compile_results = [SimpleNamespace(returncode=1) for _ in range(7)] + [
                SimpleNamespace(returncode=0)
            ]
            resolutions = [{"dep.sty": f"package-{index}"} for index in range(7)]
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch(
                        "texmini.build.resolve_tinytex_packages",
                        side_effect=resolutions,
                    ),
                    patch(
                        "texmini.build.install_tinytex_packages",
                        return_value=SimpleNamespace(returncode=0),
                    ) as install,
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile", side_effect=compile_results
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(install.call_count, 7)

    def test_dependency_progress_names_package_and_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("source", encoding="utf-8")
            Path(directory, "paper.log").write_text(
                "pdfTeX error (font expansion): auto expansion is only possible with scalable fonts\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                output = io.StringIO()
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.install_tinytex_packages",
                        return_value=SimpleNamespace(returncode=0),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        side_effect=[
                            SimpleNamespace(returncode=1, stdout="failure"),
                            SimpleNamespace(returncode=0, stdout="success"),
                        ],
                    ),
                    redirect_stdout(output),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertIn("package-install round 1 of 20", output.getvalue())
        self.assertIn("cm-super", output.getvalue())

    def test_backend_stops_at_twenty_install_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\documentclass{article}\n", encoding="utf-8"
            )
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `dep.sty' not found.\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch(
                        "texmini.build.resolve_tinytex_packages",
                        side_effect=[
                            {"dep.sty": f"package-{index}"} for index in range(21)
                        ],
                    ),
                    patch(
                        "texmini.build.install_tinytex_packages",
                        return_value=SimpleNamespace(returncode=0),
                    ) as install,
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=1),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.failure_kind, "ceiling")
        self.assertEqual(install.call_count, 20)

    def test_backend_reports_unmapped_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\documentclass{article}\n", encoding="utf-8"
            )
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `unknown.sty' not found.\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch("texmini.build.resolve_tinytex_packages", return_value={}),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=1),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.failure_kind, "unmapped")
        self.assertEqual(outcome.unmapped_files, ("unknown.sty",))

    def test_no_install_classifies_missing_package_without_installing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{geometry}\n", encoding="utf-8"
            )
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `geometry.sty' not found.\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files",
                        return_value=["geometry.sty"],
                    ),
                    patch("texmini.build.install_tinytex_packages") as install,
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=2),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", False, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 2)
        self.assertEqual(outcome.failure_kind, "disabled")
        install.assert_not_called()

    def test_install_failure_returns_tlmgr_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{geometry}\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files",
                        return_value=["geometry.sty"],
                    ),
                    patch(
                        "texmini.build.resolve_tinytex_packages",
                        return_value={"geometry.sty": "geometry"},
                    ),
                    patch(
                        "texmini.build.install_tinytex_packages",
                        return_value=SimpleNamespace(returncode=7),
                    ),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 7)
        self.assertEqual(outcome.failure_kind, "install_failed")

    def test_minted_requires_explicit_shell_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{minted}\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch("texmini.build.run_tinytex_compile") as compile_document,
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 1)
        self.assertIn("--shell-escape", outcome.primary_error.message)
        compile_document.assert_not_called()

    def test_no_install_names_missing_direct_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{glossaries}\n\\makeglossaries\n", encoding="utf-8"
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch("texmini.build.run_tinytex_compile") as compile_document,
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", False, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.failure_kind, "disabled")
        self.assertIn("makeglossaries", outcome.primary_error.message)
        compile_document.assert_not_called()

    def test_compile_uses_noninteractive_file_line_diagnostics(self) -> None:
        with patch(
            "texmini.build.run_command", return_value=SimpleNamespace(returncode=1)
        ) as run:
            build.run_tinytex_compile(
                "pdflatex", ["paper.tex"], Path("TinyTeX"), env={}
            )

        self.assertEqual(
            run.call_args.args[0],
            [
                "latexmk",
                "-pdf",
                "-cd",
                "-interaction=nonstopmode",
                "-file-line-error",
                "paper.tex",
            ],
        )


if __name__ == "__main__":
    unittest.main()
