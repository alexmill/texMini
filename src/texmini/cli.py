import os
import sys

from texmini import __version__


ENGINE_ARGS = {
    "pdflatex": ["-pdf"],
    "lualatex": ["-lualatex"],
    "xelatex": ["-xelatex"],
}

AUX_EXTENSIONS = [
    "aux",
    "bbl",
    "bcf",
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

TINYTEX_RELEASE_API = "https://api.github.com/repos/rstudio/tinytex-releases/releases/latest"
DEFAULT_TINYTEX_BUNDLE = "TinyTeX-0"
TINYTEX_BOOTSTRAP_PACKAGES = ["latex-bin", "latexmk", "metafont", "mfware"]
TINYTEX_ENGINE_PACKAGES = {"xelatex": "xetex"}
AUTO_INSTALL_RETRIES = 5
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


_missing_file_patterns = None
_biblatex_style_patterns = None
_source_patterns = None
_source_cache: dict[str, tuple[int, int, str]] = {}


def run_command(args: list[str], **kwargs: object):
    import subprocess

    return subprocess.run(args, **kwargs)


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

Compile a LaTeX document, detect bibliography files, and clean auxiliary files after successful builds.

Options:
  --engine ENGINE   Select pdflatex, lualatex, or xelatex.
  --no-clean        Keep auxiliary files after a successful build.
  --no-install      Disable TinyTeX package autoinstall.
  --version         Print the texMini version.

All other arguments are passed through to latexmk."""
    )


def parse_args(argv: list[str]) -> tuple[str, bool, bool, list[str], list[str], str | None]:
    engine = os.environ.get("TEXMINI_ENGINE", "pdflatex")
    auto_clean = os.environ.get("TEXMINI_AUTO_CLEAN", "true").lower() != "false"
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
        if arg == "--no-clean":
            auto_clean = False
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

    return engine, auto_clean, auto_install, latexmk_args, bib_files, tex_file


def executable_on_path(command: str) -> str | None:
    for directory in os.environ.get("PATH", os.defpath).split(os.pathsep):
        candidate = os.path.join(directory or ".", command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def detect_tex_file(latexmk_args: list[str], tex_file: str | None) -> str:
    if tex_file is not None:
        return tex_file

    tex_files = sorted(entry.name for entry in os.scandir(os.getcwd()) if entry.is_file() and entry.name.endswith(".tex"))
    if len(tex_files) == 1:
        print(f"Auto-detected LaTeX file: {tex_files[0]}")
        latexmk_args.append(tex_files[0])
        return tex_files[0]

    print("Error: No .tex file specified and unable to auto-detect.")
    if not tex_files:
        print("No .tex files found in current directory.")
    else:
        print(f"Multiple .tex files found: {' '.join(tex_files)}")
        print("Please specify which file to compile.")
    raise SystemExit(1)


def check_bibliography(tex_file: str, bib_files: list[str]) -> None:
    tex_path = os.fspath(tex_file)
    if not os.path.isfile(tex_path):
        return

    source = read_source_file(tex_path)
    if not source_uses_bibliography(source):
        return

    print(f"Detected bibliography usage in {tex_file}")
    if bib_files:
        print(f"Using explicitly specified bibliography files: {' '.join(bib_files)}")
        for bib_file in bib_files:
            if not os.path.isfile(bib_file):
                raise TexMiniError(f"Error: Specified bibliography file '{bib_file}' not found")
            if bib_file not in source:
                print(f"Warning: Bibliography file {bib_file} specified but not referenced in {tex_file}")
                print(f"You may need to add \\addbibresource{{{bib_file}}} to your document")
        return

    detected_bib_files = sorted(entry.name for entry in os.scandir(os.getcwd()) if entry.is_file() and entry.name.endswith(".bib"))
    if len(detected_bib_files) == 1:
        bib_file = detected_bib_files[0]
        print(f"Auto-detected bibliography file: {bib_file}")
        if bib_file not in source:
            print(f"Warning: Bibliography file {bib_file} found but not referenced in {tex_file}")
            print(f"You may need to add \\addbibresource{{{bib_file}}} to your document")
    elif not detected_bib_files:
        print(f"Warning: Bibliography commands found in {tex_file} but no .bib files found")
    else:
        print(f"Info: Multiple .bib files found: {' '.join(detected_bib_files)}")
        print("Make sure the correct ones are referenced in your document")
        print(f"Or specify explicitly: texmini {tex_file} file1.bib file2.bib")


def cleanup_auxiliary_files(tex_file: str) -> None:
    base, _ = os.path.splitext(os.fspath(tex_file))
    for extension in AUX_EXTENSIONS:
        try:
            os.unlink(f"{base}.{extension}")
        except FileNotFoundError:
            pass
    print("Build successful, all auxiliary files cleaned (kept: .tex, .bib, .pdf)")


def tinytex_root() -> "Path":
    from pathlib import Path

    return Path(os.environ.get("TEXMINI_TINYTEX_ROOT", Path.home() / ".texmini" / "TinyTeX"))


def package_map_path() -> "Path":
    from pathlib import Path

    return Path(os.environ.get("TEXMINI_PACKAGE_MAP", Path.home() / ".texmini" / "package-map.json"))


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


def latest_tinytex_asset() -> tuple[str, str]:
    import json
    import urllib.request

    bundle = tinytex_bundle()
    prefix = f"{bundle}-{tinytex_platform_key()}-"
    with urllib.request.urlopen(TINYTEX_RELEASE_API, timeout=30) as response:
        release = json.load(response)
    for asset in release["assets"]:
        name = asset["name"]
        if name.startswith(prefix) and name.endswith(".tar.xz"):
            return name, asset["browser_download_url"]
    raise TexMiniError(f"Error: No {bundle} TinyTeX archive found for this platform.")


def update_tinytex_manager(root: "Path") -> None:
    env = tinytex_env(root, "tlmgr")
    print("Updating the managed TinyTeX package manager")
    update_result = run_command(["tlmgr", "update", "--self"], env=env, check=False)
    if update_result.returncode != 0:
        raise TexMiniError("Error: TinyTeX package manager bootstrap failed.")


def bootstrap_tinytex(root: "Path") -> None:
    update_tinytex_manager(root)
    env = tinytex_env(root, "tlmgr")
    print(f"Installing TinyTeX bootstrap packages: {' '.join(TINYTEX_BOOTSTRAP_PACKAGES)}")
    install_result = run_command(["tlmgr", "install", *TINYTEX_BOOTSTRAP_PACKAGES], env=env, check=False)
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


def install_tinytex_archive(root: "Path") -> None:
    import tarfile
    import tempfile
    import urllib.request
    from pathlib import Path

    if executable_on_path("perl") is None:
        raise TexMiniError("Error: Perl is required to install and run TinyTeX. Install Perl and retry.")

    if (root / "bin").exists():
        if tinytex_bundle() == "TinyTeX-0":
            try:
                tinytex_bin_dir(root)
            except TexMiniError:
                bootstrap_tinytex(root)
        else:
            tinytex_bin_dir(root)
        print(f"TinyTeX already installed at {root}")
        return

    name, url = latest_tinytex_asset()
    root.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {name}")
    with tempfile.TemporaryDirectory(prefix=".texmini-extract-", dir=root.parent) as temporary_directory:
        extraction_root = Path(temporary_directory)
        with urllib.request.urlopen(url, timeout=60) as response:
            with tarfile.open(fileobj=response, mode="r|xz") as tar:
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
        bootstrap_tinytex(root)
    else:
        update_tinytex_manager(root)
    tinytex_bin_dir(root)
    print(f"TinyTeX installed at {root}")


def install_tinytex() -> int:
    try:
        install_tinytex_archive(tinytex_root())
        return 0
    except TexMiniError as error:
        print(error)
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


def missing_tex_files_from_log(log_path: "Path") -> list[str]:
    missing_files, _ = tex_log_requirements(log_path)
    return missing_files


def missing_tinytex_packages_from_log(log_path: "Path") -> list[str]:
    _, direct_packages = tex_log_requirements(log_path)
    return direct_packages


def report_missing_tex_files(tex_file: str) -> None:
    base, _ = os.path.splitext(os.fspath(tex_file))
    missing_files = missing_tex_files_from_log(f"{base}.log")
    if missing_files:
        print(f"Missing TeX files found: {', '.join(missing_files)}")


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
) -> list[str]:
    env = tinytex_env(root) if env is None else env
    source_files = tex_source_package_files(tex_file) if source_files is None else source_files
    if not source_files:
        return []

    import subprocess

    result = run_command(
        ["kpsewhich", *source_files],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    found_files = {os.path.basename(line) for line in result.stdout.splitlines() if line}
    return [file_name for file_name in source_files if file_name not in found_files]


def tinytex_packages_from_source(tex_file: str) -> list[str]:
    _, direct_packages = tex_source_requirements(tex_file)
    return direct_packages


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
) -> "subprocess.CompletedProcess[str]":
    env = tinytex_env(root) if env is None else env
    return run_command(["tlmgr", "install", *packages], env=env, check=False)


def ensure_tinytex_engine(root: "Path", engine: str, env: dict[str, str]) -> None:
    package = TINYTEX_ENGINE_PACKAGES.get(engine)
    if package is None or executable_on_path_with_env(engine, env):
        return

    print(f"Installing TeX Live engine package: {package}")
    result = install_tinytex_packages(root, [package], env)
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
) -> "subprocess.CompletedProcess[str]":
    env = tinytex_env(root) if env is None else env
    force_args = ["-g"] if force else []
    return run_command(
        ["latexmk", *ENGINE_ARGS[engine], "-interaction=nonstopmode", *force_args, *latexmk_args],
        env=env,
        check=False,
    )


def log_autoinstall_resolution(missing_files: list[str], resolved: dict[str, str], packages: list[str], retry: int) -> None:
    print(f"TinyTeX autoinstall retry {retry}/{AUTO_INSTALL_RETRIES}")
    if missing_files:
        print(f"Missing TeX files found: {', '.join(missing_files)}")
    else:
        print("Missing TeX files found: none")
    if resolved:
        pairs = [f"{file_name} -> {package}" for file_name, package in resolved.items()]
        print(f"Resolved TeX packages: {', '.join(pairs)}")
    else:
        print("Resolved TeX packages: none")
    if packages:
        print(f"Installing TeX Live packages: {' '.join(packages)}")
    else:
        print("Installing TeX Live packages: none")


def run_tinytex_backend(
    engine: str,
    auto_clean: bool,
    auto_install: bool,
    tex_file: str,
    latexmk_args: list[str],
) -> "subprocess.CompletedProcess[str]":
    root = tinytex_root()
    install_tinytex_archive(root)

    env = tinytex_env(root)
    ensure_tinytex_engine(root, engine, env)
    result = run_tinytex_compile(engine, latexmk_args, root, env=env)
    attempted_packages: set[str] = set()
    base, _ = os.path.splitext(os.fspath(tex_file))
    log_path = f"{base}.log"
    source_files: list[str] | None = None
    source_direct_packages: list[str] = []
    retry = 0

    while result.returncode != 0 and auto_install and retry < AUTO_INSTALL_RETRIES:
        if source_files is None:
            source_files, source_direct_packages = tex_source_requirements(tex_file)
        missing_files, log_direct_packages = tex_log_requirements(log_path)
        for missing_file in missing_tinytex_source_files(root, tex_file, env, source_files):
            if missing_file not in missing_files:
                missing_files.append(missing_file)
        direct_packages = [*log_direct_packages, *source_direct_packages]

        if not missing_files and not direct_packages:
            print("TinyTeX autoinstall: no missing TeX files or packages found in the log or source.")
            break

        resolved = resolve_tinytex_packages(root, missing_files, env=env) if missing_files else {}
        packages = sorted(
            {
                package
                for package in [*resolved.values(), *direct_packages]
                if package not in attempted_packages
            }
        )
        retry += 1
        log_autoinstall_resolution(missing_files, resolved, packages, retry)
        if not packages:
            break

        install_result = install_tinytex_packages(root, packages, env)
        attempted_packages.update(packages)
        if install_result.returncode != 0:
            print("TinyTeX autoinstall: package install failed.")
            return install_result

        print(f"TinyTeX autoinstall: retrying build ({retry}/{AUTO_INSTALL_RETRIES}).")
        result = run_tinytex_compile(engine, latexmk_args, root, force=True, env=env)

    if result.returncode == 0 and auto_clean:
        cleanup_auxiliary_files(tex_file)
    return result


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _source_cache.clear()
    if "--help" in argv or "-h" in argv:
        print_help()
        return 0
    if "--version" in argv:
        print(__version__)
        return 0
    if argv == ["install-tinytex"]:
        return install_tinytex()

    try:
        engine, auto_clean, auto_install, latexmk_args, bib_files, tex_file = parse_args(argv)
        detected_tex_file = detect_tex_file(latexmk_args, tex_file)
        check_bibliography(detected_tex_file, bib_files)
        result = run_tinytex_backend(engine, auto_clean, auto_install, detected_tex_file, latexmk_args)
    except TexMiniError as error:
        print(error)
        return 1

    if result.returncode != 0:
        report_missing_tex_files(detected_tex_file)
        print("Build failed, keeping auxiliary files for debugging")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
