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
    def _write_host_tool(directory: Path, name: str) -> Path:
        path = directory / (f"{name}.bat" if os.name == "nt" else name)
        path.write_text("@exit /b 0\n" if os.name == "nt" else name, encoding="utf-8")
        path.chmod(0o755)
        return path

    @staticmethod
    def _managed_root(directory: str) -> Path:
        root = Path(directory) / "TinyTeX"
        binary = root / "bin" / "test"
        binary.mkdir(parents=True)
        suffix = ".exe" if os.name == "nt" else ""
        for name in ("latexmk", "kpsewhich", "pdflatex", "lualatex"):
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
            for suffix in (
                "idx",
                "ind",
                "gls",
                "nls",
                "synctex",
                "synctex.gz",
                "xdy",
            ):
                (aux_dir / f"publication.{suffix}").write_text(
                    "state", encoding="utf-8"
                )
            (aux_dir / "publication.fdb_latexmk").write_text(
                '# Fdb version 4\n'
                '["makeindex people.idx"] 1 "people.idx" "people.ind" '
                '"people" 1 0\n'
                '  "people.idx" 1 1 abc ""\n'
                '  (generated)\n'
                '  "people.ilg"\n'
                '  "people.ind"\n'
                '  (rewritten before read)\n',
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

    def test_cleanup_never_deletes_recorded_inputs_or_bare_fdb_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.tex"
            source.write_text("source", encoding="utf-8")
            for name in (
                "paper.idx",
                "chapter.aux",
                "quoted.ind",
                "paper.aux",
                "paper.synctex",
            ):
                (root / name).write_text("project input", encoding="utf-8")
            (root / "paper.fls").write_text(
                f"INPUT {root / 'chapter.aux'}\n"
                f"INPUT {root / 'paper.synctex'}\n"
                f"OUTPUT {root / 'paper.aux'}\n",
                encoding="utf-8",
            )
            (root / "paper.fdb_latexmk").write_text(
                '# Fdb version 4\n'
                '["pdflatex"] 1 "paper.tex" "paper.pdf" "paper" 1 0\n'
                '  "paper.idx" 1 1 abc ""\n'
                '  "quoted.ind"\n'
                '  (generated)\n'
                '  "paper.aux"\n'
                '  (rewritten before read)\n',
                encoding="utf-8",
            )

            build.cleanup_auxiliary_files(str(source))

            self.assertTrue((root / "paper.idx").is_file())
            self.assertTrue((root / "chapter.aux").is_file())
            self.assertTrue((root / "quoted.ind").is_file())
            self.assertTrue((root / "paper.synctex").is_file())
            self.assertFalse((root / "paper.aux").exists())

    def test_resolve_build_layout_parses_latexmk_report(self) -> None:
        project_root = Path(Path.cwd().anchor) / "project"
        report = f"""Latexmk: Cwd: '{(project_root / "docs").as_posix()}'
Latexmk: Normalized aux dir, out dir, out2 dir:
  '{(project_root / "aux").as_posix()}', '{(project_root / "build").as_posix()}', '{(project_root / "build").as_posix()}'
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
        self.assertEqual(layout.aux_dir, project_root / "aux")
        self.assertEqual(layout.pdf_path, project_root / "build" / "publication.pdf")
        self.assertEqual(layout.log_path, project_root / "aux" / "publication.log")
        self.assertIn("-dir-report-only", run.call_args.args[0])

    def test_absolute_input_displays_absolute_output_path(self) -> None:
        project_root = Path(Path.cwd().anchor) / "project"
        source = project_root / "docs" / "paper.tex"
        report = f"""Latexmk: Cwd: '{source.parent.as_posix()}'
Latexmk: Normalized aux dir, out dir, out2 dir:
  '{source.parent.as_posix()}', '{source.parent.as_posix()}', '{source.parent.as_posix()}'
Latexmk: Base name of generated files:
  'paper'
"""
        completed = SimpleNamespace(returncode=0, stdout=report)
        with patch("texmini.build.run_command", return_value=completed):
            layout = build.resolve_build_layout(
                "pdflatex",
                [os.fspath(source)],
                os.fspath(source),
                {},
                reporting.Reporter(),
            )

        self.assertEqual(layout.display_pdf, os.fspath(source.with_suffix(".pdf")))

    def test_layout_hook_fields_preserve_configured_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="texmini | layout ") as directory:
            project = Path(directory) / "project"
            project.mkdir()
            values = [
                os.fspath(project),
                "../aux files",
                "intermediate | output",
                "build | final output",
                "publication",
                "../aux files/publication.log",
                "paper.tex",
            ]

            layout = build._layout_from_hook_fields(
                [os.fsencode(value).hex() for value in values], "paper.tex"
            )

        self.assertEqual(layout.source, (project / "paper.tex").resolve())
        self.assertEqual(layout.aux_dir, (project.parent / "aux files").resolve())
        self.assertEqual(layout.out_dir, (project / "build | final output").resolve())
        self.assertEqual(
            layout.pdf_path,
            (project / "build | final output").resolve() / "publication.pdf",
        )
        self.assertEqual(
            layout.log_path,
            (project.parent / "aux files").resolve() / "publication.log",
        )

    def test_fast_layout_hook_snapshots_pdf_in_distinct_out2_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            final_pdf = project / "final output" / "publication.pdf"
            values = [
                os.fspath(project),
                "aux",
                "intermediate",
                "final output",
                "publication",
                "aux/publication.log",
                "paper.tex",
            ]
            protocol_line = "MARK|" + "|".join(
                os.fsencode(value).hex() for value in values
            ) + "\n"

            class FakeProcess:
                def __init__(self) -> None:
                    self.stdout = iter([protocol_line, "latexmk output\n"])
                    self.stdin = io.StringIO()
                    self.killed = False

                def kill(self) -> None:
                    self.killed = True

                def wait(self) -> int:
                    return 0

            process = FakeProcess()
            with (
                patch(
                    "texmini.build._layout_hook_code",
                    return_value=("hook", "MARK|", "ACK\n"),
                ),
                patch(
                    "texmini.build.executable_on_path_with_env",
                    return_value="latexmk",
                ),
                patch("texmini.build.subprocess.Popen", return_value=process),
                patch(
                    "texmini.build.pdf_snapshot", return_value=(123, 456)
                ) as snapshot,
            ):
                observation = build.run_tinytex_compile_with_layout(
                    "pdflatex",
                    ["-outdir=intermediate", "paper.tex"],
                    "paper.tex",
                    Path("TinyTeX"),
                    env={},
                    cwd=project,
                )

        self.assertEqual(observation.layout.pdf_path, final_pdf.resolve())
        self.assertEqual(observation.pdf_before, (123, 456))
        snapshot.assert_called_once_with(final_pdf.resolve())
        self.assertEqual(observation.result.stdout, "latexmk output\n")

    def test_backend_combines_layout_observation_with_first_compile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            source = Path(directory) / "paper.tex"
            source.write_text("source", encoding="utf-8")
            source.with_suffix(".pdf").write_text("pdf", encoding="utf-8")
            layout = build.default_build_layout("paper.tex")
            observation = build.CompileObservation(
                SimpleNamespace(returncode=0, stdout=""), layout, None
            )
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch("texmini.build.runtime_supports_layout_hook", return_value=True),
                    patch(
                        "texmini.build.run_tinytex_compile_with_layout",
                        return_value=observation,
                    ) as compile_with_layout,
                    patch("texmini.build.resolve_build_layout") as preflight,
                    patch("texmini.build.run_tinytex_compile") as legacy_compile,
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(outcome.layout, layout)
        compile_with_layout.assert_called_once()
        preflight.assert_not_called()
        legacy_compile.assert_not_called()

    def test_backend_preinstalls_source_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{geometry}\n", encoding="utf-8"
            )
            Path(directory, "paper.pdf").write_text("pdf", encoding="utf-8")
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

    def test_backend_does_not_accept_host_biber_or_makeindex_as_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            source = Path(directory) / "paper.tex"
            source.write_text(
                "\\usepackage{biblatex,makeidx}\n\\makeindex\n",
                encoding="utf-8",
            )
            host_bin = Path(directory) / "host-bin"
            host_bin.mkdir()
            for tool in ("biber", "makeindex"):
                self._write_host_tool(host_bin, tool)

            def install(_root, packages, _env, _reporter):
                for tool in packages:
                    self._write_host_tool(root / "bin" / "test", tool)
                return SimpleNamespace(returncode=0)

            def compile_document(*_args, **_kwargs):
                source.with_suffix(".pdf").write_text("pdf", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="")

            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(
                        os.environ,
                        {
                            "TEXMINI_TINYTEX_ROOT": str(root),
                            "PATH": f"{host_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                        },
                    ),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch(
                        "texmini.build.install_tinytex_packages", side_effect=install
                    ) as install_packages,
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.runtime_supports_layout_hook", return_value=False
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        side_effect=compile_document,
                    ),
                ):
                    env = build.tinytex_env(root)
                    for tool in ("biber", "makeindex"):
                        self.assertIn(
                            os.fspath(host_bin),
                            build.executable_on_path_with_env(tool, env),
                        )
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(
            install_packages.call_args.args[1], ["biber", "makeindex"]
        )

    def test_backend_install_must_create_managed_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            source = Path(directory) / "paper.tex"
            source.write_text("\\usepackage{biblatex}\n", encoding="utf-8")
            host_bin = Path(directory) / "host-bin"
            host_bin.mkdir()
            host_biber = self._write_host_tool(host_bin, "biber")

            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(
                        os.environ,
                        {
                            "TEXMINI_TINYTEX_ROOT": str(root),
                            "PATH": f"{host_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                        },
                    ),
                    patch(
                        "texmini.build.missing_tinytex_source_files", return_value=[]
                    ),
                    patch(
                        "texmini.build.install_tinytex_packages",
                        return_value=SimpleNamespace(returncode=0),
                    ),
                    patch("texmini.build.run_tinytex_compile") as compile_document,
                    self.assertRaisesRegex(
                        model.TexMiniError, "did not provide: biber"
                    ),
                ):
                    env = build.tinytex_env(root)
                    self.assertEqual(
                        build.executable_on_path_with_env("biber", env),
                        os.fspath(host_biber),
                    )
                    build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        compile_document.assert_not_called()

    def test_backend_owns_inventoried_basename_sources_but_not_log_only_paths(
        self,
    ) -> None:
        cases = (
            ("sty", "\\usepackage{local}\n"),
            ("cls", "\\documentclass{local}\n"),
            ("bst", "\\bibliographystyle{local}\n"),
            ("bbx", "\\usepackage[bibstyle=local]{biblatex}\n"),
            ("cbx", "\\usepackage[citestyle=local]{biblatex}\n"),
        )
        for extension, declaration in cases:
            with (
                self.subTest(extension=extension),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._managed_root(directory)
                self._write_host_tool(root / "bin" / "test", "bibtex")
                self._write_host_tool(root / "bin" / "test", "biber")
                source = Path(directory) / "paper.tex"
                source.write_text(declaration, encoding="utf-8")
                local = Path(directory) / "vendor" / f"local.{extension}"
                local.parent.mkdir()
                local.write_text("project source\n", encoding="utf-8")
                source.with_suffix(".pdf").write_text("pdf", encoding="utf-8")
                source.with_suffix(".log").write_text(
                    f"! LaTeX Error: File `local.{extension}' not found.\n"
                    "! LaTeX Error: File `nested/gamma.sty' not found.\n",
                    encoding="utf-8",
                )
                previous = Path.cwd()
                try:
                    os.chdir(directory)
                    with (
                        patch.dict(
                            os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}
                        ),
                        patch(
                            "texmini.build.missing_tinytex_source_files",
                            return_value=[],
                        ),
                        patch(
                            "texmini.build.resolve_tinytex_packages",
                            return_value={"nested/gamma.sty": "gamma-package"},
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
                            "texmini.build.runtime_supports_layout_hook",
                            return_value=False,
                        ),
                        patch(
                            "texmini.build.run_tinytex_compile",
                            side_effect=[
                                SimpleNamespace(returncode=1, stdout="failure"),
                                SimpleNamespace(returncode=0, stdout="success"),
                            ],
                        ),
                    ):
                        outcome = build.run_tinytex_backend(
                            "pdflatex", True, False, "paper.tex", ["paper.tex"]
                        )
                finally:
                    os.chdir(previous)

                self.assertEqual(outcome.returncode, 0)
                self.assertEqual(resolve.call_args.args[1], ["nested/gamma.sty"])
                self.assertEqual(install.call_args.args[1], ["gamma-package"])

    def test_backend_never_resolves_source_path_but_resolves_transitive_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{styles/local}\n", encoding="utf-8"
            )
            Path(directory, "paper.pdf").write_text("pdf", encoding="utf-8")
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `styles/local.sty' not found.\n"
                "! LaTeX Error: File `nested/gamma.sty' not found.\n",
                encoding="utf-8",
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
                        return_value={"nested/gamma.sty": "gamma-package"},
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
                        "texmini.build.runtime_supports_layout_hook", return_value=False
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        side_effect=[
                            SimpleNamespace(returncode=1, stdout="failure"),
                            SimpleNamespace(returncode=0, stdout="success"),
                        ],
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(resolve.call_args.args[1], ["nested/gamma.sty"])
        self.assertEqual(install.call_args.args[1], ["gamma-package"])

    def test_backend_records_declared_ownership_on_unmapped_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text(
                "\\usepackage{styles/local}\n", encoding="utf-8"
            )
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `styles/local.sty' not found.\n"
                "! LaTeX Error: File `nested/gamma.sty' not found.\n",
                encoding="utf-8",
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
                        "texmini.build.resolve_tinytex_packages", return_value={}
                    ) as resolve,
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch(
                        "texmini.build.runtime_supports_layout_hook", return_value=False
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=1, stdout="failure"),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.failure_kind, model.FailureKind.UNMAPPED)
        self.assertEqual(
            outcome.unmapped_files,
            ("styles/local.sty", "nested/gamma.sty"),
        )
        self.assertEqual(outcome.project_files, ("styles/local.sty",))
        self.assertEqual(resolve.call_args.args[1], ["nested/gamma.sty"])

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

    def test_negative_synctex_mode_requires_uncompressed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = model.BuildLayout(
                root / "paper.tex",
                "paper",
                root / "aux",
                root / "out",
                root / "out" / "paper.pdf",
                root / "aux" / "paper.log",
            )
            layout.aux_dir.mkdir()
            layout.out_dir.mkdir()
            (layout.aux_dir / "paper.synctex.gz").write_text(
                "wrong mode", encoding="utf-8"
            )

            self.assertTrue(build.synctex_enabled(["-synctex=-1"]))
            self.assertTrue(build.synctex_enabled(["-synctex=-2"]))
            self.assertTrue(build.synctex_artifact_requested(["-synctex=-1"], layout))
            (layout.out_dir / "paper.synctex").write_text(
                "uncompressed", encoding="utf-8"
            )
            self.assertFalse(
                build.synctex_artifact_requested(["-synctex=-1"], layout)
            )
            self.assertFalse(build.synctex_enabled(["-synctex=-1", "-synctex=0"]))
            self.assertFalse(build.synctex_enabled(["-synctex=-0"]))

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
            Path(directory, "paper.pdf").write_text("pdf", encoding="utf-8")
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
            Path(directory, "paper.pdf").write_text("pdf", encoding="utf-8")
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

    def test_backend_rejects_success_without_expected_final_pdf(self) -> None:
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
                        "texmini.build.runtime_supports_layout_hook", return_value=False
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=0, stdout="success"),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 1)
        self.assertEqual(outcome.failure_kind, model.FailureKind.ORDINARY)
        self.assertIn("did not produce the expected PDF", outcome.primary_error.message)
        self.assertIn("paper.pdf", outcome.primary_error.message)

    def test_backend_preserves_tex_status_when_log_disappears(self) -> None:
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
                        "texmini.build.runtime_supports_layout_hook", return_value=False
                    ),
                    patch(
                        "texmini.build.run_tinytex_compile",
                        return_value=SimpleNamespace(returncode=7, stdout="failed"),
                    ),
                ):
                    outcome = build.run_tinytex_backend(
                        "pdflatex", True, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 7)
        self.assertEqual(outcome.failure_kind, model.FailureKind.UNIDENTIFIED)

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

    def test_no_install_never_provisions_missing_engine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._managed_root(directory)
            Path(directory, "paper.tex").write_text("source", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(
                        os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}
                    ),
                    patch("texmini.build.ensure_tinytex_engine") as ensure,
                    patch("texmini.build.install_tinytex_packages") as install,
                    patch(
                        "texmini.build.resolve_build_layout",
                        return_value=build.default_build_layout("paper.tex"),
                    ),
                    patch("texmini.build.run_tinytex_compile") as compile_document,
                ):
                    outcome = build.run_tinytex_backend(
                        "xelatex", False, False, "paper.tex", ["paper.tex"]
                    )
            finally:
                os.chdir(previous)

        self.assertEqual(outcome.returncode, 1)
        self.assertEqual(outcome.failure_kind, model.FailureKind.DISABLED)
        self.assertIn("xelatex is not installed", outcome.primary_error.message)
        self.assertIn("without --no-install", outcome.primary_error.message)
        ensure.assert_not_called()
        install.assert_not_called()
        compile_document.assert_not_called()

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

    def test_compile_passes_negative_synctex_mode_unchanged(self) -> None:
        with patch(
            "texmini.build.run_command", return_value=SimpleNamespace(returncode=0)
        ) as run:
            build.run_tinytex_compile(
                "pdflatex",
                ["-synctex=-1", "paper.tex"],
                Path("TinyTeX"),
                env={},
            )

        self.assertIn("-synctex=-1", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
