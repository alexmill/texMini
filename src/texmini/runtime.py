import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Iterable, Mapping

from texmini import __version__

from ._trace import span
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
TLMGR_SEARCH_CHUNK_FILES = 32
TLMGR_SEARCH_PATTERN_CHARACTERS = 4000
LAYOUT_HOOK_TINYTEX_VERSIONS = frozenset({"2026.08"})
RUNTIME_ASSET_FORMATS = {
    "darwin": "tar.xz",
    "linux-x86_64": "tar.xz",
    "linux-arm64": "tar.xz",
    "linuxmusl-x86_64": "tar.xz",
    "windows-x86_64": "windows-sfx",
}


def download(
    url: str, destination: Path | str, expected_sha256: str | None = None
) -> None:
    from ._download import download as perform_download

    perform_download(url, destination, expected_sha256)


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
    assets: Mapping[str, RuntimeAsset]


def _parse_runtime_manifest(data: object) -> RuntimeManifest:
    from urllib.parse import urlsplit

    def invalid(detail: str) -> TexMiniError:
        return TexMiniError(f"Error: Invalid TinyTeX runtime manifest: {detail}.")

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise invalid("unsupported schema")
    tinytex_version = data.get("tinytex_version")
    if not isinstance(tinytex_version, str) or re.fullmatch(
        r"[0-9]{4}\.[0-9]{2}", tinytex_version
    ) is None:
        raise invalid("tinytex_version must use YYYY.MM")
    repository = data.get("repository")
    if not isinstance(repository, str):
        raise invalid("repository must be an HTTPS URL")
    parsed_repository = urlsplit(repository)
    if (
        parsed_repository.scheme.lower() != "https"
        or not parsed_repository.netloc
        or parsed_repository.username is not None
        or parsed_repository.password is not None
    ):
        raise invalid("repository must be an HTTPS URL without credentials")
    raw_assets = data.get("assets")
    if not isinstance(raw_assets, dict) or set(raw_assets) != set(
        RUNTIME_ASSET_FORMATS
    ):
        raise invalid("asset keys do not exactly match supported platforms")

    expected_filenames = {
        "darwin": f"TinyTeX-1-darwin-v{tinytex_version}.tar.xz",
        "linux-x86_64": f"TinyTeX-1-linux-x86_64-v{tinytex_version}.tar.xz",
        "linux-arm64": f"TinyTeX-1-linux-arm64-v{tinytex_version}.tar.xz",
        "linuxmusl-x86_64": (
            f"TinyTeX-1-linuxmusl-x86_64-v{tinytex_version}.tar.xz"
        ),
        "windows-x86_64": f"TinyTeX-1-windows-v{tinytex_version}.exe",
    }
    assets: dict[str, RuntimeAsset] = {}
    for key, expected_format in RUNTIME_ASSET_FORMATS.items():
        raw_asset = raw_assets[key]
        if not isinstance(raw_asset, dict):
            raise invalid(f"{key} asset must be an object")
        if set(raw_asset) != {"filename", "sha256", "format"}:
            raise invalid(f"{key} asset fields are incomplete or unknown")
        filename = raw_asset["filename"]
        digest = raw_asset["sha256"]
        asset_format = raw_asset["format"]
        if filename != expected_filenames[key]:
            raise invalid(f"{key} filename does not match the pinned version")
        if not isinstance(digest, str) or re.fullmatch(
            r"[0-9a-f]{64}", digest
        ) is None:
            raise invalid(f"{key} sha256 must be 64 lowercase hexadecimal digits")
        if asset_format != expected_format:
            raise invalid(f"{key} format must be {expected_format}")
        assets[key] = RuntimeAsset(filename, digest, asset_format)

    return RuntimeManifest(
        schema_version=1,
        tinytex_version=tinytex_version,
        repository=repository,
        assets=MappingProxyType(assets),
    )


@lru_cache(maxsize=1)
def _load_runtime_manifest() -> RuntimeManifest:
    import json

    manifest_path = files("texmini").joinpath("runtime_manifest.json")
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise TexMiniError(
            f"Error: Could not read the TinyTeX runtime manifest: {error}"
        ) from error
    return _parse_runtime_manifest(data)


def load_runtime_manifest() -> RuntimeManifest:
    with span("manifest_load"):
        return _load_runtime_manifest()


def runtime_supports_layout_hook(root: Path) -> bool:
    if os.environ.get("TEXMINI_DISABLE_LAYOUT_HOOK"):
        return False
    try:
        import json

        with (root / RUNTIME_METADATA).open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        manifest = load_runtime_manifest()
        platform_key = str(metadata["platform"])
        asset = manifest.assets[platform_key]
    except (KeyError, OSError, TypeError, ValueError):
        return False
    return (
        metadata.get("schema_version") == 1
        and metadata.get("tinytex_version") in LAYOUT_HOOK_TINYTEX_VERSIONS
        and metadata.get("tinytex_version") == manifest.tinytex_version
        and metadata.get("asset") == asset.filename
        and metadata.get("sha256") == asset.sha256
        and metadata.get("repository") == manifest.repository
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
    if resolved := managed_executable(root, executable):
        return Path(resolved).parent
    raise TexMiniError(
        f"Error: TinyTeX does not provide {executable} at {root}. "
        f"Delete {root} and run texmini install-tinytex to recreate it."
    )


def managed_executable(root: Path, executable: str) -> str | None:
    bin_root = root / "bin"
    for path in sorted(bin_root.iterdir() if bin_root.exists() else []):
        for candidate in _platform_tool_names(executable):
            if resolved := shutil.which(candidate, path=os.fspath(path)):
                return resolved
    return None


def managed_tool(root: Path, executable: str) -> str:
    if resolved := managed_executable(root, executable):
        return resolved
    tinytex_bin_dir(root, executable)
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
        libc = platform.libc_ver()[0].strip().lower()
        if libc not in {"glibc", "musl"}:
            raise _unsupported_platform(
                f"unrecognized Linux C library {libc or 'unknown'}"
            )
        if machine in {"aarch64", "arm64"}:
            if libc != "glibc":
                raise _unsupported_platform("Linux musl on ARM64")
            return "linux-arm64"
        if machine not in {"amd64", "x86_64"}:
            raise _unsupported_platform()
        return "linuxmusl-x86_64" if libc == "musl" else "linux-x86_64"
    if sys.platform == "win32":
        if platform.machine().lower() in {"amd64", "x86_64"}:
            return "windows-x86_64"
        raise _unsupported_platform()
    raise _unsupported_platform()


def _unsupported_platform(reason: str | None = None) -> TexMiniError:
    detail = f" ({reason})" if reason else ""
    return TexMiniError(
        f"Error: This platform is unsupported{detail}. Supported platforms are macOS "
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

    with span("runtime_extract", format="tar.xz") as trace:
        with tarfile.open(archive_path, mode="r:xz") as archive:
            member_count = 0
            for member in archive:
                validate_tinytex_archive_member(member)
                if sys.version_info >= (3, 12):
                    archive.extract(member, destination, filter="fully_trusted")
                else:
                    archive.extract(member, destination)
                member_count += 1
            trace["member_count"] = member_count
        extracted_root = next(
            (
                candidate
                for root_name in ("TinyTeX", ".TinyTeX")
                if (candidate := destination / root_name).is_dir()
            ),
            None,
        )
        if extracted_root is None:
            raise TexMiniError(
                "Error: TinyTeX archive did not contain a TinyTeX runtime."
            )
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
    with span("runtime_validation", platform=platform_key):
        required_tools = ("latexmk", "tlmgr", "kpsewhich", "pdflatex", "lualatex")
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
    with span("runtime_prerequisites", platform=platform_key):
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
    reporter.status("Expect about 300–350 MB of disk use for the managed runtime.")
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
    source_paths: Iterable[Path] | None = None,
    reporter: Reporter | None = None,
    project_scan_complete: bool = False,
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
    source_paths = (
        project_source_files(tex_file) if source_paths is None else list(source_paths)
    )
    source_directories = {path.parent for path in source_paths}
    local_files = {
        file_name for file_name in source_files if is_project_source_reference(file_name)
    }
    for file_name in source_files:
        if file_name in local_files:
            continue
        normalized = file_name.replace("\\", "/").lstrip("/")
        matching_sources: list[Path] = []
        for path in source_paths:
            if path.name != normalized.rsplit("/", 1)[-1]:
                continue
            if "/" not in normalized:
                matching_sources.append(path)
                continue
            try:
                relative = path.resolve().relative_to(project_root).as_posix()
            except ValueError:
                continue
            if relative == normalized or relative.endswith(f"/{normalized}"):
                matching_sources.append(path)
        if matching_sources:
            local_files.add(file_name)
            continue
        if any((directory / file_name).is_file() for directory in source_directories):
            local_files.add(file_name)
    candidates = [file_name for file_name in source_files if file_name not in local_files]
    if candidates and not project_scan_complete:
        requested_by_basename: dict[str, list[tuple[str, str]]] = {}
        for file_name in candidates:
            normalized = file_name.replace("\\", "/").lstrip("/")
            requested_by_basename.setdefault(normalized.rsplit("/", 1)[-1], []).append(
                (file_name, normalized)
            )
        with span("local_file_discovery", required_file_count=len(candidates)) as trace:
            scanned_files = 0
            for directory, _, file_names in os.walk(project_root):
                root_directory = Path(directory)
                for name in file_names:
                    scanned_files += 1
                    requested = requested_by_basename.get(name)
                    if not requested:
                        continue
                    relative = (root_directory / name).relative_to(project_root).as_posix()
                    for file_name, normalized in requested:
                        if relative == normalized or relative.endswith(f"/{normalized}"):
                            local_files.add(file_name)
            trace["scanned_file_count"] = scanned_files
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


def is_explicit_local_reference(file_name: str) -> bool:
    normalized = file_name.replace("\\", "/")
    return (
        normalized.startswith(("./", "../", "/"))
        or bool(re.match(r"^[A-Za-z]:/", normalized))
    )


def is_project_source_reference(file_name: str) -> bool:
    normalized = file_name.replace("\\", "/")
    return is_explicit_local_reference(file_name) or "/" in normalized


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


def tlmgr_search_candidates(output: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    pending_package: str | None = None
    for line in output.splitlines():
        if pending_package and line[:1].isspace() and "texmf-dist/" in line:
            candidates.append((pending_package, line.strip()))
            continue
        package_name, separator, rest = line.partition(":")
        if (
            not separator
            or not package_name
            or not all(char.isalnum() or char in "_.+-" for char in package_name)
        ):
            continue
        if "texmf-dist/" in rest:
            candidates.append((package_name, rest.strip()))
            pending_package = None
            continue
        if not rest.strip():
            pending_package = package_name
            continue
        pending_package = None
    return candidates


def package_from_tlmgr_search(output: str) -> str | None:
    packages = {package for package, _ in tlmgr_search_candidates(output)}
    return next(iter(packages)) if len(packages) == 1 else None


def _tlmgr_search_chunks(file_names: list[str]) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_length = 0
    for file_name in file_names:
        escaped_length = len(re.escape(file_name.replace("\\", "/"))) + 1
        if current and (
            len(current) >= TLMGR_SEARCH_CHUNK_FILES
            or current_length + escaped_length > TLMGR_SEARCH_PATTERN_CHARACTERS
        ):
            chunks.append(current)
            current = []
            current_length = 0
        current.append(file_name)
        current_length += escaped_length
    if current:
        chunks.append(current)
    return chunks


def _tlmgr_search_pattern(file_names: list[str]) -> str:
    escaped = [re.escape(name.replace("\\", "/").lstrip("/")) for name in file_names]
    return f"/(?:{'|'.join(escaped)})$"


def _packages_for_searched_files(
    file_names: list[str], output: str
) -> dict[str, str]:
    candidates = tlmgr_search_candidates(output)
    resolved: dict[str, str] = {}
    for file_name in file_names:
        normalized = file_name.replace("\\", "/").lstrip("/")
        packages = {
            package
            for package, path in candidates
            if path.replace("\\", "/").endswith(f"/{normalized}")
        }
        if len(packages) == 1:
            resolved[file_name] = next(iter(packages))
    return resolved


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
    uncached: list[str] = []

    for missing_file in dict.fromkeys(missing_files):
        if is_explicit_local_reference(missing_file):
            continue
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
        uncached.append(missing_file)

    for chunk in _tlmgr_search_chunks(uncached):
        result = run_command(
            [
                managed_tool(root, "tlmgr"),
                "--repository",
                load_runtime_manifest().repository,
                "search",
                "--global",
                "--file",
                _tlmgr_search_pattern(chunk),
            ],
            reporter=reporter,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        _report_tlmgr_failure(result, reporter)
        searched = _packages_for_searched_files(chunk, result.stdout)
        for missing_file, package in searched.items():
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
            managed_tool(root, "tlmgr"),
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
    if managed_executable(root, engine):
        return
    package = TINYTEX_ENGINE_PACKAGES.get(engine)
    if package is None:
        raise TexMiniError(
            f"Error: TinyTeX does not provide {engine} at {root}. "
            f"Delete {root} and run texmini install-tinytex to recreate it."
        )
    reporter.status(f"Installing the {engine} engine...")
    result = install_tinytex_packages(root, [package], env, reporter)
    if result.returncode != 0:
        raise TexMiniError(f"Error: TinyTeX could not install the {engine} engine.")
    if managed_executable(root, engine) is None:
        raise TexMiniError(
            f"Error: TinyTeX installed {package}, but did not provide {engine}."
        )
