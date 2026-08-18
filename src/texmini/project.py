import os
import re
from pathlib import Path

from ._trace import span
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
        search_from = 0
        while (index := line.find("%", search_from)) != -1:
            preceding_backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                preceding_backslashes += 1
                cursor -= 1
            if preceding_backslashes % 2:
                search_from = index + 1
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
            re.compile(
                rf"pdfTeX error:.*?\(file\s+([^()\s]+\.({MISSING_FILE_EXTENSIONS}))\):"
                r"\s+cannot open\b[^\n]*\bfor reading",
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
            re.compile(
                r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*\bbiblatex\b[^}]*\}"
            ),
            re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}"),
            re.compile(r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]+)\}"),
            re.compile(r"^[A-Za-z0-9_.+:/\\-]+\.(sty|cls|bst|bbx|cbx)$"),
        )
    return _source_patterns


def biblatex_source_styles(source: str) -> list[tuple[str, str]]:
    styles: list[tuple[str, str]] = []
    for options in re.findall(
        r"\\(?:usepackage|RequirePackage)\s*\[([^\]]*)\]\s*\{[^}]*\bbiblatex\b[^}]*\}",
        source,
    ):
        for kind, name in re.findall(
            r"(?:^|,)\s*(style|bibstyle|citestyle)\s*=\s*\{?([^,}\s]+)", options
        ):
            if kind != "citestyle":
                styles.append((name, "bbx"))
            if kind != "bibstyle":
                styles.append((name, "cbx"))
    return styles


def source_uses_bibliography(source: str) -> bool:
    source = strip_tex_comments(source)
    if "\\bibliography{" in source or "\\addbibresource{" in source:
        return True
    if "biblatex" not in source or "\\usepackage" not in source:
        return False
    biblatex_package_pattern, _, _, _ = source_patterns()
    return bool(biblatex_package_pattern.search(source))


def _project_source_inventory(tex_file: str) -> tuple[list[Path], list[Path]]:
    root = Path(tex_file).resolve()
    pending = [root]
    analyzed: list[Path] = []
    seen: set[Path] = set()
    local_dependencies: list[Path] = []
    local_seen: set[Path] = set()
    project_root = Path.cwd().resolve()
    try:
        root.relative_to(project_root)
    except ValueError:
        project_root = root.parent
    project_index: dict[str, list[Path]] | None = None
    include_pattern = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
    class_pattern = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}")
    package_pattern = re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]+)\}"
    )
    bibliography_style_pattern = re.compile(r"\\bibliographystyle\s*\{([^}]+)\}")

    def local_source(
        parent: Path, name: str, extension: str
    ) -> tuple[Path | None, list[Path]]:
        nonlocal project_index
        requested = name.strip()
        candidate = parent / requested
        if not candidate.suffix:
            candidate = candidate.with_suffix(extension)
        if candidate.is_file():
            resolved = candidate.resolve()
            return resolved, [resolved]

        normalized = requested.replace("\\", "/")
        if not Path(normalized).suffix:
            normalized = f"{normalized}{extension}"
        if normalized.startswith(("./", "../", "/")) or re.match(
            r"^[A-Za-z]:/", normalized
        ):
            return None, []
        if project_index is None:
            project_index = {}
            for directory, _, file_names in os.walk(project_root):
                directory_path = Path(directory)
                for file_name in file_names:
                    if Path(file_name).suffix.lower() not in {
                        ".tex",
                        ".sty",
                        ".cls",
                        ".bst",
                        ".bbx",
                        ".cbx",
                    }:
                        continue
                    project_index.setdefault(file_name, []).append(
                        directory_path / file_name
                    )
        matches = project_index.get(Path(normalized).name, [])
        if "/" in normalized:
            matches = [
                path
                for path in matches
                if (
                    (relative := path.relative_to(project_root).as_posix())
                    == normalized
                    or relative.endswith(f"/{normalized}")
                )
            ]
        resolved_matches = [path.resolve() for path in matches]
        selected = resolved_matches[0] if len(resolved_matches) == 1 else None
        return selected, resolved_matches

    def record_local_candidates(
        parent: Path,
        name: str,
        extension: str,
        local_candidates: list[Path],
        *,
        analyze: bool = True,
    ) -> None:
        selected, matches = local_source(parent, name, extension)
        for match in matches:
            if match not in local_seen:
                local_seen.add(match)
                local_dependencies.append(match)
        if analyze and selected is not None:
            local_candidates.append(selected)

    while pending:
        path = pending.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        analyzed.append(path)
        source = strip_tex_comments(read_source_file(os.fspath(path)))
        local_candidates: list[Path] = []
        for match in include_pattern.finditer(source):
            record_local_candidates(
                path.parent, match.group(1), ".tex", local_candidates
            )
        for match in class_pattern.finditer(source):
            record_local_candidates(
                path.parent, match.group(1), ".cls", local_candidates
            )
        for match in package_pattern.finditer(source):
            for package in match.group(1).split(","):
                record_local_candidates(
                    path.parent, package, ".sty", local_candidates
                )
        for match in bibliography_style_pattern.finditer(source):
            record_local_candidates(
                path.parent,
                match.group(1),
                ".bst",
                local_candidates,
                analyze=False,
            )
        for name, extension in biblatex_source_styles(source):
            record_local_candidates(
                path.parent, name, f".{extension}", local_candidates
            )
        pending.extend(local_candidates)
    return analyzed, [path for path in local_dependencies if path not in seen]


def _project_source_files(tex_file: str) -> list[Path]:
    analyzed, local_dependencies = _project_source_inventory(tex_file)
    return [*analyzed, *local_dependencies]


def project_source_files(tex_file: str) -> list[Path]:
    with span("project_source_discovery") as trace:
        discovered = _project_source_files(tex_file)
        trace["source_count"] = len(discovered)
        return discovered


def _analyze_source_requirements(tex_file: str) -> SourceRequirements:
    with span("project_source_discovery") as trace:
        analyzed_paths, local_dependencies = _project_source_inventory(tex_file)
        source_paths = [*analyzed_paths, *local_dependencies]
        trace["source_count"] = len(source_paths)
    source_texts = [
        strip_tex_comments(read_source_file(os.fspath(path))) for path in analyzed_paths
    ]
    source = "\n".join(source_texts)
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
    for name, extension in biblatex_source_styles(source):
        add_file(name, extension)

    tools: list[str] = []
    package_names = {
        file_name.removesuffix(".sty")
        for file_name in found
        if file_name.endswith(".sty")
    }
    biblatex_match = re.search(
        r"\\(?:usepackage|RequirePackage)(?:\[([^\]]*)\])?\{[^}]*\bbiblatex\b[^}]*\}",
        source,
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
    include_graphics_pattern = re.compile(
        r"\\includegraphics(?:\[[^\]]*\])?\s*\{([^}]+)\}"
    )
    for source_path, source_text in zip(analyzed_paths, source_texts):
        for match in include_graphics_pattern.finditer(source_text):
            figure = Path(match.group(1).strip())
            if figure.suffix.lower() == ".eps" or (
                not figure.suffix
                and (source_path.parent / figure).with_suffix(".eps").is_file()
            ):
                tools.append("repstopdf")
                break

    return SourceRequirements(
        tuple(found),
        tuple(dict.fromkeys(tools)),
        tuple(source_paths),
        uses_minted="minted" in package_names,
    )


def analyze_source_requirements(tex_file: str) -> SourceRequirements:
    with span("source_analysis") as trace:
        requirements = _analyze_source_requirements(tex_file)
        trace["source_count"] = len(requirements.sources)
        trace["required_file_count"] = len(requirements.files)
        trace["required_tool_count"] = len(requirements.tools)
        return requirements


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

    source_directory = Path(tex_path).parent
    missing_referenced = sorted(
        item if Path(item).suffix else f"{item}.bib"
        for item in referenced
        if not (
            source_directory
            / (item if Path(item).suffix else f"{item}.bib")
        ).is_file()
        and not any(
            os.path.isfile(bib_file) and is_referenced(bib_file)
            for bib_file in bib_files
        )
    )
    if missing_referenced:
        reporter.warning(
            "Warning: Bibliography files referenced by "
            f"{tex_file} were not found: {', '.join(missing_referenced)}"
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
        return

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
    elif len(detected_bib_files) > 1:
        reporter.warning(
            f"Warning: Multiple bibliography files found: {' '.join(detected_bib_files)}"
        )
    elif not missing_referenced:
        reporter.warning(
            f"Warning: Bibliography commands were found in {tex_file}, but no .bib files were found."
        )


def _tex_log_requirements(log_path: Path) -> tuple[list[str], list[str]]:
    try:
        source = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], []

    found: list[str] = []
    seen: set[str] = set()

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
    if re.search(
        r"font expansion\):\s*auto expansion is only possible with scalable fonts",
        source,
        re.IGNORECASE,
    ):
        direct_packages.append("cm-super")
    return found, direct_packages


def tex_log_requirements(log_path: Path) -> tuple[list[str], list[str]]:
    with span("log_requirement_parse") as trace:
        files, packages = _tex_log_requirements(log_path)
        trace["missing_file_count"] = len(files)
        trace["direct_package_count"] = len(packages)
        return files, packages
