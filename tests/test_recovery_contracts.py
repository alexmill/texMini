from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from texmini import build


class RecoveryContractTest(unittest.TestCase):
    @staticmethod
    def _input_snapshot(paths: list[Path]) -> dict[Path, tuple[bytes, int, int]]:
        return {
            path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in paths
        }

    @staticmethod
    def _managed_root(directory: str) -> Path:
        root = Path(directory) / "TinyTeX"
        binary = root / "bin" / "test"
        binary.mkdir(parents=True)
        suffix = ".exe" if os.name == "nt" else ""
        for name in ("bibtex", "latexmk", "kpsewhich", "pdflatex", "lualatex"):
            tool = binary / f"{name}{suffix}"
            tool.write_text("", encoding="utf-8")
            tool.chmod(0o755)
        tlmgr = binary / ("tlmgr.bat" if os.name == "nt" else "tlmgr")
        tlmgr.write_text("", encoding="utf-8")
        tlmgr.chmod(0o755)
        if os.name == "nt":
            runscript = root / "bin" / "windows" / "runscript.tlu"
            perl = root / "tlpkg" / "tlperl" / "bin" / "perl.exe"
            runscript.parent.mkdir(parents=True)
            perl.parent.mkdir(parents=True)
            runscript.write_text("", encoding="utf-8")
            perl.write_text("", encoding="utf-8")
        return root

    def test_recovery_batches_all_packages_into_one_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            source = Path(directory) / "paper.tex"
            source.write_text("\\documentclass{article}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `alpha.sty' not found.\n"
                "! LaTeX Error: File `beta.sty' not found.\n",
                encoding="utf-8",
            )
            Path(directory, "paper.pdf").write_text("pdf", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.runtime_supports_layout_hook",
                        return_value=False,
                    ),
                    patch(
                        "texmini.build.missing_tinytex_source_files",
                        return_value=[],
                    ),
                    patch(
                        "texmini.build.resolve_tinytex_packages",
                        return_value={
                            "alpha.sty": "alpha-package",
                            "beta.sty": "beta-package",
                        },
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
                        side_effect=[
                            SimpleNamespace(returncode=1, stdout="TeX failed\n"),
                            SimpleNamespace(returncode=0, stdout="TeX succeeded\n"),
                        ],
                    ),
                    redirect_stdout(io.StringIO()),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        install.assert_called_once()
        self.assertEqual(
            install.call_args.args[1], ["alpha-package", "beta-package"]
        )

    def test_no_progress_retry_does_not_reinstall_or_change_build_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            source = Path(directory) / "paper.tex"
            original_source = "\\documentclass{article}\n"
            source.write_text(
                original_source
                + "\\input{chapter}\n"
                + "\\usepackage{styles/local}\n"
                + "\\bibliography{references}\n"
                + "\\includegraphics{figure.png}\n",
                encoding="utf-8",
            )
            chapter = Path(directory) / "chapter.tex"
            chapter.write_text("Project chapter\n", encoding="utf-8")
            style = Path(directory) / "styles" / "local.sty"
            style.parent.mkdir()
            style.write_text("\\ProvidesPackage{local}\n", encoding="utf-8")
            bibliography = Path(directory) / "references.bib"
            bibliography.write_text("@book{example}\n", encoding="utf-8")
            figure = Path(directory) / "figure.png"
            figure.write_bytes(b"project image")
            latexmkrc = Path(directory) / "latexmkrc"
            latexmkrc.write_text("$max_repeat = 7;\n", encoding="utf-8")
            project_inputs = [
                source,
                chapter,
                style,
                bibliography,
                figure,
                latexmkrc,
            ]
            original_inputs = self._input_snapshot(project_inputs)
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `dependency.sty' not found.\n",
                encoding="utf-8",
            )
            declared_args = ["-jobname=publication", "paper.tex"]
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.runtime_supports_layout_hook",
                        return_value=False,
                    ),
                    patch(
                        "texmini.build.missing_tinytex_source_files",
                        return_value=[],
                    ),
                    patch(
                        "texmini.build.resolve_tinytex_packages",
                        return_value={"dependency.sty": "dependency-package"},
                    ) as resolve,
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
                        side_effect=[
                            SimpleNamespace(returncode=1, stdout="TeX failed\n"),
                            SimpleNamespace(returncode=1, stdout="TeX failed\n"),
                        ],
                    ) as compile_document,
                    redirect_stdout(io.StringIO()),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", declared_args
                    )
                    retained_inputs = self._input_snapshot(project_inputs)
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.failure_kind, "ordinary")
        self.assertEqual(outcome.missing_files, ("dependency.sty",))
        self.assertEqual(retained_inputs, original_inputs)
        install.assert_called_once()
        self.assertEqual(install.call_args.args[1], ["dependency-package"])
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(compile_document.call_count, 2)
        first_compile, retry_compile = compile_document.call_args_list
        self.assertEqual(first_compile.args[:3], retry_compile.args[:3])
        self.assertEqual(first_compile.args[1], declared_args)
        self.assertFalse(first_compile.kwargs.get("force", False))
        self.assertTrue(retry_compile.kwargs["force"])
        self.assertEqual(first_compile.kwargs["cwd"], retry_compile.kwargs["cwd"])


if __name__ == "__main__":
    unittest.main()
