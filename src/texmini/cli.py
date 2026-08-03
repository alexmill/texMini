import os
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import TYPE_CHECKING

from texmini import __version__

if TYPE_CHECKING:
    import subprocess
    import tarfile


ENGINE_ARGS = {
    "pdflatex": ["-pdf"],
    "lualatex": ["-lualatex"],
    "xelatex": ["-xelatex"],
}

AUX_EXTENSIONS = [
    "acn",
    "acr",
    "alg",
    "aux",
    "bbl",
    "bcf",
    "bcf-SAVE-ERROR",
    "blg",
    "fls",
    "fdb_latexmk",
    "glg",
    "glo",
    "gls",
    "glsdefs",
    "idx",
    "ilg",
    "ind",
    "log",
    "nav",
    "nlg",
    "nlo",
    "nls",
    "out",
    "snm",
    "toc",
    "vrb",
    "run.xml",
    "synctex.gz",
]
JOB_AUX_EXTENSIONS = [*AUX_EXTENSIONS, "xdy"]
FIXED_AUXILIARY_FILES = ["missfont.log"]
GENERATED_DIRECTORIES = ["_minted", "_minted-{jobname}"]

TINYTEX_RELEASE_API = (
    "https://api.github.com/repos/rstudio/tinytex-releases/releases/latest"
)
DEFAULT_TINYTEX_BUNDLE = "TinyTeX-0"
TINYTEX_BOOTSTRAP_PACKAGES = ["latex-bin", "latexmk", "metafont", "mfware"]
TINYTEX_ENGINE_PACKAGES = {"xelatex": "xetex"}
DIRECT_TOOL_PACKAGES = {
    "biber": "biber",
    "bibtex": "bibtex",
    "makeglossaries": "glossaries",
    "makeindex": "makeindex",
    "xindy": "xindy",
}
MAX_INSTALL_ROUNDS = 20
MISSING_FILE_EXTENSIONS = "sty|cls|bst|bbx|cbx|def|fd|map|tfm|pfb|otf|ttf|enc|cfg"
COMMON_TEXLIVE_FILE_PACKAGES = {
    "amsmath.sty": "amsmath",
    "authoryear.bbx": "biblatex",
    "authoryear-comp.bbx": "biblatex",
    "authoryear-comp.cbx": "biblatex",
    "biblatex.sty": "biblatex",
    "csquotes.sty": "csquotes",
    "framed.sty": "framed",
    "geometry.sty": "geometry",
    "graphicx.sty": "graphics",
    "hyperref.sty": "hyperref",
    "imakeidx.sty": "imakeidx",
    "memoir.cls": "memoir",
    "minted.sty": "minted",
    "nomencl.sty": "nomencl",
    "numeric.cbx": "biblatex",
    "pgf.sty": "pgf",
    "plainnat.bst": "natbib",
    "tikz.sty": "pgf",
    "tocbasic.sty": "koma-script",
    "unsrtnat.bst": "natbib",
    "xcolor.sty": "xcolor",
}


class TexMiniError(Exception):
    pass


@dataclass(frozen=True)
class PrimaryError:
    message: str
    file: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class CliConfig:
    engine: str | None
    clean: bool
    verbose: bool
    auto_install: bool
    watch: bool
    shell_escape: bool
    latexmk_args: list[str]
    bib_files: list[str]
    tex_file: str | None


@dataclass(frozen=True)
class BuildLayout:
    source: Path
    jobname: str
    aux_dir: Path
    out_dir: Path
    pdf_path: Path
    log_path: Path

    @property
    def display_pdf(self) -> str:
        return display_relative_path(self.pdf_path)

    @property
    def display_log(self) -> str:
        return display_relative_path(self.log_path)


@dataclass(frozen=True)
class SourceRequirements:
    files: tuple[str, ...]
    tools: tuple[str, ...]
    sources: tuple[Path, ...]
    uses_minted: bool = False


@dataclass
class BuildOutcome:
    returncode: int
    elapsed_seconds: float
    pdf_changed: bool
    failure_kind: str | None = None
    missing_files: tuple[str, ...] = ()
    unmapped_files: tuple[str, ...] = ()
    primary_error: PrimaryError | None = None
    layout: BuildLayout | None = None


class Reporter:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._gpg_warning_printed = False

    def status(self, message: str) -> None:
        print(message, flush=True)

    def warning(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    def error(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    def observe_output(self, output: str) -> None:
        if self.verbose or self._gpg_warning_printed:
            return
        if "not verified: gpg unavailable" in output.lower():
            self.warning(
                "Warning: TeX Live could not verify repository signatures because GPG is unavailable."
            )
            self.warning("Use --verbose for details.")
            self._gpg_warning_printed = True


_missing_file_patterns = None
_biblatex_style_patterns = None
_source_patterns = None
_source_cache: dict[str, tuple[int, int, str]] = {}


def run_command(args: list[str], reporter: Reporter | None = None, **kwargs: object):
    import subprocess

    if reporter is None:
        direct_options = dict(kwargs)
        check = bool(direct_options.pop("check", False))
        return subprocess.run(args, check=check, **direct_options)

    options = dict(kwargs)
    options.pop("stdout", None)
    options.pop("stderr", None)
    options.pop("check", None)
    options["stdout"] = subprocess.PIPE
    options["stderr"] = subprocess.STDOUT
    options["text"] = True
    if reporter.verbose:
        process = subprocess.Popen(args, **options)
        output_parts: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            output_parts.append(line)
            print(line, end="", flush=True)
        return subprocess.CompletedProcess(
            args, process.wait(), "".join(output_parts), None
        )

    result = subprocess.run(args, check=False, **options)
    reporter.observe_output(result.stdout or "")
    return result


def read_source_file(path: str) -> str:
    cache_key = os.path.abspath(os.fspath(path))
    stat_result = os.stat(path)
    cached = _source_cache.get(cache_key)
    if (
        cached is None
        or cached[0] != stat_result.st_mtime_ns
        or cached[1] != stat_result.st_size
    ):
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        _source_cache[cache_key] = (
            stat_result.st_mtime_ns,
            stat_result.st_size,
            source,
        )
        return source
    return cached[2]


def strip_tex_comments(source: str) -> str:
    uncommented: list[str] = []
    for line in source.splitlines(keepends=True):
        for index, character in enumerate(line):
            if character != "%":
                continue
            preceding_backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                preceding_backslashes += 1
                cursor -= 1
            if preceding_backslashes % 2:
                continue
            line_ending = (
                "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            )
            line = f"{line[:index]}{line_ending}"
            break
        uncommented.append(line)
    return "".join(uncommented)


def missing_file_patterns():
    import re

    global _missing_file_patterns
    if _missing_file_patterns is None:
        _missing_file_patterns = [
            re.compile(
                rf"File\s+[`'\"]([^`'\"]+\.({MISSING_FILE_EXTENSIONS}))['\"]\s+not found",
                re.IGNORECASE,
            ),
            re.compile(
                rf"I\s+(?:can't|cannot|couldn't|could not)\s+find\s+file\s+[`'\"]?([^`'\"\s]+\.({MISSING_FILE_EXTENSIONS}))",
                re.IGNORECASE,
            ),
            re.compile(
                r"I couldn't open style file\s+([^`'\"\s]+\.bst)\b", re.IGNORECASE
            ),
            re.compile(r"mktextfm\s+([A-Za-z0-9_.-]+)"),
            re.compile(
                r"Font .*=([A-Za-z0-9_.-]+).*Metric \(TFM\) file not found",
                re.IGNORECASE,
            ),
            re.compile(
                r"pdfTeX error:.*?\(file\s+([A-Za-z0-9_.-]+)\):\s+Font\b[^\n]*\bnot found",
                re.IGNORECASE,
            ),
        ]
    return _missing_file_patterns


def biblatex_style_patterns():
    import re

    global _biblatex_style_patterns
    if _biblatex_style_patterns is None:
        _biblatex_style_patterns = (
            re.compile(
                r"Package biblatex Info:\s+Trying to load (bibliography|citation) style [`'\"]([^`'\"]+)['\"]",
                re.IGNORECASE,
            ),
            re.compile(
                r"Package biblatex Error:\s+Style [`'\"]([^`'\"]+)['\"]\s+not found",
                re.IGNORECASE,
            ),
        )
    return _biblatex_style_patterns


def source_patterns():
    import re

    global _source_patterns
    if _source_patterns is None:
        _source_patterns = (
            re.compile(r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\bbiblatex\b[^}]*\}"),
            re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}"),
            re.compile(r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]+)\}"),
            re.compile(r"^[A-Za-z0-9_.+-]+\.(sty|cls|bst)$"),
        )
    return _source_patterns


def source_uses_bibliography(source: str) -> bool:
    source = strip_tex_comments(source)
    if "\\bibliography{" in source or "\\addbibresource{" in source:
        return True
    if "biblatex" not in source or "\\usepackage" not in source:
        return False
    biblatex_package_pattern, _, _, _ = source_patterns()
    return bool(biblatex_package_pattern.search(source))


def project_source_files(tex_file: str) -> list[Path]:
    import re

    root = Path(tex_file).resolve()
    pending = [root]
    discovered: list[Path] = []
    seen: set[Path] = set()
    include_pattern = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
    class_pattern = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}")
    package_pattern = re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]+)\}"
    )

    while pending:
        path = pending.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        discovered.append(path)
        source = strip_tex_comments(read_source_file(os.fspath(path)))
        local_candidates: list[Path] = []
        for match in include_pattern.finditer(source):
            name = match.group(1).strip()
            candidate = path.parent / name
            local_candidates.append(
                candidate if candidate.suffix else candidate.with_suffix(".tex")
            )
        for match in class_pattern.finditer(source):
            local_candidates.append(path.parent / f"{match.group(1).strip()}.cls")
        for match in package_pattern.finditer(source):
            local_candidates.extend(
                path.parent / f"{package.strip()}.sty"
                for package in match.group(1).split(",")
            )
        pending.extend(
            candidate.resolve() for candidate in local_candidates if candidate.is_file()
        )
    return discovered


def analyze_source_requirements(tex_file: str) -> SourceRequirements:
    import re

    source_paths = project_source_files(tex_file)
    source = "\n".join(
        strip_tex_comments(read_source_file(os.fspath(path))) for path in source_paths
    )
    found: list[str] = []
    seen: set[str] = set()
    _, documentclass_pattern, package_pattern, package_file_pattern = source_patterns()

    def add_file(name: str, extension: str) -> None:
        file_name = f"{name.strip()}.{extension}"
        if package_file_pattern.match(file_name) and file_name not in seen:
            seen.add(file_name)
            found.append(file_name)

    for match in documentclass_pattern.finditer(source):
        add_file(match.group(1), "cls")
    for match in package_pattern.finditer(source):
        for package in match.group(1).split(","):
            add_file(package, "sty")
    for match in re.finditer(r"\\bibliographystyle\s*\{([^}]+)\}", source):
        add_file(match.group(1), "bst")

    tools: list[str] = []
    package_names = {
        file_name.removesuffix(".sty")
        for file_name in found
        if file_name.endswith(".sty")
    }
    biblatex_match = re.search(
        r"\\usepackage(?:\[([^\]]*)\])?\{[^}]*\bbiblatex\b[^}]*\}", source
    )
    if biblatex_match:
        options = biblatex_match.group(1) or ""
        tools.append(
            "bibtex"
            if re.search(r"(?:^|,)\s*backend\s*=\s*bibtex\b", options)
            else "biber"
        )
    elif (
        "\\bibliography{" in source
        or "\\bibliographystyle{" in source
        or "natbib" in package_names
    ):
        tools.append("bibtex")

    if "\\makeglossaries" in source and package_names & {
        "glossaries",
        "glossaries-extra",
    }:
        tools.append("makeglossaries")
        glossaries_options = " ".join(
            match.group(1) or ""
            for match in re.finditer(
                r"\\usepackage(?:\[([^\]]*)\])?\{(?:glossaries|glossaries-extra)\}",
                source,
            )
        )
        tools.append(
            "xindy"
            if re.search(r"(?:^|,)\s*xindy(?:\s|,|$)", glossaries_options)
            else "makeindex"
        )
    if (
        "\\makenomenclature" in source
        or "\\makeindex" in source
        or package_names & {"makeidx", "imakeidx", "nomencl"}
    ):
        tools.append("makeindex")

    return SourceRequirements(
        tuple(found),
        tuple(dict.fromkeys(tools)),
        tuple(source_paths),
        uses_minted="minted" in package_names,
    )


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

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--backend" or arg.startswith("--backend="):
            raise TexMiniError(
                "Error: --backend is no longer supported; texMini always uses managed TinyTeX."
            )
        if arg == "--engine":
            if i + 1 >= len(argv):
                raise TexMiniError(
                    "Error: --engine requires pdflatex, lualatex, or xelatex."
                )
            engine = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--engine="):
            engine = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--clean":
            clean = True
            i += 1
            continue
        if arg in {"--watch", "-pvc"}:
            watch = True
            i += 1
            continue
        if arg in {"--shell-escape", "-shell-escape"}:
            shell_escape = True
            latexmk_args.append("-shell-escape")
            i += 1
            continue
        if arg == "--verbose":
            verbose = True
            i += 1
            continue
        if arg == "--no-install":
            auto_install = False
            i += 1
            continue
        if arg == "-view=none":
            view_none = True
            i += 1
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
            i += 1
            continue
        if arg.endswith(".bib"):
            bib_files.append(arg)
            i += 1
            continue

        latexmk_args.append(arg)
        i += 1

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


def executable_on_path(command: str) -> str | None:
    for directory in os.environ.get("PATH", os.defpath).split(os.pathsep):
        candidate = os.path.join(directory or ".", command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def detect_tex_file(
    latexmk_args: list[str], tex_file: str | None, reporter: Reporter | None = None
) -> str:
    reporter = reporter or Reporter()
    if tex_file is not None:
        if not Path(tex_file).is_file():
            raise TexMiniError(f"Error: LaTeX source file '{tex_file}' does not exist.")
        return tex_file

    tex_files = sorted(
        entry.name
        for entry in os.scandir(os.getcwd())
        if entry.is_file() and entry.name.endswith(".tex")
    )
    candidates = [
        file_name
        for file_name in tex_files
        if "\\documentclass" in strip_tex_comments(read_source_file(file_name))
    ]
    if len(tex_files) == 1:
        detected = tex_files[0]
    elif len(candidates) == 1:
        detected = candidates[0]
    else:
        detected = None
    if detected is not None:
        reporter.status(f"Auto-detected LaTeX file: {detected}")
        latexmk_args.append(detected)
        return detected

    print("Error: No .tex file specified and unable to auto-detect.")
    if not tex_files:
        print("No .tex files found in current directory.")
    else:
        print(f"Multiple .tex files found: {' '.join(tex_files)}")
        print("Please specify which file to compile.")
    raise SystemExit(1)


def source_engine_directive(tex_file: str) -> str | None:
    import re

    source = read_source_file(tex_file)
    pattern = re.compile(
        r"^\s*%\s*!\s*(?:TeX\s+program|TEX\s+TS-program)\s*=\s*([^\s%]+)",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(source)
    return match.group(1).lower() if match else None


def resolve_engine(
    configured_engine: str | None, tex_file: str, reporter: Reporter
) -> str:
    if configured_engine is not None:
        return configured_engine
    directive = source_engine_directive(tex_file)
    if directive in ENGINE_ARGS:
        return directive
    if directive is not None:
        reporter.warning(
            f"Warning: Source requests unsupported TeX program '{directive}'; using pdflatex."
        )
    return "pdflatex"


def check_bibliography(
    tex_file: str, bib_files: list[str], reporter: Reporter | None = None
) -> None:
    import re

    reporter = reporter or Reporter()
    tex_path = os.fspath(tex_file)
    if not os.path.isfile(tex_path):
        return

    source = strip_tex_comments(read_source_file(tex_path))
    if not source_uses_bibliography(source):
        return

    referenced = {
        item.strip()
        for match in re.finditer(
            r"\\(?:bibliography|addbibresource)\{([^}]+)\}", source
        )
        for item in match.group(1).split(",")
    }

    def is_referenced(bib_file: str) -> bool:
        path = Path(bib_file)
        return (
            bib_file in referenced or path.name in referenced or path.stem in referenced
        )

    if bib_files:
        for bib_file in bib_files:
            if not os.path.isfile(bib_file):
                raise TexMiniError(
                    f"Error: Specified bibliography file '{bib_file}' not found"
                )
            if not is_referenced(bib_file):
                reporter.warning(
                    f"Warning: Bibliography file {bib_file} is not referenced in {tex_file}."
                )
                reporter.warning(
                    f"You may need to add \\addbibresource{{{bib_file}}} to your document."
                )
        return

    source_directory = Path(tex_path).parent
    detected_bib_files = sorted(
        entry.name
        for entry in os.scandir(source_directory)
        if entry.is_file() and entry.name.endswith(".bib")
    )
    if len(detected_bib_files) == 1:
        bib_file = detected_bib_files[0]
        if not is_referenced(bib_file):
            reporter.warning(
                f"Warning: Bibliography file {bib_file} is not referenced in {tex_file}."
            )
            reporter.warning(
                f"You may need to add \\addbibresource{{{bib_file}}} to your document."
            )
    elif not detected_bib_files:
        reporter.warning(
            f"Warning: Bibliography commands were found in {tex_file}, but no .bib files were found."
        )
    else:
        reporter.warning(
            f"Warning: Multiple bibliography files found: {' '.join(detected_bib_files)}"
        )


def default_build_layout(tex_file: str) -> BuildLayout:
    source = Path(tex_file)
    base = source.with_suffix("")
    return BuildLayout(
        source,
        base.name,
        base.parent,
        base.parent,
        base.with_suffix(".pdf"),
        base.with_suffix(".log"),
    )


def cleanup_auxiliary_files(tex_file: str, layout: BuildLayout | None = None) -> None:
    import re
    import shutil

    layout = layout or default_build_layout(tex_file)
    fls_path = layout.aux_dir / f"{layout.jobname}.fls"
    database_path = layout.aux_dir / f"{layout.jobname}.fdb_latexmk"
    dependency_artifacts: set[Path] = set()
    if fls_path.is_file():
        for line in fls_path.read_text(encoding="utf-8", errors="replace").splitlines():
            kind, separator, name = line.partition(" ")
            if not separator or kind not in {"INPUT", "OUTPUT"}:
                continue
            path = Path(name)
            if not path.is_absolute():
                path = layout.source.parent / path
            if any(path.name.endswith(f".{extension}") for extension in AUX_EXTENSIONS):
                dependency_artifacts.add(path.resolve())
    if database_path.is_file():
        database = database_path.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r'"([^"\n]+)"', database):
            path = Path(name)
            if not path.is_absolute():
                path = layout.source.parent / path
            if any(path.name.endswith(f".{extension}") for extension in AUX_EXTENSIONS):
                dependency_artifacts.add(path.resolve())
    for path in dependency_artifacts:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for extension in JOB_AUX_EXTENSIONS:
        try:
            os.unlink(layout.aux_dir / f"{layout.jobname}.{extension}")
        except FileNotFoundError:
            pass
        if layout.out_dir != layout.aux_dir:
            try:
                os.unlink(layout.out_dir / f"{layout.jobname}.{extension}")
            except FileNotFoundError:
                pass
    source_directory = layout.source.parent
    for path in FIXED_AUXILIARY_FILES:
        try:
            os.unlink(source_directory / path)
        except FileNotFoundError:
            pass
    for pattern in GENERATED_DIRECTORIES:
        generated = layout.aux_dir / pattern.format(jobname=layout.jobname)
        if generated.is_dir():
            shutil.rmtree(generated)


def display_relative_path(path: Path) -> str:
    try:
        return os.fspath(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return os.fspath(path)


def tinytex_root() -> "Path":
    return Path(
        os.environ.get("TEXMINI_TINYTEX_ROOT", Path.home() / ".texmini" / "TinyTeX")
    )


def package_map_path() -> "Path":
    return Path(
        os.environ.get(
            "TEXMINI_PACKAGE_MAP", Path.home() / ".texmini" / "package-map.json"
        )
    )


def display_path(path: Path) -> str:
    try:
        return os.fspath(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return os.fspath(path)


def tinytex_bin_dir(root: "Path", executable: str = "latexmk") -> "Path":
    bin_root = root / "bin"
    for path in sorted(bin_root.iterdir() if bin_root.exists() else []):
        if (path / executable).exists():
            return path
    raise TexMiniError(
        f"Error: TinyTeX does not provide {executable} at {root}. Run: texmini install-tinytex"
    )


def tinytex_env(root: "Path", executable: str = "latexmk") -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = tinytex_bin_dir(root, executable)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["LATEXMKRCSYS"] = os.fspath(Path(__file__).with_name("texmini_latexmkrc"))
    return env


def tinytex_bundle() -> str:
    return os.environ.get("TEXMINI_TINYTEX_BUNDLE", DEFAULT_TINYTEX_BUNDLE)


def tinytex_platform_key() -> str:
    import platform

    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        machine = platform.machine().lower()
        if machine in {"aarch64", "arm64"}:
            return "linux-arm64"
        libc = platform.libc_ver()[0].lower()
        return "linuxmusl-x86_64" if libc == "musl" else "linux-x86_64"
    raise TexMiniError(
        "Error: The Python TinyTeX installer currently supports macOS and Linux."
    )


def latest_tinytex_asset() -> tuple[str, str, str | None]:
    import json
    import urllib.request

    bundle = tinytex_bundle()
    prefix = f"{bundle}-{tinytex_platform_key()}-"
    request = urllib.request.Request(
        TINYTEX_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"texmini/{__version__}",
        },
    )
    if github_token := os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {github_token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    for asset in release["assets"]:
        name = asset["name"]
        if name.startswith(prefix) and name.endswith(".tar.xz"):
            return name, asset["browser_download_url"], asset.get("digest")
    raise TexMiniError(f"Error: No {bundle} TinyTeX archive found for this platform.")


def update_tinytex_manager(root: "Path", reporter: Reporter) -> None:
    env = tinytex_env(root, "tlmgr")
    if reporter.verbose:
        reporter.status("Updating the managed TinyTeX package manager...")
    update_result = run_command(
        ["tlmgr", "update", "--self"], reporter=reporter, env=env, check=False
    )
    if update_result.returncode != 0:
        raise TexMiniError("Error: TinyTeX package manager bootstrap failed.")


def bootstrap_tinytex(root: "Path", reporter: Reporter) -> None:
    update_tinytex_manager(root, reporter)
    env = tinytex_env(root, "tlmgr")
    reporter.status("Installing the LaTeX compiler...")
    install_result = run_command(
        ["tlmgr", "install", *TINYTEX_BOOTSTRAP_PACKAGES],
        reporter=reporter,
        env=env,
        check=False,
    )
    if install_result.returncode != 0:
        raise TexMiniError("Error: TinyTeX bootstrap package installation failed.")
    tinytex_bin_dir(root)


def validate_tinytex_archive_member(member: "tarfile.TarInfo") -> None:
    import posixpath

    path = member.name.replace("\\", "/")
    normalized_path = posixpath.normpath(path)

    def is_managed_path(candidate: str) -> bool:
        return any(
            candidate == root_name or candidate.startswith(f"{root_name}/")
            for root_name in ("TinyTeX", ".TinyTeX")
        )

    if "\0" in path or posixpath.isabs(path) or not is_managed_path(normalized_path):
        raise TexMiniError(f"Error: Unsafe path in TinyTeX archive: {member.name}")
    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
        raise TexMiniError(
            f"Error: Unsupported entry in TinyTeX archive: {member.name}"
        )
    if member.issym() or member.islnk():
        link_path = member.linkname.replace("\\", "/")
        target = (
            posixpath.normpath(
                posixpath.join(posixpath.dirname(normalized_path), link_path)
            )
            if member.issym()
            else posixpath.normpath(link_path)
        )
        if posixpath.isabs(link_path) or not is_managed_path(target):
            raise TexMiniError(
                f"Error: Unsafe link in TinyTeX archive: {member.name} -> {member.linkname}"
            )


def install_tinytex_archive(root: "Path", reporter: Reporter | None = None) -> None:
    import hashlib
    import shutil
    import tarfile
    import tempfile
    import urllib.request

    reporter = reporter or Reporter()

    if executable_on_path("perl") is None:
        raise TexMiniError(
            "Error: Perl is required to install and run TinyTeX. Install Perl and retry."
        )

    if (root / "bin").exists():
        if tinytex_bundle() == "TinyTeX-0":
            try:
                tinytex_bin_dir(root)
            except TexMiniError:
                bootstrap_tinytex(root, reporter)
        else:
            tinytex_bin_dir(root)
        return

    reporter.status(f"Preparing a private TinyTeX runtime in {display_path(root)}.")
    reporter.status(
        "This one-time setup requires a network connection and may take a minute."
    )
    name, url, digest = latest_tinytex_asset()
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".texmini-extract-", dir=root.parent
    ) as temporary_directory:
        extraction_root = Path(temporary_directory)
        archive_path = extraction_root / name
        if reporter.verbose:
            reporter.status(f"Downloading {url}")
        with (
            urllib.request.urlopen(url, timeout=60) as response,
            archive_path.open("wb") as archive,
        ):
            shutil.copyfileobj(response, archive)
        if digest and digest.startswith("sha256:"):
            expected = digest.removeprefix("sha256:")
            checksum = hashlib.sha256()
            with archive_path.open("rb") as archive:
                for chunk in iter(lambda: archive.read(1024 * 1024), b""):
                    checksum.update(chunk)
            actual = checksum.hexdigest()
            if actual != expected:
                raise TexMiniError(f"Error: Checksum verification failed for {name}.")
            if reporter.verbose:
                reporter.status(f"Verified SHA-256: {actual}")
        reporter.status(f"Downloaded {tinytex_bundle()}.")
        if reporter.verbose:
            reporter.status(f"Extracting {name}...")
        with tarfile.open(archive_path, mode="r:xz") as tar:
            for member in tar:
                validate_tinytex_archive_member(member)
                tar.extract(member, extraction_root)
        extracted_root = next(
            (
                candidate
                for root_name in ("TinyTeX", ".TinyTeX")
                if (candidate := extraction_root / root_name).exists()
            ),
            None,
        )
        if extracted_root is None:
            raise TexMiniError(
                "Error: TinyTeX archive did not contain a TinyTeX runtime."
            )
        extracted_root.rename(root)
    if tinytex_bundle() == "TinyTeX-0":
        bootstrap_tinytex(root, reporter)
    else:
        update_tinytex_manager(root, reporter)
    tinytex_bin_dir(root)


def install_tinytex(verbose: bool = False) -> int:
    reporter = Reporter(verbose)
    try:
        install_tinytex_archive(tinytex_root(), reporter)
        return 0
    except TexMiniError as error:
        reporter.error(str(error))
        return 1


def tex_log_requirements(log_path: "Path") -> tuple[list[str], list[str]]:
    log_file = os.fspath(log_path)
    if not os.path.isfile(log_file):
        return [], []

    found: list[str] = []
    seen: set[str] = set()
    with open(log_file, encoding="utf-8", errors="replace") as handle:
        source = handle.read()

    def add_missing_file(missing_file: str) -> None:
        if "." not in missing_file:
            missing_file = f"{missing_file}.tfm"
        if missing_file not in seen:
            seen.add(missing_file)
            found.append(missing_file)

    for pattern in missing_file_patterns():
        for match in pattern.finditer(source):
            line_start = source.rfind("\n", 0, match.start()) + 1
            line_end = source.find("\n", match.end())
            line = source[line_start : None if line_end == -1 else line_end]
            if " info:" in line.lower() or "skipping" in line.lower():
                continue
            add_missing_file(match.group(1))

    context_pattern, error_pattern = biblatex_style_patterns()
    biblatex_context: dict[str, str] = {}
    for line in source.splitlines():
        context_match = context_pattern.search(line)
        if context_match:
            biblatex_context[context_match.group(2)] = context_match.group(1).lower()
            continue

        error_match = error_pattern.search(line)
        if not error_match:
            continue

        style = error_match.group(1)
        context = biblatex_context.get(style)
        if context == "bibliography":
            add_missing_file(f"{style}.bbx")
        elif context == "citation":
            add_missing_file(f"{style}.cbx")
        else:
            add_missing_file(f"{style}.bbx")
            add_missing_file(f"{style}.cbx")
    direct_packages = (
        ["biber"]
        if "Package biblatex Warning:" in source and "Please (re)run Biber" in source
        else []
    )
    return found, direct_packages


def tex_source_requirements(tex_file: str) -> tuple[list[str], list[str]]:
    if not os.path.isfile(os.fspath(tex_file)):
        return [], []
    requirements = analyze_source_requirements(tex_file)
    packages = [DIRECT_TOOL_PACKAGES[tool] for tool in requirements.tools]
    return list(requirements.files), list(dict.fromkeys(packages))


def tex_source_package_files(tex_file: str) -> list[str]:
    source_files, _ = tex_source_requirements(tex_file)
    return source_files


def missing_tinytex_source_files(
    root: "Path",
    tex_file: str,
    env: dict[str, str] | None = None,
    source_files: list[str] | None = None,
    reporter: Reporter | None = None,
) -> list[str]:
    env = tinytex_env(root) if env is None else env
    source_files = (
        tex_source_package_files(tex_file) if source_files is None else source_files
    )
    if not source_files:
        return []

    import subprocess

    source_directory = Path(tex_file).resolve().parent
    project_root = Path.cwd().resolve()
    try:
        source_directory.relative_to(project_root)
    except ValueError:
        project_root = source_directory
    source_directories = {path.parent for path in project_source_files(tex_file)}
    local_files = set()
    for file_name in source_files:
        if any((directory / file_name).is_file() for directory in source_directories):
            local_files.add(file_name)
            continue
        if next(project_root.rglob(file_name), None) is not None:
            local_files.add(file_name)
    search_files = [
        file_name for file_name in source_files if file_name not in local_files
    ]
    if not search_files:
        return []
    result = run_command(
        ["kpsewhich", *search_files],
        reporter=reporter,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        cwd=source_directory,
    )
    found_files = {
        os.path.basename(line) for line in result.stdout.splitlines() if line
    }
    return [file_name for file_name in search_files if file_name not in found_files]


def load_package_map(path: "Path") -> dict[str, str]:
    import json

    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {str(key): str(value) for key, value in data.items() if value}


def save_package_map(path: "Path", package_map: dict[str, str]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(package_map, handle, indent=2, sort_keys=True)
        handle.write("\n")


def package_from_tlmgr_search(output: str) -> str | None:
    pending_package: str | None = None
    for line in output.splitlines():
        if pending_package and "texmf-dist/" in line:
            return pending_package
        package_name, separator, rest = line.partition(":")
        if (
            not separator
            or not package_name
            or not all(char.isalnum() or char in "_.+-" for char in package_name)
        ):
            continue
        if "texmf-dist/" in rest:
            return package_name
        if not rest.strip():
            pending_package = package_name
            continue
    return None


def common_texlive_package_for_file(file_name: str) -> str | None:
    if file_name.endswith(".tfm"):
        stem = file_name[:-4]
        if (
            len(stem) > 4
            and stem[0] in {"e", "t"}
            and stem[1:4] == "crm"
            and stem[4:].isdigit()
        ):
            return "ec"
    return COMMON_TEXLIVE_FILE_PACKAGES.get(file_name)


def resolve_tinytex_packages(
    root: "Path",
    missing_files: list[str],
    cache_path: "Path | None" = None,
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
) -> dict[str, str]:
    env = tinytex_env(root) if env is None else env
    cache_path = package_map_path() if cache_path is None else cache_path
    package_map = load_package_map(cache_path)
    resolved: dict[str, str] = {}
    updated = False

    for missing_file in dict.fromkeys(missing_files):
        cached_package = package_map.get(missing_file)
        if cached_package:
            resolved[missing_file] = cached_package
            continue

        built_in_package = common_texlive_package_for_file(missing_file)
        if built_in_package:
            package_map[missing_file] = built_in_package
            resolved[missing_file] = built_in_package
            updated = True
            continue

        import subprocess

        result = run_command(
            ["tlmgr", "search", "--global", "--file", f"/{missing_file}"],
            reporter=reporter,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        package = package_from_tlmgr_search(result.stdout)
        if package:
            package_map[missing_file] = package
            resolved[missing_file] = package
            updated = True

    if updated:
        save_package_map(cache_path, package_map)
    return resolved


def install_tinytex_packages(
    root: "Path",
    packages: list[str],
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
) -> "subprocess.CompletedProcess[str]":
    env = tinytex_env(root) if env is None else env
    return run_command(
        ["tlmgr", "install", *packages], reporter=reporter, env=env, check=False
    )


def ensure_tinytex_engine(
    root: "Path", engine: str, env: dict[str, str], reporter: Reporter
) -> None:
    package = TINYTEX_ENGINE_PACKAGES.get(engine)
    if package is None or executable_on_path_with_env(engine, env):
        return

    reporter.status(f"Installing the {engine} engine...")
    result = install_tinytex_packages(root, [package], env, reporter)
    if result.returncode != 0:
        raise TexMiniError(f"Error: TinyTeX could not install the {engine} engine.")


def executable_on_path_with_env(command: str, env: dict[str, str]) -> str | None:
    for directory in env.get("PATH", os.defpath).split(os.pathsep):
        candidate = os.path.join(directory or ".", command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def run_tinytex_compile(
    engine: str,
    latexmk_args: list[str],
    root: "Path",
    force: bool = False,
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
    cwd: "Path | None" = None,
) -> "subprocess.CompletedProcess[str]":
    env = tinytex_env(root) if env is None else env
    force_args = ["-g"] if force else []
    return run_command(
        [
            "latexmk",
            *ENGINE_ARGS[engine],
            "-cd",
            "-interaction=nonstopmode",
            "-file-line-error",
            *force_args,
            *latexmk_args,
        ],
        reporter=reporter,
        env=env,
        cwd=cwd,
        check=False,
    )


def resolve_build_layout(
    engine: str,
    latexmk_args: list[str],
    tex_file: str,
    env: dict[str, str],
    reporter: Reporter,
) -> BuildLayout:
    import re

    result = run_command(
        ["latexmk", *ENGINE_ARGS[engine], "-cd", "-dir-report-only", *latexmk_args],
        reporter=reporter,
        env=env,
        cwd=Path.cwd(),
        check=False,
    )
    if result.returncode != 0:
        raise TexMiniError(
            "Error: latexmk could not resolve the project configuration."
        )
    output = result.stdout or ""
    cwd_match = re.search(r"^Latexmk: Cwd: ['\"](.+?)['\"]$", output, re.MULTILINE)
    dirs_match = re.search(
        r"Normalized aux dir, out dir, out2 dir:\s*\n\s*['\"](.+?)['\"],\s*['\"](.+?)['\"],\s*['\"](.+?)['\"]",
        output,
    )
    job_match = re.search(
        r"Base name of generated files:\s*\n\s*['\"](.+?)['\"]", output
    )
    if not cwd_match or not dirs_match or not job_match:
        raise TexMiniError("Error: latexmk did not report the project output layout.")

    compile_directory = Path(cwd_match.group(1))
    aux_dir = Path(dirs_match.group(1))
    out_dir = Path(dirs_match.group(3))
    if not aux_dir.is_absolute():
        aux_dir = compile_directory / aux_dir
    if not out_dir.is_absolute():
        out_dir = compile_directory / out_dir
    jobname = job_match.group(1)
    source = Path(tex_file)
    if not source.is_absolute():
        source = Path.cwd() / source
    return BuildLayout(
        source.resolve(),
        jobname,
        aux_dir.resolve(),
        out_dir.resolve(),
        out_dir.resolve() / f"{jobname}.pdf",
        aux_dir.resolve() / f"{jobname}.log",
    )


def pdf_snapshot(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat_result = path.stat()
    return stat_result.st_mtime_ns, stat_result.st_size


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remaining = divmod(round(seconds), 60)
    return f"{minutes}m {remaining:02d}s"


def primary_latex_error(
    log_path: Path, tex_file: str, missing_files: list[str]
) -> PrimaryError | None:
    import re

    if missing_files:
        return PrimaryError(f"{missing_files[0]} is missing")
    if not log_path.is_file():
        return None
    source = log_path.read_text(encoding="utf-8", errors="replace")
    file_line = re.search(r"^(.*?\.tex):(\d+):\s*(?:!\s*)?(.+)$", source, re.MULTILINE)
    if file_line:
        return PrimaryError(
            file_line.group(3).strip().rstrip("."),
            file_line.group(1).removeprefix("./"),
            int(file_line.group(2)),
        )
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("! "):
            continue
        message = line[2:].strip().rstrip(".")
        for context in lines[index + 1 : index + 8]:
            line_match = re.match(r"l\.(\d+)\s", context)
            if line_match:
                return PrimaryError(message, tex_file, int(line_match.group(1)))
        return PrimaryError(message)
    return None


def document_warnings(log_path: Path) -> list[str]:
    import re

    if not log_path.is_file():
        return []
    patterns = (
        re.compile(
            r"(?:LaTeX|Package \S+|Class \S+) Warning:.*(?:undefined|rerun|\(re\)run)",
            re.IGNORECASE,
        ),
        re.compile(
            r"LaTeX Warning: There were undefined (?:references|citations)",
            re.IGNORECASE,
        ),
        re.compile(r"Missing character:", re.IGNORECASE),
        re.compile(r"Font Warning:.*(?:not available|substituted)", re.IGNORECASE),
    )
    warnings: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if (
            stripped
            and any(pattern.search(stripped) for pattern in patterns)
            and stripped not in warnings
        ):
            warnings.append(stripped)
    return warnings


def show_resolution_mappings(resolved: dict[str, str], reporter: Reporter) -> None:
    if not reporter.verbose:
        return
    for file_name, package in resolved.items():
        reporter.status(f"{file_name} -> {package}")


def run_tinytex_backend(
    engine: str,
    auto_install: bool,
    verbose: bool,
    tex_file: str,
    latexmk_args: list[str],
    started_at: float | None = None,
    reporter: Reporter | None = None,
) -> BuildOutcome:
    started_at = monotonic() if started_at is None else started_at
    reporter = reporter or Reporter(verbose)
    root = tinytex_root()

    install_tinytex_archive(root, reporter)
    env = tinytex_env(root)
    ensure_tinytex_engine(root, engine, env, reporter)
    layout = resolve_build_layout(engine, latexmk_args, tex_file, env, reporter)
    pdf_before = pdf_snapshot(layout.pdf_path)
    requirements = analyze_source_requirements(tex_file)
    source_files = list(requirements.files)
    if requirements.uses_minted and "-shell-escape" not in latexmk_args:
        return BuildOutcome(
            1,
            monotonic() - started_at,
            pdf_snapshot(layout.pdf_path) != pdf_before,
            failure_kind="ordinary",
            primary_error=PrimaryError(
                "minted requires external code execution; rerun with --shell-escape"
            ),
            layout=layout,
        )
    missing_tools = [
        tool
        for tool in requirements.tools
        if executable_on_path_with_env(tool, env) is None
    ]
    source_direct_packages = [DIRECT_TOOL_PACKAGES[tool] for tool in missing_tools]
    attempted_packages: set[str] = set()
    install_rounds = 0

    if not auto_install and missing_tools:
        tool = missing_tools[0]
        return BuildOutcome(
            1,
            monotonic() - started_at,
            pdf_snapshot(layout.pdf_path) != pdf_before,
            failure_kind="disabled",
            primary_error=PrimaryError(f"{tool} is required but not installed"),
            layout=layout,
        )

    if auto_install:
        source_missing = missing_tinytex_source_files(
            root, tex_file, env, source_files, reporter
        )
        if source_missing or source_direct_packages:
            reporter.status(f"Analyzing {tex_file}...")
        source_resolved = (
            resolve_tinytex_packages(root, source_missing, env=env, reporter=reporter)
            if source_missing
            else {}
        )
        initial_packages = sorted(
            set(source_resolved.values()) | set(source_direct_packages)
        )
        show_resolution_mappings(source_resolved, reporter)
        if initial_packages:
            noun = "package" if len(initial_packages) == 1 else "packages"
            reporter.status(
                f"Installing {len(initial_packages)} {noun}: {', '.join(initial_packages)}"
            )
            install_result = install_tinytex_packages(
                root, initial_packages, env, reporter
            )
            attempted_packages.update(initial_packages)
            install_rounds += 1
            if install_result.returncode != 0:
                return BuildOutcome(
                    install_result.returncode,
                    monotonic() - started_at,
                    pdf_snapshot(layout.pdf_path) != pdf_before,
                    failure_kind="install_failed",
                    layout=layout,
                )

    reporter.status(f"Compiling {tex_file}...")
    result = run_tinytex_compile(
        engine,
        latexmk_args,
        root,
        env=env,
        reporter=reporter,
        cwd=Path.cwd(),
    )
    last_missing_files: list[str] = []
    last_unmapped_files: list[str] = []

    while result.returncode != 0:
        missing_files, log_direct_packages = tex_log_requirements(layout.log_path)
        for missing_file in missing_tinytex_source_files(
            root, tex_file, env, source_files, reporter
        ):
            if missing_file not in missing_files:
                missing_files.append(missing_file)
        direct_packages = [*log_direct_packages, *source_direct_packages]
        last_missing_files = missing_files

        if not auto_install:
            failure_kind = (
                "disabled" if missing_files or direct_packages else "ordinary"
            )
            break

        resolved = (
            resolve_tinytex_packages(root, missing_files, env=env, reporter=reporter)
            if missing_files
            else {}
        )
        show_resolution_mappings(resolved, reporter)
        last_unmapped_files = [
            file_name for file_name in missing_files if file_name not in resolved
        ]
        packages = sorted(
            package
            for package in set(resolved.values()) | set(direct_packages)
            if package not in attempted_packages
        )
        if not packages:
            if last_unmapped_files:
                failure_kind = "unmapped"
            elif primary_latex_error(layout.log_path, tex_file, missing_files):
                failure_kind = "ordinary"
            else:
                failure_kind = "unidentified"
            break
        if install_rounds >= MAX_INSTALL_ROUNDS:
            failure_kind = "ceiling"
            break

        noun = "package" if len(packages) == 1 else "packages"
        dependency = "dependency" if len(packages) == 1 else "dependencies"
        qualifier = (
            f"required {noun}" if install_rounds == 0 else f"additional {dependency}"
        )
        reporter.status(f"Installing {len(packages)} {qualifier}...")
        install_result = install_tinytex_packages(root, packages, env, reporter)
        attempted_packages.update(packages)
        install_rounds += 1
        if install_result.returncode != 0:
            return BuildOutcome(
                install_result.returncode,
                monotonic() - started_at,
                pdf_snapshot(layout.pdf_path) != pdf_before,
                failure_kind="install_failed",
                missing_files=tuple(missing_files),
                unmapped_files=tuple(last_unmapped_files),
                primary_error=primary_latex_error(
                    layout.log_path, tex_file, missing_files
                ),
                layout=layout,
            )
        result = run_tinytex_compile(
            engine,
            latexmk_args,
            root,
            force=True,
            env=env,
            reporter=reporter,
            cwd=Path.cwd(),
        )
    else:
        failure_kind = None

    elapsed = monotonic() - started_at
    pdf_changed = pdf_snapshot(layout.pdf_path) != pdf_before
    if result.returncode == 0:
        return BuildOutcome(0, elapsed, pdf_changed, layout=layout)
    primary_error = primary_latex_error(layout.log_path, tex_file, last_missing_files)
    return BuildOutcome(
        result.returncode,
        elapsed,
        pdf_changed,
        failure_kind=failure_kind,
        missing_files=tuple(last_missing_files),
        unmapped_files=tuple(last_unmapped_files),
        primary_error=primary_error,
        layout=layout,
    )


def report_failure(
    outcome: BuildOutcome, tex_file: str, auto_install: bool, reporter: Reporter
) -> None:
    layout = outcome.layout or default_build_layout(tex_file)
    error = outcome.primary_error
    if error is not None:
        location = ""
        if error.file and error.line:
            location = f" at {error.file}:{error.line}"
        reporter.error(f"Build failed: {error.message}{location}")
    elif outcome.failure_kind == "install_failed":
        reporter.error("Build failed: TeX Live package installation failed.")
    else:
        reporter.error("Build failed: no primary LaTeX error could be identified.")

    if outcome.failure_kind == "disabled" and not auto_install:
        reporter.error("Automatic package installation is disabled by --no-install.")
    elif outcome.failure_kind == "install_failed" and error is not None:
        reporter.error("TeX Live package installation failed.")
    elif outcome.failure_kind == "unmapped":
        reporter.error(
            f"Could not map missing TeX files to packages: {', '.join(outcome.unmapped_files)}"
        )
    elif outcome.failure_kind == "ceiling":
        reporter.error(
            f"Automatic package installation stopped after {MAX_INSTALL_ROUNDS} rounds."
        )
    elif outcome.failure_kind == "unidentified":
        reporter.error("No missing TeX package could be identified.")
    if layout.log_path.is_file():
        reporter.error(f"See {layout.display_log} for complete diagnostics.")
    if outcome.pdf_changed:
        reporter.error(f"{layout.display_pdf} may be incomplete.")


def report_build_result(
    outcome: BuildOutcome,
    tex_file: str,
    clean: bool,
    verbose: bool,
    auto_install: bool,
    reporter: Reporter,
) -> int:
    layout = outcome.layout or default_build_layout(tex_file)
    if outcome.returncode != 0:
        report_failure(outcome, tex_file, auto_install, reporter)
        return outcome.returncode
    if not verbose:
        for warning in document_warnings(layout.log_path):
            reporter.warning(warning)
    elapsed = format_elapsed(outcome.elapsed_seconds)
    if outcome.pdf_changed:
        reporter.status(f"Built {layout.display_pdf} in {elapsed}")
        if not clean:
            reporter.status(
                "Build files retained for faster rebuilds; use --clean to remove them."
            )
    else:
        reporter.status(f"{layout.display_pdf} is up to date ({elapsed})")
    if clean:
        cleanup_auxiliary_files(tex_file, layout)
        reporter.status("Removed auxiliary build files.")
    return 0


WATCH_SUFFIXES = {
    ".asy",
    ".bbx",
    ".bib",
    ".bst",
    ".cbx",
    ".cfg",
    ".cls",
    ".def",
    ".eps",
    ".jpeg",
    ".jpg",
    ".lua",
    ".ltx",
    ".mp",
    ".pdf",
    ".png",
    ".py",
    ".sty",
    ".svg",
    ".tex",
}
WATCH_IGNORED_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__"}


def fls_inputs(layout: BuildLayout, project_root: Path) -> set[Path]:
    fls_path = layout.aux_dir / f"{layout.jobname}.fls"
    if not fls_path.is_file():
        return set()
    inputs: set[Path] = set()
    for line in fls_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("INPUT "):
            continue
        path = Path(line.removeprefix("INPUT "))
        if not path.is_absolute():
            path = layout.source.parent / path
        path = path.resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            continue
        if path.is_file():
            inputs.add(path)
    return inputs


def watch_snapshot(
    project_root: Path, layout: BuildLayout
) -> dict[Path, tuple[int, int]]:
    paths = fls_inputs(layout, project_root)
    for directory, names, file_names in os.walk(project_root):
        names[:] = [name for name in names if name not in WATCH_IGNORED_DIRECTORIES]
        root = Path(directory)
        for name in file_names:
            path = root / name
            if (
                name in {"latexmkrc", ".latexmkrc"}
                or path.suffix.lower() in WATCH_SUFFIXES
            ):
                paths.add(path.resolve())
    paths.discard(layout.pdf_path.resolve())
    snapshot: dict[Path, tuple[int, int]] = {}
    for path in paths:
        try:
            stat_result = path.stat()
        except FileNotFoundError:
            continue
        snapshot[path] = (stat_result.st_mtime_ns, stat_result.st_size)
    return snapshot


def run_document_build(
    config: CliConfig, tex_file: str, reporter: Reporter
) -> BuildOutcome:
    engine = resolve_engine(config.engine, tex_file, reporter)
    check_bibliography(tex_file, config.bib_files, reporter)
    return run_tinytex_backend(
        engine,
        config.auto_install,
        config.verbose,
        tex_file,
        config.latexmk_args,
        monotonic(),
        reporter,
    )


def watch_document(config: CliConfig, tex_file: str, reporter: Reporter) -> int:
    project_root = Path.cwd().resolve()
    source = Path(tex_file).resolve()
    try:
        source.relative_to(project_root)
    except ValueError:
        project_root = source.parent

    outcome = run_document_build(config, tex_file, reporter)
    result = report_build_result(
        outcome, tex_file, False, config.verbose, config.auto_install, reporter
    )
    if outcome.failure_kind == "install_failed":
        return result
    layout = outcome.layout or default_build_layout(tex_file)
    baseline = watch_snapshot(project_root, layout)
    reporter.status(f"Watching {tex_file} for changes; press Ctrl-C to stop.")
    try:
        while True:
            sleep(0.5)
            current = watch_snapshot(project_root, layout)
            if current == baseline:
                continue
            sleep(0.25)
            outcome = run_document_build(config, tex_file, reporter)
            result = report_build_result(
                outcome, tex_file, False, config.verbose, config.auto_install, reporter
            )
            if outcome.failure_kind == "install_failed":
                return result
            layout = outcome.layout or layout
            baseline = watch_snapshot(project_root, layout)
    except KeyboardInterrupt:
        reporter.status("Stopped watching.")
        return 130


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _source_cache.clear()
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
