import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from ._trace import span
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
    is_project_source_reference,
    managed_executable,
    missing_tinytex_source_files,
    resolve_tinytex_packages,
    runtime_supports_layout_hook,
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
    "synctex",
    "synctex.gz",
]
JOB_AUX_EXTENSIONS = [*AUX_EXTENSIONS, "xdy"]
FIXED_AUXILIARY_FILES = ["missfont.log"]
GENERATED_DIRECTORIES = ["_minted", "_minted-{jobname}"]
LAYOUT_HOOK_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class CompileObservation:
    result: subprocess.CompletedProcess[str]
    layout: BuildLayout | None
    pdf_before: tuple[int, int] | None


def default_build_layout(tex_file: str) -> BuildLayout:
    return BuildLayout.beside_source(tex_file)


def _recorded_artifact_path(layout: BuildLayout, name: str) -> Path:
    path = Path(name)
    if not path.is_absolute():
        path = layout.source.parent / path
    return Path(os.path.abspath(os.fspath(path)))


def _recorded_build_files(layout: BuildLayout) -> tuple[set[Path], set[Path]]:
    inputs: set[Path] = set()
    outputs: set[Path] = set()
    fls_path = layout.aux_dir / f"{layout.jobname}.fls"
    if fls_path.is_file():
        for line in fls_path.read_text(encoding="utf-8", errors="replace").splitlines():
            kind, separator, name = line.partition(" ")
            if not separator or kind not in {"INPUT", "OUTPUT"}:
                continue
            destination = inputs if kind == "INPUT" else outputs
            destination.add(_recorded_artifact_path(layout, name))

    database_path = layout.aux_dir / f"{layout.jobname}.fdb_latexmk"
    if database_path.is_file():
        generated_section = False
        for line in database_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            stripped = line.strip()
            if stripped.startswith('["'):
                generated_section = False
                continue
            if stripped == "(generated)":
                generated_section = True
                continue
            if stripped.startswith("("):
                generated_section = False
                continue
            if generated_section:
                match = re.fullmatch(r'"([^"\n]+)"', stripped)
                if match:
                    outputs.add(_recorded_artifact_path(layout, match.group(1)))
                continue
            match = re.fullmatch(
                r'"([^"\n]+)"\s+\S+\s+\S+\s+\S+\s+"[^"\n]*"',
                stripped,
            )
            if match:
                inputs.add(_recorded_artifact_path(layout, match.group(1)))
    return inputs, outputs


def _is_auxiliary_artifact(path: Path) -> bool:
    return any(path.name.endswith(f".{extension}") for extension in AUX_EXTENSIONS)


def cleanup_auxiliary_files(tex_file: str, layout: BuildLayout | None = None) -> None:
    layout = layout or default_build_layout(tex_file)
    recorded_inputs, recorded_outputs = _recorded_build_files(layout)
    generated_artifacts = {
        path for path in recorded_outputs if _is_auxiliary_artifact(path)
    }
    project_inputs = recorded_inputs - recorded_outputs
    for path in generated_artifacts:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for extension in JOB_AUX_EXTENSIONS:
        for directory in {layout.aux_dir, layout.out_dir}:
            path = Path(os.path.abspath(directory / f"{layout.jobname}.{extension}"))
            if path in project_inputs:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    for name in FIXED_AUXILIARY_FILES:
        path = Path(os.path.abspath(layout.source.parent / name))
        if path in project_inputs:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for pattern in GENERATED_DIRECTORIES:
        generated = Path(
            os.path.abspath(layout.aux_dir / pattern.format(jobname=layout.jobname))
        )
        if any(generated == path or generated in path.parents for path in project_inputs):
            continue
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
    with span("latexmk_compile", engine=engine, forced=force):
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


def _layout_hook_code(nonce: str) -> tuple[str, str, str]:
    function_name = f"texmini_layout_{nonce}"
    marker = f"TEXMINI_LAYOUT_{nonce}|"
    acknowledgement = f"ACK_{nonce}\n"
    fields = ("aux_dir", "out_dir")
    encoded_fields = [
        *(f'unpack("H*",($x{{{field}}}//""))' for field in fields),
        'unpack("H*",($out2_dir//""))',
        *(
            f'unpack("H*",($x{{{field}}}//""))'
            for field in ("root_name", "log_file", "tex_file")
        ),
    ]
    encoded_output = ',"|",'.join(encoded_fields)
    code = (
        f"sub {function_name} {{ my %x=@_; "
        "my $old=select(STDOUT); $|=1; select($old); "
        f'print "{marker}",unpack("H*",good_cwd()),"|",'
        f'{encoded_output},"\\n"; '
        "my $ack=<STDIN>; "
        f'die "texmini layout acknowledgement failed\\n" unless '
        f'defined($ack) && $ack eq "{acknowledgement}"; '
        "return 0; } "
        f'add_hook("compile_begin","{function_name}");'
    )
    return code, marker, acknowledgement


def _decode_layout_field(value: str) -> str:
    return os.fsdecode(bytes.fromhex(value))


def _reported_path(compile_directory: Path, value: str) -> Path:
    path = Path(value) if value else Path(".")
    if not path.is_absolute():
        path = compile_directory / path
    return path.resolve()


def _layout_from_hook_fields(
    fields: list[str], tex_file: str
) -> BuildLayout:
    if len(fields) != 7:
        raise ValueError("unexpected latexmk layout field count")
    cwd_value, aux_value, out_value, out2_value, jobname, log_value, source_value = (
        _decode_layout_field(value) for value in fields
    )
    if not cwd_value or not jobname or not source_value:
        raise ValueError("latexmk omitted a required layout field")
    compile_directory = Path(cwd_value).resolve()
    aux_dir = _reported_path(compile_directory, aux_value)
    out_dir = _reported_path(compile_directory, out2_value or out_value)
    source = _reported_path(compile_directory, source_value)
    log_path = _reported_path(compile_directory, log_value)
    return BuildLayout(
        source,
        jobname,
        aux_dir,
        out_dir,
        out_dir / f"{jobname}.pdf",
        log_path,
        Path(tex_file).is_absolute(),
    )


def run_tinytex_compile_with_layout(
    engine: str,
    latexmk_args: list[str] | tuple[str, ...],
    tex_file: str,
    root: Path,
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
    cwd: Path | None = None,
) -> CompileObservation:
    env = tinytex_env(root) if env is None else env
    reporter = reporter or Reporter()
    latexmk = executable_on_path_with_env("latexmk", env) or "latexmk"
    nonce = secrets.token_hex(12)
    hook_code, marker, acknowledgement = _layout_hook_code(nonce)
    args = [
        latexmk,
        *ENGINE_ARGS[engine],
        "-cd",
        "-interaction=nonstopmode",
        "-file-line-error",
        *latexmk_args,
        "-e",
        hook_code,
    ]
    options: dict[str, object] = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
    }
    output_parts: list[str] = []
    layout: BuildLayout | None = None
    before: tuple[int, int] | None = None
    line_queue: queue.Queue[str | BaseException | None] = queue.Queue()

    with span("latexmk_compile", engine=engine, forced=False, layout_hook=True):
        with span(
            "subprocess", command=Path(args[0]).name, argument_count=len(args)
        ) as command_trace:
            process = subprocess.Popen(args, **options)
            assert process.stdout is not None
            assert process.stdin is not None

            def read_output() -> None:
                try:
                    for line in process.stdout:
                        line_queue.put(line)
                except BaseException as error:
                    line_queue.put(error)
                finally:
                    line_queue.put(None)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            deadline = monotonic() + LAYOUT_HOOK_TIMEOUT_SECONDS
            protocol_failed = False
            try:
                while True:
                    timeout = (
                        None
                        if layout is not None or protocol_failed
                        else max(0.0, deadline - monotonic())
                    )
                    try:
                        item = line_queue.get(timeout=timeout)
                    except queue.Empty:
                        protocol_failed = True
                        process.kill()
                        continue
                    if item is None:
                        break
                    if isinstance(item, BaseException):
                        raise item
                    if item.startswith(marker):
                        try:
                            layout = _layout_from_hook_fields(
                                item.removeprefix(marker).rstrip("\r\n").split("|"),
                                tex_file,
                            )
                            before = pdf_snapshot(layout.pdf_path)
                            process.stdin.write(acknowledgement)
                            process.stdin.flush()
                            process.stdin.close()
                        except (BrokenPipeError, OSError, ValueError):
                            layout = None
                            before = None
                            protocol_failed = True
                            process.kill()
                        continue
                    output_parts.append(item)
                    if reporter.verbose:
                        print(item, end="", flush=True)
            except BaseException:
                process.kill()
                if not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
                process.wait()
                reader.join()
                raise
            if not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            returncode = process.wait()
            reader.join()
            command_trace["returncode"] = returncode
            command_trace["layout_observed"] = layout is not None
            command_trace["protocol_failed"] = protocol_failed

    output = "".join(output_parts)
    reporter.observe_output(output)
    return CompileObservation(
        subprocess.CompletedProcess(args, returncode, output, None),
        layout,
        before,
    )


def resolve_build_layout(
    engine: str,
    latexmk_args: list[str] | tuple[str, ...],
    tex_file: str,
    env: dict[str, str],
    reporter: Reporter,
) -> BuildLayout:
    latexmk = executable_on_path_with_env("latexmk", env) or "latexmk"
    with span("latexmk_layout", engine=engine):
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
    input_path_is_absolute = source.is_absolute()
    if not source.is_absolute():
        source = Path.cwd() / source
    return BuildLayout(
        source.resolve(),
        jobname,
        aux_dir.resolve(),
        out_dir.resolve(),
        out_dir.resolve() / f"{jobname}.pdf",
        aux_dir.resolve() / f"{jobname}.log",
        input_path_is_absolute,
    )


def pdf_snapshot(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat_result = path.stat()
    return stat_result.st_mtime_ns, stat_result.st_size


def synctex_artifact_requested(
    latexmk_args: list[str] | tuple[str, ...], layout: BuildLayout
) -> bool:
    mode = _synctex_mode(latexmk_args)
    if not mode.strip("+-0"):
        return False
    suffix = "synctex" if mode.startswith("-") else "synctex.gz"
    artifacts = {
        layout.aux_dir / f"{layout.jobname}.{suffix}",
        layout.out_dir / f"{layout.jobname}.{suffix}",
    }
    return not any(artifact.is_file() for artifact in artifacts)


def _synctex_mode(latexmk_args: list[str] | tuple[str, ...]) -> str:
    for argument in reversed(latexmk_args):
        if match := re.match(r"^-+synctex(?:=(.*))?$", argument, re.IGNORECASE):
            return match.group(1) or "1"
    return "0"


def synctex_enabled(latexmk_args: list[str] | tuple[str, ...]) -> bool:
    return bool(_synctex_mode(latexmk_args).strip("+-0"))


def stale_failed_build(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    output = (getattr(result, "stdout", "") or "").lower()
    return "nothing to do" in output or "up-to-date" in output


def resolve_layout_and_snapshot(
    request: BuildRequest, env: dict[str, str], reporter: Reporter
) -> tuple[BuildLayout, tuple[int, int] | None]:
    layout = resolve_build_layout(
        request.engine, request.latexmk_args, request.tex_file, env, reporter
    )
    return layout, pdf_snapshot(layout.pdf_path)


def _run_build(request: BuildRequest, reporter: Reporter) -> BuildOutcome:
    root = tinytex_root()
    install_tinytex_runtime(root, reporter)
    env = tinytex_env(root)
    if request.auto_install:
        ensure_tinytex_engine(root, request.engine, env, reporter)
    elif managed_executable(root, request.engine) is None:
        layout, pdf_before = resolve_layout_and_snapshot(request, env, reporter)
        return BuildOutcome(
            1,
            monotonic() - request.started_at,
            pdf_snapshot(layout.pdf_path) != pdf_before,
            failure_kind=FailureKind.DISABLED,
            primary_error=PrimaryError(
                f"{request.engine} is not installed in TinyTeX; "
                "rerun without --no-install to install it"
            ),
            layout=layout,
        )
    requirements = analyze_source_requirements(request.tex_file)
    source_files = list(requirements.files)
    project_owned_files = {
        file_name
        for file_name in source_files
        if is_project_source_reference(file_name)
    } | {
        path.name
        for path in requirements.sources
        if path.suffix.lower() in {".sty", ".cls", ".bst", ".bbx", ".cbx"}
    }
    if (
        "repstopdf" in requirements.tools
        and executable_on_path_with_env("gs", env) is None
    ):
        layout, pdf_before = resolve_layout_and_snapshot(request, env, reporter)
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
        layout, pdf_before = resolve_layout_and_snapshot(request, env, reporter)
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
        if managed_executable(root, tool) is None
    ]
    source_direct_packages = [DIRECT_TOOL_PACKAGES[tool] for tool in missing_tools]
    attempted_packages: set[str] = set()
    install_rounds = 0

    if not request.auto_install and missing_tools:
        layout, pdf_before = resolve_layout_and_snapshot(request, env, reporter)
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
            root,
            request.tex_file,
            env,
            source_files,
            source_paths=requirements.sources,
            project_scan_complete=True,
            reporter=reporter,
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
                layout, pdf_before = resolve_layout_and_snapshot(
                    request, env, reporter
                )
                return BuildOutcome(
                    install_result.returncode,
                    monotonic() - request.started_at,
                    pdf_snapshot(layout.pdf_path) != pdf_before,
                    failure_kind=FailureKind.INSTALL_FAILED,
                    layout=layout,
                )
            unavailable_tools = [
                tool
                for tool in missing_tools
                if managed_executable(root, tool) is None
            ]
            if unavailable_tools:
                raise TexMiniError(
                    "Error: TinyTeX package installation completed but did not "
                    f"provide: {', '.join(unavailable_tools)}."
                )

    reporter.status(f"Compiling {request.tex_file}...")
    if runtime_supports_layout_hook(root) and not synctex_enabled(
        request.latexmk_args
    ):
        observation = run_tinytex_compile_with_layout(
            request.engine,
            request.latexmk_args,
            request.tex_file,
            root,
            env=env,
            reporter=reporter,
            cwd=Path.cwd(),
        )
        if observation.layout is not None:
            result = observation.result
            layout = observation.layout
            pdf_before = observation.pdf_before
        else:
            layout, pdf_before = resolve_layout_and_snapshot(request, env, reporter)
            result = run_tinytex_compile(
                request.engine,
                request.latexmk_args,
                root,
                env=env,
                reporter=reporter,
                cwd=Path.cwd(),
            )
    else:
        layout, pdf_before = resolve_layout_and_snapshot(request, env, reporter)
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
            root,
            request.tex_file,
            env,
            source_files,
            source_paths=requirements.sources,
            project_scan_complete=True,
            reporter=reporter,
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

        resolvable_missing_files = [
            file_name
            for file_name in missing_files
            if file_name not in project_owned_files
        ]
        resolved = (
            resolve_tinytex_packages(
                root, resolvable_missing_files, env=env, reporter=reporter
            )
            if resolvable_missing_files
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
                project_files=tuple(
                    file_name
                    for file_name in missing_files
                    if file_name in project_owned_files
                ),
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
    pdf_after = pdf_snapshot(layout.pdf_path)
    pdf_changed = pdf_after != pdf_before
    if result.returncode == 0:
        if pdf_after is None:
            return BuildOutcome(
                1,
                elapsed,
                pdf_changed,
                failure_kind=FailureKind.ORDINARY,
                primary_error=PrimaryError(
                    "latexmk reported success but did not produce the expected "
                    f"PDF: {layout.display_pdf}"
                ),
                layout=layout,
            )
        return BuildOutcome(0, elapsed, pdf_changed, layout=layout)
    return BuildOutcome(
        result.returncode,
        elapsed,
        pdf_changed,
        failure_kind=failure_kind,
        missing_files=tuple(last_missing_files),
        unmapped_files=tuple(last_unmapped_files),
        project_files=tuple(
            file_name
            for file_name in last_missing_files
            if file_name in project_owned_files
        ),
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
    with span("document_build", engine=engine, auto_install=auto_install) as trace:
        outcome = _run_build(request, reporter)
        trace["returncode"] = outcome.returncode
        trace["failure_kind"] = (
            outcome.failure_kind.value if outcome.failure_kind is not None else None
        )
        return outcome


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
