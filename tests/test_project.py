from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from texmini import model, project, reporting, runtime


class ProjectTest(unittest.TestCase):
    def test_detect_tex_file_auto_detects_single_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("source", encoding="utf-8")
                args: list[str] = []
                detected = project.detect_tex_file(args, None)
            finally:
                os.chdir(previous)

        self.assertEqual(detected, "paper.tex")
        self.assertEqual(args, ["paper.tex"])

    def test_detect_tex_file_rejects_missing_explicit_source(self) -> None:
        with self.assertRaisesRegex(model.TexMiniError, "missing.tex.*does not exist"):
            project.detect_tex_file(["missing.tex"], "missing.tex")

    def test_detect_tex_file_selects_unique_main_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                Path("chapter.tex").write_text("Chapter", encoding="utf-8")
                Path("draft.tex").write_text(
                    "% \\documentclass{book}\n", encoding="utf-8"
                )
                Path("main.tex").write_text("\\documentclass{book}\n", encoding="utf-8")
                args: list[str] = []
                detected = project.detect_tex_file(args, None)
            finally:
                os.chdir(previous)

        self.assertEqual(detected, "main.tex")

    def test_engine_directive_and_explicit_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text(
                "% !TeX program = xelatex\n\\documentclass{article}\n", encoding="utf-8"
            )

            self.assertEqual(
                project.resolve_engine(None, str(source), reporting.Reporter()),
                "xelatex",
            )
            self.assertEqual(
                project.resolve_engine("lualatex", str(source), reporting.Reporter()),
                "lualatex",
            )

    def test_unsupported_engine_directive_warns_and_uses_pdflatex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("% !TEX TS-program = context\n", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                engine = project.resolve_engine(None, str(source), reporting.Reporter())

        self.assertEqual(engine, "pdflatex")
        self.assertIn("unsupported TeX program 'context'", errors.getvalue())

    def test_explicit_missing_bibliography_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("\\bibliography{missing}\n", encoding="utf-8")
            with self.assertRaisesRegex(model.TexMiniError, "not found"):
                project.check_bibliography(
                    str(source), [str(Path(directory) / "missing.bib")]
                )

    def test_source_cache_refreshes_after_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text("first", encoding="utf-8")
            self.assertEqual(project.read_source_file(str(source)), "first")
            source.write_text("second version", encoding="utf-8")
            self.assertEqual(project.read_source_file(str(source)), "second version")

    def test_source_requirements_extract_classes_packages_and_biber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text(
                "\\documentclass{memoir}\n\\usepackage{geometry,microtype}\n"
                "\\usepackage[backend=biber]{biblatex}\n\\bibliographystyle{plainnat}\n",
                encoding="utf-8",
            )
            files, packages = runtime.tex_source_requirements(str(source))

        self.assertEqual(
            files,
            [
                "memoir.cls",
                "geometry.sty",
                "microtype.sty",
                "biblatex.sty",
                "plainnat.bst",
            ],
        )
        self.assertEqual(packages, ["biber"])

    def test_source_requirements_ignore_commented_directives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paper.tex"
            source.write_text(
                "\\documentclass{article}\n"
                "% \\usepackage{minted}\n"
                "\\usepackage{geometry}% \\usepackage{microtype}\n"
                "Escaped percent: \\%\n",
                encoding="utf-8",
            )
            files, packages = runtime.tex_source_requirements(str(source))

        self.assertEqual(files, ["article.cls", "geometry.sty"])
        self.assertEqual(packages, [])
        self.assertFalse(
            project.source_uses_bibliography("% \\addbibresource{refs.bib}\n")
        )

    def test_source_requirements_follow_local_inputs_and_detect_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass{article}\n\\input{chapter}\n\\bibliography{refs}\n",
                encoding="utf-8",
            )
            (root / "chapter.tex").write_text(
                "\\usepackage[xindy]{glossaries}\n\\makeglossaries\n"
                "\\usepackage{imakeidx,minted}\n\\makeindex\n",
                encoding="utf-8",
            )

            requirements = project.analyze_source_requirements(str(root / "main.tex"))

        self.assertIn("glossaries.sty", requirements.files)
        self.assertIn("imakeidx.sty", requirements.files)
        self.assertEqual(
            requirements.tools, ("bibtex", "makeglossaries", "xindy", "makeindex")
        )
        self.assertTrue(requirements.uses_minted)
        self.assertEqual(
            {path.name for path in requirements.sources}, {"main.tex", "chapter.tex"}
        )

    def test_bibliography_discovery_uses_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_directory = Path(directory) / "docs"
            source_directory.mkdir()
            source = source_directory / "paper.tex"
            source.write_text("\\addbibresource{refs.bib}\n", encoding="utf-8")
            (source_directory / "refs.bib").write_text("@book{x}\n", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                project.check_bibliography(str(source), [])

        self.assertEqual(errors.getvalue(), "")

    def test_log_requirements_extract_missing_file_font_and_biber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "! LaTeX Error: File `geometry.sty' not found.\n"
                "mktextfm tcrm1000\n"
                "Package biblatex Warning: Please (re)run Biber on the file:\n",
                encoding="utf-8",
            )
            files, packages = project.tex_log_requirements(log)

        self.assertEqual(files, ["geometry.sty", "tcrm1000.tfm"])
        self.assertEqual(packages, ["biber"])

    def test_log_requirements_ignore_optional_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "Package biblatex Info: ... file 'biblatex-dm.cfg' not found.\n"
                "File 'optional.cfg' not found, skipping.\n",
                encoding="utf-8",
            )

            files, packages = project.tex_log_requirements(log)

        self.assertEqual(files, [])
        self.assertEqual(packages, [])


if __name__ == "__main__":
    unittest.main()
