import os
import re
import shutil
import subprocess
from pathlib import Path
from time import monotonic

from .model import (
    ENGINE_ARGS,
    MAX_INSTALL_ROUNDS,
    BuildLayout,
    BuildOutcome,
    BuildRequest,
    CliConfig,
    FailureKind,
    PrimaryError,
    TexMiniError,
)
from .project import (
    analyze_source_requirements,
    check_bibliography,
    resolve_engine,
    tex_log_requirements,
)
from .reporting import (
    Reporter,
    document_warnings,
    format_elapsed,
    incomplete_document_warnings,
    primary_latex_error,
    report_failure,
    run_command,
    show_resolution_mappings,
)
from .runtime import (
    DIRECT_TOOL_PACKAGES,
    ensure_tinytex_engine,
    executable_on_path_with_env,
    install_tinytex_packages,
    install_tinytex_runtime,
    missing_tinytex_source_files,
    resolve_tinytex_packages,
    tinytex_env,
    tinytex_root,
)

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


def default_build_layout(tex_file: str) -> BuildLayout:
    return BuildLayout.beside_source(tex_file)


def cleanup_auxiliary_files(tex_file: str, layout: BuildLayout | None = None) -> None:
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
        for directory in {layout.aux_dir, layout.out_dir}:
            try:
                os.unlink(directory / f"{layout.jobname}.{extension}")
            except FileNotFoundError:
                pass
    for path in FIXED_AUXILIARY_FILES:
        try:
            os.unlink(layout.source.parent / path)
        except FileNotFoundError:
            pass
    for pattern in GENERATED_DIRECTORIES:
        generated = layout.aux_dir / pattern.format(jobname=layout.jobname)
        if generated.is_dir():
            shutil.rmtree(generated)


def run_tinytex_compile(
    engine: str,
    latexmk_args: list[str] | tuple[str, ...],
    root: Path,
    force: bool = False,
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = tinytex_env(root) if env is None else env
    force_args = ["-g"] if force else []
    latexmk = executable_on_path_with_env("latexmk", env) or "latexmk"
    return run_command(
        [
            latexmk,
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
    latexmk_args: list[str] | tuple[str, ...],
    tex_file: str,
    env: dict[str, str],
    reporter: Reporter,
) -> BuildLayout:
    latexmk = executable_on_path_with_env("latexmk", env) or "latexmk"
    result = run_command(
        [latexmk, *ENGINE_ARGS[engine], "-cd", "-dir-report-only", *latexmk_args],
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


def synctex_artifact_requested(
    latexmk_args: list[str] | tuple[str, ...], layout: BuildLayout
) -> bool:
    values = [
        match.group(1)
        for argument in latexmk_args
        if (match := re.match(r"^-+synctex(?:=(.*))?$", argument, re.IGNORECASE))
    ]
    enabled = bool(values) and values[-1] not in {"0", "-1"}
    artifacts = {
        layout.aux_dir / f"{layout.jobname}.synctex.gz",
        layout.out_dir / f"{layout.jobname}.synctex.gz",
    }
    return enabled and not any(artifact.is_file() for artifact in artifacts)


def stale_failed_build(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    output = (getattr(result, "stdout", "") or "").lower()
    return "nothing to do" in output or "up-to-date" in output


def _run_build(request: BuildRequest, reporter: Reporter) -> BuildOutcome:
    root = tinytex_root()
    install_tinytex_runtime(root, reporter)
    env = tinytex_env(root)
    ensure_tinytex_engine(root, request.engine, env, reporter)
    layout = resolve_build_layout(
        request.engine, request.latexmk_args, request.tex_file, env, reporter
    )
    pdf_before = pdf_snapshot(layout.pdf_path)
    requirements = analyze_source_requirements(request.tex_file)
    source_files = list(requirements.files)
    if (
        "repstopdf" in requirements.tools
        and executable_on_path_with_env("gs", env) is None
    ):
        return BuildOutcome(
            1,
            monotonic() - request.started_at,
            pdf_snapshot(layout.pdf_path) != pdf_before,
            failure_kind=FailureKind.ORDINARY,
            primary_error=PrimaryError(
                "EPS conversion requires Ghostscript (gs); install Ghostscript "
                "with your operating system's package manager and retry"
            ),
            layout=layout,
        )
    if requirements.uses_minted and "-shell-escape" not in request.latexmk_args:
        return BuildOutcome(
            1,
            monotonic() - request.started_at,
            pdf_snapshot(layout.pdf_path) != pdf_before,
            failure_kind=FailureKind.ORDINARY,
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

    if not request.auto_install and missing_tools:
        tool = missing_tools[0]
        return BuildOutcome(
            1,
            monotonic() - request.started_at,
            pdf_snapshot(layout.pdf_path) != pdf_before,
            failure_kind=FailureKind.DISABLED,
            primary_error=PrimaryError(f"{tool} is required but not installed"),
            layout=layout,
        )

    if request.auto_install:
        source_missing = missing_tinytex_source_files(
            root, request.tex_file, env, source_files, reporter
        )
        if source_missing or source_direct_packages:
            reporter.status(f"Analyzing {request.tex_file}...")
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
                    monotonic() - request.started_at,
                    pdf_snapshot(layout.pdf_path) != pdf_before,
                    failure_kind=FailureKind.INSTALL_FAILED,
                    layout=layout,
                )

    reporter.status(f"Compiling {request.tex_file}...")
    result = run_tinytex_compile(
        request.engine,
        request.latexmk_args,
        root,
        force=synctex_artifact_requested(request.latexmk_args, layout),
        env=env,
        reporter=reporter,
        cwd=Path.cwd(),
    )
    if stale_failed_build(result):
        reporter.status(
            "Previous failed build state found; rerunning TeX for fresh diagnostics."
        )
        result = run_tinytex_compile(
            request.engine,
            request.latexmk_args,
            root,
            force=True,
            env=env,
            reporter=reporter,
            cwd=Path.cwd(),
        )
    last_missing_files: list[str] = []
    last_unmapped_files: list[str] = []

    while result.returncode != 0:
        missing_files, log_direct_packages = tex_log_requirements(layout.log_path)
        for missing_file in missing_tinytex_source_files(
            root, request.tex_file, env, source_files, reporter
        ):
            if missing_file not in missing_files:
                missing_files.append(missing_file)
        direct_packages = [*log_direct_packages, *source_direct_packages]
        last_missing_files = missing_files

        if not request.auto_install:
            failure_kind = (
                FailureKind.DISABLED
                if missing_files or direct_packages
                else FailureKind.ORDINARY
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
                failure_kind = FailureKind.UNMAPPED
            elif primary_latex_error(layout.log_path, request.tex_file, missing_files):
                failure_kind = FailureKind.ORDINARY
            else:
                failure_kind = FailureKind.UNIDENTIFIED
            break
        if install_rounds >= MAX_INSTALL_ROUNDS:
            failure_kind = FailureKind.CEILING
            break

        noun = "package" if len(packages) == 1 else "packages"
        dependency = "dependency" if len(packages) == 1 else "dependencies"
        qualifier = (
            f"required {noun}" if install_rounds == 0 else f"additional {dependency}"
        )
        reporter.status(
            f"Installing {len(packages)} {qualifier} "
            f"(package-install round {install_rounds + 1} of {MAX_INSTALL_ROUNDS}): "
            f"{', '.join(packages)}"
        )
        install_result = install_tinytex_packages(root, packages, env, reporter)
        attempted_packages.update(packages)
        install_rounds += 1
        if install_result.returncode != 0:
            return BuildOutcome(
                install_result.returncode,
                monotonic() - request.started_at,
                pdf_snapshot(layout.pdf_path) != pdf_before,
                failure_kind=FailureKind.INSTALL_FAILED,
                missing_files=tuple(missing_files),
                unmapped_files=tuple(last_unmapped_files),
                primary_error=primary_latex_error(
                    layout.log_path, request.tex_file, missing_files
                ),
                layout=layout,
            )
        result = run_tinytex_compile(
            request.engine,
            request.latexmk_args,
            root,
            force=True,
            env=env,
            reporter=reporter,
            cwd=Path.cwd(),
        )
    else:
        failure_kind = None

    elapsed = monotonic() - request.started_at
    pdf_changed = pdf_snapshot(layout.pdf_path) != pdf_before
    if result.returncode == 0:
        return BuildOutcome(0, elapsed, pdf_changed, layout=layout)
    return BuildOutcome(
        result.returncode,
        elapsed,
        pdf_changed,
        failure_kind=failure_kind,
        missing_files=tuple(last_missing_files),
        unmapped_files=tuple(last_unmapped_files),
        primary_error=primary_latex_error(
            layout.log_path, request.tex_file, last_missing_files
        ),
        layout=layout,
    )


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
    request = BuildRequest(
        engine,
        auto_install,
        tex_file,
        latexmk_args,
        started_at,
    )
    return _run_build(request, reporter)


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
    warnings = document_warnings(layout.log_path)
    if not verbose:
        for warning in warnings:
            reporter.warning(warning)
    elapsed = format_elapsed(outcome.elapsed_seconds)
    incomplete_warnings = incomplete_document_warnings(warnings)
    if incomplete_warnings:
        reporter.error(
            f"Built {layout.display_pdf} with missing document content in {elapsed}."
        )
        reporter.error(
            "The PDF contains missing characters or unresolved citations or references."
        )
        reporter.error("Auxiliary build files were retained for diagnosis.")
        return 1
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
