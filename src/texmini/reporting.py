import re
import subprocess
import sys
from pathlib import Path

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
                "TeX Live continued without signature verification. "
                f"{gpg_install_guidance().rstrip('.')}; then rerun texMini."
            )
            self._gpg_warning_printed = True


def gpg_install_guidance() -> str:
    if sys.platform == "darwin":
        return "Install GnuPG with `brew install gnupg`."
    if sys.platform == "win32":
        return "Install GnuPG for Windows."
    return "Install your operating system's GnuPG package."


def run_command(
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


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remaining = divmod(round(seconds), 60)
    return f"{minutes}m {remaining:02d}s"


def primary_latex_error(
    log_path: Path, tex_file: str, missing_files: list[str]
) -> PrimaryError | None:
    if missing_files:
        return PrimaryError(f"{missing_files[0]} is missing")
    if not log_path.is_file():
        return None
    source = log_path.read_text(encoding="utf-8", errors="replace")
    missing_input = re.search(
        r"(?:LaTeX Error:\s+File|I (?:can't|cannot) find file)\s+"
        r"[`'\"]?([^`'\"\s]+\.tex)[`'\"]?\s*(?:not found)?",
        source,
        re.IGNORECASE,
    )
    if missing_input:
        return PrimaryError(f"{missing_input.group(1)} is missing")
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


def incomplete_document_warnings(warnings: list[str]) -> list[str]:
    patterns = (
        re.compile(r"Missing character:", re.IGNORECASE),
        re.compile(
            r"undefined (?:citation|reference|citations|references)", re.IGNORECASE
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


def report_failure(
    outcome: BuildOutcome, tex_file: str, auto_install: bool, reporter: Reporter
) -> None:
    layout = outcome.layout or BuildLayout.beside_source(tex_file)
    error = outcome.primary_error
    if error is not None:
        location = ""
        if error.file and error.line:
            location = f" at {error.file}:{error.line}"
        reporter.error(f"Build failed: {error.message}{location}")
    elif outcome.failure_kind == FailureKind.INSTALL_FAILED:
        reporter.error("Build failed: TeX Live package installation failed.")
    else:
        reporter.error("Build failed: no primary LaTeX error could be identified.")

    if outcome.failure_kind == FailureKind.DISABLED and not auto_install:
        reporter.error("Automatic package installation is disabled by --no-install.")
    elif outcome.failure_kind == FailureKind.INSTALL_FAILED and error is not None:
        reporter.error("TeX Live package installation failed.")
    elif outcome.failure_kind == FailureKind.UNMAPPED:
        reporter.error(
            f"Could not map missing TeX files to packages: {', '.join(outcome.unmapped_files)}"
        )
    elif outcome.failure_kind == FailureKind.CEILING:
        reporter.error(
            f"Automatic package installation stopped after {MAX_INSTALL_ROUNDS} rounds."
        )
    elif outcome.failure_kind == FailureKind.UNIDENTIFIED:
        reporter.error("No missing TeX package could be identified.")
    if layout.log_path.is_file():
        reporter.error(f"See {layout.display_log} for complete diagnostics.")
    if outcome.pdf_changed:
        reporter.error(f"{layout.display_pdf} may be incomplete.")
