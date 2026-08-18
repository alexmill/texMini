from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import statistics
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterable

from texmini import __version__
from texmini import runtime


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FUNCTIONAL_FIXTURES = [
    "simple",
    "lualatex",
    "xelatex",
    "bibtex",
    "biber",
    "index",
    "glossary",
    "glossary-xindy",
    "glossaries-extra",
    "nomenclature",
    "minted",
    "beamer",
    "multifile",
    "custom-layout-synctex",
]
PACKAGE_POOL = [
    "adjustbox",
    "booktabs",
    "caption",
    "cleveref",
    "enumitem",
    "fancyhdr",
    "float",
    "framed",
    "listings",
    "mathtools",
    "microtype",
    "multirow",
    "parskip",
    "setspace",
    "siunitx",
    "subcaption",
    "tabularx",
    "titlesec",
    "todonotes",
    "wrapfig",
    "xcolor",
]


@dataclass(frozen=True)
class Fixture:
    tex_file: str
    arguments: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()


FUNCTIONAL_FIXTURES = {
    "simple": ("simple", Fixture("simple.tex", required_artifacts=("simple.pdf",))),
    "lualatex": (
        "engine-directives",
        Fixture("lualatex.tex", required_artifacts=("lualatex.pdf",)),
    ),
    "xelatex": (
        "engine-directives",
        Fixture("xelatex.tex", required_artifacts=("xelatex.pdf",)),
    ),
    "bibtex": (
        "bibtex",
        Fixture("paper.tex", required_artifacts=("paper.pdf", "paper.bbl")),
    ),
    "biber": (
        "bibliography",
        Fixture(
            "bibliography.tex",
            required_artifacts=("bibliography.pdf", "bibliography.bbl"),
        ),
    ),
    "index": (
        "index",
        Fixture("index.tex", required_artifacts=("index.pdf", "index.ind", "people.ind")),
    ),
    "glossary": (
        "glossary",
        Fixture(
            "glossary.tex",
            required_artifacts=("glossary.pdf", "glossary.gls", "glossary.acr"),
        ),
    ),
    "glossary-xindy": (
        "glossary-xindy",
        Fixture("glossary.tex", required_artifacts=("glossary.pdf", "glossary.gls")),
    ),
    "glossaries-extra": (
        "glossaries-extra",
        Fixture("glossary.tex", required_artifacts=("glossary.pdf", "glossary.gls")),
    ),
    "nomenclature": (
        "nomenclature",
        Fixture(
            "nomenclature.tex",
            required_artifacts=("nomenclature.pdf", "nomenclature.nls"),
        ),
    ),
    "minted": (
        "minted",
        Fixture(
            "minted.tex", ("--shell-escape",), required_artifacts=("minted.pdf",)
        ),
    ),
    "beamer": (
        "beamer",
        Fixture("slides.tex", required_artifacts=("slides.pdf",)),
    ),
    "multifile": (
        "multifile",
        Fixture(
            "main.tex",
            required_artifacts=(
                "build/publication.pdf",
                "aux/publication.bbl",
            ),
        ),
    ),
}


def sample_poisson(rng: random.Random, mean: float) -> int:
    threshold = 2.718281828459045**-mean
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def sample_overdispersed_count(
    rng: random.Random, mean: float, dispersion: float
) -> int:
    return sample_poisson(rng, rng.gammavariate(dispersion, mean / dispersion))


def random_package_selection(seed: int = 20260714, count: int = 10) -> list[str]:
    return random.Random(seed).sample(PACKAGE_POOL, count)


def bibliography_entry_count(seed: int = 20260714) -> int:
    return max(
        8, sample_overdispersed_count(random.Random(seed), mean=32.0, dispersion=3.0)
    )


def write_fixture(name: str, destination: Path) -> Fixture:
    destination.mkdir(parents=True, exist_ok=True)
    if name in FUNCTIONAL_FIXTURES:
        source_name, fixture = FUNCTIONAL_FIXTURES[name]
        shutil.copytree(
            ROOT / "tests" / "fixtures" / source_name,
            destination,
            dirs_exist_ok=True,
        )
        return fixture

    tex_file = destination / f"{name}.tex"
    if name == "common":
        tex_file.write_text(
            """\\documentclass{article}
\\usepackage{amsmath,amssymb,booktabs,enumitem,geometry,mathtools,microtype,siunitx}
\\usepackage{xcolor,hyperref,tikz}
\\begin{document}
\\section{Common packages}
\\begin{itemize}[label=--]
\\item A measured value is \\SI{9.81}{\\metre\\per\\second\\squared}.
\\item The identity $e^{i\\pi}+1=0$ exercises the math stack.
\\end{itemize}
\\begin{tabular}{lr}\\toprule Item & Value \\\\ \\midrule Alpha & 1 \\\\ Beta & 2 \\\\ \\bottomrule\\end{tabular}
\\begin{tikzpicture}\\draw[blue,thick] (0,0) -- (2,1);\\end{tikzpicture}
\\end{document}
""",
            encoding="utf-8",
        )
        return Fixture(tex_file.name)
    if name == "random-packages":
        packages = ",".join(random_package_selection())
        tex_file.write_text(
            f"""\\documentclass{{article}}
\\usepackage{{{packages}}}
\\begin{{document}}
The package sample is selected from a fixed seed.
\\end{{document}}
""",
            encoding="utf-8",
        )
        return Fixture(tex_file.name)
    if name == "bibliography-generated":
        count = bibliography_entry_count()
        keys = [f"entry{index:03d}" for index in range(count)]
        (destination / "references.bib").write_text(
            "\n\n".join(
                "\n".join(
                    [
                        f"@article{{{key},",
                        f"  title = {{Generated benchmark article {index}}},",
                        "  author = {Author, Example and Collaborator, Sample},",
                        "  journal = {Benchmark Studies},",
                        f"  year = {{{2000 + index % 25}}}",
                        "}",
                    ]
                )
                for index, key in enumerate(keys)
            )
            + "\n",
            encoding="utf-8",
        )
        citations = "\n".join(
            f"Citation {index + 1}: \\cite{{{key}}}." for index, key in enumerate(keys)
        )
        tex_file.write_text(
            f"""\\documentclass{{article}}
\\usepackage[backend=biber,style=authoryear]{{biblatex}}
\\usepackage{{csquotes}}
\\addbibresource{{references.bib}}
\\begin{{document}}
{citations}
\\printbibliography
\\end{{document}}
""",
            encoding="utf-8",
        )
        return Fixture(tex_file.name)
    if name == "package-one":
        tex_file.write_text(
            "\\documentclass{article}\n\\usepackage{verse}\n"
            "\\begin{document}One package.\\end{document}\n",
            encoding="utf-8",
        )
        return Fixture(tex_file.name)
    if name == "package-many":
        tex_file.write_text(
            "\\documentclass{article}\n"
            "\\usepackage{adjustbox,enumitem,parskip,todonotes,wrapfig}\n"
            "\\begin{document}Many independently mapped packages.\\end{document}\n",
            encoding="utf-8",
        )
        return Fixture(tex_file.name)
    if name == "custom-layout-synctex":
        source = ROOT / "tests" / "fixtures" / "simple" / "simple.tex"
        shutil.copy2(source, tex_file)
        return Fixture(
            tex_file.name,
            ("-outdir=build", "-auxdir=aux", "-jobname=publication", "-synctex=1"),
            (
                "build/publication.pdf",
                "aux/publication.synctex.gz|build/publication.synctex.gz",
            ),
        )
    if name == "failure":
        tex_file.write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            "\\definitelyundefined\n\\end{document}\n",
            encoding="utf-8",
        )
        return Fixture(tex_file.name)
    if name == "incomplete":
        tex_file.write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            "See \\ref{missing-label}.\n\\end{document}\n",
            encoding="utf-8",
        )
        return Fixture(tex_file.name)
    raise ValueError(f"Unknown fixture: {name}")


def directory_sizes(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "logical_bytes": 0,
            "allocated_bytes": 0,
            "allocated_backend": "st_blocks" if os.name == "posix" else "logical_fallback",
            "regular_files": 0,
        }
    logical = 0
    allocated = 0
    regular_files = 0
    seen_files: set[tuple[int, int]] = set()
    for entry in path.rglob("*"):
        if not entry.is_file():
            continue
        stat_result = entry.stat()
        identity = (stat_result.st_dev, stat_result.st_ino)
        if identity in seen_files:
            continue
        seen_files.add(identity)
        regular_files += 1
        logical += stat_result.st_size
        allocated += getattr(
            stat_result, "st_blocks", (stat_result.st_size + 511) // 512
        ) * 512
    return {
        "logical_bytes": logical,
        "allocated_bytes": allocated,
        "allocated_backend": "st_blocks" if os.name == "posix" else "logical_fallback",
        "regular_files": regular_files,
    }


def directory_size(path: Path, allocated: bool = False) -> int:
    sizes = directory_sizes(path)
    return int(sizes["allocated_bytes" if allocated else "logical_bytes"])


def directory_content_identity(path: Path) -> dict[str, object]:
    """Hash runtime-relevant paths, permissions, links, and file contents."""
    digest = hashlib.sha256()
    if not path.exists():
        digest.update(b"missing\0")
        return {
            "schema_version": 1,
            "sha256": digest.hexdigest(),
            "paths": 0,
            "unique_regular_files": 0,
        }

    content_hashes: dict[tuple[int, int], bytes] = {}
    paths = 0
    for entry in sorted(path.rglob("*"), key=lambda item: os.fsencode(item.relative_to(path))):
        relative = os.fsencode(entry.relative_to(path))
        try:
            entry_stat = entry.lstat()
        except OSError:
            continue
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(stat.S_IMODE(entry_stat.st_mode)).encode("ascii"))
        digest.update(b"\0")
        if entry.is_symlink():
            digest.update(b"link\0")
            digest.update(os.fsencode(os.readlink(entry)))
        elif entry.is_file():
            digest.update(b"file\0")
            identity = (entry_stat.st_dev, entry_stat.st_ino)
            content_digest = content_hashes.get(identity)
            if content_digest is None:
                file_digest = hashlib.sha256()
                with entry.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        file_digest.update(chunk)
                content_digest = file_digest.digest()
                content_hashes[identity] = content_digest
            digest.update(content_digest)
        elif entry.is_dir():
            digest.update(b"directory\0")
        else:
            digest.update(b"other\0")
        digest.update(b"\0")
        paths += 1
    return {
        "schema_version": 1,
        "sha256": digest.hexdigest(),
        "paths": paths,
        "unique_regular_files": len(content_hashes),
    }


def runtime_package_inventory(path: Path) -> dict[str, object]:
    """Return a stable installed-package identity from TeX Live's database."""
    database = path / "tlpkg" / "texlive.tlpdb"
    try:
        lines = database.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as error:
        raise RuntimeError(
            f"Could not read installed-package inventory at {database}: {error}"
        ) from error

    packages: list[dict[str, str | None]] = []
    current_name: str | None = None
    current_revision: str | None = None

    def append_current() -> None:
        if current_name is not None:
            packages.append(
                {"name": current_name, "revision": current_revision}
            )

    for line in lines:
        if line.startswith("name "):
            append_current()
            current_name = line.removeprefix("name ").strip()
            current_revision = None
        elif current_name is not None and line.startswith("revision "):
            current_revision = line.removeprefix("revision ").strip()
    append_current()
    packages.sort(key=lambda item: str(item["name"]))
    if not packages:
        raise RuntimeError(f"No installed packages found in {database}")
    canonical = json.dumps(
        packages, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "package_count": len(packages),
        "source": "tlpkg/texlive.tlpdb name+revision records",
        "packages": packages,
    }


def tinytex_bundle_name(filename: str) -> str:
    match = re.match(r"^(TinyTeX(?:-\d+)?)-", filename)
    if match is None:
        raise RuntimeError(f"Cannot identify the TinyTeX bundle from {filename!r}")
    return match.group(1)


def tinytex_asset() -> tuple[str, int]:
    """Return the expected archive size without touching the timed pre-run path."""
    manifest = runtime.load_runtime_manifest()
    platform_key = runtime.tinytex_platform_key()
    try:
        asset = manifest.assets[platform_key]
    except KeyError as error:
        raise RuntimeError(
            f"The pinned runtime manifest has no asset for {platform_key}"
        ) from error
    request = urllib.request.Request(
        runtime.tinytex_asset_url(manifest, asset), method="HEAD"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content_length = response.headers.get("Content-Length")
    if content_length is None:
        raise RuntimeError(f"No Content-Length reported for {asset.filename}")
    return asset.filename, int(content_length)


def _command_output(command: list[str], cwd: Path = ROOT) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _candidate_version(target_root: Path) -> str:
    env = dict(os.environ)
    source_path = os.fspath(target_root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing}" if existing else source_path
    )
    result = subprocess.run(
        [sys.executable, "-c", "import texmini; print(texmini.__version__)"],
        cwd=target_root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not read candidate version:\n{result.stdout}")
    return result.stdout.strip()


def _candidate_runtime_manifest(target_root: Path) -> dict[str, object]:
    """Read the manifest through the candidate checkout, not the harness checkout."""
    env = dict(os.environ)
    source_path = os.fspath(target_root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{existing}" if existing else source_path
    )
    script = """
import json
from texmini import runtime

manifest = runtime.load_runtime_manifest()
platform_key = runtime.tinytex_platform_key()
asset = manifest.assets[platform_key]
print(json.dumps({
    "schema_version": manifest.schema_version,
    "tinytex_version": manifest.tinytex_version,
    "repository": manifest.repository,
    "platform_key": platform_key,
    "asset": asset.filename,
    "asset_sha256": asset.sha256,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=target_root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read candidate runtime manifest:\n{result.stdout}"
        )
    try:
        manifest = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Candidate runtime manifest returned invalid JSON:\n{result.stdout}"
        ) from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("asset"), str):
        raise RuntimeError("Candidate runtime manifest metadata is incomplete")
    manifest_path = target_root / "src" / "texmini" / "runtime_manifest.json"
    try:
        manifest["manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
    except OSError as error:
        raise RuntimeError(
            f"Could not hash candidate runtime manifest at {manifest_path}: {error}"
        ) from error
    manifest["bundle"] = tinytex_bundle_name(str(manifest["asset"]))
    return manifest


def _prepare_explicit_workspace(path: Path) -> Path:
    """Create an explicit workspace, refusing stale state from an earlier run."""
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    try:
        occupied = next(path.iterdir())
    except StopIteration:
        return path
    raise SystemExit(
        f"--workspace must be empty; found existing entry {occupied.name!r} in {path}"
    )


def _referenced_raw_path(output: Path) -> Path | None:
    try:
        existing = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = existing.get("raw_samples") if isinstance(existing, dict) else None
    if not isinstance(name, str) or Path(name).name != name:
        return None
    return output.parent / name


def publish_result_pair(
    output: Path, raw_path: Path, results: dict[str, object]
) -> None:
    previous_raw = _referenced_raw_path(output)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    staged_output = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged_output, output)
    except BaseException:
        staged_output.unlink(missing_ok=True)
        raise
    if (
        previous_raw is not None
        and previous_raw != raw_path
        and previous_raw.parent == output.parent
    ):
        previous_raw.unlink(missing_ok=True)


def _git_metadata(target_root: Path) -> dict[str, object]:
    commit = _command_output(["git", "rev-parse", "HEAD"], target_root)
    status = _command_output(["git", "status", "--porcelain"], target_root)
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=target_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout
    tree_digest = hashlib.sha256()
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=target_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout
    included_files = 0
    for encoded_name in sorted(name for name in listed.split(b"\0") if name):
        name = os.fsdecode(encoded_name)
        if (
            name == "benchmarks/results"
            or name.startswith("benchmarks/results/")
            or name == "docs/performance-report.md"
        ):
            continue
        path = target_root / name
        try:
            path_stat = path.lstat()
        except OSError:
            continue
        tree_digest.update(encoded_name)
        tree_digest.update(b"\0")
        tree_digest.update(str(stat.S_IMODE(path_stat.st_mode)).encode("ascii"))
        tree_digest.update(b"\0")
        if path.is_symlink():
            tree_digest.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    tree_digest.update(chunk)
        tree_digest.update(b"\0")
        included_files += 1
    return {
        "commit": commit,
        "dirty": bool(status),
        "status": status.splitlines() if status else [],
        "working_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "tree_content_sha256": tree_digest.hexdigest(),
        "tree_content_file_count": included_files,
        "tree_content_excludes": [
            "benchmarks/results/",
            "docs/performance-report.md",
        ],
        "tree_content_exclusion_reason": (
            "Machine results and their derived human report are outputs, not "
            "candidate inputs."
        ),
    }


def _host_metadata(measurement_path: Path = ROOT) -> dict[str, object]:
    filesystem = None
    if sys.platform == "darwin":
        filesystem = _command_output(
            ["stat", "-f", "%T", os.fspath(measurement_path)]
        )
    elif sys.platform.startswith("linux"):
        filesystem = _command_output(
            ["stat", "-f", "-c", "%T", os.fspath(measurement_path)]
        )
    cpu = None
    if sys.platform == "darwin":
        cpu = _command_output(["sysctl", "-n", "machdep.cpu.brand_string"])
    elif os.name == "nt":
        cpu = os.environ.get("PROCESSOR_IDENTIFIER")
    elif Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.lower().startswith("model name"):
                cpu = line.partition(":")[2].strip()
                break
    total_memory = None
    try:
        total_memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        pass
    filesystem_type = None
    filesystem_mount = None
    try:
        import psutil

        resolved_root = measurement_path.resolve()
        matches = []
        for partition in psutil.disk_partitions(all=True):
            try:
                resolved_root.relative_to(Path(partition.mountpoint).resolve())
            except (OSError, ValueError):
                continue
            matches.append(partition)
        if matches:
            partition = max(matches, key=lambda item: len(item.mountpoint))
            filesystem_type = partition.fstype or None
            filesystem_mount = partition.mountpoint
    except ImportError:
        pass

    dependency_versions = {}
    for distribution in ("psutil", "Pygments"):
        try:
            dependency_versions[distribution] = version(distribution)
        except PackageNotFoundError:
            dependency_versions[distribution] = None
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu": cpu,
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": total_memory,
        "filesystem": filesystem,
        "filesystem_type": filesystem_type,
        "filesystem_mount": filesystem_mount,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "uv": _command_output(["uv", "--version"]),
        "dependency_versions": dependency_versions,
        "timezone": time.tzname,
    }


def _clone_tree(source: Path, destination: Path) -> str:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    commands: list[tuple[list[str], str]] = []
    if sys.platform == "darwin":
        commands.append((["cp", "-cR", os.fspath(source), os.fspath(destination)], "apfs_clone"))
    elif sys.platform.startswith("linux"):
        commands.append(
            (["cp", "--reflink=auto", "-a", os.fspath(source), os.fspath(destination)], "reflink_auto")
        )
    for command, backend in commands:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return backend
    shutil.copytree(source, destination, symlinks=True)
    return "shutil_copytree"


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _returncode_matches(actual: object, expected: object) -> bool:
    if expected == "nonzero":
        return isinstance(actual, int) and actual != 0
    return actual == expected


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def summarize_samples(samples: Iterable[dict[str, object]]) -> dict[str, object]:
    valid = [
        sample
        for sample in samples
        if not sample.get("instrumented")
        and sample.get("semantic_success")
        and _returncode_matches(
            sample.get("returncode"), sample.get("expected_returncode")
        )
    ]
    wall = [int(sample["wall_time_ns"]) for sample in valid]
    if not wall:
        return {"valid_samples": 0}
    median = int(statistics.median(wall))
    deviations = [abs(value - median) for value in wall]
    resources = [sample.get("resources", {}) for sample in valid]
    cpu = [
        int(resource["user_cpu_ns"]) + int(resource["system_cpu_ns"])
        for resource in resources
        if isinstance(resource, dict)
        and resource.get("user_cpu_ns") is not None
        and resource.get("system_cpu_ns") is not None
    ]
    rss = [
        int(resource["peak_child_rss_bytes"])
        for resource in resources
        if isinstance(resource, dict) and resource.get("peak_child_rss_bytes") is not None
    ]
    tree_rss = [
        int(process_tree["peak_tree_rss_bytes"])
        for sample in valid
        if isinstance((process_tree := sample.get("process_tree", {})), dict)
        and isinstance(process_tree.get("peak_tree_rss_bytes"), int)
        and int(process_tree["peak_tree_rss_bytes"]) > 0
    ]
    complete_tree_rss = len(tree_rss) == len(valid)
    alternate_a = wall[::2]
    alternate_b = wall[1::2]
    aa_delta = None
    if alternate_a and alternate_b:
        aa_delta = abs(statistics.median(alternate_a) - statistics.median(alternate_b))
    return {
        "valid_samples": len(valid),
        "wall_time_ns": {
            "median": median,
            "mad": int(statistics.median(deviations)),
            "min": min(wall),
            "max": max(wall),
            "p95": _percentile(wall, 0.95),
            "aa_alternating_median_delta": int(aa_delta) if aa_delta is not None else None,
        },
        "cpu_time_ns_median": int(statistics.median(cpu)) if cpu else None,
        "peak_child_rss_bytes_median": int(statistics.median(rss)) if rss else None,
        "peak_tree_rss_bytes_median": (
            int(statistics.median(tree_rss)) if complete_tree_rss else None
        ),
        "peak_tree_rss_valid_samples": len(tree_rss),
    }


def _trace_summary(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"events": 0}
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    phase_ns: dict[str, int] = {}
    downloads: dict[str, int] = {}
    subprocesses: dict[str, int] = {}
    for event in events:
        name = str(event.get("name"))
        phase_ns[name] = phase_ns.get(name, 0) + int(event.get("duration_ns", 0))
        if name == "download_and_sha256":
            category = str(event.get("category", "unknown"))
            downloads[category] = downloads.get(category, 0) + int(
                event.get("response_body_bytes", 0)
            )
        if name == "subprocess":
            command = str(event.get("command", "unknown"))
            subprocesses[command] = subprocesses.get(command, 0) + 1
    return {
        "events": len(events),
        "phase_time_ns": dict(sorted(phase_ns.items())),
        "direct_subprocesses": dict(sorted(subprocesses.items())),
        "direct_subprocess_count": sum(subprocesses.values()),
        "response_body_bytes": dict(sorted(downloads.items())),
    }


def environment_request(env: dict[str, str]) -> dict[str, object]:
    """Serialize only changes to the worker's inherited environment."""
    return {
        "env_overrides": {
            key: value for key, value in env.items() if os.environ.get(key) != value
        },
        "env_unset": sorted(key for key in os.environ if key not in env),
    }


class Supervisor:
    def __init__(
        self,
        target_root: Path,
        workspace: Path,
        raw_path: Path,
        candidate_id: str,
        retain_artifacts: bool = False,
    ) -> None:
        self.target_root = target_root
        self.workspace = workspace
        self.raw_path = raw_path
        self.candidate_id = candidate_id
        self.retain_artifacts = retain_artifacts
        self.samples: list[dict[str, object]] = []
        self._sample_number = 0

    def environment(
        self, runtime_root: Path, package_map: Path, trace_path: Path | None = None
    ) -> dict[str, str]:
        source_path = self.target_root / "src"
        existing = os.environ.get("PYTHONPATH")
        env = {
            **os.environ,
            "PYTHONPATH": (
                f"{source_path}{os.pathsep}{existing}" if existing else os.fspath(source_path)
            ),
            "TEXMINI_TINYTEX_ROOT": os.fspath(runtime_root),
            "TEXMINI_PACKAGE_MAP": os.fspath(package_map),
        }
        env.pop("TEXMINI_TRACE", None)
        if trace_path is not None:
            env["TEXMINI_TRACE"] = os.fspath(trace_path)
        return env

    def command(self, fixture: Fixture | None = None) -> list[str]:
        command = [sys.executable, "-m", "texmini.cli"]
        if fixture is not None:
            command.extend(fixture.arguments)
            command.append(fixture.tex_file)
        return command

    def run(
        self,
        scenario: str,
        state: str,
        iteration: int,
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        expected_returncode: int | str = 0,
        require_pdf: bool = False,
        required_artifacts: tuple[str, ...] = (),
        required_output: tuple[str, ...] = (),
        required_changed_artifacts: dict[str, str] | None = None,
        instrumented: bool = False,
        network_dependency: str | None = None,
        notes: str | None = None,
    ) -> dict[str, object]:
        self._sample_number += 1
        stem = f"{self._sample_number:04d}-{scenario}-{state}-{iteration}"
        log_path = self.workspace / "logs" / f"{stem}.log"
        trace_path = self.workspace / "traces" / f"{stem}.jsonl"
        if instrumented:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            env = {**env, "TEXMINI_TRACE": os.fspath(trace_path)}
        request = {
            "command": command,
            "cwd": os.fspath(cwd),
            "output_path": os.fspath(log_path),
            **environment_request(env),
        }
        request_path = self.workspace / "worker" / f"{stem}-request.json"
        result_path = self.workspace / "worker" / f"{stem}-result.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps(request), encoding="utf-8")
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.command_worker",
                "--request",
                os.fspath(request_path),
                "--result",
                os.fspath(result_path),
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": os.fspath(ROOT)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if worker.returncode != 0 or not result_path.is_file():
            raise RuntimeError(f"Measurement worker failed: {worker.stdout}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        pdf_exists = any(cwd.rglob("*.pdf")) if require_pdf else None
        artifact_checks = {
            requirement: any(
                (cwd / alternative).is_file()
                for alternative in requirement.split("|")
            )
            for requirement in required_artifacts
        }
        output_text = log_path.read_text(encoding="utf-8", errors="replace")
        output_checks = {
            requirement: requirement in output_text for requirement in required_output
        }
        changed_artifact_evidence: dict[str, dict[str, object]] = {}
        for relative, before_sha256 in (required_changed_artifacts or {}).items():
            artifact = cwd / relative
            after_sha256 = _file_sha256(artifact) if artifact.is_file() else None
            changed_artifact_evidence[relative] = {
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
                "changed": after_sha256 is not None and after_sha256 != before_sha256,
            }
        semantic_success = _returncode_matches(
            result["returncode"], expected_returncode
        ) and (not require_pdf or bool(pdf_exists))
        semantic_success = (
            semantic_success
            and all(artifact_checks.values())
            and all(output_checks.values())
            and all(
                bool(evidence["changed"])
                for evidence in changed_artifact_evidence.values()
            )
        )
        sample = {
            "candidate_id": self.candidate_id,
            "scenario": scenario,
            "state": state,
            "iteration": iteration,
            "expected_returncode": expected_returncode,
            "semantic_success": semantic_success,
            "instrumented": instrumented,
            "semantic_assertions": {
                "required_pdf": require_pdf,
                "required_artifacts": artifact_checks,
                "required_output": output_checks,
                "required_changed_artifacts": changed_artifact_evidence,
            },
            "network": {
                "dependent": network_dependency is not None,
                "control": "uncontrolled" if network_dependency else "not expected",
                "source": network_dependency,
            },
            "notes": notes,
            "log": (
                os.fspath(log_path.relative_to(self.workspace))
                if self.retain_artifacts
                else None
            ),
            "trace": (
                os.fspath(trace_path.relative_to(self.workspace))
                if instrumented and self.retain_artifacts
                else None
            ),
            **result,
        }
        if instrumented:
            sample["trace_summary"] = _trace_summary(trace_path)
        self.samples.append(sample)
        with self.raw_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample, sort_keys=True) + "\n")
        status = "ok" if semantic_success else "FAILED"
        print(
            f"  {scenario}/{state} #{iteration}: "
            f"{result['wall_time_ns'] / 1_000_000:.1f} ms ({status})",
            flush=True,
        )
        return sample


def _scenario_summary(samples: list[dict[str, object]]) -> dict[str, object]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for sample in samples:
        key = (str(sample["scenario"]), str(sample["state"]))
        grouped.setdefault(key, []).append(sample)
    return {
        f"{scenario}/{state}": summarize_samples(group)
        for (scenario, state), group in sorted(grouped.items())
    }


def _measure_startup(
    supervisor: Supervisor,
    runtime_root: Path,
    package_map: Path,
    repeats: int,
) -> None:
    env = supervisor.environment(runtime_root, package_map)
    print("Measuring source-command startup", flush=True)
    for scenario, option in (("startup_version", "--version"), ("startup_help", "--help")):
        for iteration in range(1, repeats + 1):
            supervisor.run(
                scenario,
                "source_tree_managed_python",
                iteration,
                supervisor.command() + [option],
                ROOT,
                env,
            )
        supervisor.run(
            scenario,
            "source_tree_managed_python",
            repeats + 1,
            supervisor.command() + [option],
            ROOT,
            env,
            instrumented=True,
        )


def _build_wheel(target_root: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", os.fspath(destination), os.fspath(target_root)],
        cwd=target_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    wheels = sorted(destination.glob("*.whl"))
    if result.returncode != 0 or len(wheels) != 1:
        raise RuntimeError(f"uv wheel build failed:\n{result.stdout}")
    return wheels[0]


def _measure_packaging(
    supervisor: Supervisor,
    runtime_root: Path,
    package_map: Path,
    repeats: int,
) -> dict[str, object]:
    print("Measuring uv artifact acquisition and installed startup", flush=True)
    wheel = _build_wheel(supervisor.target_root, supervisor.workspace / "dist")
    uvx_cache = supervisor.workspace / "uvx-cache"
    uvx_env = {
        **os.environ,
        "UV_CACHE_DIR": os.fspath(uvx_cache),
        "UV_PYTHON": sys.executable,
    }
    uvx_command = [
        "uvx",
        "--python",
        sys.executable,
        "--from",
        os.fspath(wheel),
        "texmini",
        "--version",
    ]
    supervisor.run(
        "uvx_startup",
        "artifact_cold_managed_python_present",
        1,
        uvx_command,
        ROOT,
        uvx_env,
        network_dependency="Python package index and uv artifact cache",
        notes="Fresh isolated uv cache; dependency acquisition may use the network.",
    )
    for iteration in range(1, repeats + 1):
        supervisor.run(
            "uvx_startup",
            "artifact_cached",
            iteration,
            uvx_command,
            ROOT,
            uvx_env,
        )

    tool_root = supervisor.workspace / "uv-tools"
    bin_root = supervisor.workspace / "uv-bin"
    tool_cache = supervisor.workspace / "uv-tool-cache"
    tool_env = {
        **os.environ,
        "UV_TOOL_DIR": os.fspath(tool_root),
        "UV_TOOL_BIN_DIR": os.fspath(bin_root),
        "UV_CACHE_DIR": os.fspath(tool_cache),
        "UV_PYTHON": sys.executable,
    }
    supervisor.run(
        "uv_tool_install",
        "artifact_cold_managed_python_present",
        1,
        ["uv", "tool", "install", "--python", sys.executable, os.fspath(wheel)],
        ROOT,
        tool_env,
        network_dependency="Python package index and uv artifact cache",
        notes="Fresh isolated tool directory and uv cache.",
    )
    executable = bin_root / ("texmini.exe" if os.name == "nt" else "texmini")
    installed_env = {
        **tool_env,
        "TEXMINI_TINYTEX_ROOT": os.fspath(runtime_root),
        "TEXMINI_PACKAGE_MAP": os.fspath(package_map),
    }
    supervisor.run(
        "installed_startup",
        "first_after_install",
        1,
        [os.fspath(executable), "--version"],
        ROOT,
        installed_env,
    )
    for iteration in range(1, repeats + 1):
        supervisor.run(
            "installed_startup",
            "warm",
            iteration,
            [os.fspath(executable), "--version"],
            ROOT,
            installed_env,
        )
    return {
        "wheel": {
            "path": wheel.name,
            "bytes": wheel.stat().st_size,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        },
        "uvx_cache": directory_sizes(uvx_cache),
        "uv_tool_directory": directory_sizes(tool_root),
        "uv_tool_bin_directory": directory_sizes(bin_root),
        "managed_python": "preexisting and excluded from tool-directory totals",
    }


def _measure_package_recovery(
    supervisor: Supervisor,
    base_runtime: Path,
    repeats: int,
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for fixture_name in ("package-one", "package-many"):
        populated_map: str | None = None
        for iteration in range(1, repeats + 1):
            runtime_root = supervisor.workspace / "package-runtimes" / f"{fixture_name}-{iteration}"
            clone_backend = _clone_tree(base_runtime, runtime_root)
            project = supervisor.workspace / "package-projects" / f"{fixture_name}-{iteration}"
            fixture = write_fixture(fixture_name, project)
            package_map = project / "package-map.json"
            env = supervisor.environment(runtime_root, package_map)
            sample = supervisor.run(
                "package_recovery",
                f"{fixture_name}_map_cold",
                iteration,
                supervisor.command(fixture),
                project,
                env,
                require_pdf=True,
                instrumented=False,
                network_dependency="TeX Live repository package payloads",
                notes=(
                    "Runtime cloned outside timing from the same base; package network "
                    f"state is uncontrolled; clone backend={clone_backend}."
                ),
            )
            observations.append(sample)
            if populated_map is None and package_map.is_file():
                populated_map = package_map.read_text(encoding="utf-8")
            shutil.rmtree(runtime_root, ignore_errors=True)
        runtime_root = supervisor.workspace / "package-runtimes" / f"{fixture_name}-trace"
        clone_backend = _clone_tree(base_runtime, runtime_root)
        project = supervisor.workspace / "package-projects" / f"{fixture_name}-trace"
        fixture = write_fixture(fixture_name, project)
        package_map = project / "package-map.json"
        sample = supervisor.run(
            "package_recovery",
            f"{fixture_name}_map_cold",
            repeats + 1,
            supervisor.command(fixture),
            project,
            supervisor.environment(runtime_root, package_map),
            require_pdf=True,
            instrumented=True,
            network_dependency="TeX Live repository package payloads",
            notes=(
                "Attribution-only repeat from the same base; package network state is "
                f"uncontrolled; clone backend={clone_backend}."
            ),
        )
        observations.append(sample)
        shutil.rmtree(runtime_root, ignore_errors=True)
        if populated_map is not None:
            for iteration in range(1, repeats + 1):
                runtime_root = (
                    supervisor.workspace
                    / "package-runtimes"
                    / f"{fixture_name}-map-warm-{iteration}"
                )
                clone_backend = _clone_tree(base_runtime, runtime_root)
                project = (
                    supervisor.workspace
                    / "package-projects"
                    / f"{fixture_name}-map-warm-{iteration}"
                )
                fixture = write_fixture(fixture_name, project)
                package_map = project / "package-map.json"
                package_map.write_text(populated_map, encoding="utf-8")
                sample = supervisor.run(
                    "package_recovery",
                    f"{fixture_name}_map_warm",
                    iteration,
                    supervisor.command(fixture),
                    project,
                    supervisor.environment(runtime_root, package_map),
                    require_pdf=True,
                    network_dependency="TeX Live repository package payloads",
                    notes=(
                        "Runtime cloned from the package-absent base and mapping cache "
                        "copied outside timing; network uncontrolled; "
                        f"clone backend={clone_backend}."
                    ),
                )
                observations.append(sample)
                shutil.rmtree(runtime_root, ignore_errors=True)
    return observations


def _provision_functional_runtime(
    supervisor: Supervisor,
    runtime_root: Path,
    package_map: Path,
    fixtures: list[str],
) -> None:
    print("Provisioning functional runtime outside authoritative timings", flush=True)
    for name in fixtures:
        project = supervisor.workspace / "provision" / name
        fixture = write_fixture(name, project)
        result = subprocess.run(
            supervisor.command(fixture),
            cwd=project,
            env=supervisor.environment(runtime_root, package_map),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not any(project.rglob("*.pdf")):
            raise RuntimeError(f"Could not provision {name}:\n{result.stdout[-4000:]}")
        missing = [
            requirement
            for requirement in fixture.required_artifacts
            if not any(
                (project / alternative).is_file()
                for alternative in requirement.split("|")
            )
        ]
        if missing:
            raise RuntimeError(f"Provisioning {name} omitted artifacts: {missing}")


def _fixture_pdf(project: Path, fixture: Fixture) -> Path:
    for requirement in fixture.required_artifacts:
        for alternative in requirement.split("|"):
            candidate = project / alternative
            if candidate.suffix.lower() == ".pdf" and candidate.is_file():
                return candidate
    generated = sorted(project.rglob("*.pdf"))
    if len(generated) != 1:
        raise RuntimeError(
            f"Expected one unambiguous PDF for {fixture.tex_file}, found {generated}"
        )
    return generated[0]


def _apply_visible_incremental_edit(source: Path, iteration: int) -> str:
    text = source.read_text(encoding="utf-8")
    end_document = "\\end{document}"
    insertion_point = text.rfind(end_document)
    if insertion_point < 0:
        raise RuntimeError(f"Cannot insert a visible benchmark edit into {source}")
    marker = f"texMini benchmark visible edit {iteration}"
    if re.search(r"\\documentclass(?:\[[^]]*\])?\{beamer\}", text):
        visible_line = (
            f"\\begin{{frame}}{{Benchmark edit}}{marker}.\\end{{frame}}\n"
        )
    else:
        visible_line = f"\\par\\noindent {marker}.\n"
    source.write_text(
        f"{text[:insertion_point]}{visible_line}{text[insertion_point:]}",
        encoding="utf-8",
    )
    return marker


def _measure_build_states(
    supervisor: Supervisor,
    runtime_root: Path,
    package_map: Path,
    repeats: int,
    fixtures: list[str],
) -> None:
    print("Measuring clean, no-op, and one-line incremental states", flush=True)
    env = supervisor.environment(runtime_root, package_map)
    for name in fixtures:
        for iteration in range(1, repeats + 1):
            project = supervisor.workspace / "clean-projects" / name / str(iteration)
            fixture = write_fixture(name, project)
            supervisor.run(
                f"build_{name}",
                "project_clean_runtime_provisioned",
                iteration,
                supervisor.command(fixture),
                project,
                env,
                require_pdf=True,
                required_artifacts=fixture.required_artifacts,
            )

        project = supervisor.workspace / "stateful-projects" / name
        fixture = write_fixture(name, project)
        setup = subprocess.run(
            supervisor.command(fixture),
            cwd=project,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if setup.returncode != 0:
            raise RuntimeError(f"Could not prepare no-op state for {name}")
        for iteration in range(1, repeats + 1):
            supervisor.run(
                f"build_{name}",
                "project_noop",
                iteration,
                supervisor.command(fixture),
                project,
                env,
                require_pdf=True,
                required_artifacts=fixture.required_artifacts,
            )
        supervisor.run(
            f"build_{name}",
            "project_noop",
            repeats + 1,
            supervisor.command(fixture),
            project,
            env,
            require_pdf=True,
            required_artifacts=fixture.required_artifacts,
            instrumented=True,
        )

        source = project / fixture.tex_file
        baseline_source = source.read_text(encoding="utf-8")
        for iteration in range(1, repeats + 1):
            source.write_text(baseline_source, encoding="utf-8")
            reset = subprocess.run(
                supervisor.command(fixture),
                cwd=project,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if reset.returncode != 0:
                raise RuntimeError(
                    f"Could not reset incremental state for {name}:\n"
                    f"{reset.stdout[-4000:]}"
                )
            pdf = _fixture_pdf(project, fixture)
            previous_pdf_sha256 = _file_sha256(pdf)
            marker = _apply_visible_incremental_edit(source, iteration)
            supervisor.run(
                f"build_{name}",
                "project_incremental_one_line",
                iteration,
                supervisor.command(fixture),
                project,
                env,
                require_pdf=True,
                required_artifacts=fixture.required_artifacts,
                required_changed_artifacts={
                    os.fspath(pdf.relative_to(project)): previous_pdf_sha256
                },
                notes=(
                    f"Inserted visible in-document marker {marker!r}; the expected "
                    "PDF must have a different content digest from the prior build."
                ),
            )


def _measure_failure_paths(
    supervisor: Supervisor,
    runtime_root: Path,
    package_map: Path,
    repeats: int,
) -> None:
    print("Measuring protected diagnostic paths", flush=True)
    env = supervisor.environment(runtime_root, package_map)
    for name in ("failure", "incomplete"):
        for iteration in range(1, repeats + 1):
            project = supervisor.workspace / "failure-projects" / name / str(iteration)
            fixture = write_fixture(name, project)
            sample = supervisor.run(
                f"diagnostic_{name}",
                "project_clean_runtime_provisioned",
                iteration,
                supervisor.command(fixture),
                project,
                env,
                expected_returncode="nonzero" if name == "failure" else 1,
                require_pdf=name == "incomplete",
                required_artifacts=("failure.log",) if name == "failure" else (),
                required_output=(
                    ("Build failed:", "See failure.log")
                    if name == "failure"
                    else (
                        "with missing document content",
                        "Auxiliary build files were retained for diagnosis.",
                    )
                ),
            )
        project = supervisor.workspace / "failure-projects" / name / "trace"
        fixture = write_fixture(name, project)
        supervisor.run(
            f"diagnostic_{name}",
            "project_clean_runtime_provisioned",
            repeats + 1,
            supervisor.command(fixture),
            project,
            env,
            expected_returncode="nonzero" if name == "failure" else 1,
            require_pdf=name == "incomplete",
            required_artifacts=("failure.log",) if name == "failure" else (),
            required_output=(
                ("Build failed:", "See failure.log")
                if name == "failure"
                else (
                    "with missing document content",
                    "Auxiliary build files were retained for diagnosis.",
                )
            ),
            instrumented=True,
        )


def _measure_raw_latexmk(
    supervisor: Supervisor,
    runtime_root: Path,
    repeats: int,
) -> None:
    project = supervisor.workspace / "competitor" / "raw-latexmk"
    fixture = write_fixture("simple", project)
    env = runtime.tinytex_env(runtime_root)
    latexmk = runtime.managed_tool(runtime_root, "latexmk")
    command = [
        latexmk,
        "-pdf",
        "-cd",
        "-interaction=nonstopmode",
        "-file-line-error",
        fixture.tex_file,
    ]
    subprocess.run(command, cwd=project, env=env, stdout=subprocess.DEVNULL, check=True)
    print("Measuring raw latexmk semantic-overlap reference", flush=True)
    for iteration in range(1, repeats + 1):
        supervisor.run(
            "competitor_raw_latexmk",
            "project_noop_fully_provisioned",
            iteration,
            command,
            project,
            env,
            require_pdf=True,
            notes=(
                "Overlapping no-op compile only: raw latexmk lacks texMini runtime, "
                "package recovery, diagnostics, and security semantics."
            ),
        )


def _measure_watch_once(
    supervisor: Supervisor,
    runtime_root: Path,
    package_map: Path,
    idle_seconds: float,
    iteration: int,
    *,
    instrumented: bool,
) -> dict[str, object]:
    label = "trace" if instrumented else str(iteration)
    project = supervisor.workspace / "watch" / label
    fixture = write_fixture("simple", project)
    env = supervisor.environment(runtime_root, package_map)
    setup = subprocess.run(
        supervisor.command(fixture),
        cwd=project,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if setup.returncode != 0:
        raise RuntimeError("Could not prepare watch no-op state")
    pdf = _fixture_pdf(project, fixture)
    expected_pdf_sha256 = _file_sha256(pdf)
    trace_path = supervisor.workspace / "traces" / f"watch-{label}.jsonl"
    request_path = supervisor.workspace / "worker" / f"watch-request-{label}.json"
    result_path = supervisor.workspace / "worker" / f"watch-result-{label}.json"
    log_path = supervisor.workspace / "logs" / f"watch-{label}.log"
    worker_env = dict(env)
    if instrumented:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        worker_env["TEXMINI_TRACE"] = os.fspath(trace_path)
    request = {
        "command": supervisor.command(fixture)[:-1]
        + ["--watch", supervisor.command(fixture)[-1]],
        "cwd": os.fspath(project),
        "source": fixture.tex_file,
        "pdf": os.fspath(pdf.relative_to(project)),
        "expected_pdf_sha256": expected_pdf_sha256,
        "output_path": os.fspath(log_path),
        "idle_seconds": idle_seconds,
        "timeout_seconds": max(120.0, idle_seconds + 90.0),
        **environment_request(worker_env),
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    worker = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.watch_worker",
            "--request",
            os.fspath(request_path),
            "--result",
            os.fspath(result_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": os.fspath(ROOT)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if worker.returncode != 0 or not result_path.is_file():
        raise RuntimeError(f"Watch measurement worker failed: {worker.stdout}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["log"] = (
        os.fspath(log_path.relative_to(supervisor.workspace))
        if supervisor.retain_artifacts
        else None
    )
    result["iteration"] = iteration
    result["instrumented"] = instrumented
    if instrumented:
        result["trace_summary"] = _trace_summary(trace_path)
    pdf_evidence = result.get("pdf_change_evidence", {})
    result["expected_returncode"] = 130
    result["semantic_assertions"] = {
        "handled_ctrl_c_returncode": result["returncode"] == 130,
        "pdf_changed_from_requested_noop_state": bool(
            isinstance(pdf_evidence, dict) and pdf_evidence.get("changed")
        ),
    }
    result["semantic_success"] = all(result["semantic_assertions"].values())
    result["notes"] = (
        "Fully provisioned no-op startup followed by one visible in-document "
        "source edit; the exact expected PDF must change content."
    )
    print(
        f"  watch{' trace' if instrumented else ''} #{iteration}: ready "
        f"{result['startup_to_ready_ns'] / 1_000_000:.1f} ms, change-to-build "
        f"{result['change_to_complete_ns'] / 1_000_000:.1f} ms",
        flush=True,
    )
    return result


def _metric_distribution(values: list[int | float]) -> dict[str, int | float]:
    median = statistics.median(values)
    return {
        "median": median,
        "mad": statistics.median(abs(value - median) for value in values),
        "min": min(values),
        "max": max(values),
    }


def summarize_watch_results(
    samples: list[dict[str, object]], attribution: dict[str, object]
) -> dict[str, object]:
    valid = [sample for sample in samples if sample.get("semantic_success")]
    if not valid:
        return {
            "schema_version": 2,
            "valid_samples": 0,
            "semantic_success": False,
            "samples": samples,
        }

    def distribution(*path: str) -> dict[str, int | float]:
        values: list[int | float] = []
        for sample in valid:
            value: object = sample
            for key in path:
                value = value[key]  # type: ignore[index]
            values.append(value)  # type: ignore[arg-type]
        return _metric_distribution(values)

    startup = distribution("startup_to_ready_ns")
    idle_wall = distribution("idle", "wall_time_ns")
    idle_cpu = distribution("idle", "tree_cpu_time_ns")
    idle_fraction = distribution("idle", "cpu_fraction_one_core")
    idle_rss = distribution("idle", "peak_tree_rss_bytes")
    detection = distribution("change_to_detection_ns")
    rebuild = distribution("detection_to_complete_ns")
    complete = distribution("change_to_complete_ns")
    return {
        "schema_version": 2,
        "valid_samples": len(valid),
        "returncodes": [sample["returncode"] for sample in samples],
        "startup_to_ready_ns": startup["median"],
        "idle": {
            "wall_time_ns": idle_wall["median"],
            "tree_cpu_time_ns": idle_cpu["median"],
            "cpu_fraction_one_core": idle_fraction["median"],
            "peak_tree_rss_bytes": idle_rss["median"],
            "sample_interval_seconds": valid[0]["idle"]["sample_interval_seconds"],  # type: ignore[index]
        },
        "change_to_detection_ns": detection["median"],
        "detection_to_complete_ns": rebuild["median"],
        "change_to_complete_ns": complete["median"],
        "dispersion": {
            "startup_to_ready_ns": startup,
            "idle_wall_time_ns": idle_wall,
            "idle_tree_cpu_time_ns": idle_cpu,
            "idle_cpu_fraction_one_core": idle_fraction,
            "idle_peak_tree_rss_bytes": idle_rss,
            "change_to_detection_ns": detection,
            "detection_to_complete_ns": rebuild,
            "change_to_complete_ns": complete,
        },
        "trace_summary": attribution.get("trace_summary", {"events": 0}),
        "semantic_success": len(valid) == len(samples)
        and bool(attribution.get("semantic_success")),
        "notes": (
            "Medians exclude the separate attribution-only trace. Each trial starts "
            "from an independently prepared fully provisioned no-op project."
        ),
        "samples": samples,
    }


def _measure_watch(
    supervisor: Supervisor,
    runtime_root: Path,
    package_map: Path,
    idle_seconds: float,
    repeats: int,
) -> dict[str, object]:
    print("Measuring watch startup, idle resources, and rebuild latency", flush=True)
    samples = [
        _measure_watch_once(
            supervisor,
            runtime_root,
            package_map,
            idle_seconds,
            iteration,
            instrumented=False,
        )
        for iteration in range(1, repeats + 1)
    ]
    attribution = _measure_watch_once(
        supervisor,
        runtime_root,
        package_map,
        idle_seconds,
        repeats + 1,
        instrumented=True,
    )
    return summarize_watch_results(samples, attribution)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure explicit texMini user and runtime states reproducibly."
    )
    parser.add_argument(
        "--suite",
        choices=("startup", "core", "full"),
        default="core",
        help="startup avoids TeX; core adds simple/recovery/diagnostics; full adds specialty workflows",
    )
    parser.add_argument("--candidate-id", default="current-python")
    parser.add_argument("--target-root", type=Path, default=ROOT)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--startup-repeats", type=int, default=20)
    parser.add_argument("--package-repeats", type=int, default=1)
    parser.add_argument("--watch-idle-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument(
        "--runtime-template",
        type=Path,
        help="clone a pre-provisioned base runtime instead of downloading an archive",
    )
    parser.add_argument("--skip-packaging", action="store_true")
    parser.add_argument("--skip-package-recovery", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats < 1 or args.startup_repeats < 1 or args.package_repeats < 1:
        raise SystemExit("repeat counts must be positive")
    target_root = args.target_root.resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or (
        ROOT
        / "benchmarks"
        / "results"
        / f"{timestamp}-{args.candidate_id}-{platform.machine()}.json"
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    if args.workspace is None:
        temporary = tempfile.TemporaryDirectory(prefix="texmini-benchmark-")
        workspace = Path(temporary.name)
    else:
        workspace = _prepare_explicit_workspace(args.workspace)
    raw_path = output.with_name(
        f"{output.stem}.{timestamp}.{os.getpid()}.raw.jsonl"
    )
    retained_workspace: Path | None = None
    if args.keep_workspace:
        retained_workspace = (
            workspace
            if args.workspace is not None
            else output.with_name(
                f"{output.stem}.{timestamp}.{os.getpid()}.workspace"
            )
        )
    retention_attempted = retained_workspace == workspace
    published = False
    supervisor = Supervisor(
        target_root,
        workspace,
        raw_path,
        args.candidate_id,
        retain_artifacts=args.keep_workspace,
    )

    starting_git = _git_metadata(target_root)
    same_harness_and_target = target_root == ROOT.resolve()
    starting_harness_git = (
        starting_git if same_harness_and_target else _git_metadata(ROOT)
    )
    candidate_manifest = _candidate_runtime_manifest(target_root)
    metadata: dict[str, object] = {
        "schema_version": 3,
        "timestamp_utc": timestamp,
        "candidate_id": args.candidate_id,
        "texmini_version": _candidate_version(target_root),
        "harness_version": __version__,
        "target_root": os.fspath(target_root),
        "retained_workspace": (
            os.fspath(retained_workspace) if retained_workspace else None
        ),
        "git": starting_git,
        "harness_git": starting_harness_git,
        "host": _host_metadata(workspace),
        "runtime_manifest": candidate_manifest,
        "measurement_policy": {
            "os_page_cache": "uncontrolled",
            "network": "uncontrolled; network-dependent samples are observational",
            "worker": "fresh one-shot process per authoritative trial",
            "wall_clock": "time.perf_counter_ns in worker",
            "resources": "resource.RUSAGE_CHILDREN on POSIX; unavailable otherwise",
            "filesystem_operations": "trace counters only; no portable syscall total",
            "instrumented_samples_excluded_from_summaries": True,
        },
        "configuration": {
            "argv": sys.argv,
            "suite": args.suite,
            "repeats": args.repeats,
            "startup_repeats": args.startup_repeats,
            "package_repeats": args.package_repeats,
            "watch_repeats": max(3, min(args.repeats, 7)),
            "watch_idle_seconds": args.watch_idle_seconds,
            "skip_packaging": args.skip_packaging,
            "skip_package_recovery": args.skip_package_recovery,
            "keep_workspace": args.keep_workspace,
            "runtime_template": (
                os.fspath(args.runtime_template.resolve())
                if args.runtime_template
                else None
            ),
        },
    }
    footprints: dict[str, object] = {}
    watch_result: dict[str, object] | None = None
    try:
        bootstrap_root = workspace / "runtime-base"
        package_map = workspace / "shared-package-map.json"
        if args.runtime_template:
            clone_backend = _clone_tree(args.runtime_template.resolve(), bootstrap_root)
            metadata["base_runtime_origin"] = {
                "state": "provided_template",
                "clone_backend": clone_backend,
            }
        elif args.suite != "startup":
            project = workspace / "empty-runtime-project"
            fixture = write_fixture("simple", project)
            print("Measuring first build from an empty runtime", flush=True)
            sample = supervisor.run(
                "first_build_simple",
                "runtime_empty_map_empty_project_clean",
                1,
                supervisor.command(fixture),
                project,
                supervisor.environment(bootstrap_root, package_map),
                require_pdf=True,
                network_dependency="TinyTeX release artifact and TeX Live repository",
                notes=(
                    "Authoritative user-visible observation with an initially empty "
                    "managed runtime; network and CDN state are uncontrolled."
                ),
            )
            trace_root = workspace / "runtime-empty-attribution"
            trace_map = workspace / "package-map-attribution.json"
            trace_project = workspace / "empty-runtime-attribution-project"
            trace_fixture = write_fixture("simple", trace_project)
            supervisor.run(
                "first_build_simple",
                "runtime_empty_map_empty_project_clean",
                2,
                supervisor.command(trace_fixture),
                trace_project,
                supervisor.environment(trace_root, trace_map),
                require_pdf=True,
                instrumented=True,
                network_dependency="TinyTeX release artifact and TeX Live repository",
                notes=(
                    "Attribution-only observation excluded from the timing summary; "
                    "response-body bytes are observed, while network state remains "
                    "uncontrolled."
                ),
            )
            shutil.rmtree(trace_root, ignore_errors=True)
            metadata["base_runtime_origin"] = {
                "state": "created_by_first_build",
                "sample_semantic_success": sample["semantic_success"],
            }
        else:
            bootstrap_root.mkdir(parents=True)
            metadata["base_runtime_origin"] = {"state": "not_required"}

        _measure_startup(
            supervisor, bootstrap_root, package_map, args.startup_repeats
        )
        if not args.skip_packaging:
            footprints["packaging"] = _measure_packaging(
                supervisor,
                bootstrap_root,
                package_map,
                max(3, min(args.startup_repeats, 10)),
            )

        if args.suite != "startup":
            if not args.skip_package_recovery:
                _measure_package_recovery(
                    supervisor, bootstrap_root, args.package_repeats
                )
            provisioned_root = workspace / "runtime-provisioned"
            _clone_tree(bootstrap_root, provisioned_root)
            functional = (
                DEFAULT_FUNCTIONAL_FIXTURES if args.suite == "full" else ["simple"]
            )
            _provision_functional_runtime(
                supervisor, provisioned_root, package_map, functional
            )
            _measure_build_states(
                supervisor,
                provisioned_root,
                package_map,
                args.repeats,
                functional,
            )
            _measure_failure_paths(
                supervisor,
                provisioned_root,
                package_map,
                max(3, min(args.repeats, 7)),
            )
            watch_result = _measure_watch(
                supervisor,
                provisioned_root,
                package_map,
                args.watch_idle_seconds,
                max(3, min(args.repeats, 7)),
            )
            metadata["watch"] = watch_result
            _measure_raw_latexmk(supervisor, provisioned_root, args.repeats)
            footprints["base_runtime"] = {
                **directory_sizes(bootstrap_root),
                "content_identity": directory_content_identity(bootstrap_root),
                "package_inventory": runtime_package_inventory(bootstrap_root),
            }
            footprints["fully_provisioned_runtime"] = {
                **directory_sizes(provisioned_root),
                "content_identity": directory_content_identity(provisioned_root),
                "package_inventory": runtime_package_inventory(provisioned_root),
            }

        ending_git = _git_metadata(target_root)
        ending_harness_git = (
            ending_git if same_harness_and_target else _git_metadata(ROOT)
        )
        if (
            ending_git["tree_content_sha256"]
            != starting_git["tree_content_sha256"]
        ):
            raise RuntimeError(
                "Candidate inputs changed during measurement; refusing to publish "
                "mixed-state benchmark results."
            )
        if (
            ending_harness_git["tree_content_sha256"]
            != starting_harness_git["tree_content_sha256"]
        ):
            raise RuntimeError(
                "Benchmark harness inputs changed during measurement; refusing "
                "to publish mixed-harness results."
            )
        starting_git["ending_tree_content_sha256"] = ending_git[
            "tree_content_sha256"
        ]
        starting_git["stable_during_run"] = True
        starting_harness_git["ending_tree_content_sha256"] = ending_harness_git[
            "tree_content_sha256"
        ]
        starting_harness_git["stable_during_run"] = True
        results = {
            **metadata,
            "footprints": footprints,
            "samples": supervisor.samples,
            "summary": _scenario_summary(supervisor.samples),
            "raw_samples": raw_path.name,
            "raw_samples_bytes": raw_path.stat().st_size,
            "raw_samples_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        }
        if retained_workspace is not None:
            retention_attempted = True
            if retained_workspace != workspace:
                shutil.copytree(workspace, retained_workspace)
            print(f"Retained workspace at {retained_workspace}", flush=True)
        publish_result_pair(output, raw_path, results)
        published = True
    finally:
        if retained_workspace is not None and not retention_attempted:
            retention_attempted = True
            shutil.copytree(workspace, retained_workspace)
            print(f"Retained workspace at {retained_workspace}", flush=True)
        if temporary is not None:
            temporary.cleanup()
        if not published:
            raw_path.unlink(missing_ok=True)

    failures = [sample for sample in supervisor.samples if not sample["semantic_success"]]
    if watch_result is not None and not watch_result.get("semantic_success"):
        failures.append(watch_result)
    print(f"Wrote {output}", flush=True)
    print(f"Wrote {raw_path}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
