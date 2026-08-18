import os
from dataclasses import dataclass, field
from pathlib import Path
from stat import S_ISREG
from time import sleep

from ._trace import span
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

StatSignature = tuple[int, int, int, int, int]


def _stat_signature(path: Path | str) -> StatSignature | None:
    try:
        result = os.stat(path)
    except OSError:
        return None
    return (
        result.st_mtime_ns,
        result.st_ctime_ns,
        result.st_size,
        result.st_dev,
        result.st_ino,
    )


def _fls_input_paths(layout: BuildLayout, project_root: Path) -> set[Path]:
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
        inputs.add(path)
    return inputs


def fls_inputs(layout: BuildLayout, project_root: Path) -> set[Path]:
    return {path for path in _fls_input_paths(layout, project_root) if path.is_file()}


def _scan_project_paths(
    project_root: Path,
) -> tuple[dict[Path, StatSignature], set[Path], bool]:
    """Inventory watchable files and directories without redundant path stats.

    Directory signatures are captured before their entries are read. If an entry is
    added too late for the current scan, its parent signature will therefore differ
    on the next poll and force a refresh.
    """
    directories: dict[Path, StatSignature] = {}
    paths: set[Path] = set()
    pending = [project_root]
    complete = True
    while pending:
        directory = pending.pop()
        signature = _stat_signature(directory)
        if signature is None:
            complete = False
            continue
        directories[directory] = signature
        try:
            entries = os.scandir(directory)
        except OSError:
            complete = False
            continue
        with entries:
            for entry in entries:
                name = entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if name not in WATCH_IGNORED_DIRECTORIES:
                            pending.append(Path(entry.path))
                        continue
                    # os.walk does not descend into or treat directory symlinks as
                    # files. Match that behavior while still following file links.
                    if entry.is_symlink() and entry.is_dir():
                        continue
                except OSError:
                    complete = False
                    continue
                dot = name.rfind(".")
                suffix = name[dot:].lower() if dot > 0 else ""
                if (
                    name not in {"latexmkrc", ".latexmkrc"}
                    and suffix not in WATCH_SUFFIXES
                ):
                    continue
                path = Path(entry.path)
                if entry.is_symlink():
                    try:
                        path = path.resolve()
                    except (OSError, RuntimeError):
                        complete = False
                        continue
                paths.add(path)
    return directories, paths, complete


@dataclass
class _WatchState:
    key: tuple[Path, Path, Path] | None = None
    directories: dict[Path, StatSignature] = field(default_factory=dict)
    project_paths: set[Path] = field(default_factory=set)
    project_scan_complete: bool = False
    fls_signature: StatSignature | None = None
    fls_initialized: bool = False
    cached_fls_inputs: set[Path] = field(default_factory=set)

    def prepare(self, project_root: Path, layout: BuildLayout) -> tuple[Path, Path]:
        project_root = project_root.resolve()
        fls_path = (layout.aux_dir / f"{layout.jobname}.fls").resolve()
        pdf_path = layout.pdf_path.resolve()
        key = (project_root, fls_path, pdf_path)
        if key != self.key:
            self.key = key
            self.directories.clear()
            self.project_paths.clear()
            self.project_scan_complete = False
            self.fls_signature = None
            self.fls_initialized = False
            self.cached_fls_inputs.clear()
        return project_root, pdf_path

    def directories_changed(self) -> bool:
        if not self.project_scan_complete or not self.directories:
            return True
        return any(
            _stat_signature(directory) != signature
            for directory, signature in self.directories.items()
        )

    def refresh_project_paths(self, project_root: Path) -> None:
        (
            self.directories,
            self.project_paths,
            self.project_scan_complete,
        ) = _scan_project_paths(project_root)

    def refresh_fls_inputs(self, layout: BuildLayout, project_root: Path) -> None:
        fls_path = layout.aux_dir / f"{layout.jobname}.fls"
        signature = _stat_signature(fls_path)
        if not self.fls_initialized or signature != self.fls_signature:
            # Keep missing paths too: generated inputs can appear later without
            # latexmk rewriting the recorder file first.
            self.cached_fls_inputs = _fls_input_paths(layout, project_root)
            self.fls_signature = signature
            self.fls_initialized = True


def _watch_snapshot(
    project_root: Path, layout: BuildLayout, state: _WatchState | None = None
) -> dict[Path, tuple[int, int]]:
    state = state or _WatchState()
    project_root, pdf_path = state.prepare(project_root, layout)
    if state.directories_changed():
        state.refresh_project_paths(project_root)
    state.refresh_fls_inputs(layout, project_root)
    snapshot: dict[Path, tuple[int, int]] = {}
    for from_fls, paths in (
        (False, state.project_paths),
        (True, state.cached_fls_inputs),
    ):
        for path in paths:
            if path == pdf_path or path in snapshot:
                continue
            try:
                stat_result = os.stat(path)
            except OSError:
                continue
            if from_fls and not S_ISREG(stat_result.st_mode):
                continue
            snapshot[path] = (stat_result.st_mtime_ns, stat_result.st_size)
    return snapshot


def watch_snapshot(
    project_root: Path, layout: BuildLayout, state: _WatchState | None = None
) -> dict[Path, tuple[int, int]]:
    with span("watch_snapshot") as trace:
        snapshot = _watch_snapshot(project_root, layout, state)
        trace["tracked_file_count"] = len(snapshot)
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
    watch_state = _WatchState()
    baseline = watch_snapshot(project_root, layout, watch_state)
    reporter.status(f"Watching {tex_file} for changes; press Ctrl-C to stop.")
    try:
        while True:
            sleep(0.5)
            current = watch_snapshot(project_root, layout, watch_state)
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
            baseline = watch_snapshot(project_root, layout, watch_state)
    except KeyboardInterrupt:
        reporter.status("Stopped watching.")
        return 130
