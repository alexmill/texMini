import os
import sys
from time import monotonic

from texmini import __version__

from .build import (
    report_build_result,
    run_tinytex_backend,
)
from .model import (
    ENGINE_ARGS,
    CliConfig,
    TexMiniError,
)
from .project import (
    check_bibliography,
    clear_source_cache,
    detect_tex_file,
    resolve_engine,
)
from .reporting import (
    Reporter,
)
from .runtime import (
    install_tinytex,
)
from .watch import watch_document


def print_help() -> None:
    print(
        """Usage: texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex] [OPTIONS] [document.tex] [refs.bib ...]

Compile a LaTeX document with a private TinyTeX runtime.

Options:
  --engine ENGINE   Select pdflatex, lualatex, or xelatex.
  --clean           Remove auxiliary files after a successful build.
  --watch           Rebuild when project files change; do not launch a viewer.
  --shell-escape    Allow the document to run external commands.
  --verbose         Show complete TeX, latexmk, and package-manager output.
  --no-install      Do not install missing TeX Live packages.
  --version         Print the texMini version.

The latexmk option -pvc is accepted as an alias for --watch. All other
arguments are passed through to latexmk."""
    )


def parse_args(argv: list[str]) -> CliConfig:
    engine = os.environ.get("TEXMINI_ENGINE")
    clean = os.environ.get("TEXMINI_CLEAN", "false").lower() == "true"
    verbose = False
    auto_install = os.environ.get("TEXMINI_AUTO_INSTALL", "true").lower() != "false"
    watch = False
    shell_escape = False
    latexmk_args: list[str] = []
    bib_files: list[str] = []
    tex_file: str | None = None
    view_none = False

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--backend" or arg.startswith("--backend="):
            raise TexMiniError(
                "Error: --backend is no longer supported; texMini always uses managed TinyTeX."
            )
        if arg == "--engine":
            if index + 1 >= len(argv):
                raise TexMiniError(
                    "Error: --engine requires pdflatex, lualatex, or xelatex."
                )
            engine = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--engine="):
            engine = arg.split("=", 1)[1]
            index += 1
            continue
        if arg == "--clean":
            clean = True
            index += 1
            continue
        if arg in {"--watch", "-pvc"}:
            watch = True
            index += 1
            continue
        if arg in {"--shell-escape", "-shell-escape"}:
            shell_escape = True
            latexmk_args.append("-shell-escape")
            index += 1
            continue
        if arg == "--verbose":
            verbose = True
            index += 1
            continue
        if arg == "--no-install":
            auto_install = False
            index += 1
            continue
        if arg == "-view=none":
            view_none = True
            index += 1
            continue
        if arg in {"-pv", "-new-viewer", "-new-viewer-"} or arg.startswith("-view="):
            raise TexMiniError(
                "Error: texMini watch mode does not launch or control a PDF viewer."
            )
        if arg.startswith("-pvctimeout"):
            raise TexMiniError(
                "Error: latexmk preview timeout options are not supported by texMini watch mode."
            )
        if arg.endswith(".tex"):
            if tex_file is not None:
                raise TexMiniError(
                    f"Error: Multiple .tex files specified: {tex_file} and {arg}"
                )
            tex_file = arg
            latexmk_args.append(arg)
            index += 1
            continue
        if arg.endswith(".bib"):
            bib_files.append(arg)
            index += 1
            continue
        latexmk_args.append(arg)
        index += 1

    if engine is not None and engine not in ENGINE_ARGS:
        raise TexMiniError("Error: --engine must be pdflatex, lualatex, or xelatex.")
    if clean and watch:
        raise TexMiniError(
            "Error: --clean cannot be combined with --watch because watch mode retains build state."
        )
    if view_none and not watch:
        latexmk_args.append("-view=none")

    return CliConfig(
        engine,
        clean,
        verbose,
        auto_install,
        watch,
        shell_escape,
        latexmk_args,
        bib_files,
        tex_file,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    clear_source_cache()
    if "--help" in argv or "-h" in argv:
        print_help()
        return 0
    if "--version" in argv:
        print(__version__)
        return 0
    if "install-tinytex" in argv:
        remaining = [arg for arg in argv if arg != "--verbose"]
        if remaining != ["install-tinytex"]:
            print("Error: install-tinytex only accepts --verbose.", file=sys.stderr)
            return 1
        return install_tinytex("--verbose" in argv)

    started_at = monotonic()
    reporter = Reporter("--verbose" in argv)
    try:
        config = parse_args(argv)
        reporter = Reporter(config.verbose)
        detected_tex_file = detect_tex_file(
            config.latexmk_args, config.tex_file, reporter
        )
        if config.watch:
            return watch_document(config, detected_tex_file, reporter)
        engine = resolve_engine(config.engine, detected_tex_file, reporter)
        check_bibliography(detected_tex_file, config.bib_files, reporter)
        outcome = run_tinytex_backend(
            engine,
            config.auto_install,
            config.verbose,
            detected_tex_file,
            config.latexmk_args,
            started_at,
            reporter,
        )
    except TexMiniError as error:
        reporter.error(str(error))
        return 1

    return report_build_result(
        outcome,
        detected_tex_file,
        config.clean,
        config.verbose,
        config.auto_install,
        reporter,
    )


if __name__ == "__main__":
    raise SystemExit(main())
