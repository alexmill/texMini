from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from texmini import cli


def sample_poisson(rng: random.Random, lam: float) -> int:
    threshold = 2.718281828459045 ** -lam
    probability = 1.0
    count = 0
    while probability > threshold:
        count += 1
        probability *= rng.random()
    return count - 1


def sample_overdispersed_count(rng: random.Random, mean: float, dispersion: float) -> int:
    lam = rng.gammavariate(dispersion, mean / dispersion)
    return sample_poisson(rng, lam)


class CliTest(unittest.TestCase):
    def test_parse_args_defaults_to_pdflatex(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            engine, auto_clean, auto_install, latexmk_args, bib_files, tex_file = cli.parse_args(
                ["paper.tex", "refs.bib"]
            )

        self.assertEqual(engine, "pdflatex")
        self.assertTrue(auto_clean)
        self.assertTrue(auto_install)
        self.assertEqual(latexmk_args, ["paper.tex"])
        self.assertEqual(bib_files, ["refs.bib"])
        self.assertEqual(tex_file, "paper.tex")

    def test_parse_args_disables_auto_install(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            engine, auto_clean, auto_install, latexmk_args, bib_files, tex_file = cli.parse_args(
                ["--no-install", "paper.tex"]
            )

        self.assertEqual(engine, "pdflatex")
        self.assertTrue(auto_clean)
        self.assertFalse(auto_install)
        self.assertEqual(latexmk_args, ["paper.tex"])
        self.assertEqual(bib_files, [])
        self.assertEqual(tex_file, "paper.tex")

    def test_parse_args_rejects_backend_selection(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(cli.TexMiniError, "always uses managed TinyTeX"):
                cli.parse_args(["--backend", "latexmk", "paper.tex"])

    def test_parse_args_respects_auto_install_environment(self) -> None:
        with patch.dict(os.environ, {"TEXMINI_AUTO_INSTALL": "false"}, clear=True):
            _, _, auto_install, _, _, _ = cli.parse_args(["paper.tex"])

        self.assertFalse(auto_install)

    def test_tinytex_bundle_defaults_to_smallest_release(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cli.tinytex_bundle(), "TinyTeX-0")

    def test_executable_on_path_finds_executable_without_shutil(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "perl"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)

            with patch.dict(os.environ, {"PATH": directory}):
                self.assertEqual(cli.executable_on_path("perl"), str(executable))

    def test_tinytex_install_requires_perl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with (
                patch.dict(os.environ, {"PATH": ""}),
                self.assertRaisesRegex(cli.TexMiniError, "Perl is required"),
            ):
                cli.install_tinytex_archive(root)

    def test_detect_tex_file_auto_detects_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
                latexmk_args: list[str] = []

                with redirect_stdout(StringIO()):
                    self.assertEqual(cli.detect_tex_file(latexmk_args, None), "paper.tex")
                self.assertEqual(latexmk_args, ["paper.tex"])
            finally:
                os.chdir(previous_cwd)

    def test_check_bibliography_errors_when_explicit_bib_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tex_file = Path(directory) / "paper.tex"
            tex_file.write_text("\\usepackage{biblatex}\n\\addbibresource{refs.bib}\n", encoding="utf-8")

            with self.assertRaisesRegex(cli.TexMiniError, "missing.bib"):
                with redirect_stdout(StringIO()):
                    cli.check_bibliography(str(tex_file), ["missing.bib"])

    def test_source_cache_refreshes_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tex_file = Path(directory) / "paper.tex"
            tex_file.write_text("\\documentclass{article}\n", encoding="utf-8")
            cli._source_cache.clear()

            self.assertEqual(cli.tex_source_package_files(str(tex_file)), ["article.cls"])
            tex_file.write_text("\\documentclass{memoir}\n", encoding="utf-8")

            self.assertEqual(cli.tex_source_package_files(str(tex_file)), ["memoir.cls"])

    def test_cleanup_auxiliary_files_keeps_source_and_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "paper"
            for suffix in ["tex", "pdf", "aux", "log", "run.xml"]:
                base.with_suffix(f".{suffix}").write_text("", encoding="utf-8")
            missfont_log = Path(directory) / "missfont.log"
            missfont_log.write_text("", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with redirect_stdout(StringIO()):
                    cli.cleanup_auxiliary_files(str(base.with_suffix(".tex")))
                    cli.cleanup_auxiliary_files(str(base.with_suffix(".tex")))
            finally:
                os.chdir(previous_cwd)

            self.assertTrue(base.with_suffix(".tex").exists())
            self.assertTrue(base.with_suffix(".pdf").exists())
            self.assertFalse(base.with_suffix(".aux").exists())
            self.assertFalse(base.with_suffix(".log").exists())
            self.assertFalse(base.with_suffix(".run.xml").exists())
            self.assertFalse(missfont_log.exists())

    def test_run_tinytex_backend_uses_managed_latexmk_and_cleans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
                Path("paper.aux").write_text("", encoding="utf-8")

                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.run_command", return_value=SimpleNamespace(returncode=0)) as run,
                    patch("texmini.cli.tex_source_requirements") as source_requirements,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                self.assertFalse(Path("paper.aux").exists())
                command = run.call_args.args[0]
                env = run.call_args.kwargs["env"]
                self.assertEqual(command, ["latexmk", "-pdf", "-interaction=nonstopmode", "paper.tex"])
                self.assertTrue(env["PATH"].startswith(str(bin_dir)))
                source_requirements.assert_not_called()
            finally:
                os.chdir(previous_cwd)

    def test_install_tinytex_archive_streams_download_to_tar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".tinytex"
            response = object()
            member = tarfile.TarInfo("TinyTeX/bin/universal-darwin/latexmk")

            class ResponseContext:
                def __enter__(self) -> object:
                    return response

                def __exit__(self, *_: object) -> None:
                    return None

            class TarContext:
                def __enter__(self) -> "TarContext":
                    return self

                def __exit__(self, *_: object) -> None:
                    return None

                def __iter__(self):
                    return iter([member])

                def extract(self, _: tarfile.TarInfo, destination: Path) -> None:
                    bin_dir = destination / "TinyTeX" / "bin" / "universal-darwin"
                    bin_dir.mkdir(parents=True)
                    (bin_dir / "latexmk").write_text("", encoding="utf-8")

            with (
                patch("texmini.cli.latest_tinytex_asset", return_value=("TinyTeX-1-test.tar.xz", "https://example.test/tinytex.tar.xz")),
                patch.dict(os.environ, {"TEXMINI_TINYTEX_BUNDLE": "TinyTeX-1"}),
                patch("texmini.cli.update_tinytex_manager") as update_manager,
                patch("urllib.request.urlopen", return_value=ResponseContext()) as urlopen,
                patch("urllib.request.urlretrieve") as urlretrieve,
                patch("tarfile.open", return_value=TarContext()) as tar_open,
            ):
                with redirect_stdout(StringIO()):
                    cli.install_tinytex_archive(root)

            urlopen.assert_called_once_with("https://example.test/tinytex.tar.xz", timeout=60)
            tar_open.assert_called_once_with(fileobj=response, mode="r|xz")
            urlretrieve.assert_not_called()
            update_manager.assert_called_once_with(root)
            self.assertTrue((root / "bin" / "universal-darwin" / "latexmk").exists())

    def test_tinytex_archive_validation_allows_internal_links_and_rejects_escape(self) -> None:
        internal = tarfile.TarInfo("TinyTeX/bin/universal-darwin/tlmgr")
        internal.type = tarfile.SYMTYPE
        internal.linkname = "../../texmf-dist/scripts/texlive/tlmgr.pl"
        cli.validate_tinytex_archive_member(internal)

        linux_member = tarfile.TarInfo(".TinyTeX/bin/x86_64-linux/tlmgr")
        cli.validate_tinytex_archive_member(linux_member)

        escape = tarfile.TarInfo("TinyTeX/bin/escape")
        escape.type = tarfile.SYMTYPE
        escape.linkname = "../../../outside"
        with self.assertRaisesRegex(cli.TexMiniError, "Unsafe link"):
            cli.validate_tinytex_archive_member(escape)

        traversal = tarfile.TarInfo("../outside")
        with self.assertRaisesRegex(cli.TexMiniError, "Unsafe path"):
            cli.validate_tinytex_archive_member(traversal)

    def test_tinytex_platform_selects_musl_x86_64_asset(self) -> None:
        with (
            patch.object(sys, "platform", "linux"),
            patch("platform.machine", return_value="x86_64"),
            patch("platform.libc_ver", return_value=("musl", "1.2.5")),
        ):
            self.assertEqual(cli.tinytex_platform_key(), "linuxmusl-x86_64")

    def test_minimal_tinytex_bootstrap_updates_and_installs_in_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "tlmgr").write_text("", encoding="utf-8")

            def run_command(args: list[str], **_: object) -> SimpleNamespace:
                if args[:2] == ["tlmgr", "install"]:
                    (bin_dir / "latexmk").write_text("", encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch("texmini.cli.run_command", side_effect=run_command) as run:
                with redirect_stdout(StringIO()):
                    cli.bootstrap_tinytex(root)

            self.assertEqual(
                [call.args[0] for call in run.call_args_list],
                [
                    ["tlmgr", "update", "--self"],
                    ["tlmgr", "install", "latex-bin", "latexmk", "metafont", "mfware"],
                ],
            )

    def test_tinytex_installs_xelatex_engine_on_demand(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            env = {"PATH": str(root / "bin" / "universal-darwin")}

            with (
                patch("texmini.cli.executable_on_path_with_env", return_value=None),
                patch(
                    "texmini.cli.install_tinytex_packages",
                    return_value=SimpleNamespace(returncode=0),
                ) as install,
            ):
                with redirect_stdout(StringIO()):
                    cli.ensure_tinytex_engine(root, "xelatex", env)

            install.assert_called_once_with(root, ["xetex"], env)

    def test_tinytex_does_not_install_default_engine_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            with patch("texmini.cli.install_tinytex_packages") as install:
                cli.ensure_tinytex_engine(root, "pdflatex", {"PATH": "managed-tinytex"})

            install.assert_not_called()

    def test_missing_file_parser_extracts_common_tex_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "\n".join(
                    [
                        "! LaTeX Error: File `tikz.sty' not found.",
                        "! LaTeX Error: File 'memoir.cls' not found.",
                        "! BibTeX Error: File `plainnat.bst' not found.",
                        "! Package biblatex Error: File `authoryear.bbx' not found.",
                        "! Package biblatex Error: File `numeric.cbx' not found.",
                        "! I can't find file `IEEEtran.cls'.",
                        "I couldn't open style file unsrtnat.bst",
                        "Package biblatex Info: Trying to load bibliography style 'apa'...",
                        "! Package biblatex Error: Style 'apa' not found.",
                        "Package biblatex Info: Trying to load citation style 'verbose'...",
                        "! Package biblatex Error: Style 'verbose' not found.",
                        "kpathsea: Running mktextfm ecrm1000",
                        "! Font T1/cmr/m/n/10=ecrm1000 at 10.0pt not loadable: Metric (TFM) file not found.",
                        "pdfTeX error: pdflatex (file tcrm1000): Font tcrm1000 at 600 not found",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                cli.missing_tex_files_from_log(log),
                [
                    "tikz.sty",
                    "memoir.cls",
                    "plainnat.bst",
                    "authoryear.bbx",
                    "numeric.cbx",
                    "IEEEtran.cls",
                    "unsrtnat.bst",
                    "ecrm1000.tfm",
                    "tcrm1000.tfm",
                    "apa.bbx",
                    "verbose.cbx",
                ],
            )

    def test_missing_file_parser_extracts_random_package_names(self) -> None:
        rng = random.Random(0)
        extensions = ["sty", "cls", "bst", "bbx", "cbx"]
        missing = [f"pkg-{rng.randrange(10_000)}.{extension}" for extension in extensions]

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text("\n".join(f"! LaTeX Error: File `{name}' not found." for name in missing), encoding="utf-8")

            self.assertEqual(cli.missing_tex_files_from_log(log), missing)

    def test_missing_file_parser_extracts_random_bibliography_length(self) -> None:
        rng = random.Random(4)
        count = max(3, sample_overdispersed_count(rng, mean=8.0, dispersion=2.0))
        styles = [f"bibstyle-{rng.randrange(100_000)}" for _ in range(count)]

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "\n".join(
                    f"Package biblatex Info: Trying to load bibliography style '{style}'...\n"
                    f"! Package biblatex Error: Style '{style}' not found."
                    for style in styles
                ),
                encoding="utf-8",
            )

            self.assertEqual(cli.missing_tex_files_from_log(log), [f"{style}.bbx" for style in styles])

    def test_missing_package_parser_extracts_biber_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "paper.log"
            log.write_text(
                "Package biblatex Warning: Please (re)run Biber on the file:\n"
                "(biblatex)                paper\n",
                encoding="utf-8",
            )

            self.assertEqual(cli.missing_tinytex_packages_from_log(log), ["biber"])

    def test_tex_source_package_files_extracts_classes_and_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tex_file = Path(directory) / "paper.tex"
            tex_file.write_text(
                "\n".join(
                    [
                        "\\documentclass{memoir}",
                        "\\usepackage{biblatex, csquotes}",
                        "\\RequirePackage[table]{xcolor}",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                cli.tex_source_package_files(str(tex_file)),
                ["memoir.cls", "biblatex.sty", "csquotes.sty", "xcolor.sty"],
            )

    def test_missing_tinytex_source_files_batches_kpsewhich_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            tex_file = Path(directory) / "paper.tex"
            tex_file.write_text(
                "\n".join(
                    [
                        "\\documentclass{article}",
                        "\\usepackage{geometry,biblatex,missingpkg}",
                    ]
                ),
                encoding="utf-8",
            )
            env = {"PATH": "managed-tinytex"}

            with patch(
                "texmini.cli.run_command",
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout="/texmf-dist/tex/latex/base/article.cls\n"
                    "/texmf-dist/tex/latex/geometry/geometry.sty\n",
                ),
            ) as run:
                missing_files = cli.missing_tinytex_source_files(root, str(tex_file), env)

            self.assertEqual(missing_files, ["biblatex.sty", "missingpkg.sty"])
            run.assert_called_once()
            self.assertEqual(
                run.call_args.args[0],
                ["kpsewhich", "article.cls", "geometry.sty", "biblatex.sty", "missingpkg.sty"],
            )
            self.assertIs(run.call_args.kwargs["env"], env)
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)

    def test_tinytex_packages_from_source_extracts_biber_for_biblatex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tex_file = Path(directory) / "paper.tex"
            tex_file.write_text("\\usepackage[backend=biber]{biblatex}\n", encoding="utf-8")

            self.assertEqual(cli.tinytex_packages_from_source(str(tex_file)), ["biber"])

    def test_resolver_uses_cached_mappings_before_tlmgr_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            cache = Path(directory) / "package-map.json"
            cache.write_text(json.dumps({"cached.sty": "cachedpkg"}), encoding="utf-8")

            with patch(
                "texmini.cli.run_command",
                return_value=SimpleNamespace(returncode=0, stdout="newpkg: texmf-dist/tex/latex/new/new.sty\n"),
            ) as run:
                resolved = cli.resolve_tinytex_packages(root, ["cached.sty", "new.sty"], cache)

            self.assertEqual(resolved, {"cached.sty": "cachedpkg", "new.sty": "newpkg"})
            self.assertEqual(len(run.call_args_list), 1)
            self.assertEqual(run.call_args.args[0], ["tlmgr", "search", "--global", "--file", "/new.sty"])

    def test_resolver_deduplicates_missing_files_before_tlmgr_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            cache = Path(directory) / "package-map.json"

            with patch(
                "texmini.cli.run_command",
                return_value=SimpleNamespace(returncode=0, stdout="duppkg: texmf-dist/tex/latex/dup/dup.sty\n"),
            ) as run:
                resolved = cli.resolve_tinytex_packages(root, ["dup.sty", "dup.sty"], cache)

            self.assertEqual(resolved, {"dup.sty": "duppkg"})
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], ["tlmgr", "search", "--global", "--file", "/dup.sty"])

    def test_resolver_uses_common_mapping_before_tlmgr_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            cache = Path(directory) / "package-map.json"

            with patch("texmini.cli.run_command") as run:
                resolved = cli.resolve_tinytex_packages(root, ["biblatex.sty", "tikz.sty", "tcrm1095.tfm"], cache)

            self.assertEqual(resolved, {"biblatex.sty": "biblatex", "tikz.sty": "pgf", "tcrm1095.tfm": "ec"})
            run.assert_not_called()
            self.assertEqual(
                json.loads(cache.read_text(encoding="utf-8")),
                {"biblatex.sty": "biblatex", "tcrm1095.tfm": "ec", "tikz.sty": "pgf"},
            )

    def test_tlmgr_search_parser_ignores_diagnostics(self) -> None:
        output = "\n".join(
            [
                "tlmgr: package repository https://example.invalid",
                "biblatex:",
                "\ttexmf-dist/tex/latex/biblatex/biblatex.sty",
            ]
        )

        self.assertEqual(cli.package_from_tlmgr_search(output), "biblatex")

    def test_tinytex_backend_batches_install_and_retries_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `foo.sty' not found.\n! LaTeX Error: File `bar.cls' not found.\n",
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
                    ) as compile_run,
                    patch(
                        "texmini.cli.resolve_tinytex_packages",
                        return_value={"foo.sty": "foopkg", "bar.cls": "barpkg"},
                    ),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch("texmini.cli.tinytex_packages_from_source", return_value=[]),
                    patch(
                        "texmini.cli.install_tinytex_packages",
                        return_value=SimpleNamespace(returncode=0),
                    ) as install,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                self.assertEqual(len(compile_run.call_args_list), 2)
                self.assertFalse(compile_run.call_args_list[0].kwargs.get("force", False))
                self.assertTrue(compile_run.call_args_list[1].kwargs["force"])
                self.assertEqual(install.call_args.args[1], ["barpkg", "foopkg"])
            finally:
                os.chdir(previous_cwd)

    def test_tinytex_backend_reuses_environment_across_retry_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.log").write_text("! LaTeX Error: File `foo.sty' not found.\n", encoding="utf-8")
            env = {"PATH": "managed-tinytex"}

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.tinytex_env", return_value=env) as tinytex_env,
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
                    ) as compile_run,
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]) as source_files,
                    patch("texmini.cli.resolve_tinytex_packages", return_value={"foo.sty": "foopkg"}) as resolve,
                    patch("texmini.cli.tinytex_packages_from_source", return_value=[]),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                tinytex_env.assert_called_once_with(root)
                self.assertIs(compile_run.call_args_list[0].kwargs["env"], env)
                self.assertIs(compile_run.call_args_list[1].kwargs["env"], env)
                self.assertIs(source_files.call_args.args[2], env)
                self.assertIs(resolve.call_args.kwargs["env"], env)
                self.assertIs(install.call_args.args[2], env)
            finally:
                os.chdir(previous_cwd)

    def test_tinytex_backend_batches_source_packages_with_log_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.tex").write_text(
                "\\usepackage{biblatex,csquotes,tikz}\n",
                encoding="utf-8",
            )
            Path(directory, "paper.log").write_text("! LaTeX Error: File `biblatex.sty' not found.\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
                    ),
                    patch(
                        "texmini.cli.missing_tinytex_source_files",
                        return_value=["biblatex.sty", "csquotes.sty", "tikz.sty"],
                    ),
                    patch(
                        "texmini.cli.resolve_tinytex_packages",
                        return_value={
                            "biblatex.sty": "biblatex",
                            "csquotes.sty": "csquotes",
                            "tikz.sty": "pgf",
                        },
                    ) as resolve,
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                self.assertEqual(resolve.call_args.args[1], ["biblatex.sty", "csquotes.sty", "tikz.sty"])
                self.assertEqual(install.call_args.args[1], ["biber", "biblatex", "csquotes", "pgf"])
            finally:
                os.chdir(previous_cwd)

    def test_tinytex_backend_retries_from_source_packages_when_log_has_no_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.tex").write_text("\\usepackage{sourceonly}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text("Build failed without a standard missing-file line.\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
                    ) as compile_run,
                    patch("texmini.cli.missing_tinytex_source_files", return_value=["sourceonly.sty"]),
                    patch("texmini.cli.resolve_tinytex_packages", return_value={"sourceonly.sty": "sourcepkg"}) as resolve,
                    patch("texmini.cli.tinytex_packages_from_source", return_value=[]),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                self.assertEqual(len(compile_run.call_args_list), 2)
                self.assertEqual(resolve.call_args.args[1], ["sourceonly.sty"])
                self.assertEqual(install.call_args.args[1], ["sourcepkg"])
            finally:
                os.chdir(previous_cwd)

    def test_tinytex_backend_scans_source_requirements_once_across_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.log").write_text("! LaTeX Error: File `foo.sty' not found.\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[
                            SimpleNamespace(returncode=1),
                            SimpleNamespace(returncode=1),
                            SimpleNamespace(returncode=0),
                        ],
                    ),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch(
                        "texmini.cli.resolve_tinytex_packages",
                        side_effect=[{"foo.sty": "foopkg"}, {"foo.sty": "barpkg"}],
                    ),
                    patch("texmini.cli.tex_source_requirements", return_value=([], ["biber"])) as source_requirements,
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                source_requirements.assert_called_once_with("paper.tex")
                self.assertEqual(install.call_args_list[0].args[1], ["biber", "foopkg"])
                self.assertEqual(install.call_args_list[1].args[1], ["barpkg"])
            finally:
                os.chdir(previous_cwd)

    def test_tinytex_backend_installs_package_only_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.tex").write_text("\\usepackage[backend=biber]{biblatex}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text(
                "Package biblatex Warning: Please (re)run Biber on the file:\n",
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
                    ) as compile_run,
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch("texmini.cli.resolve_tinytex_packages") as resolve,
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                ):
                    output = StringIO()
                    with redirect_stdout(output):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                self.assertEqual(len(compile_run.call_args_list), 2)
                resolve.assert_not_called()
                self.assertEqual(install.call_args.args[1], ["biber"])
                self.assertIn("Missing TeX files found: none", output.getvalue())
            finally:
                os.chdir(previous_cwd)

    def test_tinytex_backend_reads_log_once_per_autoinstall_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
            Path(directory, "paper.log").write_text(
                "! LaTeX Error: File `foo.sty' not found.\n"
                "Package biblatex Warning: Please (re)run Biber on the file:\n",
                encoding="utf-8",
            )
            log_path = str(Path(directory, "paper.log").resolve())

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
                    ),
                    patch("texmini.cli.tex_source_requirements", return_value=([], [])),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch("texmini.cli.resolve_tinytex_packages", return_value={"foo.sty": "foopkg"}),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                    patch("builtins.open", wraps=open) as opened,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, True, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 0)
                self.assertEqual(install.call_args.args[1], ["biber", "foopkg"])
                log_reads = [
                    call
                    for call in opened.call_args_list
                    if os.path.abspath(os.fspath(call.args[0])) == log_path
                ]
                self.assertEqual(len(log_reads), 1)
            finally:
                os.chdir(previous_cwd)

    def test_main_reuses_tex_source_for_bibliography_and_tinytex_autoinstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.tex").write_text(
                "\\documentclass{article}\n\\usepackage[backend=biber]{biblatex}\n",
                encoding="utf-8",
            )
            Path(directory, "paper.log").write_text("Build failed before bibliography processing.\n", encoding="utf-8")
            paper_path = str(Path(directory, "paper.tex").resolve())

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch(
                        "texmini.cli.run_tinytex_compile",
                        side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
                    ),
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch("texmini.cli.install_tinytex_packages", return_value=SimpleNamespace(returncode=0)) as install,
                    patch("builtins.open", wraps=open) as opened,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.main(["paper.tex"])

                self.assertEqual(result, 0)
                self.assertEqual(install.call_args.args[1], ["biber"])
                source_reads = [
                    call
                    for call in opened.call_args_list
                    if os.path.abspath(os.fspath(call.args[0])) == paper_path
                ]
                self.assertEqual(len(source_reads), 1)
            finally:
                os.chdir(previous_cwd)

    def test_no_install_prevents_tinytex_install_and_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "TinyTeX"
            bin_dir = root / "bin" / "universal-darwin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "latexmk").write_text("", encoding="utf-8")
            Path(directory, "paper.log").write_text("! LaTeX Error: File `foo.sty' not found.\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with (
                    patch.dict(os.environ, {"TEXMINI_TINYTEX_ROOT": str(root)}),
                    patch("texmini.cli.run_tinytex_compile", return_value=SimpleNamespace(returncode=1)) as compile_run,
                    patch("texmini.cli.missing_tinytex_source_files", return_value=[]),
                    patch("texmini.cli.install_tinytex_packages") as install,
                ):
                    with redirect_stdout(StringIO()):
                        result = cli.run_tinytex_backend("pdflatex", True, False, "paper.tex", ["paper.tex"])

                self.assertEqual(result.returncode, 1)
                self.assertEqual(len(compile_run.call_args_list), 1)
                install.assert_not_called()
            finally:
                os.chdir(previous_cwd)

    def test_managed_tinytex_compile_cannot_stop_for_interactive_input(self) -> None:
        with patch("texmini.cli.run_command", return_value=SimpleNamespace(returncode=1)) as run:
            cli.run_tinytex_compile("pdflatex", ["paper.tex"], Path("TinyTeX"), env={})

        self.assertEqual(
            run.call_args.args[0],
            ["latexmk", "-pdf", "-interaction=nonstopmode", "paper.tex"],
        )

    def test_managed_failure_reports_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous_cwd = Path.cwd()
            try:
                os.chdir(directory)
                Path("paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
                Path("paper.log").write_text("! LaTeX Error: File `missing.sty' not found.\n", encoding="utf-8")

                with patch(
                    "texmini.cli.run_tinytex_backend",
                    return_value=SimpleNamespace(returncode=1),
                ):
                    output = StringIO()
                    with redirect_stdout(output):
                        result = cli.main(["paper.tex"])

                self.assertEqual(result, 1)
                self.assertIn("Missing TeX files found: missing.sty", output.getvalue())
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
