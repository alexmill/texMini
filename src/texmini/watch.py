import os
from pathlib import Path
from time import sleep

from .build import default_build_layout, report_build_result, run_document_build
from .model import BuildLayout, CliConfig, FailureKind
from .reporting import Reporter


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
    if outcome.failure_kind == FailureKind.INSTALL_FAILED:
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
            if outcome.failure_kind == FailureKind.INSTALL_FAILED:
                return result
            layout = outcome.layout or layout
            baseline = watch_snapshot(project_root, layout)
    except KeyboardInterrupt:
        reporter.status("Stopped watching.")
        return 130
