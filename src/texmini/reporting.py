import os
import re
import subprocess
import sys
from pathlib import Path

from ._trace import span
from .model import (
    MAX_INSTALL_ROUNDS,
    BuildLayout,
    BuildOutcome,
    FailureKind,
    PrimaryError,
)


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
            self.warning(
                "This build is continuing without signature verification. "
                f"{gpg_install_guidance().rstrip('.')} so future package "
                "installations can be verified."
            )
            self._gpg_warning_printed = True


def gpg_install_guidance() -> str:
    if sys.platform == "darwin":
        return "Install GnuPG with `brew install gnupg`."
    if sys.platform == "win32":
        return "Install GnuPG for Windows."
    return "Install your operating system's GnuPG package."


def _run_command(
    args: list[str], reporter: Reporter | None = None, **kwargs: object
) -> subprocess.CompletedProcess[str]:
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


def run_command(
    args: list[str], reporter: Reporter | None = None, **kwargs: object
) -> subprocess.CompletedProcess[str]:
    with span(
        "subprocess",
        command=Path(args[0]).name,
        argument_count=len(args),
    ) as trace:
        result = _run_command(args, reporter, **kwargs)
        trace["returncode"] = result.returncode
        return result


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remaining = divmod(round(seconds), 60)
    return f"{minutes}m {remaining:02d}s"


def _read_log(log_path: Path) -> str | None:
    try:
        if not log_path.is_file():
            return None
        return log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # A log may disappear between latexmk exiting and diagnostics being
        # collected (especially in watch mode).  Reporting must not mask the
        # underlying subprocess status with a second filesystem failure.
        return None


def _log_exists(log_path: Path) -> bool:
    try:
        return log_path.is_file()
    except OSError:
        return False


def _clean_reported_tex_file(value: str) -> str:
    value = value.strip()
    if value[:1] in {"`", "'", '"'}:
        value = value[1:]
    if value[-1:] in {"`", "'", '"'}:
        value = value[:-1]
    return value


def _display_tex_file(reported_file: str, tex_file: str) -> str:
    """Express a TeX-reported path relative to the user's invocation.

    latexmk's ``-cd`` makes TeX report paths relative to the main source's
    directory.  Prefix that directory back onto relative diagnostics so an
    included-file location remains actionable from texMini's original cwd.
    """

    reported_file = _clean_reported_tex_file(reported_file)
    if not reported_file:
        return tex_file
    if Path(reported_file).is_absolute() or re.match(
        r"^(?:[A-Za-z]:[\\/]|\\\\)", reported_file
    ):
        return os.path.normpath(reported_file)

    reported = os.path.normpath(reported_file)
    requested = os.path.normpath(tex_file)
    requested_directory = os.path.dirname(requested)
    if reported == os.path.basename(requested):
        return requested
    if not requested_directory:
        return reported
    if reported == requested_directory or reported.startswith(
        requested_directory + os.sep
    ):
        return reported
    return os.path.normpath(os.path.join(requested_directory, reported))


def _tex_file_at(source: str, offset: int) -> str | None:
    """Return the active ``.tex`` input at *offset* when the log records it.

    TeX's transcript surrounds opened inputs with parentheses.  This small
    stack is only a fallback for classic ``! ...``/``l.N`` diagnostics; an
    explicit ``file.tex:N:`` diagnostic always wins.
    """

    inputs: list[str | None] = []
    tokens = re.compile(
        r'\((?P<file>"[^"\r\n]*"|[^()\s]*)|(?P<close>\))'
    ).finditer(source, 0, min(offset, len(source)))
    for token in tokens:
        if token.group("close"):
            if inputs:
                inputs.pop()
            continue
        file_name = _clean_reported_tex_file(token.group("file"))
        inputs.append(file_name if file_name.lower().endswith(".tex") else None)
    return next((file_name for file_name in reversed(inputs) if file_name), None)


def primary_latex_error(
    log_path: Path, tex_file: str, missing_files: list[str]
) -> PrimaryError | None:
    if missing_files:
        missing_file = missing_files[0]
        if missing_file.lower().endswith(".tex"):
            missing_file = _display_tex_file(missing_file, tex_file)
        return PrimaryError(f"{missing_file} is missing")
    source = _read_log(log_path)
    if source is None:
        return None
    missing_input = re.search(
        r"(?:LaTeX Error:\s+File|I (?:can't|cannot) find file)\s+"
        r"(?:[`'\"]([^`'\"\r\n]+\.tex)[`'\"]|([^`'\"\s]+\.tex))"
        r"\s*(?:not found)?",
        source,
        re.IGNORECASE,
    )
    if missing_input:
        reported_file = missing_input.group(1) or missing_input.group(2)
        return PrimaryError(
            f"{_display_tex_file(reported_file, tex_file)} is missing"
        )
    file_line = re.search(
        r"^[ \t]*(.+?\.tex)[`'\"]?:(\d+):[ \t]*(?:!\s*)?(.+)$",
        source,
        re.IGNORECASE | re.MULTILINE,
    )
    if file_line:
        return PrimaryError(
            file_line.group(3).strip().rstrip("."),
            _display_tex_file(file_line.group(1), tex_file),
            int(file_line.group(2)),
        )
    lines = source.splitlines(keepends=True)
    source_offset = 0
    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r\n")
        if not line.startswith("! "):
            source_offset += len(raw_line)
            continue
        message = line[2:].strip().rstrip(".")
        for raw_context in lines[index + 1 : index + 8]:
            context = raw_context.rstrip("\r\n")
            line_match = re.match(r"l\.(\d+)\s", context)
            if line_match:
                reported_file = _tex_file_at(source, source_offset) or tex_file
                return PrimaryError(
                    message,
                    _display_tex_file(reported_file, tex_file),
                    int(line_match.group(1)),
                )
        return PrimaryError(message)
    return None


def document_warnings(log_path: Path) -> list[str]:
    source = _read_log(log_path)
    if source is None:
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
    for line in source.splitlines():
        stripped = line.strip()
        if (
            stripped
            and any(pattern.search(stripped) for pattern in patterns)
            and stripped not in warnings
        ):
            warnings.append(stripped)
    return warnings


def incomplete_document_warnings(warnings: list[str]) -> list[str]:
    patterns = (
        re.compile(r"Missing character:", re.IGNORECASE),
        re.compile(
            r"undefined (?:citation|reference|citations|references)", re.IGNORECASE
        ),
        re.compile(
            r"(?:citation|reference|citations|references).*\bundefined\b",
            re.IGNORECASE,
        ),
    )
    return [
        warning
        for warning in warnings
        if any(pattern.search(warning) for pattern in patterns)
    ]


def show_resolution_mappings(resolved: dict[str, str], reporter: Reporter) -> None:
    if not reporter.verbose:
        return
    for file_name, package in resolved.items():
        reporter.status(f"{file_name} -> {package}")


def _is_project_file_reference(file_name: str) -> bool:
    normalized = file_name.replace("\\", "/")
    return (
        normalized.lower().endswith(".tex")
        or normalized.startswith(("./", "../", "/"))
        or "/" in normalized
        or bool(re.match(r"^[A-Za-z]:/", normalized))
    )


def report_failure(
    outcome: BuildOutcome, tex_file: str, auto_install: bool, reporter: Reporter
) -> None:
    layout = outcome.layout or BuildLayout.beside_source(tex_file)
    has_log = _log_exists(layout.log_path)
    error = outcome.primary_error
    if error is not None:
        location = ""
        if error.file and error.line:
            location = f" at {error.file}:{error.line}"
        parsed_error = (
            primary_latex_error(
                layout.log_path, tex_file, list(outcome.missing_files)
            )
            if has_log
            else None
        )
        attribution = "TeX reported: " if parsed_error == error else ""
        reporter.error(f"Build failed: {attribution}{error.message}{location}")
    elif outcome.failure_kind == FailureKind.INSTALL_FAILED:
        reporter.error("Build failed: TeX Live package installation failed.")
    else:
        reporter.error(
            "Build failed: TeX or latexmk failed, but no primary TeX error "
            "could be identified."
        )

    ownership_candidates = outcome.unmapped_files or outcome.missing_files
    if outcome.project_files is None:
        # Preserve classification for callers constructing legacy outcomes.
        project_files = [
            file_name
            for file_name in ownership_candidates
            if _is_project_file_reference(file_name)
        ]
    else:
        known_project_files = set(outcome.project_files)
        project_files = [
            file_name
            for file_name in ownership_candidates
            if file_name in known_project_files
        ]
    if outcome.failure_kind == FailureKind.DISABLED and not auto_install:
        if project_files:
            reporter.error(
                "Missing project files are not installed automatically: "
                f"{', '.join(project_files)}"
            )
        package_files = [
            file_name
            for file_name in outcome.missing_files
            if file_name not in project_files
        ]
        if package_files or not outcome.missing_files:
            reporter.error(
                "Automatic package installation is disabled by --no-install."
            )
    elif outcome.failure_kind == FailureKind.INSTALL_FAILED and error is not None:
        reporter.error("TeX Live package installation failed.")
    elif outcome.failure_kind == FailureKind.UNMAPPED:
        package_files = [
            file_name
            for file_name in outcome.unmapped_files
            if file_name not in project_files
        ]
        if project_files:
            reporter.error(
                "Missing project files are not installed automatically: "
                f"{', '.join(project_files)}"
            )
        if package_files:
            reporter.error(
                "Could not map missing TeX files to packages: "
                f"{', '.join(package_files)}"
            )
    elif outcome.failure_kind == FailureKind.CEILING:
        reporter.error(
            f"Automatic package installation stopped after {MAX_INSTALL_ROUNDS} rounds."
        )
    elif outcome.failure_kind == FailureKind.UNIDENTIFIED:
        reporter.error("No missing TeX package could be identified.")
    if has_log:
        reporter.error(f"See {layout.display_log} for complete diagnostics.")
    if outcome.pdf_changed:
        reporter.error(f"{layout.display_pdf} may be incomplete.")
    if not reporter.verbose:
        reporter.error("Run with --verbose to show complete tool output.")
