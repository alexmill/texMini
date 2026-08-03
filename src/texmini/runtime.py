import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from texmini import __version__

from .model import TexMiniError
from .project import analyze_source_requirements, project_source_files
from .reporting import Reporter, run_command

if TYPE_CHECKING:
    import tarfile


TINYTEX_RELEASE_API = (
    "https://api.github.com/repos/rstudio/tinytex-releases/releases/latest"
)
DEFAULT_TINYTEX_BUNDLE = "TinyTeX-0"
TINYTEX_BOOTSTRAP_PACKAGES = ["latex-bin", "latexmk", "metafont", "mfware"]
TINYTEX_ENGINE_PACKAGES = {"xelatex": "xetex"}
DIRECT_TOOL_PACKAGES = {
    "biber": "biber",
    "bibtex": "bibtex",
    "makeglossaries": "glossaries",
    "makeindex": "makeindex",
    "xindy": "xindy",
}
COMMON_TEXLIVE_FILE_PACKAGES = {
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
    for directory in env.get("PATH", os.defpath).split(os.pathsep):
        candidate = os.path.join(directory or ".", command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


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
        if (path / executable).exists():
            return path
    raise TexMiniError(
        f"Error: TinyTeX does not provide {executable} at {root}. Run: texmini install-tinytex"
    )


def tinytex_env(root: Path, executable: str = "latexmk") -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = tinytex_bin_dir(root, executable)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["LATEXMKRCSYS"] = os.fspath(Path(__file__).with_name("texmini_latexmkrc"))
    return env


def tinytex_bundle() -> str:
    return os.environ.get("TEXMINI_TINYTEX_BUNDLE", DEFAULT_TINYTEX_BUNDLE)


def tinytex_platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        machine = platform.machine().lower()
        if machine in {"aarch64", "arm64"}:
            return "linux-arm64"
        libc = platform.libc_ver()[0].lower()
        return "linuxmusl-x86_64" if libc == "musl" else "linux-x86_64"
    raise TexMiniError(
        "Error: The Python TinyTeX installer currently supports macOS and Linux."
    )


def latest_tinytex_asset() -> tuple[str, str, str | None]:
    import json
    import urllib.request

    bundle = tinytex_bundle()
    prefix = f"{bundle}-{tinytex_platform_key()}-"
    request = urllib.request.Request(
        TINYTEX_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"texmini/{__version__}",
        },
    )
    if github_token := os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {github_token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    for asset in release["assets"]:
        name = asset["name"]
        if name.startswith(prefix) and name.endswith(".tar.xz"):
            return name, asset["browser_download_url"], asset.get("digest")
    raise TexMiniError(f"Error: No {bundle} TinyTeX archive found for this platform.")


def update_tinytex_manager(root: Path, reporter: Reporter) -> None:
    env = tinytex_env(root, "tlmgr")
    if reporter.verbose:
        reporter.status("Updating the managed TinyTeX package manager...")
    update_result = run_command(
        ["tlmgr", "update", "--self"], reporter=reporter, env=env, check=False
    )
    if update_result.returncode != 0:
        raise TexMiniError("Error: TinyTeX package manager bootstrap failed.")


def bootstrap_tinytex(root: Path, reporter: Reporter) -> None:
    update_tinytex_manager(root, reporter)
    env = tinytex_env(root, "tlmgr")
    reporter.status("Installing the LaTeX compiler...")
    install_result = run_command(
        ["tlmgr", "install", *TINYTEX_BOOTSTRAP_PACKAGES],
        reporter=reporter,
        env=env,
        check=False,
    )
    if install_result.returncode != 0:
        raise TexMiniError("Error: TinyTeX bootstrap package installation failed.")
    tinytex_bin_dir(root)


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


def install_tinytex_archive(root: Path, reporter: Reporter | None = None) -> None:
    import hashlib
    import shutil
    import tarfile
    import tempfile
    import urllib.request

    reporter = reporter or Reporter()
    if executable_on_path("perl") is None:
        raise TexMiniError(
            "Error: Perl is required to install and run TinyTeX. Install Perl and retry."
        )
    if (root / "bin").exists():
        if tinytex_bundle() == "TinyTeX-0":
            try:
                tinytex_bin_dir(root)
            except TexMiniError:
                bootstrap_tinytex(root, reporter)
        else:
            tinytex_bin_dir(root)
        return

    reporter.status(f"Preparing a private TinyTeX runtime in {display_path(root)}.")
    reporter.status(
        "This one-time setup requires a network connection and may take a minute."
    )
    name, url, digest = latest_tinytex_asset()
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".texmini-extract-", dir=root.parent
    ) as temporary_directory:
        extraction_root = Path(temporary_directory)
        archive_path = extraction_root / name
        if reporter.verbose:
            reporter.status(f"Downloading {url}")
        with (
            urllib.request.urlopen(url, timeout=60) as response,
            archive_path.open("wb") as archive,
        ):
            shutil.copyfileobj(response, archive)
        if digest and digest.startswith("sha256:"):
            expected = digest.removeprefix("sha256:")
            checksum = hashlib.sha256()
            with archive_path.open("rb") as archive:
                for chunk in iter(lambda: archive.read(1024 * 1024), b""):
                    checksum.update(chunk)
            actual = checksum.hexdigest()
            if actual != expected:
                raise TexMiniError(f"Error: Checksum verification failed for {name}.")
            if reporter.verbose:
                reporter.status(f"Verified SHA-256: {actual}")
        reporter.status(f"Downloaded {tinytex_bundle()}.")
        if reporter.verbose:
            reporter.status(f"Extracting {name}...")
        with tarfile.open(archive_path, mode="r:xz") as tar:
            for member in tar:
                validate_tinytex_archive_member(member)
                tar.extract(member, extraction_root)
        extracted_root = next(
            (
                candidate
                for root_name in ("TinyTeX", ".TinyTeX")
                if (candidate := extraction_root / root_name).exists()
            ),
            None,
        )
        if extracted_root is None:
            raise TexMiniError(
                "Error: TinyTeX archive did not contain a TinyTeX runtime."
            )
        extracted_root.rename(root)
    if tinytex_bundle() == "TinyTeX-0":
        bootstrap_tinytex(root, reporter)
    else:
        update_tinytex_manager(root, reporter)
    tinytex_bin_dir(root)


def install_tinytex(verbose: bool = False) -> int:
    reporter = Reporter(verbose)
    try:
        install_tinytex_archive(tinytex_root(), reporter)
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
        ["kpsewhich", *search_files],
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
    env = tinytex_env(root) if env is None else env
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
            ["tlmgr", "search", "--global", "--file", f"/{missing_file}"],
            reporter=reporter,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
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
    env = tinytex_env(root) if env is None else env
    return run_command(
        ["tlmgr", "install", *packages], reporter=reporter, env=env, check=False
    )


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
