import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from texmini import __version__

from ._download import download
from .model import TexMiniError
from .project import analyze_source_requirements, project_source_files
from .reporting import Reporter, run_command

if TYPE_CHECKING:
    import tarfile


TINYTEX_RELEASE_BASE = "https://github.com/rstudio/tinytex-releases/releases/download"
RUNTIME_METADATA = ".texmini-runtime.json"
TINYTEX_ENGINE_PACKAGES = {"xelatex": "xetex"}
DIRECT_TOOL_PACKAGES = {
    "biber": "biber",
    "bibtex": "bibtex",
    "makeglossaries": "glossaries",
    "makeindex": "makeindex",
    "repstopdf": "epstopdf",
    "xindy": "xindy",
}


@dataclass(frozen=True)
class RuntimeAsset:
    filename: str
    sha256: str
    format: str


@dataclass(frozen=True)
class RuntimeManifest:
    schema_version: int
    tinytex_version: str
    repository: str
    assets: dict[str, RuntimeAsset]


def load_runtime_manifest() -> RuntimeManifest:
    import json

    manifest_path = files("texmini").joinpath("runtime_manifest.json")
    with manifest_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != 1:
        raise TexMiniError("Error: Unsupported TinyTeX runtime manifest schema.")
    repository = str(data["repository"])
    if not repository.lower().startswith("https://"):
        raise TexMiniError("Error: The TinyTeX repository must use HTTPS.")
    assets = {
        key: RuntimeAsset(
            filename=str(value["filename"]),
            sha256=str(value["sha256"]),
            format=str(value["format"]),
        )
        for key, value in data["assets"].items()
    }
    return RuntimeManifest(
        schema_version=1,
        tinytex_version=str(data["tinytex_version"]),
        repository=repository,
        assets=assets,
    )


def tinytex_asset_url(manifest: RuntimeManifest, asset: RuntimeAsset) -> str:
    return f"{TINYTEX_RELEASE_BASE}/v{manifest.tinytex_version}/{asset.filename}"


COMMON_TEXLIVE_FILE_PACKAGES = {
    "8r.enc": "dvips",
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
    "imakeidx.sty": "imakeidx",
    "memoir.cls": "memoir",
    "minted.sty": "minted",
    "nomencl.sty": "nomencl",
    "numeric.cbx": "biblatex",
    "pgf.sty": "pgf",
    "plainnat.bst": "natbib",
    "tikz.sty": "pgf",
    "tocbasic.sty": "koma-script",
    "unsrtnat.bst": "natbib",
    "xcolor.sty": "xcolor",
}


def executable_on_path(command: str) -> str | None:
    return executable_on_path_with_env(command, os.environ)


def executable_on_path_with_env(command: str, env: dict[str, str]) -> str | None:
    path = env.get("PATH", os.defpath)
    for candidate in _platform_tool_names(command):
        if resolved := shutil.which(candidate, path=path):
            return resolved
    return None


def _platform_tool_names(command: str) -> tuple[str, ...]:
    if sys.platform != "win32" or Path(command).suffix:
        return (command,)
    return command, f"{command}.exe", f"{command}.bat"


def tinytex_root() -> Path:
    return Path(
        os.environ.get("TEXMINI_TINYTEX_ROOT", Path.home() / ".texmini" / "TinyTeX")
    )


def package_map_path() -> Path:
    return Path(
        os.environ.get(
            "TEXMINI_PACKAGE_MAP", Path.home() / ".texmini" / "package-map.json"
        )
    )


def display_path(path: Path) -> str:
    try:
        return os.fspath(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return os.fspath(path)


def tinytex_bin_dir(root: Path, executable: str = "latexmk") -> Path:
    bin_root = root / "bin"
    for path in sorted(bin_root.iterdir() if bin_root.exists() else []):
        for candidate in _platform_tool_names(executable):
            if shutil.which(candidate, path=os.fspath(path)):
                return path
    raise TexMiniError(
        f"Error: TinyTeX does not provide {executable} at {root}. "
        f"Delete {root} and run texmini install-tinytex to recreate it."
    )


def managed_tool(root: Path, executable: str) -> str:
    bin_dir = tinytex_bin_dir(root, executable)
    for candidate in _platform_tool_names(executable):
        if resolved := shutil.which(candidate, path=os.fspath(bin_dir)):
            return resolved
    raise AssertionError("tinytex_bin_dir returned without resolving its tool")


def tinytex_env(root: Path, executable: str = "latexmk") -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = tinytex_bin_dir(root, executable)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["LATEXMKRCSYS"] = os.fspath(Path(__file__).with_name("texmini_latexmkrc"))
    env.pop("TEXLIVE_DOWNLOADER", None)
    env["TL_DOWNLOAD_PROGRAM"] = os.path.abspath(sys.executable)
    env["TL_DOWNLOAD_ARGS"] = "-m texmini._download"
    return env


def tinytex_platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        machine = platform.machine().lower()
        if machine in {"aarch64", "arm64"}:
            if platform.libc_ver()[0].lower() == "musl":
                raise _unsupported_platform()
            return "linux-arm64"
        if machine not in {"amd64", "x86_64"}:
            raise _unsupported_platform()
        libc = platform.libc_ver()[0].lower()
        return "linuxmusl-x86_64" if libc == "musl" else "linux-x86_64"
    if sys.platform == "win32":
        if platform.machine().lower() in {"amd64", "x86_64"}:
            return "windows-x86_64"
        raise _unsupported_platform()
    raise _unsupported_platform()


def _unsupported_platform() -> TexMiniError:
    return TexMiniError(
        "Error: This platform is unsupported. Supported platforms are macOS "
        "(Apple Silicon and x86-64), Linux glibc (ARM64 and x86-64), Linux "
        "musl (x86-64), and Windows (x86-64)."
    )


def check_runtime_prerequisites(platform_key: str) -> None:
    if platform_key != "windows-x86_64" and executable_on_path("perl") is None:
        raise TexMiniError(
            "Error: Perl is required by TinyTeX on macOS and Linux.\n"
            "Install Perl with your operating system's package manager and retry."
        )


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
        raise TexMiniError(
            f"Error: Unsupported entry in TinyTeX archive: {member.name}"
        )
    if member.issym() or member.islnk():
        link_path = member.linkname.replace("\\", "/")
        target = (
            posixpath.normpath(
                posixpath.join(posixpath.dirname(normalized_path), link_path)
            )
            if member.issym()
            else posixpath.normpath(link_path)
        )
        if posixpath.isabs(link_path) or not is_managed_path(target):
            raise TexMiniError(
                f"Error: Unsafe link in TinyTeX archive: {member.name} -> {member.linkname}"
            )


def _extract_tinytex_archive(archive_path: Path, destination: Path) -> Path:
    import tarfile

    with tarfile.open(archive_path, mode="r:xz") as archive:
        members = archive.getmembers()
        for member in members:
            validate_tinytex_archive_member(member)
        archive.extractall(destination, members=members)
    extracted_root = next(
        (
            candidate
            for root_name in ("TinyTeX", ".TinyTeX")
            if (candidate := destination / root_name).is_dir()
        ),
        None,
    )
    if extracted_root is None:
        raise TexMiniError("Error: TinyTeX archive did not contain a TinyTeX runtime.")
    return extracted_root


def _extract_tinytex_windows_sfx(
    archive_path: Path, destination: Path, reporter: Reporter
) -> Path:
    result = run_command(
        [os.fspath(archive_path), "-y", f"-o{destination}"],
        reporter=reporter,
        cwd=destination.parent,
        check=False,
    )
    if result.returncode != 0:
        raise TexMiniError(
            f"Error: The TinyTeX Windows extractor exited with status {result.returncode}."
        )
    extracted_root = destination / "TinyTeX"
    if not extracted_root.is_dir():
        raise TexMiniError(
            "Error: The TinyTeX Windows extractor did not create a TinyTeX runtime."
        )
    return extracted_root


def validate_tinytex_runtime(root: Path, platform_key: str) -> None:
    required_tools = ("latexmk", "tlmgr", "kpsewhich", "pdflatex")
    for tool in required_tools:
        managed_tool(root, tool)
    if platform_key == "windows-x86_64":
        required_files = (
            root / "bin" / "windows" / "runscript.tlu",
            root / "tlpkg" / "tlperl" / "bin" / "perl.exe",
        )
        for path in required_files:
            if not path.is_file():
                raise TexMiniError(
                    f"Error: TinyTeX does not provide {path.name} at {root}. "
                    f"Delete {root} and run texmini install-tinytex to recreate it."
                )


def _write_runtime_metadata(
    root: Path,
    manifest: RuntimeManifest,
    platform_key: str,
    asset: RuntimeAsset,
) -> None:
    import json

    metadata = {
        "schema_version": 1,
        "texmini_version": __version__,
        "tinytex_version": manifest.tinytex_version,
        "platform": platform_key,
        "asset": asset.filename,
        "sha256": asset.sha256,
        "repository": manifest.repository,
    }
    with (root / RUNTIME_METADATA).open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")


def install_tinytex_runtime(
    root: Path,
    reporter: Reporter | None = None,
    announce_existing: bool = False,
) -> None:
    import tempfile

    reporter = reporter or Reporter()
    platform_key = tinytex_platform_key()
    check_runtime_prerequisites(platform_key)
    if root.exists():
        validate_tinytex_runtime(root, platform_key)
        if announce_existing or reporter.verbose:
            reporter.status("Using the existing private TinyTeX runtime.")
        return

    manifest = load_runtime_manifest()
    try:
        asset = manifest.assets[platform_key]
    except KeyError as error:
        raise _unsupported_platform() from error
    url = tinytex_asset_url(manifest, asset)
    root.parent.mkdir(parents=True, exist_ok=True)
    reporter.status(f"Preparing TinyTeX {manifest.tinytex_version} for {platform_key}.")
    reporter.status(f"Downloading {asset.filename}...")
    with tempfile.TemporaryDirectory(
        prefix=".texmini-install-", dir=root.parent
    ) as temporary_directory:
        staging_parent = Path(temporary_directory)
        archive_path = staging_parent / asset.filename
        payload = staging_parent / "payload"
        payload.mkdir()
        download(url, archive_path, asset.sha256)
        reporter.status(f"Verified {asset.filename}.")
        reporter.status("Installing the private TinyTeX runtime...")
        if asset.format == "tar.xz":
            extracted_root = _extract_tinytex_archive(archive_path, payload)
        elif asset.format == "windows-sfx":
            extracted_root = _extract_tinytex_windows_sfx(
                archive_path, payload, reporter
            )
        else:
            raise TexMiniError(
                f"Error: Unsupported TinyTeX asset format: {asset.format}"
            )
        validate_tinytex_runtime(extracted_root, platform_key)
        _write_runtime_metadata(extracted_root, manifest, platform_key, asset)
        extracted_root.rename(root)


install_tinytex_archive = install_tinytex_runtime


def install_tinytex(verbose: bool = False) -> int:
    reporter = Reporter(verbose)
    try:
        install_tinytex_runtime(tinytex_root(), reporter, announce_existing=True)
        return 0
    except TexMiniError as error:
        reporter.error(str(error))
        return 1


def tex_source_requirements(tex_file: str) -> tuple[list[str], list[str]]:
    if not os.path.isfile(os.fspath(tex_file)):
        return [], []
    requirements = analyze_source_requirements(tex_file)
    packages = [DIRECT_TOOL_PACKAGES[tool] for tool in requirements.tools]
    return list(requirements.files), list(dict.fromkeys(packages))


def tex_source_package_files(tex_file: str) -> list[str]:
    source_files, _ = tex_source_requirements(tex_file)
    return source_files


def missing_tinytex_source_files(
    root: Path,
    tex_file: str,
    env: dict[str, str] | None = None,
    source_files: list[str] | None = None,
    reporter: Reporter | None = None,
) -> list[str]:
    env = tinytex_env(root) if env is None else env
    source_files = (
        tex_source_package_files(tex_file) if source_files is None else source_files
    )
    if not source_files:
        return []

    source_directory = Path(tex_file).resolve().parent
    project_root = Path.cwd().resolve()
    try:
        source_directory.relative_to(project_root)
    except ValueError:
        project_root = source_directory
    source_directories = {path.parent for path in project_source_files(tex_file)}
    local_files = set()
    for file_name in source_files:
        if any((directory / file_name).is_file() for directory in source_directories):
            local_files.add(file_name)
            continue
        if next(project_root.rglob(file_name), None) is not None:
            local_files.add(file_name)
    search_files = [
        file_name for file_name in source_files if file_name not in local_files
    ]
    if not search_files:
        return []
    result = run_command(
        [managed_tool(root, "kpsewhich"), *search_files],
        reporter=reporter,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        cwd=source_directory,
    )
    found_files = {
        os.path.basename(line) for line in result.stdout.splitlines() if line
    }
    return [file_name for file_name in search_files if file_name not in found_files]


def load_package_map(path: Path) -> dict[str, str]:
    import json

    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {str(key): str(value) for key, value in data.items() if value}


def save_package_map(path: Path, package_map: dict[str, str]) -> None:
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
        if (
            not separator
            or not package_name
            or not all(char.isalnum() or char in "_.+-" for char in package_name)
        ):
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
        if (
            len(stem) > 4
            and stem[0] in {"e", "t"}
            and stem[1:4] == "crm"
            and stem[4:].isdigit()
        ):
            return "ec"
    return COMMON_TEXLIVE_FILE_PACKAGES.get(file_name)


def resolve_tinytex_packages(
    root: Path,
    missing_files: list[str],
    cache_path: Path | None = None,
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
) -> dict[str, str]:
    env = tinytex_env(root, "tlmgr") if env is None else _tlmgr_env(env)
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
        result = run_command(
            [
                executable_on_path_with_env("tlmgr", env) or "tlmgr",
                "--repository",
                load_runtime_manifest().repository,
                "search",
                "--global",
                "--file",
                f"/{missing_file}",
            ],
            reporter=reporter,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        _report_tlmgr_failure(result, reporter)
        package = package_from_tlmgr_search(result.stdout)
        if package:
            package_map[missing_file] = package
            resolved[missing_file] = package
            updated = True

    if updated:
        save_package_map(cache_path, package_map)
    return resolved


def install_tinytex_packages(
    root: Path,
    packages: list[str],
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
) -> subprocess.CompletedProcess[str]:
    env = tinytex_env(root, "tlmgr") if env is None else _tlmgr_env(env)
    result = run_command(
        [
            executable_on_path_with_env("tlmgr", env) or "tlmgr",
            "--repository",
            load_runtime_manifest().repository,
            "install",
            *packages,
        ],
        reporter=reporter,
        env=env,
        check=False,
    )
    _report_tlmgr_failure(result, reporter)
    return result


def _report_tlmgr_failure(
    result: subprocess.CompletedProcess[str], reporter: Reporter | None
) -> None:
    if result.returncode == 0 or reporter is None or reporter.verbose:
        return
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    if lines:
        reporter.error("TeX Live package manager output:")
        for line in lines[-5:]:
            reporter.error(line)


def _tlmgr_env(env: dict[str, str]) -> dict[str, str]:
    managed_env = env.copy()
    managed_env.pop("TEXLIVE_DOWNLOADER", None)
    managed_env["TL_DOWNLOAD_PROGRAM"] = os.path.abspath(sys.executable)
    managed_env["TL_DOWNLOAD_ARGS"] = "-m texmini._download"
    return managed_env


def ensure_tinytex_engine(
    root: Path, engine: str, env: dict[str, str], reporter: Reporter
) -> None:
    package = TINYTEX_ENGINE_PACKAGES.get(engine)
    if package is None or executable_on_path_with_env(engine, env):
        return
    reporter.status(f"Installing the {engine} engine...")
    result = install_tinytex_packages(root, [package], env, reporter)
    if result.returncode != 0:
        raise TexMiniError(f"Error: TinyTeX could not install the {engine} engine.")
