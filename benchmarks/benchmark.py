from __future__ import annotations

import argparse
import json
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from texmini import __version__
from texmini import runtime


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ["simple", "common", "random-packages", "bibliography"]
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
GENERATED_EXTENSIONS = [
    "aux",
    "bbl",
    "bcf",
    "blg",
    "fdb_latexmk",
    "fls",
    "log",
    "out",
    "pdf",
    "run.xml",
    "toc",
]
INSTALL_SIZE_PATTERN = re.compile(r"install: .*? \[(\d+)([kKmM]?)\]")


def sample_poisson(rng: random.Random, mean: float) -> int:
    threshold = 2.718281828459045**-mean
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def sample_overdispersed_count(rng: random.Random, mean: float, dispersion: float) -> int:
    return sample_poisson(rng, rng.gammavariate(dispersion, mean / dispersion))


def random_package_selection(seed: int = 20260714, count: int = 10) -> list[str]:
    return random.Random(seed).sample(PACKAGE_POOL, count)


def bibliography_entry_count(seed: int = 20260714) -> int:
    return max(8, sample_overdispersed_count(random.Random(seed), mean=32.0, dispersion=3.0))


def write_fixture(name: str, destination: Path) -> str:
    destination.mkdir(parents=True, exist_ok=True)
    tex_file = destination / f"{name}.tex"

    if name == "simple":
        shutil.copy2(ROOT / "tests" / "fixtures" / "simple" / "simple.tex", tex_file)
        return tex_file.name

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
        return tex_file.name

    if name == "random-packages":
        packages = ",".join(random_package_selection())
        tex_file.write_text(
            f"""\\documentclass{{article}}
\\usepackage{{{packages}}}
\\begin{{document}}
The package sample is selected once from a fixed seed so repeated benchmark runs are comparable.
\\end{{document}}
""",
            encoding="utf-8",
        )
        return tex_file.name

    if name == "bibliography":
        count = bibliography_entry_count()
        keys = [f"entry{i:03d}" for i in range(count)]
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
        citations = "\n".join(f"Citation {index + 1}: \\cite{{{key}}}." for index, key in enumerate(keys))
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
        return tex_file.name

    raise ValueError(f"Unknown fixture: {name}")


def directory_size(path: Path, allocated: bool = False) -> int:
    if not path.exists():
        return 0
    stats = []
    seen_inodes: set[tuple[int, int]] = set()
    for entry in path.rglob("*"):
        if not entry.is_file():
            continue
        stat = entry.stat()
        inode = (stat.st_dev, stat.st_ino)
        if inode in seen_inodes:
            continue
        seen_inodes.add(inode)
        stats.append(stat)
    if allocated:
        return sum(stat.st_blocks * 512 for stat in stats)
    return sum(stat.st_size for stat in stats)


def clean_generated_files(directory: Path, stem: str) -> None:
    for extension in GENERATED_EXTENSIONS:
        path = directory / f"{stem}.{extension}"
        if path.exists():
            path.unlink()


def parsed_install_payload(output: str) -> int:
    total = 0
    for amount, unit in INSTALL_SIZE_PATTERN.findall(output):
        multiplier = 1024 * 1024 if unit.lower() == "m" else 1024
        total += int(amount) * multiplier
    return total


def tinytex_asset() -> tuple[str, int]:
    prefix = f"{runtime.TINYTEX_BUNDLE}-{runtime.tinytex_platform_key()}-"
    with urllib.request.urlopen(runtime.TINYTEX_RELEASE_API, timeout=30) as response:
        release = json.load(response)
    for asset in release["assets"]:
        if asset["name"].startswith(prefix) and asset["name"].endswith(".tar.xz"):
            return asset["name"], int(asset["size"])
    raise RuntimeError(
        f"No release asset found for {runtime.TINYTEX_BUNDLE} and "
        f"{runtime.tinytex_platform_key()}"
    )


def run_compile(command: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> dict[str, object]:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    log_path.write_text(result.stdout, encoding="utf-8")
    return {
        "elapsed_seconds": round(elapsed, 3),
        "returncode": result.returncode,
        "install_payload_bytes": parsed_install_payload(result.stdout),
        "log": log_path.name,
        "failure_tail": result.stdout.splitlines()[-20:] if result.returncode else [],
    }


def benchmark_runtime(fixtures: list[str], repeats: int, workspace: Path) -> dict[str, object]:
    runtime_root = workspace / "TinyTeX"
    package_map = workspace / "package-map.json"
    logs = workspace / "logs"
    logs.mkdir(parents=True)
    asset_name, archive_bytes = tinytex_asset()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "TEXMINI_PACKAGE_MAP": str(package_map),
        "TEXMINI_TINYTEX_ROOT": str(runtime_root),
    }
    command_prefix = [sys.executable, "-m", "texmini.cli"]
    cases: list[dict[str, object]] = []

    for fixture in fixtures:
        fixture_dir = workspace / "fixtures" / fixture
        tex_name = write_fixture(fixture, fixture_dir)
        stem = Path(tex_name).stem
        logical_before = directory_size(runtime_root)
        allocated_before = directory_size(runtime_root, allocated=True)
        cold = run_compile(command_prefix + [tex_name], fixture_dir, env, logs / f"{fixture}-cold.log")
        logical_after = directory_size(runtime_root)
        allocated_after = directory_size(runtime_root, allocated=True)
        pdf_path = fixture_dir / f"{stem}.pdf"
        warm_runs: list[dict[str, object]] = []

        if cold["returncode"] == 0 and pdf_path.is_file():
            for repeat in range(repeats):
                clean_generated_files(fixture_dir, stem)
                warm_runs.append(
                    run_compile(
                        command_prefix + [tex_name],
                        fixture_dir,
                        env,
                        logs / f"{fixture}-warm-{repeat + 1}.log",
                    )
                )

        warm_times = [float(run["elapsed_seconds"]) for run in warm_runs if run["returncode"] == 0]
        cases.append(
            {
                "fixture": fixture,
                "cold": cold,
                "warm_runs": warm_runs,
                "warm_median_seconds": round(statistics.median(warm_times), 3) if warm_times else None,
                "runtime_logical_bytes_before": logical_before,
                "runtime_logical_bytes_after": logical_after,
                "runtime_logical_growth_bytes": logical_after - logical_before,
                "runtime_allocated_bytes_before": allocated_before,
                "runtime_allocated_bytes_after": allocated_after,
                "runtime_allocated_growth_bytes": allocated_after - allocated_before,
                "pdf_bytes": pdf_path.stat().st_size if pdf_path.is_file() else None,
            }
        )

    return {
        "bundle": runtime.TINYTEX_BUNDLE,
        "asset": asset_name,
        "archive_bytes": archive_bytes,
        "final_runtime_logical_bytes": directory_size(runtime_root),
        "final_runtime_allocated_bytes": directory_size(runtime_root, allocated=True),
        "cases": cases,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark isolated texMini managed runtimes.")
    parser.add_argument("--fixtures", nargs="+", default=DEFAULT_FIXTURES)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keep-workspaces", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or ROOT / "benchmarks" / "results" / f"{timestamp}-{platform.machine()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="texmini-benchmark-")
    workspace_root = Path(temporary.name)
    results = {
        "schema_version": 2,
        "timestamp_utc": timestamp,
        "texmini_version": __version__,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "fixtures": args.fixtures,
        "warm_repeats": args.repeats,
        "baseline": None,
    }

    try:
        print(f"Benchmarking {runtime.TINYTEX_BUNDLE}", flush=True)
        results["baseline"] = benchmark_runtime(
            args.fixtures, args.repeats, workspace_root / runtime.TINYTEX_BUNDLE
        )
        output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    finally:
        if args.keep_workspaces:
            retained = output.with_suffix("")
            shutil.copytree(workspace_root, retained, dirs_exist_ok=True)
            print(f"Retained workspaces at {retained}")
        temporary.cleanup()

    print(f"Wrote {output}")
    baseline = results["baseline"]
    assert isinstance(baseline, dict)
    return 0 if all(case["cold"]["returncode"] == 0 for case in baseline["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
