import os
import re
from pathlib import Path

from .model import ENGINE_ARGS, SourceRequirements, TexMiniError
from .reporting import Reporter


MISSING_FILE_EXTENSIONS = "sty|cls|bst|bbx|cbx|def|fd|map|tfm|pfb|otf|ttf|enc|cfg"

_missing_file_patterns: list[re.Pattern[str]] | None = None
_biblatex_style_patterns: tuple[re.Pattern[str], re.Pattern[str]] | None = None
_source_patterns: tuple[re.Pattern[str], ...] | None = None
_source_cache: dict[str, tuple[int, int, str]] = {}


def clear_source_cache() -> None:
    _source_cache.clear()


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


def missing_file_patterns() -> list[re.Pattern[str]]:
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


def biblatex_style_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
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


def source_patterns() -> tuple[re.Pattern[str], ...]:
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


def tex_log_requirements(log_path: Path) -> tuple[list[str], list[str]]:
    if not log_path.is_file():
        return [], []

    found: list[str] = []
    seen: set[str] = set()
    source = log_path.read_text(encoding="utf-8", errors="replace")

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
