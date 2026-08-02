import os
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
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
    "aux",
    "bbl",
    "bcf",
    "bcf-SAVE-ERROR",
    "blg",
    "fls",
    "fdb_latexmk",
    "log",
    "nav",
    "out",
    "snm",
    "toc",
    "vrb",
    "run.xml",
]
FIXED_AUXILIARY_FILES = ["missfont.log"]

TINYTEX_RELEASE_API = "https://api.github.com/repos/rstudio/tinytex-releases/releases/latest"
DEFAULT_TINYTEX_BUNDLE = "TinyTeX-0"
TINYTEX_BOOTSTRAP_PACKAGES = ["latex-bin", "latexmk", "metafont", "mfware"]
TINYTEX_ENGINE_PACKAGES = {"xelatex": "xetex"}
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
    "memoir.cls": "memoir",
    "numeric.cbx": "biblatex",
    "pgf.sty": "pgf",
    "plainnat.bst": "natbib",
    "tikz.sty": "pgf",
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


@dataclass
class BuildOutcome:
    returncode: int
    elapsed_seconds: float
    pdf_changed: bool
    failure_kind: str | None = None
    missing_files: tuple[str, ...] = ()
    unmapped_files: tuple[str, ...] = ()
    primary_error: PrimaryError | None = None


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
            self.warning("Warning: TeX Live could not verify repository signatures because GPG is unavailable.")
            self.warning("Use --verbose for details.")
            self._gpg_warning_printed = True


_missing_file_patterns = None
_biblatex_style_patterns = None
_source_patterns = None
_source_cache: dict[str, tuple[int, int, str]] = {}


def run_command(args: list[str], reporter: Reporter | None = None, **kwargs: object):
    import subprocess

    if reporter is None:
        return subprocess.run(args, **kwargs)

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
        return subprocess.CompletedProcess(args, process.wait(), "".join(output_parts), None)

    result = subprocess.run(args, check=False, **options)
    reporter.observe_output(result.stdout or "")
    return result


def read_source_file(path: str) -> str:
    cache_key = os.path.abspath(os.fspath(path))
    stat_result = os.stat(path)
    cached = _source_cache.get(cache_key)
    if cached is None or cached[0] != stat_result.st_mtime_ns or cached[1] != stat_result.st_size:
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        _source_cache[cache_key] = (stat_result.st_mtime_ns, stat_result.st_size, source)
        return source
    return cached[2]


def missing_file_patterns():
    import re

    global _missing_file_patterns
    if _missing_file_patterns is None:
        _missing_file_patterns = [
            re.compile(rf"File\s+[`'\"]([^`'\"]+\.({MISSING_FILE_EXTENSIONS}))['\"]\s+not found", re.IGNORECASE),
            re.compile(
                rf"I\s+(?:can't|cannot|couldn't|could not)\s+find\s+file\s+[`'\"]?([^`'\"\s]+\.({MISSING_FILE_EXTENSIONS}))",
                re.IGNORECASE,
            ),
            re.compile(r"I couldn't open style file\s+([^`'\"\s]+\.bst)\b", re.IGNORECASE),
            re.compile(r"mktextfm\s+([A-Za-z0-9_.-]+)"),
            re.compile(r"Font .*=([A-Za-z0-9_.-]+).*Metric \(TFM\) file not found", re.IGNORECASE),
            re.compile(r"pdfTeX error:.*?\(file\s+([A-Za-z0-9_.-]+)\):\s+Font\b[^\n]*\bnot found", re.IGNORECASE),
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
            re.compile(r"^[A-Za-z0-9_.+-]+\.(sty|cls)$"),
        )
    return _source_patterns


def source_uses_bibliography(source: str) -> bool:
    if "\\bibliography{" in source or "\\addbibresource{" in source:
        return True
    if "biblatex" not in source or "\\usepackage" not in source:
        return False
    biblatex_package_pattern, _, _, _ = source_patterns()
    return bool(biblatex_package_pattern.search(source))


def print_help() -> None:
    print(
        """Usage: texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex] [OPTIONS] [document.tex] [refs.bib ...]

Compile a LaTeX document with a private TinyTeX runtime.

Options:
  --engine ENGINE   Select pdflatex, lualatex, or xelatex.
  --clean           Remove auxiliary files after a successful build.
  --verbose         Show complete TeX, latexmk, and package-manager output.
  --no-install      Do not install missing TeX Live packages.
  --version         Print the texMini version.

All other arguments are passed through to latexmk."""
    )


def parse_args(argv: list[str]) -> tuple[str, bool, bool, bool, list[str], list[str], str | None]:
    engine = os.environ.get("TEXMINI_ENGINE", "pdflatex")
    clean = os.environ.get("TEXMINI_CLEAN", "false").lower() == "true"
    verbose = False
    auto_install = os.environ.get("TEXMINI_AUTO_INSTALL", "true").lower() != "false"
    latexmk_args: list[str] = []
    bib_files: list[str] = []
    tex_file: str | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--backend" or arg.startswith("--backend="):
            raise TexMiniError("Error: --backend is no longer supported; texMini always uses managed TinyTeX.")
        if arg == "--engine":
            if i + 1 >= len(argv):
                raise TexMiniError("Error: --engine requires pdflatex, lualatex, or xelatex.")
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
        if arg == "--verbose":
            verbose = True
            i += 1
            continue
        if arg == "--no-install":
            auto_install = False
            i += 1
            continue
        if arg == "-pvc":
            raise TexMiniError("Error: -pvc is not supported by managed TinyTeX.")
        if arg.endswith(".tex"):
            if tex_file is not None:
                raise TexMiniError(f"Error: Multiple .tex files specified: {tex_file} and {arg}")
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

    if engine not in ENGINE_ARGS:
        raise TexMiniError("Error: --engine must be pdflatex, lualatex, or xelatex.")

    return engine, clean, verbose, auto_install, latexmk_args, bib_files, tex_file


def executable_on_path(command: str) -> str | None:
    for directory in os.environ.get("PATH", os.defpath).split(os.pathsep):
        candidate = os.path.join(directory or ".", command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def detect_tex_file(latexmk_args: list[str], tex_file: str | None, reporter: Reporter | None = None) -> str:
    reporter = reporter or Reporter()
    if tex_file is not None:
        return tex_file

    tex_files = sorted(entry.name for entry in os.scandir(os.getcwd()) if entry.is_file() and entry.name.endswith(".tex"))
    if len(tex_files) == 1:
        reporter.status(f"Auto-detected LaTeX file: {tex_files[0]}")
        latexmk_args.append(tex_files[0])
        return tex_files[0]

    print("Error: No .tex file specified and unable to auto-detect.")
    if not tex_files:
        print("No .tex files found in current directory.")
    else:
        print(f"Multiple .tex files found: {' '.join(tex_files)}")
        print("Please specify which file to compile.")
    raise SystemExit(1)


def check_bibliography(tex_file: str, bib_files: list[str], reporter: Reporter | None = None) -> None:
    reporter = reporter or Reporter()
    tex_path = os.fspath(tex_file)
    if not os.path.isfile(tex_path):
        return

    source = read_source_file(tex_path)
    if not source_uses_bibliography(source):
        return

    if bib_files:
        for bib_file in bib_files:
            if not os.path.isfile(bib_file):
                raise TexMiniError(f"Error: Specified bibliography file '{bib_file}' not found")
            if bib_file not in source:
                reporter.warning(f"Warning: Bibliography file {bib_file} is not referenced in {tex_file}.")
                reporter.warning(f"You may need to add \\addbibresource{{{bib_file}}} to your document.")
        return

    detected_bib_files = sorted(entry.name for entry in os.scandir(os.getcwd()) if entry.is_file() and entry.name.endswith(".bib"))
    if len(detected_bib_files) == 1:
        bib_file = detected_bib_files[0]
        if bib_file not in source:
            reporter.warning(f"Warning: Bibliography file {bib_file} is not referenced in {tex_file}.")
            reporter.warning(f"You may need to add \\addbibresource{{{bib_file}}} to your document.")
    elif not detected_bib_files:
        reporter.warning(f"Warning: Bibliography commands were found in {tex_file}, but no .bib files were found.")
    else:
        reporter.warning(f"Warning: Multiple bibliography files found: {' '.join(detected_bib_files)}")


def cleanup_auxiliary_files(tex_file: str) -> None:
    base, _ = os.path.splitext(os.fspath(tex_file))
    for extension in AUX_EXTENSIONS:
        try:
            os.unlink(f"{base}.{extension}")
        except FileNotFoundError:
            pass
    for path in FIXED_AUXILIARY_FILES:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def tinytex_root() -> "Path":
    return Path(os.environ.get("TEXMINI_TINYTEX_ROOT", Path.home() / ".texmini" / "TinyTeX"))


def package_map_path() -> "Path":
    return Path(os.environ.get("TEXMINI_PACKAGE_MAP", Path.home() / ".texmini" / "package-map.json"))


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
    raise TexMiniError(f"Error: TinyTeX does not provide {executable} at {root}. Run: texmini install-tinytex")


def tinytex_env(root: "Path", executable: str = "latexmk") -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = tinytex_bin_dir(root, executable)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
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
    raise TexMiniError("Error: The Python TinyTeX installer currently supports macOS and Linux.")


def latest_tinytex_asset() -> tuple[str, str, str | None]:
    import json
    import urllib.request

    bundle = tinytex_bundle()
    prefix = f"{bundle}-{tinytex_platform_key()}-"
    request = urllib.request.Request(
        TINYTEX_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"texmini/{__version__}"},
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
    update_result = run_command(["tlmgr", "update", "--self"], reporter=reporter, env=env, check=False)
    if update_result.returncode != 0:
        raise TexMiniError("Error: TinyTeX package manager bootstrap failed.")


def bootstrap_tinytex(root: "Path", reporter: Reporter) -> None:
    update_tinytex_manager(root, reporter)
    env = tinytex_env(root, "tlmgr")
    reporter.status("Installing the LaTeX compiler...")
    install_result = run_command(
        ["tlmgr", "install", *TINYTEX_BOOTSTRAP_PACKAGES], reporter=reporter, env=env, check=False
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
        raise TexMiniError(f"Error: Unsupported entry in TinyTeX archive: {member.name}")
    if member.issym() or member.islnk():
        link_path = member.linkname.replace("\\", "/")
        target = (
            posixpath.normpath(posixpath.join(posixpath.dirname(normalized_path), link_path))
            if member.issym()
            else posixpath.normpath(link_path)
        )
        if posixpath.isabs(link_path) or not is_managed_path(target):
            raise TexMiniError(f"Error: Unsafe link in TinyTeX archive: {member.name} -> {member.linkname}")


def install_tinytex_archive(root: "Path", reporter: Reporter | None = None) -> None:
    import hashlib
    import shutil
    import tarfile
    import tempfile
    import urllib.request

    reporter = reporter or Reporter()

    if executable_on_path("perl") is None:
        raise TexMiniError("Error: Perl is required to install and run TinyTeX. Install Perl and retry.")

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
    reporter.status("This one-time setup requires a network connection and may take a minute.")
    name, url, digest = latest_tinytex_asset()
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".texmini-extract-", dir=root.parent) as temporary_directory:
        extraction_root = Path(temporary_directory)
        archive_path = extraction_root / name
        if reporter.verbose:
            reporter.status(f"Downloading {url}")
        with urllib.request.urlopen(url, timeout=60) as response:
            with archive_path.open("wb") as archive:
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
            (candidate for root_name in ("TinyTeX", ".TinyTeX") if (candidate := extraction_root / root_name).exists()),
            None,
        )
        if extracted_root is None:
            raise TexMiniError("Error: TinyTeX archive did not contain a TinyTeX runtime.")
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
    direct_packages = ["biber"] if "Package biblatex Warning:" in source and "Please (re)run Biber" in source else []
    return found, direct_packages


def tex_source_requirements(tex_file: str) -> tuple[list[str], list[str]]:
    tex_path = os.fspath(tex_file)
    if not os.path.isfile(tex_path):
        return [], []

    source = read_source_file(tex_path)
    found: list[str] = []
    seen: set[str] = set()
    biblatex_package_pattern, documentclass_pattern, package_pattern, package_file_pattern = source_patterns()

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
    direct_packages = ["biber"] if biblatex_package_pattern.search(source) else []
    return found, direct_packages


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
    source_files = tex_source_package_files(tex_file) if source_files is None else source_files
    if not source_files:
        return []

    import subprocess

    result = run_command(
        ["kpsewhich", *source_files],
        reporter=reporter,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    found_files = {os.path.basename(line) for line in result.stdout.splitlines() if line}
    return [file_name for file_name in source_files if file_name not in found_files]


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
        if not separator or not package_name or not all(char.isalnum() or char in "_.+-" for char in package_name):
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
        if len(stem) > 4 and stem[0] in {"e", "t"} and stem[1:4] == "crm" and stem[4:].isdigit():
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
    return run_command(["tlmgr", "install", *packages], reporter=reporter, env=env, check=False)


def ensure_tinytex_engine(root: "Path", engine: str, env: dict[str, str], reporter: Reporter) -> None:
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
) -> "subprocess.CompletedProcess[str]":
    env = tinytex_env(root) if env is None else env
    force_args = ["-g"] if force else []
    return run_command(
        ["latexmk", *ENGINE_ARGS[engine], "-interaction=nonstopmode", "-file-line-error", *force_args, *latexmk_args],
        reporter=reporter,
        env=env,
        check=False,
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


def primary_latex_error(log_path: Path, tex_file: str, missing_files: list[str]) -> PrimaryError | None:
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
            r"(?:LaTeX|Package \S+|Class \S+) Warning:.*(?:undefined|rerun|\(re\)run)", re.IGNORECASE
        ),
        re.compile(r"LaTeX Warning: There were undefined (?:references|citations)", re.IGNORECASE),
        re.compile(r"Missing character:", re.IGNORECASE),
        re.compile(r"Font Warning:.*(?:not available|substituted)", re.IGNORECASE),
    )
    warnings: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and any(pattern.search(stripped) for pattern in patterns) and stripped not in warnings:
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
    base, _ = os.path.splitext(os.fspath(tex_file))
    log_path = Path(f"{base}.log")
    pdf_path = Path(f"{base}.pdf")
    pdf_before = pdf_snapshot(pdf_path)

    install_tinytex_archive(root, reporter)
    env = tinytex_env(root)
    ensure_tinytex_engine(root, engine, env, reporter)
    source_files, source_direct_packages = tex_source_requirements(tex_file)
    source_direct_packages = [
        package for package in source_direct_packages if executable_on_path_with_env(package, env) is None
    ]
    attempted_packages: set[str] = set()
    install_rounds = 0

    if auto_install:
        source_missing = missing_tinytex_source_files(root, tex_file, env, source_files, reporter)
        source_resolved = (
            resolve_tinytex_packages(root, source_missing, env=env, reporter=reporter) if source_missing else {}
        )
        initial_packages = sorted(set(source_resolved.values()) | set(source_direct_packages))
        show_resolution_mappings(source_resolved, reporter)
        if initial_packages:
            reporter.status(f"Analyzing {tex_file}...")
            noun = "package" if len(initial_packages) == 1 else "packages"
            reporter.status(f"Installing {len(initial_packages)} {noun}: {', '.join(initial_packages)}")
            install_result = install_tinytex_packages(root, initial_packages, env, reporter)
            attempted_packages.update(initial_packages)
            install_rounds += 1
            if install_result.returncode != 0:
                return BuildOutcome(
                    install_result.returncode,
                    monotonic() - started_at,
                    pdf_snapshot(pdf_path) != pdf_before,
                    failure_kind="install_failed",
                )

    reporter.status(f"Compiling {tex_file}...")
    result = run_tinytex_compile(engine, latexmk_args, root, env=env, reporter=reporter)
    last_missing_files: list[str] = []
    last_unmapped_files: list[str] = []

    while result.returncode != 0:
        missing_files, log_direct_packages = tex_log_requirements(log_path)
        for missing_file in missing_tinytex_source_files(root, tex_file, env, source_files, reporter):
            if missing_file not in missing_files:
                missing_files.append(missing_file)
        direct_packages = [*log_direct_packages, *source_direct_packages]
        last_missing_files = missing_files

        if not auto_install:
            failure_kind = "disabled" if missing_files or direct_packages else "ordinary"
            break

        resolved = resolve_tinytex_packages(root, missing_files, env=env, reporter=reporter) if missing_files else {}
        show_resolution_mappings(resolved, reporter)
        last_unmapped_files = [file_name for file_name in missing_files if file_name not in resolved]
        packages = sorted(
            package
            for package in set(resolved.values()) | set(direct_packages)
            if package not in attempted_packages
        )
        if not packages:
            if last_unmapped_files:
                failure_kind = "unmapped"
            elif primary_latex_error(log_path, tex_file, missing_files):
                failure_kind = "ordinary"
            else:
                failure_kind = "unidentified"
            break
        if install_rounds >= MAX_INSTALL_ROUNDS:
            failure_kind = "ceiling"
            break

        noun = "package" if len(packages) == 1 else "packages"
        dependency = "dependency" if len(packages) == 1 else "dependencies"
        qualifier = f"required {noun}" if install_rounds == 0 else f"additional {dependency}"
        reporter.status(f"Installing {len(packages)} {qualifier}...")
        install_result = install_tinytex_packages(root, packages, env, reporter)
        attempted_packages.update(packages)
        install_rounds += 1
        if install_result.returncode != 0:
            return BuildOutcome(
                install_result.returncode,
                monotonic() - started_at,
                pdf_snapshot(pdf_path) != pdf_before,
                failure_kind="install_failed",
                missing_files=tuple(missing_files),
                unmapped_files=tuple(last_unmapped_files),
                primary_error=primary_latex_error(log_path, tex_file, missing_files),
            )
        result = run_tinytex_compile(engine, latexmk_args, root, force=True, env=env, reporter=reporter)
    else:
        failure_kind = None

    elapsed = monotonic() - started_at
    pdf_changed = pdf_snapshot(pdf_path) != pdf_before
    if result.returncode == 0:
        return BuildOutcome(0, elapsed, pdf_changed)
    return BuildOutcome(
        result.returncode,
        elapsed,
        pdf_changed,
        failure_kind=failure_kind,
        missing_files=tuple(last_missing_files),
        unmapped_files=tuple(last_unmapped_files),
        primary_error=primary_latex_error(log_path, tex_file, last_missing_files),
    )


def report_failure(outcome: BuildOutcome, tex_file: str, auto_install: bool, reporter: Reporter) -> None:
    base, _ = os.path.splitext(os.fspath(tex_file))
    log_path = f"{base}.log"
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
        reporter.error(f"Could not map missing TeX files to packages: {', '.join(outcome.unmapped_files)}")
    elif outcome.failure_kind == "ceiling":
        reporter.error(f"Automatic package installation stopped after {MAX_INSTALL_ROUNDS} rounds.")
    elif outcome.failure_kind == "unidentified":
        reporter.error("No missing TeX package could be identified.")
    if Path(log_path).is_file():
        reporter.error(f"See {log_path} for complete diagnostics.")
    if outcome.pdf_changed:
        reporter.error(f"{base}.pdf may be incomplete.")


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
        engine, clean, verbose, auto_install, latexmk_args, bib_files, tex_file = parse_args(argv)
        reporter = Reporter(verbose)
        detected_tex_file = detect_tex_file(latexmk_args, tex_file, reporter)
        check_bibliography(detected_tex_file, bib_files, reporter)
        outcome = run_tinytex_backend(
            engine,
            auto_install,
            verbose,
            detected_tex_file,
            latexmk_args,
            started_at,
            reporter,
        )
    except TexMiniError as error:
        reporter.error(str(error))
        return 1

    base, _ = os.path.splitext(os.fspath(detected_tex_file))
    if outcome.returncode != 0:
        report_failure(outcome, detected_tex_file, auto_install, reporter)
        return outcome.returncode

    if not verbose:
        for warning in document_warnings(Path(f"{base}.log")):
            reporter.warning(warning)
    elapsed = format_elapsed(outcome.elapsed_seconds)
    if outcome.pdf_changed:
        reporter.status(f"Built {base}.pdf in {elapsed}")
        if not clean:
            reporter.status("Build files retained for faster rebuilds; use --clean to remove them.")
    else:
        reporter.status(f"{base}.pdf is up to date ({elapsed})")
    if clean:
        cleanup_auxiliary_files(detected_tex_file)
        reporter.status("Removed auxiliary build files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
